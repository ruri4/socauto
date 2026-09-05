"""Lease-fenced worker writes; no transaction stays open during network I/O."""

from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Update, case, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col

from socauto.db.jobs import InvalidJobTransitionError
from socauto.db.models import Job, JobState, Media
from socauto.db.types import utc_now
from socauto.destinations.base import PublishResult


class LostClaimError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("worker no longer owns this job")


def owned_update(job: Job) -> Update:
    return update(Job).where(
        col(Job.id) == job.id,
        col(Job.state) == job.state,
        col(Job.worker_id) == job.worker_id,
        col(Job.claimed_at) == job.claimed_at,
        col(Job.lease_expires_at) > utc_now(),
    )


def _execute(session: Session, statement: Update) -> None:
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount != 1:
        session.rollback()
        raise LostClaimError


def renew_claim(session: Session, job: Job, lease_for: timedelta) -> None:
    _execute(session, owned_update(job).values(lease_expires_at=utc_now() + lease_for))
    session.commit()


def finish_claim(
    session: Session,
    job: Job,
    target: JobState,
    *,
    media: Media | None = None,
    caption: str | None = None,
    result: PublishResult | None = None,
    error_code: str | None = None,
) -> None:
    allowed = (
        {JobState.DOWNLOADED, JobState.FAILED, JobState.CANCELLED}
        if job.state is JobState.DOWNLOADING
        else {JobState.POSTED, JobState.FAILED}
        if job.state is JobState.UPLOADING
        else set()
    )
    if target not in allowed:
        raise InvalidJobTransitionError(job.state, target)
    if target is JobState.DOWNLOADED and (media is None or caption is None):
        raise ValueError("download completion requires media and caption")
    if target is JobState.POSTED and (
        result is None or not result.creation_id or not result.video_id
    ):
        raise ValueError("publication completion requires an acknowledgement")
    if target is JobState.FAILED and error_code is None:
        raise ValueError("failure requires an error code")
    now = utc_now()
    values: dict[str, object] = {
        "state": target,
        "worker_id": None,
        "claimed_at": None,
        "lease_expires_at": None,
        "updated_at": now,
        "finished_at": None if target is JobState.DOWNLOADED else now,
        "error_code": error_code,
        "error_message": error_code.replace("_", " ") if error_code else None,
    }
    if caption is not None:
        values["resolved_caption"] = caption
    if result is not None:
        values.update(
            creation_id=result.creation_id,
            video_id=result.video_id,
            post_id=result.post_id,
            posted_url=result.post_url,
        )
    if job.state is JobState.DOWNLOADING:
        cancelled = col(Job.cancel_requested_at).is_not(None)
        values["state"] = case((cancelled, JobState.CANCELLED.value), else_=target.value)
        values["finished_at"] = case((cancelled, now), else_=values["finished_at"])
    _execute(session, owned_update(job).values(**values))
    if media is not None:
        session.add(media)
    session.commit()


def cancel_job(session: Session, job_id: UUID) -> Job:
    """Cancellation is atomic against upload claims and cannot undo publication."""
    for _ in range(5):
        session.expire_all()
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError("job not found")
        if job.state is JobState.CANCELLED:
            return job
        if job.state in {JobState.UPLOADING, JobState.POSTED}:
            raise InvalidJobTransitionError(job.state, JobState.CANCELLED)
        now = utc_now()
        values: dict[str, object] = {"cancel_requested_at": now, "updated_at": now}
        if job.state is not JobState.DOWNLOADING:
            values.update(state=JobState.CANCELLED, finished_at=now)
        result = cast(
            CursorResult[Any],
            session.execute(
                update(Job)
                .where(col(Job.id) == job_id, col(Job.state) == job.state)
                .values(**values)
            ),
        )
        if result.rowcount == 1:
            session.commit()
            session.refresh(job)
            return job
        session.rollback()
    raise LostClaimError
