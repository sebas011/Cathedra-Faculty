from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TeachingAssignmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)
    course_code: str = Field(min_length=1, max_length=50)
    course_title: str = Field(min_length=1, max_length=300)
    year_section: str = Field(min_length=1, max_length=120)
    lecture_hours: float = Field(default=0, ge=0, le=80)
    laboratory_hours: float = Field(default=0, ge=0, le=80)

    @model_validator(mode="after")
    def require_weekly_hours(self) -> "TeachingAssignmentInput":
        if self.lecture_hours + self.laboratory_hours <= 0:
            raise ValueError("Enter lecture or laboratory hours for each course.")
        return self


class FacultyWorkloadBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, from_attributes=True)
    faculty_profile_id: int = Field(gt=0)
    academic_year: str = Field(min_length=1, max_length=20)
    term: str = Field(min_length=1, max_length=40)
    remarks: str | None = Field(default=None, max_length=5000)
    compensation_category: Literal[
        "Regular Faculty", "Internal Part-time", "External Part-time"
    ] = "Regular Faculty"
    highest_qualification: Literal["Bachelor", "Masters", "Doctorate"] | None = None
    professional_qualification: Literal["None", "Doctor", "Lawyer", "CPA", "Other"] = "None"
    professional_qualification_other: str | None = Field(default=None, max_length=200)
    assignments: list[TeachingAssignmentInput] = Field(min_length=1, max_length=200)

    @field_validator("academic_year")
    @classmethod
    def validate_academic_year(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[0-9]{4}-[0-9]{4}", value):
            raise ValueError("Enter an academic year such as 2026-2027.")
        start, end = map(int, value.split("-"))
        if end != start + 1:
            raise ValueError("Academic year must contain consecutive years.")
        return value

    @field_validator("term")
    @classmethod
    def validate_term(cls, value: str) -> str:
        terms = {
            "first semester": "First Semester",
            "1st semester": "First Semester",
            "second semester": "Second Semester",
            "2nd semester": "Second Semester",
            "summer": "Summer",
        }
        normalized = terms.get(" ".join(value.split()).casefold())
        if normalized is None:
            raise ValueError("Choose First Semester, Second Semester, or Summer.")
        return normalized

    @field_validator("professional_qualification", mode="before")
    @classmethod
    def normalize_missing_professional_qualification(cls, value):
        return "None" if value is None or isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_other_credential(self):
        if self.professional_qualification == "Other":
            self.professional_qualification_other = (
                self.professional_qualification_other or ""
            ).strip()
            if not self.professional_qualification_other:
                raise ValueError("Specify the other professional credential.")
        else:
            self.professional_qualification_other = None
        return self


class FacultyWorkloadCreate(FacultyWorkloadBase):
    pass


class FacultyWorkloadUpdate(FacultyWorkloadBase):
    pass


class TeachingAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_code: str
    course_title: str
    year_section: str
    lecture_hours: float
    laboratory_hours: float


class FacultyWorkloadRead(BaseModel):
    imported_overload_hours: float | None = None
    calculated_overload_hours: float = 0
    overload_difference: bool = False
    import_provenance: str | None = None
    model_config = ConfigDict(from_attributes=True)

    id: int
    revision: int
    data_source: str
    faculty_profile_id: int
    faculty_name: str
    college: str
    department: str | None
    rank: str | None
    academic_year: str
    term: str
    remarks: str | None
    assignments: list[TeachingAssignmentRead]
    total_lecture_hours: float
    total_laboratory_hours: float
    total_weekly_hours: float
    preparation_count: int
    regular_weekly_hours: float
    overload_weekly_hours: float
    estimated_overload_pay_weekly: float
    compensation_category: str
    highest_qualification: str | None
    professional_qualification: str | None
    professional_qualification_other: str | None = None
    workflow_status: Literal["Draft", "Reviewed", "Approved", "Reopened"]
    reviewed_at: datetime | None
    reviewed_by: str | None
    approved_at: datetime | None
    approved_by: str | None
    approval_snapshot: dict[str, object] | None
    reopened_at: datetime | None
    reopened_by: str | None
    reopen_reason: str | None
    compensation_hourly_rate: float
    estimated_teaching_pay_weekly: float
    projection_weeks: int
    estimated_teaching_pay_term: float | None
    created_at: datetime


class WorkloadReopenRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=500)


class WorkloadCostSettingsUpdate(BaseModel):
    overload_hourly_rate: float = Field(ge=0, le=100_000)
    internal_monthly_equivalent_hours: float = Field(gt=0, le=500)
    external_base_hourly_rate: float = Field(ge=0, le=100_000)
    external_masters_increment: float = Field(ge=0, le=100_000)
    external_doctorate_increment: float = Field(ge=0, le=100_000)
    external_doctor_increment: float = Field(ge=0, le=100_000)
    external_lawyer_increment: float = Field(ge=0, le=100_000)
    first_semester_weeks: int = Field(ge=0, le=30)
    second_semester_weeks: int = Field(ge=0, le=30)
    summer_weeks: int = Field(ge=0, le=30)


class WorkloadCostSettingsRead(WorkloadCostSettingsUpdate):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime
    revision: int
