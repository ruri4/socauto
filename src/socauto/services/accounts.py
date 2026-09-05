"""Destination account lifecycle operations."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from socauto.config import Settings
from socauto.db.models import Account, AccountPlatform, Job
from socauto.destinations.tiktok.session import TikTokSession, TikTokSessionStore


class AccountNotFoundError(LookupError):
    """The requested account does not exist."""


class AccountInUseError(RuntimeError):
    """The account is referenced by one or more jobs."""


def create_tiktok_account(
    db: Session,
    settings: Settings,
    authenticated_session: TikTokSession,
) -> Account:
    account = Account(session_file="pending")
    store = TikTokSessionStore(settings)
    account.session_file = store.save(account.id, authenticated_session)
    db.add(account)
    try:
        db.commit()
    except Exception:
        db.rollback()
        staged = store.stage_delete(account.session_file)
        store.finish_delete(staged)
        raise
    db.refresh(account)
    return account


def list_accounts(db: Session, *, offset: int, limit: int) -> tuple[list[Account], int]:
    accounts = list(
        db.exec(
            select(Account)
            .where(Account.platform == AccountPlatform.TIKTOK)
            .order_by(col(Account.created_at).desc(), col(Account.id))
            .offset(offset)
            .limit(limit)
        ).all()
    )
    total = db.exec(
        select(func.count()).select_from(Account).where(Account.platform == AccountPlatform.TIKTOK)
    ).one()
    return accounts, total


def delete_account(db: Session, settings: Settings, account_id: UUID) -> None:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError
    if db.exec(select(Job.id).where(Job.destination_account_id == account_id).limit(1)).first():
        raise AccountInUseError

    store = TikTokSessionStore(settings)
    staged = store.stage_delete(account.session_file)
    db.delete(account)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        store.restore_delete(staged)
        raise AccountInUseError from error
    except Exception:
        db.rollback()
        store.restore_delete(staged)
        raise
    store.finish_delete(staged)
