"""Отправка сообщений Telegram из обоих процессов (бот и админка)
и сборка текстов сообщений.

Токен бота нигде не логируется. Ошибки доставки не прерывают основной поток.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.utils import days_left, display_dt, esc, fmt_money

log = logging.getLogger("app.notifications")

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot не инициализирован")
    return _bot


def has_bot() -> bool:
    return _bot is not None


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        try:
            await _bot.session.close()
        except Exception:
            pass
        _bot = None


# ------------------------------------------------------------------ отправка

async def send_message(
    chat_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = ParseMode.HTML,
) -> bool:
    """Отправляет сообщение; True — успешно. Длинные тексты бьются на части."""
    chunks = _chunk(text, 3900)
    ok_all = True
    for i, chunk in enumerate(chunks):
        kb = reply_markup if i == len(chunks) - 1 else None
        for attempt in (1, 2, 3):
            try:
                await get_bot().send_message(
                    chat_id, chunk, reply_markup=kb, parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramAPIError as exc:
                log.warning("Не удалось отправить сообщение %s: %s", chat_id, exc)
                ok_all = False
                break
            except Exception as exc:
                log.warning("Ошибка отправки %s (попытка %d): %s", chat_id, attempt, type(exc).__name__)
                ok_all = False
                await asyncio.sleep(1.5 * attempt)
        else:
            ok_all = False
    return ok_all


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    while text:
        parts.append(text[:size])
        text = text[size:]
    return parts


async def notify_admin(text: str) -> None:
    s = get_settings()
    if s.admin_id:
        await send_message(s.admin_id, text)


async def broadcast(
    text: str,
    *,
    rate_per_sec: float,
    chat_ids: list[int],
    progress=None,
) -> tuple[int, int]:
    """Рассылка с ограничением скорости. progress(done, failed, total)."""
    delay = 1.0 / max(0.5, float(rate_per_sec))
    sent = failed = 0
    total = len(chat_ids)
    for i, chat_id in enumerate(chat_ids):
        ok = await send_message(chat_id, text, parse_mode=None)  # рассылка — plain text
        sent += int(ok)
        failed += int(not ok)
        if progress:
            progress(sent, failed, total)
        if i < total - 1:
            await asyncio.sleep(delay)
    return sent, failed


# ------------------------------------------------------------------ клавиатуры

def btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("🛒 Купить подписку", "menu:shop")],
            [btn("📋 Моя подписка", "menu:mysub")],
            [btn("🔄 Продлить подписку", "menu:renew")],
            [btn("💳 Проверить оплату", "menu:checkpay")],
            [btn("🆘 Помощь", "menu:help")],
        ]
    )


# ------------------------------------------------------------------ тексты

def welcome_text(first_name: str) -> str:
    return (
        f"👋 Привет, <b>{esc(first_name)}</b>!\n\n"
        "Это бот для покупки VPN-подписки.\n\n"
        "🔐 Стабильное соединение\n"
        "⚡️ Высокая скорость\n"
        "📱 Работает на телефоне, компьютере и роутере\n\n"
        "Выберите действие в меню ниже 👇"
    )


def help_text() -> str:
    s = get_settings()
    return (
        "🆘 <b>Помощь</b>\n\n"
        "• <b>Купить подписку</b> — выберите тариф и оплатите.\n"
        "• <b>Моя подписка</b> — статус, дата окончания и ссылка на ключи.\n"
        "• <b>Проверить оплату</b> — если оплатили, но подписка не пришла.\n\n"
        "Оплата подтверждается автоматически (обычно 1–2 минуты).\n\n"
        f"Поддержка: {esc(s.support_username)}"
    )


def no_subscription_text() -> str:
    return "😔 У вас пока нет активной подписки."


def subscription_text(
    *, username: str | None, status: str, expire_at, sub_url: str | None, remna_status: str | None = None
) -> str:
    status_icon = {"ACTIVE": "✅", "EXPIRED": "⛔️", "BLOCKED": "🚫"}.get(status, "•")
    left = days_left(expire_at)
    text = (
        "📋 <b>Моя подписка</b>\n\n"
        f"Статус: {status_icon} <b>{esc(status)}</b>\n"
    )
    if username:
        text += f"Пользователь: <code>{esc(username)}</code>\n"
    if expire_at:
        text += f"Действует до: <b>{display_dt(expire_at)}</b> (осталось {left} дн.)\n"
    if remna_status:
        text += f"Состояние в панели: {esc(remna_status)}\n"
    text += "\n"
    if sub_url:
        text += f"🔗 Ссылка для приложений:\n{esc(sub_url)}\n\n"
        text += "Скопируйте ссылку в приложение (v2rayNG, Streisand, Hiddify и др.) — профиль добавится автоматически."
    else:
        text += "Ссылка на подписку пока не готова — нажмите «Отправить ключ повторно»."
    return text


def order_created_text(*, order_id: str, days: int, pay_amount: str, price: str) -> str:
    fee_note = ""
    if pay_amount != price:
        fee_note = f"\n(тариф {fmt_money(price)} ₽ + комиссия платёжной системы)"
    return (
        f"🧾 Заказ <code>{esc(order_id)}</code>\n"
        f"💎 Тариф: <b>{days} дн.</b>\n"
        f"💰 К оплате: <b>{fmt_money(pay_amount)} ₽</b>{fee_note}\n\n"
        "1️⃣ Нажмите кнопку «Оплатить» ниже\n"
        "2️⃣ После оплаты вернитесь и нажмите «Проверить оплату»\n"
        "3️⃣ Обычно оплата подтверждается автоматически за 1–2 минуты"
    )


def payment_success_text(*, order_id: str, days: int, amount, expire_at, sub_url: str | None) -> str:
    text = (
        "🎉 <b>Оплата получена!</b>\n\n"
        f"🧾 Заказ: <code>{esc(order_id)}</code>\n"
        f"💎 Тариф: {days} дн.\n"
        f"💰 Сумма: {fmt_money(amount)} ₽\n"
    )
    if expire_at:
        text += f"📅 Подписка активна до: <b>{display_dt(expire_at)}</b> (осталось {days_left(expire_at)} дн.)\n"
    if sub_url:
        text += f"\n🔗 Ваша ссылка на подписку:\n{esc(sub_url)}\n"
    else:
        text += "\nСсылка на подписку будет готова через минуту — нажмите «Моя подписка».\n"
    return text


def key_text(*, username: str | None, expire_at, sub_url: str | None, keys: str | None = None) -> str:
    text = "🔑 <b>Ваши ключи подключения</b>\n\n"
    if username:
        text += f"Пользователь: <code>{esc(username)}</code>\n"
    if expire_at:
        text += f"Действует до: <b>{display_dt(expire_at)}</b>\n"
    text += "\n"
    if keys:
        text += f"<pre>{esc(keys)[:3000]}</pre>\n"
    if sub_url:
        text += f"🔗 Ссылка для приложений:\n{esc(sub_url)}"
    return text


# ------------------------------------------------------------------ уведомления по оплате

async def notify_payment_success(order) -> None:
    from app.services.orders import get_local_user

    local = await get_local_user(order.telegram_id)
    text = payment_success_text(
        order_id=order.order_id,
        days=order.tariff_days,
        amount=order.received_amount or order.expected_price,
        expire_at=local.expire_at if local else None,
        sub_url=local.subscription_url if local else None,
    )
    rows = []
    if local and local.subscription_url:
        rows.append([url_btn("🔗 Открыть подписку", local.subscription_url)])
    rows.append([btn("📋 Моя подписка", "menu:mysub")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await send_message(order.telegram_id, text, reply_markup=kb)


async def notify_key(local) -> None:
    """(Пере)отправка ключа: сначала пробуем connection-keys, затем просто ссылку."""
    keys: str | None = None
    sub_url = local.subscription_url
    if local.remnawave_user_id:
        from app.services.remnawave import get_remna

        remna = get_remna()
        try:
            data = await remna.get_connection_keys(local.remnawave_user_id)
            keys = _extract_keys(data)
        except Exception as exc:
            log.warning("connection-keys недоступны: %s", type(exc).__name__)
    await send_message(
        local.telegram_id,
        key_text(username=local.username, expire_at=local.expire_at, sub_url=sub_url, keys=keys),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[btn("📋 Моя подписка", "menu:mysub")]] +
            ([[url_btn("🔗 Открыть подписку", sub_url)]] if sub_url else [])
        ),
    )


def _extract_keys(data) -> str | None:
    """Достаёт ключи из ответа connection-keys (формат зависит от версии панели)."""
    if data is None:
        return None
    items = data
    if isinstance(data, dict):
        items = data.get("response", data)
    if isinstance(items, dict):
        items = items.get("keys") or items.get("items") or items
    if isinstance(items, str):
        return items.strip() or None
    lines: list[str] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                lines.append(it)
            elif isinstance(it, dict):
                for field in ("key", "link", "url", "value", "raw"):
                    if it.get(field):
                        lines.append(str(it[field]))
                        break
    if not lines:
        return None
    return "\n".join(lines)[:3500]
