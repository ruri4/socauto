"""Validate retained downloads and clean only durably acknowledged media."""

import hashlib
import logging
import shutil
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine
from sqlmodel import Session, select

from socauto.config import Settings
from socauto.db.models import Job, JobState, Media
from socauto.destinations.base import PublishError

logger = logging.getLogger(__name__)


def media_path(settings: Settings, job_id: UUID, path: str) -> Path:
    candidate = Path(path).absolute()
    root = settings.jobs_dir.resolve() / str(job_id)
    try:
        relative = candidate.relative_to(root)
        if candidate.resolve() != candidate or candidate.name != "video.mp4":
            raise ValueError
        if len(relative.parts) not in (1, 2):
            raise ValueError
        if len(relative.parts) == 2:
            UUID(relative.parts[0])
    except (ValueError, OSError):
        raise PublishError("retained_media_path_invalid") from None
    return candidate


def validate_media(settings: Settings, media: Media) -> Path:
    path = media_path(settings, media.job_id, media.path)
    try:
        with path.open("rb") as file:
            checksum = hashlib.file_digest(file, "sha256").hexdigest()
        if path.stat().st_size != media.size_bytes or checksum != media.checksum_sha256:
            raise PublishError("retained_media_changed")
    except OSError:
        raise PublishError("retained_media_unavailable") from None
    return path


def cleanup_posted(engine: Engine, settings: Settings) -> None:
    """Delete files before rows, so a crash or failed unlink remains retryable."""
    with Session(engine) as session:
        retained = session.exec(
            select(Media).join(Job).where(Job.state == JobState.POSTED).limit(20)
        ).all()
        for media in retained:
            try:
                path = media_path(settings, media.job_id, media.path)
                # New downloads have an isolated attempt directory. Older media may not.
                if path.parent.name == str(media.job_id):
                    path.unlink(missing_ok=True)
                elif path.parent.exists():
                    shutil.rmtree(path.parent)
            except (OSError, PublishError):
                logger.warning("job %s media cleanup deferred", media.job_id)
                continue
            session.delete(media)
        session.commit()
