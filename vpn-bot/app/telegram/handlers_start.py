"""/start, главное меню, помощь, регистрация пользователя в локальной базе."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.database import get_session
from app.models import User
from app.services.notifications import (
    help_text,
    menu_kb,
    welcome_text,
)

log = logging.getLogger("app.bot.start")

router = Router(name="start")


async def upsert_local_user(telegram_id: int, username: str | None) -> User:
    """Регистрирует/обновляет пользователя локальной базы (без создания в Remnawave!)."""
    async with get_session() as session:
        user = (
            await session.execute(select_user_by_tg(telegram_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(telegram_id=int(telegram_id), status="ACTIVE")
            session.add(user)
        else:
            # не трогаем статус BLOCKED/EXPIRED — он управляется бизнес-логикой
            if user.status == "ACTIVE" and user.expire_at is None:
                user.status = "ACTIVE"
        await session.commit()
        return user


def select_user_by_tg(telegram_id: int):
    from sqlalchemy import select

    return select(User).where(User.telegram_id == telegram_id)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    await upsert_local_user(message.from_user.id, message.from_user.username)
    await message.answer(welcome_text(message.from_user.first_name or "друг"), reply_markup=menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text(), reply_markup=menu_kb())


@router.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery) -> None:
    await _safe_edit(cb, help_text(), menu_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:back")
async def cb_back(cb: CallbackQuery) -> None:
    name = cb.from_user.first_name if cb.from_user else "друг"
    await _safe_edit(cb, welcome_text(name or "друг"), menu_kb())
    await cb.answer()


async def _safe_edit(cb: CallbackQuery, text: str, kb) -> None:
    try:
        if cb.message is not None:
            await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:
            raise RuntimeError("no message")
    except Exception:
        try:
            if cb.from_user:
                from app.services.notifications import send_message

                await send_message(cb.from_user.id, text, reply_markup=kb)
        except Exception:
            log.exception("Не удалось показать экран меню")
