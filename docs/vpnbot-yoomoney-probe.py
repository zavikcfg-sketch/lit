#!/usr/bin/env python3
"""Проверка токена ЮMoney и поиск платежей по меткам заказов (версия 2026-10-06.1).

Запуск:
    docker cp /root/vpnbot-yoomoney-probe.py vpnbot-bot:/tmp/probe.py
    docker exec -w /app vpnbot-bot python /tmp/probe.py

Печатает: годен ли токен (HTTP-код), последние входящие операции кошелька
(дата, сумма, метка) и совпадение с зависшими заказами. Токен маскируется.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SCRIPT_VERSION = "yoomoney-probe 2026-10-06.1"


def bootstrap_path() -> str | None:
    for candidate in (os.environ.get("VPNBOT_APP_DIR"), os.getcwd(), "/app", "/opt/vpnbot/vpn-bot"):
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/. Запусти: docker exec -w /app vpnbot-bot python /tmp/probe.py")
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")


def mask_token(token: str | None) -> str:
    if not token:
        return "ПУСТО"
    text = str(token)
    if "." in text:
        head, _, tail = text.partition(".")
        return f"{head}.…{tail[-4:] if len(tail) >= 4 else ''} (длина {len(text)})"
    return f"…{text[-4:]} (длина {len(text)})"


async def main() -> int:
    import httpx

    from app.config import get_settings
    from app.database import get_session, init_db
    from app.models import Order
    from sqlalchemy import select

    await init_db()
    settings = get_settings()
    token = getattr(settings, "yoomoney_access_token", None)
    print(f"\nтокен: {mask_token(token)}")

    url = "https://yoomoney.ru/api/operation-history"
    if not token:
        print("!! Токена нет — впиши YOOMONEY_ACCESS_TOKEN в .env и перезапусти контейнер")
        return 1

    headers = {"Authorization": f"Bearer {token}"}
    ops: list[dict] = []
    attempts = (
        ("POST", "правильный запрос (type=deposition)", {"type": "deposition", "records": 100}),
        ("POST", "как в коде бота сейчас (type=in)", {"type": "in", "records": 100}),
        ("GET", "проверка GET-варианта", {"type": "deposition", "records": 30}),
    )
    async with httpx.AsyncClient(timeout=20) as client:
        for method, what, params in attempts:
            try:
                if method == "POST":
                    resp = await client.post(url, headers=headers, data=params)
                else:
                    resp = await client.get(url, headers=headers, params=params)
            except Exception as exc:  # noqa: BLE001
                print(f"\n{method} {what}: СЕТЬ НЕДОСТУПНА ({type(exc).__name__}: {exc})")
                continue
            body = (resp.text or "").replace("\n", " ")[:300]
            print(f"\n{method} {what}: HTTP {resp.status_code}\n    {body}")
            if resp.status_code == 200:
                try:
                    payload = resp.json() or {}
                except ValueError:
                    continue
                got = payload.get("operations") or []
                if got and not ops:
                    ops = got

    if ops:
        print(f"\n=== ПОСЛЕДНИЕ ВХОДЯЩИЕ ОПЕРАЦИИ (получено {len(ops)}) ===")
        for op in ops[:12]:
            print(
                "  {op_id} | {dt} | {amount} {cur} | тип {type} | статус {status} | метка: {label!r}".format(
                    op_id=op.get("operation_id"),
                    dt=op.get("datetime"),
                    amount=op.get("amount"),
                    cur=op.get("amount_currency") or "RUB",
                    type=op.get("type"),
                    status=op.get("status"),
                    label=op.get("label"),
                )
            )

    async with get_session() as session:
        pending = (
            await session.execute(select(Order).where(Order.status == "pending").order_by(Order.id))
        ).scalars().all()

    print("\n=== СОПОСТАВЛЕНИЕ С ЗАВИСШИМИ ЗАКАЗАМИ ===")
    if not pending:
        print("  зависших заказов нет")
    for order in pending:
        same_label = [op for op in ops if str(op.get("label") or "") == str(order.label)]
        if same_label:
            for op in same_label:
                print(
                    f"  {order.order_id} ({order.expected_price} ₽): НАЙДЕН платёж {op.get('amount')} ₽"
                    f" от {op.get('datetime')}, статус {op.get('status')} -> можно подтверждать"
                )
        else:
            print(
                f"  {order.order_id} ({order.expected_price} ₽): платежа с меткой {order.label} "
                "в истории кошелька нет"
            )
    print("\nЕсли видишь 200 и список операций, но метки не совпадают — пришли вывод, подберём по сумме/дате.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
