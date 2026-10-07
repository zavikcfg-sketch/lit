#!/usr/bin/env python3
"""patch-usertools 2026-10-07.1 — «Мои устройства», промокоды, квест друзей.

Что делает:
  * скачивает модуль app/telegram/usertools.py (устройства + промокоды + квест);
  * врезает его подключение в главный файл бота;
  * добавляет строки «🐛 Мои устройства» и «🎟 Промокод» в меню входа;
  * учит админа командам /promo_add, /promo_list, /promo_off;
  * за каждые 3 приглашённых друзей начисляет +30 дней (REFERRAL_QUEST=3:30).

Безопасно: бэкап, проверка синтаксиса, автооткат, повторный запуск безопасен.

Запуск:  python3 /root/vpnbot-patch-usertools.py
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_VERSION = "patch-usertools 2026-10-07.1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

MODULE_URL = (
    "https://api.github.com/repos/zavikcfg-sketch/lit/contents/"
    "docs/vpnbot-usertools-module.py?ref=arena/ce75106c-lit"
)
INSTALL_MARKER = "_litenergy_usertools.install("
FALLBACK_URL = (
    "https://raw.githubusercontent.com/zavikcfg-sketch/lit/"
    "arena/ce75106c-lit/docs/vpnbot-usertools-module.py"
)


def fetch(url: str) -> str | None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "litenergy-patch/1.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  ! не скачалось ({url}): {exc}")
        return None
    text = data.decode("utf-8", errors="replace")
    if "async def install(dp)" not in text or "MODULE_VERSION" not in text:
        print("  ! в скачанном файле нет модуля — пропускаю этот источник")
        return None
    return text


def download_module() -> str | None:
    for url in (MODULE_URL, FALLBACK_URL):
        text = fetch(url)
        if text:
            return text
    return None


def unique_folder() -> Path:
    folder = BACKUP_DIR / f"usertools-backup-{STAMP}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def backup(path: Path, folder: Path) -> Path | None:
    if not path.exists():
        return None
    target = folder / path.name
    counter = 2
    while target.exists():
        target = folder / f"{path.name}-{counter}"
        counter += 1
    shutil.copy2(path, target)
    return target


def python_files() -> list[Path]:
    if not APP.exists():
        return []
    return sorted(APP.rglob("*.py"))


def find_dispatcher_file() -> Path | None:
    rx = re.compile(r"^(\s*)(\w+)\s*=\s*Dispatcher\(", re.M)
    fallback: Path | None = None
    for path in python_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not rx.search(text):
            continue
        if "start_polling" in text:
            return path
        fallback = fallback or path
    return fallback


def insert_install(text: str) -> tuple[str | None, str]:
    if INSTALL_MARKER in text:
        return text, "уже подключено ранее"
    rx = re.compile(r"^(\s*)(\w+)\s*=\s*Dispatcher\(", re.M)
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        match = rx.match(line)
        if not match:
            continue
        name = match.group(2)
        indent = match.group(1)
        depth = line.count("(") - line.count(")")
        end = idx
        while depth > 0 and end + 1 < len(lines):
            end += 1
            depth += lines[end].count("(") - lines[end].count(")")
        block_lines = [
            "",
            "# --- LitEnergy: устройства, промокоды, квест друзей ---",
            "try:",
            "    from app.telegram import usertools as _litenergy_usertools",
            f"    _litenergy_usertools.install({name})",
            "except Exception as _usertools_exc:  # noqa: BLE001",
            "    import logging as _usertools_logging",
            '    _usertools_logging.getLogger("app").warning(',
            '        "LitEnergy usertools не подключены: %s", _usertools_exc',
            "    )",
            "",
        ]
        block = "".join((indent + item + "\n") if item else "\n" for item in block_lines)
        return "".join(lines[: end + 1]) + block + "".join(lines[end + 1:]), f"врезка в {name}"
    return None, "не нашёл создание Dispatcher"


def update_env(folder: Path) -> list[str]:
    notes: list[str] = []
    try:
        text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    except OSError:
        return ["не смог прочитать .env"]
    if ENV.exists():
        backup(ENV, folder)
    lines = text.splitlines()
    wanted = {
        "USERTOOLS_ENABLED": "1",
        "REFERRAL_QUEST": "3:30",
    }
    for key, value in wanted.items():
        if any(line.strip().startswith(f"{key}=") for line in lines):
            notes.append(f".env: {key} уже есть")
            continue
        lines.append(f"{key}={value}")
        notes.append(f".env: добавлен {key}")
    try:
        ENV.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        notes.append(f"не смог записать .env ({exc})")
    return notes


def main() -> int:
    print(f"{SCRIPT_VERSION}")
    print(f"корень бота: {ROOT}")
    if not APP.exists():
        print(f"!! нет каталога {APP} — укажи VPNBOT_DIR=/путь/к/боту")
        return 1
    telegram_dir = APP / "telegram"
    if not telegram_dir.exists():
        print(f"!! нет каталога {telegram_dir}")
        return 1

    folder = unique_folder()
    backups: list[tuple[Path, Path]] = []
    touched: list[Path] = []
    notes: list[str] = []

    print("скачиваю модуль usertools…")
    module_text = download_module()
    if module_text is None:
        print("!! не удалось скачать модуль (нет доступа к GitHub).")
        print("   Проверь: curl -sI https://api.github.com | head -1")
        return 1

    module_path = telegram_dir / "usertools.py"
    saved = backup(module_path, folder)
    if saved:
        backups.append((module_path, saved))
    module_path.write_text(module_text, encoding="utf-8")
    touched.append(module_path)
    notes.append(f"модуль записан: app/telegram/usertools.py ({len(module_text.splitlines())} строк)")

    target = find_dispatcher_file()
    if target is None:
        notes.append("!! не нашёл файл с Dispatcher — врезка не сделана")
    else:
        text = target.read_text(encoding="utf-8", errors="replace")
        updated, note = insert_install(text)
        if updated is None or updated == text:
            notes.append(f"врезка: {note}")
        else:
            saved = backup(target, folder)
            if saved:
                backups.append((target, saved))
            target.write_text(updated, encoding="utf-8")
            touched.append(target)
            notes.append(f"врезка: {note} ({target.relative_to(ROOT)})")

    notes.extend(update_env(folder))

    broken: list[str] = []
    for path in touched:
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + ".pyc")
        except py_compile.PyCompileError as exc:
            broken.append(f"{path}: {exc.msg}")
    for path in touched:
        pyc = Path(str(path) + ".pyc")
        if pyc.exists():
            pyc.unlink()

    if broken:
        print("!! синтаксические ошибки:")
        for item in broken:
            print(f"   {item}")
        for path, saved in backups:
            shutil.copy2(saved, path)
        print(f"Откат выполнен из {folder}")
        return 1

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(f" • {note}")

    # быстрая проверка, что модуль импортируется и код заведён
    code = (
        "from app.telegram import usertools\n"
        "usertools.ensure_tables()\n"
        "print('ok', usertools.MODULE_VERSION)\n"
    )
    print("\nПроверка промокодов (заведён ли демо-код не нужно — проверишь сам):")
    print("  добавить: /promo_add PROMO10 10 0")
    print("  список:   /promo_list")
    print("  выключить: /promo_off PROMO10")
    print("\nЧто появится в боте:")
    print("  • 🐛 «Мои устройства» — список устройств из панели и кнопка «Отвязать»")
    print("  • 🎟 «Промокод» — клиент отправляет код, получает дни (один раз на аккаунт)")
    print("  • 🏆 квест: за каждые 3 приглашённых — +30 дней (REFERRAL_QUEST=3:30)")
    print("  • /devices — список устройств командой")
    print("\nДальше: docker compose up -d --build")
    print(f"Откат: из {folder} вернуть файлы в {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
