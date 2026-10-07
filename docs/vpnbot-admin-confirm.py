#!/usr/bin/env python3
"""Ручное подтверждение зависшего заказа (админ-скрипт, версия 2026-10-06.1).

Показать зависшие заказы:
    docker exec -w /app vpnbot-bot python /tmp/admin-confirm.py

Подтвердить конкретный заказ (ты как админ уверен, что деньги пришли):
    docker exec -w /app vpnbot-bot python /tmp/admin-confirm.py ord_xxxxxxxx

Подтверждение идёт через ту же функцию, что и оплата: продлевает подписку,
создаёт пользователя в панели, помечает заказ оплаченным. Событие помечается
уникальным operation_id, поэтому повторный запуск не продлит подписку дважды.

Если заказ уже помечен оплаченным, но выдача в панели падала (статус paid,
а подписка/устройство не выданы) — используй режим выдачи:
    docker exec -w /app vpnbot-bot python /tmp/admin-confirm.py <order_id> --force
Он вызывает выдачу напрямую, не трогая статус заказа.

Отменить заказ, который клиент так и не оплатил (чтобы не висел в ожидании):
    docker exec -w /app vpnbot-bot python /tmp/admin-confirm.py <order_id> --cancel
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SCRIPT_VERSION = "admin-confirm 2026-10-06.3"


def bootstrap_path() -> str | None:
    candidates = [
        os.environ.get("VPNBOT_APP_DIR"),
        os.getcwd(),
        "/app",
        "/opt/vpnbot/vpn-bot",
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/ (код бота).")
    print("   Запусти так:  docker exec -w /app vpnbot-bot python /tmp/admin-confirm.py")
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")


async def show_user(telegram_id: int) -> None:
    try:
        from app.services import device_slots
        from app.services.remnawave import get_remna

        remna_id = await device_slots._remna_id(telegram_id)
        if not remna_id:
            print("  панель: пользователь не найден")
            return
        user = await get_remna().get_user(remna_id)
        if not isinstance(user, dict):
            print(f"  панель: неожиданный ответ {user!r}")
            return
        keys = ("username", "status", "expireAt", "hwidDeviceLimit", "subscriptionUrl")
        print("  панель: " + ", ".join(f"{k}={user.get(k)}" for k in keys if k in user))
    except Exception as exc:  # noqa: BLE001
        print(f"  панель: не удалось прочитать ({type(exc).__name__}: {exc})")


async def main() -> int:
    from sqlalchemy import select

    from app.database import get_session, init_db
    from app.models import Order
    from app.services import orders as orders_service

    await init_db()

    async with get_session() as session:
        pending = (
            await session.execute(
                select(Order).where(Order.status == "pending").order_by(Order.id)
            )
        ).scalars().all()

    print("\n=== ЗАКАЗЫ В ОЖИДАНИИ ОПЛАТЫ ===")
    for row in pending:
        print(
            f"  {row.order_id} | {row.expected_price} ₽ | тариф {row.tariff_code}"
            f" | создан {row.created_at} | метка {row.label}"
        )
    if not pending:
        print("  (нет)")

    args = [a for a in sys.argv[1:] if a.strip()]
    force = "--force" in args
    cancel = "--cancel" in args
    args = [a for a in args if a not in ("--force", "--cancel")]
    if not args:
        print("\nЧтобы подтвердить заказ: python /tmp/admin-confirm.py <order_id>")
        print("Если заказ уже оплачен, но выдача упала: python /tmp/admin-confirm.py <order_id> --force")
        return 0

    target = args[0].strip()
    async with get_session() as session:
        order = (
            await session.execute(select(Order).where(Order.order_id == target))
        ).scalar_one_or_none()
    if order is None:
        print(f"\n!! Заказ {target} не найден")
        return 1

    if cancel:
        print(f"\n=== ОТМЕНЯЮ {order.order_id} ({order.expected_price} ₽, статус {order.status}) ===")
        async with get_session() as session:
            fresh = (
                await session.execute(select(Order).where(Order.order_id == target))
            ).scalar_one_or_none()
            if fresh is None:
                print("!! заказ пропал")
                return 1
            if fresh.status == "paid":
                print("!! заказ уже оплачен — отменять нельзя")
                return 1
            fresh.status = "canceled"
            await session.commit()
        print("заказ помечен canceled — крон больше его не проверяет")
        return 0

    if force:
        print(
            f"\n=== ВЫДАЮ ПРИНУДИТЕЛЬНО {order.order_id}"
            f" ({order.expected_price} ₽, тариф {order.tariff_code}, статус {order.status}) ==="
        )
        try:
            from app.services import device_slots

            if order.tariff_code == device_slots.DEVICE_CODE:
                limit = await device_slots.add_device_slot(order.telegram_id)
                print(f"устройство добавлено, лимит теперь: {limit}")
            else:
                await orders_service.provision_user(order.telegram_id, order.tariff_days)
                await device_slots.ensure_base_limit(order.telegram_id)
                print("подписка выдана/продлена, базовый лимит устройств выставлен")
        except Exception as exc:  # noqa: BLE001
            print(f"!! выдача не удалась: {type(exc).__name__}: {exc}")
            return 1
        await show_user(order.telegram_id)
        print("\nГотово. Заказ остался в статусе paid — это правильно.")
        return 0

    print(f"\n=== ПОДТВЕРЖДАЮ {order.order_id} ({order.expected_price} ₽, статус {order.status}) ===")
    ok, code = await orders_service.process_successful_payment(
        order,
        operation_id=f"admin-manual-{order.order_id}",
        amount=order.expected_price,
        raw_hash="admin-manual",
    )
    print(f"результат: ok={ok} code={code!r}")

    async with get_session() as session:
        fresh = (
            await session.execute(select(Order).where(Order.order_id == target))
        ).scalar_one_or_none()
    if fresh is not None:
        print(
            f"заказ теперь: status={fresh.status}, received_amount={fresh.received_amount},"
            f" operation_id={fresh.operation_id}, paid_at={fresh.paid_at}"
        )
    await show_user(order.telegram_id)

    if code == "already":
        print("\nЭтот заказ уже был подтверждён раньше — подписка не продлевалась повторно.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
