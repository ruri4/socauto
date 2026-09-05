"""Durable publication job persistence."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, Enum, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from socauto.db.types import UTCDateTime, utc_now


class SourcePlatform(StrEnum):
    X = "x"


class DestinationPlatform(StrEnum):
    TIKTOK = "tiktok"


class JobState(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    UPLOADING = "uploading"
    POSTED = "posted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SQLModel, table=True):
    __tablename__: ClassVar[str] = "jobs"
    __table_args__ = (
        UniqueConstraint("destination_account_id", "canonical_url", name="uq_jobs_destination_url"),
        CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count"),
        Index("ix_jobs_account", "destination_account_id"),
        Index("ix_jobs_queue", "state", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_url: str = Field(max_length=2048)
    canonical_url: str = Field(max_length=2048)
    source_platform: SourcePlatform = Field(
        default=SourcePlatform.X,
        sa_column=Column(
            Enum(
                SourcePlatform,
                name="source_platform",
                native_enum=False,
                values_callable=lambda items: [item.value for item in items],
            ),
            nullable=False,
        ),
    )
    destination_platform: DestinationPlatform = Field(
        default=DestinationPlatform.TIKTOK,
        sa_column=Column(
            Enum(
                DestinationPlatform,
                name="destination_platform",
                native_enum=False,
                values_callable=lambda items: [item.value for item in items],
            ),
            nullable=False,
        ),
    )
    destination_account_id: UUID = Field(
        foreign_key="accounts.id",
        ondelete="RESTRICT",
    )
    caption_override: str | None = Field(default=None, max_length=2200)
    state: JobState = Field(
        default=JobState.PENDING,
        sa_column=Column(
            Enum(
                JobState,
                name="job_state",
                native_enum=False,
                values_callable=lambda items: [item.value for item in items],
            ),
            nullable=False,
            server_default=JobState.PENDING.value,
        ),
    )
    attempt_count: int = Field(default=0, ge=0)
    worker_id: str | None = Field(default=None, max_length=128)
    claimed_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    lease_expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    cancel_requested_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)
    posted_url: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    finished_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
