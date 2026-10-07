#!/usr/bin/env bash
# vpnbot: применить починку PATCH Remnawave (id вместо uuid), пересобрать бота
# и показать текущее состояние подписки/устройств. Версия 2026-10-06.1
#
# Запуск:  bash /root/vpnbot-apply-remna-fix.sh
set -u

BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
RAW="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"

say() { printf '%s\n' "$*"; }

cd "$BOT_DIR" || { say "нет каталога $BOT_DIR"; exit 1; }

say "===== 1/4  Починка кода: PATCH /api/users шлём с id, а не uuid ====="
curl -fsSL -o /root/vpnbot-fix-remnawave-update.py "$RAW/vpnbot-fix-remnawave-update.py?v=$(date +%s)" \
  || { say "!! не скачался скрипт починки"; exit 1; }
python3 /root/vpnbot-fix-remnawave-update.py || { say "!! починка не удалась — пришли вывод выше"; exit 1; }

say ""
say "===== 2/4  Пересборка бота ====="
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
say "жду 15 секунд..."
sleep 15

say ""
say "===== 3/4  Копирую служебные скрипты в контейнер ====="
for pair in "vpnbot-diag-remna.py:diag-remna.py" "vpnbot-admin-confirm.py:admin-confirm.py" "vpnbot-watch-payments.py:watch-payments.py"; do
  src="${pair%%:*}"
  dst="${pair##*:}"
  if curl -fsSL -o "/root/$src" "$RAW/$src?v=$(date +%s)"; then
    if docker cp "/root/$src" "$CONTAINER:/tmp/$dst" >/dev/null 2>&1; then
      say "  ok  $dst"
    else
      say "  !! не скопировался $dst"
    fi
  else
    say "  !! не скачался $src"
  fi
done

say ""
say "===== 4/4  Состояние: пользователь в панели + проверка PATCH ====="
docker exec -w /app "$CONTAINER" python /tmp/diag-remna.py || say "(диагностика завершилась с ошибкой — смотри вывод выше)"

say ""
say "ГОТОВО. Пришли мне вывод раздела 4/4 (последние ~40 строк):"
say "  - строку expireAt (дата окончания подписки)"
say "  - строку hwidDeviceLimit"
say "  - блок СЫРЫЕ PATCH-ЗАПРОСЫ (там ожидаем HTTP 200 у запросов с id)"
say "После этого выдам точные команды на выдачу подписок по оплаченным заказам."
