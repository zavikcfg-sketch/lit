#!/usr/bin/env python3
"""patch-beauty 2026-10-07.1 — вид и польза бота LitEnergy (версия 2).

Что делает:
  * пишет app/telegram/look.py — модуль оформления экранов;
  * подключает его в главном файле бота (врезки attach(bot) и install(dp));
  * главный экран: первой строкой «🎁 Попробовать 1 день — бесплатно» — только
    новым (кто не брал тест и без подписки);
  * низ главного экрана: «📱 Моя подписка», «🌍 Локации», «📖 Как подключиться»,
    «🎁 Пригласить друга», «🆘 Поддержка» — без дублей в существующих меню;
  * подпись под баннером: аккуратный футер «⚡ LitEnergy VPN» (отключается);
  * после активации теста сразу отправляется QR-код подписки;
  * экран «🌍 Локации» — список серверов/локаций из панели Remnawave;
  * команда /loc с тем же экраном.

Безопасно: бэкап app/, проверка синтаксиса, автооткат при ошибке, повторный
запуск ничего не ломает.

Запуск:  python3 /root/vpnbot-patch-beauty.py
"""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import time
from pathlib import Path

SCRIPT_VERSION = "patch-beauty 2026-10-07.1"
MODULE_VERSION = "look 2026-10-07.2"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

ATTACH_MARKER = "_litenergy_look.attach("
INSTALL_MARKER = "_litenergy_look.install("

LOOK_MODULE = r'''"""LitEnergy: оформление экранов бота (версия 2026-10-07.2).

Подключается из main.py:
    look.attach(bot)   # правки исходящих меню: пробник новым, полезные кнопки, футер
    look.install(dp)   # обработчики: «Моя подписка», «Как подключиться», «Локации», «Друг +1 день»
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
MAIN_MENU_HINTS = ("shop", "tariff", "тариф", "buy", "menu:start", "start")
SHOP_PREFIXES = ("buy:", "chk:", "device")

HELP_FALLBACK = (
    "📖 <b>Как подключиться</b>\n\n"
    "<b>1.</b> Установите приложение:\n"
    "  • iPhone (App Store): <b>Happ</b>, <b>v2rayTun</b> или <b>Streisand</b>\n"
    "  • Android (Google Play): <b>v2rayTun</b> или <b>Hiddify</b>\n"
    "  • Windows / macOS: <b>Hiddify</b> или <b>v2rayTun</b>\n\n"
    "<b>2.</b> Скопируйте ссылку подписки: команда /vpn → «Моя подписка».\n"
    "<b>3.</b> В приложении нажмите «+» → «Добавить из буфера обмена».\n"
    "<b>4.</b> Включите подключение и проверьте любой сайт.\n\n"
    "Не работает — обновите подписку в приложении (потяните вниз → «Обновить»), "
    "выключите и включите VPN. Если не помогло — напишите в поддержку."
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
    return _row_of(markup, ("lit:vpn", "моя подписка", "мой кабинет", "кабинет"))


def _has_supportish(markup) -> bool:
    return _row_of(markup, ("t.me/", "поддерж", "support"))


def _has_inviteish(markup) -> bool:
    return _row_of(markup, ("lit:ref", "ref_", "приглас", "друг", "реферал", "menu:ref", "invite"))


def _has_locish(markup) -> bool:
    return _row_of(markup, ("lit:loc", "локаци", "локац", "сервер", "сервис"))


def _is_main_menu(markup) -> bool:
    datas = [_data(button) for button in _buttons(markup)]
    if not datas:
        return False
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
def _is_our_support(button) -> bool:
    """Наша кнопка поддержки: по подписи и телеграм-ссылке."""
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
    if chat_id <= 0:  # только личные чаты
        return

    if isinstance(markup, InlineKeyboardMarkup):
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
        cleaned = InlineKeyboardMarkup(inline_keyboard=rows)

        if _is_main_menu(cleaned):
            fresh = await is_new_user(chat_id)
            if fresh:
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
            _add_footer(method)

        if changed and rows:
            try:
                method.reply_markup = InlineKeyboardMarkup(inline_keyboard=rows)
            except Exception as exc:  # noqa: BLE001
                log.warning("look: не удалось поправить меню (%s)", exc)
        if activated:
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
                    "Отсканируйте камерой телефона или откройте приложение "
                    "Happ / v2rayTun и добавьте подписку из буфера обмена."
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
        log.info("LitEnergy look %s подключён", "2026-10-07.2")
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
    """Ищем адрес панели и токен в настройках бота/.env."""
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
        candidates = []
        for name in dir(settings):
            if name.startswith("_"):
                continue
            low = name.lower()
            if any(part in low for part in ("remna", "panel", "nawave")):
                try:
                    candidates.append((name, getattr(settings, name)))
                except Exception:  # noqa: BLE001
                    continue
        for _, value in candidates:
            if isinstance(value, str) and value.startswith("http") and not url:
                url = value.rstrip("/")
            elif isinstance(value, str) and len(value) > 20 and not value.startswith("http") and not token:
                token = value
    except Exception as exc:  # noqa: BLE001
        log.debug("look: настройки не прочитаны (%s)", exc)
    return url, token


async def _panel_json(path: str, method_name: str):
    """Читаем данные панели: сначала через сервис бота, потом напрямую."""
    try:
        from app.services.remnawave import get_remna

        remna = get_remna()
    except Exception:  # noqa: BLE001
        remna = None
    if remna is not None:
        fn = getattr(remna, method_name, None)
        if callable(fn):
            try:
                data = await fn()
                parsed = _list_of(data)
                if parsed:
                    return parsed
            except Exception as exc:  # noqa: BLE001
                log.debug("look: %s не сработал (%s)", method_name, exc)
        for name in ("request", "api_request", "_request", "call"):
            fn = getattr(remna, name, None)
            if not callable(fn):
                continue
            try:
                data = await fn("GET", path)
                parsed = _list_of(data)
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
    items: list = []
    if hosts:
        items = hosts
        alive = [item for item in items if _alive(item)]
        lines.append(f"🟢 Доступно сейчас: <b>{len(alive)}</b>")
        lines.append("")
        for item in alive[:14]:
            lines.append(f"• {html.escape(_label_host(item))} — 🟢")
        down = [item for item in items if not _alive(item)]
        for item in down[:6]:
            lines.append(f"• {html.escape(_label_host(item))} — 🔴 (временно)")
    elif nodes:
        items = nodes
        alive = [item for item in items if _alive(item)]
        lines.append(f"🟢 Серверов на связи: <b>{len(alive)}</b> из {len(items)}")
        lines.append("")
        for item in items[:14]:
            lines.append(f"• {html.escape(_label_node(item))} — {_status(item)}")
    else:
        lines.append("Список локаций подтягивается из панели.")
        lines.append("")
        lines.append("Ваша подписка уже включает все доступные локации — "
                     "выберите нужную в приложении Happ / v2rayTun.")
    lines.append("")
    lines.append("Все локации входят в вашу подписку: переключайтесь в приложении, "
                 "если одна из них недоступна.")
    lines.append(f"\n🕒 Обновлено: {datetime.now(timezone.utc).astimezone().strftime('%H:%M')}")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [_mk("🔄 Обновить", LOC_CALLBACK), _mk(CARD_BUTTON, CARD_CALLBACK)],
            [_mk("📖 Как подключиться", HELP_CALLBACK)],
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
        log.info("LitEnergy look: кнопки «Моя подписка», «Локации», «Как подключиться»")
    except Exception as exc:  # noqa: BLE001
        log.warning("look: роутер не подключился (%s)", exc)
'''


def unique_backup_folder() -> Path:
    folder = BACKUP_DIR / f"beauty-backup-{STAMP}"
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
        "LOOK_FOOTER": "1",
        "LOOK_LOCATIONS": "1",
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

    folder = unique_backup_folder()
    backups: list[tuple[Path, Path]] = []
    saved = backup(module_path, folder)
    if saved:
        backups.append((module_path, saved))

    module_path.write_text(LOOK_MODULE, encoding="utf-8")
    print(f"  ok  {module_path.relative_to(ROOT)} (модуль {MODULE_VERSION})")

    bot_file, _ = find_file_with(r"^(\s*)(\w+)\s*=\s*Bot\(")
    dp_file, _ = find_file_with(r"^(\s*)(\w+)\s*=\s*Dispatcher\(")

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
        if updated is None or updated == text:
            notes.append(f"{label}: {note}")
            continue
        saved = backup(path, folder)
        if saved:
            backups.append((path, saved))
        path.write_text(updated, encoding="utf-8")
        touched.append(path)
        notes.append(f"{label}: {note} ({path.relative_to(ROOT)})")

    notes.extend(update_env())

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
        print(f"Откат выполнен из {folder}")
        return 1

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(f" • {note}")
    print("\nГлавный экран:")
    print("  • 🎁 Попробовать 1 день — бесплатно — первой строкой, только новым")
    print("  • 📱 Моя подписка · 🌍 Локации / 📖 Как подключиться · 🎁 Пригласить друга · 🆘 Поддержка")
    print("  • аккуратный футер под баннером (LOOK_FOOTER=0 выключает)")
    print("Тест: после активации сразу приходит QR-код подписки (нужен segno в контейнере).")
    print("Локации: /loc или кнопка «🌍 Локации» — список берётся из панели Remnawave.")
    print("\nДальше: docker compose up -d --build")
    print(f"Откат: из {folder} вернуть файлы в {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
