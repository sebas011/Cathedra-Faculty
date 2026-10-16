import json
import math

COLLEGE_ORDER = ("CAS", "COEd", "CBMA", "COE", "COF", "CIT", "CCS", "CCJ")


def teaching_allocations(workload, faculty, item):
    paid_hours = (
        item.overload_weekly_hours
        if item.compensation_category == "Regular Faculty"
        else item.total_weekly_hours
    )
    components = {faculty.college: paid_hours}
    basis = "Home college (no confirmed split)"
    warning = None
    try:
        provenance = json.loads(workload.import_provenance or "{}")
        resolution = provenance.get("confirmed_course_resolution", {})
        if "overload_components" in resolution:
            raw_components = resolution["overload_components"]
            if (
                item.compensation_category != "Regular Faculty"
                or not isinstance(raw_components, list)
                or not raw_components
            ):
                raise ValueError("Invalid allocation")
            confirmed = {}
            colleges = {code.casefold(): code for code in COLLEGE_ORDER}
            for component in raw_components:
                code = colleges[component["college"].strip().casefold()]
                hours = component["hours"]
                if (
                    isinstance(hours, bool)
                    or not isinstance(hours, (int, float))
                    or not math.isfinite(hours)
                    or hours < 0
                ):
                    raise ValueError("Invalid hours")
                confirmed[code] = confirmed.get(code, 0) + hours
            if not math.isclose(sum(confirmed.values()), paid_hours, rel_tol=0, abs_tol=0.000001):
                raise ValueError("Allocation does not match payable hours")
            if paid_hours > 0:
                components = {code: hours for code, hours in confirmed.items() if hours > 0}
                basis = "Confirmed teaching college allocation"
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        warning = f"{faculty.name}: college allocation could not be verified; teaching cost remains under the home college pending review."
    allocations = []
    for code, hours in components.items():
        last = len(allocations) == len(components) - 1
        share = hours / paid_hours if paid_hours else 1
        weekly_pay = (
            item.estimated_teaching_pay_weekly - sum(entry["weekly_pay"] for entry in allocations)
            if last
            else item.estimated_teaching_pay_weekly * share
        )
        term_pay = None
        if item.estimated_teaching_pay_term is not None:
            term_pay = (
                item.estimated_teaching_pay_term - sum(entry["term_pay"] for entry in allocations)
                if last
                else item.estimated_teaching_pay_term * share
            )
        allocations.append(
            {"college": code, "paid_hours": hours, "weekly_pay": weekly_pay, "term_pay": term_pay}
        )
    return allocations, basis, warning
