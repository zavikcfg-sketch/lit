# Диагностика связки Remnawave: Reality / CDN / второй сервер

Файл-чеклист: заполните то, что можете, и пришлите мне в чат (или прямо допишите ответы здесь —
файл в репозитории, я его вижу).

---

## 0. Сначала определимся со схемой

Есть 3 принципиально разных схемы, и «нет интернета» лечится по-разному:

| Схема | Как выглядит | Работает ли |
|---|---|---|
| **A.** Клиент → нода (Reality) → интернет | Нода сама является выходом | Только если у ноды есть свой выход в интернет |
| **B.** Клиент → нода (Reality) → второй сервер → интернет | Нода-RU как «мост», второй сервер как «выход» | Да, и это делается штатно в Remnawave (см. §4) |
| **C.** Клиент → CDN (Cloudflare) → нода → интернет | Reality спрятан за CDN | ❌ **Reality через обычный Cloudflare proxy не работает** (CDN терминирует TLS и не проксирует голый TCP). Через CDN живут только VLESS+WS / gRPC / XHTTP с TLS |

Важно: **если у ноды вообще нет исходящего трафика в интернет, она не сможет быть выходом** —
тогда вариант только B (или клиент должен подключаться сразу ко второму серверу).

---

## 0.1. Быстрый способ собрать всё сразу (1 команда)

В этой же папке лежит `collect-diag.sh` — он ничего не меняет, только читает и сам вычищает
секреты (UUID/ключи/пароли → XXX), а результат пишет в файл `remnawave-diag-*.txt`.

```bash
# вариант 1: файл уже есть в репозитории — скопируйте его на сервер и запустите от root:
bash collect-diag.sh <IP_ВТОРОГО_СЕРВЕРА> <ПОРТ_МОСТА>

# вариант 2: создать на сервере одной командой (вставьте и запустите, затем заберите файл):
nano collect-diag.sh    # вставьте содержимое docs/collect-diag.sh, сохраните (Ctrl+O, Ctrl+X)
bash collect-diag.sh <IP_ВТОРОГО_СЕРВЕРА> <ПОРТ_МОСТА>
```

Затем пришлите мне полученный txt. Если хотите — можно и вручную, по пунктам ниже.

---

## 1. Данные с ноды, где Reality («без интернета»)

Скопируйте вывод команд целиком:

```bash
# 1.1 есть ли у сервера/ноды выход в интернет вообще
curl -sS -m 8 https://ipinfo.io/json || echo "=== НЕТ ВЫХОДА В ИНТЕРНЕТ ==="
curl -sS -m 8 -o /dev/null -w 'google: %{http_code}\n' https://www.google.com
ping -c2 -W3 1.1.1.1
dig +short google.com @1.1.1.1

# 1.2 достаёт ли эта нода до ВТОРОГО сервера (подставьте IP и порт)
ping -c2 -W3 <IP_ВТОРОГО_СЕРВЕРА>
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<IP_ВТОРОГО_СЕРВЕРА>/<PORT>' && echo TCP_OPEN || echo TCP_CLOSED

# 1.3 состояние ноды Remnawave
sudo docker ps
sudo docker logs --tail 200 remnanode 2>&1 | grep -iE 'error|reality|handshake|dial|refused|timeout|permission'
sudo ss -tlnp | grep -E ':443|:2222|:9999'

# 1.4 ФАКТИЧЕСКИЙ конфиг, который сейчас крутится на ноде
sudo docker exec remnanode sh -c 'find / -maxdepth 5 -name "config.json" -path "*xray*" 2>/dev/null'
# и затем:
sudo docker exec remnanode cat <ПУТЬ_ИЗ_ПРЕДЫДУЩЕЙ_КОМАНДЫ>
```

Плюс из панели Remnawave: **Config Profiles → профиль, привязанный к этой ноде → View/JSON** — скопировать целиком.

---

## 2. Данные со второго сервера (который «обычный и с интернетом»)

```bash
curl -sS -m 8 https://ipinfo.io/json
sudo ss -tlnp
sudo ufw status verbose        # или: sudo iptables -S
# если это тоже нода Remnawave / отдельный Xray — показать его конфиг:
sudo docker ps
sudo cat /usr/local/etc/xray/config.json 2>/dev/null || sudo find / -maxdepth 5 -name 'config.json' -path '*xray*' 2>/dev/null
```

И ответьте:
- Чем он поднят: **нода Remnawave / отдельный Xray / 3x-ui / что-то ещё?**
- Какие на нём inbound'ы: протокол, порт, transport (raw/ws/grpc/xhttp), security (reality/tls/none)?
- Есть ли домен, проксирован ли он в Cloudflare (оранжевое облако) или серый DNS?
- Открыт ли порт inbound'а в фаерволе и в панели хостера?

---

## 3. Данные с клиента

- Приложение (v2rayNG / Hiddify / Streisand / Nekobox / sing-box …).
- Что видно при подключении: `timeout`, `handshake failed`, `connected`, но сайты не грузятся?
- Работает ли через эту же ноду второй (CDN/WS) конфиг — или тоже нет?
- Ссылка подписки/конфиг **с заменённым токеном и UUID на XXX** (только структура важна: vless://…@домен:443?security=reality&…).

---

## 4. Как это лечится (схема B — самая частая)

Reality-нода становится «мостом», а выход в интернет она получает от второго сервера.
Делается это **в Config Profile той ноды, где Reality** — в Remnawave это штатная функция
(«Server-Side Routing»): добавляем outbound на второй сервер + правило роутинга.

Шаблон (замените значения, inbound оставьте свой):

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "REALITY_IN",
      "port": 443,
      "listen": "0.0.0.0",
      "protocol": "vless",
      "settings": { "clients": [], "decryption": "none" },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] },
      "streamSettings": {
        "network": "raw",
        "security": "reality",
        "realitySettings": {
          "target": "ВАШ_TARGET:443",
          "show": false,
          "xver": 0,
          "shortIds": ["ВАШ_SHORT_ID"],
          "privateKey": "ВАШ_PRIVATE_KEY",
          "serverNames": ["ВАШ_SNI"]
        }
      }
    }
  ],
  "outbounds": [
    { "tag": "DIRECT", "protocol": "freedom" },
    { "tag": "BLOCK", "protocol": "blackhole" },

    {
      "tag": "TO_SERVER2",
      "protocol": "vless",
      "settings": {
        "vnext": [{
          "address": "IP_ВТОРОГО_СЕРВЕРА",
          "port": 443,
          "users": [{ "id": "UUID_МОСТА", "encryption": "none", "flow": "xtls-rprx-vision" }]
        }]
      },
      "streamSettings": {
        "network": "raw",
        "security": "reality",
        "realitySettings": {
          "serverName": "SNI_ВТОРОГО_СЕРВЕРА",
          "publicKey": "PBK_ВТОРОГО_СЕРВЕРА",
          "shortId": "SHORT_ID_ВТОРОГО",
          "fingerprint": "chrome"
        }
      }
    }
  ],
  "routing": {
    "rules": [
      { "type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK" },
      { "type": "field", "domain": ["geosite:private"], "outboundTag": "BLOCK" },
      { "type": "field", "protocol": ["bittorrent"], "outboundTag": "BLOCK" },
      { "type": "field", "inboundTag": ["REALITY_IN"], "outboundTag": "TO_SERVER2" }
    ]
  }
}
```

Упрощённый вариант «моста» (как в офдоках Remnawave — на Shadowsocks, меньше нагрузки):

```json
{ "tag": "TO_SERVER2", "protocol": "shadowsocks",
  "settings": { "servers": [{
    "address": "IP_ВТОРОГО_СЕРВЕРА", "port": 9999,
    "method": "chacha20-ietf-poly1305", "password": "ПАРОЛЬ_МОСТА" }] } }
```

**Чек-лист для схемы B:**
1. На втором сервере создан отдельный inbound для моста (напр. Shadowsocks на порту 9999,
   `"clients": []`) — и он **не** привязан к публичному Host, чтобы не светился в подписках.
2. Для моста создан отдельный пользователь в панели Remnawave; его UUID/пароль вписан в outbound.
3. Порт моста открыт в фаерволе второго сервера (ufw/iptables + панель хостера).
4. В профиль ноды добавлены outbound + правило роутинга, профиль сохранён и нода перезапущена.
5. Проверка: `ping` через туннель + `curl https://ipinfo.io` с клиента — должен показать IP **второго** сервера.

Ссылка на офдоки: https://docs.rw/learn/server-routing/

---

## 5. Шаблон ответа (заполните и пришлите)

```
[ ] Схема: A / B / C (или опишите своими словами)

Нода с Reality:
  - IP/домен, за CDN или напрямую:
  - вывод п.1.1:
  - вывод п.1.2:
  - вывод п.1.3:
  - JSON профиля (можно с XXX вместо ключей):

Второй сервер:
  - IP, чем поднят (Remnawave / Xray / 3x-ui):
  - inbound'ы (протокол/порт/transport/security):
  - вывод п.2:

Клиент:
  - приложение:
  - поведение при подключении:
  - конфиг (с XXX):
```
