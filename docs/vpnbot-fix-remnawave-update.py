#!/usr/bin/env python3
"""Починка обновления пользователя в Remnawave для vpnbot (версия 2026-10-06.1).

Проблема: бот отправляет PATCH /api/users с телом {"uuid": ...}, а панель
Remnawave принимает только {"id": <число>} или {"username": ...} — иначе отвечает
HTTP 400 «Validation failed». Из-за этого не выдавались подписки и доп. устройства.

Что делает скрипт:
  * заменяет метод update_user в app/services/remnawave.py на корректный:
    при необходимости получает числовой id через get_user(uuid) и отправляет его;
  * определяет, каким аргументом файл передаёт тело запроса (json=/body=/data=)
    и использует тот же;
  * делает бэкап, проверяет синтаксис, идемпотентен.

Запуск:  python3 /root/vpnbot-fix-remnawave-update.py
Дальше:  docker compose up -d --build
"""
from __future__ import annotations

import ast
import os
import py_compile
import re
import shutil
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "fix-remnawave-update 2026-10-06.1"
MARKER = "REMNA_PATCH_FIX_V1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
TARGET = ROOT / "app" / "services" / "remnawave.py"
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))

NEW_METHOD = '''    async def update_user(self, user_id, **fields):
        # {marker}
        """Обновление пользователя в панели.

        Панель Remnawave принимает только "id" (число) или "username", а не uuid,
        поэтому при необходимости сначала выясняем числовой id.
        """
        target = user_id
        if isinstance(target, str) and not target.isdigit():
            info = await self.get_user(target)
            if isinstance(info, dict) and info.get("id") is not None:
                target = int(info["id"])
            else:
                raise RemnaError(f"Панель не вернула числовой id для пользователя {user_id}")
        elif isinstance(target, str):
            target = int(target)
        payload = {"id": target, **fields}
        return await self._request("PATCH", "/api/users", {kwarg}=payload)
'''.replace("{marker}", MARKER)


def detect_kwarg(source: str) -> str:
    """Каким именем файл уже передаёт тело в _request: json=, body=, data=?"""
    found = re.findall(r"self\._request\(\s*[^,]+,\s*[^,]+,\s*([a-z_]+)\s*=", source)
    for name in ("json", "body", "data"):
        if name in found:
            return name
    return "json"


def main() -> int:
    print(f"{SCRIPT_VERSION} | файл: {TARGET}")
    if not TARGET.is_file():
        print("!! Файл не найден. Можно указать корень бота: VPNBOT_DIR=/путь python3 ...")
        return 1

    source = TARGET.read_text(encoding="utf-8")
    if MARKER in source:
        print("уже пропатчено ранее — ничего не меняю")
        try:
            py_compile.compile(str(TARGET), doraise=True)
            print("синтаксис ОК")
        except py_compile.PyCompileError as exc:
            print(f"!! синтаксис сломан: {exc}")
            return 1
        return 0

    if 'raise RemnaError' not in source or "class RemnaError" not in source:
        print("!! в файле нет RemnaError — возможно, это другой клиент. Пришли вывод выше.")
        return 1
    for needed in ("_request", "get_user"):
        if f"def {needed}" not in source:
            print(f"!! в файле нет метода {needed} — патч не подходит, пришли вывод.")
            return 1

    kwarg = detect_kwarg(source)
    print(f"тело запроса файл передаёт как: {kwarg}=")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"!! файл не разбирается: {exc}")
        return 1

    target_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "update_user":
                    target_node = item
    if target_node is None:
        print("!! метод update_user не найден")
        return 1
    print(f"найден update_user: строки {target_node.lineno}-{target_node.end_lineno}")

    lines = source.splitlines(keepends=True)
    start = target_node.lineno - 1
    if target_node.decorator_list:
        start = min(d.lineno for d in target_node.decorator_list) - 1
    end = target_node.end_lineno

    original = "".join(lines[start:end])
    print("\n--- БЫЛО ---")
    print(original.rstrip("\n"))

    replacement = NEW_METHOD.replace("{kwarg}", kwarg)
    new_source = "".join(lines[:start]) + replacement + "".join(lines[end:])

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"vpnbot-remnawave-backup-{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy2(TARGET, backup)
    print(f"\nбэкап: {backup}")

    TARGET.write_text(new_source, encoding="utf-8")
    print("\n--- СТАЛО ---")
    print(replacement.rstrip("\n"))

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"\n!! синтаксис сломан, возвращаю бэкап: {exc}")
        shutil.copy2(backup, TARGET)
        return 1
    print("\nсинтаксис ОК")
    print("Дальше: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
