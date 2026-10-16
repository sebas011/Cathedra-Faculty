import asyncio
import logging
from types import SimpleNamespace

from app.request_timing import SlowRequestMiddleware


def test_slow_request_logs_route_template_without_query_or_record_id(caplog, monkeypatch) -> None:
    ticks = iter((1.0, 2.5))
    monkeypatch.setattr("app.request_timing.perf_counter", lambda: next(ticks))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/faculty-profiles/123",
        "query_string": b"token=private-value",
    }
    messages: list[dict] = []

    async def downstream(current_scope, receive, send) -> None:
        current_scope["route"] = SimpleNamespace(path="/api/v1/faculty-profiles/{profile_id}")
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def unused(*args) -> None:
        return None

    async def capture(message: dict) -> None:
        messages.append(message)

    with caplog.at_level(logging.WARNING, logger="cathedra.performance"):
        asyncio.run(SlowRequestMiddleware(downstream)(scope, unused, capture))
    assert len(messages) == 1
    assert "route=/api/v1/faculty-profiles/{profile_id}" in caplog.text
    assert "duration_ms=1500.0" in caplog.text
    assert "123" not in caplog.text
    assert "private-value" not in caplog.text


def test_quick_request_is_not_logged(caplog, monkeypatch) -> None:
    ticks = iter((1.0, 1.1))
    monkeypatch.setattr("app.request_timing.perf_counter", lambda: next(ticks))

    async def downstream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def unused(*args) -> None:
        return None

    with caplog.at_level(logging.WARNING, logger="cathedra.performance"):
        asyncio.run(
            SlowRequestMiddleware(downstream)(
                {"type": "http", "method": "GET", "path": "/api/v1/health"},
                unused,
                unused,
            )
        )
    assert not caplog.records
