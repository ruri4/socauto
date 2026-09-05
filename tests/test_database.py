from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect
from sqlmodel import Session, SQLModel

from socauto.config import Settings, get_settings
from socauto.db.engine import create_db_engine
from socauto.db.jobs import (
    DuplicateJobError,
    claim_next_job,
    create_job,
    recover_stale_jobs,
    retry_failed_job,
    transition_job,
)
from socauto.db.models import Account, JobState, Media
from socauto.db.types import utc_now


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_db_engine(Settings(data_dir=tmp_path / "data"))
    SQLModel.metadata.create_all(database)
    yield database
    database.dispose()


def add_account(session: Session) -> Account:
    account = Account(session_file="sessions/test.json", platform_user_id="123")
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_initial_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCAUTO_DATA_DIR", str(tmp_path / "migrated"))
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        database = create_db_engine(get_settings())
        assert set(inspect(database).get_table_names()) == {
            "accounts",
            "alembic_version",
            "jobs",
            "media",
        }
        database.dispose()
    finally:
        get_settings.cache_clear()


def test_job_deduplication(engine: Engine) -> None:
    with Session(engine) as session:
        account = add_account(session)
        first = create_job(
            session,
            source_url="https://twitter.com/example/status/123?ref=test",
            destination_account_id=account.id,
        )

        with pytest.raises(DuplicateJobError) as error:
            create_job(
                session,
                source_url="https://x.com/other/status/123/video/1",
                destination_account_id=account.id,
            )

        assert error.value.existing_job_id == first.id


def test_claim_and_complete_job(engine: Engine) -> None:
    now = utc_now()
    with Session(engine) as session:
        account = add_account(session)
        job = create_job(
            session,
            source_url="https://x.com/example/status/456",
            destination_account_id=account.id,
        )

        claimed = claim_next_job(session, worker_id="worker-1", now=now)
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.state is JobState.DOWNLOADING
        assert claimed.attempt_count == 1
        assert claimed.lease_expires_at == now + timedelta(minutes=5)

        downloaded = transition_job(session, claimed, JobState.DOWNLOADED, now=now)
        session.add(
            Media(
                job_id=downloaded.id,
                path="data/jobs/video.mp4",
                mime_type="video/mp4",
                size_bytes=10,
                checksum_sha256="a" * 64,
            )
        )
        session.commit()

        uploading = claim_next_job(session, worker_id="worker-1", now=now)
        assert uploading is not None
        assert uploading.state is JobState.UPLOADING

        posted = transition_job(
            session,
            uploading,
            JobState.POSTED,
            posted_url="https://www.tiktok.com/@example/video/1",
            now=now,
        )
        assert posted.finished_at == now
        assert posted.worker_id is None


def test_restart_recovery_avoids_automatic_reupload(engine: Engine) -> None:
    expired = utc_now() - timedelta(minutes=1)
    with Session(engine) as session:
        account = add_account(session)
        downloading = create_job(
            session,
            source_url="https://x.com/example/status/1",
            destination_account_id=account.id,
        )
        uploading = create_job(
            session,
            source_url="https://x.com/example/status/2",
            destination_account_id=account.id,
        )
        downloading.state = JobState.DOWNLOADING
        downloading.worker_id = "dead-worker"
        downloading.lease_expires_at = expired
        uploading.state = JobState.UPLOADING
        uploading.worker_id = "dead-worker"
        uploading.lease_expires_at = expired
        session.add(downloading)
        session.add(uploading)
        session.commit()

        result = recover_stale_jobs(session)
        session.refresh(downloading)
        session.refresh(uploading)

        assert result.reset_downloads == 1
        assert result.failed_uploads == 1
        assert downloading.state is JobState.PENDING
        assert uploading.state is JobState.FAILED
        assert uploading.error_code == "upload_outcome_unknown"


def test_failed_job_retries_from_existing_media(engine: Engine) -> None:
    with Session(engine) as session:
        account = add_account(session)
        job = create_job(
            session,
            source_url="https://x.com/example/status/789",
            destination_account_id=account.id,
        )
        job.state = JobState.FAILED
        job.error_code = "temporary"
        session.add(job)
        session.add(
            Media(
                job_id=job.id,
                path="data/jobs/video.mp4",
                mime_type="video/mp4",
                size_bytes=10,
                checksum_sha256="b" * 64,
            )
        )
        session.commit()

        retried = retry_failed_job(session, job)

        assert retried.state is JobState.DOWNLOADED
        assert retried.error_code is None
