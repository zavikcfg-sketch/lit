#!/usr/bin/env python3
"""Установка лимита устройств (HWID) пользователю Remnawave (версия 2026-10-07.1).

Использование:
    docker exec -w /app vpnbot-bot python /tmp/set-device-limit.py <telegram_id> <лимит>

Например (1 базовое + 2 докупленных):
    docker exec -w /app vpnbot-bot python /tmp/set-device-limit.py 8346538289 3

Идемпотентен: если лимит уже такой — просто сообщит и ничего не изменит.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SCRIPT_VERSION = "set-device-limit 2026-10-07.1"


def bootstrap_path() -> str | None:
    for candidate in (os.environ.get("VPNBOT_APP_DIR"), os.getcwd(), "/app", "/opt/vpnbot/vpn-bot"):
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            sys.path.insert(0, candidate)
            return candidate
    return None


APP_ROOT = bootstrap_path()
if APP_ROOT is None:
    print("!! Не нашёл каталог с пакетом app/ (код бота).")
    print("   Запусти так:  docker exec -w /app vpnbot-bot python /tmp/set-device-limit.py <telegram_id> <лимит>")
    sys.exit(2)
print(f"{SCRIPT_VERSION} | корень бота: {APP_ROOT}")


async def main() -> int:
    args = [a for a in sys.argv[1:] if a.strip()]
    if len(args) != 2:
        print("Использование: set-device-limit.py <telegram_id> <лимит>")
        print("Например:      set-device-limit.py 8346538289 3")
        return 2
    try:
        telegram_id = int(args[0])
        target = int(args[1])
    except ValueError:
        print("!! telegram_id и лимит должны быть числами")
        return 2
    if target < 0 or target > 100:
        print("!! лимит должен быть от 0 до 100")
        return 2

    from app.database import init_db
    from app.services import device_slots
    from app.services.remnawave import RemnaError, get_remna

    await init_db()

    remna_id = await device_slots._remna_id(telegram_id)
    if not remna_id:
        print(f"!! пользователь telegram {telegram_id} не найден ни локально, ни в панели")
        return 1
    print(f"панельный id: {remna_id}")

    remna = get_remna()
    try:
        user = await remna.get_user(remna_id)
    except RemnaError as exc:
        print(f"!! не удалось прочитать пользователя: {exc}")
        return 1
    before = user.get("hwidDeviceLimit")
    print(f"было: hwidDeviceLimit={before!r}, status={user.get('status')!r}, expireAt={user.get('expireAt')!r}")

    try:
        current = int(before) if before is not None else 0
    except (TypeError, ValueError):
        current = 0
    if current == target:
        print(f"уже установлен лимит {target} — ничего не меняю")
        return 0

    try:
        await remna.update_user(remna_id, hwidDeviceLimit=target)
    except RemnaError as exc:
        print(f"!! панель отклонила запрос: {exc}")
        return 1

    after = await remna.get_user(remna_id)
    limit_after = after.get("hwidDeviceLimit")
    print(f"стало: hwidDeviceLimit={limit_after!r}")
    if int(limit_after or 0) != target:
        print("!! значение не совпало с ожидаемым — проверь панель")
        return 1
    print(f"готово: лимит устройств = {target}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
