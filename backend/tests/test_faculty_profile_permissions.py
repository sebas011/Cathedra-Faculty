import pytest


def test_faculty_roster_fields_persist_and_status_filter(client) -> None:
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Retired Example",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
            "service_status": "Retired",
            "service_status_effective_date": "2026-09-01",
            "item_number": "ITEM-42",
            "bachelors_degree": "Bachelor of Science",
            "masters_degree": "Master of Arts",
            "doctoral_degree": "Doctor of Philosophy",
            "eligibility": "Licensed Professional Teacher",
            "remarks": "Office-confirmed retirement",
        },
    )
    assert created.status_code == 201
    record = client.get(f"/api/v1/faculty-profiles/{created.json()['id']}").json()
    assert record["service_status"] == "Retired"
    assert record["service_status_effective_date"] == "2026-09-01"
    assert record["item_number"] == "ITEM-42"
    assert record["doctoral_degree"] == "Doctor of Philosophy"
    assert record["remarks"] == "Office-confirmed retirement"
    assert (
        client.get("/api/v1/faculty-profiles/page", params={"service_status": "Retired"}).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get("/api/v1/faculty-profiles/page", params={"service_status": "Active"}).json()[
            "total"
        ]
        == 0
    )


def test_staff_can_edit_general_profile_fields_but_not_pay_drivers(client) -> None:
    admin_token = client.headers["Authorization"]
    profile = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Example Faculty",
            "rank": "Assistant Professor IV",
            "employment_status": "Full-time",
            "salary_step": 2,
            "college": "CAS",
            "department": "Applied Mathematics",
        },
    ).json()
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "profile-staff", "password": "temporary-password-123", "role": "staff"},
    )
    assert staff.status_code == 201
    temporary_token = client.post(
        "/api/v1/auth/login",
        json={"username": "profile-staff", "password": "temporary-password-123"},
    ).json()["token"]
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "temporary-password-123",
                "new_password": "staff-password-123",
            },
            headers={"Authorization": f"Bearer {temporary_token}"},
        ).status_code
        == 204
    )
    staff_token = client.post(
        "/api/v1/auth/login",
        json={"username": "profile-staff", "password": "staff-password-123"},
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {staff_token}"

    endpoint = f"/api/v1/faculty-profiles/{profile['id']}"
    assert client.get(endpoint).json()["monthly_salary"] == 54371
    assert client.post("/api/v1/faculty-profiles", json=profile).status_code == 403
    general = {**profile, "name": "Updated Faculty", "campus": "Talisay", "monthly_salary": 1}
    saved = client.put(endpoint, json=general, headers={"If-Match": str(profile["revision"])})
    assert saved.status_code == 200
    assert saved.json()["name"] == "Updated Faculty"
    assert saved.json()["monthly_salary"] == 54371

    for field, replacement in (
        ("rank", "Assistant Professor III"),
        ("employment_status", "Part-time"),
        ("salary_step", 1),
        ("service_status", "Retired"),
        ("service_status_effective_date", "2026-09-01"),
    ):
        attempted = {**saved.json(), field: replacement}
        denied = client.put(
            endpoint, json=attempted, headers={"If-Match": str(saved.json()["revision"])}
        )
        assert denied.status_code == 403
        assert client.get(endpoint).json()["revision"] == saved.json()["revision"]

    client.headers["Authorization"] = admin_token
    unmapped = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Unmapped Faculty",
            "rank": "Specialist",
            "employment_status": "Full-time",
            "salary_grade": "SG 18",
            "college": "CAS",
            "department": "General",
        },
    ).json()
    client.headers["Authorization"] = f"Bearer {staff_token}"
    denied_grade = client.put(
        f"/api/v1/faculty-profiles/{unmapped['id']}",
        json={**unmapped, "salary_grade": "SG 19"},
        headers={"If-Match": str(unmapped["revision"])},
    )
    assert denied_grade.status_code == 403
    client.headers["Authorization"] = admin_token
    administrator_change = {**saved.json(), "salary_step": 1}
    approved = client.put(
        endpoint, json=administrator_change, headers={"If-Match": str(saved.json()["revision"])}
    )
    assert approved.status_code == 200
    assert approved.json()["monthly_salary"] == 53818


@pytest.mark.parametrize("field", ["name", "campus", "college", "department"])
def test_staff_general_edits_preserve_salary(client, field: str) -> None:
    profile = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "General Faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "General",
        },
    ).json()
    created = client.post(
        "/api/v1/auth/users",
        json={"username": "general-staff", "password": "temporary-password-123", "role": "staff"},
    )
    assert created.status_code == 201
    temporary_token = client.post(
        "/api/v1/auth/login",
        json={"username": "general-staff", "password": "temporary-password-123"},
    ).json()["token"]
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "temporary-password-123",
                "new_password": "staff-password-123",
            },
            headers={"Authorization": f"Bearer {temporary_token}"},
        ).status_code
        == 204
    )
    staff_token = client.post(
        "/api/v1/auth/login",
        json={"username": "general-staff", "password": "staff-password-123"},
    ).json()["token"]
    replacement = "CIT" if field == "college" else "Binalbagan" if field == "campus" else "Updated"
    changed = {**profile, field: replacement}
    response = client.put(
        f"/api/v1/faculty-profiles/{profile['id']}",
        json=changed,
        headers={"Authorization": f"Bearer {staff_token}", "If-Match": str(profile["revision"])},
    )
    assert response.status_code == 200
    assert response.json()["monthly_salary"] == profile["monthly_salary"]
