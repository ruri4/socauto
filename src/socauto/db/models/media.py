"""Downloaded source media persistence."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column
from sqlmodel import Field, SQLModel

from socauto.db.types import UTCDateTime, utc_now


class Media(SQLModel, table=True):
    __tablename__: ClassVar[str] = "media"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_media_size"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_id: UUID = Field(
        foreign_key="jobs.id",
        ondelete="CASCADE",
        unique=True,
    )
    path: str = Field(max_length=2048)
    mime_type: str = Field(max_length=128)
    size_bytes: int = Field(ge=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
