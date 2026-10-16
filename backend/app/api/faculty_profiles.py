from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_admin, require_signed_in
from app.concurrency import advance_revision
from app.db import get_db
from app.faculty_schemas import FacultyProfileCreate, FacultyProfileRead, FacultyProfileUpdate
from app.models import FacultyNoTeachingConfirmation, FacultyProfile, FacultyWorkload, LocalUser
from app.salary_scale import grade_for_rank, normalize_grade, salary_scale_payload
from app.workload_read import get_workload_cost_settings_record, read_workload, workload_options
from app.workload_schemas import FacultyWorkloadRead

router = APIRouter(prefix="/faculty-profiles", tags=["Faculty Profile"])


@router.get("/salary-scale")
def get_salary_scale() -> dict[str, object]:
    return salary_scale_payload()


@router.get("", response_model=list[FacultyProfileRead])
def list_profiles(
    search: str = Query(default="", max_length=200), db: Session = Depends(get_db)
) -> list[FacultyProfile]:
    statement = select(FacultyProfile)
    if search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                FacultyProfile.name.ilike(term),
                FacultyProfile.rank.ilike(term),
                FacultyProfile.college.ilike(term),
                FacultyProfile.department.ilike(term),
            )
        )
    return list(db.scalars(statement.order_by(FacultyProfile.name)).all())


@router.get("/page")
def paged_profiles(
    search: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    service_status: Literal["Active", "Inactive", "Retired", "Resigned", "To verify"] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    statement = select(FacultyProfile)
    if service_status:
        statement = statement.where(FacultyProfile.service_status == service_status)
    if search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                FacultyProfile.name.ilike(term),
                FacultyProfile.rank.ilike(term),
                FacultyProfile.college.ilike(term),
                FacultyProfile.department.ilike(term),
            )
        )
    matching = statement.subquery()
    totals = db.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(case((matching.c.employment_status == "Full-time", 1), else_=0)), 0
            ),
            func.count(
                func.distinct(
                    func.nullif(func.nullif(func.trim(matching.c.college), ""), "Unassigned")
                )
            ),
            func.coalesce(
                func.sum(case((matching.c.data_source == "Imported from ScholarDesk", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            or_(
                                matching.c.college.in_(("", "Unassigned")),
                                matching.c.department.in_(("", "To verify")),
                                matching.c.employment_status.in_(("", "To verify")),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).select_from(matching)
    ).one()
    total = totals[0]
    summary = {
        "full_time": totals[1],
        "colleges": totals[2],
        "imported": totals[3],
        "pending_placement": totals[4],
    }
    items = list(
        db.scalars(
            statement.order_by(FacultyProfile.name).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return {
        "items": [
            FacultyProfileRead.model_validate(item).model_dump(mode="json") for item in items
        ],
        "total": total,
        "summary": summary,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{profile_id}/workloads", response_model=list[FacultyWorkloadRead])
def profile_workloads(profile_id: int, db: Session = Depends(get_db)) -> list[FacultyWorkloadRead]:
    profile = get_profile(profile_id, db)
    records = list(
        db.scalars(
            select(FacultyWorkload)
            .options(*workload_options())
            .where(FacultyWorkload.faculty_profile_id == profile.id)
            .order_by(FacultyWorkload.academic_year.desc(), FacultyWorkload.term)
        ).all()
    )
    settings = get_workload_cost_settings_record(db)
    return [read_workload(record, profile, settings) for record in records]


@router.get("/{profile_id}", response_model=FacultyProfileRead)
def get_profile(profile_id: int, db: Session = Depends(get_db)) -> FacultyProfile:
    profile = db.get(FacultyProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Faculty profile not found.")
    return profile


@router.post("", response_model=FacultyProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: FacultyProfileCreate,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
) -> FacultyProfile:
    if (
        payload.service_status in ("Active", "To verify")
        and payload.service_status_effective_date is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="An effective date is only used for inactive, retired, or resigned status.",
        )
    if (
        payload.service_status in ("Inactive", "Retired", "Resigned")
        and payload.service_status_effective_date is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Enter the effective date for an inactive, retired, or resigned faculty member.",
        )
    duplicate = db.scalar(
        select(FacultyProfile).where(
            FacultyProfile.name.ilike(payload.name.strip()),
            FacultyProfile.college == payload.college,
            FacultyProfile.department.ilike(payload.department.strip()),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="A faculty profile with this name, department, and program already exists.",
        )
    profile = FacultyProfile(**payload.model_dump())
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        # A concurrent request may have inserted the same identity after the precheck.
        duplicate = db.scalar(
            select(FacultyProfile).where(
                FacultyProfile.name.ilike(payload.name.strip()),
                FacultyProfile.college == payload.college,
                FacultyProfile.department.ilike(payload.department.strip()),
            )
        )
        if duplicate is None:
            raise
        raise HTTPException(
            status_code=409,
            detail="A faculty profile with this name, department, and program already exists.",
        ) from caught
    db.refresh(profile)
    return profile


@router.put("/{profile_id}", response_model=FacultyProfileRead)
def update_profile(
    profile_id: int,
    payload: FacultyProfileUpdate,
    db: Session = Depends(get_db),
    user: LocalUser = Depends(require_signed_in),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> FacultyProfile:
    profile = get_profile(profile_id, db)
    if user.role != "admin":
        current_grade = grade_for_rank(profile.rank) or normalize_grade(profile.salary_grade)
        if (
            payload.rank != profile.rank
            or payload.employment_status != profile.employment_status
            or payload.salary_grade != current_grade
            or payload.salary_step != profile.salary_step
            or payload.service_status != profile.service_status
            or payload.service_status_effective_date != profile.service_status_effective_date
        ):
            raise HTTPException(
                status_code=403, detail="An administrator must change appointment or salary fields."
            )
    if (
        payload.service_status in ("Inactive", "Retired", "Resigned")
        and payload.service_status_effective_date is None
        and (
            payload.service_status != profile.service_status
            or profile.service_status_effective_date is not None
        )
    ):
        raise HTTPException(
            status_code=422, detail="Enter the effective date for this faculty status change."
        )
    if (
        payload.service_status in ("Active", "To verify")
        and payload.service_status_effective_date is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="Clear the previous status effective date when restoring or verifying active status.",
        )
    duplicate = db.scalar(
        select(FacultyProfile).where(
            FacultyProfile.id != profile_id,
            FacultyProfile.name.ilike(payload.name.strip()),
            FacultyProfile.college == payload.college,
            FacultyProfile.department.ilike(payload.department.strip()),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="A faculty profile with this name, department, and program already exists.",
        )
    advance_revision(db, FacultyProfile, profile_id, if_match)
    changes = payload.model_dump()
    if user.role != "admin":
        changes = {
            field: changes[field]
            for field in (
                "name",
                "campus",
                "college",
                "department",
                "item_number",
                "bachelors_degree",
                "masters_degree",
                "doctoral_degree",
                "eligibility",
                "remarks",
            )
        }
    elif profile.salary_source:
        changes.pop("monthly_salary")
    for field, value in changes.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
    if_match: int | None = Header(default=None, alias="If-Match"),
) -> Response:
    profile = get_profile(profile_id, db)
    advance_revision(db, FacultyProfile, profile_id, if_match)
    db.refresh(profile)
    if (
        db.scalar(
            select(FacultyWorkload.id)
            .where(FacultyWorkload.faculty_profile_id == profile_id)
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="This faculty profile has workload history and cannot be deleted.",
        )
    if (
        db.scalar(
            select(FacultyNoTeachingConfirmation.id)
            .where(FacultyNoTeachingConfirmation.faculty_id == profile_id)
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="This faculty profile has semester no-teaching confirmations. Undo them before deleting the profile.",
        )
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
