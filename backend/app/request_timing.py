import logging
from time import perf_counter

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("cathedra.performance")


class SlowRequestMiddleware:
    def __init__(self, app: ASGIApp, threshold_ms: float = 1000) -> None:
        self.app = app
        self.threshold_ms = threshold_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status_code = 500

        async def send_with_status(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            duration_ms = (perf_counter() - started) * 1000
            if duration_ms >= self.threshold_ms:
                route = scope.get("route")
                route_name = getattr(route, "path", "<unmatched>")
                logger.warning(
                    "slow_request method=%s route=%s status=%s duration_ms=%.1f",
                    scope["method"],
                    route_name,
                    status_code,
                    duration_ms,
                )
