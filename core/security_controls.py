"""Central defensive limits for expensive or security-sensitive operations.

The controls are intentionally dependency-free and process-local. They protect one
DataDeck instance from accidental or abusive concurrency, but they are not a
replacement for edge/WAF rate limiting against distributed or volumetric attacks.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath


@dataclass(frozen=True)
class LimitPolicy:
    requests: int
    window_seconds: int
    concurrent_per_principal: int
    concurrent_global: int
    global_requests: int


_DEFAULT_POLICIES = {
    "login": LimitPolicy(10, 600, 1, 50, 300),
    "upload": LimitPolicy(12, 3600, 1, 4, 120),
    "analysis": LimitPolicy(60, 600, 1, 4, 600),
    "ai": LimitPolicy(6, 3600, 1, 2, 60),
    "pdf": LimitPolicy(12, 3600, 1, 2, 120),
    "feedback": LimitPolicy(5, 3600, 1, 20, 100),
    "checkout": LimitPolicy(6, 3600, 1, 10, 60),
    "portal": LimitPolicy(12, 3600, 1, 10, 120),
    "client_write": LimitPolicy(30, 3600, 1, 10, 300),
    "webhook": LimitPolicy(120, 60, 4, 20, 600),
}


class SecurityLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: int = 1):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class RateLimitExceeded(SecurityLimitError):
    pass


class ConcurrencyLimitExceeded(SecurityLimitError):
    pass


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 100_000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def policy_for(action: str) -> LimitPolicy:
    if action not in _DEFAULT_POLICIES:
        raise ValueError(f"Unknown security action: {action}")
    default = _DEFAULT_POLICIES[action]
    prefix = f"SECURITY_{action.upper()}"
    return LimitPolicy(
        requests=_env_int(f"{prefix}_REQUESTS", default.requests),
        window_seconds=_env_int(f"{prefix}_WINDOW_SECONDS", default.window_seconds, maximum=86_400),
        concurrent_per_principal=_env_int(
            f"{prefix}_CONCURRENT_PER_USER", default.concurrent_per_principal, maximum=100
        ),
        concurrent_global=_env_int(f"{prefix}_CONCURRENT_GLOBAL", default.concurrent_global, maximum=1_000),
        global_requests=_env_int(f"{prefix}_GLOBAL_REQUESTS", default.global_requests),
    )


def _stable_key(value: str | None) -> str:
    candidate = (value or "anonymous").strip()[:500]
    return hashlib.sha256(candidate.encode("utf-8", errors="replace")).hexdigest()[:24]


class SlidingWindowLimiter:
    def __init__(self, max_buckets: int = 10_000):
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()
        self._max_buckets = max_buckets

    def consume(
        self,
        action: str,
        principal: str,
        limit: int,
        window_seconds: int,
        *,
        now: float | None = None,
    ) -> None:
        current = time.monotonic() if now is None else float(now)
        key = (action, _stable_key(principal))
        cutoff = current - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(max(1.0, window_seconds - (current - bucket[0])))
                raise RateLimitExceeded("Zu viele Anfragen. Bitte später erneut versuchen.", retry_after)
            bucket.append(current)
            if len(self._events) > self._max_buckets:
                self._cleanup(cutoff)

    def _cleanup(self, cutoff: float) -> None:
        stale = []
        for key, bucket in self._events.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                stale.append(key)
        for key in stale:
            self._events.pop(key, None)


class ConcurrencyLimiter:
    def __init__(self):
        self._per_principal: dict[tuple[str, str], int] = defaultdict(int)
        self._global: dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    @contextmanager
    def acquire(self, action: str, principal: str, per_principal: int, global_limit: int):
        key = (action, _stable_key(principal))
        with self._lock:
            if self._per_principal[key] >= per_principal:
                raise ConcurrencyLimitExceeded("Dieser Vorgang läuft bereits.", 2)
            if self._global[action] >= global_limit:
                raise ConcurrencyLimitExceeded("Das System ist ausgelastet. Bitte kurz warten.", 5)
            self._per_principal[key] += 1
            self._global[action] += 1
        try:
            yield
        finally:
            with self._lock:
                self._per_principal[key] = max(0, self._per_principal[key] - 1)
                self._global[action] = max(0, self._global[action] - 1)
                if self._per_principal[key] == 0:
                    self._per_principal.pop(key, None)


_RATE_LIMITER = SlidingWindowLimiter()
_CONCURRENCY_LIMITER = ConcurrencyLimiter()


def enforce_rate_limit(
    action: str,
    principal: str,
    *,
    session_id: str | None = None,
    now: float | None = None,
) -> None:
    policy = policy_for(action)
    _RATE_LIMITER.consume(action, f"user:{principal}", policy.requests, policy.window_seconds, now=now)
    if session_id:
        _RATE_LIMITER.consume(
            action, f"session:{session_id}", policy.requests, policy.window_seconds, now=now
        )
    _RATE_LIMITER.consume(
        action, "__global__", policy.global_requests, policy.window_seconds, now=now
    )


@contextmanager
def guarded_operation(
    action: str,
    principal: str,
    *,
    session_id: str | None = None,
    now: float | None = None,
):
    """Apply per-user/session rate limits and per-user/global backpressure."""
    policy = policy_for(action)
    enforce_rate_limit(action, principal, session_id=session_id, now=now)
    with _CONCURRENCY_LIMITER.acquire(
        action, principal, policy.concurrent_per_principal, policy.concurrent_global
    ):
        yield


def sanitize_log_value(value, max_length: int = 120) -> str:
    """Flatten untrusted values so they cannot forge additional log lines."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    return re.sub(r"\s+", " ", text).strip()[:max_length]


def validate_upload_filename(file_name: str, allowed_extensions: set[str]) -> str:
    """Validate a display-only upload name and reject traversal/control tricks."""
    if not isinstance(file_name, str):
        raise ValueError("Der Dateiname ist ungültig.")
    clean = sanitize_log_value(file_name, 255)
    if not clean or clean != file_name.strip() or "\x00" in file_name:
        raise ValueError("Der Dateiname ist ungültig.")
    if any(separator in clean for separator in ("/", "\\")) or clean in {".", ".."}:
        raise ValueError("Dateipfade sind als Upload-Name nicht erlaubt.")
    if PurePath(clean).name != clean or clean.startswith("."):
        raise ValueError("Der Dateiname ist nicht erlaubt.")
    extension = PurePath(clean).suffix.casefold()
    if extension not in allowed_extensions:
        raise ValueError("Bitte lade ausschließlich CSV- oder XLSX-Dateien hoch.")
    return clean


def reset_security_controls_for_tests() -> None:
    global _RATE_LIMITER, _CONCURRENCY_LIMITER
    _RATE_LIMITER = SlidingWindowLimiter()
    _CONCURRENCY_LIMITER = ConcurrencyLimiter()
