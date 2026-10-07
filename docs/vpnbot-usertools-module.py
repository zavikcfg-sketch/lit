"""LitEnergy: устройства, промокоды и реферальный квест.

Возможности:
  * 🐛 «Мои устройства» — список подключённых устройств (HWID) из панели,
    кнопка «Отвязать» у каждого;
  * 🎟 промокоды: дни подписки; коды заводятся админом командами
    /promo_add КОД ДНЕЙ [ЛИМИТ], /promo_list, /promo_off КОД;
  * 🎁 квест «3 друга → 30 дней»: за каждые N приглашённых друзей
    пригласивший получает бонусные дни (REFERRAL_QUEST=3:30).
"""
from __future__ import annotations

import html
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.usertools")

MODULE_VERSION = "2026-10-07.1"

DEV_CALLBACK = "lit:dev"
PROMO_CALLBACK = "lit:promo"
DEV_DELETE_PREFIX = "lit:dev:del:"
MENU_PATCH_FLAG = "_litenergy_usertools_menu"
INSTALL_FLAG = "_litenergy_usertools_installed"

TEXT_LIMIT = 120
DEVICES_CACHE_TTL = 900.0
PROMPT = (
    "🎟 <b>Промокод</b>\n\n"
    "Отправьте код одним сообщением — например: <code>PROMO10</code>\n"
    "Буквы можно строчными, дефисы и цифры допустимы."
)

router = Router(name="litenergy-usertools")


# ---------------------------------------------------------------- окружение
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


def enabled() -> bool:
    return _env("USERTOOLS_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def admin_ids() -> set[int]:
    raw = _env("ADMIN_ID", "") or _env("ADMIN_IDS", "") or _env("TELEGRAM_ADMIN_ID", "")
    values: set[int] = set()
    for chunk in re.split(r"[,\s;]+", raw):
        if chunk.strip().isdigit():
            values.add(int(chunk.strip()))
    try:
        from app.config import get_settings

        settings = get_settings()
        for name in ("admin_id", "admin_ids", "telegram_admin_id"):
            value = getattr(settings, name, None)
            if isinstance(value, int) and value:
                values.add(value)
            elif isinstance(value, str):
                for chunk in re.split(r"[,\s;]+", value):
                    if chunk.strip().isdigit():
                        values.add(int(chunk.strip()))
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    try:
                        values.add(int(item))
                    except (TypeError, ValueError):
                        continue
    except Exception:  # noqa: BLE001
        pass
    return values


def quest_reward() -> tuple[int, int]:
    """(сколько друзей, сколько дней). REFERRAL_QUEST=3:30"""
    raw = _env("REFERRAL_QUEST", "3:30")
    try:
        friends, days = raw.split(":", 1)
        return max(1, int(friends)), max(1, int(days))
    except (ValueError, AttributeError):
        return 3, 30


def _db_candidates() -> list[Path]:
    paths: list[Path] = []
    try:
        paths.append(Path(__file__).resolve().parents[2] / "data" / "bot.db")
    except Exception:  # noqa: BLE001
        pass
    env_dir = os.environ.get("VPNBOT_DIR")
    if env_dir:
        paths.append(Path(env_dir) / "data" / "bot.db")
    paths += [Path("/app/data/bot.db"), Path("data/bot.db"), Path("/opt/vpnbot/vpn-bot/data/bot.db")]
    result: list[Path] = []
    for path in paths:
        try:
            if path.is_file() and path not in result:
                result.append(path)
        except OSError:
            continue
    return result


def db_path() -> Path | None:
    found = _db_candidates()
    return found[0] if found else None


def _connect() -> sqlite3.Connection | None:
    path = db_path()
    if path is None:
        return None
    try:
        conn = sqlite3.connect(str(path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        log.warning("usertools: база недоступна (%s)", exc)
        return None


def ensure_tables() -> None:
    conn = _connect()
    if conn is None:
        return
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                days INTEGER NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promo_uses (
                code TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                used_at TEXT NOT NULL,
                UNIQUE (code, telegram_id)
            );
            CREATE TABLE IF NOT EXISTS referral_quest (
                referrer_id INTEGER NOT NULL,
                milestone INTEGER NOT NULL,
                granted_at TEXT NOT NULL,
                UNIQUE (referrer_id, milestone)
            );
            """
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("usertools: не создал таблицы (%s)", exc)
    finally:
        conn.close()


# ---------------------------------------------------------------- панель
def _remna():
    from app.services.remnawave import get_remna

    return get_remna()


async def _panel_user_id(telegram_id: int) -> int | None:
    try:
        remna = _remna()
        found = await remna.find_user_by_telegram_id(int(telegram_id))
        if found and found.get("id"):
            return int(found["id"])
    except Exception as exc:  # noqa: BLE001
        log.debug("usertools: не нашёл пользователя в панели (%s)", exc)
    return None


async def _api(method: str, path: str, payload: dict | None = None):
    remna = _remna()
    request = getattr(remna, "_request", None)
    if request is None:
        raise RuntimeError("клиент панели без _request")
    return await request(method, path, json=payload)


def _devices_of(data) -> list:
    if isinstance(data, dict):
        for key in ("devices", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return data if isinstance(data, list) else []


def _short(value, limit: int = 28) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _device_line(device: dict) -> str:
    platform = _short(device.get("platform") or device.get("deviceModel") or "устройство", 22)
    model = _short(device.get("deviceModel") or "", 22)
    created = str(device.get("createdAt") or "")[:10]
    parts = [f"• <b>{html.escape(platform)}</b>"]
    if model and model != platform:
        parts.append(f"— {html.escape(model)}")
    if created:
        parts.append(f"(с {created})")
    return " ".join(parts)


def _device_keyboard(devices: list, tokens: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, device in enumerate(devices[:8]):
        token = str(index)
        label = _short(device.get("platform") or device.get("deviceModel") or "устройство", 18)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 Отвязать {label}",
                    callback_data=f"{DEV_DELETE_PREFIX}{token}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=DEV_CALLBACK)])
    rows.append([InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_device_tokens: dict[int, tuple[float, dict[str, str], list]] = {}


def _remember(user_id: int, devices: list) -> dict[str, str]:
    import time as _time

    tokens = {str(index): str(device.get("hwid") or "") for index, device in enumerate(devices[:8])}
    _device_tokens[int(user_id)] = (_time.monotonic(), tokens, devices)
    return tokens


def _recall(user_id: int, token: str) -> tuple[dict | None, list]:
    import time as _time

    saved = _device_tokens.get(int(user_id))
    if not saved:
        return None, []
    moment, tokens, devices = saved
    if _time.monotonic() - moment > DEVICES_CACHE_TTL:
        return None, []
    hwid = tokens.get(str(token))
    if not hwid:
        return None, []
    for device in devices:
        if str(device.get("hwid")) == hwid:
            return device, devices
    return None, devices


async def devices_text(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    panel_id = await _panel_user_id(user_id)
    if panel_id is None:
        text = (
            "🐛 <b>Мои устройства</b>\n━━━━━━━━━━━━━━━\n\n"
            "Подписки пока нет. Возьмите 🎁 <b>тест на 1 день</b> — и устройство появится здесь."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Тарифы", callback_data="menu:shop")],
                [InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn")],
            ]
        )
        return text, kb
    try:
        data = await _api("GET", f"/api/hwid/devices/{panel_id}")
    except Exception as exc:  # noqa: BLE001
        log.warning("usertools: устройства не получены (%s)", exc)
        text = (
            "🐛 <b>Мои устройства</b>\n━━━━━━━━━━━━━━━\n\n"
            "Не получилось получить список — попробуйте ещё раз через минуту.\n"
            "Если не работает — напишите в поддержку."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторить", callback_data=DEV_CALLBACK)],
            ]
        )
        return text, kb

    devices = [d for d in _devices_of(data) if isinstance(d, dict)]
    lines = ["🐛 <b>Мои устройства</b>", "━━━━━━━━━━━━━━━", ""]
    if not devices:
        lines.append("Устройств пока нет.")
        lines.append("")
        lines.append("Они появятся здесь, когда вы подключитесь в приложении (Happ / v2rayTun).")
        tokens = _remember(user_id, devices)
        return "\n".join(lines), _device_keyboard(devices, tokens)
    lines.append(f"Подключено устройств: <b>{len(devices)}</b>")
    lines.append("")
    for device in devices:
        lines.append(_device_line(device))
    lines.append("")
    lines.append("Если меняете телефон или компьютер — отвяжите старое устройство кнопкой ниже.")
    tokens = _remember(user_id, devices)
    return "\n".join(lines), _device_keyboard(devices, tokens)


# ---------------------------------------------------------------- промокоды
async def grant_days(telegram_id: int, days: int) -> tuple[bool, str]:
    try:
        from app.services import referral as referral_service

        return await referral_service.grant_days(int(telegram_id), int(days))
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _promo_active(code: str) -> dict | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT code, days, max_uses, uses, active FROM promo_codes WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def promo_status(code: str, telegram_id: int) -> str:
    """ok | unknown | off | limit | used | error"""
    promo = _promo_active(code)
    if promo is None:
        return "unknown"
    if not promo.get("active"):
        return "off"
    if promo.get("max_uses") and int(promo.get("uses") or 0) >= int(promo["max_uses"]):
        return "limit"
    conn = _connect()
    if conn is None:
        return "error"
    try:
        row = conn.execute(
            "SELECT 1 FROM promo_uses WHERE code = ? AND telegram_id = ? LIMIT 1",
            (code, int(telegram_id)),
        ).fetchone()
        if row:
            return "used"
    except sqlite3.Error:
        return "error"
    finally:
        conn.close()
    return "ok"


def promo_mark_used(code: str) -> None:
    conn = _connect()
    if conn is None:
        return
    try:
        conn.execute(
            "UPDATE promo_codes SET uses = uses + 1 WHERE code = ?",
            (code,),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("usertools: не обновил счётчик промокода (%s)", exc)
    finally:
        conn.close()


def promo_add(code: str, days: int, max_uses: int = 0) -> tuple[bool, str]:
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,24}", code):
        return False, "код: 3–24 символа, только латиница, цифры, - и _"
    if days < 1 or days > 3650:
        return False, "дней должно быть от 1 до 3650"
    ensure_tables()
    conn = _connect()
    if conn is None:
        return False, "база недоступна"
    try:
        conn.execute(
            "INSERT INTO promo_codes (code, days, max_uses, uses, active, created_at) "
            "VALUES (?, ?, ?, 0, 1, ?) "
            "ON CONFLICT(code) DO UPDATE SET days = excluded.days, max_uses = excluded.max_uses, active = 1",
            (code, int(days), int(max_uses), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True, f"промокод {code}: {days} дн., лимит {max_uses or 'без ограничений'}"
    except sqlite3.Error as exc:
        return False, f"ошибка базы: {exc}"
    finally:
        conn.close()


def promo_off(code: str) -> tuple[bool, str]:
    code = code.strip().upper()
    conn = _connect()
    if conn is None:
        return False, "база недоступна"
    try:
        cur = conn.execute("UPDATE promo_codes SET active = 0 WHERE code = ?", (code,))
        conn.commit()
        return (True, f"{code} выключен") if cur.rowcount else (False, f"{code} не найден")
    except sqlite3.Error as exc:
        return False, f"ошибка базы: {exc}"
    finally:
        conn.close()


def promo_list() -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT code, days, max_uses, uses, active FROM promo_codes ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _remember_use(code: str, telegram_id: int) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute(
            "INSERT OR IGNORE INTO promo_uses (code, telegram_id, used_at) VALUES (?, ?, ?)",
            (code, int(telegram_id), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.Error as exc:
        log.warning("usertools: не записал использование (%s)", exc)
        return False
    finally:
        conn.close()


async def redeem(code: str, telegram_id: int) -> tuple[bool, str]:
    code = code.strip().upper()
    status = promo_status(code, telegram_id)
    if status == "unknown":
        return False, "Такого промокода нет. Проверьте написание."
    if status == "off":
        return False, "Этот промокод больше не действует."
    if status == "limit":
        return False, "Лимит использований промокода исчерпан."
    if status == "used":
        return False, "Вы уже использовали этот промокод."
    promo = _promo_active(code) or {}
    days = int(promo.get("days") or 0)
    if days < 1:
        return False, "У промокода не заданы дни — напишите в поддержку."
    if not _remember_use(code, telegram_id):
        return False, "Не удалось записать промокод — попробуйте позже."
    ok, reason = await grant_days(telegram_id, days)
    if not ok:
        return False, (
            "Промокод принят, но дни не начислились (нет подписки в панели).\n"
            "Оформите тариф, затем напишите в поддержку — начислим вручную."
        )
    promo_mark_used(code)
    return True, f"🎉 Промокод активирован: <b>+{days} дн.</b> к подписке."


class PromoText:
    """Фильтр: сообщение — похоже на промокод и такой код есть в базе."""

    def __init__(self):
        try:
            self.text = F.text
        except Exception:  # noqa: BLE001
            self.text = None

    async def __call__(self, message) -> bool:
        text = str(getattr(message, "text", "") or "").strip()
        if not text or text.startswith("/") or len(text) > 32:
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", text):
            return False
        promo = _promo_active(text.upper())
        return promo is not None


# ---------------------------------------------------------------- квест друзей
def _quest_count(referrer_id: int) -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (int(referrer_id),)
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _quest_mark(referrer_id: int, milestone: int) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute(
            "INSERT OR IGNORE INTO referral_quest (referrer_id, milestone, granted_at) VALUES (?, ?, ?)",
            (int(referrer_id), int(milestone), datetime.now(timezone.utc).isoformat()),
        )
        changed = conn.total_changes
        conn.commit()
        return bool(changed)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


async def _quest_check(referrer_id: int) -> None:
    friends, days = quest_reward()
    if friends < 1 or days < 1:
        return
    count = _quest_count(referrer_id)
    if count < friends:
        return
    milestone = (count // friends) * friends
    step = _quest_mark(referrer_id, milestone)
    if not step:
        return
    ok, reason = await grant_days(referrer_id, days)
    text = (
        "🏆 <b>Квест выполнен!</b>\n\n"
        f"Вы пригласили <b>{milestone}</b> друзей — начислено <b>+{days} дн.</b> к подписке.\n"
        "Приглашайте дальше: за каждые "
        f"<b>{friends}</b> друзей — ещё <b>+{days} дн.</b>"
    )
    if not ok:
        text = (
            "🏆 <b>Квест выполнен!</b>\n\n"
            f"Приглашено друзей: <b>{milestone}</b>, но бонус +{days} дн. не начислился "
            f"({reason}).\nНапишите в поддержку — начислим вручную."
        )
    await notify_user(int(referrer_id), text)


async def notify_user(user_id: int, text: str) -> None:
    """Сообщение пользователю: через сервис уведомлений, иначе отдельным клиентом."""
    try:
        from app.services import notifications

        sender = getattr(notifications, "send_message", None)
        if callable(sender):
            await sender(int(user_id), text)
            return
        inner = getattr(notifications, "bot", None) or getattr(notifications, "_bot", None)
        if inner is not None:
            await inner.send_message(int(user_id), text)
            return
    except Exception as exc:  # noqa: BLE001
        log.debug("usertools: notifications не отправил (%s)", exc)
    token = _env("BOT_TOKEN")
    if not token:
        return
    try:
        from aiogram import Bot

        async with Bot(token=token) as bot:
            await bot.send_message(int(user_id), text)
    except Exception as exc:  # noqa: BLE001
        log.debug("usertools: не уведомил напрямую (%s)", exc)


def patch_referral_register() -> None:
    """Оборачиваем register из referral.py: после успешного приглашения — квест."""
    try:
        from app.services import referral as referral_service
    except Exception as exc:  # noqa: BLE001
        log.debug("usertools: referral недоступен (%s)", exc)
        return
    if getattr(referral_service, "_litenergy_quest_patched", False):
        return
    original = getattr(referral_service, "register", None)
    if not callable(original):
        return
    async def register(referrer_id, new_user_id, days):
        result = await original(referrer_id, new_user_id, days)
        if result in ("ok", "pending"):
            try:
                await _quest_check(int(referrer_id))
            except Exception as exc:  # noqa: BLE001
                log.debug("usertools: квест не отработал (%s)", exc)
        return result

    referral_service.register = register
    referral_service._litenergy_quest_patched = True
    log.info("usertools: квест друзей подключён")


# ---------------------------------------------------------------- меню
def _menu_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🐛 Мои устройства", callback_data=DEV_CALLBACK)]


def _promo_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🎟 Промокод", callback_data=PROMO_CALLBACK)]


def patch_menu() -> None:
    """Добавляем строку «Мои устройства» в меню входа (без дублей)."""
    import importlib

    modules = (
        "app.services.notifications",
        "app.telegram.handlers_start",
        "app.telegram.handlers_subscription",
    )
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        func = getattr(module, "menu_kb", None)
        if not callable(func) or getattr(module, MENU_PATCH_FLAG, False):
            continue

        def make_wrapper(original):
            def menu_kb():
                kb = original()
                if kb is None or not getattr(kb, "inline_keyboard", None):
                    return kb
                try:
                    rows = [list(row) for row in kb.inline_keyboard]
                    datas = {
                        str(getattr(button, "callback_data", "") or "")
                        for row in rows
                        for button in row
                    }
                    if DEV_CALLBACK not in datas:
                        rows.append(_menu_row())
                    if PROMO_CALLBACK not in datas:
                        rows.append(_promo_row())
                    return InlineKeyboardMarkup(inline_keyboard=rows)
                except Exception:  # noqa: BLE001
                    return kb

            return menu_kb

        try:
            setattr(module, "menu_kb", make_wrapper(func))
            setattr(module, MENU_PATCH_FLAG, True)
        except Exception:  # noqa: BLE001
            continue


# ---------------------------------------------------------------- обработчики
@router.callback_query(F.data == DEV_CALLBACK)
async def cb_devices(cb) -> None:
    user = getattr(cb, "from_user", None)
    message = getattr(cb, "message", None)
    if user is None or message is None:
        return
    text, kb = await devices_text(int(user.id))
    try:
        from app.telegram import look as _look

        with _look.quiet():
            await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        try:
            await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            log.exception("usertools: не показал устройства")
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == PROMO_CALLBACK)
async def cb_promo(cb) -> None:
    try:
        await cb.answer(PROMPT.replace("<b>", "").replace("</b>", "")[:190], show_alert=True)
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith(DEV_DELETE_PREFIX))
async def cb_device_delete(cb) -> None:
    user = getattr(cb, "from_user", None)
    token = str(cb.data)[len(DEV_DELETE_PREFIX):]
    if user is None:
        return
    device, devices = _recall(int(user.id), token)
    if device is None:
        try:
            await cb.answer("Список устарел — нажмите «Обновить»", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    hwid = str(device.get("hwid") or "")
    panel_id = await _panel_user_id(int(user.id))
    if panel_id is None or not hwid:
        try:
            await cb.answer("Не нашёл устройство в панели", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        await _api("POST", "/api/hwid/devices/delete", {"userId": int(panel_id), "hwid": hwid})
    except Exception as exc:  # noqa: BLE001
        log.warning("usertools: не отвязал устройство (%s)", exc)
        try:
            await cb.answer("Не удалось отвязать — попробуйте позже", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    label = _short(device.get("platform") or device.get("deviceModel") or "устройство", 24)
    message = getattr(cb, "message", None)
    if message is not None:
        text, kb = await devices_text(int(user.id))
        text = f"✅ Устройство <b>{html.escape(label)}</b> отвязано.\n\n" + text
        try:
            from app.telegram import look as _look

            with _look.quiet():
                await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            try:
                await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
            except Exception:  # noqa: BLE001
                pass
    try:
        await cb.answer("Готово")
    except Exception:  # noqa: BLE001
        pass


@router.message(PromoText())
async def on_promo_text(message) -> None:
    user = getattr(message, "from_user", None)
    code = str(getattr(message, "text", "") or "").strip().upper()
    if user is None or not code:
        return
    ok, text = await redeem(code, int(user.id))
    try:
        await message.answer(text, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        log.exception("usertools: не ответил на промокод")
    if ok:
        try:
            from app.services import notifications

            for name in ("notify_admin",):
                handler = getattr(notifications, name, None)
                if callable(handler):
                    await handler(
                        "🎟 Промокод использован\n"
                        f"Код: `{code}`\nTelegram ID: `{int(user.id)}`"
                    )
                    break
        except Exception:  # noqa: BLE001
            pass


@router.message(F.text == "/devices")
async def cmd_devices(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None:
        return
    text, kb = await devices_text(int(user.id))
    try:
        from app.telegram import look as _look

        with _look.quiet():
            await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(F.text.startswith("/promo_add"))
async def cmd_promo_add(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) not in admin_ids():
        await message.answer("Команда только для админа.")
        return
    parts = str(getattr(message, "text", "") or "").split()
    if len(parts) < 3:
        await message.answer("Формат: /promo_add КОД ДНЕЙ [ЛИМИТ]\nНапример: /promo_add PROMO10 10 0")
        return
    code, days_raw = parts[1], parts[2]
    limit_raw = parts[3] if len(parts) > 3 else "0"
    try:
        days = int(days_raw)
        limit = int(limit_raw)
    except ValueError:
        await message.answer("Дни и лимит — числа.")
        return
    ok, text = promo_add(code, days, limit)
    await message.answer(("✅ " if ok else "⚠️ ") + text)


@router.message(F.text == "/promo_list")
async def cmd_promo_list(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) not in admin_ids():
        await message.answer("Команда только для админа.")
        return
    rows = promo_list()
    if not rows:
        await message.answer("Промокодов нет. Добавить: /promo_add КОД ДНЕЙ [ЛИМИТ]")
        return
    lines = ["🎟 <b>Промокоды</b>", ""]
    for row in rows:
        state = "вкл" if row.get("active") else "выкл"
        limit = row.get("max_uses") or "∞"
        lines.append(f"• <code>{row.get('code')}</code> — {row.get('days')} дн., "
                     f"использован {row.get('uses')} из {limit}, {state}")
    lines.append("")
    lines.append("Выключить: /promo_off КОД")
    await message.answer("\n".join(lines))


@router.message(F.text.startswith("/promo_off"))
async def cmd_promo_off(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) not in admin_ids():
        await message.answer("Команда только для админа.")
        return
    parts = str(getattr(message, "text", "") or "").split()
    if len(parts) < 2:
        await message.answer("Формат: /promo_off КОД")
        return
    ok, text = promo_off(parts[1])
    await message.answer(("✅ " if ok else "⚠️ ") + text)


def install(dp) -> None:
    """Подключает устройства, промокоды и квест друзей."""
    if dp is None or not enabled():
        return
    if getattr(dp, INSTALL_FLAG, False):
        return
    ensure_tables()
    patch_referral_register()
    patch_menu()
    try:
        dp.include_router(router)
    except Exception as exc:  # noqa: BLE001
        log.warning("usertools: роутер не подключился (%s)", exc)
        return
    try:
        setattr(dp, INSTALL_FLAG, True)
    except Exception:  # noqa: BLE001
        pass
    log.info("LitEnergy usertools %s: устройства, промокоды, квест друзей", MODULE_VERSION)
