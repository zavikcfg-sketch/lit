#!/usr/bin/env python3
"""Разбор структуры бота vpnbot (версия 2026-10-07.1).

Ничего не меняет — только читает код и печатает карту: какие файлы есть, какие
команды/кнопки обрабатываются, где какие callback-данные и какие тексты меню.
Нужен, чтобы аккуратно доработать внешний вид без догадок.

Запуск:
    docker cp /root/vpnbot-inspect.py vpnbot-bot:/tmp/inspect.py
    docker exec -w /app vpnbot-bot python /tmp/inspect.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

SCRIPT_VERSION = "inspect 2026-10-07.1"

INTERESTING = ("menu:", "buy:", "chk:", "profile:", "start", "trial")
MAX_SOURCE_LINES = 90


def find_app_root() -> Path | None:
    for candidate in (os.environ.get("VPNBOT_APP_DIR"), os.getcwd(), "/app", "/opt/vpnbot/vpn-bot"):
        if candidate and (Path(candidate) / "app" / "config.py").is_file():
            return Path(candidate)
    return None


def callbacks_in(text: str) -> list[str]:
    found = set()
    for match in re.finditer(r"[\"']((?:menu|buy|chk|profile|trial|dev|tariff)[:\w]*(?::[\w.-]+)?)[\"']", text):
        found.add(match.group(1))
    return sorted(found)


def dump_file(path: Path) -> None:
    rel = path.as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    callbacks = callbacks_in(text)
    print(f"\n=== {rel} ({len(text.splitlines())} строк, {len(text)} байт) ===")
    if callbacks:
        print("  callback-данные: " + ", ".join(callbacks))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        print(f"  !! не разбирается: {exc}")
        return

    funcs: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = []
            for dec in node.decorator_list:
                try:
                    decorators.append(ast.unparse(dec))
                except Exception:  # noqa: BLE001
                    decorators.append("?")
            marker = " <- ОБРАБОТЧИК" if decorators else ""
            print(f"  {node.lineno:4d}: {node.name}({', '.join(a.arg for a in node.args.args)}){marker}")
            for dec in decorators:
                print(f"        @{dec}")
            funcs.append((node.name, node.lineno))

    lines = text.splitlines()
    wanted = ("start", "menu", "shop", "profile", "help", "back", "subscribe", "me", "account", "trial")
    for name, lineno in funcs:
        if not any(word in name.lower() for word in wanted):
            continue
        print(f"\n  --- исходник {name} (строки {lineno}-{min(lineno + MAX_SOURCE_LINES, len(lines))}) ---")
        for i in range(lineno - 1, min(lineno - 1 + MAX_SOURCE_LINES, len(lines))):
            print(f"  {i + 1:4d}| {lines[i]}")


def main() -> int:
    app = find_app_root()
    if app is None:
        print("!! не нашёл пакет app/. Запусти: docker exec -w /app vpnbot-bot python /tmp/inspect.py")
        return 2
    print(f"{SCRIPT_VERSION} | корень бота: {app}")
    app_dir = app / "app"

    print("\n=== СТРУКТУРА ПАКЕТА ===")
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(app_dir)
        print(f"  {rel} — {path.stat().st_size} б, {len(path.read_text(encoding='utf-8', errors='replace').splitlines())} строк")

    for folder in ("telegram", "keyboards", "handlers"):
        sub = app_dir / folder
        if not sub.is_dir():
            continue
        print(f"\n########## app/{folder} ##########")
        for path in sorted(sub.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            dump_file(path)

    print("\n=== ПОДСКАЗКА ===")
    print("  Пришли этот вывод целиком — по нему я подготовлю аккуратный патч внешнего вида:")
    print("  оформленное меню, карточку «Моя подписка», QR-код и инструкции по приложениям.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
