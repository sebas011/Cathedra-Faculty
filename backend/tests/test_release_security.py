import base64
import hashlib
import logging

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import password_hash, verify_password
from app.local_logging import configure_local_logging
from app.login_throttle import LoginThrottle
from app.models import LocalUser


def test_throttle_normalizes_accounts_expires_and_bounds(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.login_throttle.time.monotonic", lambda: clock[0])
    limiter = LoginThrottle(capacity=8)
    for _ in range(8):
        limiter.check(" ADMIN ", "local")
    with pytest.raises(HTTPException) as failure:
        limiter.check("admin", "another")
    assert failure.value.status_code == 429
    assert failure.value.headers["Retry-After"] == "300"
    clock[0] += 301
    limiter.check("admin", "local")
    for account in ("other", "next", "last"):
        limiter.check(account, "local")
    assert len(limiter.entries) <= 8


def test_password_legacy_and_unsafe_hashes():
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", b"legacy-password", salt, 310_000)
    legacy = (
        "pbkdf2_sha256$310000$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )
    assert verify_password("legacy-password", legacy)
    assert password_hash("legacy-password").startswith("pbkdf2_sha256$600000$")
    assert not verify_password("legacy-password", legacy.replace("310000", "999999999"))
    assert not verify_password("legacy-password", "broken")


def test_successful_login_upgrades_legacy_password(client):
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", b"test-password-123", salt, 310_000)
    stored = (
        "pbkdf2_sha256$310000$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )
    with main.SessionLocal() as db:
        user = db.query(LocalUser).filter_by(username="test-admin").one()
        user.password_hash = stored
        db.commit()
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "incorrect-password"}
        ).status_code
        == 401
    )
    with main.SessionLocal() as db:
        assert db.query(LocalUser).filter_by(username="test-admin").one().password_hash == stored
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password-123"}
        ).status_code
        == 200
    )
    with main.SessionLocal() as db:
        assert (
            db.query(LocalUser)
            .filter_by(username="test-admin")
            .one()
            .password_hash.startswith("pbkdf2_sha256$600000$")
        )


def test_origin_limit_cannot_be_bypassed_with_different_usernames():
    limiter = LoginThrottle()
    for index in range(40):
        limiter.check(f"account-{index}", "local")
    with pytest.raises(HTTPException) as failure:
        limiter.check("yet-another-account", "local")
    assert failure.value.status_code == 429


def test_headers_and_login_limit(client):
    response = client.get("/api/v1/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    for _ in range(8):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "missing", "password": "invalid-password"}
            ).status_code
            == 401
        )
    limited = client.post(
        "/api/v1/auth/login", json={"username": "missing", "password": "invalid-password"}
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_staff_cannot_backup_or_exit(client):
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "staff-secure", "password": "staff-password-123", "role": "staff"},
    )
    assert created.status_code == 201
    auth = client.post(
        "/api/v1/auth/login", json={"username": "staff-secure", "password": "staff-password-123"}
    ).json()
    client.headers["Authorization"] = f"Bearer {auth['token']}"
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "staff-password-123", "new_password": "changed-password-123"},
        ).status_code
        == 204
    )
    auth = client.post(
        "/api/v1/auth/login", json={"username": "staff-secure", "password": "changed-password-123"}
    ).json()
    client.headers["Authorization"] = f"Bearer {auth['token']}"
    for path in ("/api/v1/maintenance/backups", "/api/v1/desktop/exit"):
        assert client.post(path).status_code == 403


def test_diagnostics_never_record_exception_payload(tmp_path):
    handler = configure_local_logging(tmp_path)
    try:
        try:
            raise ValueError("SECRET password token salary")
        except ValueError:
            logging.getLogger("uvicorn.error").exception("SECRET credentials")
        handler.flush()
        content = (tmp_path / "logs" / "service.log").read_text()
        assert "ValueError" in content
        assert "SECRET" not in content
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
