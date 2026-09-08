"""Caption-template CRUD policy."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from socauto.db.models import CaptionTemplate
from socauto.db.types import utc_now


class CaptionTemplateNotFoundError(LookupError):
    pass


class CaptionTemplateConflictError(ValueError):
    pass


def get_template(db: Session, template_id: UUID) -> CaptionTemplate:
    template = db.get(CaptionTemplate, template_id)
    if template is None:
        raise CaptionTemplateNotFoundError
    return template


def list_templates(db: Session, *, offset: int, limit: int) -> tuple[list[CaptionTemplate], int]:
    items = db.exec(
        select(CaptionTemplate)
        .order_by(col(CaptionTemplate.updated_at).desc(), col(CaptionTemplate.id))
        .offset(offset)
        .limit(limit)
    ).all()
    return list(items), db.exec(select(func.count()).select_from(CaptionTemplate)).one()


def create_template(db: Session, *, name: str, body: str) -> CaptionTemplate:
    template = CaptionTemplate(name=name, body=body)
    db.add(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CaptionTemplateConflictError from None
    db.refresh(template)
    return template


def update_template(
    db: Session, template_id: UUID, *, name: str | None, body: str | None
) -> CaptionTemplate:
    template = get_template(db, template_id)
    if name is not None:
        template.name = name
    if body is not None:
        template.body = body
    template.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CaptionTemplateConflictError from None
    db.refresh(template)
    return template


def delete_template(db: Session, template_id: UUID) -> None:
    db.delete(get_template(db, template_id))
    db.commit()
