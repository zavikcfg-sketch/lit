#!/usr/bin/env python3
"""Патч vpnbot (LitEnergyVPN): автоматическая выдача доп. устройств (HWID-слоты),
кнопка «Ещё устройство» в магазине, правка .env (цены, комиссия, лимит устройств).

Идемпотентный: повторный запуск ничего не ломает.
Перед изменениями делает бэкап каталога app и .env.
Запуск:  python3 /root/vpnbot-patch-devices.py
Корень бота можно переопределить: VPNBOT_DIR=/path python3 ...
"""
from __future__ import annotations

import os
import py_compile
import re
import shutil
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "patch-devices 2026-10-06.3"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))


def unique_path(path: Path) -> Path:
    """Чтобы повторный запуск в ту же секунду не падал на существующем бэкапе."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(path.name + f"-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1

SLOTS_MODULE = '''"""Дополнительные устройства (HWID-слоты) для подписок Remnawave."""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session
from app.models import User
from app.services.remnawave import RemnaError, get_remna

log = logging.getLogger("app.device_slots")

DEVICE_CODE = "device"


def slot_price() -> Decimal:
    """Цена одного дополнительного устройства (PRICE_DEVICE_SLOT)."""
    return get_settings().price_device_slot


def base_limit() -> int:
    """Базовый лимит устройств на подписку (DEVICE_BASE_LIMIT)."""
    return max(1, int(get_settings().device_base_limit or 1))


def _as_limit(value) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


async def _remna_id(telegram_id: int) -> str | None:
    async with get_session() as session:
        local = (
            await session.execute(select(User).where(User.telegram_id == int(telegram_id)))
        ).scalar_one_or_none()
    if local is not None and local.remnawave_user_id:
        return str(local.remnawave_user_id)
    found = await get_remna().find_user_by_telegram_id(int(telegram_id))
    if found and found.get("id"):
        return str(found["id"])
    return None


async def get_device_limit(telegram_id: int) -> int | None:
    """Текущий лимит устройств в панели (None, если недоступно)."""
    try:
        remna_id = await _remna_id(telegram_id)
        if not remna_id:
            return None
        return _as_limit((await get_remna().get_user(remna_id)).get("hwidDeviceLimit"))
    except RemnaError as exc:
        log.warning("Не удалось прочитать лимит устройств: %s", exc)
        return None


async def ensure_base_limit(telegram_id: int) -> None:
    """Выставляет базовый лимит (1 устройство), если он не задан или меньше."""
    base = base_limit()
    try:
        remna_id = await _remna_id(telegram_id)
        if not remna_id:
            return
        remna = get_remna()
        current = _as_limit((await remna.get_user(remna_id)).get("hwidDeviceLimit"))
        if current < base:
            await remna.update_user(remna_id, hwidDeviceLimit=base)
            log.info("Пользователь %s: базовый лимит устройств = %d", remna_id, base)
    except RemnaError as exc:
        log.warning("Не удалось выставить базовый лимит: %s", exc)


async def add_device_slot(telegram_id: int) -> int:
    """Поднимает лимит устройств на +1. Возвращает новый лимит."""
    base = base_limit()
    remna_id = await _remna_id(telegram_id)
    if not remna_id:
        raise RemnaError("Пользователь не найден в панели — сначала оформите подписку")
    remna = get_remna()
    current = _as_limit((await remna.get_user(remna_id)).get("hwidDeviceLimit"))
    new_limit = max(current, base) + 1
    await remna.update_user(remna_id, hwidDeviceLimit=new_limit)
    log.info("Пользователь %s: добавлено устройство, лимит = %d", remna_id, new_limit)
    return new_limit


async def notify_device_added(telegram_id: int, limit: int | None) -> None:
    """Сообщение клиенту об успешной докупке устройства."""
    from aiogram.types import InlineKeyboardMarkup

    from app.services import notifications

    kb = InlineKeyboardMarkup(inline_keyboard=[[notifications.btn("Меню", "menu:back")]])
    count = limit if limit else 1
    text = (
        "<b>Дополнительное устройство добавлено</b>\\n\\n"
        f"Теперь к подписке можно подключить устройств: <b>{count}</b>\\n\\n"
        "Обновите подписку в приложении, чтобы изменения применились."
    )
    await notifications.send_message(telegram_id, text, reply_markup=kb)
'''

SHOP_BUY_DEVICE = '''

async def _buy_device(cb: CallbackQuery) -> None:
    """Покупка дополнительного устройства (HWID-слот)."""
    if cb.from_user is None or cb.message is None:
        await cb.answer()
        return
    telegram_id = cb.from_user.id
    await upsert_local_user(telegram_id, cb.from_user.username)
    order = await orders.create_order(
        telegram_id,
        tariff_code=device_slots.DEVICE_CODE,
        tariff_days=0,
        price=device_slots.slot_price(),
    )
    pay_amount = fmt_money(display_amount(order.expected_price))
    text = (
        "<b>Дополнительное устройство</b>\\n\\n"
        f"К оплате: <b>{pay_amount} ₽</b>\\n"
        f"Заказ: <code>{order.order_id}</code>\\n\\n"
        "После оплаты лимит устройств увеличится автоматически."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [url_btn(f"💳 Оплатить {pay_amount} ₽", build_payment_url(order))],
            [btn("💳 Проверить оплату", f"chk:{order.order_id}")],
            [btn("⬅️ К тарифам", "menu:shop")],
        ]
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await send_message(telegram_id, text, reply_markup=kb)
    await cb.answer()
'''


def repair_markdown(text: str) -> tuple[str, int]:
    """Чинит последствия копипаста: '[user(x)](http://user(x))' -> 'user(x)'.

    Markdown-ссылки вида '[текст](http://...)': оставляем только текст.
    Скобки внутри URL балансируются, поэтому вложенные '(' и ')' не мешают.
    """
    fixed = 0
    out_lines: list[str] = []
    for line in text.split("\n"):
        cur = line
        while True:
            m = re.search(r"\[([^\[\]]+)\]\(https?://", cur)
            if not m:
                break
            start = m.start()
            i = m.end()
            depth = 1
            while i < len(cur) and depth > 0:
                ch = cur[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                i += 1
            cur = cur[:start] + m.group(1) + cur[i:]
            fixed += 1
        out_lines.append(cur)
    return "\n".join(out_lines), fixed


def sub1(text: str, pattern: str, repl: str) -> tuple[str, int]:
    return re.subn(pattern, repl, text, count=1, flags=re.M)


def patch_orders(text: str) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    if "device_slots" not in text:
        text, n = sub1(
            text,
            r"^from app\.services import notifications$",
            "from app.services import device_slots, notifications",
        )
        if n != 1:
            return None, ["orders.py: не найден импорт 'from app.services import notifications'"]
        notes.append("orders.py: импорт device_slots")
    if "add_device_slot" not in text:
        text, n = sub1(
            text,
            r"^( {12})await provision_user\(order\.telegram_id, order\.tariff_days\)$",
            r"\1if order.tariff_code == device_slots.DEVICE_CODE:\n"
            r"\1    await device_slots.add_device_slot(order.telegram_id)\n"
            r"\1else:\n"
            r"\1    await provision_user(order.telegram_id, order.tariff_days)\n"
            r"\1    await device_slots.ensure_base_limit(order.telegram_id)",
        )
        if n != 1:
            return None, ["orders.py: не найдена строка выдачи подписки (provision_user)"]
        notes.append("orders.py: выдача слота + базовый лимит 1 устройство")
    if "notify_device_added" not in text:
        text, n = sub1(
            text,
            r"^( {4})await notifications\.notify_payment_success\(fresh\)$",
            r"\1if order.tariff_code == device_slots.DEVICE_CODE:\n"
            r"\1    await device_slots.notify_device_added(\n"
            r"\1        order.telegram_id, await device_slots.get_device_limit(order.telegram_id)\n"
            r"\1    )\n"
            r"\1else:\n"
            r"\1    await notifications.notify_payment_success(fresh)",
        )
        if n != 1:
            return None, ["orders.py: не найдено уведомление об оплате (notify_payment_success)"]
        notes.append("orders.py: уведомление о добавленном устройстве")
    return text, notes


def _shop_excerpt(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    idx = next((i for i, line in enumerate(lines) if "cb_buy" in line), None)
    if idx is not None:
        lo, hi = max(0, idx - 5), min(len(lines), idx + 40)
        body = [f"   {i + 1}: {lines[i]}" for i in range(lo, hi)]
    else:
        body = [f"   {i + 1}: {line}" for i, line in enumerate(lines[:60])]
    return ["   --- фрагмент файла (пришли его мне) ---"] + body + ["   --- конец фрагмента ---"]


def _device_branch(indent: str) -> str:
    return (
        f"{indent}if code == device_slots.DEVICE_CODE:\n"
        f"{indent}    await _buy_device(cb)\n"
        f"{indent}    return\n\n"
    )


def patch_shop(text: str) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    if "device_slots" not in text:
        text, n = sub1(
            text,
            r"^from app\.services import orders$",
            "from app.services import device_slots, orders",
        )
        if n != 1:
            return None, ["handlers_shop.py: не найден импорт 'from app.services import orders'"]
        notes.append("handlers_shop.py: импорт device_slots")

    # список тарифов: кнопка «Ещё устройство»
    if "buy:device" not in text:
        text, n = sub1(
            text,
            r'^(\s*)rows\.append\(\[btn\("⬅️ Назад в меню", "menu:back"\)\]\)\s*$',
            lambda m: (
                m.group(1)
                + 'rows.append([btn(f"➕ Ещё устройство — {format_price(device_slots.slot_price())}", "buy:device")])\n'
                + m.group(1)
                + 'rows.append([btn("⬅️ Назад в меню", "menu:back")])'
            ),
        )
        if n != 1:
            return None, ["handlers_shop.py: не найдена кнопка 'Назад в меню' в списке тарифов"]
        notes.append("handlers_shop.py: кнопка «Ещё устройство»")

    # ветка покупки устройства — 3 варианта, любой отступ
    if "_buy_device" not in text:
        hook = None
        for name, pattern, where in (
            (
                "после 'code = cb.data.split(...)'",
                r"^([ \t]*)code = cb\.data\.split\([^\n]*\)[^\n]*$",
                "after",
            ),
            (
                "перед 'tariff = await get_tariff(code)'",
                r"^([ \t]*)tariff = await get_tariff\(code\)",
                "before",
            ),
        ):
            m = re.search(pattern, text, re.M)
            if m:
                indent = m.group(1)
                snippet = _device_branch(indent).rstrip("\n")
                if where == "after":
                    pos = m.end()
                    text = text[:pos] + "\n" + snippet + "\n" + text[pos:]
                else:
                    pos = m.start()
                    text = text[:pos] + snippet + "\n\n" + text[pos:]
                notes.append(f"handlers_shop.py: ветка покупки устройства ({name})")
                hook = name
                break
        if hook is None:
            m = re.search(r"^([ \t]*)async def cb_buy\([^\n]*\)[^\n]*:\s*\n", text, re.M)
            if m is None:
                return None, [
                    "handlers_shop.py: не найдены ни 'code = cb.data.split(...)', ни "
                    "'tariff = await get_tariff(code)', ни 'async def cb_buy(...)'",
                ] + _shop_excerpt(APP / "telegram" / "handlers_shop.py")
            indent = m.group(1) + "    "
            pos = m.end()
            docstring = re.match(r"[ \t]*(?:\'\'\'|\"\"\")(?:.|\n)*?(?:\'\'\'|\"\"\")\s*\n", text[pos:])
            if docstring:
                pos += docstring.end()
            text = (
                text[:pos]
                + f"{indent}code = cb.data.split(':', 1)[1]\n"
                + _device_branch(indent)
                + text[pos:]
            )
            notes.append("handlers_shop.py: ветка покупки устройства (после 'async def cb_buy')")
        text = text.rstrip("\n") + "\n" + SHOP_BUY_DEVICE
    return text, notes


def patch_config(text: str) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    if "price_device_slot" not in text:
        text, n = sub1(
            text,
            r"^    # ---- База данных ----$",
            "    # ---- Дополнительные устройства ----\n"
            "    price_device_slot: Decimal = Field(\n"
            '        default=Decimal("20"), validation_alias=AliasChoices("PRICE_DEVICE_SLOT", "PRICE_DEVICE")\n'
            "    )\n"
            "    device_base_limit: int = Field(\n"
            '        default=1, validation_alias=AliasChoices("DEVICE_BASE_LIMIT")\n'
            "    )\n\n"
            "    # ---- База данных ----",
        )
        if n != 1:
            return None, ["config.py: не найден раздел '---- База данных ----'"]
        notes.append("config.py: PRICE_DEVICE_SLOT + DEVICE_BASE_LIMIT")
    return text, notes


def update_env() -> list[str]:
    notes: list[str] = []
    fixes = {
        "PRICE_7_DAYS": "50",
        "PRICE_30_DAYS": "100",
        "PRICE_90_DAYS": "300",
        "PRICE_180_DAYS": "600",
        "PRICE_365_DAYS": "1200",
        "YOOMONEY_FEE_MODE": "absorb",
        "YOOMONEY_FEE_PERCENT": "3",
        "PRICE_DEVICE_SLOT": "20",
        "DEVICE_BASE_LIMIT": "1",
    }
    if not ENV.exists():
        return [".env: файл не найден — пропущено"]
    shutil.copy2(ENV, unique_path(Path(str(ENV) + ".bak." + STAMP)))
    out: list[str] = []
    seen: set[str] = set()
    for line in ENV.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if ("=" in line and not line.lstrip().startswith("#")) else None
        if key in fixes:
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{key}={fixes[key]}")
        else:
            out.append(line)
    for key, value in fixes.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    notes.append(".env: цены 50/100/300/600/1200, комиссия absorb 3%, PRICE_DEVICE_SLOT=20, DEVICE_BASE_LIMIT=1")
    return notes


def main() -> int:
    print(f"{SCRIPT_VERSION} | корень бота: {ROOT}")
    if not APP.is_dir():
        print(f"!! Каталог не найден: {APP}")
        print("   Укажи корень бота: VPNBOT_DIR=/opt/vpnbot/vpn-bot python3 ...")
        return 1

    files = {
        "orders": APP / "services" / "orders.py",
        "shop": APP / "telegram" / "handlers_shop.py",
        "config": APP / "config.py",
    }
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        print("!! Не найдены файлы: " + ", ".join(missing))
        return 1

    notes: list[str] = []
    results: dict[str, str] = {}
    repaired_total = 0
    for key, fn in (("orders", patch_orders), ("shop", patch_shop), ("config", patch_config)):
        original = files[key].read_text(encoding="utf-8")
        fixed, repaired = repair_markdown(original)
        repaired_total += repaired
        new_text, part = fn(fixed)
        if new_text is None:
            print("!! Патч остановлен, файлы НЕ изменены:")
            for msg in part:
                print("   " + msg)
            return 1
        results[key] = new_text
        notes.extend(part)

    # бэкап и запись
    if APP.exists():
        backup = unique_path(BACKUP_DIR / f"vpnbot-app-backup-{STAMP}")
        shutil.copytree(APP, backup)
        print(f"бэкап кода: {backup}")
    for key, path in files.items():
        path.write_text(results[key], encoding="utf-8")

    slots_path = APP / "services" / "device_slots.py"
    slots_text, _ = repair_markdown(SLOTS_MODULE)
    slots_path.write_text(slots_text, encoding="utf-8")

    targets = [
        APP / "services" / "device_slots.py",
        APP / "services" / "orders.py",
        APP / "config.py",
        APP / "telegram" / "handlers_shop.py",
    ]
    if repaired_total:
        notes.append(f"устранены следы копипаста в коде: исправлено {repaired_total} шт.")

    for path in targets:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"!! Синтаксическая ошибка: {path}")
            print(exc)
            print(f"Откатить можно так: rm -rf {APP} && cp -r {BACKUP} {APP}")
            return 1

    notes.extend(update_env())

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(" •", note)
    print("\nСинтаксис всех файлов — ОК.")
    print("Дальше: docker compose up -d --build   (в каталоге бота)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
