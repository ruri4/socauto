"""Frontend-facing job contracts, independent of storage and worker leases."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from socauto.db.models.job import DestinationPlatform, JobState, JobVisibility, SourcePlatform
from socauto.sources.x import canonicalize_x_url


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1, max_length=2048)
    destination_account_id: UUID
    caption_override: str | None = Field(default=None, max_length=2200)
    visibility: JobVisibility = Field(default=JobVisibility.PRIVATE)

    @field_validator("source_url")
    @classmethod
    def supported_url(cls, value: str) -> str:
        value.encode("utf-8")
        canonicalize_x_url(value)
        return value

    @field_validator("caption_override")
    @classmethod
    def caption_length(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-16-le")) // 2 > 2200:
            raise ValueError("caption exceeds 2200 UTF-16 code units")
        return value

    @field_validator("visibility", mode="before")
    @classmethod
    def strict_visibility(cls, value: object) -> JobVisibility:
        if not isinstance(value, str):
            raise ValueError("visibility must be private or public")
        try:
            return JobVisibility(value)
        except ValueError:
            raise ValueError("visibility must be private or public") from None


class JobRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge_duplicate_risk: bool = Field(default=False, strict=True)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_url: str
    canonical_url: str
    source_platform: SourcePlatform
    destination_platform: DestinationPlatform
    destination_account_id: UUID
    caption_override: str | None
    resolved_caption: str | None
    visibility: JobVisibility
    state: JobState = Field(description="posted means acknowledged, not confirmed visibility")
    attempt_count: int
    cancel_requested_at: datetime | None
    error_code: str | None
    creation_id: str | None
    video_id: str | None
    post_id: str | None
    posted_url: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    offset: int
    limit: int
