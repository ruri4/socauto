import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, select

from socauto.config import Settings
from socauto.db.engine import create_db_engine
from socauto.db.models import Account, Job, JobState, Media
from socauto.services.media import cleanup_posted
from socauto.worker import Worker


def posted_media(engine: Engine, settings: Settings) -> Path:
    with Session(engine) as session:
        account = Account(session_file="sessions/test.json")
        session.add(account)
        session.commit()
        job = Job(
            source_url="https://x.com/u/status/1",
            canonical_url="https://x.com/i/status/1",
            destination_account_id=account.id,
            state=JobState.POSTED,
            creation_id="project",
        )
        session.add(job)
        session.commit()
        path = settings.jobs_dir / str(job.id) / str(uuid4()) / "video.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        session.add(
            Media(
                job_id=job.id,
                path=str(path),
                mime_type="video/mp4",
                size_bytes=5,
                checksum_sha256="a" * 64,
            )
        )
        session.commit()
        return path


def test_cleanup_failure_is_durable_and_retryable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    try:
        path = posted_media(engine, settings)
        with patch("socauto.services.media.shutil.rmtree", side_effect=PermissionError):
            cleanup_posted(engine, settings)
        with Session(engine) as session:
            assert session.exec(select(Media)).first() is not None
        assert path.is_file()
        # Simulate a crash after deleting files but before deleting the media row.
        path.unlink()
        path.parent.rmdir()
        cleanup_posted(engine, settings)
        with Session(engine) as session:
            assert session.exec(select(Media)).first() is None
    finally:
        engine.dispose()


def test_worker_stopped_before_claim(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    try:
        worker = Worker(engine, settings)
        worker.stop(signal.SIGTERM, None)
        assert not worker.run_once()
        worker.run()
    finally:
        engine.dispose()


def test_real_worker_process_start_and_sigterm(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    env = {**os.environ, "SOCAUTO_DATA_DIR": str(tmp_path), "SOCAUTO_LOG_LEVEL": "INFO"}
    process = subprocess.Popen(
        [sys.executable, "-m", "socauto.worker"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ready = Event()
    lines: list[str] = []

    def output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if "worker started" in line:
                ready.set()

    reader = Thread(target=output, daemon=True)
    reader.start()
    try:
        assert ready.wait(10), "".join(lines)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
        reader.join(timeout=2)
        assert "worker stopped" in "".join(lines)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
