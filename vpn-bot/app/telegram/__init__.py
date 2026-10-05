"""Сборка aiogram Dispatcher из всех роутеров."""
from __future__ import annotations

from aiogram import Dispatcher

from app.telegram.handlers_start import router as start_router
from app.telegram.handlers_shop import router as shop_router
from app.telegram.handlers_subscription import router as subscription_router
from app.telegram.handlers_admin import router as admin_router


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(name="vpn-bot")
    dp.include_router(admin_router)       # админ-команды проверяются первыми
    dp.include_router(start_router)
    dp.include_router(shop_router)
    dp.include_router(subscription_router)
    return dp
