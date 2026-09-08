"""Public caption-template contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from socauto.services.caption_templates import CaptionTemplateError, validate_template_body


class _TemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=2200)

    @field_validator("body")
    @classmethod
    def valid_body(cls, value: str) -> str:
        try:
            return validate_template_body(value)
        except CaptionTemplateError as error:
            raise ValueError("invalid caption template") from error


class CaptionTemplateCreate(_TemplateBody):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("template name is required")
        return name


class CaptionTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    body: str | None = Field(default=None, max_length=2200)

    @model_validator(mode="before")
    @classmethod
    def nonempty_update(cls, value: object) -> object:
        if not isinstance(value, dict) or not value:
            raise ValueError("provide a name or body")
        if any(value.get(field) is None for field in ("name", "body") if field in value):
            raise ValueError("template fields cannot be null")
        return value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("template name is required")
        return name

    @field_validator("body")
    @classmethod
    def valid_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_template_body(value)
        except CaptionTemplateError as error:
            raise ValueError("invalid caption template") from error


class CaptionTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    body: str
    created_at: datetime
    updated_at: datetime


class CaptionTemplateListResponse(BaseModel):
    items: list[CaptionTemplateResponse]
    total: int
    offset: int
    limit: int
