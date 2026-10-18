import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.auth import Credentials, setup_first_admin
from app.bootstrap import SetupCapability
from app.db import Base
from app.models import LocalSession, LocalUser
from app.request_gate import RestoreGateMiddleware, RestoreRequestGate


def scope(application, path="/api/v1/maintenance/restore", method="POST", **kwargs):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "app": application,
        **kwargs,
    }


def test_unauthorized_restore_rejected_before_receive_and_queue():
    async def scenario():
        gate = RestoreRequestGate()

        def reject(request):
            raise HTTPException(401, "Sign in required.")

        application = SimpleNamespace(
            state=SimpleNamespace(restore_request_gate=gate, authorize_restore=reject)
        )
        messages = []

        async def never(*args):
            pytest.fail("Unauthorized restore read a body or reached the route")

        async def send(message):
            messages.append(message)

        middleware = RestoreGateMiddleware(never)
        for path, root in [
            ("/api/v1/maintenance/restore", ""),
            ("/api/v1/maintenance/restore/", ""),
            ("/office/api/v1/maintenance/restore", "/office"),
        ]:
            await middleware(scope(application, path, root_path=root), never, send)
            assert messages[-2]["status"] == 401
            assert gate._restores_waiting == 0
            assert not gate._restore_active

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/v1/maintenance/restore", "/api/v1/faculty-profiles"])
def test_incomplete_bodies_do_not_hold_either_gate(path):
    async def scenario():
        gate = RestoreRequestGate()
        application = SimpleNamespace(
            state=SimpleNamespace(restore_request_gate=gate, authorize_restore=lambda request: None)
        )
        waiting = asyncio.Event()
        health = asyncio.Event()

        async def incomplete():
            waiting.set()
            await asyncio.Event().wait()

        async def empty():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        async def downstream(request_scope, receive, send):
            assert await receive() == {"type": "http.request", "body": b"", "more_body": False}
            health.set()

        middleware = RestoreGateMiddleware(downstream)
        pending = asyncio.create_task(middleware(scope(application, path), incomplete, send))
        await asyncio.wait_for(waiting.wait(), 1)
        assert gate._active_requests == 0 and gate._restores_waiting == 0
        await asyncio.wait_for(
            middleware(scope(application, "/api/v1/health", "GET"), empty, send), 1
        )
        assert health.is_set()
        # Even a legitimate restore must remain possible during the ordinary slow body.
        await asyncio.wait_for(middleware(scope(application), empty, send), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert gate._active_requests == 0 and not gate._restore_active

    asyncio.run(scenario())


def test_body_limits_timeout_disconnect_and_replay():
    async def scenario():
        gate = RestoreRequestGate()
        application = SimpleNamespace(
            state=SimpleNamespace(restore_request_gate=gate, authorize_restore=lambda request: None)
        )
        responses = []
        bodies = []

        async def send(message):
            if message["type"] == "http.response.start":
                responses.append(message["status"])

        async def downstream(request_scope, receive, send):
            bodies.append((await receive())["body"])

        middleware = RestoreGateMiddleware(downstream, body_timeout=0.02, max_body_bytes=4)

        async def invoke(messages):
            async def receive():
                if messages:
                    return messages.pop(0)
                await asyncio.Event().wait()

            await middleware(scope(application), receive, send)

        await invoke(
            [
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"45"},
            ]
        )
        assert responses == [413]
        await invoke([{"type": "http.request", "body": b"1", "more_body": True}])
        assert responses == [413, 408]
        await invoke([{"type": "http.disconnect"}])
        assert not bodies
        await invoke(
            [
                {"type": "http.request", "body": b"12", "more_body": True},
                {"type": "http.request", "body": b"34"},
            ]
        )
        assert bodies == [b"1234"]
        assert gate._active_requests == 0 and gate._restores_waiting == 0

    asyncio.run(scenario())


def test_restore_preflight_uses_real_admin_authentication(client):
    assert (
        client.post(
            "/api/v1/maintenance/restore", headers={"Authorization": ""}, content=b"{"
        ).status_code
        == 401
    )
    user = client.post(
        "/api/v1/auth/users",
        json={"username": "restore-staff", "password": "staff-password-123", "role": "staff"},
    )
    assert user.status_code == 201
    session = client.post(
        "/api/v1/auth/login", json={"username": "restore-staff", "password": "staff-password-123"}
    ).json()
    assert (
        client.post(
            "/api/v1/maintenance/restore",
            headers={"Authorization": f"Bearer {session['token']}"},
            content=b"{",
        ).status_code
        == 403
    )
    assert client.post("/api/v1/maintenance/restore", content=b"{").status_code == 422


def test_bootstrap_requires_private_proof_then_consumes_it(tmp_path):
    capability = SetupCapability(tmp_path, "http://127.0.0.1:18181")
    entry = capability.entry_path
    text = entry.read_text(encoding="utf-8")
    assert "http://127.0.0.1:18181/login#setup-key=" in text
    key = re.search(r"#setup-key=([A-Za-z0-9_-]{43})", text).group(1)
    application = SimpleNamespace(state=SimpleNamespace(setup_capability=capability))

    def request(values):
        return Request(
            scope(
                application,
                "/api/v1/auth/setup",
                headers=[(b"x-cathedra-setup-key", value) for value in values],
            )
        )

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    credentials = Credentials(username="owner-admin", password="owner-password-123")
    try:
        with Session(engine) as db:
            for values in [
                [],
                [b"wrong"],
                [key.encode(), key.encode()],
                [b"a" * 10000],
                [b"\xff" * 43],
            ]:
                with pytest.raises(HTTPException) as caught:
                    setup_first_admin(credentials, request(values), db)
                assert caught.value.status_code == 403
                assert db.scalar(select(func.count()).select_from(LocalUser)) == 0
                assert db.scalar(select(func.count()).select_from(LocalSession)) == 0
                db.rollback()
            application.state.setup_capability = None
            with pytest.raises(HTTPException) as caught:
                setup_first_admin(credentials, request([key.encode()]), db)
            assert caught.value.status_code == 403
            application.state.setup_capability = capability
            result = setup_first_admin(credentials, request([key.encode()]), db)
            assert result["user"]["role"] == "admin" and result["token"]
            assert not entry.exists()
            assert key not in str(result)
            with pytest.raises(HTTPException) as caught:
                capability.require(request([key.encode()]))
            assert caught.value.status_code == 403
            db.rollback()
            with pytest.raises(HTTPException) as caught:
                setup_first_admin(credentials, request([key.encode()]), db)
            assert caught.value.status_code == 409
    finally:
        capability.consume()
        engine.dispose()


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com",
        "http://192.168.1.2:8102",
        "http://user:password@localhost",
        "http://localhost/?key=1",
    ],
)
def test_setup_entry_never_redirects_to_a_remote_origin(tmp_path, origin):
    with pytest.raises(RuntimeError):
        SetupCapability(tmp_path, origin)
    assert not list(tmp_path.glob(".setup-*"))


def test_direct_startup_private_setup_and_configured_restart(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import app.main as main

    database = tmp_path / "cathedra.db"
    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "DB_PATH", database)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(main, "initialize_database", lambda: None)
    monkeypatch.setenv("CATHEDRA_SETUP_ORIGIN", "http://127.0.0.1:5175")
    from app.db import get_db

    def db_session():
        with Session(engine) as db:
            yield db

    main.app.dependency_overrides[get_db] = db_session
    credentials = {"username": "direct-owner", "password": "direct-password-123"}
    try:
        with TestClient(main.app, base_url="http://127.0.0.1") as client:
            entry = main.app.state.setup_capability.entry_path
            assert "http://127.0.0.1:5175/login#setup-key=" in entry.read_text()
            assert client.post("/api/v1/auth/setup", json=credentials).status_code == 403
            assert client.get("/api/v1/auth/status").json() == {"setup_required": True}
            key = re.search(r"#setup-key=([A-Za-z0-9_-]{43})", entry.read_text()).group(1)
            result = client.post(
                "/api/v1/auth/setup", json=credentials, headers={"X-Cathedra-Setup-Key": key}
            )
            assert result.status_code == 201
            assert not entry.exists()
        with TestClient(main.app, base_url="http://127.0.0.1") as client:
            assert main.app.state.setup_capability is None
            assert client.get("/api/v1/auth/status").json() == {"setup_required": False}
            assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
