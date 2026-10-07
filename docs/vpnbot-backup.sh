#!/usr/bin/env bash
# Бэкап бота vpnbot: база заказов + .env + код в один архив.
# Версия 2026-10-07.1
#
# Запуск вручную:   bash /root/vpnbot-backup.sh
# В крон (ежедневно в 4:30):
#   echo '30 4 * * * /bin/bash /root/vpnbot-backup.sh >> /var/log/vpnbot-backup.log 2>&1' | crontab -l 2>/dev/null - | crontab -
#
# Хранит последние 14 архивов. Восстановление:
#   tar -xzf /root/vpnbot-backups/vpnbot-<дата>.tar.gz -C /opt/vpnbot/vpn-bot
set -u

BOT_DIR="${VPNBOT_DIR:-/opt/vpnbot/vpn-bot}"
DEST="${VPNBOT_BACKUP_DIR:-/root/vpnbot-backups}"
KEEP="${VPNBOT_BACKUP_KEEP:-14}"

say() { printf '%s\n' "$*"; }

[ -d "$BOT_DIR" ] || { say "!! нет каталога $BOT_DIR"; exit 1; }
mkdir -p "$DEST" || { say "!! не создать каталог $DEST"; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$DEST/vpnbot-$STAMP.tar.gz"

# что кладём: база, настройки, код (data/.env/app). Без логов и кэшей.
if tar -czf "$ARCHIVE" -C "$BOT_DIR" \
    --exclude='data/*.log' --exclude='__pycache__' --exclude='*.pyc' \
    data .env app 2>/dev/null; then
  :
else
  say "!! архивация не удалась (проверь права на $BOT_DIR)"
  exit 1
fi

SIZE=$(du -h "$ARCHIVE" | cut -f1)
say "бэкап: $ARCHIVE ($SIZE)"

# ротация: оставляем последние KEEP архивов
COUNT=$(ls -1 "$DEST"/vpnbot-*.tar.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  ls -1t "$DEST"/vpnbot-*.tar.gz | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old" && say "удалён старый: $old"
  done
fi

say "всего архивов: $(ls -1 "$DEST"/vpnbot-*.tar.gz 2>/dev/null | wc -l) (храним последние $KEEP)"
say "восстановление: tar -xzf $ARCHIVE -C $BOT_DIR"
