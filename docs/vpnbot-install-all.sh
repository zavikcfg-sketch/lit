#!/usr/bin/env bash
# Полная установка LitEnergy-функций в бота: тест 1 день, рефералка (+1 день
# за друга), карточка «Моя подписка» с QR, справка по приложениям, напоминания
# об окончании, ежедневный бэкап. Версия 2026-10-07.1
#
# Запуск:  bash /root/vpnbot-install-all.sh
# Повторный запуск безопасен (всё идемпотентно).

set -u

BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
RAW="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"

say()  { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }

cd "$BOT_DIR" || { say "!! нет каталога $BOT_DIR"; exit 1; }

step "1/6  Тестовая подписка на 1 день"
curl -fsSL -o /root/vpnbot-patch-trial.py "$RAW/vpnbot-patch-trial.py?v=$(date +%s)" \
  || { say "!! не скачался патч теста"; exit 1; }
python3 /root/vpnbot-patch-trial.py || { say "!! патч теста не применился"; exit 1; }

step "2/6  Рефералка, «Моя подписка», справка, QR"
curl -fsSL -o /root/vpnbot-patch-features.py "$RAW/vpnbot-patch-features.py?v=$(date +%s)" \
  || { say "!! не скачался патч функций"; exit 1; }
python3 /root/vpnbot-patch-features.py || { say "!! патч функций не применился"; exit 1; }

step "3/6  Пересборка бота"
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
say "жду 15 секунд..."
sleep 15

step "4/6  Служебные скрипты"
for pair in "vpnbot-remind-expiry.py:remind-expiry.py" "vpnbot-backup.sh:backup.sh" "vpnbot-watch-payments.py:watch-payments.py"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if curl -fsSL -o "/root/$dst" "$RAW/$src?v=$(date +%s)"; then
    chmod +x "/root/$dst"
    say "  ok  /root/$dst"
  else
    say "  !! не скачался $src"
  fi
done

step "5/6  Крон: напоминания, бэкап, проверка оплат"
CRON_TMP=/tmp/litenergy-cron.$$
crontab -l 2>/dev/null | grep -v 'remind-expiry.py' | grep -v 'vpnbot-backup.sh' > "$CRON_TMP" || true
{
  echo '0 12 * * * /usr/bin/python3 /root/remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1'
  echo '30 4 * * * /bin/bash /root/backup.sh >> /var/log/vpnbot-backup.log 2>&1'
} >> "$CRON_TMP"
crontab "$CRON_TMP" && rm -f "$CRON_TMP"
say "текущие задания cron:"
crontab -l | tail -3

step "6/6  Проверка"
say "проверка напоминаний без отправки:"
/usr/bin/python3 /root/remind-expiry.py --dry-run | tail -6 || true
say ""
say "Проверка в боте (после пересборки):"
say "  • Магазин → «🎁 Тест на 1 день — бесплатно» (нужен второй аккаунт — без подписки)"
say "  • /vpn   → карточка «Моя подписка» с QR-кодом"
say "  • /ref   → ваша ссылка-приглашение (+1 день за друга)"
say "  • /help  → инструкции по приложениям"
say "  • в меню бота появились команды из списка Telegram"
say ""
say "Если /vpn или /ref не отвечают — пришли: docker logs vpnbot-bot --tail 40"
