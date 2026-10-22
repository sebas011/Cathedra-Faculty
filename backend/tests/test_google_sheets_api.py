import json

import pytest
from sqlalchemy import func, select

import app.main as main
from app.models import ActivityEvent, FacultyWorkload, SavedProjection, WorkloadCostSettings
from app.services.google_sheets import (
    GoogleSheetsError,
    get_google_sheets_destination_service,
    get_google_sheets_service,
)
from app.services.sheets_exports import build_google_sheet_tables

PREFIX = "/api/v1/maintenance/google-sheets"
SHEET_ID = "synthetic-sheet-id-for-tests-only"


class FakeService:
    def __init__(self):
        self.tables = None
        self.expected = None
        self.fail = False
        self.tested = False
        self.configured = False

    def status(self):
        return {
            "configured": self.configured,
            "spreadsheet_id": SHEET_ID,
            "row_counts": [],
            "last_updated_at": None,
        }

    def configure(self, url, key):
        self.configured = True
        return self.status()

    def test_connection(self):
        self.tested = True
        return self.status()

    def update(self, tables, *, expected_spreadsheet_id=None):
        if self.fail:
            raise GoogleSheetsError(502, "Google Sheets is unavailable. No update was confirmed.")
        self.tables, self.expected = tables, expected_spreadsheet_id
        return {**self.status(), "last_result": "success"}

    def disconnect(self):
        self.configured = False
        return self.status()


@pytest.fixture
def sheets(client):
    fake = FakeService()
    main.app.dependency_overrides[get_google_sheets_service] = lambda: fake
    return fake


@pytest.fixture
def destinations(client):
    services = {name: FakeService() for name in ("workloads", "overload", "profiles")}

    def destination_service(destination: str):
        return services[destination]

    main.app.dependency_overrides[get_google_sheets_destination_service] = destination_service
    return services


def faculty_input(name):
    return {
        "name": name,
        "rank": "Instructor I",
        "employment_status": "Full-time",
        "salary_grade": "SG 12",
        "salary_step": 1,
        "college": "CIT",
        "department": "Information Technology",
        "monthly_salary": 30000,
    }


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("put", "", {"spreadsheet_url": SHEET_ID}),
        ("post", "/test", None),
        ("post", "/sync", {"spreadsheet_id": SHEET_ID}),
        ("delete", "", None),
        ("get", "/setup-guide", None),
    ],
)
def test_all_google_sheets_routes_require_admin(client, sheets, method, suffix, body):
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "sheet-staff", "password": "staff-password-123", "role": "staff"},
    )
    assert created.status_code == 201
    token = client.post(
        "/api/v1/auth/login", json={"username": "sheet-staff", "password": "staff-password-123"}
    ).json()["token"]
    response = client.request(
        method, PREFIX + suffix, headers={"Authorization": f"Bearer {token}"}, json=body
    )
    assert response.status_code == 403
    response = client.request(method, PREFIX + suffix, headers={"Authorization": ""}, json=body)
    assert response.status_code == 401
    assert not sheets.tested and sheets.tables is None and not sheets.configured


def test_configuration_and_test_do_not_export_records(client, sheets):
    assert (
        client.put(
            PREFIX,
            json={
                "spreadsheet_url": SHEET_ID,
                "service_account_json": "synthetic-key-not-retained-by-fake",
            },
        ).status_code
        == 200
    )
    assert client.post(PREFIX + "/test").status_code == 200
    assert sheets.tested and sheets.tables is None
    assert client.delete(PREFIX).status_code == 200
    assert not sheets.configured


def test_sync_requires_confirmed_destination_and_has_twelve_explicit_tables(client, sheets):
    assert client.post(PREFIX + "/sync").status_code == 422
    response = client.post(PREFIX + "/sync", json={"spreadsheet_id": SHEET_ID})
    assert response.status_code == 200
    assert sheets.expected == SHEET_ID
    assert len(sheets.tables) == 12
    assert all(table.title.startswith("Cathedra ") for table in sheets.tables)
    with main.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WorkloadCostSettings)) == 0


def test_sheet_snapshot_uses_saved_records_and_frozen_approvals_without_secrets(client, sheets):
    faculty = client.post(
        "/api/v1/faculty-profiles", json=faculty_input("Original Synthetic Faculty")
    ).json()
    workload = client.post(
        "/api/v1/workloads",
        json={
            "faculty_profile_id": faculty["id"],
            "academic_year": "2026-2027",
            "term": "First Semester",
            "remarks": '=HYPERLINK("example")',
            "assignments": [
                {
                    "course_code": "TEST101",
                    "course_title": "Synthetic course",
                    "year_section": "A",
                    "lecture_hours": 24,
                    "laboratory_hours": 0,
                }
            ],
        },
    ).json()
    reviewed = client.post(
        f"/api/v1/workloads/{workload['id']}/review",
        headers={"If-Match": str(workload["revision"])},
    )
    assert reviewed.status_code == 200
    approved = client.post(
        f"/api/v1/workloads/{workload['id']}/approve",
        headers={"If-Match": str(reviewed.json()["revision"])},
    )
    assert approved.status_code == 200
    changed = client.put(
        f"/api/v1/faculty-profiles/{faculty['id']}",
        json=faculty_input("Current Synthetic Faculty"),
        headers={"If-Match": str(faculty["revision"])},
    )
    assert changed.status_code == 200
    assert (
        client.put(
            "/api/v1/expenses/active-period",
            headers={"If-Match": "0"},
            json={"academic_year": "2026-2027", "term": "First Semester"},
        ).status_code
        == 200
    )
    assert client.post(PREFIX + "/sync", json={"spreadsheet_id": SHEET_ID}).status_code == 200
    tables = {table.title: table for table in sheets.tables}
    assert tables["Cathedra Faculty"].rows[0][1] == "Current Synthetic Faculty"
    assert tables["Cathedra Approved Workloads"].rows[0][1] == "Original Synthetic Faculty"
    assert tables["Cathedra Assignments"].rows[0][6] == "TEST101"
    assert tables["Cathedra Salary Projection"].rows
    assert tables["Cathedra Teaching Projection"].rows
    raw = json.dumps([{"headers": table.headers, "rows": table.rows} for table in sheets.tables])
    for forbidden in (
        "password_hash",
        "test-password-123",
        "token_hash",
        "private_key",
        "approval_snapshot",
        "import_provenance",
        "test-admin",
    ):
        assert forbidden not in raw
    assert "=HYPERLINK" in raw  # Transport must send this as a literal stringValue.
    with main.SessionLocal() as db:
        assert db.get(FacultyWorkload, workload["id"]).workflow_status == "Approved"


def test_failed_update_has_no_completed_activity(client, sheets):
    sheets.fail = True
    response = client.post(PREFIX + "/sync", json={"spreadsheet_id": SHEET_ID})
    assert response.status_code == 502
    with main.SessionLocal() as db:
        actions = db.scalars(select(ActivityEvent.action)).all()
    assert "Failed or unconfirmed Google Sheets update" in actions
    assert "Completed Google Sheets update" not in actions


def test_empty_export_is_read_only_and_marks_missing_period(client, sheets):
    with main.SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(ActivityEvent))
        tables = build_google_sheet_tables(db)
        assert db.get(WorkloadCostSettings, 1) is None
        assert db.scalar(select(func.count()).select_from(ActivityEvent)) == before
    assert any("No office period" in str(row) for row in tables[0].rows)


def test_key_size_error_does_not_echo_credential(client, sheets):
    response = client.put(
        PREFIX,
        json={"spreadsheet_url": SHEET_ID, "service_account_json": "credential-secret" * 5000},
    )
    assert response.status_code == 422
    assert "credential-secret" not in response.text


def test_setup_guide_download_is_generic(client, sheets):
    response = client.get(PREFIX + "/setup-guide")
    assert response.status_code == 200
    assert 'filename="cathedra-google-sheets-setup.md"' in response.headers["content-disposition"]
    assert "Update Google Sheet" in response.text
    assert "BEGIN PRIVATE KEY" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {
            "spreadsheet_url": SHEET_ID,
            "service_account_json": {"private_key": "SYNTHETIC-PRIVATE-MATERIAL"},
        },
        {"spreadsheet_url": SHEET_ID, "unexpected_key": "SYNTHETIC-PRIVATE-MATERIAL"},
        ["SYNTHETIC-PRIVATE-MATERIAL"],
    ],
)
def test_malformed_google_requests_never_echo_credential_input(client, sheets, payload):
    response = client.put(PREFIX, json=payload)
    assert response.status_code == 422
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in response.text
    assert "input" not in response.json()


def test_saved_estimate_summary_reads_frozen_values_without_exporting_raw_json(client, sheets):
    from app.services.projection import build_monthly_projection
    from app.services.snapshots import dump_projection

    client.get("/api/v1/workloads/cost-settings")
    with main.SessionLocal() as db:
        frozen = build_monthly_projection(db)
        saved = SavedProjection(
            academic_year="2026-2027",
            term=None,
            period="yearly",
            created_by="private-account-name",
            projection_json=dump_projection(frozen),
        )
        db.add(saved)
        db.commit()
        tables = {table.title: table for table in build_google_sheet_tables(db)}
    assert tables["Cathedra Saved Estimates"].rows[0][6] == frozen.combined_period_estimate
    assert "private-account-name" not in str(tables)


@pytest.mark.parametrize("destination", ["workloads", "overload", "profiles"])
def test_scoped_routes_require_administrator_for_every_operation(client, destinations, destination):
    assert (
        client.post(
            "/api/v1/auth/users",
            json={"username": "sheet-staff", "password": "staff-password-123", "role": "staff"},
        ).status_code
        == 201
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": "sheet-staff", "password": "staff-password-123"}
    ).json()["token"]
    for method, suffix, body in [
        ("get", "", None),
        ("put", "", {"spreadsheet_url": SHEET_ID}),
        ("delete", "", None),
        ("post", "/test", None),
        ("post", "/sync", {"spreadsheet_id": SHEET_ID}),
    ]:
        url = f"{PREFIX}/destinations/{destination}{suffix}"
        assert (
            client.request(
                method, url, json=body, headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 403
        )
        assert (
            client.request(method, url, json=body, headers={"Authorization": ""}).status_code == 401
        )
    assert all(
        not service.configured and service.tables is None for service in destinations.values()
    )


def test_scoped_configuration_test_and_disconnect_touch_only_selected_destination(
    client, destinations
):
    for destination in destinations:
        url = f"{PREFIX}/destinations/{destination}"
        assert client.get(url).status_code == 200
        assert (
            client.put(
                url, json={"spreadsheet_url": SHEET_ID, "service_account_json": "synthetic-key"}
            ).status_code
            == 200
        )
        assert client.post(url + "/test").status_code == 200
    assert client.delete(PREFIX + "/destinations/overload").status_code == 200
    assert destinations["workloads"].configured and destinations["profiles"].configured
    assert not destinations["overload"].configured
    assert all(service.tested and service.tables is None for service in destinations.values())


@pytest.mark.parametrize("destination", ["workloads", "overload", "profiles"])
def test_scoped_sync_uses_selected_dataset_and_confirmed_destination(
    client, destinations, monkeypatch, destination
):
    import app.api.google_sheets as api
    from app.services.google_sheets import SheetTable

    def snapshot(db, *, destination):
        assert db.connection().connection.driver_connection.in_transaction
        return [SheetTable("Cathedra Overview", ["Scope"], [[destination]])]

    monkeypatch.setattr(api, "build_google_sheet_tables", snapshot)
    url = f"{PREFIX}/destinations/{destination}/sync"
    assert client.post(url).status_code == 422
    assert client.post(url, json={"spreadsheet_id": SHEET_ID}).status_code == 200
    selected = destinations[destination]
    assert selected.expected == SHEET_ID
    assert selected.tables[0].rows == [[destination]]
    assert all(other.tables is None for name, other in destinations.items() if name != destination)
    label = {
        "workloads": "Faculty workload Google Sheets",
        "overload": "Overload projection Google Sheets",
        "profiles": "Faculty profile Google Sheets",
    }[destination]
    with main.SessionLocal() as db:
        actions = db.scalars(select(ActivityEvent.action)).all()
    assert f"Requested {label} update" in actions
    assert f"Completed {label} update" in actions
    assert "Completed Google Sheets update" not in actions


@pytest.mark.parametrize("method,suffix", [("get", ""), ("put", ""), ("post", "/sync")])
def test_invalid_scoped_destination_has_safe_validation_error(client, method, suffix):
    response = client.request(
        method,
        PREFIX + "/destinations/SYNTHETIC-PRIVATE-MATERIAL" + suffix,
        json={"service_account_json": {"private_key": "SYNTHETIC-PRIVATE-MATERIAL"}},
    )
    assert response.status_code == 422
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in response.text


def test_scoped_malformed_key_never_echoes_input(client, destinations):
    response = client.put(
        PREFIX + "/destinations/profiles",
        json={
            "spreadsheet_url": SHEET_ID,
            "service_account_json": {"private_key": "SYNTHETIC-PRIVATE-MATERIAL"},
        },
    )
    assert response.status_code == 422
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in response.text


def test_scoped_failed_update_records_only_selected_category_failure(client, destinations):
    destinations["overload"].fail = True
    response = client.post(
        PREFIX + "/destinations/overload/sync", json={"spreadsheet_id": SHEET_ID}
    )
    assert response.status_code == 502
    with main.SessionLocal() as db:
        actions = db.scalars(select(ActivityEvent.action)).all()
    assert "Failed or unconfirmed Overload projection Google Sheets update" in actions
    assert "Completed Overload projection Google Sheets update" not in actions
