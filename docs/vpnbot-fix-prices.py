#!/usr/bin/env python3
"""Обновление цен тарифов в базе бота (запускать ВНУТРИ контейнера vpnbot-bot).

Пример:
    docker cp /root/vpnbot-fix-prices.py vpnbot-bot:/tmp/fix-prices.py
    docker exec vpnbot-bot python /tmp/fix-prices.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

SCRIPT_VERSION = "price-fix 2026-10-06.3"

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
    print("   Запусти так:  docker exec -w /app vpnbot-bot python /tmp/fix-prices.py")
    sys.exit(2)
print(f"fix-prices {SCRIPT_VERSION} | корень бота: {APP_ROOT}")

from sqlalchemy import delete, select

from app.database import get_session, init_db
from app.models import Tariff

PRICES = [
    ("7d", 7, "50", "7 дней", 10),
    ("30d", 30, "100", "30 дней", 20),
    ("90d", 90, "300", "90 дней", 30),
    ("180d", 180, "600", "180 дней", 40),
    ("365d", 365, "1200", "365 дней", 50),
]


async def main() -> None:
    await init_db()
    async with get_session() as session:
        # служебный код "device" в тарифах не нужен — устройства обрабатываются отдельной веткой
        await session.execute(delete(Tariff).where(Tariff.code == "device"))
        for code, days, price, title, sort in PRICES:
            row = (
                await session.execute(select(Tariff).where(Tariff.code == code))
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    Tariff(
                        code=code,
                        days=days,
                        price=Decimal(price),
                        title=title,
                        enabled=True,
                        sort=sort,
                    )
                )
                print("добавлен", code, price)
            else:
                row.price = Decimal(price)
                row.days = days
                row.title = title or row.title
                row.enabled = True
                print("обновлён", code, "->", price)
        await session.commit()
        rows = (await session.execute(select(Tariff).order_by(Tariff.sort))).scalars().all()
        print("ИТОГО:", [(r.code, str(r.price), r.enabled) for r in rows])


if __name__ == "__main__":
    asyncio.run(main())
