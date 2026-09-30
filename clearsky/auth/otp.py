"""One-time sign-in codes: issue, rate-limit, verify."""

from __future__ import annotations
import hashlib
import hmac
import math
import os
import secrets
import time
from pathlib import Path
from typing import Callable, Optional

from clearsky.auth.store import AuthStore


class OtpError(Exception):
    """reason: rate_limited | invalid | expired | too_many_attempts"""

    def __init__(self, reason: str, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


def load_or_create_secret(path: Path) -> bytes:
    """32 random bytes used to HMAC codes; created once with owner-only permissions."""
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(secret)
    return secret


class OtpService:
    def __init__(
        self,
        store: AuthStore,
        secret: bytes,
        clock: Callable[[], float] = time.time,
        ttl_s: int = 600,
        max_attempts: int = 5,
        resend_interval_s: int = 60,
        per_email_hourly: int = 5,
        per_ip_hourly: int = 20,
    ):
        self.store = store
        self.secret = secret
        self.clock = clock
        self.ttl_s = ttl_s
        self.max_attempts = max_attempts
        self.resend_interval_s = resend_interval_s
        self.per_email_hourly = per_email_hourly
        self.per_ip_hourly = per_ip_hourly

    def _hash(self, email: str, code: str) -> str:
        return hmac.new(self.secret, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()

    def issue(self, email: str, ip: Optional[str] = None) -> str:
        """A fresh 6-digit code for email; older unused codes stop working."""
        now = self.clock()
        last = self.store.last_code_at(email)
        if last is not None and now - last < self.resend_interval_s:
            wait = max(1, math.ceil(self.resend_interval_s - (now - last)))
            raise OtpError("rate_limited", f"Please wait {wait}s before requesting another code.", wait)
        if self.store.codes_since(email, now - 3600) >= self.per_email_hourly:
            raise OtpError("rate_limited", "Too many codes requested for this email. Try again later.", 3600)
        if ip and self.store.codes_from_ip_since(ip, now - 3600) >= self.per_ip_hourly:
            raise OtpError("rate_limited", "Too many codes requested from this device. Try again later.", 3600)

        code = f"{secrets.randbelow(1_000_000):06d}"
        self.store.void_codes(email)
        self.store.add_code(email, self._hash(email, code), now, now + self.ttl_s, ip)
        return code

    def verify(self, email: str, code: str) -> None:
        """Returns quietly on success (the code is then used up); raises OtpError otherwise."""
        code = "".join(ch for ch in str(code) if ch.isdigit())
        row = self.store.active_code(email)
        if row is None:
            raise OtpError("invalid", "No active code for this email. Request a new one.")
        if self.clock() > row["expires_at"]:
            self.store.consume_code(row["id"])
            raise OtpError("expired", "This code has expired. Request a new one.")
        if row["attempts"] >= self.max_attempts:
            self.store.consume_code(row["id"])
            raise OtpError("too_many_attempts", "Too many wrong attempts. Request a new code.")
        if len(code) != 6 or not hmac.compare_digest(row["code_hash"], self._hash(email, code)):
            self.store.bump_attempts(row["id"])
            left = self.max_attempts - row["attempts"] - 1
            if left <= 0:
                self.store.consume_code(row["id"])
                raise OtpError("too_many_attempts", "Too many wrong attempts. Request a new code.")
            raise OtpError("invalid", f"That code is not right. {left} attempt{'s' if left != 1 else ''} left.")
        self.store.consume_code(row["id"])
