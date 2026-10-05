"""Телеграм-команды администратора (только для ADMIN_ID из .env).

/admin — краткая статистика
/find <telegram_id> — информация о пользователе
/msg <telegram_id> <текст> — написать пользователю от имени бота
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message
from sqlalchemy import func, select

from app.config import get_settings
from app.database import get_session
from app.models import Order, User
from app.services import notifications
from app.services.orders import get_local_user
from app.utils import days_left, display_dt, esc, fmt_money, utcnow

log = logging.getLogger("app.bot.admin")

router = Router(name="admin")


class AdminOnly(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        s = get_settings()
        return bool(s.admin_id > 0 and message.from_user and message.from_user.id == s.admin_id)


@router.message(AdminOnly(), Command("admin"))
async def cmd_admin(message: Message) -> None:
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active = (
            await session.scalar(
                select(func.count(User.id)).where(User.status == "ACTIVE", User.expire_at > now)
            )
            or 0
        )
        expired = (
            await session.scalar(
                select(func.count(User.id)).where(
                    User.expire_at.is_not(None), User.expire_at <= now
                )
            )
            or 0
        )
        orders_total = await session.scalar(select(func.count(Order.id))) or 0
        orders_paid = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "paid")) or 0
        )
        revenue = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(Order.status == "paid")
            )
            or 0
        )
        sales_today = (
            await session.scalar(
                select(func.count(Order.id)).where(Order.status == "paid", Order.paid_at >= today)
            )
            or 0
        )
        revenue_today = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        sales_month = (
            await session.scalar(
                select(func.count(Order.id)).where(Order.status == "paid", Order.paid_at >= month)
            )
            or 0
        )
        revenue_month = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"✅ Активных подписок: <b>{active}</b>\n"
        f"⛔️ Истёкших: <b>{expired}</b>\n\n"
        f"🧾 Заказов всего: <b>{orders_total}</b> (оплачено {orders_paid})\n"
        f"💰 Выручка: <b>{fmt_money(revenue)} ₽</b>\n\n"
        f"📅 Сегодня: {sales_today} продаж на {fmt_money(revenue_today)} ₽\n"
        f"🗓 За месяц: {sales_month} продаж на {fmt_money(revenue_month)} ₽"
    )
    await message.answer(text)


@router.message(AdminOnly(), Command("find"))
async def cmd_find(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("Использование: <code>/find &lt;telegram_id&gt;</code>")
        return
    telegram_id = int(parts[1].strip())
    local = await get_local_user(telegram_id)
    if local is None:
        await message.answer("Пользователь в локальной базе не найден.")
        return

    async with get_session() as session:
        orders_list = list(
            (
                await session.execute(
                    select(Order)
                    .where(Order.telegram_id == telegram_id)
                    .order_by(Order.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )

    tz = get_settings().display_tz
    lines = [
        "👤 <b>Пользователь</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
        f"Remna username: <code>{esc(local.username or '—')}</code>",
        f"Remna ID: <code>{esc(local.remnawave_user_id or '—')}</code>",
        f"Статус: {esc(local.status)}",
        f"Окончание: {display_dt(local.expire_at, tz)} (осталось {days_left(local.expire_at)} дн.)",
    ]
    if local.subscription_url:
        lines.append(f"Подписка: {esc(local.subscription_url)}")
    if orders_list:
        lines.append("\n🧾 Последние заказы:")
        for o in orders_list:
            lines.append(
                f"• <code>{o.order_id}</code> — {o.tariff_days} дн., "
                f"{fmt_money(o.expected_price)} ₽, {esc(o.status)}"
            )
    await message.answer("\n".join(lines))


@router.message(AdminOnly(), Command("msg"))
async def cmd_msg(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("Использование: <code>/msg &lt;telegram_id&gt; &lt;текст&gt;</code>")
        return
    telegram_id = int(parts[1].strip())
    text = parts[2]
    ok = await notifications.send_message(telegram_id, esc(text), parse_mode=ParseMode.HTML)
    await message.answer("✅ Отправлено" if ok else "⚠️ Не удалось отправить")
