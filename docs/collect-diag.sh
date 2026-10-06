#!/usr/bin/env bash
# collect-diag.sh — сбор диагностики для связки Remnawave / Xray (Reality, мост, CDN)
#
# Запуск (на сервере с нодой Remnawave, от root):
#   bash collect-diag.sh
#   bash collect-diag.sh <IP_ВТОРОГО_СЕРВЕРА> <ПОРТ_МОСТА>     # добавит проверку доступности второго сервера
#
# Скрипт ничего не меняет, только читает. Секреты (UUID, ключи, пароли) заменяются на XXX.
# Результат появится рядом в файле remnawave-diag-<дата>.txt — пришлите его целиком.

set +e
OUT="remnawave-diag-$(date +%Y%m%d-%H%M%S).txt"
TARGET_IP="${1:-}"
TARGET_PORT="${2:-}"

have() { command -v "$1" >/dev/null 2>&1; }
redact() {
  sed -E \
    -e 's/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/UUID_XXX/g' \
    -e 's/("(privateKey|publicKey|password|secretKey|SECRET_KEY|shortId|xver)"[[:space:]]*:[[:space:]]*")[^"]*/\1XXX/g' \
    -e 's/((PASSWORD|SECRET_KEY|TOKEN|API_TOKEN)[=:][[:space:]]*)[^[:space:]]+/\1XXX/g'
}

{
  echo "=============================================================="
  echo " Remnawave / Xray diagnostic report"
  echo " Дата: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo " Хост: $(hostname) | $(uname -srm)"
  echo "=============================================================="

  echo
  echo "### 1. ВЫХОД В ИНТЕРНЕТ С ЭТОГО СЕРВЕРА"
  have curl && { echo "--- curl ipinfo:"; timeout 10 curl -sS https://ipinfo.io/json 2>&1 | redact; echo; \
                 timeout 10 curl -sS -o /dev/null -w 'google https: %{http_code}\n' https://www.google.com 2>&1; }
  have ping && { echo "--- ping 1.1.1.1:"; ping -c2 -W3 1.1.1.1 2>&1 | tail -3; }
  have dig  && { echo "--- DNS google.com:"; timeout 8 dig +short google.com 2>&1 | head -5; }
  echo "--- ip route:"; ip route 2>&1 | head -10

  echo
  echo "### 2. ДОСТУПНОСТЬ ВТОРОГО СЕРВЕРА (моста)"
  if [ -n "$TARGET_IP" ]; then
    have ping && { echo "--- ping $TARGET_IP:"; ping -c2 -W3 "$TARGET_IP" 2>&1 | tail -3; }
    if [ -n "$TARGET_PORT" ]; then
      echo "--- TCP $TARGET_IP:$TARGET_PORT:"
      timeout 6 bash -c "cat < /dev/null > /dev/tcp/$TARGET_IP/$TARGET_PORT" 2>&1 && echo "TCP_OPEN" || echo "TCP_CLOSED/TIMEOUT"
    fi
    have traceroute && { echo "--- traceroute (первые 8 хопов):"; timeout 25 traceroute -n -m 8 -w 2 "$TARGET_IP" 2>&1; }
  else
    echo "  (IP второго сервера не передан — запустите: bash collect-diag.sh IP PORT)"
  fi

  echo
  echo "### 3. DOCKER / КОНТЕЙНЕРЫ"
  have docker && { docker ps -a 2>&1; echo; echo "--- docker networks:"; docker network ls 2>&1; }

  echo
  echo "### 4. ЛОГИ REMNANODE (последние 250 строк, отфильтровано)"
  if have docker; then
    if docker ps -a --format '{{.Names}}' | grep -q '^remnanode$'; then
      docker logs --tail 250 remnanode 2>&1 | redact | tail -120
    else
      echo "  контейнер remnanode не найден, ищу похожие:"
      for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -iE 'node|xray|remna'); do
        echo "--- $c:"; docker logs --tail 80 "$c" 2>&1 | redact | tail -40
      done
    fi
  fi

  echo
  echo "### 5. СЛУШАЮЩИЕ ПОРТЫ"
  (have ss && ss -tulnp) || (have netstat && netstat -tulnp) 2>&1 | head -60

  echo
  echo "### 6. ФАЕРВОЛ"
  (have ufw && ufw status verbose) 2>&1 | head -40
  (have iptables && iptables -S) 2>&1 | head -60
  have nft && { echo "--- nft ruleset:"; nft list ruleset 2>&1 | head -60; }

  echo
  echo "### 7. XRAY CONFIG (секреты заменены на XXX)"
  FOUND=0
  for p in /usr/local/etc/xray/config.json /opt/remnanode/config.json /etc/xray/config.json; do
    if [ -f "$p" ]; then echo "--- $p:"; redact < "$p"; FOUND=1; fi
  done
  if [ "$FOUND" = "0" ] && have docker; then
    CID="$(docker ps -a --format '{{.Names}} {{.ID}}' | awk '/remnanode|remnawave|xray/ {print $2; exit}')"
    if [ -n "$CID" ]; then
      CFG="$(docker exec "$CID" sh -c 'find / -maxdepth 6 -name "config.json" -path "*xray*" 2>/dev/null | head -1' 2>/dev/null)"
      echo "--- контейнер $CID, путь: ${CFG:-не найден}"
      [ -n "$CFG" ] && docker exec "$CID" cat "$CFG" 2>&1 | redact
    fi
  fi

  echo
  echo "### 8. ВЕРСИЯ / ОБРАЗ"
  have docker && docker images 2>&1 | grep -iE 'remna|xray|node' | head -10
  have xray  && xray version 2>&1 | head -3

  echo
  echo "### 9. ВРЕМЯ И ЧАСЫ"
  date; timedatectl 2>&1 | head -5

  echo
  echo "=============================================================="
  echo " ГОТОВО. Файл: $OUT"
  echo " Проверьте глазами, что секретов не осталось, и пришлите мне целиком."
  echo "=============================================================="
} 2>&1 | tee "$OUT"

echo
echo "Сохранено в: $(pwd)/$OUT"
