import hashlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, select

from socauto.config import Settings
from socauto.db.claims import cancel_job
from socauto.db.engine import create_db_engine
from socauto.db.jobs import create_job, retry_failed_job
from socauto.db.models import Account, Job, JobState, Media
from socauto.destinations.base import PublishError, PublishResult
from socauto.services.pipeline import Pipeline
from socauto.sources.x_types import XDownloadedMedia, XMultipleVideosError
from socauto.worker import Worker


class FakeSource:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls = 0
        self.after_download: Callable[[], None] = lambda: None
        self.error: Exception | None = None

    def download(
        self,
        source_url: str,
        *,
        job_id: UUID,
        caption_override: str | None = None,
        attempt_id: UUID | None = None,
    ) -> XDownloadedMedia:
        self.calls += 1
        if self.error:
            raise self.error
        assert attempt_id is not None
        path = self.settings.jobs_dir / str(job_id) / str(attempt_id) / "video.mp4"
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_bytes(b"video")
        self.after_download()
        return XDownloadedMedia(
            path=path,
            caption="tweet caption" if caption_override is None else caption_override,
            mime_type="video/mp4",
            size_bytes=5,
            checksum_sha256=hashlib.sha256(b"video").hexdigest(),
            duration_seconds=1,
            width=100,
            height=100,
        )


class FakeDestination:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str, int]] = []
        self.error: Exception | None = None
        self.after_publish: Callable[[], None] = lambda: None

    def publish(
        self,
        media: Path,
        caption: str,
        *,
        visibility: Literal[0, 1] = 1,
        before_publish: Callable[[], None] | None = None,
    ) -> PublishResult:
        if before_publish is not None:
            before_publish()
        self.calls.append((media, caption, visibility))
        if self.error:
            raise self.error
        self.after_publish()
        return PublishResult(creation_id="project-1", video_id="video-1", post_id="123")


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[Engine, Settings, UUID, FakeSource, FakeDestination]]:
    settings = Settings(data_dir=tmp_path / "data")
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(session_file="sessions/test.json")
        session.add(account)
        session.commit()
        job = create_job(
            session, source_url="https://x.com/u/status/123", destination_account_id=account.id
        )
        job_id = job.id
    yield engine, settings, job_id, FakeSource(settings), FakeDestination()
    engine.dispose()


def test_worker_pipeline_and_cleanup(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
) -> None:
    engine, settings, job_id, source, destination = setup
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    assert worker.run_once()
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        media = session.exec(select(Media)).one()
        path = Path(media.path)
        assert job.state is JobState.DOWNLOADED
        assert job.resolved_caption == "tweet caption"
        assert path.is_file()
    # A fresh worker instance must be able to resume the durable downloaded stage.
    worker = Worker(engine, settings, worker.pipeline)
    assert worker.run_once()
    assert not worker.run_once()
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        assert job.state is JobState.POSTED
        assert job.creation_id == "project-1" and job.video_id == "video-1"
        assert job.post_id == "123" and job.posted_url is None
        assert job.finished_at is not None and job.worker_id is None
        assert job.attempt_count == 1
        assert session.exec(select(Media)).first() is None
    assert destination.calls == [(path, "tweet caption", 1)]
    assert not path.parent.exists()


@pytest.mark.parametrize("code", ["upload_outcome_unknown", "tiktok_network_error"])
def test_failure_retains_media_until_manual_retry(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
    code: str,
) -> None:
    engine, settings, job_id, source, destination = setup
    destination.error = PublishError(code, retryable=True)
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    assert worker.run_once() and worker.run_once()
    assert not worker.run_once()
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        assert job.state is JobState.FAILED and job.error_code == code
        assert Path(session.exec(select(Media)).one().path).is_file()
        retry_failed_job(session, job)
    destination.error = None
    assert worker.run_once()
    assert source.calls == 1 and len(destination.calls) == 2
    with Session(engine) as session:
        assert session.get_one(Job, job_id).attempt_count == 2


@pytest.mark.parametrize("stage", ["pending", "downloading", "downloaded"])
def test_cancellation_never_calls_destination(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
    stage: str,
) -> None:
    engine, settings, job_id, source, destination = setup
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )

    def cancel() -> None:
        with Session(engine) as session:
            cancel_job(session, job_id)

    if stage == "downloading":
        source.after_download = cancel
    elif stage == "downloaded":
        worker.run_once()
        cancel()
    else:
        cancel()
    worker.run_once()
    worker.run_once()
    with Session(engine) as session:
        assert session.get_one(Job, job_id).state is JobState.CANCELLED
    assert not destination.calls


@pytest.mark.parametrize("damage", ["missing", "changed", "outside", "symlink"])
def test_retained_media_validation(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
    damage: str,
    tmp_path: Path,
) -> None:
    engine, settings, job_id, source, destination = setup
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    worker.run_once()
    with Session(engine) as session:
        media = session.exec(select(Media)).one()
        path = Path(media.path)
        if damage == "missing":
            path.unlink()
        elif damage == "changed":
            path.write_bytes(b"other")
        elif damage == "outside":
            media.path = str(tmp_path / "video.mp4")
            session.add(media)
            session.commit()
        else:
            outside = tmp_path / "video.mp4"
            outside.write_bytes(b"video")
            path.unlink()
            path.symlink_to(outside)
    worker.run_once()
    assert not destination.calls
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        assert job.state is JobState.FAILED
        assert job.error_code and job.error_code.startswith("retained_media_")


def test_safe_source_failure_and_unexpected_error(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, settings, job_id, source, destination = setup
    monkeypatch.setattr(logging.getLogger("socauto.services.pipeline"), "disabled", False)
    source.error = XMultipleVideosError("secret-cookie")
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    with caplog.at_level(logging.INFO):
        worker.run_once()
    with Session(engine) as session:
        job = session.get_one(Job, job_id)
        assert job.error_code == "x_multiple_videos_unsupported"
        assert "secret-cookie" not in (job.error_message or "")
        retry_failed_job(session, job)
    assert "secret-cookie" not in caplog.text
    source.error = RuntimeError("programming bug")
    with pytest.raises(RuntimeError, match="programming bug"):
        worker.run_once()


def test_invalid_session_fails_without_publication(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
) -> None:
    engine, settings, job_id, source, _ = setup
    worker = Worker(engine, settings, Pipeline(engine, settings, source=source))
    worker.run_once()
    worker.run_once()
    with Session(engine) as session:
        assert session.get_one(Job, job_id).error_code == "tiktok_session_invalid"


def test_stop_during_download_leaves_resumable_stage(
    setup: tuple[Engine, Settings, UUID, FakeSource, FakeDestination],
) -> None:
    engine, settings, job_id, source, destination = setup
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    source.after_download = lambda: worker.stop(15, None)
    worker.run()
    with Session(engine) as session:
        assert session.get_one(Job, job_id).state is JobState.DOWNLOADED
    assert not destination.calls
