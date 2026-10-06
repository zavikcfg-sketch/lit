#!/usr/bin/env bash
# diag-mini.sh — минимальная диагностика одной пастой, для ноды Remnawave.
# Запуск от root:  bash diag-mini.sh        (секреты заменяются на XXX автоматически)
set +e
{
  echo '=== 1. ВЫХОД В ИНТЕРНЕТ С ЭТОГО СЕРВЕРА'
  curl -sS -m 8 https://ipinfo.io/json || echo NO_INTERNET
  curl -sS -m 8 -o /dev/null -w 'google: %{http_code}\n' https://www.google.com
  ping -c2 -W3 1.1.1.1 2>&1 | tail -2

  echo; echo '=== 2. ДОСТУПНОСТЬ ВТОРОГО СЕРВЕРА (замените IP и порт!)'
  # ping -c2 -W3 <IP_ВТОРОГО>; timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<IP_ВТОРОГО>/<ПОРТ>' && echo TCP_OPEN || echo TCP_CLOSED

  echo; echo '=== 3. КОНТЕЙНЕРЫ И ОБРАЗЫ'
  docker ps -a 2>&1
  docker images 2>&1 | grep -iE 'remna|xray|node' | head -5

  echo; echo '=== 4. СЛУШАЮЩИЕ ПОРТЫ'
  ss -tulnp 2>&1 | head -40

  echo; echo '=== 5. ФАЕРВОЛ'
  ufw status verbose 2>&1 | head -30
  iptables -S 2>&1 | head -40

  echo; echo '=== 6. ЛОГИ НОДЫ (последние 100 строк)'
  docker logs --tail 200 remnanode 2>&1 | tail -100

  echo; echo '=== 7. XRAY CONFIG НА НОДЕ'
  docker exec remnanode sh -c 'cat /usr/local/etc/xray/config.json 2>/dev/null' 2>/dev/null \
    || find / -maxdepth 6 -name config.json -path '*xray*' -exec cat {} + 2>/dev/null

  echo; echo '=== 8. ВЕРСИЯ XRAY'
  docker exec remnanode sh -c 'xray version' 2>/dev/null | head -2

  echo; echo '=== 9. ЧАСЫ'
  date -u
} 2>&1 | sed -E \
  -e 's/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/UUID_XXX/g' \
  -e 's/("(privateKey|publicKey|password|secretKey|secret_key|shortId|shortIds)"[[:space:]]*:[[:space:]]*")[^"]*/\1XXX/g' \
  -e 's/((PASSWORD|SECRET_KEY|TOKEN|API_TOKEN|JWT)[=:][[:space:]]*)[^[:space:]]+/\1XXX/g'
