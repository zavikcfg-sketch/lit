#!/usr/bin/env python3
"""patch-polish 2026-10-07.1 — внешний вид бота LitEnergy (по реальному коду).

Что делает:
  * app/telegram/design.py — фирменные тексты, баннер, команды /apps и /link;
  * app/telegram/look.py — оформление меню (пробник новым, локации, кнопки, футер);
  * handlers_start.py: красивый экран входа С БАННЕРОМ-КАРТИНКОЙ и новые тексты;
  * баннер кладётся в app/telegram/assets/ (переживает пересборку контейнера);
  * врезки в главный файл (attach/install), футер, пробник первой кнопкой.

Безопасно: бэкап, проверка синтаксиса, автооткат, повторный запуск безопасен.

Запуск:  python3 /root/vpnbot-patch-polish.py
"""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import time
from pathlib import Path

SCRIPT_VERSION = "patch-polish 2026-10-07.3"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

ASSETS = APP / "telegram" / "assets"
BANNER_NAME = "litenergy-banner.png"
BANNER_ENV_KEY = "LOOK_BANNER"

ATTACH_MARKER = "_litenergy_look.attach("
INSTALL_MARKER = "_litenergy_look.install("
DESIGN_INSTALL_MARKER = "_litenergy_design.install("

WELCOME_SIGN = "LitEnergy VPN"
HELP_SIGN = "Как подключиться"

# --------------------------------------------------------------------- design.py
DESIGN_MODULE = r'''"""LitEnergy: фирменные тексты и баннер для бота.

Хранит тексты экранов, показывает баннер-картинку и добавляет команды
/apps (приложения) и /link (ссылка + QR).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.design")

router = Router(name="litenergy-design")

BANNER_ENV_KEY = "LOOK_BANNER"
BANNER_DEFAULT = "app/telegram/assets/litenergy-banner.png"

OUTLINE = "━━━━━━━━━━━━━━━"

WELCOME = (
    "⚡ <b>LitEnergy VPN</b>\n"
    f"{OUTLINE}\n"
    "Быстрый и стабильный доступ — работает даже там, где обычный VPN молчит.\n"
    "\n"
    "🟢 Любые сервисы и сайты\n"
    "🚀 Скорость без ограничений\n"
    "🛡 Обход блокировок: белые списки + CDN\n"
    "📱 Одна подписка — все ваши устройства\n"
    "\n"
    "🎁 Новым — <b>тест на 1 день бесплатно</b>\n"
    f"{OUTLINE}\n"
    "Выберите действие 👇"
)

HELP = (
    "📖 <b>Как подключиться</b>\n"
    f"{OUTLINE}\n"
    "<b>1.</b> Установите приложение:\n"
    "  • iPhone — <b>Happ</b>, <b>v2rayTun</b>, <b>Streisand</b>\n"
    "  • Android — <b>v2rayTun</b>, <b>Hiddify</b>\n"
    "  • Windows / macOS — <b>Hiddify</b>, <b>v2rayTun</b>\n"
    "\n"
    "<b>2.</b> Возьмите ссылку: /vpn (там же QR-код).\n"
    "<b>3.</b> В приложении: «+» → «Добавить из буфера обмена».\n"
    "<b>4.</b> Включите VPN и проверьте любой сайт.\n"
    "\n"
    "⚠️ <b>Не работает?</b> Обновите подписку в приложении (потяните список вниз), "
    "смените локацию и включите VPN заново. Не помогло — 🆘 поддержка."
)

APPS = (
    "📲 <b>Приложения для подключения</b>\n"
    "\n"
    "🍎 <b>iPhone / iPad</b> — <b>Happ</b> или <b>v2rayTun</b> (App Store)\n"
    "  Добавить: «+» → «Импорт подписки» → вставить ссылку.\n"
    "\n"
    "🤖 <b>Android</b> — <b>v2rayTun</b> или <b>Hiddify</b> (Google Play)\n"
    "  Добавить: «+» → «Из буфера обмена».\n"
    "\n"
    "💻 <b>Windows / macOS</b> — <b>Hiddify</b> или <b>v2rayTun</b>\n"
    "  Добавить: «Новый профиль» → вставить ссылку.\n"
    "\n"
    "Ссылку всегда можно взять в 📱 Моей подписке (/vpn)."
)

LINK_TEXT = (
    "🔗 <b>Ваша ссылка подписки</b>\n"
    "Одна ссылка подходит для всех приложений."
)


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


def _env_path() -> Path | None:
    try:
        return Path(__file__).resolve().parents[2] / ".env"
    except Exception:  # noqa: BLE001
        return None


def welcome_text(name: str = "друг") -> str:
    return WELCOME


def help_text() -> str:
    return HELP


def banner_path() -> Path | None:
    candidates = []
    env_value = _env(BANNER_ENV_KEY, "")
    if env_value:
        candidates.append(Path(env_value))
    try:
        local = Path(__file__).resolve().parent / "assets" / "litenergy-banner.png"
        candidates.append(local)
    except Exception:  # noqa: BLE001
        pass
    candidates.append(Path("/app") / BANNER_DEFAULT)
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 1000:
                return path
        except OSError:
            continue
    log.warning("design: баннер не найден, работаю без картинки")
    return None


def banner_file():
    """Файл баннера для отправки (или None)."""
    path = banner_path()
    if path is None:
        return None
    try:
        from aiogram.types import FSInputFile

        return FSInputFile(str(path), filename="litenergy.jpg")
    except Exception as exc:  # noqa: BLE001
        log.warning("design: баннер не подготовлен (%s)", exc)
        return None


MENU_FALLBACK = (
    ("🛒 Тарифы и подписка", "menu:shop"),
    ("📱 Моя подписка", "menu:mysub"),
)


def _wrap_menu(original):
    """Обёртка: если своё меню пустое или падает — отдаём гарантированное."""

    def menu_kb():
        kb = None
        try:
            kb = original()
        except Exception as exc:  # noqa: BLE001
            log.debug("design: своё меню не собралось (%s)", exc)
        if kb is not None and getattr(kb, "inline_keyboard", None):
            return kb
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=text, callback_data=data)]
                    for text, data in MENU_FALLBACK
                ]
            )
        except Exception:  # noqa: BLE001
            return kb

    return menu_kb


def _patch_menu_kb() -> None:
    """Гарантируем, что меню входа есть и не пустое: оборачиваем menu_kb во всех
    модулях, куда он был импортирован по имени (иначе правки их не видят)."""
    import importlib

    modules = (
        "app.services.notifications",
        "app.telegram.handlers_start",
        "app.telegram.handlers_subscription",
        "app.telegram.handlers_shop",
        "app.telegram.handlers_admin",
        "app.telegram.referral_extra",
    )
    patched: list[str] = []
    base = None
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        func = getattr(module, "menu_kb", None)
        if not callable(func):
            continue
        if getattr(module, "_litenergy_menu_patched", False):
            continue
        if base is None:
            base = func
            wrapped = _wrap_menu(func)
        else:
            wrapped = _wrap_menu(func)
        try:
            setattr(module, "menu_kb", wrapped)
            module._litenergy_menu_patched = True
            patched.append(name.rsplit(".", 1)[-1])
        except Exception:  # noqa: BLE001
            continue
    if patched:
        log.info("design: меню входа защищено от пустоты (%s)", ", ".join(patched))


def _patch_texts() -> None:
    """Подменяем тексты в модуле, который их отдаёт хендлерам."""
    try:
        from app.services import notifications
    except Exception as exc:  # noqa: BLE001
        log.debug("design: тексты не переопределены (%s)", exc)
        return
    if getattr(notifications, "_litenergy_texts_patched", False):
        return
    import importlib

    modules = (
        "app.services.notifications",
        "app.telegram.handlers_start",
        "app.telegram.handlers_subscription",
        "app.telegram.handlers_shop",
        "app.telegram.handlers_admin",
        "app.telegram.referral_extra",
    )
    patched: list[str] = []
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        touched = False
        if callable(getattr(module, "welcome_text", None)):
            module.welcome_text = welcome_text
            touched = True
        if callable(getattr(module, "help_text", None)):
            module.help_text = help_text
            touched = True
        if touched:
            patched.append(name.rsplit(".", 1)[-1])
    notifications._litenergy_texts_patched = True
    log.info("design: тексты входа и справки обновлены (%s)", ", ".join(patched))


def _main_kb():
    try:
        from app.telegram.handlers_start import menu_kb

        return menu_kb()
    except Exception as exc:  # noqa: BLE001
        log.debug("design: меню не собралось (%s)", exc)
        return None


def _plain_kb():
    from aiogram.types import InlineKeyboardButton

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="menu:shop")],
            [InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn")],
            [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="lit:ref")],
        ]
    )


async def send_welcome(message, name: str = "друг") -> None:
    """Экран входа: баннер-картинка + меню."""
    kb = _main_kb() or _plain_kb()
    text = welcome_text(name)
    banner = banner_file()
    if banner is not None:
        try:
            await message.answer_photo(banner, caption=text, reply_markup=kb)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("design: баннер не отправился (%s)", exc)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def show_welcome(cb, name: str = "друг") -> None:
    """Возврат в меню из callback (учитывает, что сообщение может быть с фото)."""
    kb = _main_kb() or _plain_kb()
    text = welcome_text(name)
    message = getattr(cb, "message", None)
    if message is not None:
        try:
            if getattr(message, "photo", None):
                await message.edit_caption(caption=text, reply_markup=kb)
                return
            await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
            return
        except Exception as exc:  # noqa: BLE001
            log.debug("design: не смог обновить сообщение (%s)", exc)
    user_id = getattr(getattr(cb, "from_user", None), "id", None)
    if user_id:
        try:
            from app.services.notifications import send_message

            await send_message(user_id, text, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        log.exception("design: не удалось показать меню")


def _qr_png(url: str) -> bytes | None:
    try:
        import segno
        from io import BytesIO

        buf = BytesIO()
        segno.make(url).save(buf, kind="png", scale=5, border=2)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


async def _subscription_url(user_id: int) -> str | None:
    for module_name, func_name in (
        ("app.services.trial", "subscription_url"),
        ("app.telegram.referral_extra", "subscription_url"),
    ):
        try:
            module = __import__(module_name, fromlist=[func_name])
            func = getattr(module, func_name, None)
            if func is None:
                continue
            url = await func(user_id) if func_name == "subscription_url" else None
            if url:
                return str(url)
        except Exception:  # noqa: BLE001
            continue
    return None


@router.message(F.text == "/apps")
async def cmd_apps(message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Моя подписка и QR", callback_data="lit:vpn")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="lit:help")],
        ]
    )
    try:
        await message.answer(APPS, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        log.exception("design: /apps не отправился")


@router.message(F.text == "/link")
async def cmd_link(message) -> None:
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if not user_id:
        return
    url = await _subscription_url(int(user_id))
    if not url:
        try:
            await message.answer("Ссылка появится в 📱 Моей подписке (/vpn) сразу после активации.")
        except Exception:  # noqa: BLE001
            pass
        return
    text = f"{LINK_TEXT}\n\n<code>{url}</code>"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Как подключиться", callback_data="lit:help")],
        ]
    )
    try:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        log.exception("design: /link не отправился")
        return
    png = _qr_png(url)
    if not png:
        return
    try:
        from aiogram.types import BufferedInputFile

        await message.answer_photo(
            BufferedInputFile(png, filename="litenergy-qr.png"),
            caption="🔳 Отсканируйте в приложении Happ / v2rayTun.",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("design: QR не отправлен (%s)", exc)


def install(dp) -> None:
    if dp is None:
        return
    _patch_texts()
    _patch_menu_kb()
    try:
        dp.include_router(router)
        log.info("LitEnergy design: команды /apps и /link")
    except Exception as exc:  # noqa: BLE001
        log.warning("design: роутер не подключился (%s)", exc)
'''

# ----------------------------------------------------------------------- look.py
LOOK_MODULE = r'''"""LitEnergy: оформление экранов бота (версия 2026-10-07.2).

    look.attach(bot)   # правит исходящие меню: пробник новым, локации, кнопки, футер
    look.install(dp)   # обработчики: «Моя подписка», «Локации», «Как подключиться», «Друг +1 день»
"""
from __future__ import annotations

import html
import logging
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.look")

MODULE_VERSION = "2026-10-07.3"

TRIAL_CALLBACK = "buy:trial"
HELP_CALLBACK = "lit:help"
CARD_CALLBACK = "lit:vpn"
REF_CALLBACK = "lit:ref"
LOC_CALLBACK = "lit:loc"

TRIAL_BUTTON = "🎁 Попробовать 1 день — бесплатно"
HELP_BUTTON = "📖 Как подключиться"
CARD_BUTTON = "📱 Моя подписка"
REF_BUTTON = "🎁 Пригласить друга"
LOC_BUTTON = "🌍 Локации"
SUPPORT_BUTTON = "🆘 Поддержка"

DEFAULT_SUPPORT = "https://t.me/wixyezz"
CACHE_TTL = 60.0
PANEL_TTL = 45.0
OUR_CALLBACKS = {HELP_CALLBACK, CARD_CALLBACK, REF_CALLBACK, LOC_CALLBACK}
MAIN_MENU_HINTS = ("menu:shop", "menu:mysub", "menu:renew", "menu:checkpay", "menu:start", "menu:tariffs")
SHOP_PREFIXES = ("buy:", "chk:", "device")
HELP_SIGN = "Как подключиться"

HELP_FALLBACK = (
    "📖 <b>Как подключиться</b>\n\n"
    "<b>1.</b> Установите приложение:\n"
    "  • iPhone (App Store): <b>Happ</b>, <b>v2rayTun</b> или <b>Streisand</b>\n"
    "  • Android (Google Play): <b>v2rayTun</b> или <b>Hiddify</b>\n"
    "  • Windows / macOS: <b>Hiddify</b> или <b>v2rayTun</b>\n\n"
    "<b>2.</b> Скопируйте ссылку подписки: 📱 Моя подписка → «Ссылка».\n"
    "<b>3.</b> В приложении: «+» → «Добавить из буфера обмена».\n"
    "<b>4.</b> Включите VPN и проверьте любой сайт.\n\n"
    "Не работает — обновите подписку в приложении, выключите и включите VPN."
)

FLAGS = {
    "FI": "🇫🇮", "SE": "🇸🇪", "NO": "🇳🇴", "DK": "🇩🇰", "EE": "🇪🇪", "LV": "🇱🇻",
    "LT": "🇱🇹", "PL": "🇵🇱", "DE": "🇩🇪", "NL": "🇳🇱", "BE": "🇧🇪", "FR": "🇫🇷",
    "GB": "🇬🇧", "IE": "🇮🇪", "ES": "🇪🇸", "PT": "🇵🇹", "IT": "🇮🇹", "CH": "🇨🇭",
    "AT": "🇦🇹", "CZ": "🇨🇿", "SK": "🇸🇰", "HU": "🇭🇺", "RO": "🇷🇴", "BG": "🇧🇬",
    "RS": "🇷🇸", "HR": "🇭🇷", "SI": "🇸🇮", "GR": "🇬🇷", "TR": "🇹🇷", "UA": "🇺🇦",
    "MD": "🇲🇩", "GE": "🇬🇪", "AM": "🇦🇲", "KZ": "🇰🇿", "AE": "🇦🇪", "IL": "🇮🇱",
    "US": "🇺🇸", "CA": "🇨🇦", "BR": "🇧🇷", "AR": "🇦🇷", "JP": "🇯🇵", "KR": "🇰🇷",
    "SG": "🇸🇬", "HK": "🇭🇰", "IN": "🇮🇳", "TH": "🇹🇭", "VN": "🇻🇳", "ID": "🇮🇩",
    "AU": "🇦🇺", "ZA": "🇿🇦", "CY": "🇨🇾", "MT": "🇲🇹", "IS": "🇮🇸", "LU": "🇱🇺",
}

router = Router(name="litenergy-look")
_cache: dict[int, tuple[float, bool]] = {}
_panel_cache: tuple[float, dict] | None = None
_qr_sent: set[int] = set()
_bot = None
_our_send: ContextVar[bool] = ContextVar("litenergy_our_send", default=False)


@contextmanager
def quiet():
    """Пока мы внутри — исходящие сообщения не причёсываем."""
    token = _our_send.set(True)
    try:
        yield
    finally:
        _our_send.reset(token)


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


def footer_enabled() -> bool:
    return _env("LOOK_FOOTER", "1").lower() not in {"0", "false", "no", "off"}


def locations_enabled() -> bool:
    return _env("LOOK_LOCATIONS", "1").lower() not in {"0", "false", "no", "off"}


def support_url() -> str:
    return _env("SUPPORT_URL", DEFAULT_SUPPORT).strip()


def support_handle() -> str:
    url = support_url()
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return f"@{tail}" if tail and "t.me" in url else url


# ---------------------------------------------------------------- утилиты кнопок
def _buttons(markup) -> list:
    try:
        return [button for row in markup.inline_keyboard for button in row]
    except Exception:  # noqa: BLE001
        return []


def _data(button) -> str:
    return str(getattr(button, "callback_data", "") or "")


def _text(button) -> str:
    return str(getattr(button, "text", "") or "")


def _blob(button) -> str:
    return (_data(button) + " " + _text(button) + " " + str(getattr(button, "url", "") or "")).lower()


def _row_of(markup, probes: tuple[str, ...]) -> bool:
    for button in _buttons(markup):
        if any(probe in _blob(button) for probe in probes):
            return True
    return False


def _has_helpish(markup) -> bool:
    return _row_of(markup, ("lit:help", "help", "подключ", "инструкц", "справк"))


def _has_cardish(markup) -> bool:
    return _row_of(markup, ("lit:vpn", "моя подписка", "мой кабинет", "кабинет", "menu:mysub"))


def _has_supportish(markup) -> bool:
    return _row_of(markup, ("t.me/", "поддерж", "support"))


def _has_inviteish(markup) -> bool:
    return _row_of(markup, ("lit:ref", "ref_", "приглас", "друг", "реферал", "menu:ref", "invite"))


def _has_locish(markup) -> bool:
    return _row_of(markup, ("lit:loc", "локаци", "локац", "сервер"))


def _is_main_menu(markup) -> bool:
    """Меню входа: кнопки вида menu:* и никаких признаков магазина."""
    datas = [_data(button) for button in _buttons(markup)]
    if not datas:
        return False
    datas = [data for data in datas if data != TRIAL_CALLBACK]
    if not datas:
        return False
    if any(data.startswith(prefix) for data in datas for prefix in SHOP_PREFIXES):
        return False
    return any(hint in data.lower() for data in datas for hint in MAIN_MENU_HINTS)


def _is_welcome_screen(blob: str) -> bool:
    """Кнопку пробника показываем только на экране входа, не в справке."""
    return HELP_SIGN not in blob


def _mk(text: str, callback: str):
    return InlineKeyboardButton(text=text, callback_data=callback)


def _mk_url(text: str, url: str):
    return InlineKeyboardButton(text=text, url=url)


# ---------------------------------------------------------------- новичок ли
async def is_new_user(user_id: int) -> bool:
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
def _is_our_support(button) -> bool:
    if _text(button) != SUPPORT_BUTTON:
        return False
    return "t.me/" in str(getattr(button, "url", "") or "")


def _strip_our_rows(rows: list[list]) -> tuple[list[list], bool]:
    changed = False
    result: list[list] = []
    for row in rows:
        kept = [
            button
            for button in row
            if _data(button) not in OUR_CALLBACKS and not _is_our_support(button)
        ]
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


def _add_footer(method) -> None:
    if not footer_enabled():
        return
    for attr in ("caption", "text"):
        value = getattr(method, attr, None)
        if not isinstance(value, str) or not value.strip():
            continue
        if "LitEnergy" in value or "⚡" in value:
            return
        footer = (
            "\n\n━━━━━━━━━━━━━━━\n"
            "⚡ <b>LitEnergy VPN</b> — стабильный доступ\n"
            f"🆘 Поддержка: {html.escape(support_handle())}"
        )
        try:
            setattr(method, attr, value.rstrip() + footer)
        except Exception:  # noqa: BLE001
            pass
        return


def _move_caption(method) -> None:
    """У сообщения с фото текст живёт в подписи: переносим, иначе Telegram поругается."""
    if not hasattr(method, "caption") or not isinstance(getattr(method, "caption", None), str):
        return
    if str(getattr(method, "caption", "") or "").strip():
        return
    text = getattr(method, "text", None)
    if not isinstance(text, str) or not text.strip():
        return
    if not hasattr(method, "photo"):
        return
    try:
        method.caption = text
        method.text = None
    except Exception:  # noqa: BLE001
        pass


async def polish(method) -> None:
    """Причёсываем исходящее меню: пробник новым, полезные кнопки, футер."""
    if not enabled() or _our_send.get():
        return
    if isinstance(method, (list, tuple)):
        for item in method:
            await polish(item)
        return

    markup = getattr(method, "reply_markup", None)
    try:
        chat_id = int(getattr(method, "chat_id", 0) or 0)
    except (TypeError, ValueError):
        return
    if chat_id <= 0:
        return

    blob = ""
    for attr in ("text", "caption"):
        value = getattr(method, attr, None)
        if isinstance(value, str):
            blob += value
    _move_caption(method)

    if isinstance(markup, InlineKeyboardMarkup):
        activated = "Тестовый доступ активирован" in blob
        if activated:
            forget(chat_id)

        rows = [list(row) for row in markup.inline_keyboard]
        rows, changed = _strip_our_rows(rows)
        rows, dropped_trial = _strip_trial(rows)
        changed = changed or dropped_trial
        cleaned = InlineKeyboardMarkup(inline_keyboard=rows)

        if _is_main_menu(cleaned):
            fresh = await is_new_user(chat_id)
            if fresh and _is_welcome_screen(blob):
                rows.insert(0, [_mk(TRIAL_BUTTON, TRIAL_CALLBACK)])
                changed = True
            tail: list = []
            if not fresh and not _has_cardish(cleaned):
                tail.append(_mk(CARD_BUTTON, CARD_CALLBACK))
            if locations_enabled() and not _has_locish(cleaned):
                tail.append(_mk(LOC_BUTTON, LOC_CALLBACK))
            if tail:
                rows.append(tail)
                changed = True
            second: list = []
            if not _has_helpish(cleaned):
                second.append(_mk(HELP_BUTTON, HELP_CALLBACK))
            if not _has_inviteish(cleaned):
                second.append(_mk(REF_BUTTON, REF_CALLBACK))
            if second:
                rows.append(second)
                changed = True
            url = support_url()
            if url and not _has_supportish(cleaned):
                rows.append([_mk_url(SUPPORT_BUTTON, url)])
                changed = True

        if changed and rows:
            try:
                method.reply_markup = InlineKeyboardMarkup(inline_keyboard=rows)
            except Exception as exc:  # noqa: BLE001
                log.warning("look: не удалось поправить меню (%s)", exc)

    if isinstance(markup, InlineKeyboardMarkup):
        _add_footer(method)
        if "activated" in dir() and locals().get("activated"):
            forget(chat_id)


async def post_send(method) -> None:
    """После отправки: на активации теста присылаем QR-код подписки."""
    if not enabled() or _our_send.get() or _bot is None:
        return
    blob = ""
    for attr in ("text", "caption"):
        value = getattr(method, attr, None)
        if isinstance(value, str):
            blob += value
    if "Тестовый доступ активирован" not in blob:
        return
    try:
        chat_id = int(getattr(method, "chat_id", 0) or 0)
    except (TypeError, ValueError):
        return
    if chat_id <= 0 or chat_id in _qr_sent:
        return
    match = re.search(r"https?://[^\s<>\"]+", blob.replace("&amp;", "&"))
    if not match:
        return
    url = match.group(0).rstrip(".,)")
    png = qr_png(url)
    if not png:
        return
    _qr_sent.add(chat_id)
    try:
        from aiogram.types import BufferedInputFile

        with quiet():
            await _bot.send_photo(
                chat_id,
                photo=BufferedInputFile(png, filename="litenergy-qr.png"),
                caption=(
                    "🔳 <b>QR-код вашей подписки</b>\n"
                    "Отсканируйте камерой телефона или откройте Happ / v2rayTun "
                    "и добавьте подписку из буфера обмена."
                ),
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("look: QR не отправился (%s)", exc)


def qr_png(url: str) -> bytes | None:
    try:
        import segno
        from io import BytesIO

        buf = BytesIO()
        segno.make(url).save(buf, kind="png", scale=5, border=2)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def attach(bot) -> None:
    """Подключаемся к отправке сообщений: правим клавиатуры и футер на лету."""
    global _bot
    _bot = bot
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
        result = await original(bot_arg, method, timeout)
        try:
            await post_send(method)
        except Exception as exc:  # noqa: BLE001
            log.debug("look: пост-обработка не удалась (%s)", exc)
        return result

    try:
        session.make_request = make_request
        session._litenergy_look = True
        log.info("LitEnergy look %s подключён", MODULE_VERSION)
    except Exception as exc:  # noqa: BLE001
        log.warning("look: не подключился (%s)", exc)


# ---------------------------------------------------------------- панель
def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _list_of(data) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("response", "hosts", "nodes", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                inner = _list_of(value)
                if inner:
                    return inner
    for key in ("hosts", "nodes", "items"):
        value = getattr(data, key, None)
        if isinstance(value, list):
            return value
    return []


def _panel_settings() -> tuple[str, str]:
    url = ""
    token = ""
    keys_url = ("REMNAWAVE_URL", "REMNAWAVE_BASE_URL", "REMNAWAVE_PANEL_URL", "PANEL_URL", "RW_URL")
    keys_token = ("REMNAWAVE_TOKEN", "REMNAWAVE_API_TOKEN", "REMNAWAVE_API_KEY", "RW_TOKEN", "PANEL_API_TOKEN")
    for key in keys_url:
        value = _env(key)
        if value.startswith("http"):
            url = value
            break
    for key in keys_token:
        value = _env(key)
        if len(value) > 20 and not value.startswith("http"):
            token = value
            break
    if url and token:
        return url.rstrip("/"), token
    try:
        from app.config import get_settings

        settings = get_settings()
        for name in dir(settings):
            if name.startswith("_"):
                continue
            low = name.lower()
            if not any(part in low for part in ("remna", "panel", "nawave")):
                continue
            try:
                value = getattr(settings, name)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(value, str):
                continue
            if value.startswith("http") and not url:
                url = value.rstrip("/")
            elif len(value) > 20 and not value.startswith("http") and not token:
                token = value
    except Exception as exc:  # noqa: BLE001
        log.debug("look: настройки не прочитаны (%s)", exc)
    return url, token


async def _panel_json(path: str, method_name: str):
    try:
        from app.services.remnawave import get_remna

        remna = get_remna()
    except Exception:  # noqa: BLE001
        remna = None
    if remna is not None:
        fn = getattr(remna, method_name, None)
        if callable(fn):
            try:
                parsed = _list_of(await fn())
                if parsed:
                    return parsed
            except Exception as exc:  # noqa: BLE001
                log.debug("look: %s не сработал (%s)", method_name, exc)
        for name in ("request", "api_request", "_request", "call"):
            fn = getattr(remna, name, None)
            if not callable(fn):
                continue
            try:
                parsed = _list_of(await fn("GET", path))
                if parsed:
                    return parsed
            except Exception:  # noqa: BLE001
                continue
    url, token = _panel_settings()
    if not (url and token):
        return []
    try:
        import httpx

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=12, headers=headers) as client:
            try:
                response = await client.get(f"{url}/api{path}")
            except Exception:  # noqa: BLE001
                async with httpx.AsyncClient(timeout=12, headers=headers, verify=False) as retry:
                    response = await retry.get(f"{url}/api{path}")
        if response.status_code != 200:
            log.debug("look: панель %s → %s", path, response.status_code)
            return []
        return _list_of(response.json())
    except Exception as exc:  # noqa: BLE001
        log.debug("look: панель недоступна (%s)", exc)
        return []


async def panel_data() -> dict:
    global _panel_cache
    now = time.monotonic()
    if _panel_cache is not None and now - _panel_cache[0] < PANEL_TTL:
        return _panel_cache[1]
    hosts = await _panel_json("/hosts", "get_hosts")
    nodes = await _panel_json("/nodes", "get_nodes")
    data = {"hosts": hosts, "nodes": nodes}
    if hosts or nodes:
        _panel_cache = (now, data)
    return data


def _flag(country: str) -> str:
    return FLAGS.get(str(country or "").strip().upper(), "🌐")


def _alive(item) -> bool:
    if _get(item, "isDisabled", False):
        return False
    value = _get(item, "isConnected")
    if value is None:
        value = _get(item, "isNodeOnline")
    return bool(value) if value is not None else True


def _status(item) -> str:
    return "🟢" if _alive(item) else "🔴"


def _label_host(item) -> str:
    remark = str(_get(item, "remark", "") or "").strip()
    if remark:
        return remark
    country = str(_get(item, "countryCode", "") or "")
    return f"{_flag(country)} {str(_get(item, 'name', '') or 'Локация').strip()}".strip()


def _label_node(item) -> str:
    country = str(_get(item, "countryCode", "") or "")
    name = str(_get(item, "name", "") or "Сервер").strip()
    if country and country.upper() not in name.upper():
        name = f"{_flag(country)} {name}"
    return name


async def build_locations() -> tuple[str, InlineKeyboardMarkup]:
    data = await panel_data()
    hosts = data.get("hosts") or []
    nodes = data.get("nodes") or []
    lines = ["🌍 <b>Локации LitEnergy</b>", ""]
    if hosts:
        alive = [item for item in hosts if _alive(item)]
        lines.append(f"🟢 Доступно сейчас: <b>{len(alive)}</b>")
        lines.append("")
        for item in alive[:14]:
            lines.append(f"• {html.escape(_label_host(item))} — 🟢")
        for item in [x for x in hosts if not _alive(x)][:6]:
            lines.append(f"• {html.escape(_label_host(item))} — 🔴 (временно)")
    elif nodes:
        alive = [item for item in nodes if _alive(item)]
        lines.append(f"🟢 Серверов на связи: <b>{len(alive)}</b> из {len(nodes)}")
        lines.append("")
        for item in nodes[:14]:
            lines.append(f"• {html.escape(_label_node(item))} — {_status(item)}")
    else:
        lines.append("Список локаций подтягивается из панели.")
        lines.append("")
        lines.append("Ваша подписка уже включает все доступные локации — "
                     "выберите нужную в приложении Happ / v2rayTun.")
    lines.append("")
    lines.append("Все локации входят в подписку: переключайтесь в приложении, "
                 "если одна из них недоступна.")
    lines.append(f"\n🕒 Обновлено: {datetime.now(timezone.utc).astimezone().strftime('%H:%M')}")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_mk("🔄 Обновить", LOC_CALLBACK), _mk(CARD_BUTTON, CARD_CALLBACK)],
            [_mk(HELP_BUTTON, HELP_CALLBACK)],
        ]
    )
    return "\n".join(lines), markup


# ---------------------------------------------------------------- кнопки
def _extras():
    try:
        from app.telegram import referral_extra

        return referral_extra
    except Exception:  # noqa: BLE001
        return None


async def _delegate(cb, command: str) -> bool:
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


async def _soft_answer(cb, text: str = "") -> None:
    try:
        if text:
            await cb.answer(text, show_alert=True)
        else:
            await cb.answer()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == HELP_CALLBACK)
async def cb_help(cb) -> None:
    extras = _extras()
    text = str(getattr(extras, "HELP_TEXT", "") or "") if extras is not None else ""
    if not text:
        try:
            from app.telegram import design

            text = design.help_text()
        except Exception:  # noqa: BLE001
            text = HELP_FALLBACK
    message = getattr(cb, "message", None)
    if message is not None:
        try:
            with quiet():
                await message.answer(text, disable_web_page_preview=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("look: справка не отправилась (%s)", exc)
    await _soft_answer(cb)


@router.callback_query(F.data == CARD_CALLBACK)
async def cb_card(cb) -> None:
    if not await _delegate(cb, "cmd_my_subscription"):
        await _soft_answer(cb, "Карточка подписки: команда /vpn")
        return
    await _soft_answer(cb)


@router.callback_query(F.data == REF_CALLBACK)
async def cb_ref(cb) -> None:
    if not await _delegate(cb, "cmd_referral"):
        await _soft_answer(cb, "Пригласительная ссылка: команда /ref")
        return
    await _soft_answer(cb)


@router.callback_query(F.data == LOC_CALLBACK)
async def cb_loc(cb) -> None:
    message = getattr(cb, "message", None)
    if message is None:
        await _soft_answer(cb)
        return
    try:
        text, markup = await build_locations()
        with quiet():
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("look: локации не отобразились (%s)", exc)
        await _soft_answer(cb, "Список локаций: команда /loc")
        return
    await _soft_answer(cb)


@router.message(F.text == "/loc")
async def cmd_loc(message) -> None:
    try:
        text, markup = await build_locations()
        with quiet():
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("look: /loc не сработал (%s)", exc)


def install(dp) -> None:
    """Регистрируем обработчики кнопок и команду /loc."""
    if dp is None:
        return
    try:
        dp.include_router(router)
        log.info("LitEnergy look: «Моя подписка», «Локации», «Как подключиться»")
    except Exception as exc:  # noqa: BLE001
        log.warning("look: роутер не подключился (%s)", exc)
'''

# ---------------------------------------------------- функции для handlers_start
WELCOME_FUNC = '''def welcome_text(name: str = "друг") -> str:
    """Экран входа (оформление LitEnergy)."""
    try:
        from app.telegram import design as _litenergy_design

        return _litenergy_design.welcome_text(name)
    except Exception:  # noqa: BLE001
        return (
            "⚡ <b>LitEnergy VPN</b>\\n"
            "Быстрый и стабильный доступ.\\n\\n"
            "🎁 Новым — <b>тест 1 день бесплатно</b>.\\n\\n"
            "Выберите действие ниже 👇"
        )
'''

HELP_FUNC = '''def help_text() -> str:
    """Инструкция по подключению (оформление LitEnergy)."""
    try:
        from app.telegram import design as _litenergy_design

        return _litenergy_design.help_text()
    except Exception:  # noqa: BLE001
        return (
            "📖 <b>Как подключиться</b>\\n\\n"
            "<b>1.</b> Установите Happ, v2rayTun или Hiddify.\\n"
            "<b>2.</b> Скопируйте ссылку в «Моей подписке».\\n"
            "<b>3.</b> В приложении: «+» → «Из буфера обмена».\\n"
            "<b>4.</b> Включите VPN."
        )
'''

CMD_START_FUNC = '''async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    await upsert_local_user(message.from_user.id, message.from_user.username)
    name = message.from_user.first_name or "друг"
    try:
        from app.telegram import design as _litenergy_design

        await _litenergy_design.send_welcome(message, name)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось показать экран входа")
        await message.answer(welcome_text(name), reply_markup=menu_kb())
'''

CB_BACK_FUNC = '''async def cb_back(cb: CallbackQuery) -> None:
    name = cb.from_user.first_name if cb.from_user else "друг"
    try:
        from app.telegram import design as _litenergy_design

        await _litenergy_design.show_welcome(cb, name or "друг")
    except Exception:  # noqa: BLE001
        await _safe_edit(cb, welcome_text(name or "друг"), menu_kb())
    await cb.answer()
'''


# ------------------------------------------------------------------ утилиты патча
def unique_backup_folder() -> Path:
    folder = BACKUP_DIR / f"polish-backup-{STAMP}"
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


def attach_lines(indent: str, name: str) -> list[str]:
    return [
        "",
        "# --- LitEnergy: оформление меню (пробник новым, локации, кнопки) ---",
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
        "# --- LitEnergy: кнопки «Моя подписка», «Локации», «Как подключиться» ---",
        "try:",
        "    from app.telegram import look as _litenergy_look",
        f"    _litenergy_look.install({name})",
        "except Exception as _look_exc:  # noqa: BLE001",
        "    import logging as _look_logging",
        '    _look_logging.getLogger("app").warning(',
        '        "LitEnergy look не подключён: %s", _look_exc',
        "    )",
        "",
        "# --- LitEnergy: команды /apps и /link ---",
        "try:",
        "    from app.telegram import design as _litenergy_design",
        f"    _litenergy_design.install({name})",
        "except Exception as _design_exc:  # noqa: BLE001",
        "    import logging as _design_logging",
        '    _design_logging.getLogger("app").warning(',
        '        "LitEnergy design не подключён: %s", _design_exc',
        "    )",
        "",
    ]


REFERRAL_MARK = "_litenergy_extras.install("


def _drop_block(text: str, marker: str) -> tuple[str, bool]:
    """Убирает try/except-блок, начинающийся строкой с marker."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    dropped = False
    while i < len(lines):
        line = lines[i]
        if marker in line and i + 1 < len(lines) and lines[i + 1].strip() == "try:":
            indent = len(line) - len(line.lstrip())
            end = None
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped.startswith(")") and (len(lines[j]) - len(lines[j].lstrip())) >= indent:
                    end = j
                    break
                j += 1
            if end is not None:
                dropped = True
                i = end + 1
                if i < len(lines) and lines[i].strip() == "":
                    i += 1
                continue
        out.append(line)
        i += 1
    return ("".join(out) if dropped else text), dropped


def cleanup_stale_installs(target: Path | None, folder: Path) -> tuple[list[str], list[Path]]:
    """Ищем врезку рефералки там, где нет start_polling (обычно __init__.py),
    и убираем её — иначе бот пишет предупреждение и /vpn не работает."""
    cleaned: list[str] = []
    touched: list[Path] = []
    for path in python_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if REFERRAL_MARK not in text:
            continue
        if target is not None and path == target:
            continue
        if "start_polling" in text:
            continue
        fixed, dropped = _drop_block(text, "# --- LitEnergy extras")
        if not dropped:
            continue
        backups = backup(path, folder)
        if backups is None:
            continue
        path.write_text(fixed, encoding="utf-8")
        cleaned.append(str(path.relative_to(ROOT)))
        touched.append(path)
    return cleaned, touched


def referral_lines(indent: str, name: str) -> list[str]:
    return [
        "",
        "# --- LitEnergy: рефералка, «Моя подписка», справка ---",
        "try:",
        "    from app.telegram import referral_extra as _litenergy_extras",
        f"    _litenergy_extras.install({name})",
        "except Exception as _extras_exc:  # noqa: BLE001",
        "    import logging as _extras_logging",
        '    _extras_logging.getLogger("app").warning(',
        '        "LitEnergy extras не подключены: %s", _extras_exc',
        "    )",
    ]


DEF_RX = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.M)
NEXT_TOP_RX = re.compile(r"^(?:async\s+)?def\s+\w+\s*\(|^@|^class\s+\w+", re.M)


def replace_def(text: str, name: str, new_block: str) -> tuple[str | None, str]:
    """Меняем функцию целиком (тело и заголовок), декораторы не трогаем."""
    for match in DEF_RX.finditer(text):
        if match.group(1) != name:
            continue
        start = match.start()
        rest = text[match.end():]
        following = NEXT_TOP_RX.search(rest)
        end = match.end() + (following.start() if following else len(rest))
        block = text[start:end]
        if "_litenergy_design" in block:
            return text, f"{name} уже обновлён"
        return text[:start] + new_block + text[end:], f"{name} заменён"
    return None, f"{name} не найден"


def patch_handlers_start(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    notes: list[str] = []
    original = text
    for name, block in (
        ("welcome_text", WELCOME_FUNC),
        ("help_text", HELP_FUNC),
        ("cmd_start", CMD_START_FUNC),
        ("cb_back", CB_BACK_FUNC),
    ):
        updated, note = replace_def(text, name, block)
        if updated is None:
            notes.append(f"{name}: нет в файле (импортируется — обновим в модуле)")
            continue
        text = updated
        notes.append(note)
    if text == original:
        return None, notes
    return text, notes


def update_env(folder: Path) -> list[str]:
    notes: list[str] = []
    try:
        text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    except OSError:
        return ["не смог прочитать .env"]
    if ENV.exists():
        backup(ENV, folder)
    lines = text.splitlines()
    wanted = {
        "LOOK_ENABLED": "1",
        "LOOK_FOOTER": "1",
        "LOOK_LOCATIONS": "1",
        "LOOK_BANNER": f"/app/app/telegram/assets/{BANNER_NAME}",
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

    telegram_dir = APP / "telegram"
    if not telegram_dir.exists():
        print(f"!! нет каталога {telegram_dir}")
        return 1

    folder = unique_backup_folder()
    backups: list[tuple[Path, Path]] = []
    touched: list[Path] = []
    notes: list[str] = []

    # 1) модули оформления
    for path, content, label in (
        (telegram_dir / "design.py", DESIGN_MODULE, "design.py (тексты, баннер, /apps, /link)"),
        (telegram_dir / "look.py", LOOK_MODULE, "look.py (оформление меню, локации, QR)"),
    ):
        saved = backup(path, folder)
        if saved:
            backups.append((path, saved))
        path.write_text(content, encoding="utf-8")
        touched.append(path)
        notes.append(f"модуль записан: {label}")

    # 2) баннер
    ASSETS.mkdir(parents=True, exist_ok=True)
    banner_target = ASSETS / BANNER_NAME
    source = Path(os.environ.get("VPNBOT_BANNER", "")) if os.environ.get("VPNBOT_BANNER") else None
    if source and source.is_file():
        shutil.copy2(source, banner_target)
        notes.append(f"баннер: {banner_target.relative_to(ROOT)} ({banner_target.stat().st_size // 1024} КБ)")
    elif banner_target.is_file():
        notes.append("баннер: уже на месте")
    else:
        notes.append(
            f"баннер: положи файл в {banner_target} (без него экран входа будет текстом)"
        )

    # 3) handlers_start.py
    start_path = telegram_dir / "handlers_start.py"
    if start_path.is_file():
        updated, patch_notes = patch_handlers_start(start_path)
        if updated is None:
            notes.extend(patch_notes)
        else:
            saved = backup(start_path, folder)
            if saved:
                backups.append((start_path, saved))
            start_path.write_text(updated, encoding="utf-8")
            touched.append(start_path)
            notes.append(f"handlers_start.py: {', '.join(patch_notes)}")
    else:
        notes.append("handlers_start.py не найден — тексты не заменены")

    # 4) врезки в главный файл (тот же файл, где создаётся Bot)
    bot_file, _ = find_file_with(r"^(\s*)(\w+)\s*=\s*Bot\(")
    dp_file, _ = find_file_with(r"^(\s*)(\w+)\s*=\s*Dispatcher\(")
    if bot_file is not None:
        try:
            bot_text = bot_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            bot_text = ""
        if re.search(r"^(\s*)(\w+)\s*=\s*Dispatcher\(", bot_text, re.M):
            dp_file = bot_file

    cleaned, cleaned_paths = cleanup_stale_installs(dp_file, folder)
    for path in cleaned_paths:
        touched.append(path)
    if cleaned:
        notes.append("убрана лишняя врезка из " + ", ".join(cleaned))

    need_referral = False
    if dp_file is not None and (APP / "telegram" / "referral_extra.py").is_file():
        try:
            dp_text = dp_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            dp_text = ""
        need_referral = "_litenergy_extras.install(" not in dp_text

    def install_builder(indent: str, name: str) -> list[str]:
        lines: list[str] = []
        if need_referral:
            lines.extend(referral_lines(indent, name))
        lines.extend(install_lines(indent, name))
        return lines
    for path, pattern, marker, builder, label in (
        (bot_file, r"^(\s*)(\w+)\s*=\s*Bot\(", ATTACH_MARKER, attach_lines, "attach"),
        (dp_file, r"^(\s*)(\w+)\s*=\s*Dispatcher\(", INSTALL_MARKER, install_builder, "install"),
    ):
        if path is None:
            notes.append(f"{label}: не нашёл создание Bot/Dispatcher")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"{label}: файл не прочитан ({exc})")
            continue
        updated, note = insert_block(text, pattern, marker, builder)
        if updated is None or updated == text:
            notes.append(f"{label}: {note}")
            continue
        saved = backup(path, folder)
        if saved:
            backups.append((path, saved))
        path.write_text(updated, encoding="utf-8")
        touched.append(path)
        notes.append(f"{label}: {note} ({path.relative_to(ROOT)})")

    notes.extend(update_env(folder))

    # 5) проверка синтаксиса, при ошибке откат
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
    print("\nЭкран входа:")
    print("  • баннер-картинка LitEnergy + фирменный текст")
    print("  • 🎁 Попробовать 1 день — бесплатно — первой кнопкой, только новым")
    print("  • 🌍 Локации · 📖 Как подключиться · 🎁 Пригласить друга · 🆘 Поддержка")
    print("Новые команды: /apps (приложения), /link (ссылка + QR), /loc (локации)")
    print("\nДальше: docker compose up -d --build")
    print(f"Откат: из {folder} вернуть файлы в {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
