"""Конфигурация приложения. Все секреты — только из переменных окружения (.env).

Никакие токены/пароли не хранятся в коде. Значения по умолчанию — пустые.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FEE_MODES = ("none", "client_fixed", "absorb")


@dataclass(frozen=True)
class TariffDef:
    code: str
    days: int
    price: Decimal
    title: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- Telegram ----
    bot_token: str = ""
    bot_username: str = ""
    admin_id: int = 0
    support_username: str = "@support"

    # ---- Remnawave ----
    remnawave_api_url: str = ""
    remnawave_api_token: str = ""
    remnawave_timeout: float = 20.0
    # UUID внутренних сквадов через запятую — новые пользователи будут добавляться в них
    remnawave_default_squads: str = ""

    # ---- YooMoney ----
    yoomoney_wallet: str = ""
    yoomoney_access_token: str = ""
    yoomoney_notification_secret: str = ""
    yoomoney_fee_mode: str = "client_fixed"
    yoomoney_fee_percent: Decimal = Decimal("1")
    yoomoney_webhook_path: str = "/yoomoney/notification"

    # ---- Тарифы (стартовые; далее управляются в админ-панели) ----
    price_7_days: Decimal = Field(
        default=Decimal("100"), validation_alias=AliasChoices("PRICE_7_DAYS", "PRICES_7")
    )
    price_30_days: Decimal = Field(
        default=Decimal("250"), validation_alias=AliasChoices("PRICE_30_DAYS", "PRICES_30")
    )
    price_90_days: Decimal = Field(
        default=Decimal("600"), validation_alias=AliasChoices("PRICE_90_DAYS", "PRICES_90")
    )
    price_180_days: Decimal = Field(
        default=Decimal("1000"), validation_alias=AliasChoices("PRICE_180_DAYS", "PRICES_180")
    )
    price_365_days: Decimal = Field(
        default=Decimal("1800"), validation_alias=AliasChoices("PRICE_365_DAYS", "PRICES_365")
    )

    # ---- База данных ----
    database_url: str = "sqlite+aiosqlite:///data/bot.db"

    # ---- Админ-панель ----
    admin_user: str = "admin"
    admin_password: str = ""
    admin_session_secret: str = ""
    app_secret: str = ""
    admin_port: int = 8090
    bot_http_port: int = 8088

    # ---- Прочее ----
    log_level: str = "INFO"
    display_tz: str = "Europe/Moscow"
    webhook_rate_limit_per_minute: int = 60
    webhook_max_body_bytes: int = 65536
    broadcast_default_rate: float = 10.0

    @field_validator("yoomoney_fee_mode")
    @classmethod
    def _validate_fee_mode(cls, v: str) -> str:
        v = (v or "client_fixed").strip().lower()
        if v not in FEE_MODES:
            raise ValueError(f"YOOMONEY_FEE_MODE: допустимо {' | '.join(FEE_MODES)}")
        return v

    @field_validator("yoomoney_fee_percent")
    @classmethod
    def _validate_fee_percent(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 100:
            raise ValueError("YOOMONEY_FEE_PERCENT должен быть в диапазоне 0..100")
        return v

    @property
    def default_squads(self) -> list[str]:
        """Список UUID сквадов из REMNAWAVE_DEFAULT_SQUADS (через запятую/пробел)."""
        return [x.strip() for x in self.remnawave_default_squads.replace(";", ",").split(",") if x.strip()]

    @property
    def session_secret(self) -> str:
        """Секрет для подписи cookie-сессий админки."""
        return self.admin_session_secret or self.app_secret

    def default_tariffs(self) -> list[TariffDef]:
        return [
            TariffDef("7d", 7, self.price_7_days, "7 дней"),
            TariffDef("30d", 30, self.price_30_days, "30 дней"),
            TariffDef("90d", 90, self.price_90_days, "90 дней"),
            TariffDef("180d", 180, self.price_180_days, "180 дней"),
            TariffDef("365d", 365, self.price_365_days, "365 дней"),
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
