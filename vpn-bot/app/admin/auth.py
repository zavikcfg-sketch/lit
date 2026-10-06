"""Аутентификация админ-панели: cookie-сессии, безопасное сравнение, лимит попыток.

Пароль хранится только в .env (ADMIN_PASSWORD). Токены в интерфейсе не показываются.
"""
from __future__ import annotations

import secrets

from app.config import get_settings
from app.services.yoomoney import SimpleRateLimiter

# не более 8 попыток входа в минуту с одного IP
login_limiter = SimpleRateLimiter(max_events=8, window_seconds=60)


def check_login(username: str, password: str) -> bool:
    """Постоянновременное сравнение строк — защита от timing-атак."""
    s = get_settings()
    if not s.admin_password:
        return False
    ok_user = secrets.compare_digest(
        str(username).encode("utf-8"), s.admin_user.encode("utf-8")
    )
    ok_pass = secrets.compare_digest(
        str(password).encode("utf-8"), s.admin_password.encode("utf-8")
    )
    return ok_user and ok_pass


def is_authenticated(request) -> bool:
    return bool(request.session.get("adm"))
