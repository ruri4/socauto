"""Destination account lifecycle operations."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from socauto.config import Settings
from socauto.db.models import Account, AccountPlatform, AccountStatus, Job
from socauto.db.types import utc_now
from socauto.destinations.tiktok.account_info import TikTokAccountInfo
from socauto.destinations.tiktok.session import (
    TikTokSession,
    TikTokSessionError,
    TikTokSessionStore,
)


class AccountNotFoundError(LookupError):
    """The requested account does not exist."""


class AccountInUseError(RuntimeError):
    """The account is referenced by one or more jobs."""


def import_tiktok_account(
    db: Session,
    settings: Settings,
    credentials: TikTokSession,
    info: TikTokAccountInfo,
) -> Account:
    """Create an account or replace the session for the same TikTok identity."""
    account = db.exec(
        select(Account).where(
            Account.platform == AccountPlatform.TIKTOK,
            Account.platform_user_id == info.user_id,
        )
    ).one_or_none()
    if account is None:
        account = Account(
            platform_user_id=info.user_id,
            handle=info.username,
            session_file="pending",
        )
        store = TikTokSessionStore(settings)
        account.session_file = store.save(account.id, credentials)
        db.add(account)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            store.finish_delete(store.stage_delete(account.session_file))
            existing = db.exec(
                select(Account).where(
                    Account.platform == AccountPlatform.TIKTOK,
                    Account.platform_user_id == info.user_id,
                )
            ).one_or_none()
            if existing is None:
                raise
            return _replace_tiktok_account(db, store, existing, credentials, info)
        except Exception:
            db.rollback()
            store.finish_delete(store.stage_delete(account.session_file))
            raise
        db.refresh(account)
        return account

    return _replace_tiktok_account(db, TikTokSessionStore(settings), account, credentials, info)


def _replace_tiktok_account(
    db: Session,
    store: TikTokSessionStore,
    account: Account,
    credentials: TikTokSession,
    info: TikTokAccountInfo,
) -> Account:
    try:
        previous = store.load(account.session_file)
    except TikTokSessionError:
        previous = None
    original_file = account.session_file
    account.session_file = store.save(account.id, credentials)
    try:
        account.handle = info.username
        account.status = AccountStatus.ACTIVE
        account.updated_at = utc_now()
        db.add(account)
        db.commit()
    except Exception:
        db.rollback()
        if previous is not None:
            store.save(account.id, previous)
        elif account.session_file != original_file:
            store.finish_delete(store.stage_delete(account.session_file))
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
