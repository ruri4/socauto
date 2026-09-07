"""Keep synchronous adapter work leased using independent short DB sessions."""

import logging
from datetime import timedelta
from threading import Event, Thread
from types import TracebackType

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from socauto.db.claims import LostClaimError, renew_claim
from socauto.db.models import Job

logger = logging.getLogger(__name__)


class Lease:
    def __init__(self, engine: Engine, job: Job, seconds: int) -> None:
        self.engine = engine
        self.job = job
        self.duration = timedelta(seconds=seconds)
        self.interval = seconds / 3
        self.stopped = Event()
        self.lost = Event()
        self.thread = Thread(target=self._heartbeat, name="socauto-lease", daemon=True)

    def check(self) -> None:
        if self.lost.is_set():
            raise LostClaimError
        with Session(self.engine) as session:
            renew_claim(session, self.job, self.duration)

    def _heartbeat(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                self.check()
            except LostClaimError, SQLAlchemyError:
                self.lost.set()
                logger.warning("job %s lease renewal failed", self.job.id)
                return

    def __enter__(self) -> Lease:
        self.check()
        self.thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stopped.set()
        self.thread.join()
