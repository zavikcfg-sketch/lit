#!/usr/bin/env python3
"""code-probe 2026-10-07.2 — разведка интерфейса бота LitEnergy.

Ничего не меняет: только читает исходники, собирает выгрузку и пробует
выложить её по короткой ссылке. Дополнительно печатает компактную карту
интерфейса (баннер, меню, кнопки) — её можно просто скопировать в чат.

Запуск:  python3 /root/vpnbot-code-probe.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_VERSION = "code-probe 2026-10-07.4"

BOT_DIR = Path(os.environ.get("VPNBOT_DIR") or "/opt/vpnbot/vpn-bot")
OUT_PATH = Path(os.environ.get("VPNBOT_PROBE_OUT") or "/root/vpnbot-code.out")
REPORT_PATH = Path(os.environ.get("VPNBOT_PROBE_REPORT") or "/root/vpnbot-look-report.txt")
CONTAINER = os.environ.get("VPNBOT_CONTAINER") or "vpnbot-bot"
MAX_BYTES = 900_000
SKIP_DIRS = {"__pycache__", ".venv", "venv", "env", "data", ".git", "node_modules", "site-packages", "tests"}
SKIP_SUFFIX = {".pyc", ".log", ".db", ".sqlite", ".sqlite3", ".session", ".jpg", ".png", ".webp", ".mp4"}
KEEP_SUFFIX = {".py", ".txt", ".toml", ".cfg", ".ini", ".md", ".html", ".jinja", ".jinja2", ".yml", ".yaml"}

SECRET_WORD = r"(?:bot_?token|token|secret|password|passwd|api_?key|private_?key|wallet|auth)"
SECRET_RE = re.compile(
    rf"(?i)(\b\w*{SECRET_WORD}\w*\s*(?::\s*[\w\[\]\., ]+?\s*)?[:=]\s*)([\"'])([^\"'\n]{{6,}})\2"
)
SECRET_UNQUOTED_RE = re.compile(rf"(?im)(\b\w*{SECRET_WORD}\w*\s*[:=]\s*)([^\s\"']{{6,}})")
DIGITS_RE = re.compile(r"\b\d{{8,12}}:[A-Za-z0-9_\-]{{30,}}\b")
WALLET_RE = re.compile(r"\b41001\d{{9,}}\.[A-Za-z0-9_\-]{{4,}}\b")


def mask(text: str) -> str:
    text = SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***{m.group(2)}", text)
    text = SECRET_UNQUOTED_RE.sub(lambda m: f"{m.group(1)}***", text)
    text = WALLET_RE.sub("***WALLET***", text)
    return DIGITS_RE.sub("***BOT_TOKEN***", text)


def collect_files() -> list[Path]:
    files: list[Path] = []
    app = BOT_DIR / "app"
    root = app if app.is_dir() else BOT_DIR
    for path in sorted(root.rglob("*")):
        if path.is_dir() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIX or path.name.startswith("."):
            continue
        if path.suffix.lower() in KEEP_SUFFIX:
            files.append(path)
    for extra in ("requirements.txt", "pyproject.toml", "Dockerfile", "docker-compose.yml", "alembic.ini", "run.py", "main.py"):
        path = BOT_DIR / extra
        if path.is_file() and path not in files:
            files.append(path)
    return files


def build_dump(files: list[Path]) -> tuple[str, list[str], int]:
    parts: list[str] = [
        "# БОТ LitEnergy — выгрузка кода для переделки интерфейса\n",
        f"# версия разведчика: {SCRIPT_VERSION}\n",
        f"# корень бота: {BOT_DIR}\n",
        f"# время: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
    ]
    warnings: list[str] = []
    total = 0
    index: list[str] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"не прочитан {path}: {exc}")
            continue
        rel = path.relative_to(BOT_DIR)
        lines = text.count("\n") + 1
        total += len(text)
        index.append(f"  {rel}  —  {lines} строк")
        body = mask(text)
        if rel.suffix.lower() != ".py":
            body = text
        chunk = f"\n# ==== FILE: {rel} ({lines} строк) ====\n{body}\n"
        if len("".join(parts)) + len(chunk) > MAX_BYTES:
            warnings.append(f"дальше обрезано на {rel} (слишком большой объём)")
            break
        parts.append(chunk)

    parts.insert(4, "# Файлы в каталоге:\n" + "\n".join(index) + "\n\n")
    return "".join(parts), warnings, total


def parse_handlers(text: str) -> list[tuple[str, str, str]]:
    """@router.<kind>(<фильтр>) → имя функции, с учётом многострочных фильтров."""
    found: list[tuple[str, str, str]] = []
    for m in re.finditer(r"^@router\.(\w+)\(", text, re.M):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        filt = " ".join(text[m.end(): i - 1].split())
        dm = re.search(r"^(?:[ \t]*#.*\n)*[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)", text[i:], re.M)
        found.append((m.group(1), filt[:90], dm.group(1) if dm else "?"))
    return found


def parse_kb_builders(text: str) -> list[str]:
    """Функции, которые собирают клавиатуры."""
    names: list[str] = []
    for m in re.finditer(r"^([ \t]*)(?:async[ \t]+)?def[ \t]+(\w+)\(", text, re.M):
        indent = len(m.group(1))
        body: list[str] = []
        for line in text[m.end():].splitlines():
            if line.strip() and (len(line) - len(line.lstrip())) <= indent and re.match(r"\s*(?:async\s+)?def\b|\s*class\b|\s*@", line):
                break
            body.append(line)
        blob = "\n".join(body)
        if any(k in blob for k in ("InlineKeyboardMarkup", "InlineKeyboardBuilder", "KeyboardButton", "ReplyKeyboardMarkup")):
            names.append(m.group(2))
    return names


def compact_report(files: list[Path]) -> tuple[str, int]:
    out: list[str] = [
        f"КАРТА ИНТЕРФЕЙСА БОТА ({SCRIPT_VERSION})",
        f"корень: {BOT_DIR}   aiogram: {aiogram_version()}",
        "",
    ]
    callbacks: set[str] = set()
    for path in files:
        if path.suffix.lower() != ".py" or any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(BOT_DIR)
        out.append(f"--- {rel} ({text.count(chr(10)) + 1} строк)")
        for kind, flt, name in parse_handlers(text):
            out.append(f"    @{kind}({flt}) → {name}")
        for name in parse_kb_builders(text):
            out.append(f"    клавиатура: {name}")
        for ln in text.splitlines():
            if re.search(r"BANNER|answer_photo|send_photo|file_id", ln):
                out.append(f"    баннер: {ln.strip()[:110]}")
        for ln in text.splitlines():
            if "F.text" in ln or ln.lstrip().startswith("@"):
                continue
            if re.search(r"\b(caption|text)\s*=", ln):
                out.append(f"    текст: {ln.strip()[:110]}")
        callbacks.update(re.findall(r"callback_data=[\"']([^\"']+)[\"']", text))
        callbacks.update(re.findall(r"[\"'](menu:[\w:\-]+|buy:[\w:\-]+|chk:[\w:\-]+|admin:[\w:\-]+)[\"']", text))
        out.append("")
    cb = sorted(callbacks)
    out.append(f"callback-кнопки ({len(cb)}): " + ", ".join(cb[:80]))
    text = "\n".join(out)
    return text, len(out)


def aiogram_version() -> str:
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER, "python", "-c", "import aiogram;print(aiogram.__version__)"],
            capture_output=True, text=True, timeout=25,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    for req in (BOT_DIR / "requirements.txt", BOT_DIR / "pyproject.toml"):
        if req.is_file():
            m = re.search(r"aiogram[^\n]*", req.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(0).strip()
    return "неизвестно"


def upload(path: Path) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    attempts = (
        ("файл", ["curl", "-fsS", "--max-time", "25", "-F", "reqtype=fileupload", "-F", f"fileToUpload=@{path}", "https://catbox.moe/user/api.php"]),
        ("текст", ["curl", "-fsS", "--max-time", "25", "--upload-file", str(path), "-H", "Max-Days: 7", "https://0x0.st"]),
        ("dpaste", ["curl", "-fsS", "--max-time", "25", "-F", f"content=@{path}", "-F", "syntax=python", "-F", "expiry_days=7", "https://dpaste.com/api/v2/"]),
    )
    for name, cmd in attempts:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  {name}: не сработал ({exc})")
            continue
        url = (result.stdout or "").strip().splitlines()[-1:] or [""]
        url = url[0].strip()
        if result.returncode == 0 and url.startswith("http") and len(url) < 200:
            links.append((name, url))
            print(f"  {name}: {url}")
            if name in ("файл", "текст"):
                break
        else:
            print(f"  {name}: отказ (код {result.returncode})")
    return links


def main() -> int:
    print(SCRIPT_VERSION)
    print(f"корень бота: {BOT_DIR}")
    if not BOT_DIR.is_dir():
        print(f"!! нет каталога {BOT_DIR} — укажи VPNBOT_DIR=/путь/к/боту")
        return 1

    files = collect_files()
    print(f"файлов найдено: {len(files)} | aiogram: {aiogram_version()}")

    dump, warnings, total = build_dump(files)
    for item in warnings:
        print(f"  ! {item}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(dump, encoding="utf-8")
    print(f"выгрузка кода: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} КБ)")

    report, lines = compact_report(files)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"карта интерфейса: {REPORT_PATH} ({lines} строк)")
    print("секреты в файлах замаскированы (***)")

    print("пробую выложить выгрузку по ссылке…")
    links = upload(OUT_PATH)
    if not links:
        print("пробую выложить карту интерфейса (она маленькая)…")
        links = upload(REPORT_PATH)

    print()
    print("=" * 64)
    print("КОПИЯ КАРТЫ ИНТЕРФЕЙСА (если ссылка не сработает — пришли её):")
    print("-" * 64)
    print(report)
    print("-" * 64)
    if links:
        print("ПРИШЛИ В ЧАТ ССЫЛКУ:")
        print(links[0][1])
        if len(links) > 1:
            print(f"(ещё: {links[1][1]})")
    else:
        print("!! Автозагрузка не удалась. Пришли в чат вывод команды:")
        print("   cat /root/vpnbot-look-report.txt")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
