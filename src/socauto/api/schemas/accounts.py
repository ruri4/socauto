"""Public destination-account API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from socauto.db.models import AccountPlatform, AccountStatus


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: AccountPlatform
    platform_user_id: str | None
    handle: str | None
    status: AccountStatus
    created_at: datetime
    updated_at: datetime


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int
    offset: int
    limit: int
