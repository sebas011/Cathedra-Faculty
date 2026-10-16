import json
from datetime import UTC, date, datetime, time, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.csv_export import SafeCsvWriter
from app.db import get_db
from app.models import ActivityEvent, LocalUser

router = APIRouter(prefix="/activity", tags=["Activity History"])


def activity_query(search: str, date_from: date | None, date_to: date | None):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must be before the end date.")
    statement = select(ActivityEvent)
    if search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                ActivityEvent.username.ilike(pattern),
                ActivityEvent.area.ilike(pattern),
                ActivityEvent.action.ilike(pattern),
            )
        )
    if date_from:
        statement = statement.where(
            ActivityEvent.created_at
            >= datetime.combine(date_from, time.min).astimezone(UTC).replace(tzinfo=None)
        )
    if date_to:
        statement = statement.where(
            ActivityEvent.created_at
            < (datetime.combine(date_to, time.min) + timedelta(days=1))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
    return statement.order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())


def read_event(event):
    return {
        "id": event.id,
        "username": event.username,
        "action": event.action,
        "area": event.area,
        "created_at": event.created_at.replace(tzinfo=UTC),
        "record_type": event.record_type,
        "record_id": event.record_id,
        "operation": event.operation,
        "changed_fields": json.loads(event.changed_fields) if event.changed_fields else [],
    }


@router.get("/page")
def paged_activity(
    search: str = Query(default="", max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
):
    statement = activity_query(search, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    events = db.scalars(statement.offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [read_event(event) for event in events],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/export.csv")
def export_activity(
    search: str = Query(default="", max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
):
    statement = activity_query(search, date_from, date_to).execution_options(yield_per=256)

    def rows():
        output = StringIO(newline="")
        writer = SafeCsvWriter(output)
        writer.writerow(["When", "Person", "Area", "Action", "Changed fields"])
        yield output.getvalue()
        for event in db.scalars(statement):
            output.seek(0)
            output.truncate(0)
            writer.writerow(
                [
                    read_event(event)["created_at"].isoformat(),
                    event.username,
                    event.area,
                    event.action,
                    ", ".join(read_event(event)["changed_fields"]),
                ]
            )
            yield output.getvalue()

    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cathedra-activity.csv"'},
    )


@router.get("")
def list_activity(
    db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> list[dict[str, object]]:
    events = db.scalars(
        select(ActivityEvent)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(200)
    ).all()
    return [read_event(event) for event in events]
