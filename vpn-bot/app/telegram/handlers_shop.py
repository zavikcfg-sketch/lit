"""Магазин: список тарифов, создание заказа, ссылка на оплату YooMoney."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app.services import orders
from app.services.notifications import (
    btn,
    menu_kb,
    order_created_text,
    send_message,
    url_btn,
)
from app.services.tariffs import get_tariff, get_tariffs, format_price
from app.services.yoomoney import build_payment_url, display_amount
from app.telegram.handlers_start import upsert_local_user
from app.utils import esc, fmt_money

log = logging.getLogger("app.bot.shop")

router = Router(name="shop")


async def _tariffs_kb() -> InlineKeyboardMarkup:
    rows = []
    for t in await get_tariffs():
        rows.append(
            [btn(f"💎 {t.title} — {format_price(t.price)}", f"buy:{t.code}")]
        )
    rows.append([btn("⬅️ Назад в меню", "menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.in_({"menu:shop", "menu:renew"}))
async def cb_shop(cb: CallbackQuery) -> None:
    tariffs = await get_tariffs()
    if not tariffs:
        await cb.answer("Тарифы временно недоступны", show_alert=True)
        return
    text = (
        "🛒 <b>Выберите тариф</b>\n\n"
        "После оплаты подписка выдаётся автоматически за 1–2 минуты.\n"
        "Продление суммируется с текущим сроком."
    )
    try:
        if cb.message is not None:
            await cb.message.edit_text(text, reply_markup=await _tariffs_kb())
        else:
            raise RuntimeError
    except Exception:
        if cb.from_user:
            await send_message(cb.from_user.id, text, reply_markup=await _tariffs_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery) -> None:
    if cb.from_user is None or cb.message is None:
        await cb.answer()
        return

    code = cb.data.split(":", 1)[1]
    tariff = await get_tariff(code)
    if tariff is None or not tariff.enabled:
        await cb.answer("Тариф недоступен", show_alert=True)
        return

    telegram_id = cb.from_user.id
    await upsert_local_user(telegram_id, cb.from_user.username)

    order = await orders.create_order(
        telegram_id,
        tariff_code=tariff.code,
        tariff_days=tariff.days,
        price=tariff.price,
    )
    pay_amount = fmt_money(display_amount(order.expected_price))
    text = order_created_text(
        order_id=order.order_id,
        days=tariff.days,
        pay_amount=pay_amount,
        price=fmt_money(tariff.price),
    )

    from aiogram.types import InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [url_btn(f"💳 Оплатить {pay_amount} ₽", build_payment_url(order))],
            [btn("💳 Проверить оплату", f"chk:{order.order_id}")],
            [btn("⬅️ К тарифам", "menu:shop")],
        ]
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await send_message(telegram_id, text, reply_markup=kb)
    await cb.answer()
