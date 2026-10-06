"""Тарифы: эффективные значения хранятся в БД (редактируются в админке),
стартовые — из .env (PRICE_*_DAYS или PRICES_*)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.database import get_session
from app.models import Tariff

TARIFF_DAYS = (7, 30, 90, 180, 365)


async def get_tariffs(*, only_enabled: bool = True) -> list[Tariff]:
    async with get_session() as session:
        stmt = select(Tariff).order_by(Tariff.sort, Tariff.days)
        if only_enabled:
            stmt = stmt.where(Tariff.enabled.is_(True))
        return list((await session.execute(stmt)).scalars().all())


async def get_all_tariffs() -> list[Tariff]:
    return await get_tariffs(only_enabled=False)


async def get_tariff(code: str) -> Tariff | None:
    async with get_session() as session:
        return (
            await session.execute(select(Tariff).where(Tariff.code == code))
        ).scalar_one_or_none()


def format_price(value: Decimal | str | float | int) -> str:
    """250 -> '250 ₽', 249.5 -> '249.50 ₽'."""
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return f"{value} ₽"
    if d == d.to_integral_value():
        return f"{int(d)} ₽"
    return f"{d} ₽"
