from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.expense_schemas import SavedProjectionRead
from app.models import LocalUser, SavedProjection, SemesterCloseoutEstimate
from app.services.projection import build_monthly_projection
from app.services.snapshots import dump_projection, load_projection

router = APIRouter(prefix="/expenses/closeout-estimates", tags=["Semester Closeout"])
Term = Literal["First Semester", "Second Semester", "Summer"]


class CloseoutEstimateInput(BaseModel):
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    term: Term
    as_of: date

    @field_validator("academic_year")
    @classmethod
    def consecutive_years(cls, value: str) -> str:
        start, end = map(int, value.split("-"))
        if end != start + 1:
            raise ValueError("Academic year must contain consecutive years.")
        return value


def read_estimate(record: SavedProjection) -> SavedProjectionRead:
    return SavedProjectionRead(
        id=record.id,
        academic_year=record.academic_year,
        term=record.term,
        period=record.period,
        created_by=record.created_by,
        created_at=record.created_at,
        projection=load_projection(record.projection_json, record_id=record.id),
        closeout=True,
    )


@router.get("", response_model=SavedProjectionRead | None)
def get_closeout_estimate(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[LocalUser, Depends(require_admin)],
    academic_year: str = Query(pattern=r"^\d{4}-\d{4}$"),
    term: Term = "First Semester",
) -> SavedProjectionRead | None:
    start, end = map(int, academic_year.split("-"))
    if end != start + 1:
        raise HTTPException(status_code=422, detail="Academic year must contain consecutive years.")
    record = db.scalar(
        select(SavedProjection)
        .join(
            SemesterCloseoutEstimate,
            SemesterCloseoutEstimate.projection_id == SavedProjection.id,
        )
        .where(
            SemesterCloseoutEstimate.academic_year == academic_year,
            SemesterCloseoutEstimate.term == term,
        )
    )
    return read_estimate(record) if record else None


@router.post("", response_model=SavedProjectionRead, status_code=201)
def create_closeout_estimate(
    payload: CloseoutEstimateInput,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[LocalUser, Depends(require_admin)],
) -> SavedProjectionRead:
    existing = db.scalar(
        select(SemesterCloseoutEstimate.id).where(
            SemesterCloseoutEstimate.academic_year == payload.academic_year,
            SemesterCloseoutEstimate.term == payload.term,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="This term already has a saved closeout estimate."
        )
    period = "summer" if payload.term == "Summer" else "semester"
    projection = build_monthly_projection(
        db,
        academic_year=payload.academic_year,
        term=payload.term,
        period=period,
        as_of=payload.as_of,
    )
    record = SavedProjection(
        academic_year=payload.academic_year,
        term=payload.term,
        period=period,
        created_by=user.username,
        projection_json=dump_projection(projection),
    )
    try:
        db.add(record)
        db.flush()
        db.add(
            SemesterCloseoutEstimate(
                academic_year=payload.academic_year,
                term=payload.term,
                projection_id=record.id,
            )
        )
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This term already has a saved closeout estimate. Refresh to view it.",
        ) from caught
    db.refresh(record)
    return read_estimate(record)
