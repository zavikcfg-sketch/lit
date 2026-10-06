#!/usr/bin/env bash
# ============================================================
# VPN-бот (Remnawave + YooMoney) — деплой/обновление файлов проекта
# Сгенерировано scripts/gen_deploy.py — вручную не редактировать.
#
# Использование:
#   bash vpn-bot-deploy.sh            # только создать/обновить файлы
#   bash vpn-bot-deploy.sh --deploy   # + docker compose build && up -d
#
# Скрипт НЕ трогает: .env (если уже существует), volume с базой данных.
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Создание структуры каталогов vpn-bot"
mkdir -p vpn-bot/app
mkdir -p vpn-bot/app/admin
mkdir -p vpn-bot/app/admin/static
mkdir -p vpn-bot/app/admin/templates
mkdir -p vpn-bot/app/services
mkdir -p vpn-bot/app/telegram

echo "==> Запись файлов проекта"
cat > vpn-bot/.dockerignore <<'RW_EOF_1'
.git
.gitignore
.env
.env.*
!.env.example
data/
*.db
*.db-wal
*.db-shm
__pycache__/
*.pyc
*.pyo
.venv/
venv/
.mypy_cache/
.pytest_cache/
README.md
docker-compose.yml
Dockerfile
Dockerfile.admin
.caddy/
logs/
RW_EOF_1
cat > vpn-bot/.env.example <<'RW_EOF_2'
# ============================================================
# VPN-бот (Remnawave + YooMoney) — пример окружения.
# Скопируйте:  cp .env.example .env   и заполните своими значениями.
# НИКОГДА не коммитьте реальный .env в git и не присылайте его в чат.
# ============================================================

# ---- Telegram ----
# Токен бота от @BotFather
BOT_TOKEN=
# Юзернейм бота без @ (для deep-link'ов после оплаты, необязательно)
BOT_USERNAME=
# Telegram ID главного администратора (команды /admin, /find, /msg)
ADMIN_ID=0
# Куда писать за поддержкой (показывается в разделе «Помощь»)
SUPPORT_USERNAME=@support

# ---- Remnawave ----
# Базовый URL панели (без /api на конце)
REMNAWAVE_API_URL=https://panel.litenergyapp.store
# API-токен панели (Профиль -> API токены). Не светите его нигде.
REMNAWAVE_API_TOKEN=
# UUID внутренних сквадов (панель -> Внутренние сквады), через запятую.
# Новые пользователи бота будут автоматически добавляться в эти сквады (доступ к нодам).
REMNAWAVE_DEFAULT_SQUADS=
# Таймаут HTTP-запросов к панели, секунд
REMNAWAVE_TIMEOUT=20

# ---- YooMoney ----
# Номер кошелька (получатель платежей)
YOOMONEY_WALLET=4100000000000000
# OAuth-токен для API истории операций (кнопка «Проверить оплату»); можно оставить пустым
YOOMONEY_ACCESS_TOKEN=
# Секрет HTTP-уведомлений (yoomoney.ru -> Кошелёк -> Настройки -> HTTP-уведомления). ОБЯЗАТЕЛЕН для вебхука!
YOOMONEY_NOTIFICATION_SECRET=
# Режим комиссии: none | client_fixed (клиент платит сверху) | absorb (принимаем чуть меньше)
YOOMONEY_FEE_MODE=client_fixed
# Процент комиссии
YOOMONEY_FEE_PERCENT=1
# Путь вебхука (должен совпадать с URL, указанным в настройках YooMoney)
YOOMONEY_WEBHOOK_PATH=/yoomoney/notification

# ---- Тарифы (стартовые значения; дальше цены правятся в админке) ----
# Поддерживаются также короткие имена: PRICES_7, PRICES_30, PRICES_90, PRICES_180, PRICES_365
PRICE_7_DAYS=100
PRICE_30_DAYS=250
PRICE_90_DAYS=600
PRICE_180_DAYS=1000
PRICE_365_DAYS=1800

# ---- База данных ----
# SQLite (по умолчанию, общий volume для bot и admin):
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
# PostgreSQL (если хотите использовать существующий сервер):
# DATABASE_URL=postgresql+asyncpg://user:password@127.0.0.1:5432/vpnbot

# ---- Админ-панель (порт 8090) ----
ADMIN_USER=admin
# Пароль входа в админку. Сгенерируйте: openssl rand -base64 24
ADMIN_PASSWORD=
# Секрет для подписи cookie-сессий. Сгенерируйте: openssl rand -hex 32
ADMIN_SESSION_SECRET=
# Дополнительный секрет приложения
APP_SECRET=
ADMIN_PORT=8090
# Внутренний HTTP-порт бота (healthcheck; наружу не публикуется)
BOT_HTTP_PORT=8088

# ---- Прочее ----
LOG_LEVEL=INFO
# Часовой пояс для отображения дат
DISPLAY_TZ=Europe/Moscow
# Лимиты защиты вебхука
WEBHOOK_RATE_LIMIT_PER_MINUTE=60
WEBHOOK_MAX_BODY_BYTES=65536
# Скорость рассылки по умолчанию (сообщений в секунду)
BROADCAST_DEFAULT_RATE=10
RW_EOF_2
cat > vpn-bot/Dockerfile <<'RW_EOF_3'
# Dockerfile Telegram-бота (порт 8088, health-сервер)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN groupadd -r app && useradd -r -g app app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/health', timeout=4)"

CMD ["python", "-m", "app.main"]
RW_EOF_3
cat > vpn-bot/Dockerfile.admin <<'RW_EOF_4'
# Dockerfile админ-панели (порт 8090, FastAPI/uvicorn)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN groupadd -r app && useradd -r -g app app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "app.admin.app:app", \
     "--host", "0.0.0.0", "--port", "8090", \
     "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=*"]
RW_EOF_4
cat > vpn-bot/README.md <<'RW_EOF_5'
# VPN-бот: продажа подписок через Remnawave + YooMoney

Production-ready Telegram-бот (Python 3.12, aiogram 3, FastAPI, SQLAlchemy 2 async)
+ веб-админка. Оплата — YooMoney (HTTP-уведомления), выдача подписок — Remnawave API 3.x.

```
                         ┌────────────────────────────┐
 Telegram ──(polling)──► │  bot   (порт 8088, health) │──┐
                         └────────────────────────────┘  │   ┌──────────────┐
                                                         ├──►│  БД (volume) │
 YooMoney ──(webhook)──► Caddy ──► ┌──────────────────┐  │   └──────────────┘
 admin.panel.…/yoomoney/notification│ admin (8090)     │──┘
 браузер ─────────────► Caddy ──►   │  FastAPI админка │
                                    └──────────────────┘──► Remnawave API (https)
```

* **bot** — Telegram-бот (polling, входящих подключений не требует) + healthcheck на `:8088`.
* **admin** — админ-панель + вебхук YooMoney на `:8090` (наружу через Caddy).
* **БД** — SQLite (по умолчанию) или PostgreSQL, общий volume `bot_data`.

---

## 1. Быстрый старт

```bash
# на сервере, в каталоге проекта
cd vpn-bot

# 1) окружение
cp .env.example .env
nano .env      # заполнить BOT_TOKEN, REMNAWAVE_*, YOOMONEY_*, ADMIN_PASSWORD, секреты

# секреты сгенерировать так:
#   openssl rand -hex 32      -> ADMIN_SESSION_SECRET / APP_SECRET
#   openssl rand -base64 24   -> ADMIN_PASSWORD

# 2) запуск
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f --tail=100
```

Требуется Docker + Docker Compose v2 (`docker compose version`). Caddy/Remnawave/PostgreSQL/Redis,
уже работающие на сервере, не трогаются.

---

## 2. Переменные окружения (`.env`)

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен из @BotFather |
| `BOT_USERNAME` | юзернейм бота без `@` (кнопка возврата после оплаты) |
| `ADMIN_ID` | Telegram ID админа (команды `/admin`, `/find`, `/msg`) |
| `SUPPORT_USERNAME` | контакт поддержки в разделе «Помощь» |
| `REMNAWAVE_API_URL` | `https://panel.litenergyapp.store` (без `/api`) |
| `REMNAWAVE_API_TOKEN` | API-токен панели (Bearer) |
| `YOOMONEY_WALLET` | номер кошелька |
| `YOOMONEY_NOTIFICATION_SECRET` | секрет HTTP-уведомлений (обязателен для вебхука!) |
| `YOOMONEY_ACCESS_TOKEN` | OAuth-токен API (кнопка «Проверить оплату»), необязателен |
| `YOOMONEY_FEE_MODE` | `none` \| `client_fixed` (клиент платит комиссию сверху) \| `absorb` |
| `YOOMONEY_FEE_PERCENT` | процент комиссии |
| `PRICE_7_DAYS … PRICE_365_DAYS` | стартовые цены (алиасы `PRICES_7` и т.п. тоже работают) |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/bot.db` или `postgresql+asyncpg://user:pass@host/db` |
| `ADMIN_USER`, `ADMIN_PASSWORD` | вход в админку |
| `ADMIN_SESSION_SECRET` / `APP_SECRET` | подпись cookie-сессий |
| `DISPLAY_TZ` | часовой пояс отображения (по умолчанию Europe/Moscow) |

> ⚠️ Никогда не публикуйте `.env`. Все токены в коде отсутствуют — только окружение.

---

## 3. Настройка YooMoney

1. Зайдите на **yoomoney.ru** → кошелёк → **Настройки** → блок **«HTTP-уведомления»** (или
   «Уведомления» → «Настроить уведомления»).
2. URL: `https://admin.panel.litenergyapp.store/yoomoney/notification`
3. Секрет (строка) скопируйте в `.env` → `YOOMONEY_NOTIFICATION_SECRET`, перезапустите `admin`:
   `docker compose up -d --force-recreate admin`
4. Включите уведомления. YooMoney шлёт `notification_type=p2p-incoming` c `sha1_hash`
   (или `sha256_hash`, если выбран в личном кабинете) — бот проверяет оба варианта.
5. Ссылки на оплату формируются через quickpay: `https://yoomoney.ru/quickpay/confirm?...`
   с уникальным `label=rw_<telegram_id>_<hex>` и `paymentType=AC` (карта).
6. Для кнопки «Проверить оплату» создайте OAuth-токен: yoomoney.ru →
   **Разработчикам → API** → права «История операций» → вставьте в `YOOMONEY_ACCESS_TOKEN`.

**Идемпотентность гарантируется:** уникальный `label` заказа, уникальный `operation_id`
(таблица `payment_events`), атомарный перевод заказа `pending → paid`. Повторные
уведомления и двойные оплаты дни не начисляют.

**Оплата считается успешной, если** подпись верна, валюта RUB, `codepro=false`,
`unaccepted=false` и сумма ≥ ожидаемой (с учётом режима комиссии `YOOMONEY_FEE_MODE`).

---

## 4. Настройка Caddy

На хосте в `/etc/caddy/Caddyfile` добавьте/проверьте блок:

```caddy
admin.panel.litenergyapp.store {
    reverse_proxy 127.0.0.1:8090
}
```

Применить:

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

После этого доступны:

* Админка: `https://admin.panel.litenergyapp.store`
* Вебхук YooMoney: `https://admin.panel.litenergyapp.store/yoomoney/notification`
* Healthcheck: `https://admin.panel.litenergyapp.store/health`

Telegram-бот работает через **long polling** — публичный HTTPS для него не нужен.

---

## 5. Команды эксплуатации

```bash
docker compose ps                     # статус + healthcheck
docker compose logs -f bot            # логи бота
docker compose logs -f admin          # логи админки/вебхука
docker compose restart bot admin      # перезапуск
docker compose up -d --build          # пересборка и запуск (БД НЕ удаляется)
docker compose down                   # остановка (volume остаётся)
```

**Обновление кода без потери базы:**

```bash
bash ../vpn-bot-deploy.sh      # перезаписать файлы проекта (.env и volume не трогаются)
docker compose up -d --build
docker compose exec bot python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"
# последняя команда опционально: применит новую схему (create_all) и досоздаст тарифы из .env
```

> Схема БД создаётся через `create_all` при старте: новые таблицы/колонки добавляются
> автоматически; удаление/переименование колонок требует миграции (alembic) — заложено в
> архитектуру, но для этого проекта не требуется.

---

## 6. Резервное копирование и восстановление

**Бэкап (без остановки):**

```bash
cd vpn-bot
docker compose exec -T bot python - <<'PY'
import sqlite3
src = sqlite3.connect("/app/data/bot.db")
dst = sqlite3.connect("/app/data/backup.db")
src.backup(dst)
dst.close(); src.close()
print("backup done")
PY
docker compose cp bot:/app/data/backup.db ./bot-backup-$(date +%F).db
```

**Восстановление:**

```bash
cd vpn-bot
docker compose down
docker run --rm -v vpnbot_bot_data:/data -v "$PWD":/backup alpine \
    sh -c "cp /backup/bot-backup-YYYY-MM-DD.db /data/bot.db && chown 999:999 /data/bot.db"
docker compose up -d
```

(имя тома `vpnbot_bot_data` уточните: `docker volume ls | grep bot`)

---

## 7. Админ-панель

`https://admin.panel.litenergyapp.store` — вход по `ADMIN_USER`/`ADMIN_PASSWORD`
(лимит попыток входа, cookie-сессия 12 ч, logout, токены в интерфейсе не показываются).

| Раздел | Возможности |
|---|---|
| **Дашборд** | пользователи, активные/истёкшие подписки, заказы, выручка, продажи за день/месяц, последние заказы |
| **Пользователи** | поиск (Telegram ID / username / Remna ID), фильтр статуса, пагинация, продление, блокировка/разблокировка, отправка ключа |
| **Заказы** | поиск (order_id / label / operation_id / Telegram ID), статусы, суммы, переотправка ключа/довыдача |
| **Тарифы** | изменение цен, включение/отключение (цены из `.env` — стартовые, дальше живут в БД) |
| **Рассылка** | черновик, скорость (1–30 msg/s), получатели (все/активные), предпросмотр, подтверждение, живой прогресс и журнал |
| **Логи** | действия админов, платёжные события (webhook), ошибки YooMoney/Remnawave |

**Telegram-команды админа:** `/admin` — статистика, `/find <tg_id>` — карточка пользователя,
`/msg <tg_id> <текст>` — сообщение пользователю.

---

## 8. Безопасность — что уже сделано

* токены/пароли только в `.env`; в логи не пишутся (логируются URL и статусы);
* вебхук: обязательная проверка `sha1_hash`/`sha256_hash`, rate limit (60/мин, настраивается),
  лимит размера тела (64 КБ), идемпотентность по `operation_id` и статусу заказа;
* админка: сессии с подписью, безопасное сравнение пароля, лимит попыток входа,
  проверка Origin на POST, security-заголовки (`X-Frame-Options`, `nosniff`, CSP),
  подтверждение опасных действий, журнал админ-действий;
* валидация Telegram ID и тарифов (тариф всегда читается из БД, цену подделать нельзя);
* контейнеры от non-root пользователя, `restart: unless-stopped`, healthcheck, graceful shutdown;
* Remnawave-пользователи **никогда не удаляются автоматически** — API удаления не используется.

## 9. Структура проекта

```
vpn-bot/
├── app/
│   ├── main.py                  # запуск бота (polling + health :8088)
│   ├── config.py                # все настройки из .env
│   ├── database.py              # async SQLAlchemy, WAL, сидирование тарифов
│   ├── models.py                # users, orders, payment_events, admin_actions, service_logs, tariffs
│   ├── utils.py                 # время, валидация, username, логирование
│   ├── telegram/
│   │   ├── handlers_start.py    # /start, меню, помощь
│   │   ├── handlers_shop.py     # тарифы -> заказ -> ссылка YooMoney
│   │   ├── handlers_subscription.py  # моя подписка, проверка оплаты, ключи
│   │   └── handlers_admin.py    # /admin, /find, /msg (только ADMIN_ID)
│   ├── services/
│   │   ├── remnawave.py         # клиент API панели (create/extend/enable/disable/keys)
│   │   ├── yoomoney.py          # quickpay, подпись вебхука, идемпотентная обработка
│   │   ├── orders.py            # заказы, фиксация оплат, выдача/продление
│   │   ├── notifications.py     # отправка сообщений, тексты
│   │   ├── tariffs.py           # тарифы из БД
│   │   └── broadcasts.py        # менеджер рассылок
│   └── admin/
│       ├── app.py               # FastAPI (8090), middleware безопасности
│       ├── auth.py              # сессии, лимит попыток
│       ├── routes.py            # все разделы + POST /yoomoney/notification
│       ├── templates/           # Jinja2 (тёмная тема, адаптив)
│       └── static/              # css/js без внешних CDN
├── Dockerfile                   # бот
├── Dockerfile.admin             # админка
├── docker-compose.yml           # bot + admin + volume
├── requirements.txt
├── .env.example
└── .dockerignore
```
RW_EOF_5
cat > vpn-bot/app/__init__.py <<'RW_EOF_6'
"""VPN-бот: Remnawave + YooMoney (aiogram 3 + FastAPI)."""
RW_EOF_6
cat > vpn-bot/app/admin/__init__.py <<'RW_EOF_7'
RW_EOF_7
cat > vpn-bot/app/admin/app.py <<'RW_EOF_8'
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
RW_EOF_8
cat > vpn-bot/app/admin/auth.py <<'RW_EOF_9'
"""Аутентификация админ-панели: cookie-сессии, безопасное сравнение, лимит попыток.

Пароль хранится только в .env (ADMIN_PASSWORD). Токены в интерфейсе не показываются.
"""
from __future__ import annotations

import secrets

from app.config import get_settings
from app.services.yoomoney import SimpleRateLimiter

# не более 8 попыток входа в минуту с одного IP
login_limiter = SimpleRateLimiter(max_events=8, window_seconds=60)


def check_login(username: str, password: str) -> bool:
    """Постоянновременное сравнение строк — защита от timing-атак."""
    s = get_settings()
    if not s.admin_password:
        return False
    ok_user = secrets.compare_digest(
        str(username).encode("utf-8"), s.admin_user.encode("utf-8")
    )
    ok_pass = secrets.compare_digest(
        str(password).encode("utf-8"), s.admin_password.encode("utf-8")
    )
    return ok_user and ok_pass


def is_authenticated(request) -> bool:
    return bool(request.session.get("adm"))
RW_EOF_9
cat > vpn-bot/app/admin/routes.py <<'RW_EOF_10'
"""Маршруты админ-панели и вебхука YooMoney.

Разделы: Dashboard, Users, Orders, Tariffs, Broadcast, Logs + POST /yoomoney/notification.
Безопасность: сессионная авторизация, подтверждение опасных действий (на фронте),
журналирование админ-действий, никаких токенов в интерфейсе.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import String as SAString
from sqlalchemy import and_, cast, func, or_, select

from app.admin.auth import check_login, is_authenticated, login_limiter
from app.config import get_settings
from app.database import get_session
from app.models import AdminAction, Order, PaymentEvent, ServiceLog, Tariff, User
from app.services import notifications, orders
from app.services.broadcasts import manager as broadcast_manager
from app.services.remnawave import RemnaError, get_remna
from app.services.yoomoney import process_notification
from app.utils import display_dt, fmt_money, utcnow, valid_telegram_id

log = logging.getLogger("app.admin")

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["dt"] = lambda v: display_dt(v, get_settings().display_tz)
templates.env.filters["money"] = fmt_money

USER_STATUSES = ("ACTIVE", "BLOCKED", "EXPIRED")
ORDER_STATUSES = ("pending", "paid", "canceled")
LOG_KINDS = ("yoomoney", "remnawave", "webhook", "broadcast", "bot")


# ------------------------------------------------------------------ helpers

def _render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    context = dict(ctx or {})
    context.setdefault("msg", request.query_params.get("msg"))
    context.setdefault("k", request.query_params.get("k", "ok"))
    context.setdefault("path", request.url.path)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _redirect(url: str, msg: str | None = None, kind: str = "ok") -> RedirectResponse:
    if msg:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}msg={quote(msg)}&k={kind}"
    return RedirectResponse(url, status_code=303)


def _guard(request: Request) -> RedirectResponse | None:
    if is_authenticated(request):
        return None
    return _redirect("/login", "Требуется вход в панель")


def _back(request: Request) -> str:
    """URL для возврата после POST (сохраняет фильтры и страницу)."""
    qp = [(k, v) for k, v in request.query_params.multi_items() if k not in ("msg", "k", "page")]
    base = request.url.path
    if qp:
        return base + "?" + "&".join(f"{k}={quote(v)}" for k, v in qp)
    return base


def _base_qs(request: Request) -> str:
    qp = [(k, v) for k, v in request.query_params.multi_items() if k not in ("page", "msg", "k")]
    if qp:
        return "&".join(f"{k}={quote(v)}" for k, v in qp) + "&"
    return ""


def _paginate(request: Request, total: int, per: int = 20) -> dict:
    pages = max(1, (total + per - 1) // per)
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    page = min(max(1, page), pages)
    return {"page": page, "pages": pages, "per": per, "offset": (page - 1) * per, "total": total}


async def _log_admin(action: str, target: str = "", details: str = "") -> None:
    s = get_settings()
    try:
        async with get_session() as session:
            session.add(
                AdminAction(
                    admin_id=s.admin_id,
                    action=action[:64],
                    target=str(target)[:128],
                    details=str(details)[:2000],
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось записать admin_action")


async def _load_user(user_id: int) -> User | None:
    async with get_session() as session:
        return (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()


# ------------------------------------------------------------------ auth

@router.get("/login")
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", {"section": "login"})


@router.post("/login")
async def login_submit(request: Request):
    s = get_settings()
    if not s.admin_password:
        return _redirect("/login", "Вход отключён: ADMIN_PASSWORD не задан в .env", "err")
    ip = request.client.host if request.client else "-"
    if not login_limiter.allow(f"login:{ip}"):
        return _redirect("/login", "Слишком много попыток входа — подождите минуту", "err")

    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    if not check_login(username, password):
        await _log_admin("login_failed", target=ip)
        return _render(
            request, "login.html", {"section": "login", "error": "Неверный логин или пароль"}, status_code=401
        )
    request.session["adm"] = True
    request.session["user"] = s.admin_user
    await _log_admin("login", target=ip)
    return _redirect("/", "Добро пожаловать!")


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return _redirect("/login", "Вы вышли из панели")


# ------------------------------------------------------------------ dashboard

@router.get("/")
async def dashboard(request: Request):
    r = _guard(request)
    if r:
        return r
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active = (
            await session.scalar(
                select(func.count(User.id)).where(
                    User.status == "ACTIVE", User.expire_at > now
                )
            )
            or 0
        )
        expired = (
            await session.scalar(
                select(func.count(User.id)).where(
                    or_(
                        User.status == "EXPIRED",
                        and_(User.expire_at.is_not(None), User.expire_at <= now),
                    )
                )
            )
            or 0
        )
        blocked = (
            await session.scalar(select(func.count(User.id)).where(User.status == "BLOCKED")) or 0
        )
        orders_total = await session.scalar(select(func.count(Order.id))) or 0
        orders_paid = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "paid")) or 0
        )
        orders_pending = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "pending")) or 0
        )
        revenue = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(Order.status == "paid")
            )
            or 0
        )
        sales_today = (
            await session.scalar(
                select(func.count(Order.id)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        revenue_today = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        sales_month = (
            await session.scalar(
                select(func.count(Order.id)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )
        revenue_month = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )
        recent_orders = (
            (
                await session.execute(
                    select(Order).order_by(Order.created_at.desc()).limit(6)
                )
            )
            .scalars()
            .all()
        )

    cards = [
        ("👥", "Пользователей", total_users, ""),
        ("✅", "Активных подписок", active, ""),
        ("⛔️", "Истёкших подписок", expired, ""),
        ("🚫", "Заблокировано", blocked, ""),
        ("🧾", "Заказов всего", orders_total, f"ожидают оплаты: {orders_pending}"),
        ("💰", "Оплачено заказов", orders_paid, f"выручка: {fmt_money(revenue)} ₽"),
        ("📅", "Продаж за сегодня", sales_today, f"на {fmt_money(revenue_today)} ₽"),
        ("🗓", "Продаж за месяц", sales_month, f"на {fmt_money(revenue_month)} ₽"),
    ]
    return _render(
        request,
        "dashboard.html",
        {"section": "dashboard", "cards": cards, "recent_orders": recent_orders},
    )


# ------------------------------------------------------------------ users

@router.get("/users")
async def users_page(request: Request):
    r = _guard(request)
    if r:
        return r
    q = (request.query_params.get("q") or "").strip()
    status = (request.query_params.get("status") or "").strip()

    conds = []
    if q:
        if q.lstrip("-").isdigit():
            conds.append(
                or_(
                    User.telegram_id == int(q),
                    cast(User.telegram_id, SAString).ilike(f"%{q}%"),
                    User.username.ilike(f"%{q}%"),
                    User.remnawave_user_id.ilike(f"%{q}%"),
                )
            )
        else:
            conds.append(User.username.ilike(f"%{q}%"))
    if status in USER_STATUSES:
        conds.append(User.status == status)

    async with get_session() as session:
        total = await session.scalar(select(func.count(User.id)).where(*conds)) or 0
        pg = _paginate(request, int(total))
        rows = (
            (
                await session.execute(
                    select(User)
                    .where(*conds)
                    .order_by(User.id.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "users.html",
        {
            "section": "users",
            "rows": rows,
            "q": q,
            "status": status,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
            "back": _back(request),
        },
    )


@router.post("/users/{user_id}/extend")
async def user_extend(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    form = await request.form()
    try:
        days = int(str(form.get("days", "30")))
        if not 1 <= days <= 3650:
            raise ValueError
    except ValueError:
        return _redirect(back, "Некорректное количество дней", "err")
    try:
        await orders.provision_user(user.telegram_id, days)
    except RemnaError as exc:
        await orders.log_service_error("remnawave", f"Продление из админки: {exc}")
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    await _log_admin("user_extend", f"user:{user.telegram_id}", f"days={days}")
    fresh = await orders.get_local_user(user.telegram_id)
    if fresh is not None and notifications.has_bot():
        await notifications.notify_key(fresh)
    return _redirect(back, f"Подписка продлена на {days} дн., ключ отправлен пользователю")


@router.post("/users/{user_id}/disable")
async def user_disable(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    try:
        if user.remnawave_user_id:
            await get_remna().disable_user(user.remnawave_user_id)
    except RemnaError as exc:
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    async with get_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is not None:
            db_user.status = "BLOCKED"
            await session.commit()
    await _log_admin("user_disable", f"user:{user.telegram_id}")
    return _redirect(back, "Пользователь заблокирован")


@router.post("/users/{user_id}/enable")
async def user_enable(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    try:
        if user.remnawave_user_id:
            await get_remna().enable_user(user.remnawave_user_id)
    except RemnaError as exc:
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    async with get_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is not None:
            db_user.status = "ACTIVE" if (
                db_user.expire_at is None or db_user.expire_at > utcnow()
            ) else "EXPIRED"
            await session.commit()
    await _log_admin("user_enable", f"user:{user.telegram_id}")
    return _redirect(back, "Пользователь разблокирован")


@router.post("/users/{user_id}/send_key")
async def user_send_key(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None or not user.remnawave_user_id:
        return _redirect(back, "У пользователя нет подписки Remnawave", "err")
    if not notifications.has_bot():
        return _redirect(back, "Бот недоступен (не задан BOT_TOKEN)", "err")
    await notifications.notify_key(user)
    await _log_admin("user_send_key", f"user:{user.telegram_id}")
    return _redirect(back, "Ключ отправлен пользователю")


@router.post("/users/create")
async def user_create(request: Request):
    """Создание подписки из админки: произвольный Telegram ID + срок.

    * пользователя нет локально и в панели -> создаётся (username tg_<id>);
    * пользователь уже есть -> подписка продлевается на указанные дни;
    * опционально ключ отправляется пользователю в Telegram.
    """
    r = _guard(request)
    if r:
        return r
    back = "/users"
    form = await request.form()
    notify = bool(form.get("notify"))

    try:
        days = int(str(form.get("days", "30")))
    except ValueError:
        return _redirect(back, "Некорректное количество дней", "err")
    raw_tg = str(form.get("telegram_id", "")).strip()
    if not valid_telegram_id(raw_tg) or not 1 <= days <= 3650:
        return _redirect(back, "Некорректный Telegram ID или количество дней", "err")
    telegram_id = int(raw_tg)

    if await orders.get_local_user(telegram_id) is None:
        async with get_session() as session:
            session.add(User(telegram_id=telegram_id, status="ACTIVE"))
            await session.commit()

    try:
        await orders.provision_user(telegram_id, days)
    except RemnaError as exc:
        await orders.log_service_error("remnawave", f"Создание подписки из админки: {exc}")
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    except ValueError as exc:
        return _redirect(back, str(exc), "err")

    await _log_admin("user_create", f"user:{telegram_id}", f"days={days} notify={notify}")

    msg = f"Подписка создана/продлена на {days} дн."
    if notify:
        fresh = await orders.get_local_user(telegram_id)
        if fresh is not None and notifications.has_bot():
            await notifications.notify_key(fresh)
            msg += ", ключ отправлен пользователю"
        else:
            msg += " (бот недоступен — ключ не отправлен)"
    return _redirect(back, msg)


# ------------------------------------------------------------------ orders

@router.get("/orders")
async def orders_page(request: Request):
    r = _guard(request)
    if r:
        return r
    q = (request.query_params.get("q") or "").strip()
    status = (request.query_params.get("status") or "").strip()

    conds = []
    if q:
        like = f"%{q}%"
        conds.append(
            or_(
                Order.order_id.ilike(like),
                Order.label.ilike(like),
                Order.operation_id.ilike(like),
                cast(Order.telegram_id, SAString).ilike(like),
            )
        )
    if status in ORDER_STATUSES:
        conds.append(Order.status == status)

    async with get_session() as session:
        total = await session.scalar(select(func.count(Order.id)).where(*conds)) or 0
        pg = _paginate(request, int(total))
        rows = (
            (
                await session.execute(
                    select(Order)
                    .where(*conds)
                    .order_by(Order.created_at.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "orders.html",
        {
            "section": "orders",
            "rows": rows,
            "q": q,
            "status": status,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
            "back": _back(request),
        },
    )


@router.post("/orders/{order_id}/reissue")
async def order_reissue(request: Request, order_id: str):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    async with get_session() as session:
        order = (
            await session.execute(select(Order).where(Order.order_id == order_id))
        ).scalar_one_or_none()
    if order is None:
        return _redirect(back, "Заказ не найден", "err")
    if order.status != "paid":
        return _redirect(back, "Заказ ещё не оплачен — переотправка не требуется", "err")
    if not notifications.has_bot():
        return _redirect(back, "Бот недоступен (не задан BOT_TOKEN)", "err")
    result = await orders.ensure_provisioned_and_notify(order)
    await _log_admin("order_reissue", f"order:{order.order_id}", result)
    msg = {
        "key_sent": "Подписка уже была выдана — ключ повторно отправлен пользователю",
        "provisioned": "Подписка выдана заново и отправлена пользователю",
    }.get(result, "Готово")
    return _redirect(back, msg)


# ------------------------------------------------------------------ tariffs

@router.get("/tariffs")
async def tariffs_page(request: Request):
    r = _guard(request)
    if r:
        return r
    async with get_session() as session:
        rows = (
            (await session.execute(select(Tariff).order_by(Tariff.sort, Tariff.days)))
            .scalars()
            .all()
        )
    return _render(request, "tariffs.html", {"section": "tariffs", "rows": rows, "back": _back(request)})


@router.post("/tariffs/{tariff_id}/save")
async def tariff_save(request: Request, tariff_id: int):
    r = _guard(request)
    if r:
        return r
    back = "/tariffs"
    form = await request.form()
    async with get_session() as session:
        tariff = await session.get(Tariff, tariff_id)
        if tariff is None:
            return _redirect(back, "Тариф не найден", "err")
        try:
            price = Decimal(str(form.get("price", "")).replace(",", ".")).quantize(Decimal("0.01"))
            if price < 0 or price > Decimal("1000000"):
                raise ValueError
        except (InvalidOperation, ValueError):
            return _redirect(back, "Некорректная цена", "err")
        tariff.price = price
        tariff.enabled = bool(form.get("enabled"))
        await session.commit()
        await _log_admin("tariff_update", f"tariff:{tariff.code}", f"price={price} enabled={tariff.enabled}")
    return _redirect(back, "Тариф сохранён")


# ------------------------------------------------------------------ broadcast

@router.get("/broadcast")
async def broadcast_page(request: Request):
    r = _guard(request)
    if r:
        return r
    s = get_settings()
    return _render(
        request,
        "broadcast.html",
        {
            "section": "broadcast",
            "draft": request.session.get("bc_text", ""),
            "rate": request.session.get("bc_rate") or s.broadcast_default_rate,
            "targets": request.session.get("bc_targets", "all"),
            "bc": broadcast_manager.status(),
            "running": broadcast_manager.is_running(),
        },
    )


@router.post("/broadcast/preview")
async def broadcast_preview(request: Request):
    r = _guard(request)
    if r:
        return r
    s = get_settings()
    form = await request.form()
    text = str(form.get("text", "")).strip()
    targets = str(form.get("targets", "all"))
    try:
        rate = float(str(form.get("rate", s.broadcast_default_rate)))
    except ValueError:
        rate = s.broadcast_default_rate
    rate = min(max(rate, 1.0), 30.0)

    if not text:
        return _redirect("/broadcast", "Текст рассылки пуст", "err")

    request.session["bc_text"] = text
    request.session["bc_rate"] = rate
    request.session["bc_targets"] = targets if targets in ("all", "active") else "all"

    async with get_session() as session:
        stmt = select(func.count(User.id))
        if targets == "active":
            stmt = stmt.where(User.status == "ACTIVE", User.expire_at > utcnow())
        recipients = await session.scalar(stmt) or 0

    eta_min = recipients / rate / 60 if rate else 0
    return _render(
        request,
        "broadcast.html",
        {
            "section": "broadcast",
            "draft": text,
            "rate": rate,
            "targets": targets,
            "bc": broadcast_manager.status(),
            "running": broadcast_manager.is_running(),
            "preview": {
                "text": text,
                "recipients": int(recipients),
                "eta_min": round(eta_min, 1),
            },
        },
    )


@router.post("/broadcast/send")
async def broadcast_send(request: Request):
    r = _guard(request)
    if r:
        return r
    text = request.session.get("bc_text", "")
    if not text:
        return _redirect("/broadcast", "Нет черновика рассылки — создайте его заново", "err")
    rate = float(request.session.get("bc_rate") or get_settings().broadcast_default_rate)
    targets = request.session.get("bc_targets", "all")

    async with get_session() as session:
        stmt = select(User.telegram_id).order_by(User.id.desc())
        if targets == "active":
            stmt = stmt.where(User.status == "ACTIVE", User.expire_at > utcnow())
        chat_ids = [int(tid) for tid in (await session.execute(stmt)).scalars() if valid_telegram_id(tid)]

    if not notifications.has_bot():
        return _redirect("/broadcast", "Бот недоступен (не задан BOT_TOKEN)", "err")
    ok, msg = broadcast_manager.start(text, rate, chat_ids)
    await _log_admin("broadcast", f"targets:{targets}", f"recipients={len(chat_ids)} rate={rate} started={ok}")
    return _redirect("/broadcast", msg, "ok" if ok else "err")


@router.get("/broadcast/status")
async def broadcast_status(request: Request):
    r = _guard(request)
    if r:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(broadcast_manager.status())


# ------------------------------------------------------------------ logs

@router.get("/logs")
async def logs_page(request: Request):
    r = _guard(request)
    if r:
        return r
    tab = request.query_params.get("tab", "actions")
    if tab not in ("actions", "payments", "errors"):
        tab = "actions"
    kind = (request.query_params.get("kind") or "").strip()

    async with get_session() as session:
        if tab == "actions":
            model = AdminAction
            conds = []
        elif tab == "payments":
            model = PaymentEvent
            conds = []
        else:
            model = ServiceLog
            conds = [ServiceLog.kind == kind] if kind in LOG_KINDS else []

        total = await session.scalar(select(func.count(model.id)).where(*conds)) or 0
        pg = _paginate(request, int(total), per=30)
        rows = (
            (
                await session.execute(
                    select(model)
                    .where(*conds)
                    .order_by(model.id.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "logs.html",
        {
            "section": "logs",
            "tab": tab,
            "kind": kind,
            "rows": rows,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
        },
    )


# ------------------------------------------------------------------ webhook

@router.post(get_settings().yoomoney_webhook_path)
async def yoomoney_notification(request: Request):
    s = get_settings()
    # лимит размера тела (тело кэшируется — дальше form() прочитает его из кэша)
    body = await request.body()
    if len(body) > s.webhook_max_body_bytes:
        return PlainTextResponse("too large", status_code=413)
    try:
        form = await request.form()
        params = {str(k): str(v) for k, v in form.multi_items()}
    except Exception:  # noqa: BLE001
        return PlainTextResponse("bad request", status_code=400)
    ip = request.client.host if request.client else "-"
    try:
        status, reason = await process_notification(params, ip)
    except Exception:  # noqa: BLE001
        log.exception("Исключение при обработке уведомления YooMoney")
        await orders.log_service_error("yoomoney", "Внутренняя ошибка обработки вебхука")
        return PlainTextResponse("error", status_code=500)
    return PlainTextResponse(reason, status_code=status)
RW_EOF_10
cat > vpn-bot/app/admin/static/app.js <<'RW_EOF_11'
// VPN Admin — фронтовая логика: подтверждения, тосты, прогресс рассылки
(function () {
  "use strict";

  // Подтверждение опасных действий
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm") || "Вы уверены?")) {
        e.preventDefault();
      }
    });
  });

  // Тост-уведомления
  var toast = document.getElementById("toast");
  if (toast) {
    setTimeout(function () {
      toast.style.transition = "opacity .6s";
      toast.style.opacity = "0";
      setTimeout(function () { toast.remove(); }, 700);
    }, 5000);
  }

  // Мобильное меню
  var burger = document.getElementById("burger");
  if (burger) {
    burger.addEventListener("click", function () {
      document.body.classList.toggle("nav-open");
    });
  }

  // Прогресс рассылки (опрос статуса)
  var panel = document.getElementById("bc-panel");
  if (panel) {
    var bar = document.getElementById("bc-progress");
    var text = document.getElementById("bc-text");
    var logEl = document.getElementById("bc-log");
    var stop = false;

    var poll = function () {
      if (stop) return;
      fetch("/broadcast/status", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (st) {
          var active = panel.getAttribute("data-active") === "1";
          var changed = false;
          if (active && !st.running && st.total > 0) {
            changed = true; // рассылка завершилась — обновляем страницу
          }
          if (bar) bar.style.width = (st.percent || 0) + "%";
          if (text) {
            text.textContent = st.total
              ? st.sent + "/" + st.total + " отправлено, ошибок: " + st.failed
              : "Рассылок ещё не было.";
          }
          if (logEl && st.log && st.log.length) logEl.textContent = st.log.join("\n");
          if (changed) { stop = true; setTimeout(function () { location.reload(); }, 1500); return; }
          if (st.running) setTimeout(poll, 2000);
        })
        .catch(function () { setTimeout(poll, 4000); });
    };

    if (panel.getAttribute("data-active") === "1") poll();
  }
})();
RW_EOF_11
cat > vpn-bot/app/admin/static/style.css <<'RW_EOF_12'
/* VPN Admin — тёмная тема, адаптив */
:root {
  --bg: #0d131b;
  --panel: #151d28;
  --panel-2: #1b2533;
  --border: #263344;
  --text: #e7edf4;
  --muted: #8b98a7;
  --accent: #4f8cff;
  --accent-2: #3b6fd4;
  --ok: #2fbf71;
  --err: #ff5c5c;
  --warn: #f5a623;
  --radius: 12px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}

/* ---------- sidebar ---------- */
.sidebar {
  position: fixed; inset: 0 auto 0 0; width: 230px;
  background: var(--panel); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 18px 14px; z-index: 50;
}
.brand { font-weight: 700; font-size: 17px; margin-bottom: 20px; letter-spacing: .3px; }
.brand.big { font-size: 22px; text-align: center; margin-bottom: 18px; }
.sidebar nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.sidebar nav a {
  color: var(--muted); text-decoration: none; padding: 10px 12px;
  border-radius: 8px; transition: background .15s, color .15s;
}
.sidebar nav a:hover { background: var(--panel-2); color: var(--text); }
.sidebar nav a.active { background: var(--accent); color: #fff; }
.logout-form { margin-top: 10px; }

/* ---------- main ---------- */
.main { margin-left: 230px; padding: 0 22px 40px; }
.topbar {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 0 14px; border-bottom: 1px solid var(--border); margin-bottom: 20px;
}
.topbar h1 { font-size: 20px; margin: 0; font-weight: 600; }
.count { color: var(--muted); font-size: 14px; font-weight: 400; }
.burger { display: none; background: none; border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; font-size: 18px; padding: 4px 10px; cursor: pointer; }

/* ---------- cards ---------- */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; margin-bottom: 20px; }
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px;
}
.card-icon { font-size: 22px; }
.card-value { font-size: 28px; font-weight: 700; margin: 6px 0 2px; }
.card-title { color: var(--muted); font-size: 13px; }
.card-note { color: var(--accent); font-size: 12.5px; margin-top: 6px; }

/* ---------- panels ---------- */
.panel {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 18px; margin-bottom: 20px;
}
.panel h2 { font-size: 16px; margin: 0 0 14px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* ---------- tables ---------- */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 12.5px; text-transform: uppercase; letter-spacing: .4px; }
tbody tr:hover { background: var(--panel-2); }
td.wrap, .mono.wrap { white-space: normal; word-break: break-word; }
code { background: var(--panel-2); padding: 2px 6px; border-radius: 6px; font-size: 12.5px; }
.muted { color: var(--muted); }
.mono { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 12.5px; }

/* ---------- badges ---------- */
.badge { display: inline-block; padding: 3px 9px; border-radius: 20px; font-size: 12px; font-weight: 600;
  background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
.b-active, .b-paid { background: rgba(47,191,113,.14); color: var(--ok); border-color: rgba(47,191,113,.4); }
.b-expired, .b-error { background: rgba(255,92,92,.14); color: var(--err); border-color: rgba(255,92,92,.4); }
.b-blocked, .b-pending, .b-warn { background: rgba(245,166,35,.14); color: var(--warn); border-color: rgba(245,166,35,.4); }
.b-canceled { opacity: .7; }

/* ---------- forms ---------- */
input[type=text], input[type=password], input[type=number], select, textarea {
  width: 100%; background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; font: inherit;
}
input:focus, select:focus, textarea:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
label { display: block; margin-bottom: 13px; color: var(--muted); font-size: 13px; }
label input, label select, label textarea { margin-top: 6px; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.filters input, .filters select { width: auto; min-width: 180px; flex: 1; }
.inline-form { display: inline-flex; gap: 6px; align-items: center; margin: 2px 4px 2px 0; }
.inline-form select { width: auto; padding: 4px 6px; font-size: 13px; }
.price-input { width: 110px; padding: 5px 8px !important; }
textarea { resize: vertical; }

/* ---------- buttons ---------- */
.btn {
  display: inline-block; background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 16px;
  font: inherit; font-size: 14px; cursor: pointer; text-decoration: none; transition: filter .15s;
}
.btn:hover { filter: brightness(1.18); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.danger { background: rgba(255,92,92,.15); border-color: rgba(255,92,92,.5); color: var(--err); }
.btn.ok { background: rgba(47,191,113,.15); border-color: rgba(47,191,113,.5); color: var(--ok); }
.btn.ghost { background: transparent; }
.btn.sm { padding: 5px 10px; font-size: 12.5px; border-radius: 7px; }
.btn.w100 { width: 100%; text-align: center; }

/* ---------- toast / alert ---------- */
.toast {
  position: fixed; top: 18px; right: 18px; z-index: 100; max-width: 420px;
  padding: 12px 18px; border-radius: 10px; font-size: 14px;
  background: rgba(47,191,113,.15); border: 1px solid rgba(47,191,113,.5); color: var(--ok);
  box-shadow: 0 8px 30px rgba(0,0,0,.4);
}
.toast.err { background: rgba(255,92,92,.15); border-color: rgba(255,92,92,.5); color: var(--err); }
.alert { padding: 11px 14px; border-radius: 9px; margin-bottom: 14px; font-size: 14px; }
.alert.err { background: rgba(255,92,92,.12); border: 1px solid rgba(255,92,92,.4); color: var(--err); }
.alert.warn { background: rgba(245,166,35,.12); border: 1px solid rgba(245,166,35,.4); color: var(--warn); }

/* ---------- чекбокс в строке фильтров (создание подписки) ---------- */
.filters label.chk { display: flex; align-items: center; gap: 7px; margin: 0; width: auto;
  flex: 0 0 auto; color: var(--text); font-size: 13.5px; cursor: pointer; }
.filters label.chk input { width: auto; margin: 0; }

/* ---------- pagination ---------- */
.pagination { display: flex; gap: 12px; align-items: center; margin-top: 16px; color: var(--muted); }

/* ---------- tabs ---------- */
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.tabs a { padding: 8px 14px; border-radius: 8px; text-decoration: none; color: var(--muted);
  background: var(--panel-2); border: 1px solid var(--border); font-size: 13.5px; }
.tabs a.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* ---------- broadcast ---------- */
.progress { height: 10px; background: var(--panel-2); border-radius: 20px; overflow: hidden; margin: 8px 0 10px; }
.progress .bar { height: 100%; background: linear-gradient(90deg, var(--accent), #7aa7ff); width: 0; transition: width .6s; }
.log { background: #0a0f16; border: 1px solid var(--border); border-radius: 8px; padding: 12px;
  max-height: 220px; overflow-y: auto; font-size: 12.5px; color: var(--muted); }
.preview-box { background: #0a0f16; border: 1px solid var(--border); border-radius: 10px;
  padding: 14px; white-space: pre-wrap; word-break: break-word; margin-bottom: 12px; }

/* ---------- login ---------- */
.login-body { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card { width: min(380px, 92vw); background: var(--panel); border: 1px solid var(--border);
  border-radius: 16px; padding: 28px; }

/* ---------- mobile ---------- */
@media (max-width: 900px) {
  .sidebar { transform: translateX(-100%); transition: transform .2s ease; width: 250px; }
  body.nav-open .sidebar { transform: translateX(0); box-shadow: 0 0 60px rgba(0,0,0,.6); }
  .main { margin-left: 0; padding: 0 14px 40px; }
  .burger { display: block; }
  .grid-2 { grid-template-columns: 1fr; }
  .filters input, .filters select { min-width: 130px; }
  th, td { padding: 7px 8px; }
}
RW_EOF_12
cat > vpn-bot/app/admin/templates/base.html <<'RW_EOF_13'
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>{% block title %}VPN Admin{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<aside class="sidebar" id="sidebar">
  <div class="brand">🔐 VPN Admin</div>
  <nav>
    <a href="/" class="{{ 'active' if section == 'dashboard' }}">📊 Дашборд</a>
    <a href="/users" class="{{ 'active' if section == 'users' }}">👥 Пользователи</a>
    <a href="/orders" class="{{ 'active' if section == 'orders' }}">🧾 Заказы</a>
    <a href="/tariffs" class="{{ 'active' if section == 'tariffs' }}">💎 Тарифы</a>
    <a href="/broadcast" class="{{ 'active' if section == 'broadcast' }}">📣 Рассылка</a>
    <a href="/logs" class="{{ 'active' if section == 'logs' }}">📜 Логи</a>
  </nav>
  <form method="post" action="/logout" class="logout-form">
    <button type="submit" class="btn ghost w100">⎋ Выйти</button>
  </form>
</aside>

<main class="main">
  <header class="topbar">
    <button class="burger" id="burger" aria-label="Меню">☰</button>
    <h1>{% block h1 %}{% endblock %}</h1>
  </header>

  {% if msg %}<div class="toast {{ 'err' if k == 'err' else 'ok' }}" id="toast">{{ msg }}</div>{% endif %}

  {% block content %}{% endblock %}
</main>
<script src="/static/app.js"></script>
</body>
</html>
RW_EOF_13
cat > vpn-bot/app/admin/templates/broadcast.html <<'RW_EOF_14'
{% extends "base.html" %}
{% block title %}Рассылка — VPN Admin{% endblock %}
{% block h1 %}📣 Рассылка{% endblock %}
{% block content %}
<div class="grid-2">
  <div class="panel">
    <h2>Новая рассылка</h2>
    {% if running %}
    <div class="alert warn">Идёт рассылка — создание новой недоступно до завершения.</div>
    {% endif %}
    <form method="post" action="/broadcast/preview">
      <label>Текст сообщения (обычный текст, без HTML)
        <textarea name="text" rows="7" required>{{ draft }}</textarea>
      </label>
      <label>Ограничение скорости: {{ rate }} сообщ./сек
        <input type="range" name="rate" min="1" max="30" step="1" value="{{ rate }}" oninput="this.previousElementSibling.firstChild.textContent='Ограничение скорости: '+this.value+' сообщ./сек '">
      </label>
      <label>Получатели
        <select name="targets">
          <option value="all" {{ 'selected' if targets == 'all' }}>Все пользователи</option>
          <option value="active" {{ 'selected' if targets == 'active' }}>Только активные подписки</option>
        </select>
      </label>
      <button class="btn primary">👁 Предпросмотр</button>
    </form>
  </div>

  {% if preview is defined and preview %}
  <div class="panel">
    <h2>Предпросмотр</h2>
    <div class="preview-box">{{ preview.text }}</div>
    <p>Получателей: <b>{{ preview.recipients }}</b><br>
       Оценочное время: ~{{ preview.eta_min }} мин</p>
    <form method="post" action="/broadcast/send" data-confirm="Отправить рассылку {{ preview.recipients }} пользователям? Отменить будет нельзя!">
      <button class="btn danger">🚀 Отправить</button>
      <a class="btn ghost" href="/broadcast">Отмена</a>
    </form>
  </div>
  {% endif %}
</div>

<div class="panel" id="bc-panel" data-active="{{ '1' if running else '0' }}">
  <h2>Статус рассылки</h2>
  <div class="progress"><div class="bar" id="bc-progress" style="width: {{ bc.percent }}%"></div></div>
  <p id="bc-text">{{ bc.sent }}/{{ bc.total }} отправлено, ошибок: {{ bc.failed }}{% if not running and bc.total == 0 %} — рассылок ещё не было{% endif %}</p>
  <pre class="log" id="bc-log">{% for line in bc.log %}{{ line }}
{% endfor %}</pre>
</div>
{% endblock %}
RW_EOF_14
cat > vpn-bot/app/admin/templates/dashboard.html <<'RW_EOF_15'
{% extends "base.html" %}
{% block title %}Дашборд — VPN Admin{% endblock %}
{% block h1 %}📊 Дашборд{% endblock %}
{% block content %}
<div class="cards">
  {% for icon, title, value, note in cards %}
  <div class="card">
    <div class="card-icon">{{ icon }}</div>
    <div class="card-value">{{ value }}</div>
    <div class="card-title">{{ title }}</div>
    {% if note %}<div class="card-note">{{ note }}</div>{% endif %}
  </div>
  {% endfor %}
</div>

<div class="panel">
  <h2>Последние заказы</h2>
  {% if recent_orders %}
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Заказ</th><th>Telegram ID</th><th>Тариф</th><th>Сумма</th><th>Статус</th><th>Создан</th></tr>
      </thead>
      <tbody>
        {% for o in recent_orders %}
        <tr>
          <td><code>{{ o.order_id[:14] }}…</code></td>
          <td>{{ o.telegram_id }}</td>
          <td>{{ o.tariff_days }} дн.</td>
          <td>{{ o.expected_price | money }} ₽</td>
          <td><span class="badge b-{{ o.status }}">{{ o.status }}</span></td>
          <td>{{ o.created_at | dt }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="muted">Заказов пока нет.</p>
  {% endif %}
</div>
{% endblock %}
RW_EOF_15
cat > vpn-bot/app/admin/templates/login.html <<'RW_EOF_16'
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>Вход — VPN Admin</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body class="login-body">
<div class="login-card">
  <div class="brand big">🔐 VPN Admin</div>
  {% if msg %}<div class="toast {{ 'err' if k == 'err' else 'ok' }}" id="toast">{{ msg }}</div>{% endif %}
  {% if error %}<div class="alert err">{{ error }}</div>{% endif %}
  {% if not error or error %}
  <form method="post" action="/login" autocomplete="off">
    <label>Логин
      <input type="text" name="username" required autofocus>
    </label>
    <label>Пароль
      <input type="password" name="password" required>
    </label>
    <button type="submit" class="btn primary w100">Войти</button>
  </form>
  {% endif %}
</div>
<script src="/static/app.js"></script>
</body>
</html>
RW_EOF_16
cat > vpn-bot/app/admin/templates/logs.html <<'RW_EOF_17'
{% extends "base.html" %}
{% block title %}Логи — VPN Admin{% endblock %}
{% block h1 %}📜 Логи <span class="count">{{ total }}</span>{% endblock %}
{% block content %}
<div class="panel">
  <div class="tabs">
    <a href="/logs?tab=actions" class="{{ 'active' if tab == 'actions' }}">Действия админов</a>
    <a href="/logs?tab=payments" class="{{ 'active' if tab == 'payments' }}">Платёжные события</a>
    <a href="/logs?tab=errors" class="{{ 'active' if tab == 'errors' }}">Ошибки сервисов</a>
  </div>

  {% if tab == 'errors' %}
  <form method="get" action="/logs" class="filters">
    <input type="hidden" name="tab" value="errors">
    <select name="kind">
      <option value="">Все типы</option>
      {% for kd in ('yoomoney', 'remnawave', 'webhook', 'broadcast', 'bot') %}
      <option value="{{ kd }}" {{ 'selected' if kind == kd }}>{{ kd }}</option>
      {% endfor %}
    </select>
    <button class="btn primary">Фильтр</button>
  </form>
  {% endif %}

  <div class="table-wrap">
    <table>
      {% if tab == 'actions' %}
      <thead><tr><th>Время</th><th>Admin ID</th><th>Действие</th><th>Цель</th><th>Детали</th></tr></thead>
      <tbody>
        {% for a in rows %}
        <tr>
          <td>{{ a.created_at | dt }}</td>
          <td><code>{{ a.admin_id }}</code></td>
          <td><span class="badge">{{ a.action }}</span></td>
          <td>{{ a.target }}</td>
          <td class="mono">{{ a.details or '—' }}</td>
        </tr>
        {% else %}<tr><td colspan="5" class="muted">Пусто</td></tr>{% endfor %}
      </tbody>
      {% elif tab == 'payments' %}
      <thead><tr><th>Получено</th><th>operation_id</th><th>Label</th><th>Hash</th><th>Обработано</th></tr></thead>
      <tbody>
        {% for p in rows %}
        <tr>
          <td>{{ p.received_at | dt }}</td>
          <td class="mono">{{ p.operation_id }}</td>
          <td><code>{{ p.label }}</code></td>
          <td class="mono">{{ (p.raw_hash or '')[:16] }}{% if p.raw_hash and p.raw_hash | length > 16 %}…{% endif %}</td>
          <td>{{ p.processed_at | dt if p.processed_at else '⏳ нет' }}</td>
        </tr>
        {% else %}<tr><td colspan="5" class="muted">Пусто</td></tr>{% endfor %}
      </tbody>
      {% else %}
      <thead><tr><th>Время</th><th>Тип</th><th>Уровень</th><th>Сообщение</th></tr></thead>
      <tbody>
        {% for e in rows %}
        <tr>
          <td>{{ e.created_at | dt }}</td>
          <td><span class="badge">{{ e.kind }}</span></td>
          <td><span class="badge {{ 'b-expired' if e.level == 'error' else 'b-pending' }}">{{ e.level }}</span></td>
          <td class="mono wrap">{{ e.message }}</td>
        </tr>
        {% else %}<tr><td colspan="4" class="muted">Пусто</td></tr>{% endfor %}
      </tbody>
      {% endif %}
    </table>
  </div>

  {% if pages > 1 %}
  <div class="pagination">
    {% if page > 1 %}<a class="btn sm ghost" href="?{{ base_qs }}tab={{ tab }}&kind={{ kind }}&page={{ page - 1 }}">‹ Назад</a>{% endif %}
    <span>Стр. {{ page }} из {{ pages }}</span>
    {% if page < pages %}<a class="btn sm ghost" href="?{{ base_qs }}tab={{ tab }}&kind={{ kind }}&page={{ page + 1 }}">Вперёд ›</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
RW_EOF_17
cat > vpn-bot/app/admin/templates/orders.html <<'RW_EOF_18'
{% extends "base.html" %}
{% block title %}Заказы — VPN Admin{% endblock %}
{% block h1 %}🧾 Заказы <span class="count">{{ total }}</span>{% endblock %}
{% block content %}
<div class="panel">
  <form method="get" action="/orders" class="filters">
    <input type="text" name="q" value="{{ q }}" placeholder="order_id / label / operation_id / Telegram ID">
    <select name="status">
      <option value="">Все статусы</option>
      {% for st in ('pending', 'paid', 'canceled') %}
      <option value="{{ st }}" {{ 'selected' if status == st }}>{{ st }}</option>
      {% endfor %}
    </select>
    <button class="btn primary">🔍 Искать</button>
    {% if q or status %}<a class="btn ghost" href="/orders">Сброс</a>{% endif %}
  </form>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Заказ</th><th>Label</th><th>Telegram ID</th><th>Тариф</th><th>Ожид./получ.</th><th>Статус</th><th>operation_id</th><th>Создан</th><th>Оплачен</th><th></th></tr>
      </thead>
      <tbody>
        {% for o in rows %}
        <tr>
          <td><code>{{ o.order_id[:14] }}…</code></td>
          <td><code>{{ o.label }}</code></td>
          <td><code>{{ o.telegram_id }}</code></td>
          <td>{{ o.tariff_days }} дн.</td>
          <td>{{ o.expected_price | money }}{% if o.received_amount %} / <b>{{ o.received_amount | money }}</b>{% endif %} ₽</td>
          <td><span class="badge b-{{ o.status }}">{{ o.status }}</span></td>
          <td class="mono">{{ o.operation_id or '—' }}</td>
          <td>{{ o.created_at | dt }}</td>
          <td>{{ o.paid_at | dt if o.paid_at else '—' }}</td>
          <td>
            {% if o.status == 'paid' %}
            <form method="post" action="/orders/{{ o.order_id }}/reissue" class="inline-form" data-confirm="Переотправить ключ / довыдать подписку по заказу {{ o.order_id }}?">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm">🔁 Переотправить</button>
            </form>
            {% endif %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="10" class="muted">Ничего не найдено</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if pages > 1 %}
  <div class="pagination">
    {% if page > 1 %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page - 1 }}">‹ Назад</a>{% endif %}
    <span>Стр. {{ page }} из {{ pages }}</span>
    {% if page < pages %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page + 1 }}">Вперёд ›</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
RW_EOF_18
cat > vpn-bot/app/admin/templates/tariffs.html <<'RW_EOF_19'
{% extends "base.html" %}
{% block title %}Тарифы — VPN Admin{% endblock %}
{% block h1 %}💎 Тарифы{% endblock %}
{% block content %}
<div class="panel">
  <p class="muted">Цены применяются мгновенно и для новых заказов в боте. Снятие галочки скрывает тариф в меню.</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Код</th><th>Название</th><th>Дней</th><th>Цена, ₽</th><th>Включён</th><th></th></tr>
      </thead>
      <tbody>
        {% for t in rows %}
        <tr>
          <td><code>{{ t.code }}</code></td>
          <td>{{ t.title }}</td>
          <td>{{ t.days }}</td>
          <td>
            <form method="post" action="/tariffs/{{ t.id }}/save" class="inline-form tariff-form" data-confirm="Сохранить изменения тарифа {{ t.title }}?">
              <input type="number" name="price" value="{{ t.price }}" min="0" step="0.01" class="price-input" required>
          </td>
          <td>
              <label class="switch">
                <input type="checkbox" name="enabled" value="1" {{ 'checked' if t.enabled }}>
                <span></span>
              </label>
          </td>
          <td>
              <button class="btn sm primary">💾 Сохранить</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
RW_EOF_19
cat > vpn-bot/app/admin/templates/users.html <<'RW_EOF_20'
{% extends "base.html" %}
{% block title %}Пользователи — VPN Admin{% endblock %}
{% block h1 %}👥 Пользователи <span class="count">{{ total }}</span>{% endblock %}
{% block content %}
<div class="panel">
  <h2>➕ Создать подписку</h2>
  <p class="muted">Создаёт пользователя в Remnawave (если его ещё нет) и выдаёт дни. Если подписка уже есть — продлевает её.</p>
  <form method="post" action="/users/create" class="filters" data-confirm="Создать/продлить подписку в Remnawave?">
    <input type="text" name="telegram_id" placeholder="Telegram ID" required>
    <select name="days">
      <option value="7">7 дн.</option>
      <option value="30" selected>30 дн.</option>
      <option value="90">90 дн.</option>
      <option value="180">180 дн.</option>
      <option value="365">365 дн.</option>
    </select>
    <label class="chk"><input type="checkbox" name="notify" value="1" checked> отправить ключ в бот</label>
    <button class="btn primary">➕ Создать</button>
  </form>
</div>

<div class="panel">
  <form method="get" action="/users" class="filters">
    <input type="text" name="q" value="{{ q }}" placeholder="Telegram ID / username / Remna ID">
    <select name="status">
      <option value="">Все статусы</option>
      {% for st in ('ACTIVE', 'BLOCKED', 'EXPIRED') %}
      <option value="{{ st }}" {{ 'selected' if status == st }}>{{ st }}</option>
      {% endfor %}
    </select>
    <button class="btn primary">🔍 Искать</button>
    {% if q or status %}<a class="btn ghost" href="/users">Сброс</a>{% endif %}
  </form>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>ID</th><th>Telegram ID</th><th>Remna username</th><th>Статус</th><th>Окончание</th><th>Действия</th></tr>
      </thead>
      <tbody>
        {% for u in rows %}
        <tr>
          <td>{{ u.id }}</td>
          <td><code>{{ u.telegram_id }}</code></td>
          <td>{{ u.username or '—' }}</td>
          <td><span class="badge b-{{ u.status | lower }}">{{ u.status }}</span></td>
          <td>{{ u.expire_at | dt }}</td>
          <td class="actions">
            <form method="post" action="/users/{{ u.id }}/extend" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <select name="days">
                <option value="7">7 дн.</option>
                <option value="30" selected>30 дн.</option>
                <option value="90">90 дн.</option>
                <option value="180">180 дн.</option>
                <option value="365">365 дн.</option>
              </select>
              <button class="btn sm primary">＋ Продлить</button>
            </form>
            {% if u.status == 'BLOCKED' %}
            <form method="post" action="/users/{{ u.id }}/enable" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm ok">✓ Разблокировать</button>
            </form>
            {% else %}
            <form method="post" action="/users/{{ u.id }}/disable" class="inline-form" data-confirm="Заблокировать пользователя {{ u.telegram_id }} в боте и в Remnawave?">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm danger">🚫 Блок</button>
            </form>
            {% endif %}
            <form method="post" action="/users/{{ u.id }}/send_key" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm">🔑 Ключ</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="6" class="muted">Ничего не найдено</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if pages > 1 %}
  <div class="pagination">
    {% if page > 1 %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page - 1 }}">‹ Назад</a>{% endif %}
    <span>Стр. {{ page }} из {{ pages }}</span>
    {% if page < pages %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page + 1 }}">Вперёд ›</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
RW_EOF_20
cat > vpn-bot/app/config.py <<'RW_EOF_21'
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
RW_EOF_21
cat > vpn-bot/app/database.py <<'RW_EOF_22'
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
RW_EOF_22
cat > vpn-bot/app/main.py <<'RW_EOF_23'
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
RW_EOF_23
cat > vpn-bot/app/models.py <<'RW_EOF_24'
"""SQLAlchemy-модели локальной базы (SQLite или PostgreSQL)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    """Локальный пользователь Telegram + ссылка на пользователя Remnawave."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    remnawave_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    subscription_url: Mapped[str | None] = mapped_column(Text)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime)
    # ACTIVE | BLOCKED | EXPIRED
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), onupdate=utcnow, nullable=False
    )


class Order(Base):
    """Заказ на покупку/продление подписки."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tariff_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    tariff_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    operation_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # pending | paid | canceled
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class PaymentEvent(Base):
    """Каждое входящее платёжное уведомление (для идемпотентности и аудита)."""

    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    raw_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AdminAction(Base):
    """Журнал действий администраторов."""

    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )


class ServiceLog(Base):
    """Ошибки сервисов: yoomoney | remnawave | webhook | broadcast | bot."""

    __tablename__ = "service_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )


class Tariff(Base):
    """Тарифы. Стартовые значения берутся из .env, далее редактируются в админке."""

    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), onupdate=utcnow, nullable=False
    )
RW_EOF_24
cat > vpn-bot/app/services/__init__.py <<'RW_EOF_25'
RW_EOF_25
cat > vpn-bot/app/services/broadcasts.py <<'RW_EOF_26'
"""Менеджер массовой рассылки (для админ-панели) с ограничением скорости."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from app.services import notifications


@dataclass
class BroadcastJob:
    id: str
    text: str
    rate: float
    total: int
    sent: int = 0
    failed: int = 0
    running: bool = True
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=30))


class BroadcastManager:
    """Одновременная рассылка — только одна. Остальные запуски отклоняются."""

    def __init__(self) -> None:
        self._job: BroadcastJob | None = None
        self._task: asyncio.Task | None = None

    def start(self, text: str, rate: float, chat_ids: list[int]) -> tuple[bool, str]:
        if self._job is not None and self._job.running:
            return False, "Рассылка уже запущена — дождитесь завершения."
        if not chat_ids:
            return False, "Нет получателей."
        job = BroadcastJob(id=time.strftime("%Y%m%d-%H%M%S"), text=text, rate=rate, total=len(chat_ids))
        job.log.append(f"Старт: получателей {len(chat_ids)}, скорость {rate:g} msg/s")
        self._job = job
        self._task = asyncio.create_task(self._run(job, chat_ids))
        return True, "Рассылка запущена."

    async def _run(self, job: BroadcastJob, chat_ids: list[int]) -> None:
        def progress(sent: int, failed: int, total: int) -> None:
            job.sent, job.failed, job.total = sent, failed, total
            if (sent + failed) % 25 == 0:
                job.log.append(f"Прогресс: {sent + failed}/{total} (ошибок: {failed})")

        try:
            sent, failed = await notifications.broadcast(
                job.text, rate_per_sec=job.rate, chat_ids=chat_ids, progress=progress
            )
            job.sent, job.failed = sent, failed
            job.log.append(f"Готово: отправлено {sent}, ошибок {failed}")
        except Exception as exc:  # noqa: BLE001
            job.log.append(f"Аварийное завершение: {type(exc).__name__}: {exc}")
        finally:
            job.running = False
            job.finished_at = time.time()

    def status(self) -> dict:
        job = self._job
        if job is None:
            return {"running": False, "total": 0, "sent": 0, "failed": 0, "percent": 0, "log": []}
        done = job.sent + job.failed
        percent = int(done * 100 / job.total) if job.total else 100
        return {
            "id": job.id,
            "running": job.running,
            "total": job.total,
            "sent": job.sent,
            "failed": job.failed,
            "percent": percent if job.running else 100,
            "log": list(job.log),
        }

    def is_running(self) -> bool:
        return self._job is not None and self._job.running


manager = BroadcastManager()
RW_EOF_26
cat > vpn-bot/app/services/notifications.py <<'RW_EOF_27'
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
RW_EOF_27
cat > vpn-bot/app/services/orders.py <<'RW_EOF_28'
"""Заказы, идемпотентная фиксация оплат и выдача/продление подписок Remnawave."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import get_session
from app.models import Order, PaymentEvent, User
from app.services import notifications
from app.services.remnawave import (
    RemnaError,
    RemnaNotFound,
    get_remna,
)
from app.utils import parse_iso_utc, rand_hex, utcnow, valid_telegram_id

log = logging.getLogger("app.orders")


# --------------------------------------------------------------- генерация ID

def new_order_id() -> str:
    return f"ord_{rand_hex(16)}"


def new_label(telegram_id: int) -> str:
    # Формат: rw_<telegram_id>_<random>, пример: rw_8346538289_a91f3c
    return f"rw_{telegram_id}_{rand_hex(6)}"


# --------------------------------------------------------------- CRUD заказов

async def create_order(telegram_id: int, *, tariff_code: str, tariff_days: int, price: Decimal) -> Order:
    """Создаёт заказ со статусом pending. Label уникален (проверка на коллизию)."""
    for _ in range(5):
        label = new_label(telegram_id)
        async with get_session() as session:
            exists = (
                await session.execute(select(Order.id).where(Order.label == label))
            ).scalar_one_or_none()
            if exists:
                continue
            order = Order(
                order_id=new_order_id(),
                label=label,
                telegram_id=telegram_id,
                tariff_code=tariff_code,
                tariff_days=int(tariff_days),
                expected_price=price,
                status="pending",
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            return order
    raise RuntimeError("Не удалось сгенерировать уникальный label заказа")


async def get_order(order_id: str) -> Order | None:
    async with get_session() as session:
        return (
            await session.execute(select(Order).where(Order.order_id == order_id))
        ).scalar_one_or_none()


async def get_order_by_label(label: str) -> Order | None:
    async with get_session() as session:
        return (
            await session.execute(select(Order).where(Order.label == label))
        ).scalar_one_or_none()


async def list_orders_for(telegram_id: int, statuses: tuple[str, ...] = ("pending",)) -> list[Order]:
    async with get_session() as session:
        stmt = (
            select(Order)
            .where(Order.telegram_id == telegram_id, Order.status.in_(statuses))
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        return list((await session.execute(stmt)).scalars().all())


async def get_local_user(telegram_id: int) -> User | None:
    async with get_session() as session:
        return (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()


# ------------------------------------------------- фиксация оплаты (идемпотентно)

async def event_exists(operation_id: str) -> bool:
    async with get_session() as session:
        return (
            await session.execute(
                select(PaymentEvent.id).where(PaymentEvent.operation_id == operation_id)
            )
        ).scalar_one_or_none() is not None


async def claim_order(order: Order, *, operation_id: str, amount: Decimal, raw_hash: str) -> Order | None:
    """Переводит заказ pending -> paid одним атомарным UPDATE.

    Возвращает обновлённый заказ или None, если заказ уже обработан/не найден.
    Повторное уведомление по тому же operation_id не выдаёт дни повторно.
    """
    if await event_exists(operation_id):
        return None
    async with get_session() as session:
        res = await session.execute(
            update(Order)
            .where(Order.order_id == order.order_id, Order.status == "pending")
            .values(
                status="paid",
                operation_id=operation_id,
                received_amount=amount,
                paid_at=utcnow(),
            )
        )
        if res.rowcount == 0:
            return None
        session.add(
            PaymentEvent(
                operation_id=operation_id,
                label=order.label,
                raw_hash=str(raw_hash or "")[:128],
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # второй процесс успел первым — это дубль
            await session.rollback()
            return None
        return (
            await session.execute(select(Order).where(Order.order_id == order.order_id))
        ).scalar_one()


async def mark_event_processed(operation_id: str) -> None:
    from sqlalchemy import update as _update

    async with get_session() as session:
        await session.execute(
            _update(PaymentEvent)
            .where(PaymentEvent.operation_id == operation_id)
            .values(processed_at=utcnow())
        )
        await session.commit()


# ------------------------------------------------- выдача подписки (Remnawave)

_tg_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def provision_user(telegram_id: int, days: int) -> User:
    """Создаёт или продлевает пользователя Remnawave и обновляет локальную запись.

    * Если пользователь уже есть (локально или в панели) — extend на N дней;
    * если нет — создаётся с username tg_<telegram_id>;
    * локальная запись пополняется remnawave_user_id / subscription_url / expire_at.
    """
    if not valid_telegram_id(telegram_id):
        raise ValueError("Некорректный Telegram ID")
    days = max(1, min(int(days), 3650))

    async with _locks_guard:
        lock = _tg_locks.setdefault(int(telegram_id), asyncio.Lock())
    async with lock:
        remna = get_remna()

        async with get_session() as session:
            local = (
                await session.execute(select(User).where(User.telegram_id == telegram_id))
            ).scalar_one_or_none()
            if local is None:
                local = User(telegram_id=int(telegram_id), status="ACTIVE")
                session.add(local)
                await session.commit()

            was_blocked = local.status == "BLOCKED"
            remna_id = local.remnawave_user_id

        if was_blocked and remna_id:
            try:
                await remna.enable_user(remna_id)
            except RemnaError as exc:
                log.warning("Не удалось включить пользователя %s в панели: %s", remna_id, exc)

        if remna_id:
            try:
                ruser = await remna.extend_user(remna_id, days)
            except RemnaNotFound:
                ruser = None
            if not ruser:
                # пользователь удалён в панели — создаём заново (локальную запись НЕ удаляем)
                ruser = await remna.create_user(
                    username=_username_for(telegram_id), telegram_id=telegram_id, days=days
                )
        else:
            existing = await remna.find_user_by_telegram_id(telegram_id)
            if existing and existing.get("id"):
                ruser = await remna.extend_user(str(existing["id"]), days)
            else:
                ruser = await remna.create_user(
                    username=_username_for(telegram_id), telegram_id=telegram_id, days=days
                )

        sub_url = str(ruser.get("subscriptionUrl") or "") or None
        if not sub_url:
            sub = await remna.get_subscription(str(ruser.get("id") or ""))
            if isinstance(sub, dict):
                sub_url = str(sub.get("subscriptionUrl") or sub.get("url") or "") or None

        await _ensure_squads(remna, ruser)

        expire = parse_iso_utc(ruser.get("expireAt"))

        async with get_session() as session:
            local = (
                await session.execute(select(User).where(User.telegram_id == telegram_id))
            ).scalar_one()
            local.remnawave_user_id = str(ruser.get("id") or local.remnawave_user_id or "")
            local.username = str(ruser.get("username") or local.username or _username_for(telegram_id))
            if sub_url:
                local.subscription_url = sub_url
            if expire:
                local.expire_at = expire
            local.status = "EXPIRED" if (expire and expire <= utcnow()) else "ACTIVE"
            await session.commit()
            return local


async def _ensure_squads(remna, ruser: dict) -> None:
    """Гарантирует, что пользователь состоит в сквадах из REMNAWAVE_DEFAULT_SQUADS.

    Нужен для пользователей, созданных до настройки сквадов: при ближайшем
    продлении/довыдаче они автоматически получат доступ к нодам.
    """
    squads = remna.default_squads
    if not squads or not ruser.get("id"):
        return
    current: list[str] = []
    for item in ruser.get("activeInternalSquads") or []:
        if isinstance(item, dict):
            uuid = item.get("uuid")
            if uuid:
                current.append(str(uuid))
        elif item:
            current.append(str(item))
    if set(current) >= set(squads):
        return
    merged = list(dict.fromkeys(current + squads))
    try:
        await remna.update_user(str(ruser["id"]), activeInternalSquads=merged)
        log.info("Пользователь %s добавлен в сквады: %s", ruser.get("username"), squads)
    except RemnaError as exc:
        log.warning("Не удалось добавить пользователя в сквады: %s", exc)
        await log_service_error(
            "remnawave",
            f"Пользователь {ruser.get('username')} не добавлен в сквады {squads}: {exc}",
            level="warning",
        )


def _username_for(telegram_id: int) -> str:
    from app.utils import make_username

    return make_username(telegram_id)


# --------------------------------------------- обработка успешного платежа

async def process_successful_payment(
    order: Order, *, operation_id: str, amount: Decimal, raw_hash: str = ""
) -> tuple[bool, str]:
    """Фиксирует оплату и выдаёт подписку. Идемпотентно.

    Возвращает (ok, code): ok=True — платёж зафиксирован,
    code: ok | already | deferred | order_not_found | error:<msg>
    """
    claimed = await claim_order(order, operation_id=operation_id, amount=amount, raw_hash=raw_hash)
    if claimed is None:
        current = await get_order(order.order_id)
        if current is not None and current.status == "paid":
            return True, "already"
        return False, "order_not_found"

    err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            await provision_user(order.telegram_id, order.tariff_days)
            err = None
            break
        except RemnaError as exc:
            err = exc
            log.warning("Выдача подписки (попытка %d/3) не удалась: %s", attempt, exc)
            await asyncio.sleep(2 * attempt)
        except Exception as exc:  # непредвиденное — тоже ретраим
            err = exc
            log.exception("Неожиданная ошибка выдачи подписки")
            await asyncio.sleep(2 * attempt)

    if err is not None:
        await log_service_error(
            "remnawave",
            f"Оплата по заказу {order.order_id} получена, но выдача не удалась: {err}",
        )
        await notifications.notify_admin(
            "⚠️ <b>Оплата получена, но выдача не удалась</b>\n"
            f"Заказ: <code>{order.order_id}</code>\n"
            f"Telegram ID: <code>{order.telegram_id}</code>\n"
            f"Причина: {err}\n"
            "Выдайте подписку вручную: Админка → Заказы → «Переотправить»."
        )
        return True, "deferred"

    await mark_event_processed(operation_id)
    fresh = await get_order(order.order_id) or order
    await notifications.notify_payment_success(fresh)
    return True, "ok"


async def ensure_provisioned_and_notify(order: Order) -> str:
    """Ручная довыдача из админки: если подписка не выдана — выдать, иначе отправить ключ."""
    local = await get_local_user(order.telegram_id)
    if local and local.remnawave_user_id:
        await notifications.notify_key(local)
        return "key_sent"
    await provision_user(order.telegram_id, order.tariff_days)
    fresh = await get_local_user(order.telegram_id)
    if fresh is not None:
        await notifications.notify_key(fresh)
    return "provisioned"


async def log_service_error(kind: str, message: str, level: str = "error") -> None:
    """Пишет ошибку сервиса в БД (раздел «Логи» админки)."""
    from app.models import ServiceLog

    try:
        async with get_session() as session:
            session.add(ServiceLog(kind=kind, level=level, message=str(message)[:2000]))
            await session.commit()
    except Exception:  # логирование не должно ломать основной поток
        log.exception("Не удалось записать service log")
RW_EOF_28
cat > vpn-bot/app/services/remnawave.py <<'RW_EOF_29'
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
RW_EOF_29
cat > vpn-bot/app/services/tariffs.py <<'RW_EOF_30'
"""Тарифы: эффективные значения хранятся в БД (редактируются в админке),
стартовые — из .env (PRICE_*_DAYS или PRICES_*)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.database import get_session
from app.models import Tariff

TARIFF_DAYS = (7, 30, 90, 180, 365)


async def get_tariffs(*, only_enabled: bool = True) -> list[Tariff]:
    async with get_session() as session:
        stmt = select(Tariff).order_by(Tariff.sort, Tariff.days)
        if only_enabled:
            stmt = stmt.where(Tariff.enabled.is_(True))
        return list((await session.execute(stmt)).scalars().all())


async def get_all_tariffs() -> list[Tariff]:
    return await get_tariffs(only_enabled=False)


async def get_tariff(code: str) -> Tariff | None:
    async with get_session() as session:
        return (
            await session.execute(select(Tariff).where(Tariff.code == code))
        ).scalar_one_or_none()


def format_price(value: Decimal | str | float | int) -> str:
    """250 -> '250 ₽', 249.5 -> '249.50 ₽'."""
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return f"{value} ₽"
    if d == d.to_integral_value():
        return f"{int(d)} ₽"
    return f"{d} ₽"
RW_EOF_30
cat > vpn-bot/app/services/yoomoney.py <<'RW_EOF_31'
"""YooMoney: ссылка на оплату (quickpay), проверка подписи вебхука и
идемпотентная обработка HTTP-уведомлений + ручная проверка оплаты по API.

Оплата ВСЕГДА определяется по уникальному label + operation_id, никогда — по сумме.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.models import Order
from app.services import orders
from app.utils import fmt_money

log = logging.getLogger("app.yoomoney")

QUICKPAY_URL = "https://yoomoney.ru/quickpay/confirm"


# ---------------------------------------------------------------- суммы/комиссия

def _q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def display_amount(expected: Decimal) -> Decimal:
    """Сумма к оплате, показываемая клиенту (с учётом режима комиссии).

    client_fixed: клиент платит комиссию сверху -> к сумме добавляется процент.
    """
    s = get_settings()
    expected = _q2(expected)
    if s.yoomoney_fee_mode == "client_fixed":
        fee = expected * s.yoomoney_fee_percent / Decimal("100")
        return _q2(expected + fee)
    return expected


def required_amount(expected: Decimal) -> Decimal:
    """Минимальная сумма, которая должна прийти на кошелёк.

    absorb: миримся с удержанием комиссии -> принимаем чуть меньше ожидаемого.
    """
    s = get_settings()
    expected = _q2(expected)
    if s.yoomoney_fee_mode == "absorb":
        fee = expected * s.yoomoney_fee_percent / Decimal("100")
        return _q2(expected - fee)
    return expected


# ---------------------------------------------------------------- quickpay URL

def build_payment_url(order: Order) -> str:
    """Ссылка на оплату YooMoney (форма quickpay, оплата картой — paymentType=AC)."""
    s = get_settings()
    params = {
        "receiver": s.yoomoney_wallet,
        "quickpay-form": "shop",
        "targets": f"Оплата VPN-подписки ({order.tariff_days} дн.), заказ {order.order_id}",
        "paymentType": "AC",
        "label": order.label,
        "sum": fmt_money(display_amount(order.expected_price)),
    }
    if s.bot_username:
        params["successURL"] = f"https://t.me/{s.bot_username}"
    return f"{QUICKPAY_URL}?{urlencode(params)}"


# ---------------------------------------------------------------- подпись вебхука

def verify_signature(params: dict[str, str], secret: str) -> bool:
    """Проверяет sha1_hash (или sha256_hash) уведомления YooMoney.

    Строка подписи: notification_type & operation_id & amount & currency &
    datetime & sender & codepro & <секрет> & label
    """
    if not secret:
        return False

    def g(k: str) -> str:
        return str(params.get(k) or "")

    base = "".join(
        [
            g("notification_type"),
            g("operation_id"),
            g("amount"),
            g("currency"),
            g("datetime"),
            g("sender"),
            g("codepro"),
            secret,
            g("label"),
        ]
    ).encode("utf-8")

    sha256_hash = (params.get("sha256_hash") or "").strip().lower()
    if sha256_hash and hashlib.sha256(base).hexdigest() == sha256_hash:
        return True
    sha1_hash = (params.get("sha1_hash") or "").strip().lower()
    if sha1_hash and hashlib.sha1(base).hexdigest() == sha1_hash:
        return True
    return False


# ---------------------------------------------------------------- rate limiter

class SimpleRateLimiter:
    """Простой in-memory sliding window лимитер (на процесс)."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max(1, int(max_events))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        if len(self._hits) > 10000:  # защита от роста памяти
            self._hits.clear()
        return True


# ---------------------------------------------------------------- webhook

async def process_notification(params: dict[str, str], client_ip: str = "-") -> tuple[int, str]:
    """Обработка HTTP-уведомления YooMoney. Возвращает (HTTP-статус, текст).

    Идемпотентность:
      * один operation_id обрабатывается один раз (payment_events.operation_id UNIQUE);
      * заказ переводится в paid одним атомарным UPDATE ... WHERE status='pending';
      * повторное уведомление не выдаёт дополнительные дни.
    """
    s = get_settings()
    label = (params.get("label") or "").strip()

    if not label:
        return 200, "no-label"
    if not label.startswith("rw_"):
        return 200, "foreign-label"

    order = await orders.get_order_by_label(label)
    if order is None:
        await orders.log_service_error(
            "webhook", f"Уведомление по неизвестному label={label} (ip={client_ip})", level="warning"
        )
        return 200, "order-not-found"

    secret = s.yoomoney_notification_secret
    if not secret:
        await orders.log_service_error(
            "yoomoney",
            "YOOMONEY_NOTIFICATION_SECRET не задан — уведомление отклонено",
            level="error",
        )
        return 403, "secret-not-configured"

    if not verify_signature(params, secret):
        await orders.log_service_error(
            "yoomoney",
            f"Неверная подпись уведомления для label={label} (ip={client_ip})",
            level="warning",
        )
        return 403, "bad-signature"

    operation_id = (params.get("operation_id") or "").strip()
    if not operation_id:
        return 400, "no-operation-id"

    if await orders.event_exists(operation_id):
        return 200, "duplicate"

    currency = (params.get("currency") or "").strip().upper()
    if currency not in ("643", "RUB"):
        await orders.log_service_error(
            "yoomoney", f"Неожиданная валюта {currency} по заказу {order.order_id}", level="warning"
        )
        return 400, "bad-currency"

    if (params.get("codepro") or "false").strip().lower() == "true":
        return 400, "codepro-true"
    if (params.get("unaccepted") or "false").strip().lower() == "true":
        return 400, "unaccepted"

    try:
        amount = Decimal(str(params.get("amount") or "0").replace(",", "."))
    except InvalidOperation:
        return 400, "bad-amount"

    required = required_amount(order.expected_price)
    if amount + Decimal("0.01") < required:
        await orders.log_service_error(
            "yoomoney",
            f"Сумма меньше ожидаемой: заказ {order.order_id}, получено {amount}, ожидалось {required}",
            level="warning",
        )
        # не подтверждаем заказ (остаётся pending), повторов не просим
        return 200, "amount-mismatch"

    raw_hash = params.get("sha1_hash") or params.get("sha256_hash") or ""
    ok, code = await orders.process_successful_payment(
        order, operation_id=operation_id, amount=amount, raw_hash=raw_hash
    )
    if not ok:
        return 500, code
    log.info("Платёж по заказу %s подтверждён (%s)", order.order_id, code)
    return 200, code


# ---------------------------------------------------- ручная проверка оплаты

async def fetch_operations_by_label(label: str) -> list[dict] | None:
    """История операций YooMoney по label (YOOMONEY_ACCESS_TOKEN). None = ошибка/нет токена."""
    s = get_settings()
    if not s.yoomoney_access_token:
        return None
    headers = {"Authorization": f"Bearer {s.yoomoney_access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://yoomoney.ru/api/operations-history",
                headers=headers,
                params={"type": "in", "label": label},
            )
            if resp.status_code == 200:
                ops = (resp.json() or {}).get("operations") or []
                if ops:
                    return ops
            # легаси-эндпоинт как fallback
            resp = await client.post(
                "https://yoomoney.ru/api/operation-history",
                headers=headers,
                data={"type": "in", "label": label},
            )
            if resp.status_code == 200:
                return (resp.json() or {}).get("operations") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Ошибка запроса истории YooMoney: %s", type(exc).__name__)
    return None


async def try_manual_confirm(order: Order) -> tuple[bool, str]:
    """Кнопка «Проверить оплату»: ищет платёж по label через API и подтверждает заказ."""
    operations = await fetch_operations_by_label(order.label)
    if operations is None:
        return (
            False,
            "Автопроверка недоступна (не настроен YOOMONEY_ACCESS_TOKEN или API недоступен). "
            "Если вы уже оплатили — подтверждение придёт автоматически в течение пары минут.",
        )

    for op in operations:
        if str(op.get("label") or "") != order.label:
            continue
        status = str(op.get("status") or "success").lower()
        if status != "success":
            continue
        try:
            amount = Decimal(str(op.get("amount")))
        except InvalidOperation:
            continue
        required = required_amount(order.expected_price)
        if amount + Decimal("0.01") < required:
            return (
                False,
                f"Найден платёж на {fmt_money(amount)} ₽, но это меньше ожидаемой суммы "
                f"({fmt_money(required)} ₽). Обратитесь в поддержку.",
            )
        ok, code = await orders.process_successful_payment(
            order,
            operation_id=str(op.get("operation_id") or f"manual-{order.order_id}"),
            amount=amount,
            raw_hash="manual-check",
        )
        if ok:
            if code == "already":
                return True, "Эта оплата уже была подтверждена ранее."
            return True, "✅ Оплата подтверждена! Подписка активирована/продлена."
        return False, "Оплата найдена, но произошла ошибка обработки. Попробуйте ещё раз через минуту."

    return (
        False,
        "Оплата пока не найдена. Если вы уже оплатили — подождите пару минут: "
        "платёж подтвердится автоматически, я пришлю уведомление.",
    )
RW_EOF_31
cat > vpn-bot/app/telegram/__init__.py <<'RW_EOF_32'
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
RW_EOF_32
cat > vpn-bot/app/telegram/handlers_admin.py <<'RW_EOF_33'
"""Телеграм-команды администратора (только для ADMIN_ID из .env).

/admin — краткая статистика
/find <telegram_id> — информация о пользователе
/msg <telegram_id> <текст> — написать пользователю от имени бота
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message
from sqlalchemy import func, select

from app.config import get_settings
from app.database import get_session
from app.models import Order, User
from app.services import notifications
from app.services.orders import get_local_user
from app.utils import days_left, display_dt, esc, fmt_money, utcnow

log = logging.getLogger("app.bot.admin")

router = Router(name="admin")


class AdminOnly(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        s = get_settings()
        return bool(s.admin_id > 0 and message.from_user and message.from_user.id == s.admin_id)


@router.message(AdminOnly(), Command("admin"))
async def cmd_admin(message: Message) -> None:
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active = (
            await session.scalar(
                select(func.count(User.id)).where(User.status == "ACTIVE", User.expire_at > now)
            )
            or 0
        )
        expired = (
            await session.scalar(
                select(func.count(User.id)).where(
                    User.expire_at.is_not(None), User.expire_at <= now
                )
            )
            or 0
        )
        orders_total = await session.scalar(select(func.count(Order.id))) or 0
        orders_paid = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "paid")) or 0
        )
        revenue = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(Order.status == "paid")
            )
            or 0
        )
        sales_today = (
            await session.scalar(
                select(func.count(Order.id)).where(Order.status == "paid", Order.paid_at >= today)
            )
            or 0
        )
        revenue_today = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        sales_month = (
            await session.scalar(
                select(func.count(Order.id)).where(Order.status == "paid", Order.paid_at >= month)
            )
            or 0
        )
        revenue_month = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"✅ Активных подписок: <b>{active}</b>\n"
        f"⛔️ Истёкших: <b>{expired}</b>\n\n"
        f"🧾 Заказов всего: <b>{orders_total}</b> (оплачено {orders_paid})\n"
        f"💰 Выручка: <b>{fmt_money(revenue)} ₽</b>\n\n"
        f"📅 Сегодня: {sales_today} продаж на {fmt_money(revenue_today)} ₽\n"
        f"🗓 За месяц: {sales_month} продаж на {fmt_money(revenue_month)} ₽"
    )
    await message.answer(text)


@router.message(AdminOnly(), Command("find"))
async def cmd_find(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("Использование: <code>/find &lt;telegram_id&gt;</code>")
        return
    telegram_id = int(parts[1].strip())
    local = await get_local_user(telegram_id)
    if local is None:
        await message.answer("Пользователь в локальной базе не найден.")
        return

    async with get_session() as session:
        orders_list = list(
            (
                await session.execute(
                    select(Order)
                    .where(Order.telegram_id == telegram_id)
                    .order_by(Order.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )

    tz = get_settings().display_tz
    lines = [
        "👤 <b>Пользователь</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
        f"Remna username: <code>{esc(local.username or '—')}</code>",
        f"Remna ID: <code>{esc(local.remnawave_user_id or '—')}</code>",
        f"Статус: {esc(local.status)}",
        f"Окончание: {display_dt(local.expire_at, tz)} (осталось {days_left(local.expire_at)} дн.)",
    ]
    if local.subscription_url:
        lines.append(f"Подписка: {esc(local.subscription_url)}")
    if orders_list:
        lines.append("\n🧾 Последние заказы:")
        for o in orders_list:
            lines.append(
                f"• <code>{o.order_id}</code> — {o.tariff_days} дн., "
                f"{fmt_money(o.expected_price)} ₽, {esc(o.status)}"
            )
    await message.answer("\n".join(lines))


@router.message(AdminOnly(), Command("msg"))
async def cmd_msg(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].strip().lstrip("-").isdigit():
        await message.answer("Использование: <code>/msg &lt;telegram_id&gt; &lt;текст&gt;</code>")
        return
    telegram_id = int(parts[1].strip())
    text = parts[2]
    ok = await notifications.send_message(telegram_id, esc(text), parse_mode=ParseMode.HTML)
    await message.answer("✅ Отправлено" if ok else "⚠️ Не удалось отправить")
RW_EOF_33
cat > vpn-bot/app/telegram/handlers_shop.py <<'RW_EOF_34'
"""Магазин: список тарифов, создание заказа, ссылка на оплату YooMoney."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app.services import orders
from app.services.notifications import (
    btn,
    menu_kb,
    order_created_text,
    send_message,
    url_btn,
)
from app.services.tariffs import get_tariff, get_tariffs, format_price
from app.services.yoomoney import build_payment_url, display_amount
from app.telegram.handlers_start import upsert_local_user
from app.utils import esc, fmt_money

log = logging.getLogger("app.bot.shop")

router = Router(name="shop")


async def _tariffs_kb() -> InlineKeyboardMarkup:
    rows = []
    for t in await get_tariffs():
        rows.append(
            [btn(f"💎 {t.title} — {format_price(t.price)}", f"buy:{t.code}")]
        )
    rows.append([btn("⬅️ Назад в меню", "menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.in_({"menu:shop", "menu:renew"}))
async def cb_shop(cb: CallbackQuery) -> None:
    tariffs = await get_tariffs()
    if not tariffs:
        await cb.answer("Тарифы временно недоступны", show_alert=True)
        return
    text = (
        "🛒 <b>Выберите тариф</b>\n\n"
        "После оплаты подписка выдаётся автоматически за 1–2 минуты.\n"
        "Продление суммируется с текущим сроком."
    )
    try:
        if cb.message is not None:
            await cb.message.edit_text(text, reply_markup=await _tariffs_kb())
        else:
            raise RuntimeError
    except Exception:
        if cb.from_user:
            await send_message(cb.from_user.id, text, reply_markup=await _tariffs_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery) -> None:
    if cb.from_user is None or cb.message is None:
        await cb.answer()
        return

    code = cb.data.split(":", 1)[1]
    tariff = await get_tariff(code)
    if tariff is None or not tariff.enabled:
        await cb.answer("Тариф недоступен", show_alert=True)
        return

    telegram_id = cb.from_user.id
    await upsert_local_user(telegram_id, cb.from_user.username)

    order = await orders.create_order(
        telegram_id,
        tariff_code=tariff.code,
        tariff_days=tariff.days,
        price=tariff.price,
    )
    pay_amount = fmt_money(display_amount(order.expected_price))
    text = order_created_text(
        order_id=order.order_id,
        days=tariff.days,
        pay_amount=pay_amount,
        price=fmt_money(tariff.price),
    )

    from aiogram.types import InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [url_btn(f"💳 Оплатить {pay_amount} ₽", build_payment_url(order))],
            [btn("💳 Проверить оплату", f"chk:{order.order_id}")],
            [btn("⬅️ К тарифам", "menu:shop")],
        ]
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await send_message(telegram_id, text, reply_markup=kb)
    await cb.answer()
RW_EOF_34
cat > vpn-bot/app/telegram/handlers_start.py <<'RW_EOF_35'
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
RW_EOF_35
cat > vpn-bot/app/telegram/handlers_subscription.py <<'RW_EOF_36'
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
RW_EOF_36
cat > vpn-bot/app/utils.py <<'RW_EOF_37'
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
RW_EOF_37
cat > vpn-bot/docker-compose.yml <<'RW_EOF_38'
services:
  bot:
    build:
      context: .
      dockerfile: Dockerfile
    image: vpnbot-bot:latest
    container_name: vpnbot-bot
    restart: unless-stopped
    env_file: .env
    environment:
      BOT_HTTP_PORT: 8088
    ports:
      # наружу не публикуем — healthcheck ходит локально
      - "127.0.0.1:8088:8088"
    volumes:
      - bot_data:/app/data
    stop_grace_period: 30s

  admin:
    build:
      context: .
      dockerfile: Dockerfile.admin
    image: vpnbot-admin:latest
    container_name: vpnbot-admin
    restart: unless-stopped
    env_file: .env
    environment:
      ADMIN_PORT: 8090
    ports:
      # Caddy проксирует admin.panel.litenergyapp.store -> 127.0.0.1:8090
      - "127.0.0.1:8090:8090"
    volumes:
      - bot_data:/app/data
    stop_grace_period: 30s

volumes:
  bot_data:
RW_EOF_38
cat > vpn-bot/requirements.txt <<'RW_EOF_39'
aiogram>=3.13,<4
fastapi>=0.115,<1
uvicorn[standard]>=0.30,<1
SQLAlchemy[asyncio]>=2.0.36,<3
aiosqlite>=0.20,<1
asyncpg>=0.29,<1
httpx>=0.27,<1
pydantic>=2.8,<3
pydantic-settings>=2.4,<3
Jinja2>=3.1,<4
python-multipart>=0.0.9
itsdangerous>=2.1,<3
tzdata>=2024.1
RW_EOF_39

# -------------------------------------------------------------
if [ ! -f vpn-bot/.env ]; then
  cp vpn-bot/.env.example vpn-bot/.env
  echo "!! Создан vpn-bot/.env из примера — ЗАПОЛНИТЕ секреты: nano vpn-bot/.env"
else
  echo "==> Существующий vpn-bot/.env не изменён"
fi

chmod +x vpn-bot-deploy.sh 2>/dev/null || true
echo ""
echo "==> Готово. Файлов записано: 39"
echo ""
echo "Дальнейшие шаги:"
echo "  1) nano vpn-bot/.env        # заполните BOT_TOKEN, REMNAWAVE_*, YOOMONEY_*, ADMIN_*"
echo "  2) cd vpn-bot"
echo "  3) docker compose build && docker compose up -d"
echo "  4) docker compose ps && docker compose logs -f --tail=50"
echo ""
if [ "${1:-}" = "--deploy" ]; then
  echo "==> Сборка и запуск контейнеров"
  cd vpn-bot
  docker compose build
  docker compose up -d
  docker compose ps
fi
