#!/usr/bin/env python3
# Smoke-тест проекта (без реальных внешних сервисов). Запуск:
#   python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r vpn-bot/requirements.txt
#   /tmp/venv/bin/python scripts/smoke_test.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vpn-bot"))
"""Smoke-тест всего проекта без реальных внешних сервисов (Remnawave замокан)."""
import asyncio
import hashlib
import os

os.environ.update(
    BOT_TOKEN="123456:TEST_TOKEN",
    REMNAWAVE_API_URL="https://panel.example.com",
    REMNAWAVE_API_TOKEN="testtoken",
    YOOMONEY_WALLET="4100111111111111",
    YOOMONEY_NOTIFICATION_SECRET="SECRET123",
    YOOMONEY_ACCESS_TOKEN="",
    ADMIN_ID="111111111",
    ADMIN_USER="admin",
    ADMIN_PASSWORD="testpass123",
    ADMIN_SESSION_SECRET="a" * 32,
    PRICES_7="111",          # проверяем алиас
    PRICE_30_DAYS="250",
    DATABASE_URL="sqlite+aiosqlite:////tmp/smoke_test.db",
    LOG_LEVEL="WARNING",
)
if os.path.exists("/tmp/smoke_test.db"):
    os.remove("/tmp/smoke_test.db")

HASH_FIELDS = ("notification_type", "operation_id", "amount", "currency",
               "datetime", "sender", "codepro")


def sign(params: dict, secret: str, field: str = "sha1_hash") -> str:
    base = "".join(params[k] for k in HASH_FIELDS) + secret + params["label"]
    if field == "sha256_hash":
        return hashlib.sha256(base.encode()).hexdigest()
    return hashlib.sha1(base.encode()).hexdigest()


async def fake_provision(tg, days):
    from sqlalchemy import select
    from app.database import get_session
    from app.models import User
    from app.utils import expire_after

    async with get_session() as s:
        u = (await s.execute(select(User).where(User.telegram_id == tg))).scalar_one_or_none()
        if u is None:
            u = User(
                telegram_id=tg, remnawave_user_id=f"uuid-{tg}", username=f"tg_{tg}",
                subscription_url=f"https://panel.example.com/api/sub/SHORT{tg}",
                expire_at=expire_after(days), status="ACTIVE",
            )
            s.add(u)
        else:
            u.expire_at = expire_after(days)
            u.status = "ACTIVE"
        await s.commit()
    return u


async def main():
    from app.database import init_db
    await init_db()

    # --- импортируем всё приложение (ловим ошибки импорта/сборки роутеров) ---
    from app.telegram import build_dispatcher
    dp = build_dispatcher()
    assert dp is not None
    import app.main  # noqa
    from app.admin.app import app as admin_app  # noqa

    from app.config import get_settings
    s = get_settings()
    assert s.yoomoney_fee_mode == "client_fixed"

    from app.services import notifications, orders, tariffs, yoomoney
    notifications.send_message = lambda *a, **k: _true()
    orders.provision_user = fake_provision

    # --- тарифы из .env (с алиасами) ---
    ts = await tariffs.get_all_tariffs()
    assert len(ts) == 5, ts
    t7 = await tariffs.get_tariff("7d")
    assert str(t7.price) == "111.00", t7.price
    t30 = await tariffs.get_tariff("30d")
    assert t30.days == 30 and str(t30.price) == "250.00"
    print("[ok] тарифы: сидирование, алиасы PRICES_*/PRICE_*_DAYS")

    # --- заказ ---
    order = await orders.create_order(8346538289, tariff_code=t30.code, tariff_days=t30.days, price=t30.price)
    assert order.label.startswith("rw_8346538289_") and len(order.label) == len("rw_8346538289_") + 6
    assert order.order_id.startswith("ord_")
    assert await orders.get_order_by_label(order.label) is not None
    print("[ok] заказ создан:", order.order_id, order.label)

    url = yoomoney.build_payment_url(order)
    assert "yoomoney.ru/quickpay/confirm" in url
    assert f"label={order.label}" in url and "receiver=4100111111111111" in url
    assert "sum=252.5" in url  # 250 + 1% (client_fixed)
    assert yoomoney.required_amount(t30.price) == __import__("decimal").Decimal("250.00")
    print("[ok] quickpay URL:", url)

    # --- вебхук: нет label / чужой label ---
    st, rs = await yoomoney.process_notification({"notification_type": "p2p-incoming"})
    assert (st, rs) == (200, "no-label")
    st, rs = await yoomoney.process_notification({"label": "some_else", "sha1_hash": "x"})
    assert (st, rs) == (200, "foreign-label")
    print("[ok] вебхук: мусорные уведомления отсекаются")

    # --- вебхук: неверная подпись ---
    p_bad = {
        "notification_type": "p2p-incoming", "operation_id": "op-bad", "amount": "252.50",
        "currency": "643", "datetime": "2026-10-05T12:00:00Z", "sender": "4100123456789",
        "codepro": "false", "label": order.label, "sha1_hash": "0" * 40,
    }
    st, rs = await yoomoney.process_notification(p_bad)
    assert (st, rs) == (403, "bad-signature")
    print("[ok] вебхук: подпись проверяется")

    # --- вебхук: успешная оплата ---
    params = {
        "notification_type": "p2p-incoming", "operation_id": "test-op-1", "amount": "252.50",
        "currency": "643", "datetime": "2026-10-05T12:00:00Z", "sender": "4100123456789",
        "codepro": "false", "label": order.label,
    }
    params["sha1_hash"] = sign(params, s.yoomoney_notification_secret)
    st, rs = await yoomoney.process_notification(dict(params))
    assert (st, rs) == (200, "ok"), (st, rs)

    o = await orders.get_order(order.order_id)
    assert o.status == "paid" and str(o.operation_id) == "test-op-1"
    u = await orders.get_local_user(8346538289)
    assert u.remnawave_user_id == "uuid-8346538289" and u.subscription_url
    print("[ok] вебхук: оплата принята, подписка выдана")

    # --- идемпотентность: тот же operation_id ---
    st, rs = await yoomoney.process_notification(dict(params))
    assert (st, rs) == (200, "duplicate")
    # --- другой operation_id по оплаченному заказу ---
    p2 = dict(params, operation_id="test-op-2")
    p2["sha1_hash"] = sign(p2, s.yoomoney_notification_secret)
    st, rs = await yoomoney.process_notification(p2)
    assert (st, rs) == (200, "already")
    print("[ok] идемпотентность: повторные уведомления не выдают дни")

    # --- нехватка суммы ---
    order3 = await orders.create_order(222333444, tariff_code=t30.code, tariff_days=30, price=t30.price)
    p3 = {
        "notification_type": "p2p-incoming", "operation_id": "test-op-3", "amount": "10",
        "currency": "643", "datetime": "2026-10-05T12:05:00Z", "sender": "4100123456789",
        "codepro": "false", "label": order3.label,
    }
    p3["sha1_hash"] = sign(p3, s.yoomoney_notification_secret)
    st, rs = await yoomoney.process_notification(p3)
    assert (st, rs) == (200, "amount-mismatch")
    assert (await orders.get_order(order3.order_id)).status == "pending"
    print("[ok] сумма меньше ожидаемой — заказ остаётся pending")

    # --- sha256 вариант ---
    order4 = await orders.create_order(222333444, tariff_code=t30.code, tariff_days=30, price=t30.price)
    p4 = {
        "notification_type": "p2p-incoming", "operation_id": "test-op-4", "amount": "252.50",
        "currency": "643", "datetime": "2026-10-05T12:10:00Z", "sender": "4100123456789",
        "codepro": "false", "label": order4.label,
    }
    p4["sha256_hash"] = sign(p4, s.yoomoney_notification_secret, "sha256_hash")
    st, rs = await yoomoney.process_notification(p4)
    assert (st, rs) == (200, "ok"), (st, rs)
    print("[ok] вебхук: поддерживается sha256_hash")

    # ---------------- админка ----------------
    from fastapi.testclient import TestClient

    with TestClient(admin_app) as client:
        assert client.get("/health").json()["status"] == "ok"
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and "/login" in r.headers["location"]

        r = client.post("/login", data={"username": "admin", "password": "wrong"}, follow_redirects=False)
        assert r.status_code == 401

        # CSRF: чужой Origin отклоняется
        r = client.post("/login", data={"username": "admin", "password": "testpass123"},
                        headers={"Origin": "https://evil.example"}, follow_redirects=False)
        assert r.status_code == 403

        r = client.post("/login", data={"username": "admin", "password": "testpass123"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")

        for path in ("/", "/users", "/users?q=8346538289", "/users?status=ACTIVE",
                     "/orders", f"/orders?q={order.order_id}", "/tariffs",
                     "/broadcast", "/logs?tab=actions", "/logs?tab=payments", "/logs?tab=errors"):
            resp = client.get(path)
            assert resp.status_code == 200, (path, resp.status_code, resp.text[:200])
        print("[ok] админка: вход, дашборд, users, orders, tariffs, broadcast, logs")

        # продление из админки
        from app.database import get_session
        from app.models import User
        from sqlalchemy import select
        async with get_session() as sess:
            uid = (await sess.execute(select(User.id).where(User.telegram_id == 8346538289))).scalar_one()
        r = client.post(f"/users/{uid}/extend", data={"days": "90", "back": "/users"}, follow_redirects=False)
        assert r.status_code == 303 and "k=ok" in r.headers["location"], r.headers.get("location")

        # переотправка по оплаченному заказу
        r = client.post(f"/orders/{order.order_id}/reissue", data={"back": "/orders"}, follow_redirects=False)
        assert r.status_code == 303, r.text

        # смена цены тарифа
        r = client.post(f"/tariffs/{t30.id}/save", data={"price": "299", "enabled": "1"}, follow_redirects=False)
        assert r.status_code == 303
        t30b = await tariffs.get_tariff("30d")
        assert str(t30b.price) == "299.00" and t30b.enabled
        print("[ok] админка: продление, переотправка, изменение тарифа")

        # рассылка: превью и запуск (без бота — send_message замокан)
        r = client.post("/broadcast/preview", data={"text": "Привет, мир!", "rate": "10", "targets": "all"},
                        follow_redirects=False)
        assert r.status_code == 200 and "Привет, мир!" in r.text
        r = client.post("/broadcast/send", follow_redirects=False)
        assert r.status_code == 303
        st_json = client.get("/broadcast/status").json()
        assert st_json["total"] >= 1
        print("[ok] админка: рассылка (превью/запуск/статус)")

        # вебхук через HTTP с валидной подписью
        order5 = await orders.create_order(555666777, tariff_code=t30.code, tariff_days=30, price=t30.price)
        p5 = {
            "notification_type": "p2p-incoming", "operation_id": "test-op-5", "amount": "252.50",
            "currency": "643", "datetime": "2026-10-05T12:15:00Z", "sender": "4100123456789",
            "codepro": "false", "label": order5.label,
        }
        p5["sha1_hash"] = sign(p5, s.yoomoney_notification_secret)
        r = client.post(s.yoomoney_webhook_path, data=p5)
        assert r.status_code == 200 and r.text == "ok", (r.status_code, r.text)
        # таймаут-защита тела
        r = client.post(s.yoomoney_webhook_path, data={"x": "y" * 100000},
                        headers={"content-length": str(100000 + 424)})
        assert r.status_code == 413
        print("[ok] HTTP вебхук: 200/ok, лимит тела работает")

    # logout
    print()
    print("ALL SMOKE TESTS PASSED ✅")


async def _true():
    return True


asyncio.run(main())
