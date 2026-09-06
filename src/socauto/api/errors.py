"""Safe API errors: never echo validation input or database parameters."""

import logging
import sqlite3
from http import HTTPStatus
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorDetail(BaseModel):
    code: str
    message: str
    existing_job_id: UUID | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


def api_error(status: int, code: str, message: str, **extra: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, **extra})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": "Request parameters or body are invalid",
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail: object = error.detail
        if not isinstance(detail, dict):
            detail = {
                "code": f"http_{error.status_code}",
                "message": HTTPStatus(error.status_code).phrase,
            }
        return JSONResponse(
            status_code=error.status_code, content={"detail": detail}, headers=error.headers
        )

    @app.exception_handler(OperationalError)
    async def database_error(request: Request, error: OperationalError) -> JSONResponse:
        code = getattr(error.orig, "sqlite_errorcode", None)
        if not isinstance(code, int) or code & 0xFF not in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        }:
            raise error
        logging.getLogger(__name__).warning("database temporarily busy")
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "1"},
            content={
                "detail": {
                    "code": "database_busy",
                    "message": "Database is busy; try again shortly",
                }
            },
        )
