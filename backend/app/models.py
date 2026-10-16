from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProjectionSettings(Base):
    __tablename__ = "projection_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(40), nullable=False)


class SavedProjection(Base):
    __tablename__ = "saved_projections"
    __table_args__ = (Index("ix_saved_projections_period", "academic_year", "term", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str | None] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )
    projection_json: Mapped[str] = mapped_column(Text, nullable=False)


class SemesterCloseoutEstimate(Base):
    __tablename__ = "semester_closeout_estimates"
    __table_args__ = (UniqueConstraint("academic_year", "term"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(40), nullable=False)
    projection_id: Mapped[int] = mapped_column(
        ForeignKey("saved_projections.id"), nullable=False, unique=True
    )


class SemesterOverloadBudget(Base):
    __tablename__ = "semester_overload_budgets"
    __table_args__ = (
        UniqueConstraint("academic_year", "term"),
        CheckConstraint("amount_centavos > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_centavos: Mapped[int] = mapped_column(Integer, nullable=False)


class FacultyNoTeachingConfirmation(Base):
    __tablename__ = "faculty_no_teaching_confirmations"
    __table_args__ = (
        UniqueConstraint("faculty_id", "academic_year", "term"),
        Index(
            "ix_faculty_no_teaching_confirmations_period_faculty",
            "academic_year",
            "term",
            "faculty_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(
        ForeignKey("faculty_profiles.id"), nullable=False, index=True
    )
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(40), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False
    )


class FacultyProfile(Base):
    __tablename__ = "faculty_profiles"
    __table_args__ = (
        Index("uq_faculty_profiles_identity", "name", "college", "department", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    rank: Mapped[str] = mapped_column(String(120), nullable=False)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False)
    salary_grade: Mapped[str | None] = mapped_column(String(30))
    salary_step: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    monthly_salary: Mapped[float | None] = mapped_column()
    salary_source: Mapped[str | None] = mapped_column(Text)
    campus: Mapped[str | None] = mapped_column(String(80))
    college: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    service_status: Mapped[str] = mapped_column(
        String(20), default="Active", server_default="Active", nullable=False, index=True
    )
    service_status_effective_date: Mapped[date | None] = mapped_column(Date)
    item_number: Mapped[str | None] = mapped_column(String(100))
    bachelors_degree: Mapped[str | None] = mapped_column(String(300))
    masters_degree: Mapped[str | None] = mapped_column(String(300))
    doctoral_degree: Mapped[str | None] = mapped_column(String(300))
    eligibility: Mapped[str | None] = mapped_column(String(300))
    remarks: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(30), default="Cathedra", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class FacultyWorkload(Base):
    __tablename__ = "faculty_workloads"
    __table_args__ = (
        Index("ix_faculty_workloads_period_faculty", "academic_year", "term", "faculty_profile_id"),
        Index(
            "uq_faculty_workloads_period",
            "faculty_profile_id",
            "academic_year",
            "term",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    faculty_profile_id: Mapped[int] = mapped_column(
        ForeignKey("faculty_profiles.id"), nullable=False, index=True
    )
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    term: Mapped[str] = mapped_column(String(40), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    imported_overload_hours: Mapped[float | None] = mapped_column()
    import_provenance: Mapped[str | None] = mapped_column(Text)
    compensation_category: Mapped[str] = mapped_column(
        String(30), default="Regular Faculty", nullable=False
    )
    highest_qualification: Mapped[str | None] = mapped_column(String(30))
    professional_qualification: Mapped[str | None] = mapped_column(String(30))
    professional_qualification_other: Mapped[str | None] = mapped_column(String(200))
    workflow_status: Mapped[str] = mapped_column(String(20), default="Draft", nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approval_snapshot: Mapped[str | None] = mapped_column(Text)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime)
    reopened_by: Mapped[str | None] = mapped_column(String(80))
    reopen_reason: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(30), default="Cathedra", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    assignments: Mapped[list["TeachingAssignment"]] = relationship(
        back_populates="workload", cascade="all, delete-orphan"
    )


class TeachingAssignment(Base):
    __tablename__ = "teaching_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    workload_id: Mapped[int] = mapped_column(
        ForeignKey("faculty_workloads.id"), nullable=False, index=True
    )
    course_code: Mapped[str] = mapped_column(String(50), nullable=False)
    course_title: Mapped[str] = mapped_column(String(300), nullable=False)
    year_section: Mapped[str] = mapped_column(String(120), nullable=False)
    lecture_hours: Mapped[float] = mapped_column(default=0, nullable=False)
    laboratory_hours: Mapped[float] = mapped_column(default=0, nullable=False)
    workload: Mapped[FacultyWorkload] = relationship(back_populates="assignments")


class WorkloadApprovalRevision(Base):
    __tablename__ = "workload_approval_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workload_id: Mapped[int] = mapped_column(
        ForeignKey("faculty_workloads.id"), nullable=False, index=True
    )
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(80), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LocalUser(Base):
    __tablename__ = "local_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="staff")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (Index("uq_local_users_login_name", func.lower(username), unique=True),)


class LocalSession(Base):
    __tablename__ = "local_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("local_users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class SalaryGradeRule(Base):
    __tablename__ = "salary_grade_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    salary_grade: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    monthly_salary: Mapped[float] = mapped_column(nullable=False)
    standard_weekly_hours: Mapped[float] = mapped_column(nullable=False, default=18)
    overload_hourly_rate: Mapped[float] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkloadCostSettings(Base):
    __tablename__ = "workload_cost_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    overload_hourly_rate: Mapped[float] = mapped_column(nullable=False, default=0)
    internal_monthly_equivalent_hours: Mapped[float] = mapped_column(nullable=False, default=173.33)
    external_base_hourly_rate: Mapped[float] = mapped_column(nullable=False, default=273.77)
    external_masters_increment: Mapped[float] = mapped_column(nullable=False, default=0)
    external_doctorate_increment: Mapped[float] = mapped_column(nullable=False, default=0)
    external_doctor_increment: Mapped[float] = mapped_column(nullable=False, default=0)
    external_lawyer_increment: Mapped[float] = mapped_column(nullable=False, default=0)
    first_semester_weeks: Mapped[int] = mapped_column(nullable=False, default=18)
    second_semester_weeks: Mapped[int] = mapped_column(nullable=False, default=18)
    summer_weeks: Mapped[int] = mapped_column(nullable=False, default=6)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class QualificationRateDraft(Base):
    __tablename__ = "qualification_rate_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    combination_rule: Mapped[str] = mapped_column(String(30), nullable=False)
    rates_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_events_created_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    area: Mapped[str] = mapped_column(String(80), nullable=False)
    record_type: Mapped[str | None] = mapped_column(String(80))
    record_id: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[str | None] = mapped_column(String(40))
    changed_fields: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )
