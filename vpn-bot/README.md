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
