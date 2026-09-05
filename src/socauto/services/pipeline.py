"""One claimed stage of the X-to-TikTok pipeline, without API dependencies."""

import logging
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import Engine
from sqlmodel import Session, select

from socauto.config import Settings
from socauto.db.claims import LostClaimError, finish_claim
from socauto.db.models import Account, Job, JobState, Media
from socauto.db.models.account import AccountStatus
from socauto.destinations.base import Destination, PublishError
from socauto.destinations.tiktok.session import TikTokSessionError, TikTokSessionStore
from socauto.destinations.tiktok.uploader import TikTokDestination
from socauto.services.lease import Lease
from socauto.services.media import validate_media
from socauto.sources.base import Source
from socauto.sources.x import XSourceAdapter
from socauto.sources.x_types import XSourceError

logger = logging.getLogger(__name__)
DestinationFactory = Callable[[Account], Destination]


class Pipeline:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        *,
        source: Source | None = None,
        destination_factory: DestinationFactory | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.source = source if source is not None else XSourceAdapter(settings)
        self.destination_factory = destination_factory or self._destination

    def _destination(self, account: Account) -> Destination:
        session = TikTokSessionStore(self.settings).load(account.session_file)
        return TikTokDestination(self.settings, session)

    def run(self, job: Job) -> None:
        try:
            with Lease(self.engine, job, self.settings.worker_lease_seconds) as lease:
                try:
                    if job.state is JobState.DOWNLOADING:
                        self._download(job)
                    elif job.state is JobState.UPLOADING:
                        self._upload(job, lease)
                    else:
                        raise ValueError("pipeline requires an active job claim")
                except (XSourceError, PublishError) as error:
                    self._fail(job, error.code)
                except TikTokSessionError:
                    self._fail(job, "tiktok_session_invalid")
        except LostClaimError:
            # Never overwrite recovery or another worker, even after a publish response.
            logger.warning("job %s lost its claim; result requires review", job.id)

    def _fail(self, job: Job, code: str) -> None:
        with Session(self.engine) as session:
            finish_claim(session, job, JobState.FAILED, error_code=code)
        logger.warning("job %s failed: %s", job.id, code)

    def _download(self, job: Job) -> None:
        with Session(self.engine) as session:
            current = session.get(Job, job.id)
            if current is not None and current.cancel_requested_at is not None:
                finish_claim(session, job, JobState.CANCELLED)
                return
        downloaded = self.source.download(
            job.canonical_url,
            job_id=job.id,
            attempt_id=uuid4(),
            caption_override=job.caption_override,
        )
        media = Media(
            job_id=job.id,
            path=str(downloaded.path.absolute()),
            mime_type=downloaded.mime_type,
            size_bytes=downloaded.size_bytes,
            checksum_sha256=downloaded.checksum_sha256,
            duration_seconds=downloaded.duration_seconds,
            width=downloaded.width,
            height=downloaded.height,
        )
        validate_media(self.settings, media)
        with Session(self.engine) as session:
            finish_claim(session, job, JobState.DOWNLOADED, media=media, caption=downloaded.caption)
        logger.info("job %s download finished", job.id)

    def _upload(self, job: Job, lease: Lease) -> None:
        with Session(self.engine) as session:
            account = session.get(Account, job.destination_account_id)
            media = session.exec(select(Media).where(Media.job_id == job.id)).one_or_none()
            if account is None or account.status is not AccountStatus.ACTIVE:
                raise PublishError("destination_account_unavailable")
            if media is None:
                raise PublishError("retained_media_unavailable")
            session.expunge(account)
            session.expunge(media)
        if job.resolved_caption is None:
            raise PublishError("retained_caption_unavailable")
        path = validate_media(self.settings, media)
        destination = self.destination_factory(account)
        lease.check()
        # Adapter-level retries are bounded and limited to pre-publication safe requests.
        # Never replay the entire publication operation, even for a retryable transport error.
        result = destination.publish(
            path,
            job.resolved_caption,
            visibility=1,
            before_publish=lease.check,
        )
        with Session(self.engine) as session:
            finish_claim(session, job, JobState.POSTED, result=result)
        logger.info("job %s publication acknowledged", job.id)
