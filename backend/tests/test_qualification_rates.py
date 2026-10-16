import json

import pytest
from sqlalchemy import create_engine, text

from app.migrations import migrate_qualification_rate_drafts
from tests.test_workload_preparations import assignment, create_workload, faculty_payload


def rate(**overrides):
    return {
        "category": "Professional credential",
        "qualification": "CPA",
        "effective_from": "2026-08-01",
        **overrides,
    }


def test_draft_defaults_and_round_trip(client):
    assert client.get("/api/v1/qualification-rates/draft").json() == {
        "revision": 0,
        "combination_rule": "Unconfirmed",
        "rates": [],
        "status": "Draft — not applied",
        "applies_to": "External Part-time",
        "updated_by": None,
        "updated_at": None,
    }
    response = client.put(
        "/api/v1/qualification-rates/draft",
        json={"rates": [rate(qualification="  Licensed   engineer  ")]},
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["revision"] == 1
    assert saved["rates"][0]["qualification"] == "Licensed engineer"
    assert saved["rates"][0]["hourly_addition"] == 0
    assert saved["updated_by"] == "test-admin"
    assert saved["status"] == "Draft — not applied"
    assert client.get("/api/v1/qualification-rates/draft").json() == saved
    updated = client.put(
        "/api/v1/qualification-rates/draft",
        json={"revision": 1, "combination_rule": "Highest addition only", "rates": []},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["rates"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"qualification": "   "},
        {"qualification": "x" * 121},
        {"category": "Anything"},
        {"hourly_addition": -1},
        {"hourly_addition": 100001},
        {"hourly_addition": "NaN"},
        {"hourly_addition": "Infinity"},
        {"hourly_addition": "1.001"},
        {"effective_from": "not-a-date"},
        {"effective_to": "2026-07-31"},
        {"reference": "x" * 501},
        {"active": True},
    ],
)
def test_invalid_rate_is_rejected_without_saving(client, overrides):
    response = client.put("/api/v1/qualification-rates/draft", json={"rates": [rate(**overrides)]})
    assert response.status_code == 422
    assert client.get("/api/v1/qualification-rates/draft").json()["revision"] == 0


def test_effective_ranges_cannot_overlap(client):
    payload = {
        "rates": [
            rate(effective_to="2026-12-31"),
            rate(qualification=" cpa ", effective_from="2026-12-31"),
        ]
    }
    assert client.put("/api/v1/qualification-rates/draft", json=payload).status_code == 422
    payload["rates"][1]["effective_from"] = "2027-01-01"
    response = client.put("/api/v1/qualification-rates/draft", json=payload)
    assert response.status_code == 200
    assert len(response.json()["rates"]) == 2
    assert (
        client.put(
            "/api/v1/qualification-rates/draft",
            json={"revision": 1, "rates": [rate(), rate(effective_from="2028-01-01")]},
        ).status_code
        == 422
    )


def test_stale_draft_cannot_overwrite_saved_values(client):
    first = client.put(
        "/api/v1/qualification-rates/draft", json={"rates": [rate(hourly_addition=25.25)]}
    )
    assert first.status_code == 200
    assert (
        client.put(
            "/api/v1/qualification-rates/draft", json={"revision": 0, "rates": []}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/v1/qualification-rates/draft",
            json={"revision": 1, "combination_rule": "Combine additions", "rates": [rate()]},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/qualification-rates/draft", json={"revision": 1, "rates": []}
        ).status_code
        == 409
    )
    assert (
        client.get("/api/v1/qualification-rates/draft").json()["combination_rule"]
        == "Combine additions"
    )


@pytest.mark.parametrize("category", ["Regular Faculty", "External Part-time"])
def test_drafts_cannot_activate_or_change_live_pay_and_approvals(client, category):
    faculty = client.post("/api/v1/faculty-profiles", json=faculty_payload("Draft Safety")).json()
    workload = create_workload(client, faculty["id"], [assignment("TEST101", "1A", 23)])
    endpoint = f"/api/v1/workloads/{workload['id']}"
    assert (
        client.put(
            endpoint,
            json={
                "faculty_profile_id": faculty["id"],
                "academic_year": workload["academic_year"],
                "term": workload["term"],
                "compensation_category": category,
                "professional_qualification": "CPA",
                "assignments": workload["assignments"],
            },
            headers={"If-Match": str(workload["revision"])},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{endpoint}/review", headers={"If-Match": str(workload["revision"] + 1)}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{endpoint}/approve", headers={"If-Match": str(workload["revision"] + 2)}
        ).status_code
        == 200
    )
    before = client.get(endpoint).json()
    settings = client.get("/api/v1/workloads/cost-settings").json()
    response = client.put(
        "/api/v1/qualification-rates/draft",
        json={
            "combination_rule": "Combine additions",
            "rates": [rate(hourly_addition=999, effective_from="2000-01-01")],
        },
    )
    assert response.status_code == 200
    assert client.get(endpoint).json() == before
    assert client.get("/api/v1/workloads/cost-settings").json() == settings
    assert (
        client.put(
            "/api/v1/qualification-rates/draft", json={"revision": 1, "status": "Active"}
        ).status_code
        == 422
    )


def test_staff_and_anonymous_cannot_read_or_change_drafts(client):
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "rate-staff", "password": "rate-staff-password-123", "role": "staff"},
    )
    assert created.status_code == 201
    client.headers.clear()
    assert client.get("/api/v1/qualification-rates/draft").status_code == 401
    assert client.put("/api/v1/qualification-rates/draft", json={}).status_code == 401
    session = client.post(
        "/api/v1/auth/login", json={"username": "rate-staff", "password": "rate-staff-password-123"}
    ).json()
    client.headers.update({"Authorization": f"Bearer {session['token']}"})
    assert client.get("/api/v1/qualification-rates/draft").status_code == 403
    assert client.put("/api/v1/qualification-rates/draft", json={}).status_code == 403


def test_draft_migration_is_idempotent_and_preserves_data():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migrate_qualification_rate_drafts(connection)
        connection.execute(
            text(
                "INSERT INTO qualification_rate_drafts (id, revision, combination_rule, rates_json, updated_by) VALUES (1, 1, 'Unconfirmed', :rates, 'test-admin')"
            ),
            {"rates": json.dumps([rate()])},
        )
        migrate_qualification_rate_drafts(connection)
        saved = connection.execute(
            text("SELECT revision, rates_json FROM qualification_rate_drafts")
        ).one()
        assert saved[0] == 1
        assert json.loads(saved[1]) == [rate()]
