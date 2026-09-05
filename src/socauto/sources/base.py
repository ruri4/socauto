"""Synchronous media source boundary for the worker."""

from typing import Protocol
from uuid import UUID

from socauto.sources.x_types import XDownloadedMedia


class Source(Protocol):
    def download(
        self,
        source_url: str,
        *,
        job_id: UUID,
        caption_override: str | None = None,
        attempt_id: UUID | None = None,
    ) -> XDownloadedMedia: ...
