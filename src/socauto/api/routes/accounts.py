"""TikTok account authentication and account management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from socauto.api.schemas.accounts import AccountListResponse, AccountResponse
from socauto.config import Settings
from socauto.db.engine import get_request_session
from socauto.destinations.tiktok.auth import (
    TikTokAuthenticator,
    TikTokAuthTimeoutError,
    TikTokAuthUnavailableError,
    get_tiktok_authenticator,
)
from socauto.destinations.tiktok.session import TikTokSessionError
from socauto.services.accounts import (
    AccountInUseError,
    AccountNotFoundError,
    create_tiktok_account,
    delete_account,
    list_accounts,
)

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])
Database = Annotated[Session, Depends(get_request_session)]
Authenticator = Annotated[TikTokAuthenticator, Depends(get_tiktok_authenticator)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.post(
    "/tiktok/auth",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def authenticate_tiktok(
    request: Request,
    db: Database,
    authenticator: Authenticator,
) -> AccountResponse:
    settings: Settings = request.app.state.settings
    try:
        authenticated_session = authenticator.authenticate()
        account = create_tiktok_account(db, settings, authenticated_session)
    except TikTokAuthTimeoutError as error:
        raise _error(
            504, "tiktok_auth_timeout", "TikTok login was not completed in time"
        ) from error
    except TikTokAuthUnavailableError as error:
        raise _error(
            503, "tiktok_auth_unavailable", "TikTok login browser is unavailable"
        ) from error
    except TikTokSessionError as error:
        raise _error(500, "session_storage_failed", "TikTok session could not be stored") from error
    return AccountResponse.model_validate(account)


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
