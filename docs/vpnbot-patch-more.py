#!/usr/bin/env python3
"""patch-more 2026-10-07.1 — дополнительные улучшения бота LitEnergy.

Что делает:
  * app/telegram/diag.py — «🆘 Не подключается?» и команда /diag: быстрая
    диагностика (подписка, срок с прогресс-баром, устройства, трафик, панель)
    и понятный чек-лист что делать;
  * app/telegram/referral_extra.py — карточка «Моя подписка» переделывается:
    статус-строка, прогресс-бар срока, устройства, трафик, ссылка + QR и
    полезные кнопки (ключ заново, диагностика, продлить, локации);
  * /help получает кнопки под текстом;
  * врезка в главный файл: подключение diag.

Безопасно: бэкап, проверка синтаксиса, автооткат, повторный запуск безопасен.

Запуск:  python3 /root/vpnbot-patch-more.py
"""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import time
from pathlib import Path

SCRIPT_VERSION = "patch-more 2026-10-07.1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

DIAG_MARKER = "_litenergy_diag.install("
CARD_MARKER = "▰"
SUPPORT_DEFAULT = "https://t.me/wixyezz"

DIAG_MODULE = r'''"""LitEnergy: диагностика подключения.

Кнопка «🆘 Не подключается?» и команда /diag: проверяет подписку в локальной
базе и в панели Remnawave, показывает срок, устройства и трафик, и выдаёт
понятный чек-лист. Ничего не меняет — только читает.
"""
from __future__ import annotations

import html
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.diag")

MODULE_VERSION = "2026-10-07.1"
FIX_CALLBACK = "lit:fix"
SUPPORT_DEFAULT = "https://t.me/wixyezz"

router = Router(name="litenergy-diag")


# ---------------------------------------------------------------- настройки
def _env_path() -> Path | None:
    try:
        return Path(__file__).resolve().parents[2] / ".env"
    except Exception:  # noqa: BLE001
        return None


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for path in (_env_path(), Path("/app/.env")):
        if path is None:
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, raw = line.partition("=")
                    if key.strip() == name:
                        return raw.strip().strip('"').strip("'")
        except OSError:
            continue
    return default


def support_url() -> str:
    return _env("SUPPORT_URL", SUPPORT_DEFAULT).strip()


def _look_installed() -> bool:
    try:
        return (Path(__file__).resolve().parent / "look.py").is_file()
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- база
def _db_candidates() -> list[Path]:
    paths: list[Path] = []
    # рядом с этим модулем: app/telegram/diag.py → <корень бота>/data/bot.db
    try:
        paths.append(Path(__file__).resolve().parents[2] / "data" / "bot.db")
    except Exception:  # noqa: BLE001
        pass
    env_dir = os.environ.get("VPNBOT_DIR")
    if env_dir:
        paths.append(Path(env_dir) / "data" / "bot.db")
    for name in ("DATABASE_URL", "DATABASE_PATH", "DB_PATH"):
        value = _env(name)
        if value and "sqlite" in value.lower():
            raw = value.split("///")[-1]
            if raw and raw not in (":memory:", ""):
                paths.append(Path(raw))
    paths += [
        Path("/app/data/bot.db"),
        Path("/app/data/database.db"),
        Path("data/bot.db"),
        Path("/opt/vpnbot/vpn-bot/data/bot.db"),
    ]
    result: list[Path] = []
    for path in paths:
        try:
            if path.is_file() and path not in result:
                result.append(path)
        except OSError:
            continue
    return result


def _local_row(telegram_id: int) -> dict | None:
    for db in _db_candidates():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        except sqlite3.Error:
            continue
        try:
            cur = conn.execute(
                "SELECT subscription_url, expire_at, status "
                "FROM users WHERE telegram_id = ? LIMIT 1",
                (int(telegram_id),),
            )
            row = cur.fetchone()
            if row is None:
                return {"db": str(db), "found": False}
            return {
                "db": str(db),
                "found": True,
                "subscription_url": row[0],
                "expire_at": row[1],
                "status": row[2],
            }
        except sqlite3.Error as exc:
            log.debug("diag: база %s не прочитана (%s)", db, exc)
            continue
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    return None


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


async def _panel_info(telegram_id: int):
    try:
        from app.services.remnawave import get_remna

        remna = get_remna()
        user = await remna.find_user_by_telegram_id(int(telegram_id))
        if user and user.get("id"):
            return await remna.get_user(str(user["id"]))
        return user
    except Exception as exc:  # noqa: BLE001
        log.debug("diag: панель недоступна (%s)", exc)
        return None


# ---------------------------------------------------------------- вид
SEGMENTS = 10


def bar(left: int, total: int) -> str:
    """Прогресс-бар оставшихся дней: ▰▰▰▱▱▱▱▱▱▱"""
    try:
        left = max(0, int(left))
        total = max(1, int(total))
    except (TypeError, ValueError):
        return ""
    filled = max(0, min(SEGMENTS, round(SEGMENTS * left / total)))
    return "▰" * filled + "▱" * (SEGMENTS - filled)


def tariff_total(local_expire, days_left: int) -> int:
    """Ориентир для полоски: стандартный месяц."""
    return 30


def _kb(rows_data: list[list[tuple[str, str, bool]]]) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows_data:
        line: list[InlineKeyboardButton] = []
        for text, target, is_url in row:
            if is_url:
                line.append(InlineKeyboardButton(text=text, url=target))
            else:
                line.append(InlineKeyboardButton(text=text, callback_data=target))
        keyboard.append(line)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_keyboard(has_subscription: bool) -> InlineKeyboardMarkup:
    url = support_url()
    rows: list[list[tuple[str, str, bool]]] = []
    if has_subscription:
        rows.append([("🔑 Прислать ключ заново", "sub:resend", False)])
    look = _look_installed()
    second: list[tuple[str, str, bool]] = []
    if look:
        second.append(("📱 Моя подписка", "lit:vpn", False))
        second.append(("🌍 Локации", "lit:loc", False))
    elif has_subscription:
        second.append(("🛒 Тарифы", "menu:shop", False))
    if second:
        rows.append(second)
    if url:
        rows.append([("🆘 Поддержка", url, True)])
    return _kb(rows)


async def build_report(telegram_id: int) -> tuple[str, InlineKeyboardMarkup, bool]:
    """Возвращает (текст, клавиатура, есть_ли_подписка)."""
    lines = ["🧭 <b>Диагностика подключения</b>", ""]
    has_subscription = False
    problems: list[str] = []

    local = _local_row(telegram_id)
    panel = await _panel_info(telegram_id)

    if local is None:
        lines.append("⚠️ Не удалось прочитать базу бота — напишите в поддержку.")
    elif not local.get("found"):
        lines.append("❌ Подписки нет.")
        lines.append("Возьмите 🎁 тест на 1 день (кнопка в меню) или оформите тариф.")
    else:
        has_subscription = bool(local.get("subscription_url"))
        expire = _parse_dt(local.get("expire_at"))
        now = datetime.now(timezone.utc)
        if expire:
            days = (expire.date() - now.date()).days
            if days >= 0:
                left = max(days, 0)
                lines.append(f"✅ Подписка активна, осталось <b>{left} дн.</b>")
                lines.append(f"    {bar(left, tariff_total(expire, left))}  до {expire.strftime('%d.%m.%Y')}")
            else:
                lines.append(f"❌ Подписка закончилась {expire.strftime('%d.%m.%Y')}.")
                problems.append("Продлите подписку: кнопка ниже или /vpn.")
        status = str(local.get("status") or "")
        if status.upper() == "BLOCKED":
            lines.append("🚫 Статус: <b>заблокирована</b>.")
            problems.append("Подписка заблокирована — напишите в поддержку.")
        if not local.get("subscription_url"):
            problems.append("В базе нет ссылки подписки — пришлите ключ заново или напишите в поддержку.")

    if isinstance(panel, dict) and panel:
        panel_status = str(panel.get("status") or "")
        limit = panel.get("hwidDeviceLimit")
        used = panel.get("trafficUsedBytes") or panel.get("usedTrafficBytes")
        expire_panel = _parse_dt(panel.get("expireAt"))
        detail = []
        if panel_status:
            detail.append(f"панель: <b>{html.escape(panel_status)}</b>")
        if expire_panel:
            detail.append(f"до {expire_panel.strftime('%d.%m.%Y')}")
        if limit is not None:
            detail.append(f"устройств: <b>{limit}</b>")
        if used is not None:
            try:
                detail.append(f"трафик: <b>{int(used) / (1024 ** 3):.1f} ГБ</b>")
            except (TypeError, ValueError):
                pass
        if detail:
            lines.append("ℹ️ " + " · ".join(detail))
        if panel_status and panel_status.upper() not in ("ACTIVE",):
            problems.append(f"В панели статус {panel_status} — напишите в поддержку.")
    else:
        lines.append("ℹ️ Панель сейчас не ответила — это не влияет на работу VPN.")

    lines.append("")
    lines.append("<b>Что сделать по шагам:</b>")
    lines.append("1. В приложении потяните список вниз — «Обновить подписку».")
    lines.append("2. Выключите и включите VPN, выберите другую локацию.")
    lines.append("3. Перезапустите приложение, проверьте интернет без VPN.")
    if problems:
        lines.append("")
        for item in problems:
            lines.append(f"• {html.escape(item)}")

    return "\n".join(lines), build_keyboard(has_subscription), has_subscription


async def show(message, telegram_id: int) -> None:
    text, keyboard, _ = await build_report(telegram_id)
    try:
        await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        log.exception("diag: не удалось отправить отчёт")


@router.callback_query(F.data == FIX_CALLBACK)
async def cb_fix(cb) -> None:
    message = getattr(cb, "message", None)
    user = getattr(cb, "from_user", None)
    if message is not None and user is not None:
        await show(message, int(user.id))
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass


@router.message(F.text == "/diag")
async def cmd_diag(message) -> None:
    user = getattr(message, "from_user", None)
    if user is not None:
        await show(message, int(user.id))


def install(dp) -> None:
    if dp is None:
        return
    try:
        dp.include_router(router)
        log.info("LitEnergy diag: кнопка «Не подключается?» и /diag")
    except Exception as exc:  # noqa: BLE001
        log.warning("diag: роутер не подключился (%s)", exc)
'''

CARD_FUNC = '''async def cmd_my_subscription(message: Message) -> None:
    """Карточка «Моя подписка»: срок с полоской, устройства, трафик, QR и кнопки."""
    if message.from_user is None:
        return
    tid = message.from_user.id
    row = None
    try:
        row = await _user_row(tid)
    except Exception as exc:  # noqa: BLE001
        log.warning("моя подписка: база недоступна (%s)", exc)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows: list = []
    url = str(row[0]) if row and row[0] else None
    expire = _parse_dt(row[1]) if row and row[1] else None
    now = datetime.now(timezone.utc)
    days_left = (expire.date() - now.date()).days if expire else None

    if not url:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Тарифы и подписка", callback_data="menu:shop")],
                [InlineKeyboardButton(text="🧭 Не подключается?", callback_data="lit:fix")],
            ]
        )
        text = (
            "📱 <b>Моя подписка</b>\\n"
            "━━━━━━━━━━━━━━━\\n\\n"
            "Подписки пока нет.\\n\\n"
            "🎁 Возьмите <b>тест на 1 день бесплатно</b> — кнопка на главном экране.\\n"
            "💎 Или оформите тариф от 50 ₽ в магазине."
        )
        try:
            await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            pass
        return

    state = "🟢 активна" if (days_left is not None and days_left >= 0) else "🔴 закончилась"
    lines = ["📱 <b>Моя подписка</b>", "━━━━━━━━━━━━━━━", ""]
    lines.append(f"Статус: <b>{state}</b>")
    if days_left is not None:
        total = 30
        try:
            if row and row[1]:
                lines.append(f"Осталось: <b>{max(days_left, 0)} дн.</b> (до {expire.strftime('%d.%m.%Y')})")
        except Exception:  # noqa: BLE001
            pass
        filled = max(0, min(10, round(10 * max(days_left, 0) / total))) if days_left >= 0 else 0
        lines.append("▰" * filled + "▱" * (10 - filled))

    panel = await _panel_info(tid)
    if isinstance(panel, dict):
        limit = panel.get("hwidDeviceLimit")
        if limit is not None:
            lines.append(f"📲 Устройств можно подключить: <b>{limit}</b>")
        used = panel.get("trafficUsedBytes") or panel.get("usedTrafficBytes")
        total_bytes = panel.get("trafficLimitBytes")
        if used is not None:
            try:
                gb_used = int(used) / (1024 ** 3)
                if total_bytes:
                    gb_total = int(total_bytes) / (1024 ** 3)
                    lines.append(f"📶 Трафик: <b>{gb_used:.1f}</b> из {gb_total:.0f} ГБ")
                else:
                    lines.append(f"📶 Трафик: <b>{gb_used:.1f} ГБ</b> (без лимита)")
            except (TypeError, ValueError):
                pass

    lines += [
        "",
        "Ссылка для подключения (вставьте в приложение):",
        f"<code>{url}</code>",
        "",
        "Приложения: Happ, v2rayTun, Hiddify — подробнее /help",
    ]
    text = "\\n".join(lines)

    buttons = []
    buttons.append([InlineKeyboardButton(text="🔑 Прислать ключ заново", callback_data="sub:resend")])
    second = []
    try:
        from app.telegram import look as _look  # noqa: F401

        second.append(InlineKeyboardButton(text="🌍 Локации", callback_data="lit:loc"))
    except Exception:  # noqa: BLE001
        pass
    buttons.append([InlineKeyboardButton(text="🧭 Не подключается?", callback_data="lit:fix")])
    if second:
        buttons.append(second)
    buttons.append([InlineKeyboardButton(text="💎 Продлить / тарифы", callback_data="menu:shop")])
    buttons.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/wixyezz")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

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
'''

HELP_FUNC = '''async def cmd_help(message: Message) -> None:
    """Инструкция + полезные кнопки."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = [
        [
            InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn"),
            InlineKeyboardButton(text="🌍 Локации", callback_data="lit:loc"),
        ],
        [InlineKeyboardButton(text="🧭 Не подключается?", callback_data="lit:fix")],
    ]
    try:
        await message.answer(
            HELP_TEXT,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001
        await message.answer(HELP_TEXT, disable_web_page_preview=True)
'''


# ----------------------------------------------------------------- утилиты
def unique_folder() -> Path:
    folder = BACKUP_DIR / f"more-backup-{STAMP}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def backup(path: Path, folder: Path) -> Path | None:
    if not path.exists():
        return None
    target = folder / path.name
    counter = 2
    while target.exists():
        target = folder / f"{path.name}-{counter}"
        counter += 1
    shutil.copy2(path, target)
    return target


DEF_RX = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.M)
NEXT_TOP_RX = re.compile(r"^(?:async\s+)?def\s+\w+\s*\(|^@|^class\s+\w+", re.M)


def replace_def(text: str, name: str, new_block: str, done_marker: str) -> tuple[str | None, str]:
    for match in DEF_RX.finditer(text):
        if match.group(1) != name:
            continue
        start = match.start()
        rest = text[match.end():]
        following = NEXT_TOP_RX.search(rest)
        end = match.end() + (following.start() if following else len(rest))
        block = text[start:end]
        if done_marker and done_marker in block:
            return text, f"{name} уже обновлён"
        return text[:start] + new_block + text[end:], f"{name} обновлён"
    return None, f"{name} не найден"


def python_files() -> list[Path]:
    if not APP.exists():
        return []
    return sorted(APP.rglob("*.py"))


def find_file_with(pattern: str) -> tuple[Path | None, str]:
    rx = re.compile(pattern, re.M)
    fallback: tuple[Path, str] | None = None
    for path in python_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = rx.search(text)
        if not match:
            continue
        if fallback is None:
            fallback = (path, match.group(1))
        if "start_polling" in text:
            return path, match.group(1)
    return fallback if fallback else (None, "")


def insert_block(text: str, pattern: str, marker: str, builder) -> tuple[str | None, str]:
    if marker in text:
        return text, "уже подключено ранее"
    rx = re.compile(pattern, re.M)
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        match = rx.match(line)
        if not match:
            continue
        name = match.group(2)
        indent = match.group(1)
        depth = line.count("(") - line.count(")")
        end = idx
        while depth > 0 and end + 1 < len(lines):
            end += 1
            depth += lines[end].count("(") - lines[end].count(")")
        block_lines = builder(indent, name)
        block = "".join((indent + item + "\n") if item else "\n" for item in block_lines)
        return "".join(lines[: end + 1]) + block + "".join(lines[end + 1:]), f"врезка в {name}"
    return None, "шаблон не найден"


def install_lines(indent: str, name: str) -> list[str]:
    return [
        "",
        "# --- LitEnergy: диагностика «Не подключается?» ---",
        "try:",
        "    from app.telegram import diag as _litenergy_diag",
        f"    _litenergy_diag.install({name})",
        "except Exception as _diag_exc:  # noqa: BLE001",
        "    import logging as _diag_logging",
        '    _diag_logging.getLogger("app").warning(',
        '        "LitEnergy diag не подключён: %s", _diag_exc',
        "    )",
        "",
    ]


def main() -> int:
    print(f"{SCRIPT_VERSION}")
    print(f"корень бота: {ROOT}")
    if not APP.exists():
        print(f"!! нет каталога {APP} — укажи VPNBOT_DIR=/путь/к/боту")
        return 1

    telegram_dir = APP / "telegram"
    folder = unique_folder()
    backups: list[tuple[Path, Path]] = []
    touched: list[Path] = []
    notes: list[str] = []

    # 1) модуль диагностики
    diag_path = telegram_dir / "diag.py"
    if telegram_dir.exists():
        saved = backup(diag_path, folder)
        if saved:
            backups.append((diag_path, saved))
        diag_path.write_text(DIAG_MODULE, encoding="utf-8")
        touched.append(diag_path)
        notes.append("diag.py: кнопка «Не подключается?» и /diag")
    else:
        notes.append("!! нет каталога app/telegram")

    # 2) карточка подписки и /help в referral_extra.py
    extra_path = telegram_dir / "referral_extra.py"
    if extra_path.is_file():
        text = extra_path.read_text(encoding="utf-8", errors="replace")
        updated_card, note_card = replace_def(text, "cmd_my_subscription", CARD_FUNC, CARD_MARKER)
        if updated_card is None:
            notes.append(f"referral_extra.py: {note_card} — карточка не изменена")
        else:
            if updated_card != text:
                saved = backup(extra_path, folder)
                if saved:
                    backups.append((extra_path, saved))
            text = updated_card
            notes.append(f"referral_extra.py: {note_card}")
        updated_help, note_help = replace_def(
            text, "cmd_help", HELP_FUNC, "lit:fix"
        )
        if updated_help is None:
            notes.append(f"referral_extra.py: {note_help}")
        else:
            if updated_help != text:
                saved = backup(extra_path, folder)
                if saved:
                    backups.append((extra_path, saved))
            text = updated_help
            notes.append(f"referral_extra.py: {note_help}")
        try:
            extra_path.write_text(text, encoding="utf-8")
            if extra_path not in touched:
                touched.append(extra_path)
        except OSError as exc:
            notes.append(f"referral_extra.py: не записался ({exc})")
    else:
        notes.append("referral_extra.py не найден — карточка не обновлена (нужен patch-features)")

    # 3) врезка подключения diag
    dp_file, _ = find_file_with(r"^(\s*)(\w+)\s*=\s*Dispatcher\(")
    if dp_file is not None:
        text = dp_file.read_text(encoding="utf-8", errors="replace")
        updated, note = insert_block(text, r"^(\s*)(\w+)\s*=\s*Dispatcher\(", DIAG_MARKER, install_lines)
        if updated is None or updated == text:
            notes.append(f"install: {note}")
        else:
            saved = backup(dp_file, folder)
            if saved:
                backups.append((dp_file, saved))
            dp_file.write_text(updated, encoding="utf-8")
            touched.append(dp_file)
            notes.append(f"install: {note} ({dp_file.relative_to(ROOT)})")
    else:
        notes.append("install: не нашёл создание Dispatcher")

    # 4) синтаксис + откат при ошибке
    broken: list[str] = []
    for path in touched:
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + ".pyc")
        except py_compile.PyCompileError as exc:
            broken.append(f"{path}: {exc.msg}")
    for path in touched:
        pyc = Path(str(path) + ".pyc")
        if pyc.exists():
            pyc.unlink()

    if broken:
        print("!! синтаксические ошибки:")
        for item in broken:
            print(f"   {item}")
        for path, saved in backups:
            shutil.copy2(saved, path)
        print(f"Откат выполнен из {folder}")
        return 1

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(f" • {note}")
    print("\nЧто появится в боте:")
    print("  • «Моя подписка» — полоска срока, устройства, трафик, ссылка, QR и кнопки")
    print("  • «🧭 Не подключается?» — диагностика: срок, статус, устройства + чек-лист")
    print("  • команда /diag — то же самое; кнопки также под /help")
    print("\nДальше: docker compose up -d --build")
    print(f"Откат: из {folder} вернуть файлы в {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
