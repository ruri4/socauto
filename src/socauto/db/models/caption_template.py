"""Reusable caption-template persistence."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from socauto.db.types import UTCDateTime, utc_now


class CaptionTemplate(SQLModel, table=True):
    __tablename__: ClassVar[str] = "caption_templates"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(
        sa_column=Column(String(80, collation="NOCASE"), unique=True, nullable=False),
    )
    body: str = Field(max_length=2200)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(UTCDateTime(), nullable=False),
    )
