#!/usr/bin/env bash
# LitEnergy: полная установка бота. Версия 2026-10-07.6
#   тест 1 день (с QR) · рефералка +1 день · «Моя подписка» · локации
#   фирменный экран входа с баннером · пробник на главном экране для новых
#   напоминания и бэкап по крону
#
# Запуск:  bash /root/vpnbot-install-all.sh
# Повторный запуск безопасен.

set -u

VERSION="install-all 2026-10-07.6"
BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
RAW="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"
STAMP="$(date +%s)"

say()  { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }

fetch() {  # fetch <файл в docs> <куда положить>
  local src="$1" dst="$2"
  curl -fsSL -o "$dst" "$RAW/$src?v=$STAMP-$RANDOM"
}

say "$VERSION"

cd "$BOT_DIR" || { say "!! нет каталога $BOT_DIR"; exit 1; }
say "корень бота: $BOT_DIR"

step "1/9  Тестовая подписка на 1 день"
fetch vpnbot-patch-trial.py /root/vpnbot-patch-trial.py || { say "!! не скачался патч теста"; exit 1; }
python3 /root/vpnbot-patch-trial.py || { say "!! патч теста не применился"; exit 1; }

step "2/9  Рефералка, «Моя подписка», справка, QR"
fetch vpnbot-patch-features.py /root/vpnbot-patch-features.py || { say "!! не скачался патч функций"; exit 1; }
python3 /root/vpnbot-patch-features.py || { say "!! патч функций не применился"; exit 1; }

step "3/9  Баннер и аватар"
mkdir -p "$BOT_DIR/app/telegram/assets"
if fetch banner-litenergy.png /root/litenergy-banner.png; then
  cp /root/litenergy-banner.png "$BOT_DIR/app/telegram/assets/litenergy-banner.png"
  say "  ok  баннер: app/telegram/assets/litenergy-banner.png ($(du -h /root/litenergy-banner.png | cut -f1))"
else
  say "  !! баннер не скачался — экран входа будет текстом"
fi
fetch avatar-litenergy.png /root/litenergy-avatar.png && say "  ok  аватар: /root/litenergy-avatar.png (для BotFather → /setuserpic)"

step "4/9  Красивый экран входа, тексты, кнопка пробника для новых, /apps и /link"
fetch vpnbot-patch-polish.py /root/vpnbot-patch-polish.py || { say "!! не скачался патч оформления"; exit 1; }
VPNBOT_BANNER=/root/litenergy-banner.png python3 /root/vpnbot-patch-polish.py || { say "!! патч оформления не применился"; exit 1; }
say "  проверка: экран входа обновлён ($(grep -c _litenergy_design "$BOT_DIR/app/telegram/handlers_start.py") связок)"
say "  проверка: врезки в main.py ($(grep -c _litenergy_look.attach "$BOT_DIR/app/main.py"))"

step "5/9  Карточка подписки с полоской срока и кнопка «Не подключается?»"
fetch vpnbot-patch-more.py /root/vpnbot-patch-more.py || { say "!! не скачался патч улучшений"; exit 1; }
python3 /root/vpnbot-patch-more.py || { say "!! патч улучшений не применился"; exit 1; }

step "6/9  Пересборка бота"
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
sleep 12

# segno нужен для QR-кодов: если в контейнере нет — добавляем и пересобираем без кэша
if ! docker exec "$CONTAINER" python -c "import segno" >/dev/null 2>&1; then
  say "  segno не установился — добавляю и пересобираю без кэша"
  grep -qi '^segno' requirements.txt || echo 'segno>=1.6' >> requirements.txt
  docker compose build --no-cache bot && docker compose up -d bot && sleep 10
fi
docker exec "$CONTAINER" python -c "import segno" >/dev/null 2>&1 \
  && say "  ok  QR-коды работают (segno на месте)" \
  || say "  !! segno всё ещё нет — QR не будет, остальное работает"

step "7/9  Служебные скрипты"
for pair in "vpnbot-remind-expiry.py:remind-expiry.py" "vpnbot-backup.sh:backup.sh" "vpnbot-watch-payments.py:watch-payments.py"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if fetch "$src" "/root/$dst"; then
    chmod +x "/root/$dst"
    say "  ok  /root/$dst"
  else
    say "  !! не скачался $src"
  fi
done

step "8/9  Крон: напоминания, бэкап, оплаты"
DB_PATH=""
[ -f "$BOT_DIR/data/bot.db" ] && DB_PATH="$BOT_DIR/data/bot.db"
if [ -z "$DB_PATH" ]; then
  DB_PATH="$(find /opt/vpnbot -maxdepth 4 -name 'bot.db' -not -path '*/node_modules/*' 2>/dev/null | head -1)"
fi
if [ -n "$DB_PATH" ]; then
  say "  база бота: $DB_PATH"
else
  say "  !! базу bot.db не нашёл — напоминания будут писать в лог «не нашёл базу»"
  say "     пришли вывод: docker exec $CONTAINER find /app -name 'bot.db'"
fi

CRON_TMP=/tmp/litenergy-cron.$$
crontab -l 2>/dev/null | grep -v 'remind-expiry.py' | grep -v 'vpnbot-backup.sh' > "$CRON_TMP" || true
{
  if [ -n "$DB_PATH" ]; then
    echo "0 12 * * * VPNBOT_DB=$DB_PATH /usr/bin/python3 /root/remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1"
  else
    echo '0 12 * * * /usr/bin/python3 /root/remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1'
  fi
  echo '30 4 * * * /bin/bash /root/backup.sh >> /var/log/vpnbot-backup.log 2>&1'
} >> "$CRON_TMP"
crontab "$CRON_TMP" && rm -f "$CRON_TMP"
say "  текущий крон:"; crontab -l | tail -3 | sed 's/^/    /'

step "9/9  Проверка"
printf '  баннер в контейнере: '
docker exec "$CONTAINER" test -s /app/app/telegram/assets/litenergy-banner.png 2>/dev/null && say "ok" || say "НЕТ"
printf '  новый экран входа: '
docker exec "$CONTAINER" grep -q "_litenergy_design" /app/app/telegram/handlers_start.py 2>/dev/null && say "ok" || say "НЕТ"
printf '  врезки в main.py: '
if docker exec "$CONTAINER" grep -q "_litenergy_look.attach" /app/app/main.py 2>/dev/null; then say "ok"; else say "НЕТ"; fi
printf '  пробник: '
docker exec "$CONTAINER" python -c "from app.services import trial;print('ok,', trial.trial_days(),'дн.')" 2>/dev/null || say "НЕТ"
printf '  оформление: '
docker exec "$CONTAINER" python -c "from app.telegram import look, design;print('ok')" 2>/dev/null || say "НЕТ"
printf '  рефералка: '
docker exec "$CONTAINER" python -c "from app.telegram import referral_extra;print('ok')" 2>/dev/null || say "НЕТ"
printf '  segno (QR): '
docker exec "$CONTAINER" python -c "import segno;print('ok')" 2>/dev/null || say "НЕТ"
printf '  диагностика: '
docker exec "$CONTAINER" python -c "from app.telegram import diag;print('ok')" 2>/dev/null || say "НЕТ"

say ""
say "Проверка в боте (лучше со второго аккаунта — где теста ещё не было):"
say "  • /start — баннер-картинка, «🎁 Попробовать 1 день — бесплатно» первой кнопкой"
say "  • после активации теста — сразу QR-код подписки"
say "  • /vpn — подписка · /ref — приглашение (+1 день) · /loc — локации · /apps — приложения"
say "  • /link — ссылка подписки с QR · /help — инструкция"
say "  • /diag или 🧭 «Не подключается?» — диагностика с чек-листом"
say ""
say "Аватар бота (по желанию): BotFather → /setuserpic → /root/litenergy-avatar.png"
say "Если что-то не отвечает — пришли: docker logs $CONTAINER --tail 40"
