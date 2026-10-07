"""LitEnergy: баланс в боте — пополнение кошелька и оплата подписки с баланса.

Возможности:
  * 💰 «Баланс» — сколько на кошельке, история операций;
  * ➕ пополнение через YooMoney (те же авто-подтверждение и кнопка «Проверить оплату»);
  * ⚡ оплата тарифов и дополнительных устройств прямо с баланса — без комиссии 3%;
  * /balance — экран баланса, /balance_add ID СУММА — начисление админом.

Деньги считаются в копейках (целые числа), валюта — рубли.

Подключается через install(dp); повторный вызов безопасен.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger("app.balance")

MODULE_VERSION = "2026-10-07.1"

BAL_CALLBACK = "lit:bal"
TOP_CALLBACK = "bal:top"
TP_PREFIX = "bal:tp:"
CUSTOM_CALLBACK = "bal:custom"
PAY_CALLBACK = "bal:pay"
PAY_PREFIX = "bal:pay:"
TOPUP_CODE = "balance"
INSTALL_FLAG = "_litenergy_balance_installed"
MENU_FLAG = "_litenergy_balance_menu"
PATCH_FLAG = "_litenergy_balance_orders_patched"
KB_FLAG = "_litenergy_balance_tariffs_patched"

DEFAULT_MIN_TOPUP = 50
MAX_TOPUP = 15000
CUSTOM_TTL = 600.0

router = Router(name="litenergy-balance")


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
    return _env("BALANCE_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


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


def min_topup() -> int:
    try:
        return max(10, int(_env("BALANCE_MIN_TOPUP", str(DEFAULT_MIN_TOPUP))))
    except ValueError:
        return DEFAULT_MIN_TOPUP


def topup_presets() -> list[int]:
    raw = _env("BALANCE_TOPUP_PRESETS", "100,200,300,500")
    values: list[int] = []
    for chunk in re.split(r"[,\s;]+", raw):
        chunk = chunk.strip()
        if chunk.isdigit():
            amount = int(chunk)
            if min_topup() <= amount <= MAX_TOPUP and amount not in values:
                values.append(amount)
    return values or [100, 200, 300, 500]


# ---------------------------------------------------------------- деньги
def _money(kop: int) -> str:
    """12345 -> '123,45 ₽', 15000 -> '150 ₽'."""
    kop = int(kop)
    rub, rest = divmod(abs(kop), 100)
    sign = "-" if kop < 0 else ""
    if rest == 0:
        return f"{sign}{rub} ₽"
    return f"{sign}{rub},{rest:02d} ₽"


def _rub_to_kop(value) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_rub_text(text: str) -> Decimal | None:
    raw = str(text or "").strip().replace("₽", "").replace("руб", "").replace(" ", "")
    raw = raw.replace(",", ".")
    if not re.fullmatch(r"\d{1,6}(\.\d{1,2})?", raw):
        return None
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if amount < min_topup() or amount > MAX_TOPUP:
        return None
    return amount


# ---------------------------------------------------------------- база
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
        log.warning("balance: база недоступна (%s)", exc)
        return None


def ensure_tables() -> None:
    conn = _connect()
    if conn is None:
        return
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                telegram_id INTEGER PRIMARY KEY,
                balance_kop INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS wallet_ops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount_kop INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                order_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS wallet_ops_user ON wallet_ops (telegram_id, id DESC);
            """
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.warning("balance: не создал таблицы (%s)", exc)
    finally:
        conn.close()


def balance_kop(telegram_id: int) -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT balance_kop FROM wallets WHERE telegram_id = ?", (int(telegram_id),)
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _log_op(conn: sqlite3.Connection, telegram_id: int, kind: str, amount_kop: int, note: str, order_id: str) -> None:
    conn.execute(
        "INSERT INTO wallet_ops (telegram_id, kind, amount_kop, note, order_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (int(telegram_id), str(kind), int(amount_kop), str(note)[:200], str(order_id)[:64],
         datetime.now(timezone.utc).isoformat()),
    )


def _credit(telegram_id: int, kop: int, *, kind: str = "topup", note: str = "", order_id: str = "") -> bool:
    """Начисляет копейки на кошелёк (создаёт его при необходимости)."""
    kop = int(kop)
    if kop <= 0:
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        conn.execute(
            "INSERT INTO wallets (telegram_id, balance_kop, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(telegram_id) DO UPDATE SET balance_kop = balance_kop + excluded.balance_kop,"
            " updated_at = excluded.updated_at",
            (int(telegram_id), kop, datetime.now(timezone.utc).isoformat()),
        )
        _log_op(conn, telegram_id, kind, kop, note, order_id)
        conn.commit()
        return True
    except sqlite3.Error as exc:
        log.warning("balance: не начислил (%s)", exc)
        return False
    finally:
        conn.close()


def _debit(telegram_id: int, kop: int, *, kind: str = "spend", note: str = "", order_id: str = "") -> bool:
    """Списывает копейки атомарно: не хватает — False, ничего не меняется."""
    kop = int(kop)
    if kop <= 0:
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.execute(
            "UPDATE wallets SET balance_kop = balance_kop - ?, updated_at = ?"
            " WHERE telegram_id = ? AND balance_kop >= ?",
            (kop, datetime.now(timezone.utc).isoformat(), int(telegram_id), kop),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _log_op(conn, telegram_id, kind, -kop, note, order_id)
        conn.commit()
        return True
    except sqlite3.Error as exc:
        log.warning("balance: не списал (%s)", exc)
        return False
    finally:
        conn.close()


def history(telegram_id: int, limit: int = 5) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT kind, amount_kop, note, order_id, created_at FROM wallet_ops"
            " WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
            (int(telegram_id), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _cancel_order(order_id: str) -> None:
    conn = _connect()
    if conn is None:
        return
    try:
        conn.execute("UPDATE orders SET status = 'canceled' WHERE order_id = ?", (str(order_id),))
        conn.commit()
    except sqlite3.Error as exc:
        log.debug("balance: не отменил заказ %s (%s)", order_id, exc)
    finally:
        conn.close()


# ---------------------------------------------------------------- уведомления
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
        log.debug("balance: notifications не отправил (%s)", exc)
    token = _env("BOT_TOKEN")
    if not token:
        return
    try:
        from aiogram import Bot

        async with Bot(token=token) as bot:
            await bot.send_message(int(user_id), text)
    except Exception as exc:  # noqa: BLE001
        log.debug("balance: не уведомил напрямую (%s)", exc)


async def notify_admin(text: str) -> None:
    try:
        from app.services import notifications

        sender = getattr(notifications, "notify_admin", None)
        if callable(sender):
            await sender(text)
    except Exception as exc:  # noqa: BLE001
        log.debug("balance: админ не уведомлён (%s)", exc)


# ---------------------------------------------------------------- патч заказов
def patch_orders() -> None:
    """Оплату заказа на пополнение превращаем в начисление на кошелёк.

    Заказы обычных тарифов и устройств продолжают обрабатываться как раньше.
    """
    try:
        from app.services import orders as orders_service
    except Exception as exc:  # noqa: BLE001
        log.debug("balance: orders недоступны (%s)", exc)
        return
    if getattr(orders_service, PATCH_FLAG, False):
        return
    original = getattr(orders_service, "process_successful_payment", None)
    if not callable(original):
        log.warning("balance: в orders нет process_successful_payment — патч пропущен")
        return

    async def process_successful_payment(order, *, operation_id, amount, raw_hash=""):
        if str(getattr(order, "tariff_code", "")) != TOPUP_CODE:
            return await original(order, operation_id=operation_id, amount=amount, raw_hash=raw_hash)

        claimed = await orders_service.claim_order(
            order, operation_id=operation_id, amount=amount, raw_hash=raw_hash
        )
        if claimed is None:
            current = await orders_service.get_order(order.order_id)
            if current is not None and getattr(current, "status", "") == "paid":
                return True, "already"
            return False, "order_not_found"

        topup = _rub_to_kop(getattr(order, "expected_price", 0)) or _rub_to_kop(amount)
        credited = _credit(
            int(order.telegram_id),
            topup,
            kind="topup",
            note=f"Пополнение баланса по заказу {order.order_id}",
            order_id=order.order_id,
        )
        if not credited:
            # база недоступна — не теряем платёж: заказ остаётся paid, деньги зачислит повтор
            await notify_admin(
                "⚠️ <b>Пополнение получено, но не зачислено</b>\n"
                f"Заказ: <code>{order.order_id}</code>\n"
                f"Telegram ID: <code>{int(order.telegram_id)}</code>\n"
                f"Сумма: {_money(topup)}\n"
                "Проверьте базу: баланс в боте."
            )
            return True, "deferred"

        try:
            await orders_service.mark_event_processed(operation_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("balance: mark_event_processed не прошёл (%s)", exc)

        await notify_user(
            int(order.telegram_id),
            "💰 <b>Баланс пополнен</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"Зачислено: <b>{_money(topup)}</b>\n"
            f"Баланс: <b>{_money(balance_kop(int(order.telegram_id)))}</b>\n\n"
            "Оплатить подписку с баланса — без комиссии: кнопка «⚡ Оплатить с баланса» в тарифах.",
        )
        await notify_admin(
            "💰 <b>Пополнение баланса</b>\n"
            f"Telegram ID: <code>{int(order.telegram_id)}</code>\n"
            f"Зачислено: {_money(topup)}"
        )
        return True, "ok"

    orders_service.process_successful_payment = process_successful_payment
    setattr(orders_service, PATCH_FLAG, True)

    # админская «Переотправить» не должна выдавать подписку за пополнение
    original_reissue = getattr(orders_service, "ensure_provisioned_and_notify", None)
    if callable(original_reissue) and not getattr(orders_service, "_litenergy_balance_reissue", False):
        async def ensure_provisioned_and_notify(order):
            if str(getattr(order, "tariff_code", "")) == TOPUP_CODE:
                return "topup"
            return await original_reissue(order)

        orders_service.ensure_provisioned_and_notify = ensure_provisioned_and_notify
        setattr(orders_service, "_litenergy_balance_reissue", True)

    log.info("balance: заказы на пополнение подключены")


# ---------------------------------------------------------------- оплата с баланса
async def pay_from_balance(telegram_id: int, code: str) -> tuple[bool, str]:
    """Оплата тарифа или устройства с баланса. (ok, текст для клиента)"""
    from app.services import device_slots, orders as orders_service
    from app.services.tariffs import format_price, get_tariff

    if str(code) == getattr(device_slots, "DEVICE_CODE", "device"):
        days = 0
        price = Decimal(str(device_slots.slot_price()))
        title = "Дополнительное устройство"
    else:
        tariff = await get_tariff(str(code))
        if tariff is None or not getattr(tariff, "enabled", False):
            return False, "Тариф недоступен. Обновите список: 🛒 Тарифы."
        days = int(tariff.days)
        price = Decimal(str(tariff.price))
        title = f"Тариф «{tariff.title}»"

    need = _rub_to_kop(price)
    have = balance_kop(int(telegram_id))
    if need <= 0:
        return False, "Не удалось определить сумму. Напишите в поддержку."
    if have < need:
        return False, (
            f"На балансе <b>{_money(have)}</b>, а нужно <b>{_money(need)}</b>.\n"
            "Пополните баланс — это займёт минуту: 💰 Баланс → ➕ Пополнить."
        )

    order = await orders_service.create_order(
        int(telegram_id), tariff_code=str(code), tariff_days=days, price=price
    )
    if not _debit(
        int(telegram_id),
        need,
        kind="spend",
        note=f"{title} (заказ {order.order_id})",
        order_id=order.order_id,
    ):
        _cancel_order(order.order_id)
        return False, "Не хватило средств в момент списания — попробуйте ещё раз."

    ok, result = await orders_service.process_successful_payment(
        order,
        operation_id=f"bal-{order.order_id}",
        amount=price,
        raw_hash="balance",
    )
    rest = _money(balance_kop(int(telegram_id)))

    if ok and result in ("ok", "already"):
        return True, (
            f"✅ <b>{title} оплачено с баланса</b>\n\n"
            f"Списано: <b>{_money(need)}</b>\n"
            f"Остаток: <b>{rest}</b>\n\n"
            "Подписка активирована — карточка в «📱 Моя подписка»."
        )
    if ok and result == "deferred":
        return False, (
            "💳 Оплата с баланса принята, но активация задерживается.\n"
            "Деньги не потеряются: через пару минут всё выдастся автоматически.\n"
            "Если подписка не появилась за 10 минут — напишите в поддержку."
        )

    # заказ не обработан — возвращаем деньги на баланс
    _credit(
        int(telegram_id),
        need,
        kind="refund",
        note=f"Возврат за неудавшийся заказ {order.order_id}",
        order_id=order.order_id,
    )
    _cancel_order(order.order_id)
    await notify_admin(
        "⚠️ <b>Оплата с баланса не прошла</b>\n"
        f"Заказ: <code>{order.order_id}</code>\n"
        f"Telegram ID: <code>{int(telegram_id)}</code>\n"
        f"Сумма: {_money(need)} — возвращена на баланс\n"
        f"Код результата: {result}"
    )
    return False, (
        "Не удалось активировать подписку — деньги вернулись на баланс.\n"
        f"Остаток: <b>{rest}</b>. Попробуйте ещё раз или напишите в поддержку."
    )


# ---------------------------------------------------------------- экраны
def balance_text(telegram_id: int) -> str:
    rows = history(telegram_id, limit=5)
    lines = [
        "💰 <b>Баланс</b>",
        "━━━━━━━━━━━━━━━",
        "",
        f"Доступно: <b>{_money(balance_kop(telegram_id))}</b>",
        "",
    ]
    if rows:
        lines.append("Последние операции:")
        names = {"topup": "Пополнение", "spend": "Оплата", "refund": "Возврат", "admin": "Начисление"}
        for row in rows:
            amount = int(row.get("amount_kop") or 0)
            sign = "+" if amount >= 0 else "−"
            title = names.get(str(row.get("kind")), "Операция")
            date = str(row.get("created_at") or "")[:10]
            lines.append(f"• {title}: {sign}{_money(abs(amount))} ({date})")
    else:
        lines.append("Операций пока не было.")
    lines += [
        "",
        "С баланса подписка оплачивается без комиссии платёжной системы.",
        "Пополнить: кнопка ниже (от " + str(min_topup()) + " ₽).",
    ]
    return "\n".join(lines)


def balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data=TOP_CALLBACK)],
            [InlineKeyboardButton(text="⚡ Оплатить с баланса", callback_data=PAY_CALLBACK)],
            [InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:back")],
        ]
    )


def topup_kb() -> InlineKeyboardMarkup:
    presets = topup_presets()
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for amount in presets:
        pair.append(
            InlineKeyboardButton(text=f"💳 {amount} ₽", callback_data=f"{TP_PREFIX}{amount}")
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="✏️ Своя сумма", callback_data=CUSTOM_CALLBACK)])
    rows.append([InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_text() -> str:
    presets = ", ".join(f"{amount} ₽" for amount in topup_presets())
    return (
        "➕ <b>Пополнение баланса</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"Быстрые суммы: {presets}.\n"
        f"Минимум — {min_topup()} ₽, можно ввести свою сумму.\n\n"
        "Оплата приходит на баланс автоматически за 1–2 минуты.\n"
        "С баланса подписка оплачивается без комиссии 3%."
    )


async def pay_list_text(telegram_id: int) -> str:
    from app.services import device_slots
    from app.services.tariffs import format_price, get_tariffs

    have = balance_kop(int(telegram_id))
    lines = [
        "⚡ <b>Оплата с баланса</b>",
        "━━━━━━━━━━━━━━━",
        "",
        f"Баланс: <b>{_money(have)}</b> (без комиссии)",
        "",
        "Тарифы:",
    ]
    try:
        tariffs = await get_tariffs()
    except Exception as exc:  # noqa: BLE001
        log.debug("balance: тарифы не получены (%s)", exc)
        tariffs = []
    for tariff in tariffs:
        need = _rub_to_kop(tariff.price)
        mark = "✅" if have >= need else "•"
        lines.append(f"{mark} {tariff.title} — {format_price(tariff.price)}")
    try:
        device_price = Decimal(str(device_slots.slot_price()))
    except Exception:  # noqa: BLE001
        device_price = Decimal("0")
    if device_price:
        need = _rub_to_kop(device_price)
        mark = "✅" if have >= need else "•"
        lines.append(f"{mark} Дополнительное устройство — {format_price(device_price)}")
    lines += ["", "✅ — хватает баланса, нажмите кнопку ниже."]
    return "\n".join(lines)


async def pay_list_kb(telegram_id: int) -> InlineKeyboardMarkup:
    from app.services import device_slots
    from app.services.tariffs import format_price, get_tariffs

    have = balance_kop(int(telegram_id))
    rows: list[list[InlineKeyboardButton]] = []
    try:
        tariffs = await get_tariffs()
    except Exception:  # noqa: BLE001
        tariffs = []
    for tariff in tariffs:
        need = _rub_to_kop(tariff.price)
        mark = "✅" if have >= need else "•"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {tariff.title} — {format_price(tariff.price)}",
                    callback_data=f"{PAY_PREFIX}{tariff.code}",
                )
            ]
        )
    try:
        device_price = Decimal(str(device_slots.slot_price()))
        code = getattr(device_slots, "DEVICE_CODE", "device")
    except Exception:  # noqa: BLE001
        device_price, code = Decimal("0"), ""
    if device_price and code:
        need = _rub_to_kop(device_price)
        mark = "✅" if have >= need else "•"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} Устройство — {format_price(device_price)}",
                    callback_data=f"{PAY_PREFIX}{code}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Пополнить", callback_data=TOP_CALLBACK)])
    rows.append([InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(cb, text: str, kb: InlineKeyboardMarkup | None) -> None:
    message = getattr(cb, "message", None)
    try:
        if message is not None:
            await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
            return
    except Exception:  # noqa: BLE001
        pass
    user = getattr(cb, "from_user", None)
    if user is not None:
        await notify_user(int(user.id), text)


# ---------------------------------------------------------------- обработчики
@router.callback_query(F.data == BAL_CALLBACK)
async def cb_balance(cb) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    try:
        await _show(cb, balance_text(int(user.id)), balance_kb())
    finally:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data == TOP_CALLBACK)
async def cb_topup(cb) -> None:
    try:
        await _show(cb, topup_text(), topup_kb())
    finally:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass


_pending: dict[int, float] = {}


def _pending_topup(user_id: int) -> bool:
    moment = _pending.get(int(user_id))
    if moment is None:
        return False
    if time.monotonic() - moment > CUSTOM_TTL:
        _pending.pop(int(user_id), None)
        return False
    return True


async def _start_topup(cb, amount: Decimal) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    from app.services import orders as orders_service
    from app.services.yoomoney import build_payment_url, display_amount

    order = await orders_service.create_order(
        int(user.id), tariff_code=TOPUP_CODE, tariff_days=0, price=Decimal(amount)
    )
    pay_amount = display_amount(order.expected_price)
    text = (
        "🧾 <b>Пополнение баланса</b>\n\n"
        f"Сумма: <b>{_money(_rub_to_kop(order.expected_price))}</b>\n"
        f"Заказ: <code>{order.order_id}</code>\n\n"
        "1️⃣ Нажмите «Оплатить»\n"
        "2️⃣ Вернитесь и нажмите «Проверить оплату»\n"
        "3️⃣ Зачисление — за 1–2 минуты, автоматически"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {_money(_rub_to_kop(pay_amount))}",
                    url=build_payment_url(order),
                )
            ],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"chk:{order.order_id}")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)],
        ]
    )
    try:
        await _show(cb, text, kb)
    except Exception:  # noqa: BLE001
        await notify_user(int(user.id), text + "\n\n" + build_payment_url(order))


@router.callback_query(F.data.startswith(TP_PREFIX))
async def cb_topup_amount(cb) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    raw = str(cb.data)[len(TP_PREFIX):].strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        await cb.answer("Не понял сумму", show_alert=True)
        return
    try:
        await _start_topup(cb, amount)
    except Exception as exc:  # noqa: BLE001
        log.warning("balance: пополнение не создалось (%s)", exc)
        await cb.answer("Не удалось создать платёж — попробуйте позже", show_alert=True)
        return
    try:
        await cb.answer("Счёт создан")
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == CUSTOM_CALLBACK)
async def cb_custom(cb) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    _pending[int(user.id)] = time.monotonic()
    try:
        await _show(
            cb,
            "✏️ <b>Своя сумма</b>\n\n"
            f"Отправьте сумму одним сообщением — например: <code>150</code>\n"
            f"Минимум {min_topup()} ₽, максимум {MAX_TOPUP} ₽.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)],
                ]
            ),
        )
    finally:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data == PAY_CALLBACK)
async def cb_pay(cb) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    try:
        text = await pay_list_text(int(user.id))
        kb = await pay_list_kb(int(user.id))
        await _show(cb, text, kb)
    finally:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith(PAY_PREFIX))
async def cb_pay_code(cb) -> None:
    user = getattr(cb, "from_user", None)
    if user is None:
        return
    code = str(cb.data)[len(PAY_PREFIX):].strip()
    try:
        ok, text = await pay_from_balance(int(user.id), code)
    except Exception as exc:  # noqa: BLE001
        log.exception("balance: оплата с баланса не прошла")
        ok, text = False, "Ошибка оплаты — попробуйте позже или напишите в поддержку."
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Моя подписка", callback_data="lit:vpn")],
            [InlineKeyboardButton(text="🛒 Тарифы", callback_data="menu:shop")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)],
        ]
    )
    try:
        await _show(cb, text, kb)
        await cb.answer("Готово" if ok else "Смотрите сообщение", show_alert=not ok)
    except Exception:  # noqa: BLE001
        await notify_user(int(user.id), text)


@router.message(F.text.regexp(r"^\d{2,6}([.,]\d{1,2})?\s*(₽|руб\.?)?$"))
async def on_custom_amount(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None or not _pending_topup(int(user.id)):
        return
    amount = _parse_rub_text(str(getattr(message, "text", "") or ""))
    if amount is None:
        await message.answer(
            f"Нужна сумма от {min_topup()} до {MAX_TOPUP} ₽ одним числом, например: 150"
        )
        return
    _pending.pop(int(user.id), None)
    await _start_topup_message(message, amount)


async def _start_topup_message(message, amount: Decimal) -> None:
    from app.services import orders as orders_service
    from app.services.yoomoney import build_payment_url

    order = await orders_service.create_order(
        int(message.from_user.id), tariff_code=TOPUP_CODE, tariff_days=0, price=Decimal(amount)
    )
    text = (
        "🧾 <b>Пополнение баланса</b>\n\n"
        f"Сумма: <b>{_money(_rub_to_kop(order.expected_price))}</b>\n"
        f"Заказ: <code>{order.order_id}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {_money(_rub_to_kop(order.expected_price))}",
                    url=build_payment_url(order),
                )
            ],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"chk:{order.order_id}")],
        ]
    )
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(F.text == "/balance")
async def cmd_balance(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None:
        return
    await message.answer(
        balance_text(int(user.id)), reply_markup=balance_kb(), disable_web_page_preview=True
    )


@router.message(F.text.startswith("/balance_add"))
async def cmd_balance_add(message) -> None:
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) not in admin_ids():
        await message.answer("Команда только для админа.")
        return
    parts = str(getattr(message, "text", "") or "").split()
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        await message.answer("Формат: /balance_add TELEGRAM_ID СУММА\nНапример: /balance_add 8346538289 300")
        return
    target = int(parts[1])
    amount = _parse_rub_text(parts[2].replace("₽", ""))
    if amount is None:
        await message.answer(f"Сумма — от {min_topup()} до {MAX_TOPUP} ₽.")
        return
    kop = _rub_to_kop(amount)
    if not _credit(target, kop, kind="admin", note=f"Начисление админом {int(user.id)}"):
        await message.answer("Не удалось начислить (база недоступна).")
        return
    await message.answer(
        f"✅ <code>{target}</code>: +{_money(kop)}, баланс {_money(balance_kop(target))}"
    )
    await notify_user(
        target,
        "💰 <b>Баланс пополнен</b>\n\n"
        f"Начислено: <b>{_money(kop)}</b>\n"
        f"Баланс: <b>{_money(balance_kop(target))}</b>\n\n"
        "Оплатить подписку с баланса: тарифы → «⚡ Оплатить с баланса».",
    )


# ---------------------------------------------------------------- меню и тарифы
def _balance_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="💰 Баланс", callback_data=BAL_CALLBACK)]


def patch_menu() -> None:
    """Строка «💰 Баланс» в меню входа (сразу после тарифов, без дублей)."""
    import importlib

    modules = (
        "app.services.notifications",
        "app.telegram.handlers_start",
        "app.telegram.handlers_subscription",
        "app.telegram.handlers_shop",
        "app.telegram.handlers_admin",
        "app.telegram.referral_extra",
    )
    for name in modules:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        func = getattr(module, "menu_kb", None)
        if not callable(func) or getattr(module, MENU_FLAG, False):
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
                    if BAL_CALLBACK in datas:
                        return InlineKeyboardMarkup(inline_keyboard=rows)
                    place = None
                    for index, row in enumerate(rows):
                        if "menu:shop" in {
                            str(getattr(button, "callback_data", "") or "") for button in row
                        }:
                            place = index + 1
                            break
                    if place is None:
                        rows.append(_balance_row())
                    else:
                        rows.insert(place, _balance_row())
                    return InlineKeyboardMarkup(inline_keyboard=rows)
                except Exception:  # noqa: BLE001
                    return kb

            return menu_kb

        try:
            setattr(module, "menu_kb", make_wrapper(func))
            setattr(module, MENU_FLAG, True)
        except Exception:  # noqa: BLE001
            continue


def patch_tariffs_kb() -> None:
    """Кнопка «⚡ Оплатить с баланса» на экране тарифов."""
    try:
        from app.telegram import handlers_shop as shop
    except Exception as exc:  # noqa: BLE001
        log.debug("balance: handlers_shop недоступны (%s)", exc)
        return
    original = getattr(shop, "_tariffs_kb", None)
    if not callable(original) or getattr(shop, KB_FLAG, False):
        return

    async def _tariffs_kb():
        kb = await original()
        if kb is None or not getattr(kb, "inline_keyboard", None):
            return kb
        try:
            rows = [list(row) for row in kb.inline_keyboard]
            datas = {
                str(getattr(button, "callback_data", "") or "") for row in rows for button in row
            }
            if PAY_CALLBACK in datas:
                return InlineKeyboardMarkup(inline_keyboard=rows)
            row = [InlineKeyboardButton(text="⚡ Оплатить с баланса", callback_data=PAY_CALLBACK)]
            place = len(rows)
            for index, item in enumerate(rows):
                if any(
                    str(getattr(button, "callback_data", "") or "").startswith("device")
                    or str(getattr(button, "callback_data", "") or "") == "buy:device"
                    for button in item
                ):
                    place = index
                    break
            rows.insert(place, row)
            return InlineKeyboardMarkup(inline_keyboard=rows)
        except Exception:  # noqa: BLE001
            return kb

    try:
        setattr(shop, "_tariffs_kb", _tariffs_kb)
        setattr(shop, KB_FLAG, True)
    except Exception:  # noqa: BLE001
        pass


def install(dp) -> None:
    """Подключает баланс: кошелёк, пополнение, оплата с баланса."""
    if dp is None or not enabled():
        return
    if getattr(dp, INSTALL_FLAG, False):
        return
    ensure_tables()
    patch_orders()
    patch_menu()
    patch_tariffs_kb()
    try:
        dp.include_router(router)
    except Exception as exc:  # noqa: BLE001
        log.warning("balance: роутер не подключился (%s)", exc)
        return
    try:
        setattr(dp, INSTALL_FLAG, True)
    except Exception:  # noqa: BLE001
        pass
    log.info("LitEnergy balance %s: кошелёк, пополнение, оплата с баланса", MODULE_VERSION)
