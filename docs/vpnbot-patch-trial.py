#!/usr/bin/env python3
"""Пробный период (тест на 1 день) для vpnbot — версия 2026-10-07.1.

Что добавляет:
  * app/services/trial.py — логика теста: один раз на аккаунт, только если нет
    действующей подписки; выдаёт настоящую подписку Remnawave на 1 день;
  * кнопку «🎁 Тест на 1 день — бесплатно» в магазине (Магазин → кнопка);
  * ветку обработки buy:trial в handlers_shop.py;
  * настройки TRIAL_DAYS / TRIAL_ENABLED в config.py и .env.

Идемпотентен: повторный запуск ничего не ломает. Делает бэкап app/ и .env.

Запуск:  python3 /root/vpnbot-patch-trial.py
Дальше:  docker compose up -d --build
"""
from __future__ import annotations

import os
import py_compile
import re
import shutil
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "patch-trial 2026-10-07.1"

ROOT = Path(os.environ.get("VPNBOT_DIR", "/opt/vpnbot/vpn-bot"))
BACKUP_DIR = Path(os.environ.get("VPNBOT_BACKUP_DIR", "/root"))
APP = ROOT / "app"
ENV = ROOT / ".env"
STAMP = time.strftime("%Y%m%d-%H%M%S")

TRIAL_MODULE = '''"""Пробный период: бесплатный тест на 1 день."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session
from app.models import Order, User
from app.services import orders as orders_service

log = logging.getLogger("app.trial")

TRIAL_CODE = "trial"


def trial_days() -> int:
    """Сколько дней даём в тесте (TRIAL_DAYS, по умолчанию 1)."""
    try:
        value = int(get_settings().trial_days)
    except Exception:  # noqa: BLE001
        value = 1
    return max(1, min(value, 7))


def trial_enabled() -> bool:
    """Включён ли тест (TRIAL_ENABLED)."""
    try:
        return bool(get_settings().trial_enabled)
    except Exception:  # noqa: BLE001
        return True


async def trial_used(telegram_id: int) -> bool:
    """Пользовался ли уже тестом (по оплаченному пробному заказу)."""
    try:
        async with get_session() as session:
            found = (
                await session.execute(
                    select(Order.id)
                    .where(
                        Order.telegram_id == int(telegram_id),
                        Order.tariff_code == TRIAL_CODE,
                        Order.status == "paid",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        log.warning("Тест: не смог проверить историю (%s)", exc)
        return True  # при сомнении второй тест не даём
    return found is not None


async def has_active_subscription(telegram_id: int) -> bool:
    """Есть ли действующая подписка (по локальной записи)."""
    try:
        async with get_session() as session:
            local = (
                await session.execute(
                    select(User).where(User.telegram_id == int(telegram_id))
                )
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        return False
    if local is None or not getattr(local, "expire_at", None):
        return False
    expire = local.expire_at
    if expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)
    return expire > datetime.now(timezone.utc)


async def subscription_url(telegram_id: int) -> str | None:
    """Ссылка подписки из локальной записи."""
    try:
        async with get_session() as session:
            local = (
                await session.execute(
                    select(User).where(User.telegram_id == int(telegram_id))
                )
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        return None
    return str(getattr(local, "subscription_url", "") or "") or None


async def _set_order_status(order, status: str) -> None:
    """Помечает пробный заказ (paid/failed), чтобы тест не сгорал при ошибке."""
    try:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(Order).where(Order.order_id == order.order_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = status
            if status == "paid":
                row.received_amount = Decimal("0")
                row.operation_id = f"trial-{order.order_id}"
                row.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Тест: не удалось обновить заказ %s (%s)", order.order_id, exc)


async def claim_trial(telegram_id: int) -> tuple[bool, str]:
    """Выдаёт пробную подписку. Возвращает (ok, код).

    Коды: ok | used | active | disabled | error:<...>
    """
    if not trial_enabled():
        return False, "disabled"
    if await trial_used(telegram_id):
        return False, "used"
    if await has_active_subscription(telegram_id):
        return False, "active"

    days = trial_days()
    order = await orders_service.create_order(
        telegram_id, tariff_code=TRIAL_CODE, tariff_days=days, price=Decimal("0")
    )
    try:
        await orders_service.provision_user(telegram_id, days)
    except Exception as exc:  # noqa: BLE001
        log.warning("Тест: выдача не удалась (%s)", exc)
        await _set_order_status(order, "failed")
        return False, f"error:{type(exc).__name__}"
    try:
        from app.services import device_slots

        await device_slots.ensure_base_limit(telegram_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("Тест: лимит устройств не выставлен (%s)", exc)
    await _set_order_status(order, "paid")
    log.info("Тест выдан пользователю %s на %d дн.", telegram_id, days)
    return True, "ok"
'''

TRIAL_HANDLER = '''

async def _start_trial(cb) -> None:
    """Выдача бесплатного теста (один раз на аккаунт)."""
    user = getattr(cb, "from_user", None)
    message = getattr(cb, "message", None)
    if user is None or message is None:
        await cb.answer()
        return
    telegram_id = user.id

    try:
        ok, code = await trial.claim_trial(telegram_id)
    except Exception as exc:  # noqa: BLE001
        ok, code = False, f"error:{type(exc).__name__}"

    if not ok:
        if code == "used":
            text = (
                "🎁 <b>Тестовый период уже использован</b>\\n\\n"
                "Тест даётся один раз на аккаунт. Подписка в магазине — от 50 ₽."
            )
        elif code == "active":
            text = (
                "🎁 <b>У вас уже есть действующая подписка</b>\\n\\n"
                "Тестовый период доступен только новым пользователям."
            )
        elif code == "disabled":
            text = "🎁 <b>Тестовый период сейчас недоступен</b>\\n\\nПопробуйте позже."
        else:
            text = (
                "⚠️ <b>Не удалось выдать тест</b>\\n\\n"
                "Попробуйте ещё раз через минуту или напишите в поддержку."
            )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [btn("💎 Тарифы и подписка", "menu:shop")],
                [btn("⬅️ Назад", "menu:back")],
            ]
        )
    else:
        url = await trial.subscription_url(telegram_id)
        days = trial.trial_days()
        text = (
            "🎉 <b>Тестовый доступ активирован</b>\\n\\n"
            f"Срок: <b>{days} дн.</b> · Устройств: <b>1</b>\\n"
            "Доступ: <b>полный</b> — все локации, без ограничений скорости и трафика.\\n"
        )
        if url:
            text += f"\\nСсылка для подключения:\\n<code>{url}</code>\\n"
        text += (
            "\\nУстановите приложение (Happ, v2rayTun, Hiddify) и вставьте ссылку.\\n\\n"
            "Понравилось? Оформите подписку в магазине — от 50 ₽, "
            "и можно докупить ещё одно устройство за 20 ₽."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [btn("💎 Оформить подписку", "menu:shop")],
                [btn("⬅️ Назад в меню", "menu:back")],
            ]
        )

    try:
        await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        try:
            await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            pass
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
'''


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(path.name + f"-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def patch_import(text: str) -> tuple[str | None, list[str]]:
    if "trial.TRIAL_CODE" in text or re.search(r"from app\.services import .*\btrial\b", text):
        return text, []
    m = re.search(r"^from app\.services import ([\w, ]*orders[\w, ]*)$", text, re.M)
    if m is None:
        return None, ["handlers_shop.py: не найден импорт 'from app.services import ... orders ...'"]
    names = m.group(1).rstrip()
    if not names.endswith(","):
        names += ","
    names += " trial"
    return text[: m.start(1)] + names + text[m.end(1):], ["handlers_shop.py: импорт trial"]


def patch_button(text: str) -> tuple[str | None, list[str]]:
    if '"buy:trial"' in text:
        return text, []
    line = '{indent}rows.append([btn("🎁 Тест на 1 день — бесплатно", "buy:trial")])\n'
    for pattern in (
        r'^(\s*)rows\.append\(\[btn\(f"➕ Ещё устройство[^\n]*$',
        r'^(\s*)rows\.append\(\[btn\("⬅️ Назад в меню", "menu:back"\)\]\)\s*$',
    ):
        m = re.search(pattern, text, re.M)
        if m:
            return text[: m.start()] + line.format(indent=m.group(1)) + text[m.start():], [
                "handlers_shop.py: кнопка «Тест на 1 день»"
            ]
    return None, ["handlers_shop.py: не нашёл, куда вставить кнопку теста"]


def patch_branch(text: str) -> tuple[str | None, list[str]]:
    if "_start_trial" in text:
        return text, []
    m = re.search(r"^([ \t]*)if code == device_slots\.DEVICE_CODE:\n", text, re.M)
    if m:
        indent = m.group(1)
        block = (
            f"{indent}if code == trial.TRIAL_CODE:\n"
            f"{indent}    await _start_trial(cb)\n"
            f"{indent}    return\n\n"
        )
        return text[: m.start()] + block + text[m.start():], ["handlers_shop.py: ветка buy:trial"]
    m = re.search(r"^([ \t]*)code = cb\.data\.split\([^\n]*\)[^\n]*$", text, re.M)
    if m:
        indent = m.group(1)
        block = (
            f"\n{indent}if code == trial.TRIAL_CODE:\n"
            f"{indent}    await _start_trial(cb)\n"
            f"{indent}    return\n"
        )
        return text[: m.end()] + block + text[m.end():], [
            "handlers_shop.py: ветка buy:trial (после разбора callback)"
        ]
    return None, ["handlers_shop.py: не нашёл функцию cb_buy, куда вставить ветку теста"]


def patch_config(text: str) -> tuple[str | None, list[str]]:
    if "trial_days" in text:
        return text, []
    m = re.search(r"^(\s*)# ---- База данных ----$", text, re.M)
    if m is None:
        return None, ["config.py: не найден раздел '---- База данных ----'"]
    indent = m.group(1)
    block = (
        f"{indent}# ---- Тестовый период ----\n"
        f"{indent}trial_days: int = Field(default=1, validation_alias=AliasChoices(\"TRIAL_DAYS\"))\n"
        f"{indent}trial_enabled: bool = Field(default=True, validation_alias=AliasChoices(\"TRIAL_ENABLED\"))\n\n"
    )
    return text[: m.start()] + block + text[m.start():], ["config.py: TRIAL_DAYS + TRIAL_ENABLED"]


def update_env() -> list[str]:
    if not ENV.exists():
        return [".env: файл не найден — пропущено"]
    shutil.copy2(ENV, unique_path(Path(str(ENV) + ".bak." + STAMP)))
    fixes = {"TRIAL_DAYS": "1", "TRIAL_ENABLED": "1"}
    lines = ENV.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
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
    return [".env: TRIAL_DAYS=1, TRIAL_ENABLED=1"]


def main() -> int:
    print(f"{SCRIPT_VERSION} | корень бота: {ROOT}")
    if not APP.is_dir():
        print(f"!! Каталог не найден: {APP}")
        print("   Можно указать корень: VPNBOT_DIR=/opt/vpnbot/vpn-bot python3 ...")
        return 1

    shop_path = APP / "telegram" / "handlers_shop.py"
    config_path = APP / "config.py"
    for path in (shop_path, config_path):
        if not path.is_file():
            print(f"!! не найден файл {path}")
            return 1

    notes: list[str] = []
    shop_text = shop_path.read_text(encoding="utf-8")
    handler_exists = "async def _start_trial" in shop_text
    for fn in (patch_import, patch_button, patch_branch):
        new_text, part = fn(shop_text)
        if new_text is None:
            print("!! Патч остановлен, файлы НЕ изменены:")
            for msg in part:
                print("   " + msg)
            return 1
        shop_text = new_text
        notes.extend(part)
    if not handler_exists:
        shop_text = shop_text.rstrip("\n") + "\n" + TRIAL_HANDLER

    config_text = config_path.read_text(encoding="utf-8")
    new_config, part = patch_config(config_text)
    if new_config is None:
        print("!! Патч остановлен, файлы НЕ изменены:")
        for msg in part:
            print("   " + msg)
        return 1
    config_text = new_config
    notes.extend(part)

    if APP.exists():
        backup = unique_path(BACKUP_DIR / f"vpnbot-app-backup-{STAMP}")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(APP, backup)
        print(f"бэкап кода: {backup}")

    (APP / "services" / "trial.py").write_text(TRIAL_MODULE, encoding="utf-8")
    shop_path.write_text(shop_text, encoding="utf-8")
    config_path.write_text(config_text, encoding="utf-8")

    targets = [APP / "services" / "trial.py", shop_path, config_path]
    for path in targets:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"!! Синтаксическая ошибка: {path}")
            print(exc)
            print(f"Откат: rm -rf {APP} && cp -r {backup} {APP}")
            return 1

    notes.extend(update_env())

    print("\n=== ЧТО СДЕЛАНО ===")
    for note in notes:
        print(" •", note)
    print("\nСинтаксис всех файлов — ОК.")
    print("\nДальше:")
    print("  docker compose up -d --build")
    print("\nПроверка в боте: Магазин → «🎁 Тест на 1 день — бесплатно».")
    print("Первый раз — активируется на 1 день; повторно — «уже использован».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
