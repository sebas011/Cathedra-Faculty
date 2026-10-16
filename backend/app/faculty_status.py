from datetime import date

from app.models import FacultyProfile

KNOWN_TERM_STARTS = {
    ("2026-2027", "First Semester"): date(2026, 8, 12),
    ("2026-2027", "Second Semester"): date(2027, 1, 13),
    ("2026-2027", "Summer"): date(2027, 6, 14),
}


def normalized_term(term: str) -> str:
    return {"1st Semester": "First Semester", "2nd Semester": "Second Semester"}.get(
        term.strip(), term.strip()
    )


def workload_status_conflict(
    profile: FacultyProfile, academic_year: str, term: str, as_of: date
) -> bool:
    if profile.service_status not in ("Inactive", "Retired", "Resigned"):
        return False
    effective_date = profile.service_status_effective_date
    if effective_date is None or effective_date <= as_of:
        return True
    return workload_term_status_conflict(profile, academic_year, term)


def workload_term_status_conflict(profile: FacultyProfile, academic_year: str, term: str) -> bool:
    """Check the teaching period, allowing eligible historical corrections."""
    if profile.service_status not in ("Inactive", "Retired", "Resigned"):
        return False
    effective_date = profile.service_status_effective_date
    if effective_date is None:
        return True
    canonical_term = normalized_term(term)
    known_start = KNOWN_TERM_STARTS.get((academic_year.strip(), canonical_term))
    if known_start is not None:
        return effective_date <= known_start
    try:
        start_year, end_year = map(int, academic_year.strip().split("-"))
    except ValueError:
        return False
    term_year = start_year if canonical_term == "First Semester" else end_year
    return effective_date.year < term_year


def term_status_transition(
    profile: FacultyProfile, academic_year: str | None, term: str | None
) -> bool:
    effective_date = profile.service_status_effective_date
    if effective_date is None or academic_year is None or term is None:
        return False
    canonical_term = normalized_term(term)
    known_start = KNOWN_TERM_STARTS.get((academic_year, canonical_term))
    if known_start is not None:
        return effective_date > known_start and effective_date.year == known_start.year
    try:
        start_year, end_year = map(int, academic_year.split("-"))
    except ValueError:
        return False
    term_year = start_year if canonical_term == "First Semester" else end_year
    return effective_date.year == term_year


def planning_status(profile: FacultyProfile, as_of: date) -> str:
    if profile.service_status == "To verify":
        return "provisional"
    if profile.service_status == "Active":
        return "included"
    if profile.service_status_effective_date is None:
        return "provisional"
    return "excluded" if profile.service_status_effective_date <= as_of else "included"
