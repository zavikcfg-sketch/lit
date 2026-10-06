#!/usr/bin/env python3
"""Диагностика подтверждения оплаты в vpnbot (версия 2026-10-06.4).

Запуск (обязательно из каталога кода бота):
    docker cp /root/vpnbot-check-payment.py vpnbot-bot:/tmp/check-payment.py
    docker exec -w /app vpnbot-bot python /tmp/check-payment.py

С одним заказом:
    docker exec -w /app vpnbot-bot python /tmp/check-payment.py <order_id>

Скрипт НЕ печатает токены и секреты. Он:
  1) показывает все настройки ЮMoney/цен из окружения контейнера;
  2) считает порог подтверждения по каждой цене (комиссия от суммы заказа);
  3) печатает заказы и события оплат из базы;
  4) для зависших заказов делает прямой запрос к API ЮMoney и вызывает
     ту самую функцию, что стоит за кнопкой «Проверить оплату» (с текстом ошибки).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import traceback
from pathlib import Path

SCRIPT_VERSION = "check-payment 2026-10-06.4"


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
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")

SECRET_HINTS = ("token", "secret", "password", "passwd", "key")


def title(text: str) -> None:
    print("\n" + "=" * 8 + " " + text + " " + "=" * 8)


def masked(name: str, value) -> str:
    if any(hint in name for hint in SECRET_HINTS):
        if not value:
            return "ПУСТО"
        return f"ЗАДАН (длина {len(str(value))})"
    return repr(value)


def safe(label: str, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        print(f"{label}: {result!r}")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: ОШИБКА {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)
        return None


async def acall(label: str, coro):
    """Аккуратно вызывает async-функцию (её надо именно await-ить)."""
    try:
        result = await coro
        print(f"{label}: {result!r}")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: ИСКЛЮЧЕНИЕ {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3)
        return None


async def probe_api(label: str) -> None:
    """Прямой запрос к ЮMoney: видно код ответа (401 = токен плохой, 200 = ок)."""
    import httpx

    from app.config import get_settings

    settings = get_settings()
    token = getattr(settings, "yoomoney_access_token", None)
    print(f"    токен yoomoney_access_token: {'ЕСТЬ' if token else 'ПУСТО'}")
    if not token:
        print("    прямой запрос пропущен — без токена автопроверка невозможна")
        return
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://yoomoney.ru/api/operations-history",
                headers={"Authorization": f"Bearer {token}"},
                params={"type": "in", "label": label},
            )
            body = (resp.text or "").replace("\n", " ")[:400]
            print(f"    GET operations-history: HTTP {resp.status_code} | {body}")
        except Exception as exc:  # noqa: BLE001
            print(f"    GET operations-history: ОШИБКА {type(exc).__name__}: {exc}")
        try:
            resp = await client.post(
                "https://yoomoney.ru/api/operation-history",
                headers={"Authorization": f"Bearer {token}"},
                data={"type": "in", "label": label},
            )
            body = (resp.text or "").replace("\n", " ")[:400]
            print(f"    POST operation-history: HTTP {resp.status_code} | {body}")
        except Exception as exc:  # noqa: BLE001
            print(f"    POST operation-history: ОШИБКА {type(exc).__name__}: {exc}")


async def main() -> int:
    target = sys.argv[1].strip() if len(sys.argv) > 1 else None

    from app.config import get_settings
    from app.database import get_session, init_db
    from app.models import Order, PaymentEvent
    from app.services import orders as orders_service
    from app.services import yoomoney

    await init_db()

    title("НАСТРОЙКИ ИЗ ОКРУЖЕНИЯ КОНТЕЙНЕРА")
    settings = get_settings()
    fields = getattr(type(settings), "model_fields", None) or getattr(settings, "__fields__", {})
    interesting = (
        "yoomoney",
        "price",
        "device",
        "webhook",
        "notify",
        "public",
        "host",
        "port",
    )
    for name in sorted(fields):
        lower = name.lower()
        if not any(word in lower for word in interesting):
            continue
        value = getattr(settings, name, None)
        print(f"  {name} = {masked(name, value)}")
    print("  код пропатчен (device_slots импортируется):", hasattr(orders_service, "device_slots"))

    title("ПОРОГ ПОДТВЕРЖДЕНИЯ ПО КАЖДОЙ ЦЕНЕ ЗАКАЗА")
    print("  (комиссия считается от суммы конкретного заказа, а не фиксированно)")
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
        show = safe("", yoomoney.display_amount, base_price)
        need = safe("", yoomoney.required_amount, base_price)
        print(f"  {attr}: заказ {base_price} ₽ -> клиент платит {show} ₽, подтверждаем от {need} ₽")

    title("ЗАКАЗЫ В БАЗЕ (последние 8)")
    cols = [c.name for c in Order.__table__.columns]
    async with get_session() as session:
        recent = (
            await session.execute(select_order_desc(Order))
        ).scalars().all()
        events = (
            await session.execute(
                select_events(PaymentEvent)
            )
        ).scalars().all()
        event_cols = [c.name for c in PaymentEvent.__table__.columns]

    for row in recent:
        print("  " + ", ".join(f"{c}={getattr(row, c, None)}" for c in cols))
    if not recent:
        print("  (пусто)")

    title("СОБЫТИЯ ОПЛАТ (последние 5)")
    for row in events:
        print("  " + ", ".join(f"{c}={getattr(row, c, None)}" for c in event_cols))
    if not events:
        print("  (пусто)")

    paid_markers = {"paid", "success", "succeeded", "confirmed", "completed"}

    def is_pending(row) -> bool:
        return str(getattr(row, "status", "") or "").lower() not in paid_markers

    if target:
        chosen = [r for r in recent if str(getattr(r, "order_id", "")) == target]
        if not chosen:
            print(f"\n!! Заказ {target} не найден среди последних 8")
    else:
        pending = [r for r in recent if is_pending(r)]
        chosen = pending[:3] if pending else recent[:3]

    title("ПРОВЕРКА ОПЛАТЫ (то же, что делает кнопка «Проверить оплату»)")
    if not chosen:
        print("  нечего проверять — заказов нет")
    for row in chosen:
        order_id = getattr(row, "order_id", None)
        expected = getattr(row, "expected_price", None)
        label = getattr(row, "label", None) or f"rw_{order_id}"
        print(f"\n>>> заказ {order_id} (статус {getattr(row, 'status', None)}, метка {label})")
        print(f"    ожидаем {expected} ₽, подтверждаем от "
              f"{safe('', yoomoney.required_amount, expected)} ₽")

        await probe_api(str(label))

        ops = await acall("    fetch_operations_by_label", yoomoney.fetch_operations_by_label(str(label)))
        if isinstance(ops, list):
            if not ops:
                print("        (операций по метке нет)")
            for op in ops:
                if isinstance(op, dict):
                    shown = {k: op.get(k) for k in ("operation_id", "amount", "datetime", "label", "status") if k in op}
                    print(f"        {shown}")
                else:
                    print(f"        {op!r}")

        print("    сигнатура try_manual_confirm:", inspect.signature(yoomoney.try_manual_confirm))
        result = await acall("    РЕЗУЛЬТАТ", yoomoney.try_manual_confirm(row))
        print(f"    -> {result!r}")

    title("ПОДСКАЗКА")
    print("  yoomoney_notification_secret должен совпадать с секретом из настроек уведомлений")
    print("  ЮMoney. Если он ПУСТО — авто-подтверждение по вебхуку работать не будет,")
    print("  останется только кнопка «Проверить оплату» (нужен yoomoney_access_token).")
    return 0


def select_order_desc(Order):
    from sqlalchemy import select

    return select(Order).order_by(Order.id.desc()).limit(8)


def select_events(PaymentEvent):
    from sqlalchemy import select

    return select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(5)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
