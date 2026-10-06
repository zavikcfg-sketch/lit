"""HTTP-клиент Remnawave API (backend 3.x).

Все запросы:
  * авторизуются Bearer-токеном из .env (REMNAWAVE_API_TOKEN);
  * имеют таймаут;
  * корректно обрабатывают 400/401/403/404/5xx;
  * логируют ошибки БЕЗ токенов и секретов;
  * возвращают понятные исключения.

Никогда не удаляет пользователей Remnawave (delete в принципе не реализован).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings
from app.utils import expire_after, format_iso_z, make_username

log = logging.getLogger("app.remnawave")


class RemnaError(Exception):
    """Базовая ошибка Remnawave API."""


class RemnaAuthError(RemnaError):
    """401/403 — неверный или просроченный API-токен."""


class RemnaNotFound(RemnaError):
    """404 — объект не найден."""


class RemnaBadRequest(RemnaError):
    """400/422 — некорректный запрос."""


class RemnaServerError(RemnaError):
    """5xx — ошибка на стороне панели."""


class RemnaWaveClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 20.0,
        default_squads: list[str] | None = None,
    ) -> None:
        if not base_url:
            raise RemnaError("REMNAWAVE_API_URL не задан")
        if not token:
            raise RemnaError("REMNAWAVE_API_TOKEN не задан")
        self._base_url = base_url.rstrip("/")
        self._default_squads = [s for s in (default_squads or []) if s]
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "vpn-bot/1.0",
            },
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def default_squads(self) -> list[str]:
        return list(self._default_squads)

    # ------------------------------------------------------------------ core

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Выполняет запрос, возвращает payload (развёрнутый из envelope 'response')."""
        try:
            resp = await self._client.request(method, path, json=json, params=params)
        except httpx.TimeoutException:
            raise RemnaError(f"Remnawave: таймаут запроса {method} {path}") from None
        except httpx.HTTPError as exc:
            raise RemnaError(f"Remnawave: сетевая ошибка ({type(exc).__name__}) {method} {path}") from exc

        detail = ""
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("detail") or "")[:300]

        if resp.status_code in (401, 403):
            raise RemnaAuthError(f"Remnawave: доступ запрещён (HTTP {resp.status_code}). Проверьте REMNAWAVE_API_TOKEN")
        if resp.status_code == 404:
            raise RemnaNotFound(f"Remnawave: не найдено (404) {path}")
        if resp.status_code in (400, 409, 422):
            raise RemnaBadRequest(f"Remnawave: HTTP {resp.status_code} {method} {path} — {detail or 'некорректный запрос'}")
        if resp.status_code >= 500:
            raise RemnaServerError(f"Remnawave: ошибка сервера (HTTP {resp.status_code}) {path} — {detail}")
        if resp.status_code >= 300:
            raise RemnaError(f"Remnawave: неожиданный ответ HTTP {resp.status_code} {path}")

        if payload is None:
            return {}
        if isinstance(payload, dict) and "response" in payload:
            return payload["response"]
        return payload

    # ------------------------------------------------------------- raw users

    async def create_user(
        self,
        *,
        username: str,
        telegram_id: int,
        days: int,
        traffic_limit_bytes: int = 0,
        traffic_limit_strategy: str = "NO_RESET",
        status: str = "ACTIVE",
        expire_at: datetime | None = None,
    ) -> dict:
        """POST /api/users — создание пользователя."""
        expire = expire_at or expire_after(days)
        payload: dict = {
            "username": username,
            "expireAt": format_iso_z(expire),
            "status": status,
            "trafficLimitBytes": traffic_limit_bytes,
            "trafficLimitStrategy": traffic_limit_strategy,
        }
        if telegram_id:
            payload["telegramId"] = int(telegram_id)
        if self._default_squads:
            # пользователь сразу попадает на ноды этих сквадов
            payload["activeInternalSquads"] = list(self._default_squads)
        data = await self._request("POST", "/api/users", json=payload)
        if not isinstance(data, dict) or not data.get("id"):
            raise RemnaError("Remnawave: неожиданный ответ при создании пользователя")
        log.info("Remnawave: создан пользователь %s (telegram_id=%s)", data.get("username"), telegram_id)
        return data

    async def get_user(self, user_id: str | int) -> dict:
        """GET /api/users/{uuid}."""
        data = await self._request("GET", f"/api/users/{user_id}")
        return data if isinstance(data, dict) else {}

    async def find_user_by_telegram_id(self, telegram_id: int) -> dict | None:
        """Поиск пользователя по Telegram ID (с fallback'ом по username tg_<id>)."""
        try:
            data = await self._request("GET", f"/api/users/by-telegram-id/{telegram_id}")
        except RemnaNotFound:
            data = None
        if isinstance(data, list):
            return data[0] if data else None
        if isinstance(data, dict) and data.get("id"):
            return data
        # Fallback: у нас детерминированные username -> пробуем поиск по имени
        try:
            data = await self._request("GET", f"/api/users/by-username/{make_username(telegram_id)}")
        except RemnaNotFound:
            return None
        return data if isinstance(data, dict) and data.get("id") else None

    async def update_user(self, user_id: str | int, **fields) -> dict:
        """PATCH /api/users — обновление полей (uuid + поля)."""
        payload = {"uuid": str(user_id), **fields}
        data = await self._request("PATCH", "/api/users", json=payload)
        return data if isinstance(data, dict) else {}

    async def extend_user(self, user_id: str | int, days: int) -> dict:
        """POST /api/users/{uuid}/actions/extend — продление на N дней."""
        days = max(1, min(int(days), 3650))
        data = await self._request("POST", f"/api/users/{user_id}/actions/extend", json={"days": days})
        if not isinstance(data, dict) or not data:
            # некоторые версии возвращают пустое тело — дочитываем пользователя
            data = await self.get_user(user_id)
        return data

    async def disable_user(self, user_id: str | int) -> dict:
        """POST /api/users/{uuid}/actions/disable — блокировка."""
        return await self._request("POST", f"/api/users/{user_id}/actions/disable", json={})

    async def enable_user(self, user_id: str | int) -> dict:
        """POST /api/users/{uuid}/actions/enable — разблокировка."""
        return await self._request("POST", f"/api/users/{user_id}/actions/enable", json={})

    # ---------------------------------------------------------- subscriptions

    async def get_subscription(self, user_id: str | int) -> dict | None:
        """GET /api/subscriptions/by-id/{userId} — данные подписки (или None)."""
        try:
            data = await self._request("GET", f"/api/subscriptions/by-id/{user_id}")
        except RemnaNotFound:
            return None
        return data if isinstance(data, dict) else None

    async def get_connection_keys(self, user_id: str | int) -> Any | None:
        """GET /api/subscriptions/connection-keys/{userId} — ключи подключения (или None)."""
        try:
            data = await self._request("GET", f"/api/subscriptions/connection-keys/{user_id}")
        except RemnaNotFound:
            return None
        return data


# ------------------------------------------------------------------ singleton

_client: RemnaWaveClient | None = None


def get_remna() -> RemnaWaveClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = RemnaWaveClient(
            base_url=s.remnawave_api_url,
            token=s.remnawave_api_token,
            timeout=s.remnawave_timeout,
            default_squads=s.default_squads,
        )
    return _client


async def close_remna() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
