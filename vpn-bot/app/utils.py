"""Общие утилиты: время, имена пользователей, валидация, экранирование."""
from __future__ import annotations

import html
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,36}$")


def utcnow() -> datetime:
    """Текущее время в UTC (naive — в базе храним наивные UTC-даты)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_iso_utc(value: str | None) -> datetime | None:
    """'2026-11-04T00:00:00.000Z' -> naive UTC datetime."""
    if not value:
        return None
    v = str(value).strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def format_iso_z(dt: datetime) -> str:
    """naive UTC datetime -> '2026-11-04T00:00:00.000Z'."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def expire_after(days: int) -> datetime:
    return utcnow() + timedelta(days=int(days))


def days_left(expire_at: datetime | None) -> int:
    if expire_at is None:
        return 0
    return max(0, (expire_at - utcnow()).days)


def display_dt(dt: datetime | None, tz_name: str = "Europe/Moscow") -> str:
    """Формат даты для показа пользователю."""
    if dt is None:
        return "—"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    local = dt.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%d.%m.%Y %H:%M")


def valid_telegram_id(value: object) -> bool:
    try:
        iv = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return 0 < iv < 2**63


def esc(text: object) -> str:
    """HTML-экранирование для сообщений Telegram (parse_mode=HTML)."""
    return html.escape(str(text), quote=False)


def make_username(telegram_id: int) -> str:
    """Username Remnawave: tg_<telegram_id>; 3–36 символов, [A-Za-z0-9_-]."""
    base = f"tg_{telegram_id}"
    if USERNAME_RE.fullmatch(base):
        return base
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "", base)[:32] or "tg"
    return f"{sanitized}_{secrets.token_hex(2)}"[:36]


def rand_hex(n: int) -> str:
    return secrets.token_hex((n + 1) // 2)[:n]


def setup_logging() -> None:
    """Единая настройка логирования (бот и админка). Секреты в логи не попадают."""
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def fmt_money(value: object) -> str:
    """Decimal/число -> '250' или '249.75' (без экспоненты)."""
    from decimal import Decimal

    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return str(value)
    s = f"{d:f}".rstrip("0").rstrip(".")
    return s or "0"
