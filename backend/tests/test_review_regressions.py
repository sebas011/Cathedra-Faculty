import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date
from threading import Barrier, Event, current_thread
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

import app.api.auth as auth_api
import app.api.workload as workload_api
from app.bootstrap import SetupCapability
from app.db import Base
from app.models import ActivityEvent, LocalSession, LocalUser, WorkloadCostSettings
from app.workload_read import get_workload_cost_settings_record


def test_concurrent_default_cost_settings_initialization(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'settings.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    both_read_empty = Barrier(2)

    class BootstrapSession(Session):
        def get(self, entity, ident, **kwargs):
            record = super().get(entity, ident, **kwargs)
            if entity is WorkloadCostSettings and record is None:
                both_read_empty.wait(timeout=10)
            return record

    sessions = sessionmaker(bind=engine, class_=BootstrapSession, expire_on_commit=False)

    def initialize():
        with sessions() as db:
            db.info["audit_actor"] = (1, "settings-review-admin")
            settings = get_workload_cost_settings_record(db)
            return settings.id, settings.first_semester_weeks

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: initialize(), range(2)))
        assert results == [(1, 18), (1, 18)]
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(WorkloadCostSettings)) == 1
            assert db.scalar(select(func.count()).select_from(ActivityEvent)) == 1
    finally:
        engine.dispose()


def test_concurrent_first_admin_setup_has_only_one_winner(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    capability = SetupCapability(tmp_path, "http://127.0.0.1:8102")
    key = re.search(r"#setup-key=([A-Za-z0-9_-]{43})", capability.entry_path.read_text()).group(1)
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(setup_capability=capability)),
            "headers": [(b"x-cathedra-setup-key", key.encode())],
        }
    )
    first_hash_started = Event()
    release_first_hash = Event()
    second_sql_started = Event()
    stored_hash = auth_api.password_hash("bootstrap-password-123")

    def controlled_hash(password):
        if password == "first-password-123":
            first_hash_started.set()
            assert release_first_hash.wait(10)
        return stored_hash

    @event.listens_for(engine, "before_cursor_execute")
    def observe_second_request(connection, cursor, statement, parameters, context, many):
        if current_thread().name == "second-bootstrap":
            second_sql_started.set()

    def setup(username, password):
        if username == "second-admin":
            current_thread().name = "second-bootstrap"
        with sessions() as db:
            try:
                return 201, auth_api.setup_first_admin(
                    auth_api.Credentials(username=username, password=password),
                    request,
                    db,
                )
            except HTTPException as error:
                return error.status_code, None

    monkeypatch.setattr(auth_api, "password_hash", controlled_hash)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(setup, "first-admin", "first-password-123")
            try:
                assert first_hash_started.wait(5)
                second = pool.submit(setup, "second-admin", "second-password-123")
                assert second_sql_started.wait(5)
                # The second request must wait for the first bootstrap write.
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.5)
            finally:
                release_first_hash.set()
            assert first.result(timeout=5)[0] == 201
            assert second.result(timeout=5) == (409, None)
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(LocalUser)) == 1
            assert db.scalar(select(LocalUser.username)) == "first-admin"
            assert db.scalar(select(func.count()).select_from(LocalSession)) == 1
            # A rejected attempt releases the write lock and can reuse its session.
            for _ in range(2):
                with pytest.raises(HTTPException) as error:
                    auth_api.setup_first_admin(
                        auth_api.Credentials(username="third-admin", password="third-password-123"),
                        request,
                        db,
                    )
                assert error.value.status_code == 409
    finally:
        engine.dispose()


def create_profile_and_workload(client, category="Regular Faculty"):
    profile_response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Review Regression Faculty",
            "rank": "Instructor I",
            "employment_status": "Part-time" if category == "External Part-time" else "Full-time",
            "college": "CAS",
            "department": "General",
        },
    )
    assert profile_response.status_code == 201
    profile = profile_response.json()
    payload = {
        "faculty_profile_id": profile["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "compensation_category": category,
        "assignments": [
            {
                "course_code": "REG101",
                "course_title": "Regression Course",
                "year_section": "1A",
                "lecture_hours": 6,
                "laboratory_hours": 0,
            }
        ],
    }
    workload_response = client.post("/api/v1/workloads", json=payload)
    assert workload_response.status_code == 201
    return profile, payload, workload_response.json()


@pytest.mark.parametrize(
    "new_scope",
    [
        {"term": "Second Semester"},
        {"academic_year": "2028-2029"},
    ],
)
def test_same_faculty_period_edit_rechecks_retirement(client, monkeypatch, new_scope):
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 3)

    monkeypatch.setattr(workload_api, "date", ReviewDate)
    profile, payload, workload = create_profile_and_workload(client)
    retired = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": "2027-01-01",
        },
        headers={"If-Match": str(profile["revision"])},
    )
    assert retired.status_code == 200
    endpoint = f"/api/v1/workloads/{workload['id']}"
    rejected = client.put(
        endpoint, json={**payload, **new_scope}, headers={"If-Match": str(workload["revision"])}
    )
    assert rejected.status_code == 409
    unchanged = client.get(endpoint).json()
    assert unchanged["academic_year"] == payload["academic_year"]
    assert unchanged["term"] == payload["term"]
    assert unchanged["revision"] == workload["revision"]


def test_retired_faculty_historical_correction_keeps_original_scope(client):
    profile, payload, workload = create_profile_and_workload(client)
    retired = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        json={
            **profile,
            "service_status": "Retired",
            "service_status_effective_date": "2026-09-01",
        },
        headers={"If-Match": str(profile["revision"])},
    )
    assert retired.status_code == 200
    response = client.put(
        f"/api/v1/workloads/{workload['id']}",
        json={
            **payload,
            "term": "1st Semester",
            "remarks": "Corrected historical remarks",
        },
        headers={"If-Match": str(workload["revision"])},
    )
    assert response.status_code == 200
    assert response.json()["term"] == "First Semester"
    assert response.json()["remarks"] == "Corrected historical remarks"


@pytest.mark.parametrize("category", ["Internal Part-time", "External Part-time"])
def test_valid_part_time_approval_is_not_a_historical_allocation_issue(client, category):
    _, _, workload = create_profile_and_workload(client, category)
    endpoint = f"/api/v1/workloads/{workload['id']}"
    reviewed = client.post(f"{endpoint}/review", headers={"If-Match": str(workload["revision"])})
    assert reviewed.status_code == 200
    approved = client.post(
        f"{endpoint}/approve", headers={"If-Match": str(reviewed.json()["revision"])}
    )
    assert approved.status_code == 200
    snapshot = approved.json()["approval_snapshot"]
    assert snapshot["workload"]["total_weekly_hours"] == 6
    assert snapshot["workload"]["overload_weekly_hours"] == 0
    assert snapshot["teaching_allocation"]["allocations"][0]["paid_hours"] == 6
    review = client.get("/api/v1/workloads/historical-allocation-review")
    assert review.status_code == 200
    assert review.json() == {"count": 0, "items": []}


@pytest.mark.parametrize("filters", [{}, {"college": "CAS"}, {"employment_status": "Full-time"}])
def test_confirmed_no_teaching_has_known_zero_pay(client, filters):
    response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Confirmed No Teaching",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "General",
        },
    )
    assert response.status_code == 201
    profile = response.json()
    period = {"academic_year": "2026-2027", "term": "First Semester"}
    endpoint = f"/api/v1/expenses/no-teaching-confirmations/{profile['id']}"
    assert client.put(endpoint, json=period).status_code == 200
    projection = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            **period,
            "period": "semester",
            **filters,
        },
    ).json()
    record = projection["records"][0]
    assert record["teaching_status"] == "Confirmed not teaching this semester"
    assert record["period_overload_pay"] == 0
    assert record["period_part_time_pay"] == 0
    assert not any("not yet established" in warning for warning in projection["warnings"])
    if not filters:
        assert projection["overload_coverage"]["provisional"] is False
    assert client.delete(endpoint, params=period).status_code == 204
    unconfirmed = client.get(
        "/api/v1/expenses/monthly-projection",
        params={
            **period,
            "period": "semester",
            **filters,
        },
    ).json()["records"][0]
    assert unconfirmed["period_overload_pay"] is None


@pytest.mark.parametrize("service_status", ["Inactive", "Retired", "Resigned"])
def test_existing_inactive_effective_date_cannot_be_cleared(client, service_status):
    response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Dated Status",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "General",
            "service_status": service_status,
            "service_status_effective_date": "2026-09-01",
        },
    )
    assert response.status_code == 201
    profile = response.json()
    endpoint = f"/api/v1/faculty-profiles/{profile['id']}"
    rejected = client.put(
        endpoint,
        json={**profile, "service_status_effective_date": None},
        headers={"If-Match": str(profile["revision"])},
    )
    assert rejected.status_code == 422
    retained = client.get(endpoint).json()
    assert retained["service_status_effective_date"] == "2026-09-01"
    assert retained["revision"] == profile["revision"]
