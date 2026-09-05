"""Standalone durable queue consumer: uv run python -m socauto.worker."""

import logging
import signal
from datetime import timedelta
from threading import Event
from types import FrameType
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from socauto.config import Settings, get_settings
from socauto.db.engine import create_db_engine
from socauto.db.jobs import claim_next_job, recover_stale_jobs
from socauto.services.media import cleanup_posted
from socauto.services.pipeline import Pipeline

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self, engine: Engine, settings: Settings, pipeline: Pipeline | None = None
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.pipeline = pipeline if pipeline is not None else Pipeline(engine, settings)
        self.stopped = Event()

    def run_once(self) -> bool:
        with Session(self.engine) as session:
            recovery = recover_stale_jobs(session)
            if recovery.reset_downloads or recovery.failed_uploads:
                logger.warning(
                    "recovered %s downloads; %s uploads require review",
                    recovery.reset_downloads,
                    recovery.failed_uploads,
                )
        cleanup_posted(self.engine, self.settings)
        if self.stopped.is_set():
            return False
        with Session(self.engine) as session:
            job = claim_next_job(
                session,
                worker_id=uuid4().hex,
                lease_for=timedelta(seconds=self.settings.worker_lease_seconds),
            )
            if job is None:
                return False
            session.expunge(job)
        self.pipeline.run(job)
        cleanup_posted(self.engine, self.settings)
        return True

    def run(self) -> None:
        logger.info("worker started")
        while not self.stopped.is_set():
            if not self.run_once():
                self.stopped.wait(self.settings.worker_poll_seconds)
        logger.info("worker stopped")

    def stop(self, signum: int, frame: FrameType | None) -> None:
        """Finish the active stage without interrupting an irreversible publish."""
        self.stopped.set()


def main() -> int:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    engine = create_db_engine(settings)
    worker = Worker(engine, settings)
    previous = {sig: signal.signal(sig, worker.stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        worker.run()
    except SQLAlchemyError:
        logger.error("worker database operation failed; check migrations and storage")
        return 1
    except Exception as error:
        # Tracebacks from adapters/SQL may contain credentials or signed request parameters.
        logger.error("worker stopped on unexpected %s", type(error).__name__)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
