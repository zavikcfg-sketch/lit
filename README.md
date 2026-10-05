# lit — VPN-бот (Remnawave + YooMoney)

Готовый production-проект: Telegram-бот продажи VPN-подписок (Remnawave API + YooMoney),
веб-админка FastAPI, Docker Compose, Caddy.

## Структура

* [`vpn-bot/`](vpn-bot/) — исходники проекта (бот `:8088`, админка `:8090`).
* [`vpn-bot/README.md`](vpn-bot/README.md) — полная документация: запуск, YooMoney, Caddy, бэкапы.
* [`vpn-bot-deploy.sh`](vpn-bot-deploy.sh) — **один скрипт для сервера**: создаёт/обновляет все файлы
  проекта (`cat <<'EOF'`), не трогает существующий `.env` и базу.

## Быстрый старт на сервере

```bash
bash vpn-bot-deploy.sh          # создать/обновить файлы (./vpn-bot/)
nano vpn-bot/.env               # заполнить секреты
cd vpn-bot && docker compose up -d --build
```

или сразу со сборкой: `bash vpn-bot-deploy.sh --deploy`.

## Разработка

```bash
python3 scripts/gen_deploy.py      # перегенерировать vpn-bot-deploy.sh из vpn-bot/
pip install -r vpn-bot/requirements.txt
python3 scripts/smoke_test.py      # smoke-тесты (замоканный Remnawave)
```

⚠️ Никогда не коммитьте `.env` и не публикуйте токены. Все секреты — только в `.env` на сервере.
