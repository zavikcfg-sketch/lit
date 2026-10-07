#!/usr/bin/env python3
"""Диагностика выдачи подписки в Remnawave (версия 2026-10-06.1).

Запуск (одной строкой, из любого места):
    docker exec -w /app vpnbot-bot python /tmp/diag-remna.py

Можно указать заказ:
    docker exec -w /app vpnbot-bot python /tmp/diag-remna.py ord_2d2d788f56995f9f

Скрипт печатает:
  * заказ и его статус в базе бота;
  * пользователя из панели Remnawave (uuid, expireAt, hwidDeviceLimit, status);
  * ответы панели на PATCH /api/users с разными телами — там будет точное
    описание ошибки валидации вместо общего «Validation failed».
Секреты маскируются.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SCRIPT_VERSION = "diag-remna 2026-10-06.2"
DEFAULT_ORDER = "ord_2d2d788f56995f9f"


def bootstrap_path() -> str | None:
    for candidate in (os.environ.get("VPNBOT_APP_DIR"), os.getcwd(), "/app", "/opt/vpnbot/vpn-bot"):
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл пакет app/. Запусти: docker exec -w /app vpnbot-bot python /tmp/diag-remna.py")
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")

SECRET_WORDS = ("token", "key", "secret", "password", "pass")
BASE_WORDS = ("url", "host", "base", "api")


def mask(name: str, value) -> str:
    text = str(value)
    if any(w in name.lower() for w in SECRET_WORDS):
        return f"ЗАДАН (длина {len(text)})" if text else "ПУСТО"
    return text


def title(text: str) -> None:
    print("\n" + "=" * 8 + " " + text + " " + "=" * 8)


def find_conn() -> tuple[str | None, str | None, list[str]]:
    """Base URL и токен панели: ищем в переменных окружения и настройках."""
    notes: list[str] = []
    base: str | None = None
    token: str | None = None

    env_hits = []
    for name, value in sorted(os.environ.items()):
        low = name.lower()
        if "remna" in low or "panel" in low:
            env_hits.append(f"{name}={mask(name, value)}")
            if any(w in low for w in BASE_WORDS) and value.startswith("http"):
                base = base or value.rstrip("/")
            if any(w in low for w in SECRET_WORDS) and not base and not value.startswith("http"):
                pass
            if any(w in low for w in SECRET_WORDS):
                token = token or value
    title("ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (remna/panel)")
    for line in env_hits or ["  (нет)"]:
        print("  " + line)

    try:
        from app.config import get_settings

        settings = get_settings()
        fields = getattr(type(settings), "model_fields", None) or getattr(settings, "__fields__", {})
        hits = []
        for name in sorted(fields):
            low = name.lower()
            if "remna" not in low and "panel" not in low:
                continue
            value = getattr(settings, name, None)
            hits.append(f"{name}={mask(name, value)}")
            if value and isinstance(value, str):
                if value.startswith("http"):
                    base = base or value.rstrip("/")
                elif any(w in low for w in SECRET_WORDS):
                    token = token or value
        title("НАСТРОЙКИ app.config")
        for line in hits or ["  (нет)"]:
            print("  " + line)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"настройки не прочитались: {type(exc).__name__}: {exc}")

    title("РЕЗУЛЬТАТ ПОИСКА ПОДКЛЮЧЕНИЯ")
    print(f"  base url: {base or 'НЕ НАЙДЕН'}")
    print(f"  токен: {'НАЙДЕН' if token else 'НЕ НАЙДЕН'}")
    return base, token, notes


async def main() -> int:
    order_id = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_ORDER

    from sqlalchemy import select

    from app.database import get_session, init_db
    from app.models import Order, PaymentEvent, User
    from app.services import remnawave as remna_module

    await init_db()

    title(f"ЗАКАЗ {order_id}")
    async with get_session() as session:
        order = (
            await session.execute(select(Order).where(Order.order_id == order_id))
        ).scalar_one_or_none()
    if order is None:
        print("  заказ не найден в базе")
        return 1
    cols = [c.name for c in Order.__table__.columns]
    print("  " + ", ".join(f"{c}={getattr(order, c, None)}" for c in cols))

    telegram_id = order.telegram_id
    title(f"ЛОКАЛЬНАЯ ЗАПИСЬ ПОЛЬЗОВАТЕЛЯ (telegram {telegram_id})")
    async with get_session() as session:
        local = (
            await session.execute(select(User).where(User.telegram_id == int(telegram_id)))
        ).scalar_one_or_none()
        events = (
            await session.execute(
                select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(5)
            )
        ).scalars().all()
    if local is None:
        print("  локального пользователя нет")
        local_uuid = None
    else:
        ucols = [c.name for c in User.__table__.columns]
        print("  " + ", ".join(f"{c}={getattr(local, c, None)}" for c in ucols))
        local_uuid = getattr(local, "remnawave_user_id", None)

    title("СОБЫТИЯ ОПЛАТ (последние 5)")
    ecols = [c.name for c in PaymentEvent.__table__.columns]
    for row in events:
        print("  " + ", ".join(f"{c}={getattr(row, c, None)}" for c in ecols))
    if not events:
        print("  (пусто)")

    title("ПАНЕЛЬ REMNAWAVE: ПОЛЬЗОВАТЕЛЬ")
    try:
        client = remna_module.get_remna()
    except Exception as exc:  # noqa: BLE001
        print(f"  клиент не создался: {type(exc).__name__}: {exc}")
        return 1
    print(f"  класс клиента: {type(client).__name__}")
    for attr in ("base_url", "_base_url", "url", "api_url", "host"):
        if hasattr(client, attr):
            print(f"  {attr} = {getattr(client, attr)}")

    panel_user = None
    for label, action in (
        ("get_user по локальному uuid", lambda: client.get_user(str(local_uuid)) if local_uuid else None),
        ("find_user_by_telegram_id", lambda: client.find_user_by_telegram_id(int(telegram_id))),
    ):
        try:
            result = action()
            if result is None:
                print(f"  {label}: пропущено (нет данных)")
                continue
            if hasattr(result, "__await__"):
                result = await result
            print(f"  {label}: получено")
            if isinstance(result, dict):
                panel_user = panel_user or result
                keep = (
                    "id", "uuid", "username", "status", "expireAt", "hwidDeviceLimit",
                    "telegramId", "trafficLimitBytes", "activeInternalSquads",
                )
                shown = {k: result.get(k) for k in keep if k in result}
                print("     " + json.dumps(shown, ensure_ascii=False, default=str))
                extra = [k for k in result if k not in keep]
                print(f"     прочие поля: {', '.join(extra[:14])}")
            else:
                print(f"     ответ: {result!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label}: ОШИБКА {type(exc).__name__}: {exc}")

    if panel_user is None:
        print("  !! пользователь в панели не найден — вот причина, почему выдача не идёт")
        return 1

    uuid = panel_user.get("uuid") or panel_user.get("id")
    limit = panel_user.get("hwidDeviceLimit")

    title("ИСХОДНИКИ ФУНКЦИЙ ВЫДАЧИ (прямо из контейнера)")
    import inspect

    targets = []
    for name in ("update_user", "extend_user", "_request", "get_user"):
        fn = getattr(remna_module.get_remna().__class__, name, None)
        if fn is not None:
            targets.append((f"remnawave.{name}", fn))
    try:
        from app.services import orders as orders_module

        for name in ("provision_user", "process_successful_payment"):
            fn = getattr(orders_module, name, None)
            if fn is not None:
                targets.append((f"orders.{name}", fn))
    except Exception as exc:  # noqa: BLE001
        print(f"  orders не прочитались: {type(exc).__name__}: {exc}")
    try:
        from app.services import device_slots

        for name in ("ensure_base_limit", "add_device_slot", "_remna_id"):
            fn = getattr(device_slots, name, None)
            if fn is not None:
                targets.append((f"device_slots.{name}", fn))
    except Exception as exc:  # noqa: BLE001
        print(f"  device_slots не прочитались: {type(exc).__name__}: {exc}")

    for name, fn in targets:
        try:
            print(f"\n--- {name} ---")
            print(inspect.getsource(fn))
        except Exception as exc:  # noqa: BLE001
            print(f"  исходник недоступен ({type(exc).__name__}: {exc})")

    title("СЫРЫЕ PATCH-ЗАПРОСЫ (ищем точный текст ошибки валидации)")
    base, token, notes = find_conn()
    for note in notes:
        print("  " + note)
    if not (base and token):
        print("  !! не нашёл base url или токен — пробы PATCH пропущены")
        print("  подскажи вывод выше, продолжим от него")
        return 1

    import httpx

    url = f"{base}/api/users"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    title("НАСТРОЙКИ ПОДПИСКИ И HWID (GET, чтобы понять, включён ли HWID)")
    async with httpx.AsyncClient(timeout=25) as http:
        for path in ("/api/subscription-settings", "/api/settings"):
            try:
                resp = await http.get(f"{base}{path}", headers=headers)
                body = (resp.text or "").replace("\n", " ")[:700]
                print(f"\n  GET {path}: HTTP {resp.status_code}\n     {body}")
            except Exception as exc:  # noqa: BLE001
                print(f"\n  GET {path}: СЕТЬ {type(exc).__name__}: {exc}")

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    attempts = [
        ("только uuid", {"uuid": uuid}),
        ("uuid + hwidDeviceLimit (как делает бот)", {"uuid": uuid, "hwidDeviceLimit": 2}),
        ("uuid + hwidDeviceLimit строкой", {"uuid": uuid, "hwidDeviceLimit": "2"}),
        ("uuid + статус", {"uuid": uuid, "status": "ACTIVE"}),
        (
            "uuid + expireAt с миллисекундами и Z",
            {"uuid": uuid, "expireAt": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"},
        ),
        (
            "uuid + expireAt без миллисекунд",
            {"uuid": uuid, "expireAt": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        ),
        (
            "uuid + expireAt без Z",
            {"uuid": uuid, "expireAt": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")},
        ),
    ]
    async with httpx.AsyncClient(timeout=25) as http:
        for name, payload in attempts:
            try:
                resp = await http.patch(url, headers=headers, json=payload)
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [{name}] СЕТЬ: {type(exc).__name__}: {exc}")
                continue
            body = (resp.text or "").replace("\n", " ")[:700]
            print(f"\n  [{name}] HTTP {resp.status_code}\n     отправлено: {json.dumps(payload)}\n     ответ: {body}")

    title("ИТОГ")
    print(f"  uuid в панели: {uuid}")
    print(f"  текущий hwidDeviceLimit: {limit!r}")
    print("  пришли вывод целиком — по ответу панели видно, какое поле нужно поправить в коде.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
