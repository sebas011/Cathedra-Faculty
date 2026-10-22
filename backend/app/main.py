import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select

import app.activity_audit
from app.api.activity import router as activity_router
from app.api.auth import router as auth_router
from app.api.closeout import router as closeout_router
from app.api.expenses import router as expenses_router
from app.api.faculty_profiles import router as faculty_profiles_router
from app.api.google_sheets import router as google_sheets_router
from app.api.maintenance import router as maintenance_router
from app.api.qualification_rates import router as qualification_rates_router
from app.api.verification import router as verification_router
from app.api.workload import router as workload_router
from app.auth import require_admin, require_signed_in
from app.bootstrap import SetupCapability
from app.db import DB_PATH, Base, engine
from app.db import SessionLocal as SessionLocal
from app.local_host import LocalHostMiddleware
from app.migrations import run_migrations, validate_migration_history
from app.models import LocalUser
from app.product import PRODUCT, PRODUCT_NAME, bind_empty_database
from app.request_gate import RestoreGateMiddleware, RestoreRequestGate
from app.request_timing import SlowRequestMiddleware
from app.restore_recovery import recover_interrupted_restore
from app.security_headers import SecurityHeadersMiddleware
from app.version import build_identity, release_version


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    recover_interrupted_restore(DB_PATH, DB_PATH.parent / "backups")
    with engine.connect() as connection:
        validate_migration_history(connection)
    with engine.begin() as connection:
        bind_empty_database(connection)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        run_migrations(connection)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.restore_request_gate = RestoreRequestGate()
    application.state.authorize_restore = authorize_restore
    application.state.setup_capability = None
    try:
        initialize_database()
        with SessionLocal() as db:
            setup_required = (db.scalar(select(func.count()).select_from(LocalUser)) or 0) == 0
        if setup_required:
            application.state.setup_capability = SetupCapability(
                DB_PATH.parent, os.environ.get("CATHEDRA_SETUP_ORIGIN", "http://127.0.0.1:8102")
            )
        yield
    finally:
        if application.state.setup_capability is not None:
            application.state.setup_capability.consume()
        engine.dispose()


def authorize_restore(request: Request) -> None:
    with SessionLocal() as db:
        require_admin(require_signed_in(request, request.headers.get("Authorization"), db))


app = FastAPI(title=f"{PRODUCT_NAME} API", version=release_version(), lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{host}:{port}"
        for host in ("127.0.0.1", "localhost")
        for port in (5173, 5174, 5175)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RestoreGateMiddleware)
app.add_middleware(SlowRequestMiddleware)
app.add_middleware(LocalHostMiddleware)

app.add_middleware(SecurityHeadersMiddleware)


@app.get("/api/v1/health")
def health(request: Request) -> dict[str, str | bool]:
    directory_identity = hashlib.sha256(
        str(DB_PATH.parent.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]
    return {
        "status": "ok",
        "product": PRODUCT,
        "release_version": release_version(),
        "build_identity": build_identity(),
        "data_directory_identity": directory_identity,
        "desktop_mode": getattr(request.app.state, "shutdown_signal", None) is not None,
    }


@app.post("/api/v1/desktop/exit", dependencies=[Depends(require_admin)])
def exit_desktop(request: Request) -> dict[str, str]:
    shutdown_signal = getattr(request.app.state, "shutdown_signal", None)
    if shutdown_signal is None:
        raise HTTPException(
            status_code=409, detail="Exit Cathedra is available only in the desktop app."
        )
    shutdown_signal.set()
    return {"status": "closing"}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(
    faculty_profiles_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)]
)
app.include_router(workload_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])
app.include_router(maintenance_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])
app.include_router(google_sheets_router, prefix="/api/v1")
app.include_router(expenses_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])
app.include_router(closeout_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])
app.include_router(activity_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])
app.include_router(
    qualification_rates_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)]
)
app.include_router(verification_router, prefix="/api/v1", dependencies=[Depends(require_signed_in)])

_default_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_DIST = Path(os.environ.get("CATHEDRA_FRONTEND_DIST", _default_frontend_dist)).resolve()
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str) -> FileResponse:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found.")
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=404, detail="Frontend assets have not been built.")
    requested_file = (FRONTEND_DIST / path).resolve()
    if FRONTEND_DIST in requested_file.parents and requested_file.is_file():
        return FileResponse(requested_file)
    return FileResponse(FRONTEND_INDEX)
