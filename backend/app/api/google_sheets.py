"""Administrator-controlled export to a user-selected Google spreadsheet."""

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.api.maintenance import maintenance_activity
from app.auth import require_admin
from app.db import get_db
from app.services.google_sheets import (
    GoogleSheetsError,
    GoogleSheetsService,
    get_google_sheets_service,
)
from app.services.sheets_exports import build_google_sheet_tables


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's normal validation body echoes invalid input. A malformed
                # key object must not return credential material to the browser.
                raise HTTPException(
                    status_code=422,
                    detail="The Google Sheets request is invalid. Review the sheet link and choose a valid service account JSON key file.",
                ) from None

        return sanitized_handler


router = APIRouter(
    prefix="/maintenance/google-sheets",
    tags=["Google Sheets"],
    dependencies=[Depends(require_admin)],
    route_class=PrivateValidationRoute,
)


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_url: str = Field(min_length=20, max_length=500)
    service_account_json: SecretStr | None = None


class SyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str = Field(pattern=r"^[A-Za-z0-9_-]{20,200}$")


def execute(operation):
    try:
        return operation()
    except GoogleSheetsError as caught:
        raise HTTPException(status_code=caught.status_code, detail=caught.message) from None


@router.get("")
def connection_status(service: GoogleSheetsService = Depends(get_google_sheets_service)):
    return execute(service.status)


@router.put("")
def configure_connection(
    payload: ConnectionInput,
    service: GoogleSheetsService = Depends(get_google_sheets_service),
    db: Session = Depends(get_db),
):
    credential = (
        payload.service_account_json.get_secret_value()
        if payload.service_account_json is not None
        else None
    )
    if credential is not None and len(credential.encode("utf-8")) > 65_536:
        raise HTTPException(
            status_code=422, detail="Choose a service account JSON key smaller than 64 KiB."
        )
    maintenance_activity(db, "Requested Google Sheets connection change", "Requested")
    result = execute(lambda: service.configure(payload.spreadsheet_url, credential))
    maintenance_activity(db, "Completed Google Sheets connection change", "Completed")
    return result


@router.post("/test")
def test_connection(service: GoogleSheetsService = Depends(get_google_sheets_service)):
    return execute(service.test_connection)


@router.post("/sync")
def update_sheet(
    payload: SyncInput,
    service: GoogleSheetsService = Depends(get_google_sheets_service),
    db: Session = Depends(get_db),
):
    maintenance_activity(db, "Requested Google Sheets update", "Requested")
    try:
        # Python's legacy sqlite transaction mode does not BEGIN on SELECT.
        # Hold one explicit read snapshot, then release it before network IO.
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        tables = build_google_sheet_tables(db)
        db.rollback()
        result = execute(
            lambda: service.update(tables, expected_spreadsheet_id=payload.spreadsheet_id)
        )
    except Exception:
        db.rollback()
        maintenance_activity(db, "Failed or unconfirmed Google Sheets update", "Failed")
        raise
    try:
        maintenance_activity(db, "Completed Google Sheets update", "Completed")
    except HTTPException:
        # Google already committed. Do not misreport it as an unsuccessful export.
        result["message"] = (
            "Google Sheet updated, but local completion activity could not be recorded."
        )
    return result


@router.delete("")
def disconnect(
    service: GoogleSheetsService = Depends(get_google_sheets_service), db: Session = Depends(get_db)
):
    maintenance_activity(db, "Requested Google Sheets disconnection", "Requested")
    result = execute(service.disconnect)
    maintenance_activity(db, "Completed Google Sheets disconnection", "Completed")
    return result


@router.get("/setup-guide")
def setup_guide():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    guide = root / "docs" / "GOOGLE_SHEETS_SETUP.md"
    if not guide.is_file():
        raise HTTPException(
            status_code=503,
            detail="The setup guide is missing. Reinstall the complete application package.",
        )
    return FileResponse(
        guide, media_type="text/markdown; charset=utf-8", filename="cathedra-google-sheets-setup.md"
    )
