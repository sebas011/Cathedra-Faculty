from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session


def require_new_revision(expected_revision: int | None) -> None:
    if expected_revision is None:
        raise HTTPException(status_code=428, detail="Reload this record before saving changes.")
    if expected_revision != 0:
        raise HTTPException(status_code=409, detail="This record changed. Reload before saving.")


def advance_revision(
    db: Session, model: type, record_id: int, expected_revision: int | None
) -> None:
    if expected_revision is None:
        raise HTTPException(status_code=428, detail="Reload this record before saving changes.")
    result = db.execute(
        update(model)
        .where(model.id == record_id, model.revision == expected_revision)
        .values(revision=model.revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="This record changed in another window. Review the latest version before saving.",
        )
