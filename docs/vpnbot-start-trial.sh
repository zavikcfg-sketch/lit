#!/usr/bin/env bash
# Тестовая подписка 1 день + отчёт о структуре бота.
# Версия 2026-10-07.1
#
# Запуск одной строкой:
#   bash /root/vpnbot-start-trial.sh
#
# Что делает:
#   1) скачивает и применяет патч «тест на 1 день» (кнопка в магазине);
#   2) пересобирает контейнер бота;
#   3) складывает отчёт о структуре обработчиков в /root/inspect.out
#      (нужен, чтобы аккуратно улучшить внешний вид: меню, карточки, QR).
set -u

BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
CONTAINER="${VPNBOT_CONTAINER:-vpnbot-bot}"
RAW="https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs"

say() { printf '%s\n' "$*"; }

cd "$BOT_DIR" || { say "!! нет каталога $BOT_DIR"; exit 1; }

say "===== 1/4  Патч: тестовая подписка на 1 день ====="
curl -fsSL -o /root/vpnbot-patch-trial.py "$RAW/vpnbot-patch-trial.py?v=$(date +%s)" \
  || { say "!! не скачался патч (проверь интернет)"; exit 1; }
python3 /root/vpnbot-patch-trial.py || { say "!! патч не применился — пришли вывод выше"; exit 1; }

say ""
say "===== 2/4  Пересборка бота ====="
say "(код в контейнере обновляется только пересборкой)"
docker compose up -d --build || { say "!! docker compose не сработал"; exit 1; }
say "жду 12 секунд, пока бот поднимется..."
sleep 12

say ""
say "===== 3/4  Отчёт о структуре бота ====="
if curl -fsSL -o /root/inspect.py "$RAW/vpnbot-inspect.py?v=$(date +%s)"; then
  if docker cp /root/inspect.py "$CONTAINER:/tmp/inspect.py" >/dev/null 2>&1; then
    docker exec -w /app "$CONTAINER" python /tmp/inspect.py > /root/inspect.out 2>&1 || true
    say "отчёт сохранён: /root/inspect.out ($(wc -l < /root/inspect.out) строк)"
  else
    say "!! не скопировался inspect.py в контейнер"
  fi
else
  say "!! не скачался inspect.py"
fi

say ""
say "===== 4/4  Готово ====="
say "Проверка теста: бот → Магазин → «🎁 Тест на 1 день — бесплатно»"
say "  (со своего аккаунта скажет «подписка уже есть» — это правильно, проверь со второго)"
say ""
say "Дальше пришли мне отчёт:  cat /root/inspect.out"
say "По нему подготовлю патч внешнего вида: красивое меню, карточка «Моя подписка»,"
say "QR-код для подключения и инструкции по приложениям (Happ, v2rayTun, Hiddify)."
