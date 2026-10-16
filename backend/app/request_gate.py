import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RestoreRequestGate:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_requests = 0
        self._restore_active = False
        self._restores_waiting = 0

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._restore_active and self._restores_waiting == 0
            )
            self._active_requests += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_requests -= 1
                if self._active_requests == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        async with self._condition:
            self._restores_waiting += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._restore_active and self._active_requests == 0
                )
                self._restore_active = True
            finally:
                self._restores_waiting -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._restore_active = False
                self._condition.notify_all()


class RestoreGateMiddleware:
    def __init__(
        self, app: ASGIApp, body_timeout: float = 10, max_body_bytes: int = 1024 * 1024
    ) -> None:
        self.app = app
        self.body_timeout = body_timeout
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        gate: RestoreRequestGate = scope["app"].state.restore_request_gate
        path = scope["path"]
        root = scope.get("root_path", "").rstrip("/")
        if root and path.startswith(root + "/"):
            path = path[len(root) :]
        is_restore = scope["method"] == "POST" and path.rstrip("/") == "/api/v1/maintenance/restore"
        if is_restore:
            authorize = getattr(scope["app"].state, "authorize_restore", None)
            if authorize is None:
                await JSONResponse({"detail": "Restore authorization is unavailable."}, 503)(
                    scope, receive, send
                )
                return
            try:
                # Authentication reads the database, but never reads the client body.
                async with gate.shared():
                    await run_in_threadpool(authorize, Request(scope))
            except HTTPException as caught:
                await JSONResponse(
                    {"detail": caught.detail}, caught.status_code, headers=caught.headers
                )(scope, receive, send)
                return

        # No request may hold a database gate while waiting for client-controlled bytes.
        body = bytearray()
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.max_body_bytes:
                        await JSONResponse({"detail": "Request body is too large."}, 413)(
                            scope, receive, send
                        )
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "Request body timed out."}, 408)(scope, receive, send)
            return

        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        async with gate.exclusive() if is_restore else gate.shared():
            # The route also revalidates the session after obtaining exclusivity.
            await self.app(scope, replay, send)
