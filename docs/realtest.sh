#!/usr/bin/env bash
# realtest.sh — проверяет Reality-инбаунд «как будто мы клиент», прямо с этого же сервера.
# Ничего в конфиге ноды не меняет: поднимает временный xray-клиент внутри контейнера remnanode
# и ходит через 127.0.0.1:8443 в интернет. Показывает точную ошибку, если подключение отклонено.
#
# Запуск от root:  bash realtest.sh
set +e

C=remnanode
HOST=127.0.0.1
PORT=8443
UUID=ec894075-6131-48f9-b924-d32d080b1b90
PBK=gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA
SID=4bce9acaa879ed1e
SNI=www.microsoft.com
SOCK=11080
PRIV=qGh3tCPA0vDT7vB7oXqn-1m7ltqfVXwERjDHlXD-nEY

echo "=============================================================="
echo " ТЕСТ 0: xray в контейнере"
echo "=============================================================="
docker exec $C /usr/local/bin/xray version 2>&1 | head -2

echo
echo "=============================================================="
echo " ТЕСТ 1: публичный ключ, выведенный из private key конфига"
echo "         (сравните с PBK=$PBK)"
echo "=============================================================="
docker exec $C /usr/local/bin/xray x25519 -i "$PRIV" 2>&1 | head -4

stop_test() {
  docker exec $C sh -c 'for p in /proc/[0-9]*; do if grep -qa rwtest "$p/cmdline" 2>/dev/null; then kill "${p#/proc/}" 2>/dev/null; fi; done' 2>/dev/null
  sleep 0.5
}

write_cfg() { # $1 = имя файла, $2 = кусок json с flow (может быть пустым)
  cat > "/tmp/$1" <<EOF
{
  "log": { "loglevel": "debug", "error": "/tmp/$1.log" },
  "inbounds": [
    { "tag": "socks-in", "listen": "127.0.0.1", "port": $SOCK, "protocol": "socks",
      "settings": { "auth": "noauth", "udp": false } }
  ],
  "outbounds": [
    { "tag": "proxy", "protocol": "vless",
      "settings": { "vnext": [ { "address": "$HOST", "port": $PORT,
        "users": [ { "id": "$UUID", "encryption": "none"$2 } ] } ] },
      "streamSettings": { "network": "tcp", "security": "reality",
        "realitySettings": { "fingerprint": "chrome", "serverName": "$SNI",
          "publicKey": "$PBK", "shortId": "$SID", "spiderX": "/" } } }
  ]
}
EOF
}

test_one() { # $1 = короткое имя, $2 = json-кусок flow
  local name="$1" snippet="$2" file="rwtest-$1.json"
  echo
  echo "=============================================================="
  echo " ТЕСТ [$name]  flow=${snippet:-<НЕ ИСПОЛЬЗУЕТСЯ>}"
  echo "=============================================================="
  stop_test
  write_cfg "$file" "$snippet"
  docker cp "/tmp/$file" "$C:/tmp/$file" >/dev/null 2>&1
  docker exec -d $C /usr/local/bin/xray run -c "/tmp/$file"

  local ok=0
  for i in 1 2 3 4 5; do
    sleep 1
    if docker exec $C sh -c "test -s /tmp/$file.log" 2>/dev/null; then ok=1; break; fi
  done
  [ "$ok" = "0" ] && echo "!!! клиент не запустился (нет лог-файла)"

  echo "--- ответ https://ipinfo.io/json через туннель:"
  timeout 15 curl -sS --max-time 12 -x "socks5h://127.0.0.1:$SOCK" https://ipinfo.io/json 2>&1 | head -14

  echo "--- лог временного клиента:"
  docker exec $C sh -c "tail -n 25 /tmp/$file.log 2>/dev/null" | sed -E 's/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/UUID_XXX/g'

  stop_test
  docker exec $C rm -f "/tmp/$file" "/tmp/$file.log" >/dev/null 2>&1
}

test_one withflow ',"flow":"xtls-rprx-vision"'
test_one noflow ''

echo
echo "=============================================================="
echo " ЛОГ НОДЫ за последние 2 минуты (что сервер думает о подключениях)"
echo "=============================================================="
docker logs --since 2m $C 2>&1 \
  | grep -a -iE 'accepted|rejected|not able to use|client flow is empty|vision|reality|invalid' \
  | tail -25

echo
echo "=============================================================="
echo " ГОТОВО. Ключевое:"
echo "  • «ТЕСТ withflow» прошёл (ipinfo показал IP сервера) → конфиг и ключи верные,"
echo "    проблема в клиенте/сети клиента."
echo "  • «ТЕСТ noflow» упал с 'client flow is empty' → так и должно быть при flow в settings."
echo "  • оба упали → смотрите текст ошибок выше и пришлите их мне."
echo "=============================================================="
