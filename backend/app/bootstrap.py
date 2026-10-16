"""First-admin authority delivered through a private, short-lived local file."""

import hashlib
import hmac
import html
import os
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


class SetupCapability:
    def __init__(self, data_directory: Path, origin: str) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("First-time setup requires a local HTTP origin.")
        if os.name == "nt" and sys.version_info < (3, 13):
            raise RuntimeError("Private first-time setup requires Python 3.13 or newer on Windows.")
        data_directory.mkdir(parents=True, exist_ok=True)
        # mkdtemp creates mode 0700 atomically. On Windows 3.13+ this grants
        # access to the creating user and Administrators, excluding other users.
        self.directory = Path(tempfile.mkdtemp(prefix=".setup-", dir=data_directory))
        self.entry_path = self.directory / "start.html"
        token = secrets.token_urlsafe(32)
        self._digest: bytes | None = hashlib.sha256(token.encode("ascii")).digest()
        destination = html.escape(f"{origin.rstrip('/')}/login#setup-key={token}", quote=True)
        try:
            self.entry_path.write_text(
                '<!doctype html><html><head><meta charset="utf-8">'
                '<meta name="referrer" content="no-referrer">'
                f'<meta http-equiv="refresh" content="0;url={destination}">'
                "<title>Cathedra setup</title></head><body>"
                f'<a href="{destination}">Open Cathedra first-time setup</a></body></html>',
                encoding="utf-8",
            )
        except Exception:
            self.consume()
            raise

    def require(self, request: Request) -> None:
        values = request.headers.getlist("x-cathedra-setup-key")
        value = values[0] if len(values) == 1 else ""
        valid_shape = len(value) == 43 and value.isascii()
        candidate = hashlib.sha256(value.encode("ascii")).digest() if valid_shape else b""
        if self._digest is None or not hmac.compare_digest(candidate, self._digest):
            raise HTTPException(
                status_code=403,
                detail="Open Cathedra from its desktop shortcut to finish first-time setup.",
            )

    def consume(self) -> None:
        self._digest = None
        # A cleanup failure cannot revive authority or turn a committed setup into an error.
        try:
            self.entry_path.unlink(missing_ok=True)
            self.directory.rmdir()
        except OSError:
            pass
