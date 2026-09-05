from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import Engine, update
from sqlmodel import Session, SQLModel, col

from socauto.config import Settings
from socauto.db.claims import LostClaimError, cancel_job, finish_claim, renew_claim
from socauto.db.engine import create_db_engine
from socauto.db.jobs import (
    InvalidJobTransitionError,
    claim_next_job,
    create_job,
    recover_stale_jobs,
)
from socauto.db.models import Account, Job, JobState
from socauto.db.types import utc_now
from socauto.destinations.base import PublishResult
from socauto.services.lease import Lease


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[tuple[Engine, UUID]]:
    engine = create_db_engine(Settings(data_dir=tmp_path))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(session_file="sessions/test.json")
        session.add(account)
        session.commit()
        job = create_job(
            session, source_url="https://x.com/u/status/1", destination_account_id=account.id
        )
        job_id = job.id
    yield engine, job_id
    engine.dispose()


def claim(engine: Engine, worker_id: str = "test") -> Job:
    with Session(engine) as session:
        job = claim_next_job(session, worker_id=worker_id)
        assert job is not None
        session.expunge(job)
        return job


def expire(engine: Engine, job_id: UUID) -> None:
    with Session(engine) as session:
        session.execute(
            update(Job)
            .where(col(Job.id) == job_id)
            .values(lease_expires_at=utc_now() - timedelta(seconds=1))
        )
        session.commit()


def test_concurrent_claim_has_one_owner(queue: tuple[Engine, UUID]) -> None:
    engine, _ = queue
    barrier = Barrier(2)

    def contend(worker: str) -> str | None:
        with Session(engine) as session:
            barrier.wait(timeout=5)
            job = claim_next_job(session, worker_id=worker)
            return job.worker_id if job else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(contend, ["one", "two"]))
    assert results.count(None) == 1
    assert len(set(results) & {"one", "two"}) == 1


def test_expired_worker_cannot_renew_or_finish(queue: tuple[Engine, UUID]) -> None:
    engine, job_id = queue
    old = claim(engine)
    expire(engine, job_id)
    with Session(engine) as session:
        with pytest.raises(LostClaimError):
            renew_claim(session, old, timedelta(minutes=5))
        assert recover_stale_jobs(session).reset_downloads == 1
    current = claim(engine, "replacement")
    with Session(engine) as session:
        with pytest.raises(LostClaimError):
            finish_claim(session, old, JobState.FAILED, error_code="late_failure")
        persisted = session.get_one(Job, job_id)
        assert persisted.worker_id == current.worker_id
        assert persisted.attempt_count == 2 and persisted.error_code is None


def test_upload_recovery_rejects_late_acknowledgement(queue: tuple[Engine, UUID]) -> None:
    engine, job_id = queue
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        job.state = JobState.DOWNLOADED
        session.add(job)
        session.commit()
    old = claim(engine)
    expire(engine, job_id)
    with Session(engine) as session:
        assert recover_stale_jobs(session).failed_uploads == 1
        with pytest.raises(LostClaimError):
            finish_claim(
                session,
                old,
                JobState.POSTED,
                result=PublishResult(creation_id="project", video_id="vid"),
            )
        assert session.get_one(Job, job_id).error_code == "upload_outcome_unknown"
        assert claim_next_job(session, worker_id="replacement") is None


def test_heartbeat_uses_independent_session_and_stops(
    queue: tuple[Engine, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, job_id = queue
    job = claim(engine)
    renewed = Event()

    def renew(session: Session, snapshot: Job, duration: timedelta) -> None:
        assert snapshot not in session
        renew_claim(session, snapshot, duration)
        renewed.set()

    monkeypatch.setattr("socauto.services.lease.renew_claim", renew)
    lease = Lease(engine, job, seconds=30)
    lease.interval = 0.01
    with lease:
        renewed.clear()
        assert renewed.wait(timeout=2)
        with Session(engine) as session:
            current = session.get_one(Job, job_id)
            assert current.lease_expires_at is not None
            assert current.lease_expires_at > utc_now()
            assert recover_stale_jobs(session).reset_downloads == 0
    assert not lease.thread.is_alive()
    expire(engine, job_id)
    with pytest.raises(LostClaimError):
        lease.check()


def test_cancelled_expired_download_is_not_requeued(queue: tuple[Engine, UUID]) -> None:
    engine, job_id = queue
    claim(engine)
    with Session(engine) as session:
        assert cancel_job(session, job_id).state is JobState.DOWNLOADING
    expire(engine, job_id)
    with Session(engine) as session:
        recover_stale_jobs(session)
        assert session.get_one(Job, job_id).state is JobState.CANCELLED
        assert claim_next_job(session, worker_id="next") is None


def test_cancellation_rejected_after_upload_claim(queue: tuple[Engine, UUID]) -> None:
    engine, job_id = queue
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        job.state = JobState.DOWNLOADED
        session.add(job)
        session.commit()
    claim(engine)
    with Session(engine) as session, pytest.raises(InvalidJobTransitionError):
        cancel_job(session, job_id)
