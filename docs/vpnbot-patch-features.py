#!/usr/bin/env python3
"""LitEnergy-функции для vpnbot: рефералка, «Моя подписка» + QR, справка, меню команд.
Версия 2026-10-07.1

Что ставит:
  * app/services/referral.py        — учёт приглашений (+1 день пригласившему за друга)
  * app/telegram/referral_extra.py  — обработчики /ref, /vpn, /help, QR, меню команд
  * врезку в основной файл бота (там, где создаётся Dispatcher) — подключение модуля
  * настройки: REFERRAL_BONUS_DAYS=1 (.env, config.py)
  * segno в requirements.txt (генерация QR без картинок-зависимостей)

Идемпотентно, делает бэкап, проверяет синтаксис.

Запуск:  python3 /root/vpnbot-patch-features.py
Дальше:  docker compose up -d --build
"""
from __future__ import annotations

import os
import py_compile
import re
import shutil
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "patch-features 2026-10-07.1"
MARKER = "referral_extra"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

REFERRAL_SERVICE = '''"""Реферальная программа: +N дней за приглашённого друга."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import get_session

log = logging.getLogger("app.referral")


async def ensure_table() -> None:
    """Создаёт таблицу приглашений (если её нет)."""
    async with get_session() as session:
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS referrals ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "new_user_id INTEGER NOT NULL UNIQUE, "
                "referrer_id INTEGER NOT NULL, "
                "days INTEGER NOT NULL DEFAULT 1, "
                "created_at TEXT NOT NULL)"
            )
        )
        await session.commit()


async def _known_user(telegram_id: int) -> bool:
    async with get_session() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM users WHERE telegram_id = :tid LIMIT 1"),
                {"tid": int(telegram_id)},
            )
        ).scalar_one_or_none()
    return row is not None


async def _panel_id(telegram_id: int) -> str | None:
    async with get_session() as session:
        row = (
            await session.execute(
                text("SELECT remnawave_user_id FROM users WHERE telegram_id = :tid LIMIT 1"),
                {"tid": int(telegram_id)},
            )
        ).scalar_one_or_none()
    if row:
        return str(row)
    try:
        from app.services.remnawave import get_remna

        found = await get_remna().find_user_by_telegram_id(int(telegram_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("referral: не найти пользователя в панели (%s)", exc)
        return None
    return str(found["id"]) if found and found.get("id") else None


async def grant_days(telegram_id: int, days: int) -> tuple[bool, str]:
    """Добавляет дни к подписке пригласившего."""
    try:
        panel = await _panel_id(telegram_id)
        if not panel:
            return False, "нет подписки в панели"
        from app.services.remnawave import get_remna

        await get_remna().extend_user(panel, int(days))
        return True, "дни добавлены"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def register(referrer_id: int, new_user_id: int, days: int) -> str:
    """Регистрирует приглашение и начисляет дни.

    Коды: ok | pending | self | known | duplicate
    """
    if int(referrer_id) == int(new_user_id):
        return "self"
    await ensure_table()
    if await _known_user(new_user_id):
        return "known"
    try:
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO referrals (new_user_id, referrer_id, days, created_at) "
                    "VALUES (:new, :ref, :days, :at)"
                ),
                {
                    "new": int(new_user_id),
                    "ref": int(referrer_id),
                    "days": int(days),
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.info("referral: приглашение не записано (%s)", exc)
        return "duplicate"

    granted, reason = await grant_days(referrer_id, days)
    if not granted:
        log.warning("referral: дни не начислены %s (%s)", referrer_id, reason)
        try:
            from app.services.notifications import notify_admin

            await notify_admin(
                "🎁 <b>Реферальный бонус не начислен</b>\\n"
                f"Пригласивший: <code>{referrer_id}</code>\\n"
                f"Причина: {reason}\\n"
                "Начислите вручную: панель → пользователь → +дни."
            )
        except Exception:  # noqa: BLE001
            pass
        return "pending"
    return "ok"


async def stats(telegram_id: int) -> tuple[int, int]:
    """(сколько друзей пришло, сколько дней получено)."""
    await ensure_table()
    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), COALESCE(SUM(days), 0) FROM referrals "
                    "WHERE referrer_id = :rid"
                ),
                {"rid": int(telegram_id)},
            )
        ).one()
    return int(row[0] or 0), int(row[1] or 0)
'''

EXTRA_MODULE = '''"""LitEnergy: рефералка, карточка «Моя подписка», справка и QR."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO

from aiogram import BaseMiddleware, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

log = logging.getLogger("app.extras")

router = Router(name="litenergy-extras")

COMMANDS = [
    ("vpn", "📱 Моя подписка"),
    ("ref", "🎁 Пригласить друга (+день)"),
    ("help", "📖 Как подключиться"),
]

_commands_done = False


def bonus_days() -> int:
    try:
        from app.config import get_settings

        return max(1, int(getattr(get_settings(), "referral_bonus_days", 1) or 1))
    except Exception:  # noqa: BLE001
        return 1


async def _maybe_set_commands(bot) -> None:
    global _commands_done
    if _commands_done:
        return
    try:
        from aiogram.types import BotCommand

        await bot.set_my_commands(
            [BotCommand(command=name, description=desc) for name, desc in COMMANDS]
        )
        _commands_done = True
    except Exception as exc:  # noqa: BLE001
        log.debug("список команд не обновлён: %s", exc)


async def _user_row(telegram_id: int):
    from sqlalchemy import text

    from app.database import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT subscription_url, expire_at, status FROM users "
                    "WHERE telegram_id = :tid LIMIT 1"
                ),
                {"tid": int(telegram_id)},
            )
        ).first()
    return row


def _parse_dt(value):
    if value is None:
        return None
    text_value = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _qr_png(url: str) -> bytes | None:
    try:
        import segno

        buf = BytesIO()
        segno.make(url).save(buf, kind="png", scale=6, border=2)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


async def _panel_info(telegram_id: int):
    try:
        from app.services.remnawave import get_remna

        remna = get_remna()
        user = await remna.find_user_by_telegram_id(int(telegram_id))
        if user and user.get("id"):
            return await remna.get_user(str(user["id"]))
        return user
    except Exception:  # noqa: BLE001
        return None


class ReferralMiddleware(BaseMiddleware):
    """Ловит переход по ссылке-приглашению (/start ref_<id>) до основного обработчика."""

    async def __call__(self, handler, event, data):
        try:
            await self._process(event, data)
        except Exception as exc:  # noqa: BLE001
            log.warning("referral: %s", exc)
        return await handler(event, data)

    async def _process(self, event, data) -> None:
        bot = data.get("bot")
        if bot is not None:
            await _maybe_set_commands(bot)
        if not isinstance(event, Message) or not event.text:
            return
        parts = event.text.strip().split(maxsplit=1)
        if not parts or not parts[0].startswith("/start"):
            return
        if len(parts) < 2 or not parts[1].startswith("ref_"):
            return
        if event.from_user is None:
            return
        raw = parts[1][len("ref_"):].strip().split()[0]
        if not raw.isdigit():
            return
        referrer_id = int(raw)
        new_user_id = event.from_user.id

        from app.services import referral as referral_service

        days = bonus_days()
        code = await referral_service.register(referrer_id, new_user_id, days)
        log.info("referral: %s -> %s: %s", new_user_id, referrer_id, code)
        if bot is None or code not in ("ok", "pending"):
            return
        try:
            if code == "ok":
                text = (
                    "🎉 <b>Друг присоединился по вашей ссылке</b>\\n\\n"
                    f"Вам начислено <b>+{days} дн.</b> к подписке.\\n"
                    "Приглашайте ещё — каждый друг добавляет дни."
                )
            else:
                text = (
                    "🎉 <b>Друг присоединился по вашей ссылке</b>\\n\\n"
                    "Бонус не начислен: у вас нет активной подписки.\\n"
                    "Оформите подписку — и приглашайте дальше."
                )
            await bot.send_message(referrer_id, text)
        except Exception as exc:  # noqa: BLE001
            log.debug("referral: не смог уведомить %s (%s)", referrer_id, exc)


@router.message(Command("vpn", "me", "subscription"))
async def cmd_my_subscription(message: Message) -> None:
    if message.from_user is None:
        return
    tid = message.from_user.id
    row = None
    try:
        row = await _user_row(tid)
    except Exception as exc:  # noqa: BLE001
        log.warning("моя подписка: база недоступна (%s)", exc)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Продлить / тарифы", callback_data="menu:shop")],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/wixyezz")],
        ]
    )

    url = str(row[0]) if row and row[0] else None
    expire = _parse_dt(row[1]) if row and row[1] else None
    lines = ["📱 <b>Моя подписка</b>", ""]
    if not url:
        lines += [
            "Подписка не найдена.",
            "",
            "Оформите в магазине — от 50 ₽, или возьмите 🎁 тест на 1 день.",
        ]
        await message.answer("\\n".join(lines), reply_markup=kb, disable_web_page_preview=True)
        return

    now = datetime.now(timezone.utc)
    days_left = (expire - now).days if expire else None
    state = "активна" if (days_left is not None and days_left >= 0) else "закончилась"
    lines.append(f"Статус: <b>{state}</b>")
    if days_left is not None:
        lines.append(f"Осталось: <b>{max(days_left, 0)} дн.</b> (до {expire.strftime('%d.%m.%Y')})")

    panel = await _panel_info(tid)
    if isinstance(panel, dict):
        limit = panel.get("hwidDeviceLimit")
        if limit is not None:
            lines.append(f"Устройств можно подключить: <b>{limit}</b>")
        used = panel.get("trafficUsedBytes") or panel.get("usedTrafficBytes")
        total = panel.get("trafficLimitBytes")
        if used is not None:
            try:
                gb_used = int(used) / (1024 ** 3)
                if total:
                    gb_total = int(total) / (1024 ** 3)
                    lines.append(f"Трафик: <b>{gb_used:.1f}</b> из {gb_total:.0f} ГБ")
                else:
                    lines.append(f"Трафик: <b>{gb_used:.1f}</b> ГБ (без лимита)")
            except Exception:  # noqa: BLE001
                pass

    lines += [
        "",
        "Ссылка для подключения (вставьте в приложение):",
        f"<code>{url}</code>",
        "",
        "Приложения: Happ, v2rayTun, Hiddify. Подробнее — /help",
    ]
    text = "\\n".join(lines)

    png = _qr_png(url)
    if png:
        try:
            await message.answer_photo(
                BufferedInputFile(png, filename="litenergyvpn-qr.png"),
                caption=text,
                reply_markup=kb,
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.debug("QR не отправился (%s)", exc)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(Command("ref", "referral", "friends"))
async def cmd_referral(message: Message) -> None:
    if message.from_user is None or message.bot is None:
        return
    tid = message.from_user.id
    days = bonus_days()
    count, earned = 0, 0
    try:
        from app.services import referral as referral_service

        count, earned = await referral_service.stats(tid)
    except Exception as exc:  # noqa: BLE001
        log.warning("рефералка: статистика недоступна (%s)", exc)

    link = None
    try:
        me = await message.bot.get_me()
        if me.username:
            link = f"https://t.me/{me.username}?start=ref_{tid}"
    except Exception as exc:  # noqa: BLE001
        log.debug("рефералка: не получил username бота (%s)", exc)

    text = (
        "🎁 <b>Пригласите друга — получите дни VPN</b>\\n\\n"
        f"За каждого друга, который зайдёт по вашей ссылке: <b>+{days} дн.</b>\\n\\n"
        f"Приглашено друзей: <b>{count}</b>\\n"
        f"Получено дней: <b>{earned}</b>\\n"
    )
    if link:
        text += f"\\nВаша ссылка:\\n<code>{link}</code>\\n\\nПросто отправьте её другу."
    await message.answer(text, disable_web_page_preview=True)


HELP_TEXT = """📖 <b>Как подключиться</b>

<b>1.</b> Установите приложение:
• <a href="https://apps.apple.com/app/id6479371157">Happ</a> (iPhone) / <a href="https://play.google.com/store/apps/details?id=com.happproxy">Happ</a> (Android)
• <a href="https://v2raytun.com">v2rayTun</a> — iOS / Android
• <a href="https://hiddify.com">Hiddify</a> — все платформы

<b>2.</b> Получите свою ссылку: команда /vpn (там же QR-код).

<b>3.</b> В приложении: «Добавить подписку» → вставить ссылку → подключиться.
Обновление подписки происходит автоматически.

<b>Полезно:</b>
• 📱 /vpn — статус, срок, устройства, ссылка и QR
• 🎁 /ref — пригласить друга и получить +дни
• 🆘 Поддержка: @wixyezz

Если VPN не подключается: проверьте интернет, выберите другую локацию в приложении, обновите подписку (потяните список вниз) и попробуйте ещё раз."""


@router.message(Command("help", "how"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, disable_web_page_preview=True)


def install(dp) -> None:
    """Подключает модуль к диспетчеру бота."""
    middleware = ReferralMiddleware()
    try:
        dp.message.outer_middleware(middleware)
    except AttributeError:
        dp.message.middleware(middleware)
    dp.include_router(router)
    log.info("LitEnergy extras подключены: /vpn, /ref, /help, реферальные ссылки")


__all__ = ["install", "router"]
'''


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(path.name + f"-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def find_dispatcher_target() -> tuple[Path | None, str, list[str]]:
    """Ищем файл с созданием Dispatcher и имя переменной."""
    notes: list[str] = []
    candidates: list[Path] = []
    for path in sorted(APP.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "Dispatcher(" in text:
            candidates.append(path)
    if not candidates:
        return None, "dp", ["не нашёл файл, где создаётся Dispatcher"]
    # приоритет: файл с start_polling
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "start_polling" in text:
            return path, "", []
    return candidates[0], "", []


def insert_install(text: str, var: str) -> tuple[str | None, str]:
    if MARKER in text:
        return text, "уже подключено ранее"
    lines = text.splitlines(keepends=True)
    # 1) ищем создание диспетчера
    pattern = re.compile(r"^(\s*)(\w+)\s*=\s*Dispatcher\(")
    for idx, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        name = match.group(2)
        depth = line.count("(") - line.count(")")
        end = idx
        while depth > 0 and end + 1 < len(lines):
            end += 1
            depth += lines[end].count("(") - lines[end].count(")")
        indent = match.group(1)
        block_lines = [
            "",
            "# --- LitEnergy extras: рефералка, моя подписка, справка ---",
            "try:",
            "    from app.telegram import referral_extra as _litenergy_extras",
            f"    _litenergy_extras.install({name})",
            "except Exception as _litenergy_exc:  # noqa: BLE001",
            "    import logging as _litenergy_logging",
            "    _litenergy_logging.getLogger(\"app\").warning(",
            "        \"LitEnergy extras не подключены: %s\", _litenergy_exc",
            "    )",
            "",
        ]
        block = "".join((indent + line + "\n") if line else "\n" for line in block_lines)
        return "".join(lines[: end + 1]) + block + "".join(lines[end + 1:]), f"врезка после создания Dispatcher (переменная {name})"
    # 2) запасной вариант: перед start_polling
    for idx, line in enumerate(lines):
        if "start_polling" not in line:
            continue
        match = re.search(r"(\w+)\.start_polling", line)
        name = match.group(1) if match else "dp"
        indent = re.match(r"(\s*)", line).group(1)
        block = (
            f"{indent}# --- LitEnergy extras ---\n"
            f"{indent}try:\n"
            f"{indent}    from app.telegram import referral_extra as _litenergy_extras\n"
            f"{indent}    _litenergy_extras.install({name})\n"
            f"{indent}except Exception as _litenergy_exc:  # noqa: BLE001\n"
            f"{indent}    import logging as _litenergy_logging\n"
            f"{indent}    _litenergy_logging.getLogger(\"app\").warning(\n"
            f"{indent}        \"LitEnergy extras не подключены: %s\", _litenergy_exc\n"
            f"{indent}    )\n"
        )
        return "".join(lines[:idx]) + block + "".join(lines[idx:]), "врезка перед start_polling"
    return None, "не нашёл ни создания Dispatcher, ни start_polling"


def patch_config(text: str) -> tuple[str | None, list[str]]:
    if "referral_bonus_days" in text:
        return text, []
    match = re.search(r"^(\s*)# ---- База данных ----$", text, re.M)
    if match is None:
        return None, ["config.py: не найден раздел '---- База данных ----'"]
    indent = match.group(1)
    block = (
        f"{indent}# ---- Реферальная программа ----\n"
        f"{indent}referral_bonus_days: int = 1\n\n"
    )
    return text[: match.start()] + block + text[match.start():], ["config.py: referral_bonus_days"]


def update_env() -> list[str]:
    if not ENV.exists():
        return [".env: нет файла — пропущено"]
    shutil.copy2(ENV, unique_path(Path(str(ENV) + ".bak." + STAMP)))
    lines = ENV.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen = False
    for line in lines:
        if line.startswith("REFERRAL_BONUS_DAYS="):
            if seen:
                continue
            seen = True
            out.append("REFERRAL_BONUS_DAYS=1")
        else:
            out.append(line)
    if not seen:
        out.append("REFERRAL_BONUS_DAYS=1")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    return [".env: REFERRAL_BONUS_DAYS=1"]


def update_requirements() -> list[str]:
    path = ROOT / "requirements.txt"
    if not path.exists():
        return ["requirements.txt: нет файла — segno не добавлен (QR будет ссылкой)"]
    text = path.read_text(encoding="utf-8")
    if "segno" in text:
        return []
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "segno>=1.6\n", encoding="utf-8")
    return ["requirements.txt: добавлен segno (QR-код без картинок-зависимостей)"]


def main() -> int:
    print(f"{SCRIPT_VERSION} | корень бота: {ROOT}")
    if not APP.is_dir():
        print(f"!! нет каталога {APP}")
        return 1

    main_file, _var, notes_main = find_dispatcher_target()
    if main_file is None:
        print("!! не нашёл, где создаётся Dispatcher — пришли вывод, посмотрю структуру")
        return 1
    print(f"основной файл бота: {main_file.relative_to(ROOT)}")

    notes: list[str] = []
    main_text = main_file.read_text(encoding="utf-8")
    new_main, note = insert_install(main_text, "")
    if new_main is None:
        print(f"!! {note}")
        return 1
    notes.append(f"{main_file.name}: {note}")

    config_path = APP / "config.py"
    if config_path.is_file():
        new_config, part = patch_config(config_path.read_text(encoding="utf-8"))
        if new_config is None:
            print("!! Патч остановлен, файлы НЕ изменены:")
            for msg in part:
                print("   " + msg)
            return 1
        notes.extend(part)
    else:
        new_config = None
        notes.append("config.py: не найден — настройка будет по умолчанию (1 день)")

    if APP.exists():
        backup = unique_path(BACKUP_DIR / f"vpnbot-app-backup-{STAMP}")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(APP, backup)
        print(f"бэкап кода: {backup}")

    (APP / "services" / "referral.py").write_text(REFERRAL_SERVICE, encoding="utf-8")
    (APP / "telegram" / "referral_extra.py").write_text(EXTRA_MODULE, encoding="utf-8")
    main_file.write_text(new_main, encoding="utf-8")
    if new_config is not None:
        config_path.write_text(new_config, encoding="utf-8")

    targets = [
        APP / "services" / "referral.py",
        APP / "telegram" / "referral_extra.py",
        main_file,
    ]
    if new_config is not None:
        targets.append(config_path)
    broken = False
    for path in targets:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"!! синтаксическая ошибка: {path}")
            print(exc)
            broken = True
    if broken:
        print(f"Откат: rm -rf {APP} && cp -r {BACKUP_DIR}/* {ROOT}  (или из архива бэкапа)")
        return 1

    notes.extend(update_env())
    notes.extend(update_requirements())

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(" •", note)
    print("\nКоманды в боте после пересборки:")
    print("  /vpn  — карточка «Моя подписка» (срок, устройства, трафик, QR)")
    print("  /ref  — ссылка-приглашение, +1 день за каждого друга")
    print("  /help — инструкция по приложениям (Happ, v2rayTun, Hiddify)")
    print("\nДальше: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
