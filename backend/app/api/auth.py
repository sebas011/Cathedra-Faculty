from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity_audit import add_activity
from app.auth import (
    PASSWORD_ITERATIONS,
    create_session,
    password_hash,
    require_admin,
    require_signed_in,
    token_digest,
    verify_password,
)
from app.db import get_db
from app.login_throttle import login_throttle
from app.models import LocalSession, LocalUser

router = APIRouter(prefix="/auth", tags=["Local Accounts"])
_dummy_password_hash = password_hash("unusable-" + __import__("secrets").token_urlsafe(32))


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserCreate(Credentials):
    role: str = Field(pattern="^(admin|staff)$")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=10, max_length=200)


def user_data(user: LocalUser) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
    }


def session_data(db: Session, user: LocalUser) -> dict[str, object]:
    return {"token": create_session(db, user), "user": user_data(user)}


@router.get("/status")
def account_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"setup_required": (db.scalar(select(func.count()).select_from(LocalUser)) or 0) == 0}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup_first_admin(
    payload: Credentials, request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    try:
        # Acquire SQLite's write lock before checking bootstrap eligibility.
        db.execute(text("BEGIN IMMEDIATE"))
        if (db.scalar(select(func.count()).select_from(LocalUser)) or 0) != 0:
            raise HTTPException(
                status_code=409, detail="An administrator account has already been set up."
            )
        capability = getattr(request.app.state, "setup_capability", None)
        if capability is None:
            raise HTTPException(status_code=403, detail="Close and reopen Cathedra to begin setup.")
        capability.require(request)
        user = LocalUser(
            username=payload.username.strip(),
            password_hash=password_hash(payload.password),
            role="admin",
        )
        db.add(user)
        db.commit()
        capability.consume()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return session_data(db, user)


@router.post("/login")
def login(
    payload: Credentials, request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    login_throttle.check(payload.username, request.client.host if request.client else "local")
    user = db.scalar(
        select(LocalUser).where(
            func.lower(LocalUser.username) == func.lower(payload.username.strip())
        )
    )
    stored = user.password_hash if user else _dummy_password_hash
    valid = verify_password(payload.password, stored)
    if user is None or not user.is_active or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect."
        )
    if int(user.password_hash.split("$", 3)[1]) < PASSWORD_ITERATIONS:
        user.password_hash = password_hash(payload.password)
    return session_data(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_signed_in),
) -> None:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    db.query(LocalSession).filter(LocalSession.token_hash == token_digest(token)).delete()
    db.commit()


@router.get("/me")
def current_user(user: LocalUser = Depends(require_signed_in)) -> dict[str, object]:
    return user_data(user)


@router.get("/users")
def list_users(
    db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> list[dict[str, object]]:
    return [
        user_data(user) for user in db.scalars(select(LocalUser).order_by(LocalUser.username)).all()
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> dict[str, object]:
    username = payload.username.strip()
    if db.scalar(select(LocalUser).where(func.lower(LocalUser.username) == func.lower(username))):
        raise HTTPException(status_code=409, detail="That username is already in use.")
    user = LocalUser(
        username=username,
        password_hash=password_hash(payload.password),
        role=payload.role,
        must_change_password=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as caught:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.") from caught
    db.refresh(user)
    return user_data(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: LocalUser = Depends(require_signed_in),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Your current password is incorrect."
        )
    user.password_hash = password_hash(payload.new_password)
    user.must_change_password = False
    db.query(LocalSession).filter(LocalSession.user_id == user.id).delete()
    db.commit()


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
) -> None:
    user = db.get(LocalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Local account not found.")
    user.password_hash = password_hash(payload.new_password)
    user.must_change_password = True
    db.query(LocalSession).filter(LocalSession.user_id == user.id).delete()
    db.commit()


class AccountStatusUpdate(BaseModel):
    active: bool


@router.put("/users/{user_id}/status")
def set_account_status(
    user_id: int,
    payload: AccountStatusUpdate,
    db: Session = Depends(get_db),
    _: LocalUser = Depends(require_admin),
) -> dict[str, object]:
    user = db.get(LocalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Local account not found.")
    statement = (
        update(LocalUser)
        .where(LocalUser.id == user_id, LocalUser.is_active.is_(not payload.active))
        .values(is_active=payload.active)
    )
    if not payload.active:
        administrators = (
            select(func.count())
            .select_from(LocalUser)
            .where(LocalUser.role == "admin", LocalUser.is_active.is_(True))
            .scalar_subquery()
        )
        statement = statement.where(or_(LocalUser.role != "admin", administrators > 1))
    result = db.execute(statement)
    db.refresh(user)
    if result.rowcount != 1 and user.is_active != payload.active:
        raise HTTPException(
            status_code=409, detail="The last active administrator cannot be disabled."
        )
    if result.rowcount == 1:
        add_activity(
            db,
            "Local Accounts",
            "Enabled Local Accounts" if payload.active else "Disabled Local Accounts",
            record_type="local_users",
            record_id=user_id,
            operation="Updated",
            changed_fields=["is_active"],
        )
    if not payload.active:
        db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    db.commit()
    return user_data(user)


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: int, db: Session = Depends(get_db), _: LocalUser = Depends(require_admin)
) -> None:
    if db.get(LocalUser, user_id) is None:
        raise HTTPException(status_code=404, detail="Local account not found.")
    db.query(LocalSession).filter(LocalSession.user_id == user_id).delete()
    add_activity(
        db,
        "Local Accounts",
        f"Revoked Local Accounts sessions #{user_id}",
        record_type="local_users",
        record_id=user_id,
        operation="Revoked sessions",
    )
    db.commit()
