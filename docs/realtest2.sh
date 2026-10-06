#!/usr/bin/env bash
# realtest2.sh — ИЗОЛИРОВАННЫЙ тест REALITY на самом сервере.
#
# Что делает: поднимает в контейнере remnanode СВОЙ временный xray-сервер (на других портах)
# и СВОЙ временный xray-клиент, и проверяет связку локально. Конфиг ноды НЕ трогает.
#
# Это отделяет два разных диагноза:
#   • «Reality сломан в принципе на этой машине»  → тогда виновато окружение/nft/сборка;
#   • «нода отдаёт клиентам неверные параметры или в ней нет юзера» → тогда окружение в порядке.
#
# Запуск от root:  bash realtest2.sh 2>&1 | tee /root/realtest2.txt
set +e

C=remnanode
X=/usr/local/bin/xray
U=ec894075-6131-48f9-b924-d32d080b1b90
NODE_PRIV=qGh3tCPA0vDT7vB7oXqn-1m7ltqfVXwERjDHlXD-nEY
NODE_PBK=gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA
NODE_SID=4bce9acaa879ed1e
SNI=www.microsoft.com

hr() { echo; echo "=============================================================="; echo " $*"; echo "=============================================================="; }

kill_test() {
  docker exec $C sh -c 'for p in /proc/[0-9]*; do if grep -qa "rwtest-" "$p/cmdline" 2>/dev/null; then kill "${p#/proc/}" 2>/dev/null; fi; done' 2>/dev/null
  sleep 0.4
}

# ------------------------------------------------------------------
hr "0. Xray и реально запущенные процессы"
docker exec $C $X version 2>&1 | head -2
echo "--- процессы xray в контейнере:"
docker exec $C sh -c 'for d in /proc/[0-9]*; do if [ -r "$d/cmdline" ] && tr "\0" " " < "$d/cmdline" 2>/dev/null | grep -qa xray; then echo "PID ${d#/proc/}: $(tr "\0" " " < "$d/cmdline")"; fi; done' 2>&1

hr "1. Где нода держит конфиг xray (служебные файлы s6)"
docker exec $C sh -c 'ls -la /run/service/ 2>/dev/null; echo "--- xray service:"; ls -la /run/service/xray/ 2>/dev/null; echo "--- run-скрипт:"; cat /run/service/xray/run 2>/dev/null' 2>&1 | head -50

hr "2. Файлы логов xray внутри контейнера"
docker exec $C sh -c 'ls -la /var/log 2>/dev/null; echo ---; ls -la /var/log/xray 2>/dev/null; echo ---; find / -maxdepth 4 -type f -name "*.log" 2>/dev/null | head -20' 2>&1 | head -40

hr "3. Свежая пара ключей (для чистого теста)"
OUT=$(docker exec $C $X x25519 2>&1)
echo "$OUT"
PRIV=$(printf '%s\n' "$OUT" | grep -i 'PrivateKey' | grep -oE '[A-Za-z0-9_-]{43}' | head -1)
PUB=$(printf '%s\n' "$OUT" | grep -i 'PublicKey'  | grep -oE '[A-Za-z0-9_-]{43}' | head -1)
if [ -z "$PRIV" ] || [ -z "$PUB" ]; then
  echo "!!! не удалось разобрать ключи, беру ключи ноды"
  PRIV=$NODE_PRIV; PUB=$NODE_PBK
fi
echo "PRIV=$PRIV"; echo "PUB=$PUB"

# ------------------------------------------------------------------
mk_server() { # $1 port  $2 privkey  $3 shortid  $4 settings-json
  local port="$1" priv="$2" sid="$3" settings="$4" file="/tmp/rwtest-srv-$1.json"
  cat > "$file" <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "tag": "rwtest-in",
    "listen": "127.0.0.1",
    "port": $port,
    "protocol": "vless",
    "settings": $settings,
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "dest": "www.microsoft.com:443",
        "show": false,
        "xver": 0,
        "shortIds": ["$sid"],
        "privateKey": "$priv",
        "serverNames": ["$SNI"]
      }
    }
  }],
  "outbounds": [ { "tag": "DIRECT", "protocol": "freedom" } ]
}
EOF
  docker cp "$file" "$C:$file" >/dev/null 2>&1
  echo "$file"
}

mk_client() { # $1 name  $2 socks-port  $3 target-port  $4 pbk  $5 sid  $6 flow-snippet(если нужен)
  local name="$1" sock="$2" tport="$3" pbk="$4" sid="$5" flow="$6"
  local file="/tmp/rwtest-cli-$name.json"
  cat > "$file" <<EOF
{
  "log": { "loglevel": "debug", "error": "/tmp/rwtest-cli-$name.log" },
  "inbounds": [ { "tag": "socks", "listen": "127.0.0.1", "port": $sock, "protocol": "socks",
                  "settings": { "auth": "noauth", "udp": false } } ],
  "outbounds": [ {
    "tag": "proxy", "protocol": "vless",
    "settings": { "vnext": [ { "address": "127.0.0.1", "port": $tport,
      "users": [ { "id": "$U", "encryption": "none"$flow } ] } ] },
    "streamSettings": { "network": "tcp", "security": "reality",
      "realitySettings": { "fingerprint": "chrome", "serverName": "$SNI",
        "publicKey": "$pbk", "shortId": "$sid", "spiderX": "/" } } } ]
}
EOF
  docker cp "$file" "$C:$file" >/dev/null 2>&1
  echo "$file"
}

run_test() { # $1 заголовок  $2 server-file(может быть пусто)  $3 client-file  $4 socks-port  $5 tag
  local title="$1" srv="$2" cli="$3" sock="$4" tag="$5"
  hr "$title"
  kill_test
  if [ -n "$srv" ]; then docker exec -d $C $X run -c "$srv"; fi
  docker exec -d $C $X run -c "$cli"
  sleep 1.5
  echo "--- ipinfo.io через туннель:"
  timeout 15 curl -sS --max-time 12 -x "socks5h://127.0.0.1:$sock" https://ipinfo.io/json 2>&1 | head -12
  echo "--- последние строки лога клиента:"
  docker exec $C sh -c "tail -n 18 /tmp/rwtest-cli-$tag.log 2>/dev/null" 2>&1
  kill_test
}

# ------------------------------------------------------------------
hr "4. МАТРИЦА: свои сервер+клиент, локально"

SID="0011223344556677"
# как у ноды: flow на уровне settings
SF1='{"clients":[{"id":"'"$U"'","email":"t"}],"decryption":"none","flow":"xtls-rprx-vision"}'
# flow у каждого пользователя
SF2='{"clients":[{"id":"'"$U"'","email":"t","flow":"xtls-rprx-vision"}],"decryption":"none"}'
# без flow вообще
SF3='{"clients":[{"id":"'"$U"'","email":"t"}],"decryption":"none"}'

S1=$(mk_server 9443 "$PRIV" "$SID" "$SF1")
S2=$(mk_server 9444 "$PRIV" "$SID" "$SF2")
S3=$(mk_server 9445 "$PRIV" "$SID" "$SF3")

C1=$(mk_client flow    11081 9443 "$PUB" "$SID" ',"flow":"xtls-rprx-vision"')
C2=$(mk_client noflow  11082 9443 "$PUB" "$SID" '')
C3=$(mk_client flow2   11083 9444 "$PUB" "$SID" ',"flow":"xtls-rprx-vision"')
C4=$(mk_client noflow2 11084 9445 "$PUB" "$SID" '')

run_test "4a. flow в settings (как у ноды) + клиент С flow"      "$S1" "$C1" 11081 flow
run_test "4b. flow в settings (как у ноды) + клиент БЕЗ flow"    "$S1" "$C2" 11082 noflow
run_test "4c. flow у пользователя + клиент С flow"               "$S2" "$C3" 11083 flow2
run_test "4d. без flow вообще + клиент БЕЗ flow"                 "$S3" "$C4" 11084 noflow2

hr "5. Ключи из конфига НОДЫ против инбаунда ноды (8443)"
CN=$(mk_client nodekeys 11085 8443 "$NODE_PBK" "$NODE_SID" ',"flow":"xtls-rprx-vision"')
run_test "5. нода: 8443, pbk/sid из дампа, клиент с flow" "" "$CN" 11085 nodekeys

# ------------------------------------------------------------------
hr "6. nftables: что может дропать трафик"
nft list ruleset > /root/nft-dump.txt 2>&1
echo "сохранено: /root/nft-dump.txt (строк: $(wc -l < /root/nft-dump.txt 2>/dev/null))"
grep -n -iE '8443|drop|reject' /root/nft-dump.txt 2>/dev/null | head -30

hr "7. Сырой лог контейнера ноды за 5 минут"
docker logs --since 5m $C > /root/node-log-last.txt 2>&1
echo "сохранено: /root/node-log-last.txt (строк: $(wc -l < /root/node-log-last.txt 2>/dev/null))"
grep -a -iE 'accepted|rejected|reality|vless|vision|flow|fallback|EOF|dial' /root/node-log-last.txt 2>/dev/null | tail -30

hr "ГОТОВО"
kill_test
docker exec $C sh -c 'rm -f /tmp/rwtest-*' 2>/dev/null
cat <<'EOT'
Как читать результат:

  • 4a/4c/4d = ipinfo показал IP сервера  → Reality на этой машине работает,
    а 5 (нода) упал                      → нода отдаёт клиентам неверные параметры
                                            (ключи/SNI/shortId) или в её конфиге нет юзера.
  • 4a упал, 4c/4d прошли                 → проблема именно в схеме «flow в settings» (как в профиле ноды) —
                                            надо перенести flow к пользователям/в Host.
  • упали ВСЕ 4a–4d                       → дело не в параметрах, а в окружении
                                            (nft-дропы / сборка xray) → смотрите /root/nft-dump.txt.

Пришлите весь вывод + файлы /root/nft-dump.txt и /root/node-log-last.txt.
EOT
