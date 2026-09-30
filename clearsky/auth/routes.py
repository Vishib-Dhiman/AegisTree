"""HTTP endpoints for email-code sign-in."""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from clearsky.auth.mailer import Mailer
from clearsky.auth.otp import OtpError, OtpService
from clearsky.auth.sessions import COOKIE_NAME, SessionManager
from clearsky.auth.store import AuthStore


@dataclass
class Auth:
    store: AuthStore
    otp: OtpService
    mailer: Mailer
    sessions: SessionManager
    secure_cookies: bool = False
    clock: Callable[[], float] = field(default=time.time)

    def user_for(self, request: Request) -> Optional[Dict[str, Any]]:
        return self.sessions.resolve(request.cookies.get(COOKIE_NAME))


class CodeRequest(BaseModel):
    email: str


class VerifyRequest(BaseModel):
    email: str
    code: str


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as ex:
        raise HTTPException(status_code=400, detail=f"That email address doesn't look right: {ex}")


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    email = user["email"]
    name = (user.get("display_name") or "").strip()
    label = name or email.split("@")[0]
    parts = [p for p in label.replace(".", " ").replace("_", " ").split() if p]
    initials = "".join(p[0] for p in parts[:2]).upper() or email[0].upper()
    return {"id": user["id"], "email": email, "display_name": name or None, "label": label, "initials": initials}


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def build_auth_router(auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    @router.post("/request-code")
    def request_code(req: CodeRequest, request: Request) -> Dict[str, Any]:
        email = normalize_email(req.email)
        try:
            code = auth.otp.issue(email, ip=_ip(request))
        except OtpError as ex:
            raise HTTPException(status_code=429, detail=str(ex), headers={"Retry-After": str(ex.retry_after or 60)})
        delivery = auth.mailer.send_code(email, code)
        auth.store.audit(None, "code_requested", {"email": email, "delivery": delivery, "ip": _ip(request)})
        return {"status": "sent", "email": email, "delivery": delivery, "expires_in_s": auth.otp.ttl_s}

    @router.post("/verify")
    def verify(req: VerifyRequest, request: Request, response: Response) -> Dict[str, Any]:
        email = normalize_email(req.email)
        try:
            auth.otp.verify(email, req.code)
        except OtpError as ex:
            auth.store.audit(None, "login_failed", {"email": email, "reason": ex.reason, "ip": _ip(request)})
            raise HTTPException(status_code=400, detail=str(ex))
        user = auth.store.get_or_create_user(email, now=auth.clock())
        auth.store.record_login(user["id"], auth.clock())
        token = auth.sessions.create(user["id"], ip=_ip(request), user_agent=request.headers.get("user-agent"))
        response.set_cookie(value=token, **auth.sessions.cookie_kwargs(auth.secure_cookies))
        auth.store.audit(user["id"], "login", {"ip": _ip(request)})
        return {"status": "ok", "user": public_user(auth.store.user(user["id"]))}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> Dict[str, Any]:
        user = auth.user_for(request)
        auth.sessions.revoke(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path="/")
        if user:
            auth.store.audit(user["id"], "logout")
        return {"status": "ok"}

    @router.get("/me")
    def me(request: Request) -> Dict[str, Any]:
        user = auth.user_for(request)
        if not user:
            raise HTTPException(status_code=401, detail="Not signed in")
        return {"user": public_user(user)}

    @router.patch("/me")
    def update_me(req: ProfileUpdate, request: Request) -> Dict[str, Any]:
        user = auth.user_for(request)
        if not user:
            raise HTTPException(status_code=401, detail="Not signed in")
        name = (req.display_name or "").strip()
        if len(name) > 60:
            raise HTTPException(status_code=400, detail="Name must be 60 characters or fewer.")
        auth.store.set_display_name(user["id"], name or None)
        return {"user": public_user(auth.store.user(user["id"]))}

    return router
