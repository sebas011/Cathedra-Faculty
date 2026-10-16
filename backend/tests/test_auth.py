def test_records_require_a_local_session(client) -> None:
    client.headers.clear()
    response = client.get("/api/v1/faculty-profiles")
    assert response.status_code == 401


def test_health_reports_the_release_version(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["release_version"]


def test_administrator_can_create_staff_account(client) -> None:
    response = client.post(
        "/api/v1/auth/users",
        json={"username": "office-staff", "password": "staff-password-123", "role": "staff"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "staff"
    history = client.get("/api/v1/activity")
    assert history.status_code == 200
    assert history.json()[0]["area"] == "Local Accounts"


def test_user_can_change_password(client) -> None:
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "test-password-123", "new_password": "new-test-password-123"},
    )
    assert changed.status_code == 204
    client.headers.clear()
    login = client.post(
        "/api/v1/auth/login", json={"username": "test-admin", "password": "new-test-password-123"}
    )
    assert login.status_code == 200


def test_temporary_credentials_require_password_change_and_revocation(client) -> None:
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "temporary-staff", "password": "temporary-password-123", "role": "staff"},
    ).json()
    assert staff["must_change_password"] is True
    signed_in = client.post(
        "/api/v1/auth/login",
        json={"username": "temporary-staff", "password": "temporary-password-123"},
    ).json()
    token = signed_in["token"]
    assert (
        client.get(
            "/api/v1/faculty-profiles", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "temporary-password-123",
                "new_password": "permanent-password-123",
            },
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 204
    )
    assert (
        client.get(
            "/api/v1/faculty-profiles", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    signed_in = client.post(
        "/api/v1/auth/login",
        json={"username": "temporary-staff", "password": "permanent-password-123"},
    ).json()
    token = signed_in["token"]
    assert (
        client.get(
            "/api/v1/faculty-profiles", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/auth/users/{staff['id']}/revoke-sessions").status_code == 204
    assert (
        client.get(
            "/api/v1/faculty-profiles", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )


def test_disabled_accounts_cannot_sign_in_and_last_admin_is_protected(client) -> None:
    admin = client.get("/api/v1/auth/me").json()
    assert (
        client.put(f"/api/v1/auth/users/{admin['id']}/status", json={"active": False}).status_code
        == 409
    )
    staff = client.post(
        "/api/v1/auth/users",
        json={"username": "disabled-staff", "password": "temporary-password-123", "role": "staff"},
    ).json()
    assert (
        client.put(f"/api/v1/auth/users/{staff['id']}/status", json={"active": False}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "disabled-staff", "password": "temporary-password-123"},
        ).status_code
        == 401
    )
    assert (
        client.put(f"/api/v1/auth/users/{staff['id']}/status", json={"active": True}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "disabled-staff", "password": "temporary-password-123"},
        ).status_code
        == 200
    )
