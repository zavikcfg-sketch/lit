"""Асинхронный доступ к базе данных (SQLite по умолчанию, PostgreSQL опционально)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import Engine
from sqlalchemy import event

from app.config import get_settings
from app.models import Base, Tariff

log = logging.getLogger("app.db")

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _normalize_url(url: str) -> str:
    """Разрешаем короткие формы URL: sqlite:/// и postgresql://."""
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        url = "sqlite+aiosqlite" + url[len("sqlite"):]
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _safe_url(url: str) -> str:
    """URL без учётных данных — для безопасного логирования."""
    return re.sub(r"(://[^:/@]+):([^@/]+)@", r":***@", url)


def _sqlite_file_path(url: str) -> Path | None:
    rest = url.split("sqlite+aiosqlite:///", 1)[-1]
    if not rest or rest.startswith(":memory:") or rest == "":
        return None
    return Path(rest)


async def init_db() -> None:
    """Создаёт движок, схему и стартовые тарифы. Вызывается при старте обоих сервисов."""
    global _engine, _sessionmaker

    settings = get_settings()
    url = _normalize_url(settings.database_url)

    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite+aiosqlite"):
        path = _sqlite_file_path(url)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"timeout": 30}

    _engine = create_async_engine(url, **kwargs)

    if url.startswith("sqlite+aiosqlite"):

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await seed_tariffs()
    log.info("База данных готова: %s", _safe_url(url))


async def seed_tariffs() -> None:
    """Добавляет тарифы из .env, если их ещё нет в базе (существующие не трогаем)."""
    settings = get_settings()
    async with get_session() as session:
        rows = await session.execute(select(Tariff.code))
        existing = {code for (code,) in rows.all()}
        created = 0
        for sort, tdef in enumerate(settings.default_tariffs()):
            if tdef.code in existing:
                continue
            session.add(
                Tariff(
                    code=tdef.code,
                    days=tdef.days,
                    price=tdef.price,
                    title=tdef.title,
                    enabled=True,
                    sort=sort,
                )
            )
            created += 1
        if created:
            await session.commit()
            log.info("Создано тарифов из .env: %d", created)


def get_session() -> AsyncSession:
    if _sessionmaker is None:
        raise RuntimeError("База не инициализирована: сначала вызовите init_db()")
    return _sessionmaker()


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
