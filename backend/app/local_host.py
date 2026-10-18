"""Enforce the desktop service's documented loopback HTTP authorities."""

import re

from starlette.responses import PlainTextResponse

_AUTHORITY = re.compile(r"(?:localhost|127\.0\.0\.1)(?::([0-9]{1,5}))?", re.IGNORECASE)


class LocalHostMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hosts = [value for key, value in scope.get("headers", ()) if key.lower() == b"host"]
        try:
            authority = hosts[0].decode("ascii") if len(hosts) == 1 else ""
        except UnicodeDecodeError:
            authority = ""
        match = _AUTHORITY.fullmatch(authority)
        if match is None or (match[1] is not None and not 1 <= int(match[1]) <= 65535):
            await PlainTextResponse("Invalid local service host.", status_code=400)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
