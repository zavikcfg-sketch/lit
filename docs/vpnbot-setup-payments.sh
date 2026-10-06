#!/usr/bin/env bash
# vpnbot: настройка подтверждения оплат ЮMoney — токен, починка поиска платежей,
# авто-подтверждение по крону (раз в минуту). Версия 2026-10-06.1
#
# Запуск ОТ ROOT на сервере магазина (именно так, не через | bash):
#   curl -fsSL -o /root/vpnbot-setup-payments.sh "https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs/vpnbot-setup-payments.sh?v=$(date +%s)"
#   bash /root/vpnbot-setup-payments.sh
#
# Ничего секретного в командной строке и в истории bash не остаётся:
# токен и секрет вводятся в приглашении скрипта.

set -u

SCRIPT_VERSION="setup-payments 2026-10-06.1"
RAW_BASE="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"
BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
ENV_FILE="$BOT_DIR/.env"
LOG_FILE="/var/log/vpnbot-watch.log"

say()  { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }
die()  { printf '!! %s\n' "$*"; exit 1; }

get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }

set_env() {  # set_env KEY VALUE — без вывода значения на экран
  local key="$1" value="$2"
  if grep -q "^$key=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" '
      index($0, k"=") == 1 { if (!done) { print k"="v; done=1 } ; next }
      { print }
    ' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

step "0/7  Проверки"
say "$SCRIPT_VERSION"
[ -d "$BOT_DIR" ] || die "нет каталога $BOT_DIR (можно задать: VPNBOT_DIR=/путь bash $0)"
cd "$BOT_DIR" || die "не могу перейти в $BOT_DIR"
DOCKER_BIN="$(command -v docker)" || die "docker не найден"
[ -f "$ENV_FILE" ] || die "нет файла $ENV_FILE"
if $DOCKER_BIN ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  say "контейнер $CONTAINER запущен"
else
  say "внимание: контейнер $CONTAINER сейчас не запущен (это нормально, если ещё не поднимали)"
fi
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)" && say "бэкап .env сделан"
say "текущие переменные ЮMoney в .env:"
grep -n -i 'yoomoney' "$ENV_FILE" | sed 's/=.*/=<скрыто>/'

step "1/7  Токен ЮMoney (YOOMONEY_ACCESS_TOKEN)"
if [ -n "${TOKEN_FILE:-}" ] && [ -f "$TOKEN_FILE" ]; then
  FILE_TOK="$(tr -d '\r\n' < "$TOKEN_FILE")"
  if [ "${#FILE_TOK}" -ge 200 ]; then
    set_env YOOMONEY_ACCESS_TOKEN "$FILE_TOK"
    say "токен прочитан из $TOKEN_FILE (длина ${#FILE_TOK}) и записан в .env"
  else
    say "!! в $TOKEN_FILE только ${#FILE_TOK} символов — проверь файл"
  fi
fi
TOK="$(get_env YOOMONEY_ACCESS_TOKEN)"
if [ "${#TOK}" -ge 200 ]; then
  say "токен уже установлен (длина ${#TOK}) — оставляю как есть"
else
  if [ "${#TOK}" -ge 1 ]; then
    say "!! в .env токен есть, но он короче 200 символов (длина ${#TOK}) —"
    say "   похоже, он оборвался при вставке. Введи его заново целиком."
    say "   Полный токен — около 273 символов: 16 цифр кошелька, точка и длинный хвост."
  fi
  attempt=0
  while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
    read -r -p "Вставь токен ЮMoney и нажми Enter: " NEWTOK
    if [ "${#NEWTOK}" -ge 200 ] && printf '%s' "$NEWTOK" | grep -q '\.'; then
      set_env YOOMONEY_ACCESS_TOKEN "$NEWTOK"
      TOK="$NEWTOK"
      say "токен записан (длина ${#TOK})"
      break
    fi
    say "!! это не похоже на полный токен: введено символов ${#NEWTOK}, а нужно около 273."
    say "   Если вставилось меньше — токен оборвался. Надёжнее: сохрани его в файл"
    say "   (nano /root/token.txt), затем запусти скрипт с TOKEN_FILE=/root/token.txt."
    say "   Короткий ключ (~24 символа) — это секрет уведомлений, его спрошу на шаге 2."
  done
  [ "${#TOK}" -ge 100 ] || die "токен не введён — запусти скрипт заново (history −3)"
fi

step "2/7  Секрет уведомлений (необязательно, Enter — пропустить)"
SEC="$(get_env YOOMONEY_NOTIFICATION_SECRET)"
if [ -n "$SEC" ]; then
  say "секрет уже установлен (длина ${#SEC}) — оставляю как есть"
else
  read -r -p "Вставь секрет из настроек уведомлений ЮMoney (или Enter): " NEWSEC
  if [ -n "$NEWSEC" ]; then
    set_env YOOMONEY_NOTIFICATION_SECRET "$NEWSEC"
    say "секрет записан (длина ${#NEWSEC})"
  else
    say "пропущено — вебхук подпись проверять не будет, работаем через крон"
  fi
fi

step "3/7  Починка поиска платежей в app/services/yoomoney.py"
curl -fsSL -o /root/vpnbot-fix-yoomoney.py "$RAW_BASE/vpnbot-fix-yoomoney.py?v=$(date +%s)" \
  || die "не скачался fix-yoomoney.py (проверь интернет)"
python3 /root/vpnbot-fix-yoomoney.py || die "починка не удалась — пришли вывод выше"

step "4/7  Пересборка и запуск бота"
say "(важно: код в контейнере обновляется только пересборкой, restart не подходит)"
$DOCKER_BIN compose up -d --build || die "docker compose up -d --build не удался"
say "жду 15 секунд, пока бот поднимется..."
sleep 15

step "5/7  Авто-подтверждение: разовый прогон"
curl -fsSL -o "$BOT_DIR/watch-payments.py" "$RAW_BASE/vpnbot-watch-payments.py?v=$(date +%s)" \
  || die "не скачался watch-payments.py"
$DOCKER_BIN cp "$BOT_DIR/watch-payments.py" "$CONTAINER:/tmp/watch-payments.py" >/dev/null \
  && say "watch-payments.py скопирован в контейнер"
$DOCKER_BIN exec -w /app "$CONTAINER" python /tmp/watch-payments.py \
  || say "(прогон завершился с ошибкой — смотри вывод выше)"

step "6/7  Крон: проверка оплат раз в минуту"
touch "$LOG_FILE" 2>/dev/null || true
CRON_LINE="* * * * * cd $BOT_DIR && $DOCKER_BIN cp watch-payments.py $CONTAINER:/tmp/watch-payments.py >/dev/null 2>&1 && $DOCKER_BIN exec -w /app $CONTAINER python /tmp/watch-payments.py >> $LOG_FILE 2>&1"
( crontab -l 2>/dev/null | grep -v 'watch-payments' ; printf '%s\n' "$CRON_LINE" ) | crontab - \
  || die "не удалось установить задание в cron"
say "установлено:"
crontab -l | tail -1
if systemctl is-active cron >/dev/null 2>&1; then
  say "служба cron: работает"
else
  systemctl enable --now cron >/dev/null 2>&1 || service cron start >/dev/null 2>&1 || true
  say "служба cron: пытался запустить"
fi

step "7/7  Проверка токена (ждать HTTP 200)"
curl -fsSL -o /root/vpnbot-yoomoney-probe.py "$RAW_BASE/vpnbot-yoomoney-probe.py?v=$(date +%s)" \
  || die "не скачался probe"
$DOCKER_BIN cp /root/vpnbot-yoomoney-probe.py "$CONTAINER:/tmp/probe.py" >/dev/null
$DOCKER_BIN exec -w /app "$CONTAINER" python /tmp/probe.py

step "ГОТОВО"
say "• токен: длина ${#TOK}  (сохранён в .env)"
if [ -n "$(get_env YOOMONEY_NOTIFICATION_SECRET)" ]; then
  say "• секрет уведомлений: сохранён"
else
  say "• секрет уведомлений: не задан (для крона не нужен)"
fi
say "• крон: проверка каждую минуту"
say ""
say "Через 1-2 минуты посмотри журнал:  tail -20 $LOG_FILE"
say "Там должно появиться 'ПОДТВЕРЖДЕНО ok=True' по каждому оплаченному заказу."
say ""
say "Если в разделе 7 увидишь HTTP 401 — токен не подходит для API."
say "Перевыпусти его: yoomoney.ru/myservices/new (права: история операций),"
say "затем повтори этот же скрипт — он спросит новый токен."
