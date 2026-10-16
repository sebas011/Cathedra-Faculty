def faculty_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Maria Santos",
        "rank": "Associate Professor IV",
        "employment_status": "Full-time",
        "salary_grade": "SG 1",
        "salary_step": 8,
        "college": "CIT",
        "department": "Information Technology",
    }
    payload.update(overrides)
    return payload


def test_salary_scale_exposes_corrected_sg_22_step_8(client) -> None:
    scale = client.get("/api/v1/faculty-profiles/salary-scale")
    assert scale.status_code == 200
    grade = next(item for item in scale.json()["grades"] if item["salary_grade"] == "SG 22")
    assert grade["steps"][-1] == {"step": 8, "monthly_salary": 90295}


def test_rank_sets_official_grade_and_monthly_salary(client) -> None:
    response = client.post("/api/v1/faculty-profiles", json=faculty_payload())
    assert response.status_code == 201
    assert response.json()["salary_grade"] == "SG 22"
    assert response.json()["salary_step"] == 8
    assert response.json()["monthly_salary"] == 90295


def test_unavailable_salary_step_is_rejected(client) -> None:
    response = client.post(
        "/api/v1/faculty-profiles",
        json=faculty_payload(rank="Non-teaching Staff", salary_grade="SG 33", salary_step=3),
    )
    assert response.status_code == 422
