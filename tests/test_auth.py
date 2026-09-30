import os
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clearsky.auth import (
    COOKIE_NAME,
    Auth,
    AuthStore,
    Mailer,
    OtpError,
    OtpService,
    SessionManager,
    SmtpSettings,
    build_auth_router,
    load_or_create_secret,
)


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path: Path):
    return AuthStore(tmp_path / "auth.sqlite")


@pytest.fixture
def otp(store, clock):
    return OtpService(store, b"k" * 32, clock=clock)


# ---- codes ----

def test_code_is_six_digits_and_stored_only_as_hash(otp, store):
    code = otp.issue("a@x.io")
    assert len(code) == 6 and code.isdigit()
    row = store.active_code("a@x.io")
    assert code not in row["code_hash"] and len(row["code_hash"]) == 64


def test_verify_once_then_used_up(otp):
    code = otp.issue("a@x.io")
    otp.verify("a@x.io", code)
    with pytest.raises(OtpError) as ex:
        otp.verify("a@x.io", code)
    assert ex.value.reason == "invalid"


def test_code_expires(otp, clock):
    code = otp.issue("a@x.io")
    clock.t += 601
    with pytest.raises(OtpError) as ex:
        otp.verify("a@x.io", code)
    assert ex.value.reason == "expired"


def test_wrong_attempts_are_limited(otp):
    code = otp.issue("a@x.io")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(OtpError) as ex:
            otp.verify("a@x.io", wrong)
        assert ex.value.reason == "invalid"
    with pytest.raises(OtpError) as ex:
        otp.verify("a@x.io", wrong)
    assert ex.value.reason == "too_many_attempts"
    with pytest.raises(OtpError):
        otp.verify("a@x.io", code)  # even the right code no longer works


def test_new_code_voids_the_old_one(otp, clock):
    first = otp.issue("a@x.io")
    clock.t += 61
    second = otp.issue("a@x.io")
    if first != second:
        with pytest.raises(OtpError):
            otp.verify("a@x.io", first)
    otp.verify("a@x.io", second)


def test_rate_limits(otp, clock):
    otp.issue("a@x.io", ip="10.0.0.2")
    with pytest.raises(OtpError) as ex:
        otp.issue("a@x.io", ip="10.0.0.2")  # within a minute
    assert ex.value.reason == "rate_limited" and ex.value.retry_after <= 60
    for _ in range(4):
        clock.t += 61
        otp.issue("a@x.io", ip="10.0.0.2")
    clock.t += 61
    with pytest.raises(OtpError):
        otp.issue("a@x.io", ip="10.0.0.2")  # 6th in an hour


def test_ip_rate_limit(store, clock):
    otp = OtpService(store, b"k" * 32, clock=clock, per_ip_hourly=3)
    for i in range(3):
        otp.issue(f"u{i}@x.io", ip="10.0.0.9")
    with pytest.raises(OtpError):
        otp.issue("u9@x.io", ip="10.0.0.9")


def test_secret_file_is_private_and_stable(tmp_path: Path):
    path = tmp_path / "secret.key"
    first = load_or_create_secret(path)
    assert load_or_create_secret(path) == first and len(first) == 32
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# ---- sessions ----

def test_session_lifecycle(store, clock):
    sessions = SessionManager(store, clock=clock)
    user = store.get_or_create_user("a@x.io")
    token = sessions.create(user["id"])
    assert sessions.resolve(token)["email"] == "a@x.io"
    assert store.session(token) is None  # only the hash is stored
    clock.t += 6 * 24 * 3600
    assert sessions.resolve(token) is not None  # sliding expiry
    clock.t += 6 * 24 * 3600
    assert sessions.resolve(token) is not None
    sessions.revoke(token)
    assert sessions.resolve(token) is None


def test_session_expires(store, clock):
    sessions = SessionManager(store, clock=clock)
    token = sessions.create(store.get_or_create_user("a@x.io")["id"])
    clock.t += 8 * 24 * 3600
    assert sessions.resolve(token) is None


# ---- mailer ----

class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None, fail=False):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.login_as = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_mailer_sends_over_smtp(tmp_path: Path):
    FakeSMTP.sent = []
    settings = SmtpSettings.from_env({"CLEARSKY_SMTP_HOST": "smtp.example.com", "CLEARSKY_SMTP_USER": "me@example.com",
                                      "CLEARSKY_SMTP_PASSWORD": "pw"})
    mailer = Mailer(settings, tmp_path / "outbox.log", smtp_factory=FakeSMTP)
    assert mailer.send_code("a@x.io", "123456") == "email"
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "a@x.io" and "123456" in msg["Subject"] and "123456" in msg.get_content()
    assert not (tmp_path / "outbox.log").exists()


def test_mailer_falls_back_to_outbox_when_smtp_fails(tmp_path: Path, capsys):
    def offline(*a, **k):
        raise OSError("[Errno 8] nodename nor servname provided")

    settings = SmtpSettings("smtp.example.com", 587, "u", "p", "u@example.com")
    mailer = Mailer(settings, tmp_path / "outbox.log", smtp_factory=offline)
    assert mailer.send_code("a@x.io", "654321") == "outbox"
    assert "654321" in (tmp_path / "outbox.log").read_text()
    assert stat.S_IMODE(os.stat(tmp_path / "outbox.log").st_mode) == 0o600
    assert "654321" in capsys.readouterr().out
    assert "nodename" in mailer.last_error


def test_no_smtp_configured_uses_outbox(tmp_path: Path):
    assert SmtpSettings.from_env({}) is None
    assert Mailer(None, tmp_path / "o.log").send_code("a@x.io", "111222") == "outbox"


# ---- routes ----

@pytest.fixture
def client(tmp_path: Path, store, clock):
    auth = Auth(store=store, otp=OtpService(store, b"k" * 32, clock=clock),
                mailer=Mailer(None, tmp_path / "outbox.log"), sessions=SessionManager(store, clock=clock), clock=clock)
    app = FastAPI()
    app.include_router(build_auth_router(auth))
    return TestClient(app), tmp_path / "outbox.log", clock


def last_code(outbox: Path) -> str:
    return outbox.read_text().strip().splitlines()[-1].split("code=")[1]


def test_sign_up_sign_in_and_out(client):
    c, outbox, _ = client
    r = c.post("/api/auth/request-code", json={"email": "  Priya@Example.COM "})
    assert r.status_code == 200 and r.json()["delivery"] == "outbox"
    email = r.json()["email"]
    assert email == "priya@example.com"

    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/verify", json={"email": email, "code": last_code(outbox)})
    assert r.status_code == 200 and r.json()["user"]["email"] == email
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/auth/me").json()["user"]["initials"] == "P"

    r = c.patch("/api/auth/me", json={"display_name": "Priya Sharma"})
    assert r.json()["user"]["initials"] == "PS"

    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_bad_email_and_bad_code(client):
    c, outbox, clock = client
    assert c.post("/api/auth/request-code", json={"email": "not-an-email"}).status_code == 400
    c.post("/api/auth/request-code", json={"email": "a@x.io"})
    r = c.post("/api/auth/verify", json={"email": "a@x.io", "code": "12"})
    assert r.status_code == 400 and "attempts left" in r.json()["detail"]
    assert COOKIE_NAME not in c.cookies


def test_request_code_rate_limited_with_retry_after(client):
    c, _, _ = client
    c.post("/api/auth/request-code", json={"email": "a@x.io"})
    r = c.post("/api/auth/request-code", json={"email": "a@x.io"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) <= 60
