"""Точка входа Telegram-бота: polling + health-сервер (порт 8088) + graceful shutdown."""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from app.config import get_settings
from app.database import dispose_db, init_db
from app.services import notifications
from app.services.remnawave import close_remna
from app.telegram import build_dispatcher
from app.utils import setup_logging


def make_health_app(service: str) -> web.Application:
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": service})

    app.router.add_get("/health", health)
    return app


async def start_health_server(port: int, service: str) -> web.AppRunner:
    runner = web.AppRunner(make_health_app(service), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner


async def run() -> None:
    setup_logging()
    log = logging.getLogger("app.bot")

    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан — заполните .env")
    if not settings.remnawave_api_url or not settings.remnawave_api_token:
        log.warning("REMNAWAVE_API_URL/REMNAWAVE_API_TOKEN не заданы — выдача подписок работать не будет")

    await init_db()
    log.info("База данных инициализирована")

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import BotCommand, BotCommandScopeDefault

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    notifications.set_bot(bot)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
        ],
        scope=BotCommandScopeDefault(),
    )

    runner = await start_health_server(settings.bot_http_port, "bot")
    log.info("Health-сервер бота слушает 0.0.0.0:%d", settings.bot_http_port)

    dp = build_dispatcher()
    try:
        # polling: входящие HTTPS-подключения не требуются
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await runner.cleanup()
        await notifications.close_bot()
        await close_remna()
        await dispose_db()
        log.info("Бот остановлен (graceful shutdown)")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
