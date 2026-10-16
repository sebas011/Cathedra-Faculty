import sqlite3

from app.api import maintenance


def test_legacy_empty_tables_restore_without_recreating_retired_feature(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    filename = client.post("/api/v1/maintenance/backups").json()["filename"]
    with sqlite3.connect(maintenance.BACKUP_DIR / filename) as database:
        database.execute("DELETE FROM schema_migrations WHERE version=21")
        database.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY)")
    response = client.post("/api/v1/maintenance/restore", json={"filename": filename})
    assert response.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "test-admin",
            "password": "test-password-123",
        },
    )
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    assert client.get("/api/v1/faculty-profiles").status_code == 200
    assert client.get("/api/v1/fsdp").status_code == 404
    next_backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    with sqlite3.connect(maintenance.BACKUP_DIR / next_backup) as database:
        assert (
            database.execute("SELECT name FROM sqlite_master WHERE name='scholars'").fetchone()
            is None
        )


def test_populated_retired_tables_block_restore_without_changing_current_data(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    filename = client.post("/api/v1/maintenance/backups").json()["filename"]
    with sqlite3.connect(maintenance.BACKUP_DIR / filename) as database:
        database.execute("DELETE FROM schema_migrations WHERE version=21")
        database.execute("CREATE TABLE scholars (id INTEGER PRIMARY KEY)")
        database.execute("INSERT INTO scholars VALUES(7)")
    response = client.post("/api/v1/maintenance/restore", json={"filename": filename})
    assert response.status_code == 422
    assert "Preserve and export" in response.json()["detail"]
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/faculty-profiles").status_code == 200
