import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, selectinload

from app.auth import require_admin
from app.csv_export import SafeCsvWriter
from app.db import DB_PATH, get_db
from app.migrations import MIGRATIONS, run_migrations
from app.models import FacultyProfile, FacultyWorkload, LocalUser
from app.product import verify_product
from app.restore_recovery import begin_restore, finish_restore

router = APIRouter(prefix="/maintenance", tags=["Backup & Export"])
BACKUP_DIR = DB_PATH.parent / "backups"


def backup_files() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        BACKUP_DIR.glob("cathedra-backup-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def protected_backup_names(backups: list[Path]) -> set[str]:
    protected = {
        item.name
        for item in backups
        if item.name.startswith("cathedra-backup-before-restore-") or backup_pin_path(item).exists()
    }
    newest_regular = next(
        (item for item in backups if not item.name.startswith("cathedra-backup-before-restore-")),
        None,
    )
    if newest_regular is not None:
        protected.add(newest_regular.name)
    return protected


def backup_pin_path(backup: Path) -> Path:
    return backup.with_name(f".{backup.name}.protected")


def selected_backup_file(filename: str) -> Path:
    if (
        filename != Path(filename).name
        or not filename.startswith("cathedra-backup-")
        or not filename.endswith(".db")
    ):
        raise HTTPException(status_code=404, detail="The selected backup is not available.")
    selected = (BACKUP_DIR / filename).resolve()
    if selected.parent != BACKUP_DIR.resolve() or not selected.is_file():
        raise HTTPException(status_code=404, detail="The selected backup is not available.")
    return selected


def make_backup(source: sqlite3.Connection, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.stem}-{uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
        verify_backup_file(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def verify_backup_file(path: Path) -> None:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as database:
        verify_product(database)
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("The backup failed its integrity check.")
        if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("The backup has broken record links.")
        tables = {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if (
            not {
                "schema_migrations",
                "faculty_profiles",
                "faculty_workloads",
                "local_users",
                "local_sessions",
            }
            <= tables
        ):
            raise ValueError("This is not a Cathedra database backup.")
        version = database.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if version is None or version > MIGRATIONS[-1][0]:
            raise ValueError("The backup schema version is not supported.")


def csv_download(filename: str, headings: list[str], rows: list[list[object | None]]) -> Response:
    output = StringIO(newline="")
    writer = SafeCsvWriter(output)
    writer.writerow(headings)
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/status")
def maintenance_status(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as caught:
        raise HTTPException(
            status_code=503, detail="Database connection is unavailable."
        ) from caught

    backups = backup_files()
    latest = backups[0] if backups else None
    protected = protected_backup_names(backups)
    free_bytes = shutil.disk_usage(DB_PATH.parent).free
    backup_storage_bytes = sum(item.stat().st_size for item in backups)
    return {
        "database_status": "healthy",
        "database_file": DB_PATH.name,
        "database_size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "faculty_profiles": db.scalar(select(func.count()).select_from(FacultyProfile)) or 0,
        "workload_records": db.scalar(select(func.count()).select_from(FacultyWorkload)) or 0,
        "backup_count": len(backups),
        "backup_overdue": latest is None
        or datetime.now().timestamp() - latest.stat().st_mtime > 7 * 86400,
        "latest_backup_at": datetime.fromtimestamp(latest.stat().st_mtime).astimezone().isoformat()
        if latest
        else None,
        "backup_retention": None,
        "backup_storage_bytes": backup_storage_bytes,
        "free_storage_bytes": free_bytes,
        "storage_warning": free_bytes < max(1024**3, DB_PATH.stat().st_size * 3)
        if DB_PATH.exists()
        else free_bytes < 1024**3,
        "backups": [
            {
                "filename": item.name,
                "created_at": datetime.fromtimestamp(item.stat().st_mtime).astimezone().isoformat(),
                "size_bytes": item.stat().st_size,
                "protected": item.name in protected,
                "pinned": backup_pin_path(item).exists(),
            }
            for item in backups
        ],
    }


@router.post("/integrity-check")
def check_database_integrity(db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)):
    integrity = list(db.execute(text("PRAGMA integrity_check")).scalars())
    links = db.execute(text("PRAGMA foreign_key_check")).first()
    if integrity != ["ok"] or links is not None:
        raise HTTPException(
            status_code=409,
            detail="Database integrity verification failed. Preserve a backup and request recovery assistance.",
        )
    return {"status": "verified", "checked_at": datetime.now().astimezone().isoformat()}


@router.post("/backups", status_code=status.HTTP_201_CREATED)
def create_database_backup(
    db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> dict[str, object]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = BACKUP_DIR / f"cathedra-backup-{timestamp}.db"

    try:
        make_backup(db.connection().connection.driver_connection, destination)
    except Exception as caught:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to create database backup.") from caught

    return {
        "filename": destination.name,
        "created_at": datetime.now().astimezone().isoformat(),
        "size_bytes": destination.stat().st_size,
    }


@router.get("/backups/{filename}/download")
def download_database_backup(filename: str, _: LocalUser = Depends(require_admin)) -> FileResponse:
    selected = selected_backup_file(filename)
    try:
        verify_backup_file(selected)
    except (sqlite3.DatabaseError, OSError, ValueError) as caught:
        raise HTTPException(
            status_code=422, detail="The selected backup could not be verified for download."
        ) from caught
    return FileResponse(
        selected,
        media_type="application/octet-stream",
        filename=selected.name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/backups/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_database_backup(filename: str, _: LocalUser = Depends(require_admin)) -> Response:
    selected = selected_backup_file(filename)
    if filename in protected_backup_names(backup_files()):
        raise HTTPException(
            status_code=409,
            detail="This backup is protected. The newest regular backup and restore safety copies cannot be deleted here.",
        )
    selected.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/backups/{filename}/protection", status_code=status.HTTP_204_NO_CONTENT)
def protect_database_backup(filename: str, _: LocalUser = Depends(require_admin)) -> Response:
    selected = selected_backup_file(filename)
    backup_pin_path(selected).touch(exist_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/backups/{filename}/protection", status_code=status.HTTP_204_NO_CONTENT)
def unprotect_database_backup(filename: str, _: LocalUser = Depends(require_admin)) -> Response:
    selected = selected_backup_file(filename)
    if selected.name.startswith("cathedra-backup-before-restore-"):
        raise HTTPException(status_code=409, detail="Restore safety backups are always protected.")
    backup_pin_path(selected).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RestoreRequest(BaseModel):
    filename: str


@router.post("/restore")
def restore_database(
    payload: RestoreRequest,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
) -> dict[str, object]:
    selected = (BACKUP_DIR / Path(payload.filename).name).resolve()
    if (
        selected.parent != BACKUP_DIR.resolve()
        or not selected.is_file()
        or selected.suffix != ".db"
    ):
        raise HTTPException(status_code=404, detail="The selected backup is not available.")
    staged = BACKUP_DIR / f".restore-stage-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    try:
        with closing(sqlite3.connect(selected)) as source:
            try:
                verify_product(source)
            except ValueError as caught:
                raise HTTPException(status_code=422, detail=str(caught)) from caught
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise HTTPException(
                    status_code=422, detail="The selected backup could not be verified."
                )
            if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise HTTPException(
                    status_code=422, detail="The selected backup has broken record links."
                )
            tables = {
                row[0]
                for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if (
                not {
                    "schema_migrations",
                    "faculty_profiles",
                    "faculty_workloads",
                    "local_users",
                    "local_sessions",
                }
                <= tables
            ):
                raise HTTPException(
                    status_code=422, detail="This is not a supported Cathedra backup."
                )
            version = source.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if version is None or version > MIGRATIONS[-1][0]:
                raise HTTPException(
                    status_code=422,
                    detail="The backup schema version is not supported by this Cathedra version.",
                )
            with closing(sqlite3.connect(staged)) as staged_target:
                source.backup(staged_target)
        staged_engine = create_engine(f"sqlite:///{staged.as_posix()}")
        try:
            with staged_engine.begin() as connection:
                try:
                    run_migrations(connection)
                except RuntimeError as caught:
                    raise HTTPException(status_code=422, detail=str(caught)) from caught
        finally:
            staged_engine.dispose()
        with closing(sqlite3.connect(staged)) as verified:
            if verified.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise HTTPException(
                    status_code=422, detail="The migrated backup could not be verified."
                )
            if verified.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise HTTPException(
                    status_code=422, detail="The migrated backup has broken record links."
                )
            verified.execute("DELETE FROM local_sessions")
            verified.commit()
        pre_restore = (
            BACKUP_DIR / f"cathedra-backup-before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        )
        target = db.connection().connection.driver_connection
        make_backup(target, pre_restore)
        begin_restore(DB_PATH, pre_restore)
        try:
            with closing(sqlite3.connect(staged)) as source:
                source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Restored database failed integrity verification.")
            if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise sqlite3.DatabaseError("Restored database has broken record links.")
            finish_restore(DB_PATH)
        except Exception:
            with closing(sqlite3.connect(pre_restore)) as recovery:
                recovery.backup(target)
            finish_restore(DB_PATH)
            raise
    except HTTPException:
        raise
    except Exception as caught:
        raise HTTPException(
            status_code=500, detail="Unable to restore the selected backup."
        ) from caught
    finally:
        staged.unlink(missing_ok=True)
    return {"restored_from": selected.name, "safety_backup": pre_restore.name}


@router.get("/exports/faculty-profiles.csv")
def export_faculty_profiles(db: Session = Depends(get_db)) -> Response:
    profiles = db.scalars(
        select(FacultyProfile).order_by(FacultyProfile.name, FacultyProfile.id)
    ).all()
    rows = [
        [
            profile.id,
            profile.name,
            profile.rank,
            profile.employment_status,
            profile.salary_grade,
            profile.salary_step,
            profile.monthly_salary,
            profile.college,
            profile.department,
            profile.data_source,
            profile.created_at,
            profile.updated_at,
            profile.service_status,
            profile.service_status_effective_date,
            profile.campus,
            profile.item_number,
            profile.bachelors_degree,
            profile.masters_degree,
            profile.doctoral_degree,
            profile.eligibility,
            profile.remarks,
        ]
        for profile in profiles
    ]
    return csv_download(
        "cathedra-faculty-profiles.csv",
        [
            "Faculty ID",
            "Name",
            "Academic Rank",
            "Employment Status",
            "Salary Grade",
            "Salary Step",
            "Monthly Salary Equivalent",
            "Department",
            "Program",
            "Source",
            "Created At",
            "Updated At",
            "Faculty Status",
            "Status Effective Date",
            "Campus",
            "Item Number",
            "Bachelor's Degree",
            "Master's Degree",
            "Doctoral Degree",
            "Eligibility",
            "Remarks",
        ],
        rows,
    )


@router.get("/exports/workloads.csv")
def export_workloads(db: Session = Depends(get_db)) -> Response:
    records = (
        db.execute(
            select(FacultyWorkload, FacultyProfile)
            .join(FacultyProfile)
            .options(selectinload(FacultyWorkload.assignments))
            .order_by(FacultyProfile.name, FacultyWorkload.academic_year.desc(), FacultyWorkload.id)
        )
        .unique()
        .all()
    )
    rows: list[list[object | None]] = []
    for workload, profile in records:
        base = [
            workload.id,
            profile.name,
            profile.rank,
            profile.college,
            profile.department,
            workload.academic_year,
            workload.term,
            workload.remarks,
            workload.data_source,
            workload.created_at,
        ]
        for assignment in workload.assignments:
            rows.append(
                base
                + [
                    assignment.course_code,
                    assignment.course_title,
                    assignment.year_section,
                    assignment.lecture_hours,
                    assignment.laboratory_hours,
                    assignment.lecture_hours + assignment.laboratory_hours,
                ]
            )
    return csv_download(
        "cathedra-workloads.csv",
        [
            "Workload ID",
            "Faculty Name",
            "Academic Rank",
            "College",
            "Department",
            "Academic Year",
            "Term",
            "Remarks",
            "Source",
            "Created At",
            "Course Code",
            "Course Title",
            "Year & Section",
            "Lecture Hours",
            "Laboratory Hours",
            "Total Weekly Hours",
        ],
        rows,
    )
