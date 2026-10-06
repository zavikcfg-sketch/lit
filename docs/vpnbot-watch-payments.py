#!/usr/bin/env python3
"""Авто-подтверждение оплат vpnbot по API ЮMoney (версия 2026-10-06.1).

Раз в минуту проверяет зависшие заказы: ищет платёж в истории кошелька по метке
заказа и, если сумма достаточная, подтверждает оплату той же функцией, что и
кнопка «Проверить оплату» (продление подписки, создание пользователя в панели,
уведомление клиенту). Повторное подтверждение невозможно — защита по operation_id.

Установка (один раз), запуск от root:
    cd /opt/vpnbot/vpn-bot
    curl -fsSL -o watch-payments.py https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs/vpnbot-watch-payments.py
    crontab -l 2>/dev/null | grep -v watch-payments > /tmp/cron.new
    echo '* * * * * cd /opt/vpnbot/vpn-bot && docker cp watch-payments.py vpnbot-bot:/tmp/watch-payments.py >/dev/null 2>&1 && docker exec -w /app vpnbot-bot python /tmp/watch-payments.py >> /var/log/vpnbot-watch.log 2>&1' >> /tmp/cron.new
    crontab /tmp/cron.new && crontab -l | tail -1

Проверить руками:
    docker cp watch-payments.py vpnbot-bot:/tmp/watch-payments.py
    docker exec -w /app vpnbot-bot python /tmp/watch-payments.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCRIPT_VERSION = "watch-payments 2026-10-06.1"


def bootstrap_path() -> str | None:
    for candidate in (os.environ.get("VPNBOT_APP_DIR"), os.getcwd(), "/app", "/opt/vpnbot/vpn-bot"):
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/. Запусти: docker exec -w /app vpnbot-bot python /tmp/watch-payments.py")
    sys.exit(2)

YOO_URL = "https://yoomoney.ru/api/operation-history"


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


async def find_operations(label: str) -> list[dict] | None:
    """Операции ЮMoney с меткой label. [] — платежа нет, None — API недоступен."""
    import httpx

    from app.config import get_settings

    settings = get_settings()
    token = getattr(settings, "yoomoney_access_token", None)
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    attempts = (
        ("POST", {"type": "deposition", "label": label, "records": 100}),
        ("GET", {"type": "deposition", "records": 100}),
        ("POST", {"type": "deposition", "records": 100}),
        ("POST", {"records": 100}),
    )
    got_answer = False
    async with httpx.AsyncClient(timeout=20) as client:
        for method, params in attempts:
            try:
                if method == "GET":
                    resp = await client.get(YOO_URL, headers=headers, params=params)
                else:
                    resp = await client.post(YOO_URL, headers=headers, data=params)
            except Exception:  # noqa: BLE001
                continue
            if resp.status_code != 200:
                continue
            got_answer = True
            try:
                payload = resp.json() or {}
            except ValueError:
                continue
            if payload.get("error"):
                continue
            matched = [
                op for op in (payload.get("operations") or [])
                if str(op.get("label") or "") == label
            ]
            if matched:
                return matched
            if "label" not in params:
                return []
    return [] if got_answer else None


async def check_order(order, orders_service) -> None:
    from app.services.yoomoney import required_amount

    if not order.label:
        print(f"{stamp()} {order.order_id}: у заказа нет метки — пропускаю")
        return

    try:
        required = required_amount(order.expected_price)
    except Exception:  # noqa: BLE001
        required = Decimal(str(order.expected_price))

    ops = await find_operations(str(order.label or ""))
    if ops is None:
        print(f"{stamp()} API ЮMoney недоступен (токен/сеть) — пропускаю")
        return
    if not ops:
        print(f"{stamp()} {order.order_id}: платежа по метке {order.label} пока нет")
        return

    for op in ops:
        status = str(op.get("status") or "success").lower()
        if status != "success":
            print(f"{stamp()} {order.order_id}: платёж {op.get('operation_id')} в статусе {status}")
            continue
        try:
            amount = Decimal(str(op.get("amount")))
        except (InvalidOperation, TypeError):
            continue
        if amount + Decimal("0.01") < required:
            print(
                f"{stamp()} {order.order_id}: платёж {amount} ₽ меньше порога {required} ₽ — не подтверждаю"
            )
            continue
        ok, code = await orders_service.process_successful_payment(
            order,
            operation_id=str(op.get("operation_id") or f"poll-{order.order_id}"),
            amount=amount,
            raw_hash="poll",
        )
        print(f"{stamp()} {order.order_id}: ПОДТВЕРЖДЕНО ok={ok} code={code!r} (платёж {amount} ₽)")
        return


async def main() -> int:
    from sqlalchemy import select

    from app.config import get_settings
    from app.database import get_session, init_db
    from app.models import Order
    from app.services import orders as orders_service

    await init_db()
    about = f"{SCRIPT_VERSION} | корень: {APP_ROOT}"
    if not getattr(get_settings(), "yoomoney_access_token", None):
        print(f"{stamp()} {about}")
        print("!! YOOMONEY_ACCESS_TOKEN не задан — авто-подтверждение невозможно")
        return 1

    async with get_session() as session:
        pending = (
            await session.execute(
                select(Order).where(Order.status == "pending").order_by(Order.id)
            )
        ).scalars().all()

    if not pending:
        return 0  # ничего не пишем, чтобы не засорять лог

    print(f"{stamp()} {about}")
    for order in pending:
        await check_order(order, orders_service)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
