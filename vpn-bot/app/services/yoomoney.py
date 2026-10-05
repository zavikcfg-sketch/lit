"""YooMoney: ссылка на оплату (quickpay), проверка подписи вебхука и
идемпотентная обработка HTTP-уведомлений + ручная проверка оплаты по API.

Оплата ВСЕГДА определяется по уникальному label + operation_id, никогда — по сумме.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.models import Order
from app.services import orders
from app.utils import fmt_money

log = logging.getLogger("app.yoomoney")

QUICKPAY_URL = "https://yoomoney.ru/quickpay/confirm"


# ---------------------------------------------------------------- суммы/комиссия

def _q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def display_amount(expected: Decimal) -> Decimal:
    """Сумма к оплате, показываемая клиенту (с учётом режима комиссии).

    client_fixed: клиент платит комиссию сверху -> к сумме добавляется процент.
    """
    s = get_settings()
    expected = _q2(expected)
    if s.yoomoney_fee_mode == "client_fixed":
        fee = expected * s.yoomoney_fee_percent / Decimal("100")
        return _q2(expected + fee)
    return expected


def required_amount(expected: Decimal) -> Decimal:
    """Минимальная сумма, которая должна прийти на кошелёк.

    absorb: миримся с удержанием комиссии -> принимаем чуть меньше ожидаемого.
    """
    s = get_settings()
    expected = _q2(expected)
    if s.yoomoney_fee_mode == "absorb":
        fee = expected * s.yoomoney_fee_percent / Decimal("100")
        return _q2(expected - fee)
    return expected


# ---------------------------------------------------------------- quickpay URL

def build_payment_url(order: Order) -> str:
    """Ссылка на оплату YooMoney (форма quickpay, оплата картой — paymentType=AC)."""
    s = get_settings()
    params = {
        "receiver": s.yoomoney_wallet,
        "quickpay-form": "shop",
        "targets": f"Оплата VPN-подписки ({order.tariff_days} дн.), заказ {order.order_id}",
        "paymentType": "AC",
        "label": order.label,
        "sum": fmt_money(display_amount(order.expected_price)),
    }
    if s.bot_username:
        params["successURL"] = f"https://t.me/{s.bot_username}"
    return f"{QUICKPAY_URL}?{urlencode(params)}"


# ---------------------------------------------------------------- подпись вебхука

def verify_signature(params: dict[str, str], secret: str) -> bool:
    """Проверяет sha1_hash (или sha256_hash) уведомления YooMoney.

    Строка подписи: notification_type & operation_id & amount & currency &
    datetime & sender & codepro & <секрет> & label
    """
    if not secret:
        return False

    def g(k: str) -> str:
        return str(params.get(k) or "")

    base = "".join(
        [
            g("notification_type"),
            g("operation_id"),
            g("amount"),
            g("currency"),
            g("datetime"),
            g("sender"),
            g("codepro"),
            secret,
            g("label"),
        ]
    ).encode("utf-8")

    sha256_hash = (params.get("sha256_hash") or "").strip().lower()
    if sha256_hash and hashlib.sha256(base).hexdigest() == sha256_hash:
        return True
    sha1_hash = (params.get("sha1_hash") or "").strip().lower()
    if sha1_hash and hashlib.sha1(base).hexdigest() == sha1_hash:
        return True
    return False


# ---------------------------------------------------------------- rate limiter

class SimpleRateLimiter:
    """Простой in-memory sliding window лимитер (на процесс)."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max(1, int(max_events))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        if len(self._hits) > 10000:  # защита от роста памяти
            self._hits.clear()
        return True


# ---------------------------------------------------------------- webhook

async def process_notification(params: dict[str, str], client_ip: str = "-") -> tuple[int, str]:
    """Обработка HTTP-уведомления YooMoney. Возвращает (HTTP-статус, текст).

    Идемпотентность:
      * один operation_id обрабатывается один раз (payment_events.operation_id UNIQUE);
      * заказ переводится в paid одним атомарным UPDATE ... WHERE status='pending';
      * повторное уведомление не выдаёт дополнительные дни.
    """
    s = get_settings()
    label = (params.get("label") or "").strip()

    if not label:
        return 200, "no-label"
    if not label.startswith("rw_"):
        return 200, "foreign-label"

    order = await orders.get_order_by_label(label)
    if order is None:
        await orders.log_service_error(
            "webhook", f"Уведомление по неизвестному label={label} (ip={client_ip})", level="warning"
        )
        return 200, "order-not-found"

    secret = s.yoomoney_notification_secret
    if not secret:
        await orders.log_service_error(
            "yoomoney",
            "YOOMONEY_NOTIFICATION_SECRET не задан — уведомление отклонено",
            level="error",
        )
        return 403, "secret-not-configured"

    if not verify_signature(params, secret):
        await orders.log_service_error(
            "yoomoney",
            f"Неверная подпись уведомления для label={label} (ip={client_ip})",
            level="warning",
        )
        return 403, "bad-signature"

    operation_id = (params.get("operation_id") or "").strip()
    if not operation_id:
        return 400, "no-operation-id"

    if await orders.event_exists(operation_id):
        return 200, "duplicate"

    currency = (params.get("currency") or "").strip().upper()
    if currency not in ("643", "RUB"):
        await orders.log_service_error(
            "yoomoney", f"Неожиданная валюта {currency} по заказу {order.order_id}", level="warning"
        )
        return 400, "bad-currency"

    if (params.get("codepro") or "false").strip().lower() == "true":
        return 400, "codepro-true"
    if (params.get("unaccepted") or "false").strip().lower() == "true":
        return 400, "unaccepted"

    try:
        amount = Decimal(str(params.get("amount") or "0").replace(",", "."))
    except InvalidOperation:
        return 400, "bad-amount"

    required = required_amount(order.expected_price)
    if amount + Decimal("0.01") < required:
        await orders.log_service_error(
            "yoomoney",
            f"Сумма меньше ожидаемой: заказ {order.order_id}, получено {amount}, ожидалось {required}",
            level="warning",
        )
        # не подтверждаем заказ (остаётся pending), повторов не просим
        return 200, "amount-mismatch"

    raw_hash = params.get("sha1_hash") or params.get("sha256_hash") or ""
    ok, code = await orders.process_successful_payment(
        order, operation_id=operation_id, amount=amount, raw_hash=raw_hash
    )
    if not ok:
        return 500, code
    log.info("Платёж по заказу %s подтверждён (%s)", order.order_id, code)
    return 200, code


# ---------------------------------------------------- ручная проверка оплаты

async def fetch_operations_by_label(label: str) -> list[dict] | None:
    """История операций YooMoney по label (YOOMONEY_ACCESS_TOKEN). None = ошибка/нет токена."""
    s = get_settings()
    if not s.yoomoney_access_token:
        return None
    headers = {"Authorization": f"Bearer {s.yoomoney_access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://yoomoney.ru/api/operations-history",
                headers=headers,
                params={"type": "in", "label": label},
            )
            if resp.status_code == 200:
                ops = (resp.json() or {}).get("operations") or []
                if ops:
                    return ops
            # легаси-эндпоинт как fallback
            resp = await client.post(
                "https://yoomoney.ru/api/operation-history",
                headers=headers,
                data={"type": "in", "label": label},
            )
            if resp.status_code == 200:
                return (resp.json() or {}).get("operations") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Ошибка запроса истории YooMoney: %s", type(exc).__name__)
    return None


async def try_manual_confirm(order: Order) -> tuple[bool, str]:
    """Кнопка «Проверить оплату»: ищет платёж по label через API и подтверждает заказ."""
    operations = await fetch_operations_by_label(order.label)
    if operations is None:
        return (
            False,
            "Автопроверка недоступна (не настроен YOOMONEY_ACCESS_TOKEN или API недоступен). "
            "Если вы уже оплатили — подтверждение придёт автоматически в течение пары минут.",
        )

    for op in operations:
        if str(op.get("label") or "") != order.label:
            continue
        status = str(op.get("status") or "success").lower()
        if status != "success":
            continue
        try:
            amount = Decimal(str(op.get("amount")))
        except InvalidOperation:
            continue
        required = required_amount(order.expected_price)
        if amount + Decimal("0.01") < required:
            return (
                False,
                f"Найден платёж на {fmt_money(amount)} ₽, но это меньше ожидаемой суммы "
                f"({fmt_money(required)} ₽). Обратитесь в поддержку.",
            )
        ok, code = await orders.process_successful_payment(
            order,
            operation_id=str(op.get("operation_id") or f"manual-{order.order_id}"),
            amount=amount,
            raw_hash="manual-check",
        )
        if ok:
            if code == "already":
                return True, "Эта оплата уже была подтверждена ранее."
            return True, "✅ Оплата подтверждена! Подписка активирована/продлена."
        return False, "Оплата найдена, но произошла ошибка обработки. Попробуйте ещё раз через минуту."

    return (
        False,
        "Оплата пока не найдена. Если вы уже оплатили — подождите пару минут: "
        "платёж подтвердится автоматически, я пришлю уведомление.",
    )
