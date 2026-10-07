#!/usr/bin/env bash
# Полная установка LitEnergy: тест 1 день (с QR), рефералка (+1 день за друга),
# карточка «Моя подписка», локации, справка, новый вид с баннером,
# напоминания об окончании, ежедневный бэкап. Версия 2026-10-07.3
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

step "1/8  Тестовая подписка на 1 день"
curl -fsSL -o /root/vpnbot-patch-trial.py "$RAW/vpnbot-patch-trial.py?v=$(date +%s)" \
  || { say "!! не скачался патч теста"; exit 1; }
python3 /root/vpnbot-patch-trial.py || { say "!! патч теста не применился"; exit 1; }

step "2/8  Рефералка, «Моя подписка», справка"
curl -fsSL -o /root/vpnbot-patch-features.py "$RAW/vpnbot-patch-features.py?v=$(date +%s)" \
  || { say "!! не скачался патч функций"; exit 1; }
python3 /root/vpnbot-patch-features.py || { say "!! патч функций не применился"; exit 1; }

step "3/8  Оформление меню (пробник новым, локации, полезные кнопки)"
curl -fsSL -o /root/vpnbot-patch-beauty.py "$RAW/vpnbot-patch-beauty.py?v=$(date +%s)" \
  || { say "!! не скачался патч вида"; exit 1; }
python3 /root/vpnbot-patch-beauty.py || { say "!! патч вида не применился"; exit 1; }

step "4/8  Баннер: скачиваю фирменную картинку"
mkdir -p "$BOT_DIR/app/telegram/assets"
curl -fsSL -o /root/litenergy-banner.png "$RAW/banner-litenergy.png?v=$(date +%s)" \
  || say "  !! баннер не скачался — экран входа будет текстом"
curl -fsSL -o /root/litenergy-avatar.png "$RAW/avatar-litenergy.png?v=$(date +%s)" \
  || say "  !! аватар не скачался"
[ -s /root/litenergy-banner.png ] && cp /root/litenergy-banner.png "$BOT_DIR/app/telegram/assets/litenergy-banner.png" \
  && say "  ok  баннер в app/telegram/assets/ (переживёт пересборку)"

step "5/8  Красивый экран входа, тексты, команды /apps и /link"
curl -fsSL -o /root/vpnbot-patch-polish.py "$RAW/vpnbot-patch-polish.py?v=$(date +%s)" \
  || { say "!! не скачался патч оформления"; exit 1; }
VPNBOT_BANNER=/root/litenergy-banner.png python3 /root/vpnbot-patch-polish.py \
  || { say "!! патч оформления не применился"; exit 1; }

step "6/8  Пересборка бота"
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
say "жду 15 секунд..."
sleep 15

step "7/8  Служебные скрипты и крон"
for pair in "vpnbot-remind-expiry.py:remind-expiry.py" "vpnbot-backup.sh:backup.sh" "vpnbot-watch-payments.py:watch-payments.py"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if curl -fsSL -o "/root/$dst" "$RAW/$src?v=$(date +%s)"; then
    chmod +x "/root/$dst"
    say "  ok  /root/$dst"
  else
    say "  !! не скачался $src"
  fi
done
CRON_TMP=/tmp/litenergy-cron.$$
crontab -l 2>/dev/null | grep -v 'remind-expiry.py' | grep -v 'vpnbot-backup.sh' > "$CRON_TMP" || true
grep -q 'watch-payments' "$CRON_TMP" || echo "* * * * * cd $BOT_DIR && /usr/bin/python3 /root/watch-payments.py >> /var/log/vpnbot-watch.log 2>&1" >> "$CRON_TMP"
{
  echo '0 12 * * * /usr/bin/python3 /root/remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1'
  echo '30 4 * * * /bin/bash /root/backup.sh >> /var/log/vpnbot-backup.log 2>&1'
} >> "$CRON_TMP"
crontab "$CRON_TMP" && rm -f "$CRON_TMP"
say "крон:"; crontab -l | tail -4

step "8/8  Проверка"
check() {
  printf '  %s: ' "$1"
  shift
  docker exec "$CONTAINER" python -c "$1" 2>/dev/null || say "НЕТ"
}
printf '  баннер в контейнере: '; docker exec "$CONTAINER" test -s /app/app/telegram/assets/litenergy-banner.png && say "ok" || say "нет"
printf '  segno (QR-коды): '; docker exec "$CONTAINER" python -c "import segno;print('ok')" 2>/dev/null || say "нет"
printf '  новый экран входа: '; docker exec "$CONTAINER" grep -q "_litenergy_design" /app/app/telegram/handlers_start.py && say "ok" || say "нет"
printf '  пробник: '; docker exec "$CONTAINER" python -c "from app.services import trial;print('ok', trial.trial_days(), 'дн.')" 2>/dev/null || say "нет"
printf '  оформление (look): '; docker exec "$CONTAINER" python -c "from app.telegram import look;print('ok')" 2>/dev/null || say "нет"
say ""
say "Проверка в боте:"
say "  • /start — баннер + «🎁 Попробовать 1 день — бесплатно» первой кнопкой (только новым)"
say "  • после активации теста — сразу QR-код подписки"
say "  • /vpn — подписка · /ref — приглашение (+1 день) · /loc — локации · /apps — приложения"
say "  • /link — ссылка подписки с QR"
say ""
say "Аватар для бота (по желанию): файл /root/litenergy-avatar.png → BotFather → /setuserpic"
say "Если что-то не отвечает — пришли: docker logs $CONTAINER --tail 40"
