#!/usr/bin/env python3
"""patch-look 2026-10-07.1 — главный экран бота LitEnergy.

Что делает:
  * создаёт app/telegram/look.py — модуль оформления экранов;
  * подключает его в главном файле бота (две врезки: attach(bot) и install(dp));
  * на главном экране (там, где баннер и кнопки меню) добавляет первой строкой
    кнопку «🎁 Попробовать 1 день — бесплатно» — ТОЛЬКО новым пользователям
    (кто ещё не брал тест и без действующей подписки);
  * убирает кнопку теста из магазина (она переезжает на главный экран);
  * добавляет нижний ряд полезных кнопок: «📱 Моя подписка» (после теста/подписки),
    «📖 Как подключиться», «🆘 Поддержка»;
  * делает кнопки «Как подключиться / Моя подписка / Друг +1 день» рабочими.

Ничего не удаляет: перед правкой бэкап app/, при ошибке — автооткат.
Повторный запуск безопасен.

Запуск:  python3 /root/vpnbot-patch-look.py
"""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import time
from pathlib import Path

SCRIPT_VERSION = "patch-look 2026-10-07.1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

ATTACH_MARKER = "_litenergy_look.attach("
INSTALL_MARKER = "_litenergy_look.install("

LOOK_MODULE = r'''"""LitEnergy: оформление экранов — пробник для новых и полезные кнопки.

Подключается из main.py:
    look.attach(bot)   # правки исходящих меню (кнопки и порядок)
    look.install(dp)   # обработчики кнопок «Как подключиться», «Моя подписка», «Друг +1 день»
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.look")

TRIAL_CALLBACK = "buy:trial"
HELP_CALLBACK = "lit:help"
CARD_CALLBACK = "lit:vpn"
REF_CALLBACK = "lit:ref"

TRIAL_BUTTON = "🎁 Попробовать 1 день — бесплатно"
HELP_BUTTON = "📖 Как подключиться"
CARD_BUTTON = "📱 Моя подписка"
REF_BUTTON = "🎁 Друг +1 день"
SUPPORT_BUTTON = "🆘 Поддержка"

DEFAULT_SUPPORT = "https://t.me/wixyezz"
CACHE_TTL = 60.0
OUR_CALLBACKS = {HELP_CALLBACK, CARD_CALLBACK, REF_CALLBACK}
MAIN_MENU_HINTS = ("shop", "tariff", "тариф", "buy", "menu:start", "start")
SHOP_PREFIXES = ("buy:", "chk:", "device")

HELP_FALLBACK = (
    "📖 <b>Как подключиться</b>\n\n"
    "<b>1.</b> Установите приложение:\n"
    "  • iPhone (App Store): <b>Happ</b>, <b>v2rayTun</b> или <b>Streisand</b>\n"
    "  • Android (Google Play): <b>v2rayTun</b> или <b>Hiddify</b>\n"
    "  • Windows / macOS: <b>Hiddify</b> или <b>v2rayTun</b>\n\n"
    "<b>2.</b> Скопируйте ссылку подписки: команда /vpn → «Моя подписка».\n"
    "<b>3.</b> В приложении нажмите «+» → «Добавить из буфера обмена» "
    "(или «Импорт подписки»).\n"
    "<b>4.</b> Включите подключение и проверьте любой сайт.\n\n"
    "Если не работает: обновите подписку в приложении (свайп вниз → «Обновить»), "
    "затем включите-выключите VPN. Помогло? Напишите в поддержку."
)

router = Router(name="litenergy-look")
_cache: dict[int, tuple[float, bool]] = {}


# ---------------------------------------------------------------- настройки
def _env_files() -> list[Path]:
    files: list[Path] = []
    try:
        files.append(Path(__file__).resolve().parents[2] / ".env")
    except Exception:  # noqa: BLE001
        pass
    files.append(Path("/app/.env"))
    return files


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for path in _env_files():
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                if key.strip() == name:
                    return raw.strip().strip('"').strip("'")
        except OSError:
            continue
    return default


def enabled() -> bool:
    return _env("LOOK_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def support_url() -> str:
    return _env("SUPPORT_URL", DEFAULT_SUPPORT).strip()


# ---------------------------------------------------------------- кнопки меню
def _buttons(markup) -> list:
    try:
        return [button for row in markup.inline_keyboard for button in row]
    except Exception:  # noqa: BLE001
        return []


def _data(button) -> str:
    return str(getattr(button, "callback_data", "") or "")


def _text(button) -> str:
    return str(getattr(button, "text", "") or "")


def _has(markup, callback: str) -> bool:
    return any(_data(button) == callback for button in _buttons(markup))


def _has_helpish(markup) -> bool:
    probes = ("help", "подключ", "инструкц", "справк", "помощь")
    for button in _buttons(markup):
        blob = (_data(button) + " " + _text(button)).lower()
        if any(probe in blob for probe in probes):
            return True
    return False


def _has_cardish(markup) -> bool:
    for button in _buttons(markup):
        blob = (_data(button) + " " + _text(button)).lower()
        if CARD_CALLBACK in blob or "моя подписка" in blob or "мой кабинет" in blob:
            return True
    return False


def _has_supportish(markup) -> bool:
    for button in _buttons(markup):
        url = str(getattr(button, "url", "") or "")
        blob = (_text(button) + " " + url).lower()
        if "t.me/" in url and any(probe in blob for probe in ("поддерж", "support", "help", "помощ")):
            return True
    return False


def _is_main_menu(markup) -> bool:
    datas = [_data(button) for button in _buttons(markup)]
    if not datas:
        return False
    # кнопку теста, которую добавляем сами, в расчёт не берём
    datas = [data for data in datas if data != TRIAL_CALLBACK]
    if not datas:
        return False
    if any(data.startswith(prefix) for data in datas for prefix in SHOP_PREFIXES):
        return False
    return any(hint in data.lower() for data in datas for hint in MAIN_MENU_HINTS)


def _mk(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def _mk_url(text: str, url: str):
    return InlineKeyboardButton(text=text, url=url)


# ---------------------------------------------------------------- новичок ли
async def is_new_user(user_id: int) -> bool:
    """Новым считаем того, кто не брал тест и без действующей подписки."""
    now = time.monotonic()
    cached = _cache.get(int(user_id))
    if cached is not None and now - cached[0] < CACHE_TTL:
        return cached[1]
    fresh = False
    try:
        from app.services import trial as trial_service

        if trial_service.trial_enabled():
            fresh = (not await trial_service.trial_used(user_id)) and (
                not await trial_service.has_active_subscription(user_id)
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("look: пробник недоступен (%s)", exc)
        fresh = False
    _cache[int(user_id)] = (now, fresh)
    return fresh


def forget(user_id: int) -> None:
    _cache.pop(int(user_id), None)


# ---------------------------------------------------------------- правка меню
def _strip_our_rows(rows: list[list]) -> tuple[list[list], bool]:
    changed = False
    result: list[list] = []
    for row in rows:
        kept = [button for button in row if _data(button) not in OUR_CALLBACKS and _text(button) != SUPPORT_BUTTON]
        if len(kept) != len(row):
            changed = True
        if kept:
            result.append(kept)
    return result, changed


def _strip_trial(rows: list[list]) -> tuple[list[list], bool]:
    changed = False
    result: list[list] = []
    for row in rows:
        kept = [button for button in row if _data(button) != TRIAL_CALLBACK]
        if len(kept) != len(row):
            changed = True
        if kept:
            result.append(kept)
    return result, changed


async def polish(method) -> None:
    """Причёсываем исходящее меню: кнопка пробника новым + нижний ряд утилит."""
    if not enabled():
        return
    if isinstance(method, (list, tuple)):
        for item in method:
            await polish(item)
        return
    markup = getattr(method, "reply_markup", None)
    if not isinstance(markup, InlineKeyboardMarkup):
        return
    try:
        chat_id = int(getattr(method, "chat_id", 0) or 0)
    except (TypeError, ValueError):
        return
    if chat_id <= 0:  # только личные чаты
        return

    blob = ""
    for attr in ("text", "caption"):
        value = getattr(method, attr, None)
        if isinstance(value, str):
            blob += value
    activated = "Тестовый доступ активирован" in blob
    if activated:
        forget(chat_id)

    rows = [list(row) for row in markup.inline_keyboard]
    rows, changed = _strip_our_rows(rows)
    rows, dropped_trial = _strip_trial(rows)
    changed = changed or dropped_trial
    # дальше смотрим на клавиатуру без наших кнопок — так повторный прогон не путается
    cleaned = InlineKeyboardMarkup(inline_keyboard=rows)

    if _is_main_menu(cleaned):
        fresh = await is_new_user(chat_id)
        if fresh:
            rows.insert(0, [_mk(TRIAL_BUTTON, TRIAL_CALLBACK)])
            changed = True
        tail: list = []
        if not fresh and not _has_cardish(cleaned):
            tail.append(_mk(CARD_BUTTON, CARD_CALLBACK))
        if not _has_helpish(cleaned):
            tail.append(_mk(HELP_BUTTON, HELP_CALLBACK))
        url = support_url()
        if url and not _has_supportish(cleaned):
            tail.append(_mk_url(SUPPORT_BUTTON, url))
        if tail:
            rows.append(tail)
            changed = True

    if changed and rows:
        try:
            method.reply_markup = InlineKeyboardMarkup(inline_keyboard=rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("look: не удалось поправить меню (%s)", exc)
    if activated:
        # следующий экран пересчитает статус заново (тест уже выдан)
        forget(chat_id)


def attach(bot) -> None:
    """Подключаемся к отправке сообщений: правим клавиатуры на лету."""
    session = getattr(bot, "session", None)
    if session is None:
        return
    if getattr(session, "_litenergy_look", False):
        return
    original = session.make_request

    async def make_request(bot_arg, method, timeout=None):
        try:
            await polish(method)
        except Exception as exc:  # noqa: BLE001
            log.debug("look: пропускаю правку (%s)", exc)
        return await original(bot_arg, method, timeout)

    try:
        session.make_request = make_request
        session._litenergy_look = True
        log.info("LitEnergy look подключён")
    except Exception as exc:  # noqa: BLE001
        log.warning("look: не подключился (%s)", exc)


# ---------------------------------------------------------------- кнопки
def _extras():
    try:
        from app.telegram import referral_extra

        return referral_extra
    except Exception:  # noqa: BLE001
        return None


async def _delegate(cb: CallbackQuery, command: str) -> bool:
    extras = _extras()
    if extras is None:
        return False
    handler = getattr(extras, command, None)
    message = getattr(cb, "message", None)
    if handler is None or message is None:
        return False
    try:
        message.from_user = cb.from_user
    except Exception:  # noqa: BLE001
        pass
    try:
        await handler(message)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("look: %s не сработал (%s)", command, exc)
        return False


async def _soft_answer(cb: CallbackQuery, text: str = "") -> None:
    try:
        if text:
            await cb.answer(text, show_alert=True)
        else:
            await cb.answer()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == HELP_CALLBACK)
async def cb_help(cb: CallbackQuery) -> None:
    extras = _extras()
    text = str(getattr(extras, "HELP_TEXT", "") or "") if extras is not None else ""
    if not text:
        text = HELP_FALLBACK
    message = getattr(cb, "message", None)
    if message is not None:
        try:
            await message.answer(text, disable_web_page_preview=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("look: справка не отправилась (%s)", exc)
    await _soft_answer(cb)


@router.callback_query(F.data == CARD_CALLBACK)
async def cb_card(cb: CallbackQuery) -> None:
    if not await _delegate(cb, "cmd_my_subscription"):
        await _soft_answer(cb, "Карточка подписки: команда /vpn")
        return
    await _soft_answer(cb)


@router.callback_query(F.data == REF_CALLBACK)
async def cb_ref(cb: CallbackQuery) -> None:
    if not await _delegate(cb, "cmd_referral"):
        await _soft_answer(cb, "Пригласительная ссылка: команда /ref")
        return
    await _soft_answer(cb)


def install(dp) -> None:
    """Регистрируем обработчики кнопок."""
    if dp is None:
        return
    try:
        dp.include_router(router)
    except Exception as exc:  # noqa: BLE001
        log.warning("look: роутер не подключился (%s)", exc)
'''


def unique_backup(name: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"look-backup-{STAMP}" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = unique_backup(path.name)
    shutil.copy2(path, target)
    return target


def python_files() -> list[Path]:
    if not APP.exists():
        return []
    return sorted(APP.rglob("*.py"))


def find_file_with(pattern: str) -> tuple[Path | None, str]:
    """Файл с созданием Bot(...) или Dispatcher(...) и имя переменной."""
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


def insert_block(text: str, pattern: str, marker: str, lines_builder) -> tuple[str | None, str]:
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
        block_lines = lines_builder(indent, name)
        block = "".join((indent + item + "\n") if item else "\n" for item in block_lines)
        return "".join(lines[: end + 1]) + block + "".join(lines[end + 1:]), f"врезка в {name}"
    return None, "шаблон не найден"


def attach_lines(indent: str, name: str) -> list[str]:
    return [
        "",
        "# --- LitEnergy: оформление меню (пробник новым, полезные кнопки) ---",
        "try:",
        "    from app.telegram import look as _litenergy_look",
        f"    _litenergy_look.attach({name})",
        "except Exception as _look_exc:  # noqa: BLE001",
        "    import logging as _look_logging",
        '    _look_logging.getLogger("app").warning(',
        '        "LitEnergy look не подключён: %s", _look_exc',
        "    )",
        "",
    ]


def install_lines(indent: str, name: str) -> list[str]:
    return [
        "",
        "# --- LitEnergy: кнопки «Как подключиться», «Моя подписка», «Друг +1 день» ---",
        "try:",
        "    from app.telegram import look as _litenergy_look",
        f"    _litenergy_look.install({name})",
        "except Exception as _look_exc:  # noqa: BLE001",
        "    import logging as _look_logging",
        '    _look_logging.getLogger("app").warning(',
        '        "LitEnergy look не подключён: %s", _look_exc',
        "    )",
        "",
    ]


def update_env() -> list[str]:
    notes: list[str] = []
    try:
        text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    except OSError:
        return ["не смог прочитать .env"]
    lines = text.splitlines()
    wanted = {
        "LOOK_ENABLED": "1",
        "SUPPORT_URL": "https://t.me/wixyezz",
    }
    for key, value in wanted.items():
        if any(line.strip().startswith(f"{key}=") for line in lines):
            notes.append(f".env: {key} уже есть")
            continue
        lines.append(f"{key}={value}")
        notes.append(f".env: добавлен {key}")
    try:
        ENV.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        notes.append(f"не смог записать .env ({exc})")
    return notes


def main() -> int:
    print(f"{SCRIPT_VERSION}")
    print(f"корень бота: {ROOT}")
    if not APP.exists():
        print(f"!! нет каталога {APP} — укажи VPNBOT_DIR=/путь/к/боту")
        return 1

    module_path = APP / "telegram" / "look.py"
    if not module_path.parent.exists():
        print(f"!! нет каталога {module_path.parent}")
        return 1

    backups: list[tuple[Path, Path]] = []
    saved = backup(module_path)
    if saved:
        backups.append((module_path, saved))

    module_path.write_text(LOOK_MODULE, encoding="utf-8")
    print(f"  ok  {module_path.relative_to(ROOT)}")

    bot_file, bot_var = find_file_with(r"^(\s*)(\w+)\s*=\s*Bot\(")
    dp_file, dp_var = find_file_with(r"^(\s*)(\w+)\s*=\s*Dispatcher\(")

    touched: list[Path] = []
    notes: list[str] = []

    for path, pattern, marker, builder, label in (
        (bot_file, r"^(\s*)(\w+)\s*=\s*Bot\(", ATTACH_MARKER, attach_lines, "attach"),
        (dp_file, r"^(\s*)(\w+)\s*=\s*Dispatcher\(", INSTALL_MARKER, install_lines, "install"),
    ):
        if path is None:
            notes.append(f"{label}: не нашёл, куда вставить (создание Bot/Dispatcher)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"{label}: файл не прочитан ({exc})")
            continue
        updated, note = insert_block(text, pattern, marker, builder)
        if updated is None:
            notes.append(f"{label}: {note}")
            continue
        if updated == text:
            notes.append(f"{label}: {note}")
            continue
        saved = backup(path)
        if saved:
            backups.append((path, saved))
        path.write_text(updated, encoding="utf-8")
        touched.append(path)
        notes.append(f"{label}: {note} ({path.relative_to(ROOT)})")

    notes.extend(update_env())

    # ---- проверка синтаксиса, при ошибке откат
    broken: list[str] = []
    for path in [module_path, *touched]:
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + ".pyc")
        except py_compile.PyCompileError as exc:
            broken.append(f"{path}: {exc.msg}")
    for path in [module_path, *touched]:
        pyc = Path(str(path) + ".pyc")
        if pyc.exists():
            pyc.unlink()

    if broken:
        print("!! синтаксические ошибки:")
        for item in broken:
            print(f"   {item}")
        for path, saved in backups:
            shutil.copy2(saved, path)
        print(f"Откат выполнен из {BACKUP_DIR}/look-backup-{STAMP}")
        return 1

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(f" • {note}")
    print("\nКнопки на главном экране:")
    print("  • 🎁 Попробовать 1 день — бесплатно  — только новым (нет теста и подписки)")
    print("  • 📱 Моя подписка / 📖 Как подключиться / 🆘 Поддержка — нижним рядом")
    print("Кнопка теста из магазина убрана — она теперь на главном экране.")
    print("\nДальше: docker compose up -d --build")
    print(f"Откат: rm -rf {ROOT}/app && из {BACKUP_DIR}/look-backup-{STAMP} вернуть файлы")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
