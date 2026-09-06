"""Job submission and manual retry policy; no network or browser work here."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from socauto.db.jobs import create_job, retry_failed_job
from socauto.db.models import Account, AccountPlatform, AccountStatus, Job, JobState
from socauto.services.accounts import AccountNotFoundError


class JobNotFoundError(LookupError):
    """No job exists with this identifier."""


class AccountUnavailableError(ValueError):
    """The destination is not an active TikTok account."""


class RetryConfirmationRequiredError(ValueError):
    """An uncertain publication must be reviewed before retrying."""


def get_job(db: Session, job_id: UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError
    return job


def _active_account(db: Session, account_id: UUID) -> None:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError
    if account.platform is not AccountPlatform.TIKTOK or account.status is not AccountStatus.ACTIVE:
        raise AccountUnavailableError


def submit_job(
    db: Session, *, source_url: str, destination_account_id: UUID, caption_override: str | None
) -> Job:
    _active_account(db, destination_account_id)
    try:
        return create_job(
            db,
            source_url=source_url,
            destination_account_id=destination_account_id,
            caption_override=caption_override,
        )
    except IntegrityError:
        # create_job rolled back; account deletion can race submission.
        if db.get(Account, destination_account_id) is None:
            raise AccountNotFoundError from None
        raise


def list_jobs(
    db: Session,
    *,
    offset: int,
    limit: int,
    state: JobState | None = None,
    destination_account_id: UUID | None = None,
) -> tuple[list[Job], int]:
    query = select(Job)
    count = select(func.count()).select_from(Job)
    if state is not None:
        query = query.where(Job.state == state)
        count = count.where(Job.state == state)
    if destination_account_id is not None:
        query = query.where(Job.destination_account_id == destination_account_id)
        count = count.where(Job.destination_account_id == destination_account_id)
    items = db.exec(
        query.order_by(col(Job.created_at).desc(), col(Job.id)).offset(offset).limit(limit)
    ).all()
    return list(items), db.exec(count).one()


def retry_job(db: Session, job_id: UUID, *, acknowledge_duplicate_risk: bool) -> Job:
    job = get_job(db, job_id)
    if job.state is JobState.FAILED:
        _active_account(db, job.destination_account_id)
        if job.error_code == "upload_outcome_unknown" and not acknowledge_duplicate_risk:
            raise RetryConfirmationRequiredError
    return retry_failed_job(db, job)
