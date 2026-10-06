"""Сборка FastAPI-приложения админ-панели (порт 8090).

Здесь же: безопасные заголовки, проверка Origin для POST, rate limit и лимит
размера тела для вебхука YooMoney, healthcheck, graceful shutdown.
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin.routes import router as panel_router
from app.config import get_settings
from app.database import dispose_db, init_db
from app.services import notifications
from app.services.remnawave import close_remna
from app.services.yoomoney import SimpleRateLimiter
from app.utils import setup_logging


def create_app() -> FastAPI:
    s = get_settings()
    log = logging.getLogger("app.admin")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        setup_logging()
        if not s.admin_password:
            log.warning("ADMIN_PASSWORD не задан — вход в админку отключён")
        if not s.session_secret:
            log.warning("ADMIN_SESSION_SECRET/APP_SECRET не заданы — сессии сбросятся при перезапуске")
        await init_db()
        if s.bot_token:
            try:
                from aiogram import Bot
                from aiogram.client.default import DefaultBotProperties
                from aiogram.enums import ParseMode

                notifications.set_bot(
                    Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                )
            except Exception:  # noqa: BLE001
                log.exception("Не удалось инициализировать Telegram-клиент для уведомлений")
        log.info("Админ-панель запущена (порт %d)", s.admin_port)
        yield
        await notifications.close_bot()
        await close_remna()
        await dispose_db()
        log.info("Админ-панель остановлена (graceful shutdown)")

    app = FastAPI(
        title="VPN Admin",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=s.session_secret or secrets.token_hex(32),
        session_cookie="vpnadmin",
        max_age=43200,  # 12 часов
        same_site="lax",
    )

    webhook_limiter = SimpleRateLimiter(s.webhook_rate_limit_per_minute, 60)

    @app.middleware("http")
    async def _guards(request: Request, call_next):
        path = request.url.path
        is_webhook = request.method == "POST" and path == s.yoomoney_webhook_path

        # CSRF-защита форм: Origin (если передан) должен совпадать с Host
        if request.method == "POST" and not is_webhook:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                return PlainTextResponse("Forbidden", status_code=403)

        # rate limit + лимит размера заголовка Content-Length для вебхука
        if is_webhook:
            ip = request.client.host if request.client else "-"
            if not webhook_limiter.allow(ip):
                return PlainTextResponse("rate limited", status_code=429)
            cl = request.headers.get("content-length", "")
            if cl.isdigit() and int(cl) > s.webhook_max_body_bytes:
                return PlainTextResponse("too large", status_code=413)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not path.startswith("/static"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:",
            )
        return response

    app.include_router(panel_router)
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "admin"}

    return app


app = create_app()
