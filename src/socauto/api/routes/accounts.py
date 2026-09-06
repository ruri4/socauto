"""TikTok credential import and account management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlmodel import Session

from socauto.api.errors import ErrorResponse
from socauto.api.schemas.accounts import (
    AccountImportResponse,
    AccountListResponse,
    AccountResponse,
    AccountSessionResponse,
)
from socauto.config import Settings
from socauto.db.engine import get_request_session
from socauto.db.models import Account, AccountStatus
from socauto.db.types import utc_now
from socauto.destinations.tiktok.account_info import (
    SessionChecker,
    TikTokSessionCheckError,
    get_session_checker,
)
from socauto.destinations.tiktok.cookies import (
    MAX_COOKIE_FILE_BYTES,
    TikTokCookieImportError,
    parse_cookie_export,
)
from socauto.destinations.tiktok.session import TikTokSessionError, TikTokSessionStore
from socauto.services.accounts import (
    AccountInUseError,
    AccountNotFoundError,
    delete_account,
    import_tiktok_account,
    list_accounts,
)

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])
Database = Annotated[Session, Depends(get_request_session)]
Checker = Annotated[SessionChecker, Depends(get_session_checker)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _check_status(code: str) -> int:
    return {
        "tiktok_session_invalid": 401,
        "tiktok_auth_rejected": 401,
        "tiktok_rate_limited": 429,
        "tiktok_network_error": 503,
        "tiktok_unavailable": 503,
    }.get(code, 502)


@router.post(
    "/tiktok/import",
    response_model=AccountImportResponse,
    responses={code: {"model": ErrorResponse} for code in (401, 413, 422, 429, 502, 503)},
    description=(
        "Import an uploaded TikTok cookie export, verify it live, and create or update the "
        "matching destination account. The original upload is not retained."
    ),
)
def import_tiktok_session(
    request: Request,
    response: Response,
    db: Database,
    checker: Checker,
    cookie_file: Annotated[
        UploadFile,
        File(alias="file", description="Netscape or browser JSON cookie export"),
    ],
    user_agent: Annotated[str | None, Form(min_length=1, max_length=512)] = None,
) -> AccountImportResponse:
    response.headers["Cache-Control"] = "no-store"
    settings: Settings = request.app.state.settings
    try:
        content = cookie_file.file.read(MAX_COOKIE_FILE_BYTES + 1)
    except OSError:
        raise _error(
            422, "tiktok_cookie_export_invalid", "TikTok cookie export is unreadable"
        ) from None
    finally:
        cookie_file.file.close()
    try:
        credentials = parse_cookie_export(content, user_agent or settings.tiktok_user_agent)
        info = checker.check(credentials)
        account = import_tiktok_account(db, settings, credentials, info)
    except TikTokCookieImportError as error:
        too_large = error.code == "tiktok_cookie_export_too_large"
        raise _error(
            413 if too_large else 422,
            error.code,
            "TikTok cookie export exceeds the 1 MiB limit"
            if too_large
            else "TikTok cookie export is invalid or lacks required publishing cookies",
        ) from None
    except TikTokSessionCheckError as error:
        raise _error(
            _check_status(error.code), error.code, "TikTok credentials could not be verified"
        ) from None
    except TikTokSessionError as error:
        raise _error(500, "session_storage_failed", "TikTok session could not be stored") from error
    return AccountImportResponse(
        account=AccountResponse.model_validate(account),
        checked_at=utc_now(),
        user=info,
    )


@router.post(
    "/{account_id}/session/validate",
    response_model=AccountSessionResponse,
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 429, 502, 503)},
    description=(
        "Ask TikTok for the authenticated user's basic identity. This does not publish, "
        "update stored cookies, or prove upload permission."
    ),
)
def validate_account_session(
    request: Request,
    response: Response,
    account_id: UUID,
    db: Database,
    checker: Checker,
) -> AccountSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    account = db.get(Account, account_id)
    if account is None:
        raise _error(404, "account_not_found", "Account not found")
    settings: Settings = request.app.state.settings
    try:
        session = TikTokSessionStore(settings).load(account.session_file)
        info = checker.check(session)
    except TikTokSessionError:
        account.status = AccountStatus.EXPIRED
        account.updated_at = utc_now()
        db.add(account)
        db.commit()
        raise _error(401, "tiktok_session_invalid", "Stored TikTok session is unusable") from None
    except TikTokSessionCheckError as error:
        status_code = _check_status(error.code)
        if status_code == 401:
            account.status = AccountStatus.EXPIRED
            account.updated_at = utc_now()
            db.add(account)
            db.commit()
        raise _error(status_code, error.code, "TikTok session could not be verified") from None
    if account.platform_user_id not in (None, info.user_id):
        raise _error(409, "account_identity_changed", "Stored session belongs to another account")
    account.platform_user_id = info.user_id
    account.handle = info.username
    account.status = AccountStatus.ACTIVE
    account.updated_at = utc_now()
    db.add(account)
    db.commit()
    return AccountSessionResponse(account_id=account_id, checked_at=utc_now(), user=info)


@router.get("", response_model=AccountListResponse)
def get_accounts(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AccountListResponse:
    accounts, total = list_accounts(db, offset=offset, limit=limit)
    return AccountListResponse(
        items=[AccountResponse.model_validate(account) for account in accounts],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_account(request: Request, account_id: UUID, db: Database) -> Response:
    settings: Settings = request.app.state.settings
    try:
        delete_account(db, settings, account_id)
    except AccountNotFoundError as error:
        raise _error(404, "account_not_found", "Account not found") from error
    except AccountInUseError as error:
        raise _error(409, "account_in_use", "Account is referenced by existing jobs") from error
    except TikTokSessionError as error:
        raise _error(
            500, "session_storage_failed", "TikTok session could not be removed"
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
