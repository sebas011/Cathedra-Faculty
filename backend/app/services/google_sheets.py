"""Explicit, one-way exports to app-owned Google Sheets tabs.

Credentials live beside the selected database, never inside it. The integration
uses a fixed OAuth endpoint and a single atomic Sheets batch for each export.
"""

from __future__ import annotations

import base64
import ctypes
import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account
from urllib3.util import Timeout

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_ROOT = "https://sheets.googleapis.com/v4/spreadsheets/"
OWNER_KEY = "cathedra_faculty_export"
OWNER_VALUE = "v1"
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
OPERATION_TIMEOUT_SECONDS = 45
METADATA_FIELDS = (
    "spreadsheetId,properties(title),"
    "sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)),"
    "developerMetadata(metadataKey,metadataValue,location))"
)
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,200}\Z")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com\Z")
GoogleSheetsDestination = Literal["workloads", "overload", "profiles"]
DESTINATIONS = ("workloads", "overload", "profiles")
_configuration_locks: dict[Path, threading.RLock] = {}
_configuration_locks_guard = threading.Lock()


def _configuration_lock(directory: Path):
    with _configuration_locks_guard:
        return _configuration_locks.setdefault(directory, threading.RLock())


@dataclass
class SheetTable:
    title: str
    headers: list[str]
    rows: list[list[object]]


class GoogleSheetsError(Exception):
    """A user-safe error. Never wrap Google response bodies or key material."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class _UncertainWriteError(GoogleSheetsError):
    def __init__(self):
        super().__init__(
            504,
            "Google may have completed this update before the connection was interrupted. Check the Cathedra Overview tab before retrying.",
        )


def _spreadsheet_id(value: str) -> str:
    if not isinstance(value, str):
        raise GoogleSheetsError(422, "Enter a Google Sheets link or spreadsheet ID.")
    value = value.strip()
    if _ID_PATTERN.fullmatch(value):
        return value
    try:
        parsed = urlsplit(value)
        match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{20,200})(?:/edit)?/?", parsed.path)
        if parsed.scheme == "https" and parsed.netloc == "docs.google.com" and match:
            return match.group(1)
    except ValueError:
        pass
    raise GoogleSheetsError(
        422, "Use an HTTPS docs.google.com/spreadsheets/d/ link or its spreadsheet ID."
    )


def _credential_info(raw: str) -> tuple[dict, service_account.Credentials]:
    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 64 * 1024:
            raise ValueError
        info = json.loads(raw)
        if (
            not isinstance(info, dict)
            or info.get("type") != "service_account"
            or not isinstance(info.get("client_email"), str)
            or not _EMAIL_PATTERN.fullmatch(info["client_email"])
            or info.get("token_uri") != TOKEN_URL
            or info.get("universe_domain", "googleapis.com") != "googleapis.com"
            or not isinstance(info.get("private_key"), str)
        ):
            raise ValueError
        # Discard project metadata, delegation fields, and all dynamic endpoints.
        clean = {
            "type": "service_account",
            "client_email": info["client_email"],
            "private_key": info["private_key"],
            "token_uri": TOKEN_URL,
            "universe_domain": "googleapis.com",
        }
        if info.get("private_key_id"):
            if not isinstance(info["private_key_id"], str) or len(info["private_key_id"]) > 200:
                raise ValueError
            clean["private_key_id"] = info["private_key_id"]
        private_key = serialization.load_pem_private_key(
            clean["private_key"].encode("utf-8"), password=None
        )
        if not isinstance(private_key, RSAPrivateKey):
            raise ValueError
        credentials = service_account.Credentials.from_service_account_info(
            clean, scopes=[SHEETS_SCOPE], always_use_jwt_access=False
        )
        return clean, credentials
    except (ValueError, TypeError, KeyError, RecursionError, UnsupportedAlgorithm, GoogleAuthError):
        raise GoogleSheetsError(
            422,
            "Use a valid Google service-account JSON key with its standard Google OAuth token endpoint.",
        ) from None


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    """Protect Windows keys for the signed-in OS account; forbid UI prompts."""

    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        result = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        result = function(
            ctypes.byref(source),
            "Cathedra Google Sheets",
            None,
            None,
            None,
            1,
            ctypes.byref(output),
        )
    function.restype = wintypes.BOOL
    if not result:
        raise OSError("Credential protection is unavailable")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _pack_credentials(info: dict) -> dict:
    data = json.dumps(info, allow_nan=False).encode("utf-8")
    if os.name == "nt":
        return {
            "protection": "windows-dpapi",
            "data": base64.b64encode(_dpapi(data, decrypt=False)).decode("ascii"),
        }
    return {"protection": "private-file", "data": info}


def _unpack_credentials(envelope: dict) -> str:
    if envelope.get("protection") == "windows-dpapi" and os.name == "nt":
        return _dpapi(base64.b64decode(envelope["data"], validate=True), decrypt=True).decode(
            "utf-8"
        )
    if envelope.get("protection") == "private-file" and os.name != "nt":
        return json.dumps(envelope["data"], allow_nan=False)
    raise ValueError("Credential storage is incompatible")


class _OAuthResponse:
    def __init__(self, response: requests.Response):
        self.status = response.status_code
        self.data = response.content
        self.headers = response.headers


class _Transport:
    def __init__(self):
        self.deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        self.session = requests.Session()
        self.session.trust_env = False
        self.oauth_attempted = False

    def close(self) -> None:
        self.session.close()

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout()
        # No redirects and no retries: a redirected key/token must never leave
        # Google's fixed endpoints; a timed-out write must never be repeated.
        return self.session.request(
            method,
            url,
            timeout=Timeout(
                total=min(12, remaining), connect=min(4, remaining), read=min(8, remaining)
            ),
            allow_redirects=False,
            **kwargs,
        )

    def oauth_request(self, url, method="GET", body=None, headers=None, **kwargs):
        if url != TOKEN_URL or method != "POST" or self.oauth_attempted:
            raise GoogleSheetsError(
                502, "Google sign-in failed. Check the service-account key and try again."
            )
        self.oauth_attempted = True
        return _OAuthResponse(self.request(method, TOKEN_URL, data=body, headers=headers))

    def json_request(self, method: str, spreadsheet_id: str, token: str, *, payload=None):
        # spreadsheet_id is validated locally before it can reach this method.
        url = SHEETS_ROOT + spreadsheet_id
        if method == "POST":
            url += ":batchUpdate"
        kwargs = {"headers": {"Authorization": "Bearer " + token}}
        if payload is not None:
            kwargs["data"] = payload
            kwargs["headers"]["Content-Type"] = "application/json; charset=utf-8"
        else:
            kwargs["params"] = {"fields": METADATA_FIELDS, "includeGridData": "false"}
        response = self.request(method, url, **kwargs)
        if method == "POST" and (response.status_code >= 500 or response.status_code == 408):
            raise _UncertainWriteError()
        if response.status_code in (401, 403):
            raise GoogleSheetsError(
                403,
                "Google denied access. Share this spreadsheet with the service-account email as Editor and enable the Google Sheets API.",
            )
        if response.status_code == 404:
            raise GoogleSheetsError(
                404,
                "Google could not find this spreadsheet. Check the link and sharing permissions.",
            )
        if response.status_code == 429:
            raise GoogleSheetsError(
                429, "Google Sheets is busy or its request limit was reached. Try again later."
            )
        if not 200 <= response.status_code < 300:
            raise GoogleSheetsError(
                502,
                "Google Sheets rejected the request. Check access and protected tabs, then try again.",
            )
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TypeError):
            if method == "POST":
                raise _UncertainWriteError() from None
            raise GoogleSheetsError(
                502, "Google Sheets returned an unreadable response. Try again later."
            ) from None


def _empty_state() -> dict:
    return {
        "configured": False,
        "ready": False,
        "spreadsheet_id": None,
        "spreadsheet_url": None,
        "spreadsheet_title": None,
        "service_account_email": None,
        "last_updated_at": None,
        "last_result": None,
        "last_message": None,
        "row_counts": [],
    }


def _cell(value: object) -> dict:
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"userEnteredValue": {"boolValue": value}}
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise GoogleSheetsError(422, "The export contains a number Google Sheets cannot store.")
        return {"userEnteredValue": {"numberValue": value}}
    if isinstance(value, str):
        if len(value) > 50000:
            raise GoogleSheetsError(
                422, "An export cell exceeds Google Sheets' 50,000-character limit."
            )
        return {"userEnteredValue": {"stringValue": value}}
    raise GoogleSheetsError(422, "The export contains an unsupported cell value.")


def _owned(sheet: dict) -> bool:
    sheet_id = sheet.get("properties", {}).get("sheetId")
    return any(
        isinstance(marker, dict)
        and marker.get("metadataKey") == OWNER_KEY
        and marker.get("metadataValue") == OWNER_VALUE
        and marker.get("location", {}).get("sheetId") == sheet_id
        for marker in sheet.get("developerMetadata", [])
    )


def _batch(tables: list[SheetTable], metadata: dict) -> tuple[bytes, list[dict]]:
    requests_list = []
    counts = []
    sheets = metadata.get("sheets", [])
    by_title = {sheet["properties"]["title"]: sheet for sheet in sheets}
    used_ids = {sheet["properties"]["sheetId"] for sheet in sheets}
    seen_titles = set()
    next_id = max(used_ids, default=-1) + 1
    if not tables:
        raise GoogleSheetsError(422, "There are no export tables to update.")
    for table in tables:
        if (
            not isinstance(table, SheetTable)
            or not table.title.startswith("Cathedra ")
            or len(table.title) > 100
            or re.search(r"[:\\/?*\[\]]", table.title)
            or table.title in seen_titles
            or not table.headers
            or any(not isinstance(header, str) for header in table.headers)
        ):
            raise GoogleSheetsError(
                422, "The export contains an invalid or duplicate Cathedra tab."
            )
        seen_titles.add(table.title)
        width = len(table.headers)
        if width > 18278 or len(table.rows) + 1 > 10000000:
            raise GoogleSheetsError(422, "This export exceeds Google Sheets' size limits.")
        for row in table.rows:
            if len(row) > width:
                raise GoogleSheetsError(
                    422, "An export row contains more values than its table headers."
                )
        sheet = by_title.get(table.title)
        height = len(table.rows) + 1
        if sheet is None:
            while next_id in used_ids:
                next_id += 1
            sheet_id = next_id
            next_id += 1
            used_ids.add(sheet_id)
            requests_list.extend(
                [
                    {
                        "addSheet": {
                            "properties": {
                                "sheetId": sheet_id,
                                "title": table.title,
                                "gridProperties": {
                                    "rowCount": max(height, 1),
                                    "columnCount": width,
                                },
                            }
                        }
                    },
                    {
                        "createDeveloperMetadata": {
                            "developerMetadata": {
                                "metadataKey": OWNER_KEY,
                                "metadataValue": OWNER_VALUE,
                                "location": {"sheetId": sheet_id},
                                "visibility": "DOCUMENT",
                            }
                        }
                    },
                ]
            )
            clear_height, clear_width = height, width
        else:
            if not _owned(sheet):
                raise GoogleSheetsError(
                    409,
                    f'The tab "{table.title}" is not owned by Cathedra. Rename it in Google Sheets before updating.',
                )
            properties = sheet["properties"]
            sheet_id = properties["sheetId"]
            grid = properties.get("gridProperties", {})
            clear_height = max(height, grid.get("rowCount", 1))
            clear_width = max(width, grid.get("columnCount", 1))
            if clear_height != grid.get("rowCount") or clear_width != grid.get("columnCount"):
                requests_list.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {
                                    "rowCount": clear_height,
                                    "columnCount": clear_width,
                                },
                            },
                            "fields": "gridProperties.rowCount,gridProperties.columnCount",
                        }
                    }
                )
        if clear_height * clear_width > 10000000:
            raise GoogleSheetsError(422, "This export exceeds Google Sheets' size limits.")
        # An explicit range clears every old value in the owned grid, including
        # surplus trailing rows/columns. Rows below supply the replacement data.
        requests_list.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": clear_height,
                        "startColumnIndex": 0,
                        "endColumnIndex": clear_width,
                    },
                    "rows": [
                        {"values": [_cell(value) for value in row]}
                        for row in [table.headers, *table.rows]
                    ],
                    "fields": "userEnteredValue",
                }
            }
        )
        counts.append({"title": table.title, "rows": len(table.rows)})
    payload = json.dumps(
        {"requests": requests_list, "includeSpreadsheetInResponse": False},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise GoogleSheetsError(
            413, "This export is larger than the 10 MB update limit. Reduce the data and try again."
        )
    return payload, counts


class GoogleSheetsService:
    def __init__(self, data_directory: Path, *, destination: GoogleSheetsDestination | None = None):
        if destination is not None and destination not in DESTINATIONS:
            raise GoogleSheetsError(422, "Choose a valid Google Sheets destination.")
        self._directory = Path(data_directory).resolve() / ".google-sheets"
        self._destination = destination
        filename = f"connection-{destination}.json" if destination else "connection.json"
        self._path = self._directory / filename
        self._configuration_lock = _configuration_lock(self._directory)
        self._lock = threading.RLock()
        self._state = _empty_state()
        self._load_error: str | None = None
        self._info: dict | None = None
        self._credentials: service_account.Credentials | None = None
        self._load()

    def _load(self) -> None:
        if self._directory.is_symlink() or self._path.is_symlink():
            self._state["configured"] = self._path.is_symlink() or self._path.exists()
            self._load_error = "Google Sheets settings use an unsupported storage location. Disconnect the local settings before reconnecting."
            return
        if not self._path.exists():
            return
        # A saved connection still needs a recovery control when its key or
        # JSON cannot be opened. Never present it as ready or expose its data.
        self._state["configured"] = True
        try:
            if self._path.stat().st_size > 128 * 1024:
                raise ValueError
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            if saved.get("version") != 1:
                raise ValueError
            spreadsheet_id = _spreadsheet_id(saved["state"]["spreadsheet_id"])
            info, credentials = _credential_info(_unpack_credentials(saved["credentials"]))
            state = _empty_state()
            state.update({key: saved["state"].get(key) for key in state})
            state.update(
                configured=True,
                ready=True,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                service_account_email=info["client_email"],
            )
            if state["last_result"] not in (None, "success", "error", "uncertain"):
                raise ValueError
            if not isinstance(state["row_counts"], list) or any(
                not isinstance(item, dict)
                or not isinstance(item.get("title"), str)
                or type(item.get("rows")) is not int
                or item["rows"] < 0
                for item in state["row_counts"]
            ):
                raise ValueError
            if any(
                state[key] is not None and not isinstance(state[key], str)
                for key in ("spreadsheet_title", "last_updated_at", "last_message")
            ):
                raise ValueError
            self._state, self._info, self._credentials = state, info, credentials
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
            GoogleSheetsError,
        ):
            # A copied DPAPI envelope belongs to the original Windows account.
            # Keep reconnect/disconnect available instead of trapping every API
            # action behind an unreadable configuration dependency.
            self._load_error = "Saved Google Sheets settings could not be opened. Reconnect with the original service-account JSON key."

    def _save(self, state: dict, info: dict) -> None:
        temporary = None
        try:
            if self._directory.is_symlink() or self._path.is_symlink():
                raise OSError
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._directory.chmod(0o700)
            saved = {"version": 1, "state": state, "credentials": _pack_credentials(info)}
            descriptor, temporary = tempfile.mkstemp(
                prefix="connection-", suffix=".tmp", dir=self._directory
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(saved, handle, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            temporary = None
        except (OSError, ValueError, TypeError):
            raise GoogleSheetsError(
                500,
                "Google Sheets settings could not be saved privately. Check this app's local data folder permissions.",
            ) from None
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def status(self) -> dict:
        with self._lock:
            result = {
                **self._state,
                "row_counts": [dict(item) for item in self._state["row_counts"]],
            }
            if self._load_error:
                result["message"] = self._load_error
            return result

    def configure(self, spreadsheet_url: str, service_account_json: str | None) -> dict:
        # Every destination (including the original combined connection) uses
        # the same lock. The duplicate check and atomic save are one operation.
        with self._configuration_lock, self._lock:
            spreadsheet_id = _spreadsheet_id(spreadsheet_url)
            if service_account_json is not None:
                info, credentials = _credential_info(service_account_json)
            elif self._info is not None:
                info, credentials = self._info, self._credentials
            else:
                raise GoogleSheetsError(422, "Choose a Google service-account JSON key to connect.")
            self._require_distinct_destination(spreadsheet_id)
            state = (
                dict(self._state)
                if spreadsheet_id == self._state["spreadsheet_id"]
                else _empty_state()
            )
            state.update(
                configured=True,
                ready=True,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
                service_account_email=info["client_email"],
            )
            self._save(state, info)
            self._state, self._info, self._credentials = state, info, credentials
            self._load_error = None
            return {
                **self.status(),
                "message": "Connection saved locally. Test the connection before updating Google Sheets.",
            }

    def _require_distinct_destination(self, spreadsheet_id: str) -> None:
        for destination in (None, *DESTINATIONS):
            filename = f"connection-{destination}.json" if destination else "connection.json"
            path = self._directory / filename
            if path == self._path:
                continue
            try:
                if self._directory.is_symlink() or path.is_symlink():
                    raise ValueError
                if not path.exists():
                    continue
                if path.stat().st_size > 128 * 1024:
                    raise ValueError
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("version") != 1:
                    raise ValueError
                other_id = _spreadsheet_id(saved["state"]["spreadsheet_id"])
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                RecursionError,
                GoogleSheetsError,
            ):
                raise GoogleSheetsError(
                    409,
                    "Another Google Sheets connection could not be checked. Disconnect its local settings before saving this connection.",
                ) from None
            if other_id == spreadsheet_id:
                raise GoogleSheetsError(
                    409,
                    "Use a different spreadsheet for each destination. This spreadsheet is already connected to another destination or the previous combined export.",
                )

    def _require_configured(self) -> None:
        if not self._credentials or not self._state["spreadsheet_id"]:
            raise GoogleSheetsError(
                409, "Connect a Google spreadsheet and service-account key first."
            )

    def _make_transport(self) -> _Transport:
        return _Transport()

    def _token(self, transport: _Transport) -> str:
        try:
            if not self._credentials.valid:
                self._credentials.refresh(transport.oauth_request)
            if not isinstance(self._credentials.token, str) or not self._credentials.token:
                raise ValueError
            return self._credentials.token
        except (GoogleAuthError, ValueError, TypeError):
            raise GoogleSheetsError(
                403,
                "Google sign-in failed. Check the service-account key and whether it is still active.",
            ) from None

    def test_connection(self) -> dict:
        with self._lock:
            self._require_configured()
            transport = self._make_transport()
            try:
                metadata = transport.json_request(
                    "GET", self._state["spreadsheet_id"], self._token(transport)
                )
                state = {
                    **self._state,
                    "spreadsheet_title": metadata.get("properties", {}).get("title"),
                }
                self._save(state, self._info)
                self._state = state
                return {
                    **self.status(),
                    "message": "Spreadsheet metadata is accessible. This checks read access only; the next update will check write access.",
                }
            except requests.RequestException:
                raise GoogleSheetsError(
                    502,
                    "The connection check could not reach Google. Check your internet connection and try again.",
                ) from None
            finally:
                transport.close()

    def disconnect(self) -> dict:
        with self._configuration_lock, self._lock:
            try:
                if self._directory.is_symlink():
                    raise GoogleSheetsError(
                        409,
                        "The Google Sheets settings folder is a symbolic link. Remove that link from the app's local data folder before reconnecting.",
                    )
                self._path.unlink(missing_ok=True)
            except OSError:
                raise GoogleSheetsError(
                    500,
                    "The local Google Sheets connection could not be removed. Check local folder permissions.",
                ) from None
            self._state, self._info, self._credentials = _empty_state(), None, None
            self._load_error = None
            return {
                **self.status(),
                "message": "Disconnected. Existing Google Sheets tabs remain available.",
            }

    def update(
        self, tables: list[SheetTable], *, expected_spreadsheet_id: str | None = None
    ) -> dict:
        with self._lock:
            self._require_configured()
            if (
                expected_spreadsheet_id is not None
                and expected_spreadsheet_id != self._state["spreadsheet_id"]
            ):
                raise GoogleSheetsError(
                    409,
                    "The connected spreadsheet changed while the export was prepared. Review the connection and update again.",
                )
            transport = self._make_transport()
            sent = False
            try:
                token = self._token(transport)
                metadata = transport.json_request("GET", self._state["spreadsheet_id"], token)
                payload, counts = _batch(tables, metadata)
                sent = True
                transport.json_request(
                    "POST", self._state["spreadsheet_id"], token, payload=payload
                )
                state = {
                    **self._state,
                    "spreadsheet_title": metadata.get("properties", {}).get("title"),
                    "last_updated_at": datetime.now(UTC).isoformat(),
                    "last_result": "success",
                    "last_message": "Google Sheets updated successfully.",
                    "row_counts": counts,
                }
                # Keep the confirmed remote outcome in memory even if local
                # storage fails after Google's atomic batch has completed.
                self._state = state
                try:
                    self._save(state, self._info)
                except GoogleSheetsError:
                    return {
                        **self.status(),
                        "message": "Google Sheets updated successfully, but the local update history could not be saved. Check local folder permissions.",
                    }
                return {**self.status(), "message": state["last_message"]}
            except requests.RequestException:
                message = (
                    "Google may have completed this update before the connection was interrupted. Check the Cathedra Overview tab before retrying."
                    if sent
                    else "Google could not be reached. Check your internet connection and try again."
                )
                self._record_failure("uncertain" if sent else "error", message)
                raise GoogleSheetsError(504 if sent else 502, message) from None
            except _UncertainWriteError as error:
                self._record_failure("uncertain", error.message)
                raise
            except GoogleSheetsError as error:
                self._record_failure("error", error.message)
                raise
            except (KeyError, TypeError, ValueError, OverflowError):
                message = "Google Sheets returned incompatible metadata or the export contains unsupported data."
                self._record_failure("uncertain" if sent else "error", message)
                raise GoogleSheetsError(502, message) from None
            finally:
                transport.close()

    def _record_failure(self, result: str, message: str) -> None:
        self._state = {**self._state, "last_result": result, "last_message": message}
        try:
            self._save(self._state, self._info)
        except GoogleSheetsError:
            pass


_services: dict[tuple[Path, GoogleSheetsDestination | None], GoogleSheetsService] = {}
_services_lock = threading.Lock()


def get_google_sheets_service() -> GoogleSheetsService:
    return _get_service(None)


def get_google_sheets_destination_service(
    destination: GoogleSheetsDestination,
) -> GoogleSheetsService:
    return _get_service(destination)


def _get_service(destination: GoogleSheetsDestination | None) -> GoogleSheetsService:
    from app.db import DB_PATH

    directory = DB_PATH.parent.resolve()
    key = (directory, destination)
    with _services_lock:
        if key not in _services:
            _services[key] = GoogleSheetsService(directory, destination=destination)
        return _services[key]
