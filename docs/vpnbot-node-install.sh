#!/usr/bin/env bash
# LitEnergy: установка ноды Remnawave на новый VPS. Версия 2026-10-07.1
#
# Что делает: ставит Docker, поднимает ноду (remnawave/node), открывает порты,
# проверяет, что нода запустилась и слушает порт панели.
#
# Запускать на НОВОМ сервере от root:
#   bash /root/node-install.sh "<SECRET_KEY_ИЗ_ПАНЕЛИ>" [ПОРТ_ПАНЕЛИ]
#
# SECRET_KEY берётся в панели: Ноды → создать ноду → скопировать Secret key.
# Порт панели по умолчанию 2222 — менять не нужно.

set -u

VERSION="node-install 2026-10-07.1"
DIR="/opt/remnanode"
IMAGE="remnawave/node:latest"

say()  { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }

say "$VERSION"

if [ "$(id -u)" != "0" ]; then
  say "!! запусти от root (или через sudo)"
  exit 1
fi

SECRET="${1:-}"
NODE_PORT="${2:-2222}"
SECRET="$(printf '%s' "$SECRET" | tr -d '\r\n\t ' | sed 's/^"//; s/"$//')"

if [ -z "$SECRET" ]; then
  say "!! не передан SECRET_KEY."
  say "   Панель → Ноды → создать ноду → скопировать Secret key."
  say "   Запуск: bash /root/node-install.sh \"СКОПИРОВАННЫЙ_КЛЮЧ\""
  exit 1
fi
if [ "${#SECRET}" -lt 16 ]; then
  say "!! ключ слишком короткий (${#SECRET} символов) — похоже, скопировался не полностью"
  exit 1
fi
case "$NODE_PORT" in
  ''|*[!0-9]*) say "!! порт должен быть числом"; exit 1;;
esac

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "aarch64" ]; then
  say "!! архитектура $ARCH — нода Remnawave не поддерживается"
  exit 1
fi

step "1/5  Docker"
if command -v docker >/dev/null 2>&1; then
  say "  уже установлен: $(docker --version)"
else
  say "  ставлю Docker (официальный скрипт)…"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh || { say "!! нет доступа к get.docker.com"; exit 1; }
  sh /tmp/get-docker.sh >/tmp/docker-install.log 2>&1 || { say "!! Docker не установился, лог: /tmp/docker-install.log"; exit 1; }
  say "  установлен: $(docker --version)"
fi
systemctl enable docker >/dev/null 2>&1 || true
systemctl start docker >/dev/null 2>&1 || true

step "2/5  Конфигурация ноды"
mkdir -p "$DIR"
cat > "$DIR/docker-compose.yml" <<'YAML'
services:
  remnanode:
    image: remnawave/node:latest
    container_name: remnanode
    hostname: remnanode
    network_mode: host
    restart: always
    cap_add:
      - NET_ADMIN
    ulimits:
      nofile:
        soft: 1048576
        hard: 1048576
    environment:
      - NODE_PORT=${NODE_PORT}
      - SECRET_KEY=${SECRET_KEY}
YAML
printf 'NODE_PORT=%s\nSECRET_KEY=%s\n' "$NODE_PORT" "$SECRET" > "$DIR/.env"
chmod 600 "$DIR/.env"
say "  файлы: $DIR/docker-compose.yml, $DIR/.env (права 600)"

step "3/5  Запуск ноды"
cd "$DIR" || exit 1
docker compose up -d || { say "!! нода не запустилась"; exit 1; }
sleep 8
docker ps --filter name=remnanode --format '  контейнер: {{.Names}} — {{.Status}}'

step "4/5  Порты"
OPEN_PORTS="2222 443 8443 80"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  for p in $OPEN_PORTS; do ufw allow "$p"/tcp >/dev/null 2>&1 || true; done
  say "  ufw: открыл порты $OPEN_PORTS"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  for p in $OPEN_PORTS; do firewall-cmd --permanent --add-port="$p"/tcp >/dev/null 2>&1 || true; done
  firewall-cmd --reload >/dev/null 2>&1 || true
  say "  firewalld: открыл порты $OPEN_PORTS"
else
  say "  локальный фаервол не активен (ufw/firewalld нет) — порты открыты"
fi
say "  важно: если у хостера есть свой «облачный фаервол» — открой в нём порты $OPEN_PORTS"

step "5/5  Проверка"
LISTEN="$(ss -tlnp 2>/dev/null | grep ":$NODE_PORT " | head -1)"
if [ -n "$LISTEN" ]; then
  say "  ok  нода слушает порт $NODE_PORT"
else
  say "  !! порт $NODE_PORT не слушается — пришли вывод: docker logs remnanode --tail 40"
fi
MYIP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || curl -fsS --max-time 8 https://ifconfig.me 2>/dev/null || echo '?')"
say "  внешний IP этого сервера: $MYIP"
say ""
say "Готово. Дальше:"
say "  1) Панель → Ноды: у новой ноды должен загореться 🟢 (иногда нужно 1–2 минуты,"
say "     кнопка «Обновить» в панели)."
say "  2) Если нода красная — проверь, что в панели указан адрес $MYIP и порт $NODE_PORT,"
say "     и пришли: docker logs remnanode --tail 40"
say ""
say "Эта нода — «обычный VPN» (прямое подключение). Финляндия с CDN остаётся как обход."
