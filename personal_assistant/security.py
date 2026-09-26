from __future__ import annotations

import hashlib
import hmac
import math
import time
from collections import deque
from threading import Lock
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from personal_assistant.config import SERVICE_API_TOKEN, SESSION_SECRET, WEB_PASSWORD

SESSION_COOKIE = "pa_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60


class LoginRateLimiter:
    """A small process-local throttle for this single-user web login."""

    def __init__(self) -> None:
        self._failures: deque[float] = deque()
        self._lock = Lock()

    def check(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._discard_expired(now)
            if len(self._failures) < LOGIN_FAILURE_LIMIT:
                return
            retry_after = max(
                1,
                math.ceil(LOGIN_FAILURE_WINDOW_SECONDS - (now - self._failures[0])),
            )
        raise HTTPException(
            status_code=429,
            detail="登录尝试过多，请稍后再试。",
            headers={"Retry-After": str(retry_after)},
        )

    def failed(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._discard_expired(now)
            self._failures.append(now)

    def succeeded(self) -> None:
        with self._lock:
            self._failures.clear()

    def _discard_expired(self, now: float) -> None:
        while self._failures and now - self._failures[0] >= LOGIN_FAILURE_WINDOW_SECONDS:
            self._failures.popleft()


login_rate_limiter = LoginRateLimiter()


def require_same_origin(request: Request) -> None:
    """Reject browser form/API requests whose Origin does not match the host."""
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")
    parsed = urlsplit(origin or "")
    expected_host = host
    using_forwarded_host = False
    forwarded_host = request.headers.get("x-forwarded-host", "").strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").casefold()
    client_host = request.client.host if request.client else ""
    if forwarded_host and forwarded_proto == "https" and client_host in {"127.0.0.1", "::1"}:
        # Tailscale Serve terminates TLS and proxies to our loopback-only API.
        expected_host = forwarded_host
        using_forwarded_host = True
    if (
        not origin
        or parsed.scheme not in {"http", "https"}
        or (using_forwarded_host and parsed.scheme != "https")
        or not parsed.netloc
        or parsed.netloc.casefold() != expected_host.casefold()
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=403, detail="请求来源校验失败。")


def password_matches(candidate: str) -> bool:
    return hmac.compare_digest(candidate.encode(), WEB_PASSWORD.encode())


def create_session() -> tuple[str, int]:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    signature = hmac.new(
        SESSION_SECRET.encode(), f"personal-assistant:{expires}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{expires}.{signature}", expires


def valid_session(value: str | None) -> bool:
    if not value:
        return False
    try:
        expires_text, signature = value.split(".", 1)
        expires = int(expires_text)
    except (ValueError, TypeError):
        return False
    if expires < int(time.time()):
        return False
    expected = hmac.new(
        SESSION_SECRET.encode(), f"personal-assistant:{expires}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def request_actor(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate and hmac.compare_digest(candidate.encode(), SERVICE_API_TOKEN.encode()):
            return "astrbot"
    if valid_session(request.cookies.get(SESSION_COOKIE)):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            require_same_origin(request)
        return "web"
    raise HTTPException(status_code=401, detail="Login required")
