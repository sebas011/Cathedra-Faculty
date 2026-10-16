import json

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, selectinload

from app.activity_audit import add_activity
from app.models import FacultyProfile, FacultyWorkload, WorkloadCostSettings
from app.workload_schemas import FacultyWorkloadRead, TeachingAssignmentRead


def workload_options():
    return [selectinload(FacultyWorkload.assignments)]


def get_workload_cost_settings_record(db: Session) -> WorkloadCostSettings:
    settings = db.get(WorkloadCostSettings, 1)
    if settings is None:
        # Dashboard requests may all see an empty settings table on first use.
        inserted = db.execute(
            insert(WorkloadCostSettings).values(id=1).on_conflict_do_nothing(index_elements=["id"])
        )
        if inserted.rowcount == 1:
            add_activity(
                db,
                "Compensation Rules",
                "Created Compensation Rules #1",
                record_type=WorkloadCostSettings.__tablename__,
                record_id=1,
                operation="Created",
                changed_fields=sorted(
                    column.key
                    for column in WorkloadCostSettings.__table__.columns
                    if column.key not in {"id", "updated_at"}
                ),
            )
        db.commit()
        settings = db.get(WorkloadCostSettings, 1)
    return settings


def calculate_teaching_cost(
    workload: FacultyWorkload,
    faculty: FacultyProfile,
    total_weekly_hours: float,
    overload_weekly_hours: float,
    settings: WorkloadCostSettings,
) -> tuple[str, float, float]:
    category = workload.compensation_category or "Regular Faculty"
    if category == "Internal Part-time":
        hourly_rate = (faculty.monthly_salary or 0) / settings.internal_monthly_equivalent_hours
        return category, hourly_rate, total_weekly_hours * hourly_rate
    if category == "External Part-time":
        hourly_rate = settings.external_base_hourly_rate
        if workload.highest_qualification == "Masters":
            hourly_rate += settings.external_masters_increment
        elif workload.highest_qualification == "Doctorate":
            hourly_rate += settings.external_doctorate_increment
        if workload.professional_qualification == "Doctor":
            hourly_rate += settings.external_doctor_increment
        elif workload.professional_qualification == "Lawyer":
            hourly_rate += settings.external_lawyer_increment
        return category, hourly_rate, total_weekly_hours * hourly_rate
    hourly_rate = (faculty.monthly_salary or 0) * 12 * 0.000781
    return category, hourly_rate, overload_weekly_hours * hourly_rate


def weeks_for_term(term: str, settings: WorkloadCostSettings) -> int:
    return {
        "first semester": settings.first_semester_weeks,
        "1st semester": settings.first_semester_weeks,
        "second semester": settings.second_semester_weeks,
        "2nd semester": settings.second_semester_weeks,
        "summer": settings.summer_weeks,
    }.get(term.strip().lower(), 0)


def read_workload(
    workload: FacultyWorkload, faculty: FacultyProfile, settings: WorkloadCostSettings
) -> FacultyWorkloadRead:
    assignments = [TeachingAssignmentRead.model_validate(item) for item in workload.assignments]
    total_lecture_hours = sum(item.lecture_hours for item in assignments)
    total_laboratory_hours = sum(item.laboratory_hours for item in assignments)
    preparation_count = len({item.course_code.strip().casefold() for item in assignments})
    regular_weekly_hours = 21 if preparation_count <= 2 else 18
    total_weekly_hours = total_lecture_hours + total_laboratory_hours
    calculated_overload_hours = max(total_weekly_hours - regular_weekly_hours, 0)
    overload_weekly_hours = (
        workload.imported_overload_hours
        if workload.imported_overload_hours is not None
        else calculated_overload_hours
    )
    compensation_category, compensation_hourly_rate, estimated_teaching_pay_weekly = (
        calculate_teaching_cost(
            workload, faculty, total_weekly_hours, overload_weekly_hours, settings
        )
    )
    projection_weeks = weeks_for_term(workload.term, settings)
    approval_snapshot = None
    if workload.approval_snapshot:
        try:
            approval_snapshot = json.loads(workload.approval_snapshot)
        except json.JSONDecodeError:
            approval_snapshot = None
    return FacultyWorkloadRead(
        imported_overload_hours=workload.imported_overload_hours,
        calculated_overload_hours=calculated_overload_hours,
        overload_difference=workload.imported_overload_hours is not None
        and abs(overload_weekly_hours - calculated_overload_hours) > 0.01,
        import_provenance=workload.import_provenance,
        id=workload.id,
        revision=workload.revision,
        data_source=workload.data_source,
        faculty_profile_id=faculty.id,
        faculty_name=faculty.name,
        college=faculty.college,
        department=faculty.department,
        rank=faculty.rank,
        academic_year=workload.academic_year,
        term=workload.term,
        remarks=workload.remarks,
        compensation_category=compensation_category,
        highest_qualification=workload.highest_qualification,
        professional_qualification=workload.professional_qualification,
        professional_qualification_other=workload.professional_qualification_other,
        workflow_status=workload.workflow_status,
        reviewed_at=workload.reviewed_at,
        reviewed_by=workload.reviewed_by,
        approved_at=workload.approved_at,
        approved_by=workload.approved_by,
        approval_snapshot=approval_snapshot,
        reopened_at=workload.reopened_at,
        reopened_by=workload.reopened_by,
        reopen_reason=workload.reopen_reason,
        assignments=assignments,
        total_lecture_hours=total_lecture_hours,
        total_laboratory_hours=total_laboratory_hours,
        total_weekly_hours=total_weekly_hours,
        preparation_count=preparation_count,
        regular_weekly_hours=regular_weekly_hours,
        overload_weekly_hours=overload_weekly_hours,
        estimated_overload_pay_weekly=overload_weekly_hours
        * ((faculty.monthly_salary or 0) * 12 * 0.000781),
        compensation_hourly_rate=compensation_hourly_rate,
        estimated_teaching_pay_weekly=estimated_teaching_pay_weekly,
        projection_weeks=projection_weeks,
        estimated_teaching_pay_term=(
            estimated_teaching_pay_weekly * projection_weeks if projection_weeks else None
        ),
        created_at=workload.created_at,
    )
