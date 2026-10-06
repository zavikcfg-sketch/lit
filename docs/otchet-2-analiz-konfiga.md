# Отчёт №2 — анализ живого конфига ноды

Дата: 2026-10-06 · Нода: `pwr-s2587` · 13.143.164.175 (Helsinki, FI)

---

## 1. Что реально запущено (из `cli --dump-config`)

| Инбаунд | Порт | Протокол | Особенности |
|---|---|---|---|
| `Shadowsocks` | 1234 | shadowsocks | chacha20-ietf-poly1305, 2 клиента (id 7, id 8) |
| `VLESS-Reality-8443` | 8443 | vless | `network: tcp`, `security: reality`, `dest: www.microsoft.com:443`, `serverNames: [www.microsoft.com]`, shortId `4bce9acaa879ed1e`, privateKey `XXX` |

**Outbounds: только `DIRECT` (freedom) и `BLOCK` (blackhole).**
**Routing: только служебное правило REMNAWAVE_API_INBOUND.**

### Что из этого следует

1. **Никакого «моста» на второй сервер в конфиге нет.** Весь клиентский трафик уходит в интернет
   напрямую с этого сервера. Второй сервер сейчас **не используется вообще**.
2. **Интернет у сервера есть** (проверено: ipinfo → Helsinki, google 200, ping 1.1.1.1 ок).
   Значит серверная часть цепочки «клиент → Reality → интернет» полностью рабочая.
3. Значит «Reality без интернета» — это проблема на стыке **ссылка/подписка ↔ клиент ↔ досягаемость порта**,
   а не «серверу некуда ходить».

---

## 2. Публичный ключ (выведен из privateKey)

Из `privateKey` конфига выведен соответствующий ему публичный ключ:

```
pbk = gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA
```

Это тот `pbk`, который **обязан** быть в ссылке клиента. Сверьте его с полем `Public Key` в панели
(в карточке инбаунда/хоста). Если в панели другое значение — у всех клиентов в ссылке неверный ключ,
и Reality не подключится ни при каких условиях (это одна из самых частых причин «Reality не работает»).

---

## 3. Что проверять в первую очередь (по убыванию вероятности)

1. **Адрес и порт в Host'е панели.**
   - Порт должен быть **8443**. Если там 443 — клиенты стучатся в Caddy, а не в Reality.
   - Address должен быть **IP `13.143.164.175`** или домен, который резолвится в этот IP **напрямую**
     (DNS-only / «серое облако»). Если домен спрятан за Cloudflare-прокси (оранжевое облако) —
     Reality через него не пройдёт никогда (CDN терминирует TLS и не проксирует голый TCP).
2. **SNI.** В ссылке должно быть `sni=www.microsoft.com` — ровно как в `serverNames` конфига.
   Если в Host'е в Advanced Options переопределён SNI на свой домен — клиент не пройдёт handshake.
3. **`pbk` / `sid`.** См. §2 и `shortId` из конфига.
4. **Flow.** В живом конфиге у пользователей `flow` не указан (он лежит на уровне `settings`, где Xray
   его не читает). Поэтому нужно эмпирически проверить, какой вариант ссылки рабочий: **с**
   `flow=xtls-rprx-vision` и **без** него. Тестовые ссылки — §4.

---

## 4. Тестовые ссылки (собраны вручную по конфигу)

Проверить в клиенте, отключив всё лишнее. Значения UUID взяты из дампа (id 7 / id 8).

**Reality, 8443, с flow:**
```
vless://<UUID_7>@13.143.164.175:8443?type=tcp&security=reality&encryption=none&pbk=gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA&fp=chrome&sni=www.microsoft.com&sid=4bce9acaa879ed1e&flow=xtls-rprx-vision#TEST-8443-withflow
```

**Reality, 8443, без flow:**
```
vless://<UUID_7>@13.143.164.175:8443?type=tcp&security=reality&encryption=none&pbk=gPffJOlscdEQtDKcW38MwW85HNxkV1AdElq5Ph_ZZxA&fp=chrome&sni=www.microsoft.com&sid=4bce9acaa879ed1e#TEST-8443-noflow
```

**Shadowsocks, 1234 (проверка, что сервер вообще выпускает в интернет):**
```
ss://<base64(method:password_7)>@13.143.164.175:1234#TEST-SS-user7
```

**Логика выводов:**
- SS работает, Reality — нет → проблема изолирована в Reality-параметрах (порт/SNI/ключ/flow/CDN).
- Работает «без flow», не работает «с flow» → панель выдаёт клиентам ссылку с vision, которого нет на сервере
  (лечится приведением профиля в порядок: flow должен стоять внутри каждого клиента, а не в `settings`).
- Не работает ни один вариант → смотреть Host/порт/CDN (п.3.1).

---

## 5. Команды на сервере (проверка Reality-инбаунда локально)

```bash
# 1) доступен ли target для Reality (он должен быть доступен: handshake идёт через него)
curl -sS -o /dev/null -w 'microsoft: %{http_code}\n' --max-time 8 https://www.microsoft.com/

# 2) локальная проверка самого инбаунда: «чужой» клиент должен получить настоящий microsoft
curl -s -o /dev/null -w 'reality-relay: %{http_code}\n' --max-time 10 \
  --resolve www.microsoft.com:8443:127.0.0.1 https://www.microsoft.com:8443/

# 3) логи во время попытки подключения клиента
docker logs -f --tail 20 remnanode 2>&1 | grep -iE 'vless|reality|vision|flow|invalid|reject|accepted|refused|dial|timeout'
```

Ожидаемое поведение в п.2: Reality отдаёт настоящий сертификат microsoft (код 200/301/302).
Если пусто/ошибка — инбаунд не релеит на target, это уже отдельная поломка на сервере.

---

## 6. Безопасность — важно

В чате засветились **приватный ключ Reality, UUID пользователей и пароли Shadowsocks**.
Рекомендую после починки:
1. Перегенерировать ключи Reality (privateKey/publicKey + shortIds) и обновить Host в панели.
2. Перевыпустить UUID пользователей и пароли SS.
3. Не коммитить эти значения в файлы репозитория — он **публичный**.
