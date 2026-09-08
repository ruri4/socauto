"""Versioned reusable caption-template endpoints."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from socauto.api.errors import ErrorResponse, api_error
from socauto.api.schemas.caption_templates import (
    CaptionTemplateCreate,
    CaptionTemplateListResponse,
    CaptionTemplateResponse,
    CaptionTemplateUpdate,
)
from socauto.db.engine import get_request_session
from socauto.services.templates import (
    CaptionTemplateConflictError,
    CaptionTemplateNotFoundError,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)

router = APIRouter(
    prefix="/v1/caption-templates",
    tags=["caption-templates"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
Database = Annotated[Session, Depends(get_request_session)]


def _not_found() -> NoReturn:
    raise api_error(404, "caption_template_not_found", "Caption template not found")


def _conflict() -> NoReturn:
    raise api_error(409, "caption_template_name_conflict", "A template already uses this name")


@router.get("", response_model=CaptionTemplateListResponse)
def listing(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CaptionTemplateListResponse:
    items, total = list_templates(db, offset=offset, limit=limit)
    return CaptionTemplateListResponse(
        items=[CaptionTemplateResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{template_id}", response_model=CaptionTemplateResponse)
def detail(template_id: UUID, db: Database) -> CaptionTemplateResponse:
    try:
        return CaptionTemplateResponse.model_validate(get_template(db, template_id))
    except CaptionTemplateNotFoundError:
        _not_found()


@router.post("", response_model=CaptionTemplateResponse, status_code=201)
def create(request: CaptionTemplateCreate, db: Database) -> CaptionTemplateResponse:
    try:
        return CaptionTemplateResponse.model_validate(
            create_template(db, name=request.name, body=request.body)
        )
    except CaptionTemplateConflictError:
        _conflict()


@router.patch("/{template_id}", response_model=CaptionTemplateResponse)
def update(
    template_id: UUID, request: CaptionTemplateUpdate, db: Database
) -> CaptionTemplateResponse:
    try:
        return CaptionTemplateResponse.model_validate(
            update_template(db, template_id, name=request.name, body=request.body)
        )
    except CaptionTemplateNotFoundError:
        _not_found()
    except CaptionTemplateConflictError:
        _conflict()


@router.delete("/{template_id}", status_code=204)
def delete(template_id: UUID, db: Database) -> Response:
    try:
        delete_template(db, template_id)
    except CaptionTemplateNotFoundError:
        _not_found()
    return Response(status_code=204)
