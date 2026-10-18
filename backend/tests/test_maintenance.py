import sqlite3
from contextlib import closing
from pathlib import Path

from app.api import maintenance
from app.migrations import MIGRATIONS


def test_status_backup_and_csv_exports(client, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")

    status = client.get("/api/v1/maintenance/status")
    assert status.status_code == 200
    assert status.json()["database_status"] == "healthy"
    assert status.json()["backup_count"] == 0

    backup = client.post("/api/v1/maintenance/backups")
    assert backup.status_code == 201
    backup_file = maintenance.BACKUP_DIR / backup.json()["filename"]
    assert backup_file.exists()
    assert backup.json()["size_bytes"] == backup_file.stat().st_size

    refreshed_status = client.get("/api/v1/maintenance/status")
    assert refreshed_status.json()["backup_count"] == 1

    restored = client.post(
        "/api/v1/maintenance/restore", json={"filename": backup.json()["filename"]}
    )
    assert restored.status_code == 200
    assert (maintenance.BACKUP_DIR / restored.json()["safety_backup"]).exists()
    assert client.get("/api/v1/auth/me").status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password-123"}
    )
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    for endpoint, heading in (
        ("/api/v1/maintenance/exports/faculty-profiles.csv", "Faculty ID,"),
        ("/api/v1/maintenance/exports/workloads.csv", "Workload ID,"),
    ):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.text.startswith(heading)


def test_restore_rejects_non_cathedra_and_newer_schema_without_changing_active_data(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    maintenance.BACKUP_DIR.mkdir()
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Preserved faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
        },
    ).json()
    foreign = maintenance.BACKUP_DIR / "foreign.db"
    with closing(sqlite3.connect(foreign)) as connection, connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    assert (
        client.post("/api/v1/maintenance/restore", json={"filename": foreign.name}).status_code
        == 422
    )
    backup = client.post("/api/v1/maintenance/backups").json()
    with (
        closing(sqlite3.connect(maintenance.BACKUP_DIR / backup["filename"])) as connection,
        connection,
    ):
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (MIGRATIONS[-1][0] + 1, "future"),
        )
    assert (
        client.post(
            "/api/v1/maintenance/restore", json={"filename": backup["filename"]}
        ).status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/faculty-profiles/{created['id']}").json()["name"]
        == "Preserved faculty"
    )


def test_restore_rejects_broken_record_links_without_changing_active_data(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Preserved faculty",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
        },
    ).json()
    backup = client.post("/api/v1/maintenance/backups").json()
    with (
        closing(sqlite3.connect(maintenance.BACKUP_DIR / backup["filename"])) as connection,
        connection,
    ):
        connection.execute(
            "INSERT INTO faculty_no_teaching_confirmations (faculty_id, academic_year, term, confirmed_by) VALUES (?, ?, ?, ?)",
            (999999, "2026-2027", "First Semester", "test-admin"),
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is not None

    response = client.post("/api/v1/maintenance/restore", json={"filename": backup["filename"]})
    assert response.status_code == 422
    assert (
        client.get(f"/api/v1/faculty-profiles/{created['id']}").json()["name"]
        == "Preserved faculty"
    )


def test_admin_can_download_verified_backup_but_staff_cannot(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    backup = client.post("/api/v1/maintenance/backups").json()
    endpoint = f"/api/v1/maintenance/backups/{backup['filename']}/download"
    downloaded = client.get(endpoint)
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"SQLite format 3\x00")
    assert backup["filename"] in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "no-store"

    staff = client.post(
        "/api/v1/auth/users",
        json={
            "username": "backup-staff",
            "password": "test-password-123",
            "role": "staff",
        },
    )
    assert staff.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "backup-staff",
            "password": "test-password-123",
        },
    )
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    assert client.get(endpoint).status_code == 403


def test_corrupt_backup_cannot_be_downloaded(client, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    backup = client.post("/api/v1/maintenance/backups").json()
    (maintenance.BACKUP_DIR / backup["filename"]).write_bytes(b"not a database")
    response = client.get(f"/api/v1/maintenance/backups/{backup['filename']}/download")
    assert response.status_code == 422


def test_failed_backup_verification_does_not_publish_file(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")

    def fail_verification(_: Path) -> None:
        raise ValueError("verification failed")

    monkeypatch.setattr(maintenance, "verify_backup_file", fail_verification)
    response = client.post("/api/v1/maintenance/backups")
    assert response.status_code == 500
    assert list(maintenance.BACKUP_DIR.iterdir()) == []


def test_only_admin_can_prune_unprotected_backup(client, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    first = client.post("/api/v1/maintenance/backups").json()["filename"]
    second = client.post("/api/v1/maintenance/backups").json()["filename"]
    status = client.get("/api/v1/maintenance/status").json()
    assert status["backup_storage_bytes"] > 0
    assert status["free_storage_bytes"] > 0
    assert next(item for item in status["backups"] if item["filename"] == second)["protected"]
    assert client.delete(f"/api/v1/maintenance/backups/{second}").status_code == 409

    staff = client.post(
        "/api/v1/auth/users",
        json={
            "username": "backup-prune-staff",
            "password": "test-password-123",
            "role": "staff",
        },
    )
    assert staff.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "backup-prune-staff",
            "password": "test-password-123",
        },
    )
    staff_token = login.json()["token"]
    admin_token = client.headers["Authorization"]
    client.headers["Authorization"] = f"Bearer {staff_token}"
    assert client.delete(f"/api/v1/maintenance/backups/{first}").status_code == 403
    client.headers["Authorization"] = admin_token
    assert client.delete(f"/api/v1/maintenance/backups/{first}").status_code == 204
    assert not (maintenance.BACKUP_DIR / first).exists()
    assert (maintenance.BACKUP_DIR / second).exists()


def test_restore_safety_backup_cannot_be_pruned(client, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    restored = client.post("/api/v1/maintenance/restore", json={"filename": backup})
    assert restored.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "test-admin",
            "password": "test-password-123",
        },
    )
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    safety_backup = restored.json()["safety_backup"]
    assert client.delete(f"/api/v1/maintenance/backups/{safety_backup}").status_code == 409
    assert (maintenance.BACKUP_DIR / safety_backup).exists()


def test_admin_can_pin_older_backup_without_automatic_pruning(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    older = client.post("/api/v1/maintenance/backups").json()["filename"]
    newest = client.post("/api/v1/maintenance/backups").json()["filename"]
    protection = f"/api/v1/maintenance/backups/{older}/protection"
    assert client.post(protection).status_code == 204
    status = client.get("/api/v1/maintenance/status").json()
    older_status = next(item for item in status["backups"] if item["filename"] == older)
    assert older_status["protected"] and older_status["pinned"]
    assert client.delete(f"/api/v1/maintenance/backups/{older}").status_code == 409
    assert client.delete(protection).status_code == 204
    assert client.delete(f"/api/v1/maintenance/backups/{older}").status_code == 204
    assert (maintenance.BACKUP_DIR / newest).exists()
