"""Deliver sign-in codes by SMTP, falling back to a local outbox.

SMTP settings come only from environment variables so the password never ends
up in .aegis/config.json or git:
  CLEARSKY_SMTP_HOST, CLEARSKY_SMTP_PORT (587 = STARTTLS, 465 = SSL),
  CLEARSKY_SMTP_USER, CLEARSKY_SMTP_PASSWORD, CLEARSKY_SMTP_FROM
When SMTP is not configured, or sending fails (e.g. Wi-Fi is off), the code is
appended to the outbox file and printed on the server console instead.
"""

from __future__ import annotations
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Literal, Mapping, Optional

log = logging.getLogger("clearsky.auth")


@dataclass
class SmtpSettings:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    sender: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Optional["SmtpSettings"]:
        host = env.get("CLEARSKY_SMTP_HOST", "").strip()
        if not host:
            return None
        user = env.get("CLEARSKY_SMTP_USER") or None
        return cls(
            host=host,
            port=int(env.get("CLEARSKY_SMTP_PORT", "587")),
            user=user,
            password=env.get("CLEARSKY_SMTP_PASSWORD") or None,
            sender=env.get("CLEARSKY_SMTP_FROM") or user or "clearsky@localhost",
        )


class Mailer:
    def __init__(
        self,
        settings: Optional[SmtpSettings],
        outbox_path: Path,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
        smtp_ssl_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP_SSL,
        timeout_s: float = 5.0,
    ):
        self.settings = settings
        self.outbox_path = Path(outbox_path)
        self.smtp_factory = smtp_factory
        self.smtp_ssl_factory = smtp_ssl_factory
        self.timeout_s = timeout_s
        self.last_error: Optional[str] = None

    def send_code(self, email: str, code: str) -> Literal["email", "outbox"]:
        if self.settings is not None:
            try:
                self._send_smtp(email, code)
                self.last_error = None
                return "email"
            except Exception as ex:  # offline, bad credentials, provider down
                self.last_error = f"{type(ex).__name__}: {ex}"
                log.warning("ClearSky: could not email sign-in code (%s); using the outbox", self.last_error)
        self._to_outbox(email, code)
        return "outbox"

    def _message(self, email: str, code: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"{code} is your ClearSky sign-in code"
        msg["From"] = self.settings.sender
        msg["To"] = email
        msg.set_content(
            f"Your ClearSky sign-in code is {code}.\n\n"
            "It expires in 10 minutes and works once. If you did not ask for it, ignore this email.\n"
        )
        return msg

    def _send_smtp(self, email: str, code: str) -> None:
        s = self.settings
        context = ssl.create_default_context()
        if s.port == 465:
            server = self.smtp_ssl_factory(s.host, s.port, timeout=self.timeout_s, context=context)
        else:
            server = self.smtp_factory(s.host, s.port, timeout=self.timeout_s)
        with server:
            if s.port != 465:
                server.starttls(context=context)
            if s.user and s.password:
                server.login(s.user, s.password)
            server.send_message(self._message(email, code))

    def _to_outbox(self, email: str, code: str) -> None:
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"{stamp}  to={email}  code={code}\n"
        fd = os.open(self.outbox_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(line)
        print(f"[ClearSky] Sign-in code for {email}: {code} (not emailed; also in {self.outbox_path})", flush=True)
