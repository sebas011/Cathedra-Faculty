import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity_audit import add_activity
from app.auth import require_admin
from app.db import get_db
from app.models import LocalUser, QualificationRateDraft
from app.qualification_schemas import QualificationDraftInput, QualificationDraftRead

router = APIRouter(prefix="/qualification-rates", tags=["Qualification Rate Settings"])


def read_draft(db: Session) -> QualificationDraftRead:
    draft = db.get(QualificationRateDraft, 1)
    if draft is None:
        return QualificationDraftRead()
    return QualificationDraftRead(
        revision=draft.revision,
        combination_rule=draft.combination_rule,
        rates=json.loads(draft.rates_json),
        updated_by=draft.updated_by,
        updated_at=draft.updated_at,
    )


@router.get("/draft", response_model=QualificationDraftRead)
def get_draft(
    db: Annotated[Session, Depends(get_db)], user: Annotated[LocalUser, Depends(require_admin)]
):
    return read_draft(db)


@router.put("/draft", response_model=QualificationDraftRead)
def save_draft(
    payload: QualificationDraftInput,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[LocalUser, Depends(require_admin)],
):
    values = {
        "revision": payload.revision + 1,
        "combination_rule": payload.combination_rule,
        "rates_json": json.dumps([rate.model_dump(mode="json") for rate in payload.rates]),
        "updated_by": user.username,
        "updated_at": datetime.now(),
    }
    conflict = "These draft settings changed in another window. Reload the saved draft before editing again."
    if payload.revision == 0:
        db.add(QualificationRateDraft(id=1, **values))
        try:
            db.commit()
        except IntegrityError as caught:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict) from caught
    else:
        result = db.execute(
            update(QualificationRateDraft)
            .where(
                QualificationRateDraft.id == 1,
                QualificationRateDraft.revision == payload.revision,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict)
        add_activity(
            db,
            "Qualification Rates",
            "Updated Qualification Rates #1",
            record_type="qualification_rate_drafts",
            record_id=1,
            operation="Updated",
            changed_fields=["combination_rule", "rates"],
        )
        db.commit()
    db.expire_all()
    return read_draft(db)
