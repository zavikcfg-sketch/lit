#!/usr/bin/env python3
"""Генерирует vpn-bot-deploy.sh — один скрипт, который создаёт/обновляет ВСЕ файлы
проекта vpn-bot на сервере через cat <<'EOF' (без затрагивания .env и данных).

Запуск из корня репозитория:  python3 scripts/gen_deploy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "vpn-bot"
OUT = ROOT / "vpn-bot-deploy.sh"

SKIP_NAMES = {".env", "__pycache__", ".git"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".db", ".db-wal", ".db-shm")


def collect_files() -> list[Path]:
    files: list[Path] = []
    for p in sorted(PROJECT.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_NAMES for part in p.relative_to(PROJECT).parts):
            continue
        if p.name.endswith(SKIP_SUFFIXES):
            continue
        files.append(p)
    return files


def main() -> int:
    if not PROJECT.is_dir():
        print("каталог vpn-bot не найден", file=sys.stderr)
        return 1
    files = collect_files()
    if not files:
        print("нет файлов для упаковки", file=sys.stderr)
        return 1

    lines: list[str] = []
    lines.append("#!/usr/bin/env bash")
    lines.append("# ============================================================")
    lines.append("# VPN-бот (Remnawave + YooMoney) — деплой/обновление файлов проекта")
    lines.append("# Сгенерировано scripts/gen_deploy.py — вручную не редактировать.")
    lines.append("#")
    lines.append("# Использование:")
    lines.append("#   bash vpn-bot-deploy.sh            # только создать/обновить файлы")
    lines.append("#   bash vpn-bot-deploy.sh --deploy   # + docker compose build && up -d")
    lines.append("#")
    lines.append("# Скрипт НЕ трогает: .env (если уже существует), volume с базой данных.")
    lines.append("# ============================================================")
    lines.append("set -euo pipefail")
    lines.append('cd "$(dirname "$0")"')
    lines.append("")
    lines.append('echo "==> Создание структуры каталогов vpn-bot"')
    dirs = sorted({str(f.parent.relative_to(PROJECT)) for f in files})
    for d in dirs:
        if d == ".":
            continue
        lines.append(f"mkdir -p vpn-bot/{d}")
    lines.append("")
    lines.append('echo "==> Запись файлов проекта"')
    for i, f in enumerate(files, start=1):
        rel = f.relative_to(PROJECT)
        content = f.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        if f"\nRW_EOF_{i}\n" in content or content.startswith(f"RW_EOF_{i}\n"):
            raise SystemExit(f"коллизия heredoc-разделителя в {rel}")
        lines.append(f"cat > vpn-bot/{rel} <<'RW_EOF_{i}'")
        body = content.rstrip("\n")
        if body:
            lines.append(body)
        lines.append(f"RW_EOF_{i}")
    lines.append("")
    lines.append("# -------------------------------------------------------------")
    lines.append('if [ ! -f vpn-bot/.env ]; then')
    lines.append('  cp vpn-bot/.env.example vpn-bot/.env')
    lines.append('  echo "!! Создан vpn-bot/.env из примера — ЗАПОЛНИТЕ секреты: nano vpn-bot/.env"')
    lines.append('else')
    lines.append('  echo "==> Существующий vpn-bot/.env не изменён"')
    lines.append('fi')
    lines.append("")
    lines.append('chmod +x vpn-bot-deploy.sh 2>/dev/null || true')
    lines.append('echo ""')
    lines.append('echo "==> Готово. Файлов записано: ' + str(len(files)) + '"')
    lines.append('echo ""')
    lines.append('echo "Дальнейшие шаги:"')
    lines.append('echo "  1) nano vpn-bot/.env        # заполните BOT_TOKEN, REMNAWAVE_*, YOOMONEY_*, ADMIN_*"')
    lines.append('echo "  2) cd vpn-bot"')
    lines.append('echo "  3) docker compose build && docker compose up -d"')
    lines.append('echo "  4) docker compose ps && docker compose logs -f --tail=50"')
    lines.append('echo ""')
    lines.append('if [ "${1:-}" = "--deploy" ]; then')
    lines.append('  echo "==> Сборка и запуск контейнеров"')
    lines.append('  cd vpn-bot')
    lines.append('  docker compose build')
    lines.append('  docker compose up -d')
    lines.append('  docker compose ps')
    lines.append('fi')
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    OUT.chmod(0o755)
    print(f"OK: {OUT} ({OUT.stat().st_size / 1024:.1f} КБ, файлов: {len(files)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
