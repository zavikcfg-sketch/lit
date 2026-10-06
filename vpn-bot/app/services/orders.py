"""Заказы, идемпотентная фиксация оплат и выдача/продление подписок Remnawave."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import get_session
from app.models import Order, PaymentEvent, User
from app.services import notifications
from app.services.remnawave import (
    RemnaError,
    RemnaNotFound,
    get_remna,
)
from app.utils import parse_iso_utc, rand_hex, utcnow, valid_telegram_id

log = logging.getLogger("app.orders")


# --------------------------------------------------------------- генерация ID

def new_order_id() -> str:
    return f"ord_{rand_hex(16)}"


def new_label(telegram_id: int) -> str:
    # Формат: rw_<telegram_id>_<random>, пример: rw_8346538289_a91f3c
    return f"rw_{telegram_id}_{rand_hex(6)}"


# --------------------------------------------------------------- CRUD заказов

async def create_order(telegram_id: int, *, tariff_code: str, tariff_days: int, price: Decimal) -> Order:
    """Создаёт заказ со статусом pending. Label уникален (проверка на коллизию)."""
    for _ in range(5):
        label = new_label(telegram_id)
        async with get_session() as session:
            exists = (
                await session.execute(select(Order.id).where(Order.label == label))
            ).scalar_one_or_none()
            if exists:
                continue
            order = Order(
                order_id=new_order_id(),
                label=label,
                telegram_id=telegram_id,
                tariff_code=tariff_code,
                tariff_days=int(tariff_days),
                expected_price=price,
                status="pending",
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            return order
    raise RuntimeError("Не удалось сгенерировать уникальный label заказа")


async def get_order(order_id: str) -> Order | None:
    async with get_session() as session:
        return (
            await session.execute(select(Order).where(Order.order_id == order_id))
        ).scalar_one_or_none()


async def get_order_by_label(label: str) -> Order | None:
    async with get_session() as session:
        return (
            await session.execute(select(Order).where(Order.label == label))
        ).scalar_one_or_none()


async def list_orders_for(telegram_id: int, statuses: tuple[str, ...] = ("pending",)) -> list[Order]:
    async with get_session() as session:
        stmt = (
            select(Order)
            .where(Order.telegram_id == telegram_id, Order.status.in_(statuses))
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        return list((await session.execute(stmt)).scalars().all())


async def get_local_user(telegram_id: int) -> User | None:
    async with get_session() as session:
        return (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()


# ------------------------------------------------- фиксация оплаты (идемпотентно)

async def event_exists(operation_id: str) -> bool:
    async with get_session() as session:
        return (
            await session.execute(
                select(PaymentEvent.id).where(PaymentEvent.operation_id == operation_id)
            )
        ).scalar_one_or_none() is not None


async def claim_order(order: Order, *, operation_id: str, amount: Decimal, raw_hash: str) -> Order | None:
    """Переводит заказ pending -> paid одним атомарным UPDATE.

    Возвращает обновлённый заказ или None, если заказ уже обработан/не найден.
    Повторное уведомление по тому же operation_id не выдаёт дни повторно.
    """
    if await event_exists(operation_id):
        return None
    async with get_session() as session:
        res = await session.execute(
            update(Order)
            .where(Order.order_id == order.order_id, Order.status == "pending")
            .values(
                status="paid",
                operation_id=operation_id,
                received_amount=amount,
                paid_at=utcnow(),
            )
        )
        if res.rowcount == 0:
            return None
        session.add(
            PaymentEvent(
                operation_id=operation_id,
                label=order.label,
                raw_hash=str(raw_hash or "")[:128],
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # второй процесс успел первым — это дубль
            await session.rollback()
            return None
        return (
            await session.execute(select(Order).where(Order.order_id == order.order_id))
        ).scalar_one()


async def mark_event_processed(operation_id: str) -> None:
    from sqlalchemy import update as _update

    async with get_session() as session:
        await session.execute(
            _update(PaymentEvent)
            .where(PaymentEvent.operation_id == operation_id)
            .values(processed_at=utcnow())
        )
        await session.commit()


# ------------------------------------------------- выдача подписки (Remnawave)

_tg_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def provision_user(telegram_id: int, days: int) -> User:
    """Создаёт или продлевает пользователя Remnawave и обновляет локальную запись.

    * Если пользователь уже есть (локально или в панели) — extend на N дней;
    * если нет — создаётся с username tg_<telegram_id>;
    * локальная запись пополняется remnawave_user_id / subscription_url / expire_at.
    """
    if not valid_telegram_id(telegram_id):
        raise ValueError("Некорректный Telegram ID")
    days = max(1, min(int(days), 3650))

    async with _locks_guard:
        lock = _tg_locks.setdefault(int(telegram_id), asyncio.Lock())
    async with lock:
        remna = get_remna()

        async with get_session() as session:
            local = (
                await session.execute(select(User).where(User.telegram_id == telegram_id))
            ).scalar_one_or_none()
            if local is None:
                local = User(telegram_id=int(telegram_id), status="ACTIVE")
                session.add(local)
                await session.commit()

            was_blocked = local.status == "BLOCKED"
            remna_id = local.remnawave_user_id

        if was_blocked and remna_id:
            try:
                await remna.enable_user(remna_id)
            except RemnaError as exc:
                log.warning("Не удалось включить пользователя %s в панели: %s", remna_id, exc)

        if remna_id:
            try:
                ruser = await remna.extend_user(remna_id, days)
            except RemnaNotFound:
                ruser = None
            if not ruser:
                # пользователь удалён в панели — создаём заново (локальную запись НЕ удаляем)
                ruser = await remna.create_user(
                    username=_username_for(telegram_id), telegram_id=telegram_id, days=days
                )
        else:
            existing = await remna.find_user_by_telegram_id(telegram_id)
            if existing and existing.get("id"):
                ruser = await remna.extend_user(str(existing["id"]), days)
            else:
                ruser = await remna.create_user(
                    username=_username_for(telegram_id), telegram_id=telegram_id, days=days
                )

        sub_url = str(ruser.get("subscriptionUrl") or "") or None
        if not sub_url:
            sub = await remna.get_subscription(str(ruser.get("id") or ""))
            if isinstance(sub, dict):
                sub_url = str(sub.get("subscriptionUrl") or sub.get("url") or "") or None

        await _ensure_squads(remna, ruser)

        expire = parse_iso_utc(ruser.get("expireAt"))

        async with get_session() as session:
            local = (
                await session.execute(select(User).where(User.telegram_id == telegram_id))
            ).scalar_one()
            local.remnawave_user_id = str(ruser.get("id") or local.remnawave_user_id or "")
            local.username = str(ruser.get("username") or local.username or _username_for(telegram_id))
            if sub_url:
                local.subscription_url = sub_url
            if expire:
                local.expire_at = expire
            local.status = "EXPIRED" if (expire and expire <= utcnow()) else "ACTIVE"
            await session.commit()
            return local


async def _ensure_squads(remna, ruser: dict) -> None:
    """Гарантирует, что пользователь состоит в сквадах из REMNAWAVE_DEFAULT_SQUADS.

    Нужен для пользователей, созданных до настройки сквадов: при ближайшем
    продлении/довыдаче они автоматически получат доступ к нодам.
    """
    squads = remna.default_squads
    if not squads or not ruser.get("id"):
        return
    current: list[str] = []
    for item in ruser.get("activeInternalSquads") or []:
        if isinstance(item, dict):
            uuid = item.get("uuid")
            if uuid:
                current.append(str(uuid))
        elif item:
            current.append(str(item))
    if set(current) >= set(squads):
        return
    merged = list(dict.fromkeys(current + squads))
    try:
        await remna.update_user(str(ruser["id"]), activeInternalSquads=merged)
        log.info("Пользователь %s добавлен в сквады: %s", ruser.get("username"), squads)
    except RemnaError as exc:
        log.warning("Не удалось добавить пользователя в сквады: %s", exc)
        await log_service_error(
            "remnawave",
            f"Пользователь {ruser.get('username')} не добавлен в сквады {squads}: {exc}",
            level="warning",
        )


def _username_for(telegram_id: int) -> str:
    from app.utils import make_username

    return make_username(telegram_id)


# --------------------------------------------- обработка успешного платежа

async def process_successful_payment(
    order: Order, *, operation_id: str, amount: Decimal, raw_hash: str = ""
) -> tuple[bool, str]:
    """Фиксирует оплату и выдаёт подписку. Идемпотентно.

    Возвращает (ok, code): ok=True — платёж зафиксирован,
    code: ok | already | deferred | order_not_found | error:<msg>
    """
    claimed = await claim_order(order, operation_id=operation_id, amount=amount, raw_hash=raw_hash)
    if claimed is None:
        current = await get_order(order.order_id)
        if current is not None and current.status == "paid":
            return True, "already"
        return False, "order_not_found"

    err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            await provision_user(order.telegram_id, order.tariff_days)
            err = None
            break
        except RemnaError as exc:
            err = exc
            log.warning("Выдача подписки (попытка %d/3) не удалась: %s", attempt, exc)
            await asyncio.sleep(2 * attempt)
        except Exception as exc:  # непредвиденное — тоже ретраим
            err = exc
            log.exception("Неожиданная ошибка выдачи подписки")
            await asyncio.sleep(2 * attempt)

    if err is not None:
        await log_service_error(
            "remnawave",
            f"Оплата по заказу {order.order_id} получена, но выдача не удалась: {err}",
        )
        await notifications.notify_admin(
            "⚠️ <b>Оплата получена, но выдача не удалась</b>\n"
            f"Заказ: <code>{order.order_id}</code>\n"
            f"Telegram ID: <code>{order.telegram_id}</code>\n"
            f"Причина: {err}\n"
            "Выдайте подписку вручную: Админка → Заказы → «Переотправить»."
        )
        return True, "deferred"

    await mark_event_processed(operation_id)
    fresh = await get_order(order.order_id) or order
    await notifications.notify_payment_success(fresh)
    return True, "ok"


async def ensure_provisioned_and_notify(order: Order) -> str:
    """Ручная довыдача из админки: если подписка не выдана — выдать, иначе отправить ключ."""
    local = await get_local_user(order.telegram_id)
    if local and local.remnawave_user_id:
        await notifications.notify_key(local)
        return "key_sent"
    await provision_user(order.telegram_id, order.tariff_days)
    fresh = await get_local_user(order.telegram_id)
    if fresh is not None:
        await notifications.notify_key(fresh)
    return "provisioned"


async def log_service_error(kind: str, message: str, level: str = "error") -> None:
    """Пишет ошибку сервиса в БД (раздел «Логи» админки)."""
    from app.models import ServiceLog

    try:
        async with get_session() as session:
            session.add(ServiceLog(kind=kind, level=level, message=str(message)[:2000]))
            await session.commit()
    except Exception:  # логирование не должно ломать основной поток
        log.exception("Не удалось записать service log")
