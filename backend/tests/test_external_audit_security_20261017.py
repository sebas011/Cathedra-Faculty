import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.main as main
from app.local_host import LocalHostMiddleware
from app.login_throttle import LoginThrottle, login_throttle
from app.models import ActivityEvent


@pytest.mark.parametrize(
    "host",
    [
        "evil.example.com",
        "localhost.evil.example",
        "127.0.0.1.evil.example",
        "localhost@evil.example",
        "evil.example@localhost",
        "localhost/path",
        "localhost,evil.example",
        "localhost:0",
        "localhost:65536",
        "localhost:abc",
        "localhost:",
        " localhost",
        "localhost ",
        "localhost\r\nX-Test: value",
        "localhost.",
        "[::1]",
        "127.1",
        "127.0.0.1:80:90",
    ],
)
def test_host_boundary_rejects_other_authorities_without_reading_request(host):
    async def app(scope, receive, send):
        raise AssertionError("Rejected host reached application/database boundary")

    async def receive():
        raise AssertionError("Rejected host consumed a request body")

    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(
        LocalHostMiddleware(app)(
            {"type": "http", "headers": [(b"host", host.encode())]}, receive, send
        )
    )
    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"host", b"localhost"), (b"Host", b"evil")],
        [(b"host", b"localhost"), (b"host", b"localhost")],
        [(b"host", b"\xff")],
    ],
)
def test_host_boundary_rejects_ambiguous_or_non_ascii_authorities(headers):
    statuses = []

    async def app(*_):
        raise AssertionError("Invalid host reached app")

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    asyncio.run(LocalHostMiddleware(app)({"type": "http", "headers": headers}, None, send))
    assert statuses == [400]


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.1:8102", "localhost", "LOCALHOST:5175", "LocalHost:65535"]
)
def test_documented_hosts_keep_health_and_auth_boundaries(client, host):
    assert client.get("/api/v1/health", headers={"Host": host}).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Host": host}).status_code == 200
    client.headers.clear()
    assert client.get("/api/v1/faculty-profiles", headers={"Host": host}).status_code == 401


def test_wrong_current_password_keeps_existing_sign_in(client):
    before = client.get("/api/v1/auth/me").json()
    response = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "mistyped", "new_password": "different-password-123"},
    )
    assert response.status_code == 400
    assert client.get("/api/v1/auth/me").json() == before
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password-123"}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer expired"}).status_code
        == 401
    )


def test_successful_logins_do_not_consume_failure_allowance(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "test-password-123"},
            ).status_code
            == 200
        )
    assert not login_throttle.entries and not login_throttle.registered_entries
    assert not login_throttle.pending


def test_failed_account_does_not_lock_other_loopback_accounts():
    limiter = LoginThrottle(capacity=8)
    for _ in range(8):
        limiter.finish(limiter.check(" targeted ", "127.0.0.1"), failed=True)
    with pytest.raises(HTTPException) as rejected:
        limiter.check("TARGETED", "different-peer")
    assert rejected.value.status_code == 429
    for index in range(45):
        limiter.finish(limiter.check(f"different-{index}", "127.0.0.1"), success=True)
    assert len(limiter.entries) == 1


def test_failure_state_is_bounded_success_resets_only_its_account():
    limiter = LoginThrottle(capacity=3)
    for index in range(12):
        limiter.finish(limiter.check(f"account-{index}", "local"), failed=True)
    assert len(limiter.entries) == 3
    limiter.finish(limiter.check("account-11", "local"), success=True)
    assert len(limiter.entries) == 2
    assert not limiter.pending


@pytest.mark.parametrize("capacity", [3, 4096])
def test_registered_account_limit_survives_unknown_name_churn(monkeypatch, capacity):
    clock = [10.0]
    monkeypatch.setattr("app.login_throttle.time.monotonic", lambda: clock[0])
    limiter = LoginThrottle(capacity=capacity)
    for _ in range(8):
        ticket = limiter.check("registered", "local")
        limiter.mark_registered(ticket)
        limiter.finish(ticket, failed=True)
    with pytest.raises(HTTPException):
        limiter.check("registered", "local")
    for index in range(capacity + 1):
        limiter.finish(limiter.check(f"unknown-{index}", "local"), failed=True)
    with pytest.raises(HTTPException) as rejected:
        limiter.check("REGISTERED", "local")
    assert rejected.value.headers["Retry-After"] == "300"
    assert len(limiter.entries) == capacity and len(limiter.registered_entries) == 1
    # An existing blocked account and guessed-name capacity do not block another.
    other = limiter.check("other-registered", "local")
    limiter.mark_registered(other)
    limiter.finish(other, success=True)
    assert len(limiter.registered_entries) == 1
    clock[0] += 301
    ticket = limiter.check("registered", "local")
    limiter.mark_registered(ticket)
    limiter.finish(ticket, success=True)
    assert not limiter.registered_entries and not limiter._registered_tickets


def test_login_protects_real_account_limit_from_guessed_names(client, monkeypatch):
    monkeypatch.setattr(login_throttle, "capacity", 2)
    assert (
        client.post(
            "/api/v1/auth/users",
            json={"username": "other-admin", "password": "other-password-123", "role": "admin"},
        ).status_code
        == 201
    )
    for _ in range(8):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "incorrect-password"},
            ).status_code
            == 401
        )
    for index in range(3):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": f"unknown-{index}", "password": "incorrect-password"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "TEST-ADMIN", "password": "test-password-123"},
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "other-admin", "password": "other-password-123"},
        ).status_code
        == 200
    )


def test_pending_guesses_reserve_the_remaining_failure_allowance():
    limiter = LoginThrottle()
    for _ in range(7):
        limiter.finish(limiter.check("account", "local"), failed=True)
    ticket = limiter.check("account", "local")
    with pytest.raises(HTTPException):
        limiter.check("ACCOUNT", "local")
    limiter.finish(ticket, success=True)
    limiter.finish(limiter.check("account", "local"), success=True)
    assert not limiter.pending and not limiter.entries


def test_throttle_normalization_matches_sqlite_login_identity():
    limiter = LoginThrottle()
    for _ in range(8):
        limiter.finish(limiter.check("Straße", "local"), failed=True)
    with pytest.raises(HTTPException):
        limiter.check("STRAßE", "local")
    limiter.finish(limiter.check("Strasse", "local"), success=True)


def test_concurrent_admission_bounds_verification_and_releases_errors():
    limiter = LoginThrottle()
    barrier = Barrier(12)

    def reserve(_):
        barrier.wait(timeout=10)
        try:
            return limiter.check("same-account", "local")
        except HTTPException as caught:
            assert caught.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        tickets = [ticket for ticket in pool.map(reserve, range(12)) if ticket is not None]
    assert len(tickets) == 8
    for ticket in tickets:
        limiter.finish(ticket)
        limiter.finish(ticket)  # Releasing twice cannot underflow another request.
    assert not limiter.pending and not limiter.entries
    tickets = [limiter.check(str(index), "local") for index in range(40)]
    with pytest.raises(HTTPException):
        limiter.check("another", "local")
    limiter.finish(tickets.pop(), success=True)
    limiter.finish(limiter.check("another", "local"), success=True)
    for ticket in tickets:
        limiter.finish(ticket)
    assert not limiter.pending


def test_auth_activity_has_authenticated_actors_and_no_guessed_identity(client):
    guessed = "private-guess@example.invalid"
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": guessed, "password": "wrong-password-123"}
        ).status_code
        == 401
    )
    with main.SessionLocal() as db:
        event = db.scalars(
            select(ActivityEvent).where(ActivityEvent.action == "Sign-in rejected")
        ).one()
        assert event.username is None and event.user_id is None
        assert guessed not in str(vars(event)) and "wrong-password" not in str(vars(event))
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    with main.SessionLocal() as db:
        event = db.scalars(select(ActivityEvent).where(ActivityEvent.action == "Signed out")).one()
        assert event.username == "test-admin"


def test_anonymous_failure_activity_budget_is_bounded_and_expires(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.login_throttle.time.monotonic", lambda: clock[0])
    limiter = LoginThrottle()
    assert all(limiter.allow_failure_diagnostic() for _ in range(40))
    assert not limiter.allow_failure_diagnostic()
    clock[0] = 301.0
    assert limiter.allow_failure_diagnostic()
