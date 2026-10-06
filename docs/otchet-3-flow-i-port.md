# Отчёт №3 — порт открыт, найден нюанс с flow, следующий тест

Продолжение. Сервер: 13.143.164.175 (Helsinki, FI), нода Remnawave, Xray v26.7.28.

---

## 1. Порт 8443 открыт из интернета — проверил независимо

Внешняя проверка TCP-подключения к `13.143.164.175:8443` с 6 точек мира:

**https://check-host.net/check-report/4f53ba0fk855**

| Узел | Результат |
|---|---|
| Гонконг | Connected (1.29 с) |
| Индия, Мумбаи | Connected (0.20 с) |
| Израиль, Тель-Авив | Connected (0.12 с) |
| Сингапур | Connected (0.22 с) |
| Швейцария, Цюрих | Connected (0.04 с) |
| США, Даллас | Connected (0.14 с) |

**Вывод:** инбаунд Reality доступен снаружи, фаервол не мешает. Отсюда: проблема не в «сервер недоступен»,
а в параметрах/протоколе на стороне клиента.

---

## 2. Найден важный нюанс: `flow` в вашем профиле

В вашем конфиге:

```json
"settings": {
  "clients": [ ... ],
  "decryption": "none",
  "flow": "xtls-rprx-vision"     <-- вот тут
}
```

По исходникам Xray (`infra/conf/vless.go`) этот `flow` **применяется ко ВСЕМ инжектируемым пользователям**:

```go
switch account.Flow {
case "":
    account.Flow = c.Flow   // если у пользователя нет своего flow — берётся из settings
...
```

А в `proxy/vless/inbound/inbound.go`:

```go
switch requestAddons.Flow {
case vless.XRV:
    if account.Flow == requestAddons.Flow { ...ok... }
    else { return errors.New("account ... is not able to use the flow xtls-rprx-vision") }
case "":
    if account.Flow == vless.XRV && request.Command == TCP {
        return errors.New("account ... is rejected since the client flow is empty ...")
    }
}
```

**Практический смысл:**

| Что в ссылке клиента | Что делает сервер |
|---|---|
| `flow=xtls-rprx-vision` | ✅ пускает |
| без `flow` | ❌ отклоняет: «client flow is empty» |

Причём в панели Remnawave для Reality/TLS-инбаундов `flow: xtls-rprx-vision` ставится **по умолчанию**
(обсуждение на форуме Remnawave: https://f.docs.rw/t/topic/337 — чтобы отключить, надо явно задать `"flow": ""`).

**Вывод:** ссылка клиента ОБЯЗАНА содержать `flow=xtls-rprx-vision`. Проверьте в панели Host:
если из-за CDN/адреса флоу теряется или ссылка собирается без него — Reality будет «подключаться, но без интернета».

---

## 3. Про CDN — главный подозреваемый

Reality **не работает через Cloudflare-прокси (оранжевое облако)**: CDN терминирует TLS и не проксирует голый TCP.
Если Host для Reality-инбаунда указывает на CDN-домен (порт 443 → Caddy на этом сервере), клиент попадает
не в Reality, а в Caddy/Cloudflare. Shadowsocks при этом работает, потому что его Host, скорее всего,
указывает на IP напрямую — отсюда «SS работает, Reality нет».

**Что должно быть у Reality-Host в панели:**
- Address: `13.143.164.175` или домен в режиме **DNS-only (серое облако)**
- Port: **8443**
- SNI: `www.microsoft.com`
- Flow: `xtls-rprx-vision`

---

## 4. Следующий тест: реальный xray-клиент на самом сервере

Скрипт `realtest.sh` (лежит в этой же папке) поднимает внутри контейнера `remnanode` временный
xray-клиент и ходит через `127.0.0.1:8443` в интернет — то есть повторяет путь клиента, но без клиента.
Показывает точную ошибку Xray при отказе.

```bash
curl -fsSL https://raw.githubusercontent.com/zavikcfg-sketch/lit/arena/ce75106c-lit/docs/realtest.sh -o /root/realtest.sh && bash /root/realtest.sh 2>&1 | tee /root/realtest.txt
```

Что смотреть в выводе:
- «ТЕСТ withflow» → если `ipinfo.io` вернул JSON — конфиг/ключи верны, дело в клиенте или его сети.
- «ТЕСТ noflow» → должен упасть с `client flow is empty` (это нормально и подтверждает теорию из §2).
- Секция «ЛОГ НОДЫ» → покажет `accepted` / `rejected` с причиной.

---

## 5. Проверки на стороне клиента (Windows)

```powershell
Test-NetConnection 13.143.164.175 -Port 8443
Test-NetConnection 13.143.164.175 -Port 1234
```

Ожидание: `TcpTestSucceeded : True` для обоих. Если 8443 — False, а 1234 — True, значит порт режет
провайдер клиента (тогда тест с мобильного интернета покажет то же).

Плюс нужен **лог клиента** (v2rayN: вкладка «Логи» / Hiddify: Logs) — там будет точная причина
(`reality: invalid public key`, `client flow is empty`, `timeout` и т.п.).

---

## 6. Что прислать

1. Вывод `realtest.sh` (файл `/root/realtest.txt`).
2. Вывод `Test-NetConnection` (оба порта) + название и версию клиента, что он показывает.
3. Ссылку из подписки (`vless://...`) с заменённым UUID на XXX.
4. Скрин/значения Host в панели: **Address / Port / SNI / поток (flow)**.
