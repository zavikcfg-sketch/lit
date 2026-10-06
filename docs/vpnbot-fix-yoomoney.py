#!/usr/bin/env python3
"""Починка поиска платежей в vpnbot/app/services/yoomoney.py (версия 2026-10-06.1).

Что исправляет:
  * эндпоинт `/api/operations-history` -> правильный `/api/operation-history`;
  * `type=in` -> правильное значение `type=deposition` (допустимы только
    deposition/payment, «in» — это поле ответа, а не параметр запроса);
  * отбор по метке теперь идёт и на стороне API, и на стороне бота.

Идемпотентно: повторный запуск ничего не делает. Делает резервную копию файла.

Запуск:
    python3 /root/vpnbot-fix-yoomoney.py
"""
from __future__ import annotations

import ast
import os
import py_compile
import shutil
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "fix-yoomoney 2026-10-06.1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
TARGET = ROOT / "app" / "services" / "yoomoney.py"
MARKER = "YOOMONEY_LOOKUP_V2"

NEW_FUNCTION = '''async def fetch_operations_by_label(label: str) -> list[dict] | None:
    # YOOMONEY_LOOKUP_V2
    """История операций YooMoney: ищем платежи с меткой label.

    [] — запросы прошли, но платежа с такой меткой нет;
    None — не удалось получить ответ (нет токена/сеть/неверный токен).
    """
    s = get_settings()
    if not s.yoomoney_access_token:
        return None
    url = "https://yoomoney.ru/api/operation-history"
    headers = {"Authorization": f"Bearer {s.yoomoney_access_token}"}
    attempts = (
        ("POST", {"type": "deposition", "label": label, "records": 100}),
        ("GET", {"type": "deposition", "records": 100}),
        ("POST", {"type": "deposition", "records": 100}),
        ("POST", {"records": 100}),
    )
    got_answer = False
    async with httpx.AsyncClient(timeout=20) as client:
        for method, params in attempts:
            try:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=params)
                else:
                    resp = await client.post(url, headers=headers, data=params)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("YooMoney: запрос не удался (%s)", type(exc).__name__)
                continue
            if resp.status_code != 200:
                log.warning("YooMoney: HTTP %s — %s", resp.status_code, (resp.text or "")[:200])
                continue
            got_answer = True
            try:
                payload = resp.json() or {}
            except ValueError:
                continue
            if payload.get("error"):
                log.warning("YooMoney: ошибка API %s", payload.get("error"))
                continue
            matched = [
                op
                for op in (payload.get("operations") or [])
                if str(op.get("label") or "") == label
            ]
            if matched:
                return matched
            if "label" not in params:
                return []
    if got_answer:
        return []
    return None
'''


def replace_function(source: str, name: str, new_code: str) -> tuple[str | None, str]:
    """Заменяет функцию целиком (границы берём через ast, а не по тексту)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return None, f"не разобрать файл: {exc}"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = source.splitlines(keepends=True)
            start = node.lineno - 1
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list) - 1
            end = node.end_lineno
            if end is None:
                return None, "не удалось определить конец функции"
            new_lines = lines[:start] + [new_code.rstrip("\n") + "\n"] + lines[end:]
            return "".join(new_lines), f"заменена функция {name} (строки {start + 1}-{end})"
    return None, f"функция {name} не найдена"


def main() -> int:
    print(f"{SCRIPT_VERSION} | файл: {TARGET}")
    if not TARGET.is_file():
        print("!! Файл не найден. Укажи корень бота: VPNBOT_DIR=/opt/vpnbot/vpn-bot python3 ...")
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

    new_source, note = replace_function(source, "fetch_operations_by_label", NEW_FUNCTION)
    if new_source is None:
        print(f"!! {note}")
        lines = source.splitlines()
        for i, line in enumerate(lines[:40], 1):
            print(f"   {i}: {line}")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    backup = BACKUP_DIR / f"vpnbot-yoomoney-backup-{stamp}.py"
    try:
        shutil.copy2(TARGET, backup)
        print(f"бэкап: {backup}")
    except OSError as exc:
        print(f"!! не смог сделать бэкап ({exc}) — прерываю, чтобы не рисковать")
        return 1

    TARGET.write_text(new_source, encoding="utf-8")
    print(f"• {note}")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"!! синтаксис сломан, возвращаю бэкап: {exc}")
        shutil.copy2(backup, TARGET)
        return 1
    print("синтаксис ОК")
    print("\nДальше: docker compose restart vpnbot-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
