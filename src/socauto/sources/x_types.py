"""Typed results and safe failures for the X source adapter."""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


class XSourceError(Exception):
    """Base class for safe, machine-readable X source failures."""

    code: ClassVar[str] = "x_source_error"


class XMetadataError(XSourceError):
    code = "x_metadata_unavailable"


class XNoVideoError(XSourceError):
    code = "x_video_not_found"


class XMultipleVideosError(XSourceError):
    code = "x_multiple_videos_unsupported"


class XCookieFileError(XSourceError):
    code = "x_cookie_file_unavailable"


class XDownloadError(XSourceError):
    code = "x_download_failed"


class XIncompatibleMediaError(XSourceError):
    code = "x_media_incompatible"


@dataclass(frozen=True)
class XPostMetadata:
    canonical_url: str
    media_id: str
    caption: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None


@dataclass(frozen=True)
class XDownloadedMedia:
    path: Path
    caption: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    duration_seconds: float | None
    width: int | None
    height: int | None
