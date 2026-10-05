"""Моя подписка, проверка оплаты, повторная отправка ключа."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app.config import get_settings
from app.services import orders
from app.services.notifications import (
    btn,
    menu_kb,
    no_subscription_text,
    send_message,
    subscription_text,
    url_btn,
)
from app.services.orders import get_local_user, list_orders_for
from app.services.yoomoney import try_manual_confirm
from app.telegram.handlers_start import _safe_edit
from app.utils import utcnow

log = logging.getLogger("app.bot.sub")

router = Router(name="subscription")


@router.callback_query(F.data == "menu:mysub")
async def cb_my_subscription(cb: CallbackQuery) -> None:
    if cb.from_user is None:
        await cb.answer()
        return
    telegram_id = cb.from_user.id
    local = await get_local_user(telegram_id)

    if local is None or (not local.remnawave_user_id and not local.subscription_url):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[btn("🛒 Купить подписку", "menu:shop")], [btn("⬅️ Назад в меню", "menu:back")]]
        )
        await _safe_edit(cb, no_subscription_text(), kb)
        await cb.answer()
        return

    # локальный статус: если срок истёк, но статус ещё ACTIVE — показываем EXPIRED
    status = local.status
    if status == "ACTIVE" and local.expire_at and local.expire_at <= utcnow():
        status = "EXPIRED"

    remna_status = None
    if local.remnawave_user_id:
        try:
            from app.services.remnawave import get_remna

            fresh = await get_remna().get_user(local.remnawave_user_id)
            remna_status = str(fresh.get("status")) if fresh else None
            if fresh:
                from app.utils import parse_iso_utc

                if fresh.get("expireAt"):
                    local_expire = parse_iso_utc(fresh.get("expireAt"))
                    if local_expire:
                        local.expire_at = local_expire
                if fresh.get("subscriptionUrl"):
                    local.subscription_url = fresh["subscriptionUrl"]
                if fresh.get("username"):
                    local.username = fresh["username"]
        except Exception:
            log.warning("Не удалось обновить данные из панели — показываю локальные")

    kb_rows = []
    if local.subscription_url:
        kb_rows.append([url_btn("🔗 Открыть подписку", local.subscription_url)])
    kb_rows.append([btn("🔑 Отправить ключ повторно", "sub:resend")])
    kb_rows.append([btn("🔄 Продлить подписку", "menu:renew")])
    kb_rows.append([btn("⬅️ Назад в меню", "menu:back")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    text = subscription_text(
        username=local.username,
        status=status,
        expire_at=local.expire_at,
        sub_url=local.subscription_url,
        remna_status=remna_status,
    )
    await _safe_edit(cb, text, kb)
    await cb.answer()


@router.callback_query(F.data == "sub:resend")
async def cb_resend_key(cb: CallbackQuery) -> None:
    if cb.from_user is None:
        await cb.answer()
        return
    local = await get_local_user(cb.from_user.id)
    if local is None or not local.remnawave_user_id:
        await cb.answer("Подписка не найдена", show_alert=True)
        return
    await cb.answer("Отправляю ключ…")
    from app.services.notifications import notify_key

    await notify_key(local)


@router.callback_query(F.data == "menu:checkpay")
async def cb_checkpay(cb: CallbackQuery) -> None:
    if cb.from_user is None:
        await cb.answer()
        return
    pending = await list_orders_for(cb.from_user.id, statuses=("pending",))
    if not pending:
        await _safe_edit(
            cb,
            "💳 Ожидающих оплаты заказов нет.\n\nЕсли вы оплатили, но подписка не пришла — "
            "подождите 1–2 минуты, оплата подтверждается автоматически.",
            menu_kb(),
        )
        await cb.answer()
        return

    lines = ["💳 <b>Ожидающие оплаты заказы</b>\n"]
    kb_rows = []
    for o in pending[:5]:
        lines.append(
            f"• <code>{o.order_id}</code> — {o.tariff_days} дн., {o.expected_price:g} ₽"
        )
        kb_rows.append([btn(f"Проверить оплату ({o.tariff_days} дн.)", f"chk:{o.order_id}")])
    kb_rows.append([btn("⬅️ Назад в меню", "menu:back")])
    await _safe_edit(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("chk:"))
async def cb_check_order(cb: CallbackQuery) -> None:
    if cb.from_user is None:
        await cb.answer()
        return
    order_id = cb.data.split(":", 1)[1]
    order = await orders.get_order(order_id)
    if order is None or order.telegram_id != cb.from_user.id:
        await cb.answer("Заказ не найден", show_alert=True)
        return

    if order.status == "paid":
        await cb.answer("Этот заказ уже оплачен ✅", show_alert=True)
        return

    await cb.answer("Проверяю оплату…")
    ok, message = await try_manual_confirm(order)
    if ok:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[btn("📋 Моя подписка", "menu:mysub")], [btn("⬅️ Назад в меню", "menu:back")]]
        )
        await _safe_edit(cb, message, kb)
    else:
        await cb.answer(message, show_alert=True)
