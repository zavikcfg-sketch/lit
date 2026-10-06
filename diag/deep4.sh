#!/bin/bash
# deep4.sh — финальная диагностика VLESS-Reality (remnanode, Remnawave 3.4)
# Запуск: bash /tmp/deep4.sh   (скачивание: curl -fsSL <raw-url> -o /tmp/deep4.sh)
echo ">>> DEEP4-FINAL <<< (если этой строки нет первой в выводе — запущен старый скрипт)"
rm -f /tmp/deep.sh /tmp/deep2.sh /tmp/deep3.sh
E="docker exec remnanode"

# Убить тестовые клиенты прошлых прогонов
$E sh -c 'for d in /proc/[0-9]*/cmdline; do if grep -qaE "clA.json|cl.json|cl8444|srv8444" "$d" 2>/dev/null; then kill "$(basename "$(dirname "$d")")" 2>/dev/null; fi; done' 2>/dev/null
sleep 1

echo ""
echo "=========== БЛОК 1. Боевой конфиг ноды: кто в VLESS ==========="
CFGP=$($E sh -c 'for d in /proc/[0-9]*/cmdline; do if grep -qa xray "$d" 2>/dev/null; then tr "\0" "\n" < "$d" | grep "\.json" | grep -vE "cl8444|clA|srv8444" | head -1; fi; done' | head -1)
echo "путь конфига: ${CFGP:-НЕ НАЙДЕН}"
if [ -n "$CFGP" ]; then
  $E cat "$CFGP" > /tmp/nodeconfig.json 2>/dev/null
  python3 - <<'PY'
import json
try:
    c = json.load(open("/tmp/nodeconfig.json"))
except Exception as e:
    print("не прочитан:", e); raise SystemExit
print("log:", c.get("log"))
for ib in c.get("inbounds", []):
    if ib.get("protocol") != "vless":
        continue
    rs = (ib.get("streamSettings") or {}).get("realitySettings") or {}
    print("INBOUND:", ib.get("tag"), ib.get("port"))
    print("  privateKey:", str(rs.get("privateKey"))[:6], "| serverNames:", rs.get("serverNames"), "| shortIds:", rs.get("shortIds"), "| dest:", rs.get("dest") or rs.get("target"))
    cl = (ib.get("settings") or {}).get("clients", [])
    print("  КЛИЕНТОВ:", len(cl))
    for x in cl:
        print("   - id:", x.get("id"), "| email:", x.get("email"), "| flow:", x.get("flow"))
PY
else
  echo "(конфиг не найден через /proc, смотрим типовые пути)"
  $E sh -c 'ls /etc/xray /tmp 2>/dev/null | head -20'
fi

echo ""
echo "=========== БЛОК 2. Чистый Reality на 8444 в обход панели (решающий тест) ==========="
KP=$($E xray x25519)
PRIV=$(echo "$KP" | grep "Private key:" | head -1 | awk '{print $3}')
PUB=$(echo "$KP" | grep "Public key:" | head -1 | awk '{print $3}')
SID=$(openssl rand -hex 8)
echo "свежие ключи: priv=$(echo "$PRIV" | head -c 6)... pub=$(echo "$PUB" | head -c 6)... sid=$SID"
if [ -z "$PRIV" ] || [ -z "$PUB" ]; then
  echo "ОШИБКА генерации ключей: $KP"
else
  cat > /tmp/srv8444.json <<J
{"log":{"loglevel":"debug"},"inbounds":[{"tag":"r","listen":"127.0.0.1","port":8444,"protocol":"vless","settings":{"clients":[{"id":"ec894075-6131-48f9-b924-d32d080b1b90","flow":"xtls-rprx-vision"}],"decryption":"none"},"sniffing":{"enabled":true,"destOverride":["http","tls","quic"]},"streamSettings":{"network":"tcp","security":"reality","realitySettings":{"dest":"www.microsoft.com:443","serverNames":["www.microsoft.com"],"privateKey":"$PRIV","shortIds":["$SID"]}}}],"outbounds":[{"protocol":"freedom"}]}
J
  cat > /tmp/cl8444.json <<J
{"inbounds":[{"tag":"s","listen":"127.0.0.1","port":10896,"protocol":"socks","settings":{"auth":"noauth"}}],"outbounds":[{"protocol":"vless","settings":{"vnext":[{"address":"127.0.0.1","port":8444,"users":[{"id":"ec894075-6131-48f9-b924-d32d080b1b90","flow":"xtls-rprx-vision","encryption":"none"}]}]},"streamSettings":{"network":"tcp","security":"reality","realitySettings":{"serverName":"www.microsoft.com","fingerprint":"chrome","publicKey":"$PUB","shortId":"$SID","spiderX":"/"}}}]}
J
  docker cp /tmp/srv8444.json remnanode:/tmp/srv8444.json
  docker cp /tmp/cl8444.json remnanode:/tmp/cl8444.json
  docker exec -d remnanode sh -c 'xray run -c /tmp/srv8444.json > /tmp/srv8444.log 2>&1'
  docker exec -d remnanode sh -c 'xray run -c /tmp/cl8444.json > /tmp/cl8444.log 2>&1'
  sleep 3
  curl -s --socks5-hostname 127.0.0.1:10896 -m 12 -o /dev/null -w "microsoft: HTTP %{http_code}\n" https://www.microsoft.com/
  curl -s --socks5-hostname 127.0.0.1:10896 -m 12 -o /dev/null -w "whoer:     HTTP %{http_code}\n" https://whoer.net/
  echo "--- лог клиента 8444 (хвост) ---"
  $E sh -c 'tail -6 /tmp/cl8444.log' 2>/dev/null
  echo "--- лог сервера 8444 (хвост) ---"
  $E sh -c 'tail -10 /tmp/srv8444.log' 2>/dev/null
fi

echo ""
echo "=========== БЛОК 3. Повтор теста панельного 8443 ==========="
cat > /tmp/clA.json <<'J'
{"inbounds":[{"tag":"s","listen":"127.0.0.1","port":10899,"protocol":"socks","settings":{"auth":"noauth"}}],"outbounds":[{"protocol":"vless","settings":{"vnext":[{"address":"127.0.0.1","port":8443,"users":[{"id":"ec894075-6131-48f9-b924-d32d080b1b90","flow":"xtls-rprx-vision","encryption":"none"}]}]},"streamSettings":{"network":"tcp","security":"reality","realitySettings":{"serverName":"www.microsoft.com","fingerprint":"chrome","publicKey":"gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA","shortId":"4bce9acaa879ed1e","spiderX":"/"}}}]}
J
docker cp /tmp/clA.json remnanode:/tmp/clA.json
docker exec -d remnanode sh -c 'xray run -c /tmp/clA.json > /tmp/clA.log 2>&1'
sleep 3
curl -s --socks5-hostname 127.0.0.1:10899 -m 12 -o /dev/null -w "microsoft: HTTP %{http_code}\n" https://www.microsoft.com/
curl -s --socks5-hostname 127.0.0.1:10899 -m 12 -o /dev/null -w "whoer:     HTTP %{http_code}\n" https://whoer.net/
echo "--- лог клиента 8443 (хвост) ---"
$E sh -c 'tail -8 /tmp/clA.log' 2>/dev/null

echo ""
echo "=========== БЛОК 4. Лог ноды за 5 мин (debug, без фильтра) ==========="
docker logs --since 5m remnanode 2>&1 | tail -50

$E sh -c 'for d in /proc/[0-9]*/cmdline; do if grep -qaE "clA.json|cl8444|srv8444" "$d" 2>/dev/null; then kill "$(basename "$(dirname "$d")")" 2>/dev/null; fi; done' 2>/dev/null

echo ""
echo "=========== БЛОК 5. Панель: юзеры на ноде и админ ==========="
python3 - <<'PY'
import json, urllib.request, re
env = open("/opt/vpnbot/vpn-bot/.env").read()
tok = re.search(r"^REMNAWAVE_API_TOKEN=(\S+)", env, re.M).group(1)
H = {"Authorization": "Bearer " + tok}
B = "https://panel.litenergyapp.store"
def get(u):
    r = urllib.request.Request(B + u, headers=H)
    return json.load(urllib.request.urlopen(r, timeout=15))
try:
    data = get("/api/nodes")
    rows = data if isinstance(data, list) else data.get("response", data)
    if isinstance(rows, dict):
        rows = rows.get("rows", [])
    for n in rows:
        print("НОДА:", n.get("name"), "| alive:", n.get("isNodeAlive"), "| ver:", n.get("version"))
        try:
            nu = get("/api/nodes/%s/users" % n["uuid"])
            r2 = nu.get("response", nu) if isinstance(nu, dict) else nu
            lst = r2 if isinstance(r2, list) else (r2.get("users") or r2.get("rows") or [])
            print("  пушено юзеров:", len(lst))
            for u in lst:
                print("   -", u.get("uuid"), "|", u.get("shortUuid"), "|", u.get("username"), "|", u.get("status"))
        except Exception as e:
            print("  users-by-node:", e)
except Exception as e:
    print("ноды:", e)
try:
    a = get("/api/users/by-username/tg_8346538289")
    a = a.get("response", a) if isinstance(a, dict) else a
    print("АДМИН uuid:", a.get("uuid"), "| status:", a.get("status"))
    print("  ожидали: ec894075-6131-48f9-b924-d32d080b1b90")
except Exception as e:
    print("админ:", e)
PY

echo ""
echo "=========== БЛОК 6. nftables (плагины ноды) ==========="
nft list ruleset 2>/dev/null | wc -l
nft list ruleset 2>/dev/null | grep -iE "8443|1234" | head -8
echo ">>> DEEP4 ЗАВЕРШЁН <<<"
