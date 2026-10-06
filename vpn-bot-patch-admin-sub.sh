#!/usr/bin/env bash
# ============================================================
# ПАТЧ: добавление функции «Создать подписку» в админ-панель
#   * Пользователи -> панель «Создать подписку»: Telegram ID + срок,
#     создание/продление в Remnawave + отправка ключа в бот.
# Патч обновляет 3 файла и пересобирает контейнер admin.
# .env и база данных НЕ затрагиваются.
#
# Запуск: положите файл рядом с каталогом vpn-bot (или внутрь него) и:
#   bash vpn-bot-patch-admin-sub.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

if [ -f docker-compose.yml ]; then DIR=".";
elif [ -f vpn-bot/docker-compose.yml ]; then DIR="vpn-bot";
else echo "ОШИБКА: запускайте из каталога с vpn-bot/ или из самого vpn-bot/"; exit 1; fi
echo "==> Каталог проекта: $DIR"

echo "==> Обновление файлов"
cat > "$DIR/app/admin/routes.py" <<'PATCH_EOF_1'
"""Маршруты админ-панели и вебхука YooMoney.

Разделы: Dashboard, Users, Orders, Tariffs, Broadcast, Logs + POST /yoomoney/notification.
Безопасность: сессионная авторизация, подтверждение опасных действий (на фронте),
журналирование админ-действий, никаких токенов в интерфейсе.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import String as SAString
from sqlalchemy import and_, cast, func, or_, select

from app.admin.auth import check_login, is_authenticated, login_limiter
from app.config import get_settings
from app.database import get_session
from app.models import AdminAction, Order, PaymentEvent, ServiceLog, Tariff, User
from app.services import notifications, orders
from app.services.broadcasts import manager as broadcast_manager
from app.services.remnawave import RemnaError, get_remna
from app.services.yoomoney import process_notification
from app.utils import display_dt, fmt_money, utcnow, valid_telegram_id

log = logging.getLogger("app.admin")

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["dt"] = lambda v: display_dt(v, get_settings().display_tz)
templates.env.filters["money"] = fmt_money

USER_STATUSES = ("ACTIVE", "BLOCKED", "EXPIRED")
ORDER_STATUSES = ("pending", "paid", "canceled")
LOG_KINDS = ("yoomoney", "remnawave", "webhook", "broadcast", "bot")


# ------------------------------------------------------------------ helpers

def _render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    context = dict(ctx or {})
    context.setdefault("msg", request.query_params.get("msg"))
    context.setdefault("k", request.query_params.get("k", "ok"))
    context.setdefault("path", request.url.path)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _redirect(url: str, msg: str | None = None, kind: str = "ok") -> RedirectResponse:
    if msg:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}msg={quote(msg)}&k={kind}"
    return RedirectResponse(url, status_code=303)


def _guard(request: Request) -> RedirectResponse | None:
    if is_authenticated(request):
        return None
    return _redirect("/login", "Требуется вход в панель")


def _back(request: Request) -> str:
    """URL для возврата после POST (сохраняет фильтры и страницу)."""
    qp = [(k, v) for k, v in request.query_params.multi_items() if k not in ("msg", "k", "page")]
    base = request.url.path
    if qp:
        return base + "?" + "&".join(f"{k}={quote(v)}" for k, v in qp)
    return base


def _base_qs(request: Request) -> str:
    qp = [(k, v) for k, v in request.query_params.multi_items() if k not in ("page", "msg", "k")]
    if qp:
        return "&".join(f"{k}={quote(v)}" for k, v in qp) + "&"
    return ""


def _paginate(request: Request, total: int, per: int = 20) -> dict:
    pages = max(1, (total + per - 1) // per)
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    page = min(max(1, page), pages)
    return {"page": page, "pages": pages, "per": per, "offset": (page - 1) * per, "total": total}


async def _log_admin(action: str, target: str = "", details: str = "") -> None:
    s = get_settings()
    try:
        async with get_session() as session:
            session.add(
                AdminAction(
                    admin_id=s.admin_id,
                    action=action[:64],
                    target=str(target)[:128],
                    details=str(details)[:2000],
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        log.exception("Не удалось записать admin_action")


async def _load_user(user_id: int) -> User | None:
    async with get_session() as session:
        return (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()


# ------------------------------------------------------------------ auth

@router.get("/login")
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", {"section": "login"})


@router.post("/login")
async def login_submit(request: Request):
    s = get_settings()
    if not s.admin_password:
        return _redirect("/login", "Вход отключён: ADMIN_PASSWORD не задан в .env", "err")
    ip = request.client.host if request.client else "-"
    if not login_limiter.allow(f"login:{ip}"):
        return _redirect("/login", "Слишком много попыток входа — подождите минуту", "err")

    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    if not check_login(username, password):
        await _log_admin("login_failed", target=ip)
        return _render(
            request, "login.html", {"section": "login", "error": "Неверный логин или пароль"}, status_code=401
        )
    request.session["adm"] = True
    request.session["user"] = s.admin_user
    await _log_admin("login", target=ip)
    return _redirect("/", "Добро пожаловать!")


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return _redirect("/login", "Вы вышли из панели")


# ------------------------------------------------------------------ dashboard

@router.get("/")
async def dashboard(request: Request):
    r = _guard(request)
    if r:
        return r
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async with get_session() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active = (
            await session.scalar(
                select(func.count(User.id)).where(
                    User.status == "ACTIVE", User.expire_at > now
                )
            )
            or 0
        )
        expired = (
            await session.scalar(
                select(func.count(User.id)).where(
                    or_(
                        User.status == "EXPIRED",
                        and_(User.expire_at.is_not(None), User.expire_at <= now),
                    )
                )
            )
            or 0
        )
        blocked = (
            await session.scalar(select(func.count(User.id)).where(User.status == "BLOCKED")) or 0
        )
        orders_total = await session.scalar(select(func.count(Order.id))) or 0
        orders_paid = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "paid")) or 0
        )
        orders_pending = (
            await session.scalar(select(func.count(Order.id)).where(Order.status == "pending")) or 0
        )
        revenue = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(Order.status == "paid")
            )
            or 0
        )
        sales_today = (
            await session.scalar(
                select(func.count(Order.id)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        revenue_today = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= today
                )
            )
            or 0
        )
        sales_month = (
            await session.scalar(
                select(func.count(Order.id)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )
        revenue_month = (
            await session.scalar(
                select(func.coalesce(func.sum(Order.expected_price), 0)).where(
                    Order.status == "paid", Order.paid_at >= month
                )
            )
            or 0
        )
        recent_orders = (
            (
                await session.execute(
                    select(Order).order_by(Order.created_at.desc()).limit(6)
                )
            )
            .scalars()
            .all()
        )

    cards = [
        ("👥", "Пользователей", total_users, ""),
        ("✅", "Активных подписок", active, ""),
        ("⛔️", "Истёкших подписок", expired, ""),
        ("🚫", "Заблокировано", blocked, ""),
        ("🧾", "Заказов всего", orders_total, f"ожидают оплаты: {orders_pending}"),
        ("💰", "Оплачено заказов", orders_paid, f"выручка: {fmt_money(revenue)} ₽"),
        ("📅", "Продаж за сегодня", sales_today, f"на {fmt_money(revenue_today)} ₽"),
        ("🗓", "Продаж за месяц", sales_month, f"на {fmt_money(revenue_month)} ₽"),
    ]
    return _render(
        request,
        "dashboard.html",
        {"section": "dashboard", "cards": cards, "recent_orders": recent_orders},
    )


# ------------------------------------------------------------------ users

@router.get("/users")
async def users_page(request: Request):
    r = _guard(request)
    if r:
        return r
    q = (request.query_params.get("q") or "").strip()
    status = (request.query_params.get("status") or "").strip()

    conds = []
    if q:
        if q.lstrip("-").isdigit():
            conds.append(
                or_(
                    User.telegram_id == int(q),
                    cast(User.telegram_id, SAString).ilike(f"%{q}%"),
                    User.username.ilike(f"%{q}%"),
                    User.remnawave_user_id.ilike(f"%{q}%"),
                )
            )
        else:
            conds.append(User.username.ilike(f"%{q}%"))
    if status in USER_STATUSES:
        conds.append(User.status == status)

    async with get_session() as session:
        total = await session.scalar(select(func.count(User.id)).where(*conds)) or 0
        pg = _paginate(request, int(total))
        rows = (
            (
                await session.execute(
                    select(User)
                    .where(*conds)
                    .order_by(User.id.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "users.html",
        {
            "section": "users",
            "rows": rows,
            "q": q,
            "status": status,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
            "back": _back(request),
        },
    )


@router.post("/users/{user_id}/extend")
async def user_extend(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    form = await request.form()
    try:
        days = int(str(form.get("days", "30")))
        if not 1 <= days <= 3650:
            raise ValueError
    except ValueError:
        return _redirect(back, "Некорректное количество дней", "err")
    try:
        await orders.provision_user(user.telegram_id, days)
    except RemnaError as exc:
        await orders.log_service_error("remnawave", f"Продление из админки: {exc}")
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    await _log_admin("user_extend", f"user:{user.telegram_id}", f"days={days}")
    fresh = await orders.get_local_user(user.telegram_id)
    if fresh is not None and notifications.has_bot():
        await notifications.notify_key(fresh)
    return _redirect(back, f"Подписка продлена на {days} дн., ключ отправлен пользователю")


@router.post("/users/{user_id}/disable")
async def user_disable(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    try:
        if user.remnawave_user_id:
            await get_remna().disable_user(user.remnawave_user_id)
    except RemnaError as exc:
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    async with get_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is not None:
            db_user.status = "BLOCKED"
            await session.commit()
    await _log_admin("user_disable", f"user:{user.telegram_id}")
    return _redirect(back, "Пользователь заблокирован")


@router.post("/users/{user_id}/enable")
async def user_enable(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None:
        return _redirect(back, "Пользователь не найден", "err")
    try:
        if user.remnawave_user_id:
            await get_remna().enable_user(user.remnawave_user_id)
    except RemnaError as exc:
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    async with get_session() as session:
        db_user = await session.get(User, user.id)
        if db_user is not None:
            db_user.status = "ACTIVE" if (
                db_user.expire_at is None or db_user.expire_at > utcnow()
            ) else "EXPIRED"
            await session.commit()
    await _log_admin("user_enable", f"user:{user.telegram_id}")
    return _redirect(back, "Пользователь разблокирован")


@router.post("/users/{user_id}/send_key")
async def user_send_key(request: Request, user_id: int):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    user = await _load_user(user_id)
    if user is None or not user.remnawave_user_id:
        return _redirect(back, "У пользователя нет подписки Remnawave", "err")
    if not notifications.has_bot():
        return _redirect(back, "Бот недоступен (не задан BOT_TOKEN)", "err")
    await notifications.notify_key(user)
    await _log_admin("user_send_key", f"user:{user.telegram_id}")
    return _redirect(back, "Ключ отправлен пользователю")


@router.post("/users/create")
async def user_create(request: Request):
    """Создание подписки из админки: произвольный Telegram ID + срок.

    * пользователя нет локально и в панели -> создаётся (username tg_<id>);
    * пользователь уже есть -> подписка продлевается на указанные дни;
    * опционально ключ отправляется пользователю в Telegram.
    """
    r = _guard(request)
    if r:
        return r
    back = "/users"
    form = await request.form()
    notify = bool(form.get("notify"))

    try:
        days = int(str(form.get("days", "30")))
    except ValueError:
        return _redirect(back, "Некорректное количество дней", "err")
    raw_tg = str(form.get("telegram_id", "")).strip()
    if not valid_telegram_id(raw_tg) or not 1 <= days <= 3650:
        return _redirect(back, "Некорректный Telegram ID или количество дней", "err")
    telegram_id = int(raw_tg)

    if await orders.get_local_user(telegram_id) is None:
        async with get_session() as session:
            session.add(User(telegram_id=telegram_id, status="ACTIVE"))
            await session.commit()

    try:
        await orders.provision_user(telegram_id, days)
    except RemnaError as exc:
        await orders.log_service_error("remnawave", f"Создание подписки из админки: {exc}")
        return _redirect(back, f"Ошибка Remnawave: {exc}", "err")
    except ValueError as exc:
        return _redirect(back, str(exc), "err")

    await _log_admin("user_create", f"user:{telegram_id}", f"days={days} notify={notify}")

    msg = f"Подписка создана/продлена на {days} дн."
    if notify:
        fresh = await orders.get_local_user(telegram_id)
        if fresh is not None and notifications.has_bot():
            await notifications.notify_key(fresh)
            msg += ", ключ отправлен пользователю"
        else:
            msg += " (бот недоступен — ключ не отправлен)"
    return _redirect(back, msg)


# ------------------------------------------------------------------ orders

@router.get("/orders")
async def orders_page(request: Request):
    r = _guard(request)
    if r:
        return r
    q = (request.query_params.get("q") or "").strip()
    status = (request.query_params.get("status") or "").strip()

    conds = []
    if q:
        like = f"%{q}%"
        conds.append(
            or_(
                Order.order_id.ilike(like),
                Order.label.ilike(like),
                Order.operation_id.ilike(like),
                cast(Order.telegram_id, SAString).ilike(like),
            )
        )
    if status in ORDER_STATUSES:
        conds.append(Order.status == status)

    async with get_session() as session:
        total = await session.scalar(select(func.count(Order.id)).where(*conds)) or 0
        pg = _paginate(request, int(total))
        rows = (
            (
                await session.execute(
                    select(Order)
                    .where(*conds)
                    .order_by(Order.created_at.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "orders.html",
        {
            "section": "orders",
            "rows": rows,
            "q": q,
            "status": status,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
            "back": _back(request),
        },
    )


@router.post("/orders/{order_id}/reissue")
async def order_reissue(request: Request, order_id: str):
    r = _guard(request)
    if r:
        return r
    back = _back(request)
    async with get_session() as session:
        order = (
            await session.execute(select(Order).where(Order.order_id == order_id))
        ).scalar_one_or_none()
    if order is None:
        return _redirect(back, "Заказ не найден", "err")
    if order.status != "paid":
        return _redirect(back, "Заказ ещё не оплачен — переотправка не требуется", "err")
    if not notifications.has_bot():
        return _redirect(back, "Бот недоступен (не задан BOT_TOKEN)", "err")
    result = await orders.ensure_provisioned_and_notify(order)
    await _log_admin("order_reissue", f"order:{order.order_id}", result)
    msg = {
        "key_sent": "Подписка уже была выдана — ключ повторно отправлен пользователю",
        "provisioned": "Подписка выдана заново и отправлена пользователю",
    }.get(result, "Готово")
    return _redirect(back, msg)


# ------------------------------------------------------------------ tariffs

@router.get("/tariffs")
async def tariffs_page(request: Request):
    r = _guard(request)
    if r:
        return r
    async with get_session() as session:
        rows = (
            (await session.execute(select(Tariff).order_by(Tariff.sort, Tariff.days)))
            .scalars()
            .all()
        )
    return _render(request, "tariffs.html", {"section": "tariffs", "rows": rows, "back": _back(request)})


@router.post("/tariffs/{tariff_id}/save")
async def tariff_save(request: Request, tariff_id: int):
    r = _guard(request)
    if r:
        return r
    back = "/tariffs"
    form = await request.form()
    async with get_session() as session:
        tariff = await session.get(Tariff, tariff_id)
        if tariff is None:
            return _redirect(back, "Тариф не найден", "err")
        try:
            price = Decimal(str(form.get("price", "")).replace(",", ".")).quantize(Decimal("0.01"))
            if price < 0 or price > Decimal("1000000"):
                raise ValueError
        except (InvalidOperation, ValueError):
            return _redirect(back, "Некорректная цена", "err")
        tariff.price = price
        tariff.enabled = bool(form.get("enabled"))
        await session.commit()
        await _log_admin("tariff_update", f"tariff:{tariff.code}", f"price={price} enabled={tariff.enabled}")
    return _redirect(back, "Тариф сохранён")


# ------------------------------------------------------------------ broadcast

@router.get("/broadcast")
async def broadcast_page(request: Request):
    r = _guard(request)
    if r:
        return r
    s = get_settings()
    return _render(
        request,
        "broadcast.html",
        {
            "section": "broadcast",
            "draft": request.session.get("bc_text", ""),
            "rate": request.session.get("bc_rate") or s.broadcast_default_rate,
            "targets": request.session.get("bc_targets", "all"),
            "bc": broadcast_manager.status(),
            "running": broadcast_manager.is_running(),
        },
    )


@router.post("/broadcast/preview")
async def broadcast_preview(request: Request):
    r = _guard(request)
    if r:
        return r
    s = get_settings()
    form = await request.form()
    text = str(form.get("text", "")).strip()
    targets = str(form.get("targets", "all"))
    try:
        rate = float(str(form.get("rate", s.broadcast_default_rate)))
    except ValueError:
        rate = s.broadcast_default_rate
    rate = min(max(rate, 1.0), 30.0)

    if not text:
        return _redirect("/broadcast", "Текст рассылки пуст", "err")

    request.session["bc_text"] = text
    request.session["bc_rate"] = rate
    request.session["bc_targets"] = targets if targets in ("all", "active") else "all"

    async with get_session() as session:
        stmt = select(func.count(User.id))
        if targets == "active":
            stmt = stmt.where(User.status == "ACTIVE", User.expire_at > utcnow())
        recipients = await session.scalar(stmt) or 0

    eta_min = recipients / rate / 60 if rate else 0
    return _render(
        request,
        "broadcast.html",
        {
            "section": "broadcast",
            "draft": text,
            "rate": rate,
            "targets": targets,
            "bc": broadcast_manager.status(),
            "running": broadcast_manager.is_running(),
            "preview": {
                "text": text,
                "recipients": int(recipients),
                "eta_min": round(eta_min, 1),
            },
        },
    )


@router.post("/broadcast/send")
async def broadcast_send(request: Request):
    r = _guard(request)
    if r:
        return r
    text = request.session.get("bc_text", "")
    if not text:
        return _redirect("/broadcast", "Нет черновика рассылки — создайте его заново", "err")
    rate = float(request.session.get("bc_rate") or get_settings().broadcast_default_rate)
    targets = request.session.get("bc_targets", "all")

    async with get_session() as session:
        stmt = select(User.telegram_id).order_by(User.id.desc())
        if targets == "active":
            stmt = stmt.where(User.status == "ACTIVE", User.expire_at > utcnow())
        chat_ids = [int(tid) for tid in (await session.execute(stmt)).scalars() if valid_telegram_id(tid)]

    if not notifications.has_bot():
        return _redirect("/broadcast", "Бот недоступен (не задан BOT_TOKEN)", "err")
    ok, msg = broadcast_manager.start(text, rate, chat_ids)
    await _log_admin("broadcast", f"targets:{targets}", f"recipients={len(chat_ids)} rate={rate} started={ok}")
    return _redirect("/broadcast", msg, "ok" if ok else "err")


@router.get("/broadcast/status")
async def broadcast_status(request: Request):
    r = _guard(request)
    if r:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(broadcast_manager.status())


# ------------------------------------------------------------------ logs

@router.get("/logs")
async def logs_page(request: Request):
    r = _guard(request)
    if r:
        return r
    tab = request.query_params.get("tab", "actions")
    if tab not in ("actions", "payments", "errors"):
        tab = "actions"
    kind = (request.query_params.get("kind") or "").strip()

    async with get_session() as session:
        if tab == "actions":
            model = AdminAction
            conds = []
        elif tab == "payments":
            model = PaymentEvent
            conds = []
        else:
            model = ServiceLog
            conds = [ServiceLog.kind == kind] if kind in LOG_KINDS else []

        total = await session.scalar(select(func.count(model.id)).where(*conds)) or 0
        pg = _paginate(request, int(total), per=30)
        rows = (
            (
                await session.execute(
                    select(model)
                    .where(*conds)
                    .order_by(model.id.desc())
                    .limit(pg["per"])
                    .offset(pg["offset"])
                )
            )
            .scalars()
            .all()
        )
    return _render(
        request,
        "logs.html",
        {
            "section": "logs",
            "tab": tab,
            "kind": kind,
            "rows": rows,
            "page": pg["page"],
            "pages": pg["pages"],
            "total": pg["total"],
            "base_qs": _base_qs(request),
        },
    )


# ------------------------------------------------------------------ webhook

@router.post(get_settings().yoomoney_webhook_path)
async def yoomoney_notification(request: Request):
    s = get_settings()
    # лимит размера тела (тело кэшируется — дальше form() прочитает его из кэша)
    body = await request.body()
    if len(body) > s.webhook_max_body_bytes:
        return PlainTextResponse("too large", status_code=413)
    try:
        form = await request.form()
        params = {str(k): str(v) for k, v in form.multi_items()}
    except Exception:  # noqa: BLE001
        return PlainTextResponse("bad request", status_code=400)
    ip = request.client.host if request.client else "-"
    try:
        status, reason = await process_notification(params, ip)
    except Exception:  # noqa: BLE001
        log.exception("Исключение при обработке уведомления YooMoney")
        await orders.log_service_error("yoomoney", "Внутренняя ошибка обработки вебхука")
        return PlainTextResponse("error", status_code=500)
    return PlainTextResponse(reason, status_code=status)
PATCH_EOF_1
cat > "$DIR/app/admin/templates/users.html" <<'PATCH_EOF_2'
{% extends "base.html" %}
{% block title %}Пользователи — VPN Admin{% endblock %}
{% block h1 %}👥 Пользователи <span class="count">{{ total }}</span>{% endblock %}
{% block content %}
<div class="panel">
  <h2>➕ Создать подписку</h2>
  <p class="muted">Создаёт пользователя в Remnawave (если его ещё нет) и выдаёт дни. Если подписка уже есть — продлевает её.</p>
  <form method="post" action="/users/create" class="filters" data-confirm="Создать/продлить подписку в Remnawave?">
    <input type="text" name="telegram_id" placeholder="Telegram ID" required>
    <select name="days">
      <option value="7">7 дн.</option>
      <option value="30" selected>30 дн.</option>
      <option value="90">90 дн.</option>
      <option value="180">180 дн.</option>
      <option value="365">365 дн.</option>
    </select>
    <label class="chk"><input type="checkbox" name="notify" value="1" checked> отправить ключ в бот</label>
    <button class="btn primary">➕ Создать</button>
  </form>
</div>

<div class="panel">
  <form method="get" action="/users" class="filters">
    <input type="text" name="q" value="{{ q }}" placeholder="Telegram ID / username / Remna ID">
    <select name="status">
      <option value="">Все статусы</option>
      {% for st in ('ACTIVE', 'BLOCKED', 'EXPIRED') %}
      <option value="{{ st }}" {{ 'selected' if status == st }}>{{ st }}</option>
      {% endfor %}
    </select>
    <button class="btn primary">🔍 Искать</button>
    {% if q or status %}<a class="btn ghost" href="/users">Сброс</a>{% endif %}
  </form>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>ID</th><th>Telegram ID</th><th>Remna username</th><th>Статус</th><th>Окончание</th><th>Действия</th></tr>
      </thead>
      <tbody>
        {% for u in rows %}
        <tr>
          <td>{{ u.id }}</td>
          <td><code>{{ u.telegram_id }}</code></td>
          <td>{{ u.username or '—' }}</td>
          <td><span class="badge b-{{ u.status | lower }}">{{ u.status }}</span></td>
          <td>{{ u.expire_at | dt }}</td>
          <td class="actions">
            <form method="post" action="/users/{{ u.id }}/extend" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <select name="days">
                <option value="7">7 дн.</option>
                <option value="30" selected>30 дн.</option>
                <option value="90">90 дн.</option>
                <option value="180">180 дн.</option>
                <option value="365">365 дн.</option>
              </select>
              <button class="btn sm primary">＋ Продлить</button>
            </form>
            {% if u.status == 'BLOCKED' %}
            <form method="post" action="/users/{{ u.id }}/enable" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm ok">✓ Разблокировать</button>
            </form>
            {% else %}
            <form method="post" action="/users/{{ u.id }}/disable" class="inline-form" data-confirm="Заблокировать пользователя {{ u.telegram_id }} в боте и в Remnawave?">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm danger">🚫 Блок</button>
            </form>
            {% endif %}
            <form method="post" action="/users/{{ u.id }}/send_key" class="inline-form">
              <input type="hidden" name="back" value="{{ back }}">
              <button class="btn sm">🔑 Ключ</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="6" class="muted">Ничего не найдено</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if pages > 1 %}
  <div class="pagination">
    {% if page > 1 %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page - 1 }}">‹ Назад</a>{% endif %}
    <span>Стр. {{ page }} из {{ pages }}</span>
    {% if page < pages %}<a class="btn sm ghost" href="?{{ base_qs }}page={{ page + 1 }}">Вперёд ›</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
PATCH_EOF_2
cat > "$DIR/app/admin/static/style.css" <<'PATCH_EOF_3'
/* VPN Admin — тёмная тема, адаптив */
:root {
  --bg: #0d131b;
  --panel: #151d28;
  --panel-2: #1b2533;
  --border: #263344;
  --text: #e7edf4;
  --muted: #8b98a7;
  --accent: #4f8cff;
  --accent-2: #3b6fd4;
  --ok: #2fbf71;
  --err: #ff5c5c;
  --warn: #f5a623;
  --radius: 12px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}

/* ---------- sidebar ---------- */
.sidebar {
  position: fixed; inset: 0 auto 0 0; width: 230px;
  background: var(--panel); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 18px 14px; z-index: 50;
}
.brand { font-weight: 700; font-size: 17px; margin-bottom: 20px; letter-spacing: .3px; }
.brand.big { font-size: 22px; text-align: center; margin-bottom: 18px; }
.sidebar nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.sidebar nav a {
  color: var(--muted); text-decoration: none; padding: 10px 12px;
  border-radius: 8px; transition: background .15s, color .15s;
}
.sidebar nav a:hover { background: var(--panel-2); color: var(--text); }
.sidebar nav a.active { background: var(--accent); color: #fff; }
.logout-form { margin-top: 10px; }

/* ---------- main ---------- */
.main { margin-left: 230px; padding: 0 22px 40px; }
.topbar {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 0 14px; border-bottom: 1px solid var(--border); margin-bottom: 20px;
}
.topbar h1 { font-size: 20px; margin: 0; font-weight: 600; }
.count { color: var(--muted); font-size: 14px; font-weight: 400; }
.burger { display: none; background: none; border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; font-size: 18px; padding: 4px 10px; cursor: pointer; }

/* ---------- cards ---------- */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; margin-bottom: 20px; }
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px;
}
.card-icon { font-size: 22px; }
.card-value { font-size: 28px; font-weight: 700; margin: 6px 0 2px; }
.card-title { color: var(--muted); font-size: 13px; }
.card-note { color: var(--accent); font-size: 12.5px; margin-top: 6px; }

/* ---------- panels ---------- */
.panel {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 18px; margin-bottom: 20px;
}
.panel h2 { font-size: 16px; margin: 0 0 14px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* ---------- tables ---------- */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 12.5px; text-transform: uppercase; letter-spacing: .4px; }
tbody tr:hover { background: var(--panel-2); }
td.wrap, .mono.wrap { white-space: normal; word-break: break-word; }
code { background: var(--panel-2); padding: 2px 6px; border-radius: 6px; font-size: 12.5px; }
.muted { color: var(--muted); }
.mono { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 12.5px; }

/* ---------- badges ---------- */
.badge { display: inline-block; padding: 3px 9px; border-radius: 20px; font-size: 12px; font-weight: 600;
  background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
.b-active, .b-paid { background: rgba(47,191,113,.14); color: var(--ok); border-color: rgba(47,191,113,.4); }
.b-expired, .b-error { background: rgba(255,92,92,.14); color: var(--err); border-color: rgba(255,92,92,.4); }
.b-blocked, .b-pending, .b-warn { background: rgba(245,166,35,.14); color: var(--warn); border-color: rgba(245,166,35,.4); }
.b-canceled { opacity: .7; }

/* ---------- forms ---------- */
input[type=text], input[type=password], input[type=number], select, textarea {
  width: 100%; background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; font: inherit;
}
input:focus, select:focus, textarea:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
label { display: block; margin-bottom: 13px; color: var(--muted); font-size: 13px; }
label input, label select, label textarea { margin-top: 6px; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.filters input, .filters select { width: auto; min-width: 180px; flex: 1; }
.inline-form { display: inline-flex; gap: 6px; align-items: center; margin: 2px 4px 2px 0; }
.inline-form select { width: auto; padding: 4px 6px; font-size: 13px; }
.price-input { width: 110px; padding: 5px 8px !important; }
textarea { resize: vertical; }

/* ---------- buttons ---------- */
.btn {
  display: inline-block; background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 16px;
  font: inherit; font-size: 14px; cursor: pointer; text-decoration: none; transition: filter .15s;
}
.btn:hover { filter: brightness(1.18); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.danger { background: rgba(255,92,92,.15); border-color: rgba(255,92,92,.5); color: var(--err); }
.btn.ok { background: rgba(47,191,113,.15); border-color: rgba(47,191,113,.5); color: var(--ok); }
.btn.ghost { background: transparent; }
.btn.sm { padding: 5px 10px; font-size: 12.5px; border-radius: 7px; }
.btn.w100 { width: 100%; text-align: center; }

/* ---------- toast / alert ---------- */
.toast {
  position: fixed; top: 18px; right: 18px; z-index: 100; max-width: 420px;
  padding: 12px 18px; border-radius: 10px; font-size: 14px;
  background: rgba(47,191,113,.15); border: 1px solid rgba(47,191,113,.5); color: var(--ok);
  box-shadow: 0 8px 30px rgba(0,0,0,.4);
}
.toast.err { background: rgba(255,92,92,.15); border-color: rgba(255,92,92,.5); color: var(--err); }
.alert { padding: 11px 14px; border-radius: 9px; margin-bottom: 14px; font-size: 14px; }
.alert.err { background: rgba(255,92,92,.12); border: 1px solid rgba(255,92,92,.4); color: var(--err); }
.alert.warn { background: rgba(245,166,35,.12); border: 1px solid rgba(245,166,35,.4); color: var(--warn); }

/* ---------- чекбокс в строке фильтров (создание подписки) ---------- */
.filters label.chk { display: flex; align-items: center; gap: 7px; margin: 0; width: auto;
  flex: 0 0 auto; color: var(--text); font-size: 13.5px; cursor: pointer; }
.filters label.chk input { width: auto; margin: 0; }

/* ---------- pagination ---------- */
.pagination { display: flex; gap: 12px; align-items: center; margin-top: 16px; color: var(--muted); }

/* ---------- tabs ---------- */
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.tabs a { padding: 8px 14px; border-radius: 8px; text-decoration: none; color: var(--muted);
  background: var(--panel-2); border: 1px solid var(--border); font-size: 13.5px; }
.tabs a.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* ---------- broadcast ---------- */
.progress { height: 10px; background: var(--panel-2); border-radius: 20px; overflow: hidden; margin: 8px 0 10px; }
.progress .bar { height: 100%; background: linear-gradient(90deg, var(--accent), #7aa7ff); width: 0; transition: width .6s; }
.log { background: #0a0f16; border: 1px solid var(--border); border-radius: 8px; padding: 12px;
  max-height: 220px; overflow-y: auto; font-size: 12.5px; color: var(--muted); }
.preview-box { background: #0a0f16; border: 1px solid var(--border); border-radius: 10px;
  padding: 14px; white-space: pre-wrap; word-break: break-word; margin-bottom: 12px; }

/* ---------- login ---------- */
.login-body { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card { width: min(380px, 92vw); background: var(--panel); border: 1px solid var(--border);
  border-radius: 16px; padding: 28px; }

/* ---------- mobile ---------- */
@media (max-width: 900px) {
  .sidebar { transform: translateX(-100%); transition: transform .2s ease; width: 250px; }
  body.nav-open .sidebar { transform: translateX(0); box-shadow: 0 0 60px rgba(0,0,0,.6); }
  .main { margin-left: 0; padding: 0 14px 40px; }
  .burger { display: block; }
  .grid-2 { grid-template-columns: 1fr; }
  .filters input, .filters select { min-width: 130px; }
  th, td { padding: 7px 8px; }
}
PATCH_EOF_3

echo "==> Пересборка и перезапуск админки"
cd "$DIR"
docker compose up -d --build admin

echo ""
echo "==> Статус:"
docker compose ps
echo "Проверка: curl -s http://127.0.0.1:8090/health"
echo "Готово: Админка -> Пользователи -> блок «Создать подписку»."
