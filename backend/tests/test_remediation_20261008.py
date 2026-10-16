import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

import app.main as main
from app.models import ActivityEvent, FacultyWorkload, WorkloadCostSettings


def test_concurrent_disable_preserves_one_active_administrator(tmp_path):
    from fastapi import HTTPException
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.api.auth import AccountStatusUpdate, set_account_status
    from app.db import Base
    from app.models import LocalUser

    engine = create_engine("sqlite:///" + (tmp_path / "accounts.db").as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                LocalUser(
                    id=i, username=f"admin{i}", password_hash="Synthetic fixture", role="admin"
                )
                for i in (1, 2)
            ]
        )
        db.commit()
    barrier = Barrier(2)

    def disable(user_id):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                set_account_status(user_id, AccountStatusUpdate(active=False), db, None)
                return 200
            except HTTPException as caught:
                return caught.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(disable, (1, 2))) == [200, 409]
    with Session(engine) as db:
        assert len(db.scalars(select(LocalUser).where(LocalUser.is_active.is_(True))).all()) == 1
    engine.dispose()


def test_integrity_check_and_identity_validation(client):
    result = client.post("/api/v1/maintenance/integrity-check")
    assert (
        result.status_code == 200
        and result.json()["status"] == "verified"
        and result.json()["checked_at"]
    )
    assert (
        client.post(
            "/api/v1/auth/users",
            json={"username": "   ", "password": "Synthetic-password-123", "role": "staff"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/faculty-profiles",
            json={
                "name": " ",
                "rank": "Instructor I",
                "employment_status": "Full-time",
                "college": "CAS",
                "department": "Math",
            },
        ).status_code
        == 422
    )


def test_staff_cannot_export_history_or_check_integrity(client):
    account = {"username": "audit-staff", "password": "Synthetic-password-123", "role": "staff"}
    assert client.post("/api/v1/auth/users", json=account).status_code == 201
    session = client.post("/api/v1/auth/login", json=account).json()
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    assert client.get("/api/v1/activity/page").status_code == 403
    assert client.get("/api/v1/activity/export.csv").status_code == 403
    assert client.post("/api/v1/maintenance/integrity-check").status_code == 403


def faculty(client, name="Remediation Faculty"):
    response = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": name,
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "Mathematics",
        },
    )
    assert response.status_code == 201
    return response.json()


def payload(profile, **overrides):
    return {
        "faculty_profile_id": profile["id"],
        "academic_year": "2026-2027",
        "term": "First Semester",
        "assignments": [
            {
                "course_code": "MATH101",
                "course_title": "Mathematics",
                "year_section": "A",
                "lecture_hours": 24,
            }
        ],
        **overrides,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"academic_year": "invalid"},
        {"academic_year": "2026-2028"},
        {"term": "Unknown"},
        {
            "assignments": [
                {
                    "course_code": " ",
                    "course_title": "Valid",
                    "year_section": "A",
                    "lecture_hours": 3,
                }
            ]
        },
        {
            "assignments": [
                {
                    "course_code": "MATH",
                    "course_title": " ",
                    "year_section": "A",
                    "lecture_hours": 3,
                }
            ]
        },
        {
            "assignments": [
                {
                    "course_code": "MATH",
                    "course_title": "Valid",
                    "year_section": " ",
                    "lecture_hours": 3,
                }
            ]
        },
    ],
)
def test_invalid_workload_never_persists(client, changes):
    profile = faculty(client)
    assert client.post("/api/v1/workloads", json=payload(profile, **changes)).status_code == 422
    assert client.get("/api/v1/workloads").json() == []


def test_normalizes_valid_workload_and_blocks_invalid_legacy_review(client):
    profile = faculty(client)
    record = client.post(
        "/api/v1/workloads",
        json=payload(profile, academic_year=" 2026-2027 ", term=" 1st Semester "),
    ).json()
    assert record["academic_year"] == "2026-2027" and record["term"] == "First Semester"
    with main.SessionLocal() as db:
        db.get(FacultyWorkload, record["id"]).assignments[0].course_title = " "
        db.commit()
    assert (
        client.post(
            f"/api/v1/workloads/{record['id']}/review", headers={"If-Match": "0"}
        ).status_code
        == 409
    )


def test_approved_unknown_term_cost_is_not_zero(client):
    profile = faculty(client)
    record = client.post("/api/v1/workloads", json=payload(profile, term="Summer")).json()
    client.get("/api/v1/workloads/cost-settings")
    with main.SessionLocal() as db:
        db.get(WorkloadCostSettings, 1).summer_weeks = 0
        db.commit()
    base = f"/api/v1/workloads/{record['id']}"
    assert client.post(base + "/review", headers={"If-Match": "0"}).status_code == 200
    assert client.post(base + "/approve", headers={"If-Match": "1"}).status_code == 200
    summary = client.get("/api/v1/workloads/approved-summary").json()
    assert summary["weekly_pay"] > 0
    assert summary["term_pay"] is None
    assert summary["items"][0]["term_pay"] is None
    assert summary["college_totals"][0]["term_pay"] is None
    assert summary["incomplete_term_count"] == 1
    assert summary["known_term_pay"] == 0
    frozen = client.get(base).json()["approval_snapshot"]
    assert frozen["workload"]["estimated_teaching_pay_term"] is None


@pytest.mark.parametrize("kind", ["faculty-profiles", "workloads"])
def test_stale_and_missing_revision_cannot_delete(client, kind):
    profile = faculty(client)
    if kind == "workloads":
        value = payload(profile)
        record = client.post("/api/v1/workloads", json=value).json()
    else:
        record = profile
        value = {**profile, "name": "Updated Faculty"}
    endpoint = f"/api/v1/{kind}/{record['id']}"
    assert client.delete(endpoint).status_code == 428
    assert client.put(endpoint, json=value, headers={"If-Match": "0"}).status_code == 200
    assert client.delete(endpoint, headers={"If-Match": "0"}).status_code == 409
    assert client.get(endpoint).status_code == 200
    assert client.delete(endpoint, headers={"If-Match": "1"}).status_code == 204


@pytest.mark.parametrize("resource", ["active-period", "overload-budgets"])
def test_shared_setting_rejects_missing_stale_and_first_insert_revisions(client, resource):
    endpoint = f"/api/v1/expenses/{resource}"
    value = {"academic_year": "2026-2027", "term": "First Semester"}
    if resource == "overload-budgets":
        value["amount"] = "100.00"
    assert client.put(endpoint, json=value).status_code == 428
    assert client.put(endpoint, json=value, headers={"If-Match": "1"}).status_code == 409
    saved = client.put(endpoint, json=value, headers={"If-Match": "0"})
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    assert client.put(endpoint, json=value, headers={"If-Match": "0"}).status_code == 409
    updated = client.put(endpoint, json=value, headers={"If-Match": "1"})
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    if resource == "overload-budgets":
        endpoint += f"/{saved.json()['id']}"
        assert client.delete(endpoint, headers={"If-Match": "1"}).status_code == 409
        assert client.delete(endpoint, headers={"If-Match": "2"}).status_code == 204


@pytest.mark.parametrize("year", ["invalid", "2026-2028"])
def test_invalid_confirmation_delete_is_validation_error(client, year):
    assert (
        client.delete(
            "/api/v1/expenses/no-teaching-confirmations/1",
            params={"academic_year": year, "term": "First Semester"},
        ).status_code
        == 422
    )


def test_activity_paging_filters_and_csv_reach_older_history(client):
    with main.SessionLocal() as db:
        db.add_all(
            [
                ActivityEvent(
                    username="History Test",
                    action=f"History {i}",
                    area="Synthetic",
                    created_at=datetime(2020, 1, 1),
                    changed_fields=json.dumps(["name"]),
                )
                for i in range(225)
            ]
        )
        db.commit()
    params = {"search": "History Test", "date_from": "2020-01-01", "date_to": "2020-01-01"}
    first = client.get("/api/v1/activity/page", params=params).json()
    last = client.get("/api/v1/activity/page", params={**params, "page": 5}).json()
    assert first["total"] == 225 and len(first["items"]) == 50 and len(last["items"]) == 25
    assert first["items"][0]["id"] > last["items"][0]["id"]
    exported = client.get("/api/v1/activity/export.csv", params=params)
    assert exported.status_code == 200 and exported.text.count("History Test") == 225
    assert (
        client.get(
            "/api/v1/activity/page", params={"date_from": "2021-01-01", "date_to": "2020-01-01"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/activity/page", params={"page": 0}).status_code == 422


def test_directory_summary_matches_existing_formulas(client):
    profile = faculty(client)
    for index, category in enumerate(
        ["Regular Faculty", "Internal Part-time", "External Part-time"]
    ):
        assert (
            client.post(
                "/api/v1/workloads",
                json=payload(
                    profile,
                    academic_year=f"{2026 + index}-{2027 + index}",
                    compensation_category=category,
                ),
            ).status_code
            == 201
        )
    records = client.get("/api/v1/workloads").json()
    summary = client.get("/api/v1/workloads/page").json()["summary"]
    assert summary["assignments"] == 3 and summary["preparations"] == 3
    assert summary["weekly_pay"] == pytest.approx(
        sum(item["estimated_teaching_pay_weekly"] for item in records)
    )


def test_directory_preparations_match_unicode_casefold(client):
    profile = faculty(client)
    assignments = [
        {"course_code": code, "course_title": "Synthetic", "year_section": "A", "lecture_hours": 8}
        for code in ("Straße", "STRASSE", "HISTORY")
    ]
    record = client.post("/api/v1/workloads", json=payload(profile, assignments=assignments)).json()
    summary = client.get("/api/v1/workloads/page").json()["summary"]
    assert record["preparation_count"] == summary["preparations"] == 2
    assert summary["weekly_pay"] == record["estimated_teaching_pay_weekly"]


@pytest.mark.parametrize("kind", ["faculty-profiles", "workloads", "overload-budgets"])
def test_deleted_recreated_record_rejects_old_revision(client, kind):
    if kind == "overload-budgets":
        endpoint = "/api/v1/expenses/overload-budgets"
        value = {"academic_year": "2026-2027", "term": "First Semester", "amount": "100.00"}
        old = client.put(endpoint, json=value, headers={"If-Match": "0"}).json()
    else:
        profile = faculty(client)
        endpoint = f"/api/v1/{kind}"
        if kind == "workloads":
            value = payload(profile)
            old = client.post(endpoint, json=value).json()
        else:
            value = {**profile, "name": "Recreated Faculty"}
            old = profile
    old_revision = {"If-Match": str(old["revision"])}
    assert client.delete(f"{endpoint}/{old['id']}", headers=old_revision).status_code == 204
    recreated = (
        client.put(endpoint, json=value, headers={"If-Match": "0"})
        if kind == "overload-budgets"
        else client.post(endpoint, json=value)
    )
    assert recreated.status_code in (200, 201)
    new = recreated.json()
    assert new["revision"] > old["revision"]
    assert client.delete(f"{endpoint}/{new['id']}", headers=old_revision).status_code == 409
    if kind == "overload-budgets":
        assert (
            client.put(
                endpoint, json={**value, "amount": "200.00"}, headers=old_revision
            ).status_code
            == 409
        )


def test_activity_timestamps_preserve_utc_and_filter_local_dates(client):
    timestamp = datetime(2020, 1, 1, 23, 30)
    with main.SessionLocal() as db:
        db.add(
            ActivityEvent(
                username="Timezone Test", action="Synthetic", area="Test", created_at=timestamp
            )
        )
        db.commit()
    local_date = timestamp.replace(tzinfo=UTC).astimezone().date().isoformat()
    query = {"search": "Timezone Test", "date_from": local_date, "date_to": local_date}
    records = client.get("/api/v1/activity/page", params=query).json()
    assert records["total"] == 1
    assert records["items"][0]["created_at"].endswith("Z") or records["items"][0][
        "created_at"
    ].endswith("+00:00")
    assert (
        "2020-01-01T23:30:00+00:00" in client.get("/api/v1/activity/export.csv", params=query).text
    )
