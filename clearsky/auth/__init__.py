"""Email one-time-code sign-in for ClearSky.

Open sign-up: any valid email can request a code, and the account is created
the first time a code is verified. Sessions are opaque random tokens kept in an
HttpOnly cookie; only their hashes are stored.
"""

from clearsky.auth.mailer import Mailer, SmtpSettings
from clearsky.auth.otp import OtpError, OtpService, load_or_create_secret
from clearsky.auth.routes import Auth, build_auth_router
from clearsky.auth.sessions import COOKIE_NAME, SessionManager
from clearsky.auth.store import AuthStore

__all__ = [
    "Auth",
    "AuthStore",
    "COOKIE_NAME",
    "Mailer",
    "OtpError",
    "OtpService",
    "SessionManager",
    "SmtpSettings",
    "build_auth_router",
    "load_or_create_secret",
]
