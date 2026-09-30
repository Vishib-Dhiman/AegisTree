"""SQLite storage for users, one-time codes, sessions and the audit log.

Times are Unix seconds (float). Codes and session tokens are stored only as
hashes; the plaintext never touches the database.
"""

from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT,
  created_at REAL NOT NULL,
  last_login_at REAL,
  last_workspace TEXT
);
CREATE TABLE IF NOT EXISTS otp_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed INTEGER NOT NULL DEFAULT 0,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS otp_email ON otp_codes(email, created_at);
CREATE INDEX IF NOT EXISTS otp_ip ON otp_codes(ip, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  ip TEXT,
  user_agent TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL,
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT
);
"""


class AuthStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _one(self, sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(sql, args)
            return cur.lastrowid

    # users
    def user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self._one("SELECT * FROM users WHERE email = ?", (email,))

    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._one("SELECT * FROM users WHERE id = ?", (user_id,))

    def get_or_create_user(self, email: str, now: Optional[float] = None) -> Dict[str, Any]:
        existing = self.user_by_email(email)
        if existing:
            return existing
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (email, created_at) VALUES (?, ?)",
                (email, now if now is not None else time.time()),
            )
        return self.user_by_email(email)

    def record_login(self, user_id: int, now: float) -> None:
        self._exec("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))

    def set_display_name(self, user_id: int, name: Optional[str]) -> None:
        self._exec("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))

    def set_last_workspace(self, user_id: int, workspace: Optional[str]) -> None:
        self._exec("UPDATE users SET last_workspace = ? WHERE id = ?", (workspace, user_id))

    def count_users(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]

    # one-time codes
    def void_codes(self, email: str) -> None:
        self._exec("UPDATE otp_codes SET consumed = 1 WHERE email = ? AND consumed = 0", (email,))

    def add_code(self, email: str, code_hash: str, now: float, expires_at: float, ip: Optional[str]) -> None:
        self._exec(
            "INSERT INTO otp_codes (email, code_hash, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
            (email, code_hash, now, expires_at, ip),
        )

    def active_code(self, email: str) -> Optional[Dict[str, Any]]:
        return self._one(
            "SELECT * FROM otp_codes WHERE email = ? AND consumed = 0 ORDER BY created_at DESC LIMIT 1",
            (email,),
        )

    def bump_attempts(self, code_id: int) -> None:
        self._exec("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (code_id,))

    def consume_code(self, code_id: int) -> None:
        self._exec("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (code_id,))

    def codes_since(self, email: str, since: float) -> int:
        return self._one("SELECT COUNT(*) AS n FROM otp_codes WHERE email = ? AND created_at >= ?", (email, since))["n"]

    def codes_from_ip_since(self, ip: str, since: float) -> int:
        return self._one("SELECT COUNT(*) AS n FROM otp_codes WHERE ip = ? AND created_at >= ?", (ip, since))["n"]

    def last_code_at(self, email: str) -> Optional[float]:
        row = self._one("SELECT MAX(created_at) AS t FROM otp_codes WHERE email = ?", (email,))
        return row["t"] if row else None

    # sessions
    def add_session(self, token_hash: str, user_id: int, now: float, expires_at: float,
                    ip: Optional[str], user_agent: Optional[str]) -> None:
        self._exec(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at, ip, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at, now, ip, (user_agent or "")[:300]),
        )

    def session(self, token_hash: str) -> Optional[Dict[str, Any]]:
        return self._one("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,))

    def refresh_session(self, token_hash: str, now: float, expires_at: float) -> None:
        self._exec("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?", (now, expires_at, token_hash))

    def delete_session(self, token_hash: str) -> None:
        self._exec("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def purge_expired(self, now: float) -> None:
        self._exec("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self._exec("DELETE FROM otp_codes WHERE created_at < ?", (now - 86400,))

    # audit
    def audit(self, user_id: Optional[int], action: str, detail: Any = None, now: Optional[float] = None) -> None:
        text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, default=str)
        self._exec(
            "INSERT INTO audit (at, user_id, action, detail) VALUES (?, ?, ?, ?)",
            (now if now is not None else time.time(), user_id, action, text),
        )

    def recent_audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT a.at, a.action, a.detail, u.email FROM audit a LEFT JOIN users u ON u.id = a.user_id "
                "ORDER BY a.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
