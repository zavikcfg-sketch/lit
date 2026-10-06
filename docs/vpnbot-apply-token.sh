#!/usr/bin/env bash
# Применить токен ЮMoney из файла к .env бота и проверить доступ к API.
# Версия 2026-10-06.1
#
# Как пользоваться (никаких переменных и длинных вставок в терминал):
#   1) nano /root/token.txt     -> вставить токен ЦЕЛИКОМ одной строкой, Ctrl+O, Enter, Ctrl+X
#   2) bash /root/vpnbot-apply-token.sh
#
# Скрипт сам проверит длину, запишет токен в .env, пересоберёт бота и покажет
# проверку API (ждать HTTP 200).

set -u

SCRIPT_VERSION="apply-token 2026-10-06.1"
BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
ENV_FILE="$BOT_DIR/.env"
TOKEN_FILE="${TOKEN_FILE:-/root/token.txt}"
RAW_BASE="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"

say() { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }
die() { printf '!! %s\n' "$*"; exit 1; }

step "0/4  Проверки"
say "$SCRIPT_VERSION"
[ -d "$BOT_DIR" ] || die "нет каталога $BOT_DIR"
cd "$BOT_DIR" || die "не могу перейти в $BOT_DIR"
[ -f "$ENV_FILE" ] || die "нет файла $ENV_FILE"
if [ ! -f "$TOKEN_FILE" ]; then
  die "нет файла $TOKEN_FILE. Создай его: nano $TOKEN_FILE (вставь токен целиком, одна строка, Ctrl+O, Enter, Ctrl+X)"
fi

RAW_BYTES=$(wc -c < "$TOKEN_FILE")
CLEAN=$(tr -d ' \t\r\n' < "$TOKEN_FILE")
say "файл $TOKEN_FILE: $RAW_BYTES байт; после очистки от пробелов/переводов строк: ${#CLEAN} символов"
say "начало токена: ${CLEAN:0:18}… (остальное скрыто)"
if [ "${#CLEAN}" -lt 200 ]; then
  say "первые 30 символов: ${CLEAN:0:30}"
  die "в файле только ${#CLEAN} символов, а полный токен — около 273. Проверь содержимое: nano $TOKEN_FILE (или cat -A $TOKEN_FILE)"
fi
case "$CLEAN" in
  *.*) ;;
  *) die "в токене нет символа точки — это похоже на пароль или секрет, а не на токен" ;;
esac

step "1/4  Запись токена в .env"
cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)" || die "не смог сделать бэкап .env"
awk -v v="$CLEAN" '
  index($0, "YOOMONEY_ACCESS_TOKEN=") == 1 { if (!done) { print "YOOMONEY_ACCESS_TOKEN="v; done=1 }; next }
  { print }
  END { if (!done) print "YOOMONEY_ACCESS_TOKEN="v }
' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE" || die "не смог записать .env"
STORED=$(awk -F= '/^YOOMONEY_ACCESS_TOKEN=/{print length($2)}' "$ENV_FILE")
LINES=$(grep -c '^YOOMONEY_ACCESS_TOKEN=' "$ENV_FILE")
say "в .env теперь: $STORED символов, строк с токеном: $LINES"
[ "$STORED" -ge 200 ] || die "в .env записалось только $STORED символов — что-то не так с файлом токена"
[ "$LINES" -eq 1 ] || say "внимание: строк с токеном $LINES (должна быть 1) — проверь .env вручную"

step "2/4  Перезапуск бота"
docker compose up -d --force-recreate || die "docker compose не сработал"
say "жду 12 секунд..."
sleep 12

step "3/4  Проверка API ЮMoney (ждать HTTP 200)"
curl -fsSL -o /root/vpnbot-yoomoney-probe.py "$RAW_BASE/vpnbot-yoomoney-probe.py?v=$(date +%s)" \
  || die "не скачался скрипт проверки (проверь интернет)"
docker cp /root/vpnbot-yoomoney-probe.py "$CONTAINER:/tmp/probe.py" >/dev/null || die "не скопировался в контейнер"
docker exec -w /app "$CONTAINER" python /tmp/probe.py || say "(проверка завершилась с ошибкой — смотри вывод выше)"

step "4/4  Что дальше"
if [ "${#CLEAN}" -ge 200 ]; then
  say "• токен записан: ${#CLEAN} символов"
  say "• крон уже стоит (раз в минуту), заказы подтвердятся сами"
  say "• журнал:  tail -20 /var/log/vpnbot-watch.log"
  say "• когда увидишь 'ПОДТВЕРЖДЕНО ok=True' — удали файл с токеном:  shred -u $TOKEN_FILE"
  say "• затем перевыпусти токен (он публиковался в переписке) и повтори эти же два шага с новым"
fi
