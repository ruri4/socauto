"""Connected destination account persistence."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Column, Enum, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from socauto.db.types import UTCDateTime, utc_now


class AccountPlatform(StrEnum):
    TIKTOK = "tiktok"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


class Account(SQLModel, table=True):
    __tablename__: ClassVar[str] = "accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_accounts_platform_user"),
        Index("ix_accounts_platform_status", "platform", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    platform: AccountPlatform = Field(
        default=AccountPlatform.TIKTOK,
        sa_column=Column(
            Enum(
                AccountPlatform,
                name="account_platform",
                native_enum=False,
                values_callable=lambda items: [item.value for item in items],
            ),
            nullable=False,
        ),
    )
    platform_user_id: str | None = Field(default=None, max_length=128)
    handle: str | None = Field(default=None, max_length=128)
    session_file: str = Field(max_length=1024, unique=True)
    status: AccountStatus = Field(
        default=AccountStatus.ACTIVE,
        sa_column=Column(
            Enum(
                AccountStatus,
                name="account_status",
                native_enum=False,
                values_callable=lambda items: [item.value for item in items],
            ),
            nullable=False,
            server_default=AccountStatus.ACTIVE.value,
        ),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
