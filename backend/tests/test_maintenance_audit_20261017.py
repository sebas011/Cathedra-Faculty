import json
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import select, text

import app.main as main
from app.api import maintenance
from app.models import ActivityEvent, LocalSession, LocalUser
from app.restore_recovery import restore_marker_path


def events() -> list[ActivityEvent]:
    with main.SessionLocal() as db:
        return list(
            db.scalars(
                select(ActivityEvent)
                .where(ActivityEvent.area == "Backup & Export")
                .order_by(ActivityEvent.id)
            )
        )


def isolated_maintenance(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(maintenance, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(maintenance, "DB_PATH", tmp_path / "cathedra.db")


def test_maintenance_records_fixed_actor_time_action_without_exported_values(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Private Export Person",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
            "monthly_salary": 54321,
        },
    )
    assert created.status_code == 201
    older = client.post("/api/v1/maintenance/backups").json()["filename"]
    newer = client.post("/api/v1/maintenance/backups").json()["filename"]
    assert client.post("/api/v1/maintenance/integrity-check").status_code == 200
    assert client.get(f"/api/v1/maintenance/backups/{older}/download").status_code == 200
    protection = f"/api/v1/maintenance/backups/{older}/protection"
    assert client.post(protection).status_code == 204
    assert client.delete(protection).status_code == 204
    assert client.delete(f"/api/v1/maintenance/backups/{older}").status_code == 204
    assert client.get("/api/v1/maintenance/exports/faculty-profiles.csv").status_code == 200
    assert client.get("/api/v1/maintenance/exports/workloads.csv").status_code == 200

    history = events()
    actions = [event.action for event in history]
    for operation in (
        "database backup creation",
        "database integrity check",
        "database backup protection",
        "database backup unprotection",
        "database backup deletion",
    ):
        assert f"Requested {operation}" in actions
        assert f"Completed {operation}" in actions
        assert actions.index(f"Requested {operation}") < actions.index(f"Completed {operation}")
    for action in (
        "Prepared database backup download",
        "Prepared personnel CSV export",
        "Prepared workload CSV export",
    ):
        assert action in actions
        assert next(event for event in history if event.action == action).operation == "Prepared"
    for event in history:
        assert event.username == "test-admin" and event.user_id == 1
        assert event.created_at is not None
        assert event.changed_fields == "[]"
    serialized = json.dumps(
        [{"action": event.action, "changed_fields": event.changed_fields} for event in history]
    )
    for private_value in (older, newer, "Private Export Person", "54321", "test-password-123"):
        assert private_value not in serialized


def test_staff_keeps_signed_in_export_access_with_attributed_preparation_events(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    assert (
        client.post(
            "/api/v1/auth/users",
            json={"username": "export-staff", "password": "staff-password-123", "role": "staff"},
        ).status_code
        == 201
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "export-staff", "password": "staff-password-123"},
    )
    assert login.status_code == 200
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "staff-password-123", "new_password": "changed-password-123"},
        ).status_code
        == 204
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "export-staff", "password": "changed-password-123"},
    )
    assert login.status_code == 200
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    for name in ("faculty-profiles", "workloads"):
        assert client.get(f"/api/v1/maintenance/exports/{name}.csv").status_code == 200
    assert client.get(f"/api/v1/maintenance/backups/{backup}/download").status_code == 403
    assert client.post("/api/v1/maintenance/backups").status_code == 403
    staff_history = [event for event in events() if event.username == "export-staff"]
    assert {event.action for event in staff_history} == {
        "Prepared personnel CSV export",
        "Prepared workload CSV export",
    }


def test_rejected_backup_operations_never_record_success(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    before = len(events())
    assert client.delete(f"/api/v1/maintenance/backups/{backup}").status_code == 409
    (maintenance.BACKUP_DIR / backup).write_bytes(b"malformed backup")
    assert client.get(f"/api/v1/maintenance/backups/{backup}/download").status_code == 422
    assert client.post("/api/v1/maintenance/restore", json={"filename": backup}).status_code == 422
    assert len(events()) == before
    assert client.get("/api/v1/auth/me").status_code == 200


def test_failed_backup_has_intent_and_failure_without_completion(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)

    def fail_verification(_: Path) -> None:
        raise ValueError("invalid backup")

    monkeypatch.setattr(maintenance, "verify_backup_file", fail_verification)
    assert client.post("/api/v1/maintenance/backups").status_code == 500
    assert [event.action for event in events()] == [
        "Requested database backup creation",
        "Failed database backup creation",
    ]
    assert list(maintenance.BACKUP_DIR.iterdir()) == []


def test_audit_intent_failure_prevents_backup_deletion(client, monkeypatch, tmp_path: Path) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    older = client.post("/api/v1/maintenance/backups").json()["filename"]
    client.post("/api/v1/maintenance/backups")
    with main.SessionLocal() as db:
        db.execute(
            text(
                "CREATE TRIGGER reject_delete_intent BEFORE INSERT ON activity_events "
                "WHEN NEW.action = 'Requested database backup deletion' "
                "BEGIN SELECT RAISE(ABORT, 'activity unavailable'); END"
            )
        )
        db.commit()
    response = client.delete(f"/api/v1/maintenance/backups/{older}")
    assert response.status_code == 503
    assert (maintenance.BACKUP_DIR / older).exists()
    assert not any("deletion" in event.action for event in events())


def test_delete_completion_audit_failure_reports_completed_effect_explicitly(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    older = client.post("/api/v1/maintenance/backups").json()["filename"]
    client.post("/api/v1/maintenance/backups")
    with main.SessionLocal() as db:
        db.execute(
            text(
                "CREATE TRIGGER reject_delete_completion BEFORE INSERT ON activity_events "
                "WHEN NEW.action = 'Completed database backup deletion' "
                "BEGIN SELECT RAISE(ABORT, 'activity unavailable'); END"
            )
        )
        db.commit()
    response = client.delete(f"/api/v1/maintenance/backups/{older}")
    assert response.status_code == 503
    assert "Completed database backup deletion" in response.json()["detail"]
    assert not (maintenance.BACKUP_DIR / older).exists()
    assert [event.action for event in events() if "deletion" in event.action] == [
        "Requested database backup deletion"
    ]


def test_restore_preserves_initiating_identity_with_cross_database_id_collision(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    with closing(sqlite3.connect(maintenance.BACKUP_DIR / backup)) as database, database:
        database.execute(
            "UPDATE local_users SET username = 'different-restored-person' WHERE id = 1"
        )
    original_record_activity = maintenance.restored_activity

    def verify_marker_then_record(target: sqlite3.Connection, username: str) -> None:
        assert restore_marker_path(maintenance.DB_PATH).exists()
        original_record_activity(target, username)
        assert not target.in_transaction
        assert restore_marker_path(maintenance.DB_PATH).exists()

    monkeypatch.setattr(maintenance, "restored_activity", verify_marker_then_record)
    restored = client.post("/api/v1/maintenance/restore", json={"filename": backup})
    assert restored.status_code == 200
    assert not restore_marker_path(maintenance.DB_PATH).exists()
    assert client.get("/api/v1/auth/me").status_code == 401
    with main.SessionLocal() as db:
        assert db.get(LocalUser, 1).username == "different-restored-person"
        assert list(db.scalars(select(LocalSession))) == []
    completed = [event for event in events() if event.action == "Completed database restore"]
    assert len(completed) == 1
    assert completed[0].username == "test-admin"
    assert completed[0].user_id is None
    assert completed[0].created_at is not None


def test_restore_intent_failure_preserves_active_records_and_sessions(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Preserved before restore intent",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
        },
    ).json()
    with main.SessionLocal() as db:
        db.execute(
            text(
                "CREATE TRIGGER reject_restore_intent BEFORE INSERT ON activity_events "
                "WHEN NEW.action = 'Requested database restore' "
                "BEGIN SELECT RAISE(ABORT, 'restore activity unavailable'); END"
            )
        )
        db.commit()

    restored = client.post("/api/v1/maintenance/restore", json={"filename": backup})

    assert restored.status_code == 503
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get(f"/api/v1/faculty-profiles/{created['id']}").json()["name"] == created["name"]
    assert not restore_marker_path(maintenance.DB_PATH).exists()
    assert not list(maintenance.BACKUP_DIR.glob("cathedra-backup-before-restore-*.db"))
    assert not list(maintenance.BACKUP_DIR.glob(".restore-stage-*.db"))
    assert not any("restore" in event.action for event in events())


def test_restore_activity_failure_recovers_previous_data_and_sessions(
    client, monkeypatch, tmp_path: Path
) -> None:
    isolated_maintenance(monkeypatch, tmp_path)
    backup = client.post("/api/v1/maintenance/backups").json()["filename"]
    with closing(sqlite3.connect(maintenance.BACKUP_DIR / backup)) as database, database:
        database.execute(
            "CREATE TRIGGER reject_restore_completion BEFORE INSERT ON activity_events "
            "WHEN NEW.action = 'Completed database restore' "
            "BEGIN SELECT RAISE(ABORT, 'restore activity unavailable'); END"
        )
    created = client.post(
        "/api/v1/faculty-profiles",
        json={
            "name": "Preserved after failed restore",
            "rank": "Instructor I",
            "employment_status": "Full-time",
            "college": "CAS",
            "department": "BSAM",
        },
    ).json()
    restored = client.post("/api/v1/maintenance/restore", json={"filename": backup})
    assert restored.status_code == 500
    assert not restore_marker_path(maintenance.DB_PATH).exists()
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get(f"/api/v1/faculty-profiles/{created['id']}").json()["name"] == created["name"]
    assert [event.action for event in events() if "restore" in event.action] == [
        "Requested database restore",
        "Failed database restore",
    ]
