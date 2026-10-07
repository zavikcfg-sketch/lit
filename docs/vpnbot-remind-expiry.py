#!/usr/bin/env python3
"""Напоминания об окончании подписки (vpnbot) — версия 2026-10-07.1.

Запускается НА ХОСТЕ (внутри контейнера не нужен), использует только стандартную
библиотеку Python: читает .env (BOT_TOKEN) и базу бота data/bot.db, отправляет
сообщения через Telegram Bot API.

Что отправляет:
  * за 3 дня до окончания — мягкое напоминание;
  * за 1 день — «завтра закончится»;
  * в день окончания / после — «подписка закончилась».
Повторы исключены: состояние в /root/vpnbot-reminders-state.json.

Проверка без отправки:
    python3 /root/vpnbot-remind-expiry.py --dry-run
Рабочий запуск:
    python3 /root/vpnbot-remind-expiry.py

Крон (каждый день в 12:00):
    0 12 * * * cd /opt/vpnbot/vpn-bot && /usr/bin/python3 /root/vpnbot-remind-expiry.py >> /var/log/vpnbot-remind.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_VERSION = "remind-expiry 2026-10-07.1"

BOT_DIR = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
ENV_FILE = BOT_DIR / ".env"
DB_FILE = Path(os.environ.get("VPNBOT_DB", str(BOT_DIR / "data" / "bot.db")))
STATE_FILE = Path(os.environ.get("VPNBOT_REMIND_STATE", "/root/vpnbot-reminders-state.json"))

WARN_DAYS = (3, 1)
MAX_PER_RUN = 200


def say(text: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} {text}")


def read_env_value(key: str) -> str | None:
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as exc:
        say(f"!! не смог сохранить состояние: {exc}")


def parse_dt(value) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_users() -> list[tuple[int, str | None]]:
    """Пары (telegram_id, expire_at) из локальной базы бота."""
    if not DB_FILE.is_file():
        say(f"!! не нашёл базу {DB_FILE}")
        return []
    try:
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        say(f"!! не открыть базу: {exc}")
        return []
    try:
        cur = conn.execute("SELECT telegram_id, expire_at FROM users")
        return [(int(row[0]), row[1]) for row in cur.fetchall() if row and row[0]]
    except sqlite3.Error as exc:
        say(f"!! ошибка запроса к базе: {exc}")
        return []
    finally:
        conn.close()


def build_message(kind: str, days_left: int, subscription_url: str | None) -> str:
    if kind == "warn3":
        head = "⏳ <b>Подписка заканчивается через 3 дня</b>"
        tail = "Продлите сейчас, чтобы не остаться без VPN."
    elif kind == "warn1":
        head = "⏳ <b>Подписка заканчивается завтра</b>"
        tail = "Продлить можно в один тап по кнопке ниже."
    elif kind == "today":
        head = "⏳ <b>Подписка заканчивается сегодня</b>"
        tail = "Продлите до конца дня, чтобы не потерять доступ."
    else:
        head = "🚫 <b>Подписка закончилась</b>"
        tail = "Продлите подписку — доступ восстановится сразу после оплаты, настройки на телефоне менять не нужно."
    text = f"{head}\n\nОсталось дней: <b>{max(days_left, 0)}</b>.\n{tail}"
    if subscription_url and kind == "warn3":
        text += f"\n\nСсылка подписки (если нужна):\n<code>{subscription_url}</code>"
    return text


def send_message(token: str, chat_id: int, text: str) -> bool:
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "reply_markup": json.dumps(
            {"inline_keyboard": [[{"text": "💎 Продлить подписку", "callback_data": "menu:shop"}]]},
            ensure_ascii=False,
        ),
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=25) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if '"ok":true' in body:
            return True
        say(f"   Telegram ответил отказом: {body[:200]}")
        return False
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200] if exc.fp else ""
        say(f"   HTTP {exc.code}: {detail}")
        return False
    except Exception as exc:  # noqa: BLE001
        say(f"   ошибка отправки: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Напоминания об окончании подписки")
    parser.add_argument("--dry-run", action="store_true", help="показать, что было бы отправлено")
    parser.add_argument("--force-days", type=int, default=None, help="проверить как будто осталось N дней")
    args = parser.parse_args()

    say(f"{SCRIPT_VERSION} | база: {DB_FILE} | {'ПРОБНЫЙ РЕЖИМ' if args.dry_run else 'рабочий режим'}")
    token = read_env_value("BOT_TOKEN")
    if not token:
        say("!! не нашёл BOT_TOKEN в .env — отправка невозможна")
        return 1

    users = fetch_users()
    if not users:
        say("пользователей не нашлось")
        return 0
    say(f"пользователей в базе: {len(users)}")

    state = load_state()
    now = datetime.now(timezone.utc)
    sent = 0
    planned = 0

    for telegram_id, expire_raw in users:
        expire = parse_dt(expire_raw)
        if expire is None:
            continue
        if expire <= now:
            days_left, kind = 0, "expired"
        else:
            # считаем по календарным дням: «заканчивается 16-го, сегодня 13-е» -> 3 дня
            days_left = (expire.date() - now.date()).days
            kind = {3: "warn3", 1: "warn1", 0: "today"}.get(days_left)
        if args.force_days is not None:
            days_left = args.force_days
            kind = {3: "warn3", 1: "warn1", 0: "today"}.get(days_left, "expired" if days_left < 0 else kind)
        if kind is None:
            continue

        key = f"{telegram_id}:{expire.strftime('%Y-%m-%d')}:{kind}"
        if key in state:
            continue

        planned += 1
        if planned > MAX_PER_RUN:
            say("!! слишком много напоминаний за один запуск — остановился, остальное в следующий раз")
            break
        text = build_message(kind, days_left, None)
        if args.dry_run:
            say(f"[пробно] {telegram_id}: {kind} (осталось {days_left} дн.) -> {text.splitlines()[0]}")
            continue
        if send_message(token, telegram_id, text):
            state[key] = now.strftime("%Y-%m-%d %H:%M:%S")
            sent += 1
            say(f"отправлено {telegram_id}: {kind} (осталось {days_left} дн.)")
        else:
            say(f"!! не отправлено {telegram_id}: {kind}")

    if not args.dry_run and sent:
        save_state(state)
    say(f"итог: запланировано {planned}, отправлено {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
