#!/usr/bin/env python3
"""Диагностика подтверждения оплаты в vpnbot (запускать ВНУТРИ контейнера vpnbot-bot).

    docker cp /root/vpnbot-check-payment.py vpnbot-bot:/tmp/check-payment.py
    docker exec vpnbot-bot python /tmp/check-payment.py

Можно указать конкретный заказ:
    docker exec vpnbot-bot python /tmp/check-payment.py <order_id>

Скрипт печатает: режим комиссии и цены из окружения контейнера, последние заказы,
историю операций ЮMoney по их меткам и РЕЗУЛЬТАТ вызова той же функции,
которой пользуется кнопка «Проверить оплату» (с полным текстом ошибки).
Секреты не печатает.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import traceback
from pathlib import Path


SCRIPT_VERSION = "check-payment 2026-10-06.3"


def bootstrap_path() -> str | None:
    """Ищем каталог, внутри которого лежит пакет app/ (код бота)."""
    candidates = [
        os.environ.get("VPNBOT_APP_DIR"),
        os.getcwd(),
        "/app",
        "/opt/vpnbot/vpn-bot",
        "/code",
        "/srv/app",
        "/home/app",
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/ (код бота).")
    print("   Запусти так:  docker exec -w /app vpnbot-bot python /tmp/check-payment.py")
    print("   Проверить путь:  docker exec vpnbot-bot sh -c 'ls -d /app/app /opt/*/vpn-bot/app 2>/dev/null'")
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")

from sqlalchemy import select


def title(text: str) -> None:
    print("\n" + "=" * 8 + " " + text + " " + "=" * 8)


def safe(label: str, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        print(f"{label}: {result!r}")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: ОШИБКА {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None


def mask(value) -> str:
    text = str(value or "")
    if len(text) <= 6:
        return "***"
    return text[:4] + "…" + text[-2:]


async def main() -> int:
    target = sys.argv[1].strip() if len(sys.argv) > 1 else None

    from app.config import get_settings
    from app.database import get_session, init_db
    from app.models import Order, PaymentEvent
    from app.services import yoomoney
    from app.services import orders as orders_service

    await init_db()

    title("НАСТРОЙКИ ИЗ ОКРУЖЕНИЯ КОНТЕЙНЕРА")
    settings = get_settings()
    for name in (
        "yoomoney_fee_mode",
        "yoomoney_fee_percent",
        "price_7_days",
        "price_30_days",
        "price_90_days",
        "price_180_days",
        "price_365_days",
        "price_device_slot",
        "device_base_limit",
    ):
        if hasattr(settings, name):
            print(f"  {name} = {getattr(settings, name)!r}")
    for name in ("yoomoney_wallet", "yoomoney_receiver"):
        if hasattr(settings, name):
            print(f"  {name} = {mask(getattr(settings, name))}")
    for name in ("yoomoney_token", "yoomoney_notification_secret"):
        if hasattr(settings, name):
            value = getattr(settings, name)
            print(f"  {name}: {'ЗАДАН' if value else 'ПУСТО'}")
    print("  прошло ли патч device_slots:", hasattr(orders_service, "device_slots"))

    title("ПОРОГ ПОДТВЕРЖДЕНИЯ ПО КАЖДОЙ ЦЕНЕ ЗАКАЗА")
    print("  (комиссия считается от суммы конкретного заказа, а не от фиксированной)")
    for attr in (
        "price_7_days",
        "price_30_days",
        "price_90_days",
        "price_180_days",
        "price_365_days",
        "price_device_slot",
    ):
        if not hasattr(settings, attr):
            continue
        base_price = getattr(settings, attr)
        try:
            show = yoomoney.display_amount(base_price)
        except Exception as exc:  # noqa: BLE001
            show = f"ОШИБКА {exc}"
        try:
            need = yoomoney.required_amount(base_price)
        except Exception as exc:  # noqa: BLE001
            need = f"ОШИБКА {exc}"
        print(f"  {attr}: заказ {base_price} ₽ -> клиент платит {show} ₽, подтверждаем от {need} ₽")

    title("ЛОГИКА КОМИССИИ (исходник yoomoney.py)")
    for name in ("display_amount", "required_amount", "try_manual_confirm", "fetch_operations_by_label"):
        fn = getattr(yoomoney, name, None)
        if fn is None:
            print(f"  {name}: НЕТ такой функции")
            continue
        try:
            print(f"\n--- {name} ---")
            print(inspect.getsource(fn))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: исходник недоступен ({exc})")
    print("  функции модуля:", [n for n in dir(yoomoney) if not n.startswith("__")])

    title("ЗАКАЗЫ В БАЗЕ (последние 8)")
    cols = [c.name for c in Order.__table__.columns]
    async with get_session() as session:
        recent = (
            await session.execute(select(Order).order_by(Order.id.desc()).limit(8))
        ).scalars().all()
        events = (
            await session.execute(select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(5))
        ).scalars().all()
        event_cols = [c.name for c in PaymentEvent.__table__.columns]

    orders_by_id = {}
    for row in recent:
        data = {c: getattr(row, c, None) for c in cols}
        orders_by_id[str(data.get("order_id"))] = row
        print("  " + ", ".join(f"{k}={v}" for k, v in data.items()))

    if not recent:
        print("  (пусто)")

    title("СОБЫТИЯ ОПЛАТ (последние 5)")
    for row in events:
        print("  " + ", ".join(f"{c}={getattr(row, c, None)}" for c in event_cols))
    if not events:
        print("  (пусто)")

    # какие строки заказов считаем «не подтверждёнными»
    paid_markers = {"paid", "success", "succeeded", "confirmed", "completed"}

    def is_pending(row) -> bool:
        status = str(getattr(row, "status", "") or "").lower()
        return status not in paid_markers

    if target:
        chosen = [r for r in recent if str(getattr(r, "order_id", "")) == target]
        if not chosen:
            print(f"\n!! Заказ {target} не найден среди последних 8 — покажу по нему попытку всё равно")
            chosen = [None]
    else:
        pending = [r for r in recent if is_pending(r)]
        chosen = pending[:3] if pending else recent[:3]

    title("ПРОВЕРКА ОПЛАТЫ (то же, что делает кнопка «Проверить оплату»)")
    for row in chosen:
        if row is None:
            print(f"  заказ {target}: пропущен (нет строки в БД)")
            continue
        order_id = getattr(row, "order_id", None)
        expected = getattr(row, "expected_price", None) or getattr(row, "price", None)
        print(f"\n>>> заказ {order_id} (статус {getattr(row, 'status', None)})")
        if hasattr(yoomoney, "display_amount"):
            safe("    display_amount", yoomoney.display_amount, expected)
        if hasattr(yoomoney, "required_amount"):
            safe("    required_amount", yoomoney.required_amount, expected)

        label = None
        for name in ("order_label", "label_for", "build_label", "make_label", "payment_label"):
            fn = getattr(yoomoney, name, None)
            if fn is not None:
                safe(f"    {name}", fn, row)
        if label is None:
            label = f"rw_{order_id}"
            print(f"    метка по умолчанию: {label}")

        if hasattr(yoomoney, "fetch_operations_by_label"):
            ops = safe("    операции по метке", yoomoney.fetch_operations_by_label, label)
            if ops:
                for op in ops:
                    print("        ", {k: op.get(k) for k in ("operation_id", "amount", "datetime", "label") if isinstance(op, dict)} if isinstance(op, dict) else op)
            else:
                print("        (операций не найдено)")

        fn = getattr(yoomoney, "try_manual_confirm", None) or getattr(orders_service, "try_manual_confirm", None)
        if fn is None:
            print("    try_manual_confirm: НЕТ функции")
        else:
            print("    вызов try_manual_confirm:", inspect.signature(fn))
            try:
                result = await fn(row)
                print(f"    РЕЗУЛЬТАТ: {result!r}")
            except Exception as exc:  # noqa: BLE001
                print(f"    ИСКЛЮЧЕНИЕ {type(exc).__name__}: {exc}")
                traceback.print_exc()

    title("ГОТОВО")
    print("Скопируй весь вывод и пришли — по нему видно, почему бот не подтвердил оплату.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
