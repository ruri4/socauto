"""Transactional durable-job operations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from socauto.db.models import Job, JobCaptionMode, JobState, JobVisibility, Media
from socauto.db.types import utc_now
from socauto.sources.x import canonicalize_x_url

ACTIVE_STATES = frozenset({JobState.DOWNLOADING, JobState.UPLOADING})
TERMINAL_STATES = frozenset({JobState.POSTED, JobState.FAILED, JobState.CANCELLED})

_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.DOWNLOADING, JobState.CANCELLED}),
    JobState.DOWNLOADING: frozenset({JobState.DOWNLOADED, JobState.FAILED, JobState.CANCELLED}),
    JobState.DOWNLOADED: frozenset({JobState.UPLOADING, JobState.FAILED, JobState.CANCELLED}),
    JobState.UPLOADING: frozenset({JobState.POSTED, JobState.FAILED}),
    JobState.POSTED: frozenset(),
    JobState.FAILED: frozenset({JobState.PENDING, JobState.DOWNLOADED, JobState.CANCELLED}),
    JobState.CANCELLED: frozenset(),
}


class DuplicateJobError(Exception):
    def __init__(self, existing_job_id: UUID) -> None:
        super().__init__(f"a job already exists for this destination: {existing_job_id}")
        self.existing_job_id = existing_job_id


class InvalidJobTransitionError(ValueError):
    def __init__(self, current: JobState, target: JobState) -> None:
        super().__init__(f"cannot transition job from {current.value} to {target.value}")
        self.current = current
        self.target = target


class JobConflictError(RuntimeError):
    """The job changed after it was read."""


@dataclass(frozen=True)
class RecoveryResult:
    reset_downloads: int = 0
    failed_uploads: int = 0


def create_job(
    session: Session,
    *,
    source_url: str,
    destination_account_id: UUID,
    caption_override: str | None = None,
    caption_mode: JobCaptionMode = JobCaptionMode.SOURCE,
    caption_template_id: UUID | None = None,
    caption_template_name_snapshot: str | None = None,
    caption_template_body_snapshot: str | None = None,
    visibility: JobVisibility = JobVisibility.PRIVATE,
) -> Job:
    job = Job(
        source_url=source_url,
        canonical_url=canonicalize_x_url(source_url),
        destination_account_id=destination_account_id,
        caption_override=caption_override,
        caption_mode=caption_mode,
        caption_template_id=caption_template_id,
        caption_template_name_snapshot=caption_template_name_snapshot,
        caption_template_body_snapshot=caption_template_body_snapshot,
        visibility=visibility,
    )
    session.add(job)

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        existing = session.exec(
            select(Job).where(
                Job.destination_account_id == destination_account_id,
                Job.canonical_url == job.canonical_url,
            )
        ).one_or_none()
        if existing is not None:
            raise DuplicateJobError(existing.id) from error
        raise

    session.refresh(job)
    return job


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    lease_for: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> Job | None:
    claimed_at = now or utc_now()

    for _ in range(5):
        candidate = session.exec(
            select(Job)
            .where(
                col(Job.state).in_([JobState.PENDING, JobState.DOWNLOADED]),
                col(Job.cancel_requested_at).is_(None),
            )
            .order_by(col(Job.created_at), col(Job.id))
            .limit(1)
        ).first()
        if candidate is None:
            session.rollback()
            return None

        target = JobState.DOWNLOADING if candidate.state is JobState.PENDING else JobState.UPLOADING
        values: dict[str, object] = {
            "state": target,
            "worker_id": worker_id,
            "claimed_at": claimed_at,
            "lease_expires_at": claimed_at + lease_for,
            "updated_at": claimed_at,
        }
        if candidate.state is JobState.PENDING:
            values["attempt_count"] = col(Job.attempt_count) + 1

        result = cast(
            CursorResult[Any],
            session.execute(
                update(Job)
                .where(
                    col(Job.id) == candidate.id,
                    col(Job.state) == candidate.state,
                    col(Job.cancel_requested_at).is_(None),
                )
                .values(**values)
            ),
        )
        if result.rowcount == 1:
            session.commit()
            claimed = session.get(Job, candidate.id)
            if claimed is None:
                raise RuntimeError("claimed job disappeared")
            return claimed
        session.rollback()

    return None


def transition_job(
    session: Session,
    job: Job,
    target: JobState,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    posted_url: str | None = None,
    now: datetime | None = None,
) -> Job:
    if target not in _TRANSITIONS[job.state]:
        raise InvalidJobTransitionError(job.state, target)
    if target is JobState.POSTED and posted_url is None and job.creation_id is None:
        raise ValueError("posted jobs require an acknowledgement or posted URL")
    if target is JobState.FAILED and error_code is None:
        raise ValueError("failed jobs require an error code")

    changed_at = now or utc_now()
    statement = update(Job).where(col(Job.id) == job.id, col(Job.state) == job.state)
    if job.state in ACTIVE_STATES:
        statement = statement.where(
            col(Job.worker_id) == job.worker_id,
            col(Job.claimed_at) == job.claimed_at,
            col(Job.lease_expires_at) > changed_at,
        )
    values: dict[str, object] = {"state": target, "updated_at": changed_at}

    if target not in ACTIVE_STATES:
        values.update(worker_id=None, claimed_at=None, lease_expires_at=None)
    if target in TERMINAL_STATES:
        values["finished_at"] = changed_at
    if target is JobState.FAILED:
        values.update(error_code=error_code, error_message=error_message)
    if target is JobState.POSTED:
        values["posted_url"] = posted_url

    result = cast(CursorResult[Any], session.execute(statement.values(**values)))
    if result.rowcount != 1:
        session.rollback()
        raise RuntimeError("job changed or worker lease expired")
    session.commit()
    session.refresh(job)
    return job


def retry_failed_job(session: Session, job: Job, *, now: datetime | None = None) -> Job:
    if job.state is not JobState.FAILED:
        raise InvalidJobTransitionError(job.state, JobState.PENDING)

    has_media = session.exec(select(Media.id).where(Media.job_id == job.id)).first() is not None
    target = JobState.DOWNLOADED if has_media else JobState.PENDING
    changed_at = now or utc_now()
    result = cast(
        CursorResult[Any],
        session.execute(
            update(Job)
            .where(
                col(Job.id) == job.id,
                col(Job.state) == JobState.FAILED,
                col(Job.updated_at) == job.updated_at,
            )
            .values(
                state=target,
                error_code=None,
                error_message=None,
                finished_at=None,
                cancel_requested_at=None,
                updated_at=changed_at,
                attempt_count=col(Job.attempt_count) + int(has_media),
            )
        ),
    )
    if result.rowcount != 1:
        session.rollback()
        raise JobConflictError("job changed before retry")
    session.commit()
    session.refresh(job)
    return job


def recover_stale_jobs(session: Session, *, now: datetime | None = None) -> RecoveryResult:
    recovered_at = now or utc_now()
    counts: list[int] = []
    for state in (JobState.DOWNLOADING, JobState.UPLOADING):
        values: dict[str, object] = {
            "worker_id": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "updated_at": recovered_at,
            "state": JobState.PENDING if state is JobState.DOWNLOADING else JobState.FAILED,
        }
        if state is JobState.UPLOADING:
            values.update(
                error_code="upload_outcome_unknown",
                error_message="worker lease expired while uploading; retry manually",
                finished_at=recovered_at,
            )
        result = cast(
            CursorResult[Any],
            session.execute(
                update(Job)
                .where(
                    col(Job.state) == state,
                    col(Job.lease_expires_at).is_(None)
                    | (col(Job.lease_expires_at) <= recovered_at),
                )
                .values(**values)
            ),
        )
        counts.append(result.rowcount)
    # A cancelled download must not become an unclaimable pending job on restart.
    session.execute(
        update(Job)
        .where(
            col(Job.state).in_([JobState.PENDING, JobState.DOWNLOADED]),
            col(Job.cancel_requested_at).is_not(None),
        )
        .values(state=JobState.CANCELLED, finished_at=recovered_at, updated_at=recovered_at)
    )
    session.commit()
    return RecoveryResult(reset_downloads=counts[0], failed_uploads=counts[1])
