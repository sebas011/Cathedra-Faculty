"""Versioned saved estimates and explicit failures for unreadable frozen records."""

import json
import math

from fastapi import HTTPException
from pydantic import ValidationError

from app.expense_schemas import MonthlySalaryProjectionRead

PROJECTION_SCHEMA_VERSION = 1


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def _json_object(payload: str) -> dict:
    value = json.loads(payload, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("Snapshot must be an object")
    return value


def _finite_values(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Snapshot contains non-finite numbers")
    if isinstance(value, dict):
        for item in value.values():
            _finite_values(item)
    elif isinstance(value, list):
        for item in value:
            _finite_values(item)


def dump_projection(projection: MonthlySalaryProjectionRead) -> str:
    # Retain the original top-level fields so an older compatible release can
    # still read a backup. Its Pydantic reader ignores this additive marker.
    return json.dumps(
        {
            **projection.model_dump(mode="json"),
            "schema_version": PROJECTION_SCHEMA_VERSION,
        },
        allow_nan=False,
    )


def load_projection(payload: str, *, record_id: int) -> MonthlySalaryProjectionRead:
    try:
        saved = _json_object(payload)
        if "schema_version" in saved:
            version = saved["schema_version"]
            if type(version) is not int or version != PROJECTION_SCHEMA_VERSION:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saved estimate #{record_id} uses an unsupported format version. Open it with a compatible app version.",
                )
            # Also accept the nested envelope from the initial audit patch.
            # New writes keep the historical top-level shape for older readers.
            if "projection" in saved:
                saved = saved["projection"]
        # Unversioned snapshots are the original format. Existing model defaults
        # cover optional additions; missing required financial data is never invented.
        projection = MonthlySalaryProjectionRead.model_validate(saved)
        _finite_values(projection.model_dump())
        return projection
    except (ValueError, TypeError, KeyError, RecursionError, ValidationError) as caught:
        raise HTTPException(
            status_code=409,
            detail=f"Saved estimate #{record_id} is unreadable or incompatible. Preserve it and restore a verified backup or open it with a compatible app version.",
        ) from caught


def load_approval_snapshot(payload: str, *, label: str) -> dict:
    try:
        snapshot = _json_object(payload)
        if not isinstance(snapshot.get("faculty"), dict) or not isinstance(
            snapshot.get("workload"), dict
        ):
            raise ValueError("Approval is missing frozen faculty or workload data")
        if "schema_version" in snapshot and (
            type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
        ):
            raise ValueError("Unsupported approval format version")
        frozen = snapshot["workload"]
        for field in (
            "total_weekly_hours",
            "overload_weekly_hours",
            "estimated_teaching_pay_weekly",
            "estimated_teaching_pay_term",
        ):
            value = frozen[field]
            if value is None and field != "estimated_teaching_pay_term":
                raise ValueError(f"Missing frozen number: {field}")
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid frozen number: {field}")
        _finite_values(snapshot)
        return snapshot
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as caught:
        raise HTTPException(
            status_code=409,
            detail=f"{label} is unreadable. Preserve the frozen record and restore a verified backup before relying on it.",
        ) from caught
