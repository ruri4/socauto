"""Frontend-facing job contracts, independent of storage and worker leases."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from socauto.db.models.job import (
    DestinationPlatform,
    JobCaptionMode,
    JobState,
    JobVisibility,
    SourcePlatform,
)
from socauto.services.caption_templates import CaptionTemplateError, validate_template_body
from socauto.sources.x import canonicalize_x_url


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1, max_length=2048)
    destination_account_id: UUID
    caption_override: str | None = Field(default=None, max_length=2200)
    caption_mode: JobCaptionMode | None = None
    caption_template_id: UUID | None = None
    caption_template: str | None = Field(default=None, max_length=2200)
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

    @field_validator("caption_template")
    @classmethod
    def template_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_template_body(value)
        except CaptionTemplateError as error:
            raise ValueError("invalid caption template") from error

    @field_validator("caption_mode", mode="before")
    @classmethod
    def strict_caption_mode(cls, value: object) -> JobCaptionMode | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("caption_mode is invalid")
        try:
            return JobCaptionMode(value)
        except ValueError:
            raise ValueError("caption_mode is invalid") from None

    @field_validator("visibility", mode="before")
    @classmethod
    def strict_visibility(cls, value: object) -> JobVisibility:
        if not isinstance(value, str):
            raise ValueError("visibility must be private or public")
        try:
            return JobVisibility(value)
        except ValueError:
            raise ValueError("visibility must be private or public") from None

    @model_validator(mode="after")
    def caption_inputs(self) -> JobCreate:
        if self.caption_mode is None:
            if "caption_mode" in self.model_fields_set:
                raise ValueError("caption_mode cannot be null")
            if self.caption_template_id is not None or self.caption_template is not None:
                raise ValueError("template inputs require an explicit template mode")
            self.caption_mode = (
                JobCaptionMode.OVERRIDE
                if self.caption_override is not None
                else JobCaptionMode.SOURCE
            )
        if self.caption_mode is JobCaptionMode.SOURCE:
            if any(
                value is not None
                for value in (
                    self.caption_override,
                    self.caption_template_id,
                    self.caption_template,
                )
            ):
                raise ValueError("source caption mode does not accept caption inputs")
        elif self.caption_mode is JobCaptionMode.OVERRIDE:
            if self.caption_override is None or any(
                value is not None for value in (self.caption_template_id, self.caption_template)
            ):
                raise ValueError("override caption mode requires only caption_override")
        elif self.caption_mode is JobCaptionMode.SAVED_TEMPLATE:
            if self.caption_template_id is None or any(
                value is not None for value in (self.caption_override, self.caption_template)
            ):
                raise ValueError("saved template mode requires only caption_template_id")
        elif (
            self.caption_template_id is not None
            or self.caption_template is None
            or self.caption_override is not None
        ):
            raise ValueError("custom template mode requires only caption_template")
        return self


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
    caption_mode: JobCaptionMode
    caption_template_id: UUID | None
    caption_template_name_snapshot: str | None
    caption_template_body_snapshot: str | None
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
