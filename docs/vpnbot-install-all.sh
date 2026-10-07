#!/usr/bin/env bash
# Полная установка LitEnergy-функций в бота: тест 1 день, рефералка (+1 день
# за друга), карточка «Моя подписка», локации, справка, новый вид главного
# экрана, напоминания об окончании, ежедневный бэкап. Версия 2026-10-07.2
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

step "1/7  Тестовая подписка на 1 день"
curl -fsSL -o /root/vpnbot-patch-trial.py "$RAW/vpnbot-patch-trial.py?v=$(date +%s)" \
  || { say "!! не скачался патч теста"; exit 1; }
python3 /root/vpnbot-patch-trial.py || { say "!! патч теста не применился"; exit 1; }

step "2/7  Рефералка, «Моя подписка», справка"
curl -fsSL -o /root/vpnbot-patch-features.py "$RAW/vpnbot-patch-features.py?v=$(date +%s)" \
  || { say "!! не скачался патч функций"; exit 1; }
python3 /root/vpnbot-patch-features.py || { say "!! патч функций не применился"; exit 1; }

step "3/7  Вид бота: пробник новым, локации, полезные кнопки, футер"
curl -fsSL -o /root/vpnbot-patch-beauty.py "$RAW/vpnbot-patch-beauty.py?v=$(date +%s)" \
  || { say "!! не скачался патч вида"; exit 1; }
python3 /root/vpnbot-patch-beauty.py || { say "!! патч вида не применился"; exit 1; }

step "4/7  Пересборка бота"
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
say "жду 15 секунд..."
sleep 15

step "5/7  Служебные скрипты"
for pair in "vpnbot-remind-expiry.py:remind-expiry.py" "vpnbot-backup.sh:backup.sh" "vpnbot-watch-payments.py:watch-payments.py"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if curl -fsSL -o "/root/$dst" "$RAW/$src?v=$(date +%s)"; then
    chmod +x "/root/$dst"
    say "  ok  /root/$dst"
  else
    say "  !! не скачался $src"
  fi
done

step "6/7  Крон: напоминания, бэкап, проверка оплат"
CRON_TMP=/tmp/litenergy-cron.$$
crontab -l 2>/dev/null | grep -v 'remind-expiry.py' | grep -v 'vpnbot-backup.sh' > "$CRON_TMP" || true
grep -q 'watch-payments' "$CRON_TMP" || echo "* * * * * cd $BOT_DIR && /usr/bin/python3 /root/watch-payments.py >> /var/log/vpnbot-watch.log 2>&1" >> "$CRON_TMP"
{
  echo '0 12 * * * /usr/bin/python3 /root/remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1'
  echo '30 4 * * * /bin/bash /root/backup.sh >> /var/log/vpnbot-backup.log 2>&1'
} >> "$CRON_TMP"
crontab "$CRON_TMP" && rm -f "$CRON_TMP"
say "текущие задания cron:"
crontab -l | tail -4

step "7/7  Проверка"
say -n "QR-код (segno в контейнере): "
docker exec "$CONTAINER" python -c "import segno; print('ok', segno.__version__)" 2>/dev/null || say "нет — QR не будет (остальное работает)"
say -n "пробник в коде: "
docker exec "$CONTAINER" python -c "from app.services import trial; print('ok, дней:', trial.trial_days())" 2>/dev/null || say "нет — проверь логи"
say -n "вид (look): "
docker exec "$CONTAINER" python -c "from app.telegram import look; print('ok')" 2>/dev/null || say "нет — проверь логи"
say ""
say "проверка напоминаний без отправки:"
/usr/bin/python3 /root/remind-expiry.py --dry-run | tail -5 || true
say ""
say "Проверка в боте:"
say "  • /start — «🎁 Попробовать 1 день — бесплатно» первой кнопкой (у кого теста ещё не было)"
say "  • после активации теста — сразу QR-код подписки"
say "  • /vpn — карточка подписки · /ref — приглашение (+1 день) · /help — инструкции"
say "  • 🌍 Локации — список серверов из панели (команда /loc)"
say ""
say "Если что-то не отвечает — пришли: docker logs $CONTAINER --tail 40"
