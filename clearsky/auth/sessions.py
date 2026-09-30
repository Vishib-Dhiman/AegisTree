"""Sign-in sessions: random tokens in an HttpOnly cookie, stored hashed."""

from __future__ import annotations
import hashlib
import secrets
import time
from typing import Any, Callable, Dict, Optional

from clearsky.auth.store import AuthStore

COOKIE_NAME = "clearsky_session"
SESSION_TTL_S = 7 * 24 * 3600
REFRESH_AFTER_S = 3600  # slide the expiry at most once an hour


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionManager:
    def __init__(self, store: AuthStore, clock: Callable[[], float] = time.time, ttl_s: int = SESSION_TTL_S):
        self.store = store
        self.clock = clock
        self.ttl_s = ttl_s

    def create(self, user_id: int, ip: Optional[str] = None, user_agent: Optional[str] = None) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        self.store.add_session(_hash(token), user_id, now, now + self.ttl_s, ip, user_agent)
        return token

    def resolve(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """The signed-in user for a cookie value, or None. Extends active sessions."""
        if not token:
            return None
        token_hash = _hash(token)
        row = self.store.session(token_hash)
        if row is None:
            return None
        now = self.clock()
        if now > row["expires_at"]:
            self.store.delete_session(token_hash)
            return None
        if now - row["last_seen_at"] > REFRESH_AFTER_S:
            self.store.refresh_session(token_hash, now, now + self.ttl_s)
        return self.store.user(row["user_id"])

    def revoke(self, token: Optional[str]) -> None:
        if token:
            self.store.delete_session(_hash(token))

    def cookie_kwargs(self, secure: bool) -> Dict[str, Any]:
        return {
            "key": COOKIE_NAME,
            "max_age": self.ttl_s,
            "httponly": True,
            "secure": secure,
            "samesite": "strict",
            "path": "/",
        }
