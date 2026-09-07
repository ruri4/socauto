"""X/Twitter URL handling and media downloads."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

import yt_dlp
from yt_dlp.utils import DownloadError

from socauto.config import Settings
from socauto.sources.x_output import output_path
from socauto.sources.x_types import (
    XCookieFileError,
    XDownloadedMedia,
    XDownloadError,
    XIncompatibleMediaError,
    XMetadataError,
    XMultipleVideosError,
    XNoVideoError,
    XPostMetadata,
    XSourceError,
)

if TYPE_CHECKING:
    from yt_dlp import _Params

_X_HOSTS = {
    "mobile.twitter.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "www.x.com",
    "x.com",
}
_STATUS_PATH = re.compile(r"^/[^/]+/status/(?P<id>[0-9]+)(?:/.*)?$")


class UnsupportedXUrlError(ValueError):
    """Raised when a URL is not a supported X status URL."""


def canonicalize_x_url(value: str) -> str:
    """Normalize supported X/Twitter status links for durable deduplication."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise UnsupportedXUrlError("invalid X URL") from error

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname not in _X_HOSTS
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsupportedXUrlError("URL must be an HTTP(S) X or Twitter status link")

    match = _STATUS_PATH.fullmatch(parsed.path)
    if match is None:
        raise UnsupportedXUrlError("URL must point to a single X status")

    return f"https://x.com/i/status/{match.group('id')}"


class _YoutubeDL(Protocol):
    def extract_info(self, url: str, *, download: bool = True) -> object: ...


YoutubeDLFactory = Callable[[dict[str, object]], AbstractContextManager[_YoutubeDL]]


class _QuietLogger:
    """Prevent upstream diagnostics from exposing signed media URLs or cookies."""

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(
        self,
        message: str,
        *,
        once: bool = False,
        only_once: bool = False,
    ) -> None:
        pass

    def error(self, message: str) -> None:
        pass

    def stdout(self, message: str) -> None:
        pass

    def stderr(self, message: str) -> None:
        pass


def _youtube_dl_factory(options: dict[str, object]) -> AbstractContextManager[_YoutubeDL]:
    return cast(
        AbstractContextManager[_YoutubeDL],
        yt_dlp.YoutubeDL(cast(_Params, options)),
    )


_FORMAT_SELECTOR = (
    "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a]/"
    "best[vcodec^=avc1][ext=mp4]/best[ext=mp4]"
)


class XSourceAdapter:
    """Extract one X video and download it into its durable job directory."""

    def __init__(
        self,
        settings: Settings,
        *,
        ydl_factory: YoutubeDLFactory = _youtube_dl_factory,
    ) -> None:
        self._settings = settings
        self._ydl_factory = ydl_factory

    def inspect(self, source_url: str) -> XPostMetadata:
        canonical_url = canonicalize_x_url(source_url)
        options = self._base_options()

        try:
            with self._ydl_factory(options) as ydl:
                raw_info = ydl.extract_info(canonical_url, download=False)
            root = _require_mapping(raw_info)
            video = _single_video(root)
        except XSourceError:
            raise
        except DownloadError, OSError:
            raise XMetadataError("could not read X post metadata") from None

        if not _has_video(video):
            raise XNoVideoError("the X post does not contain a downloadable video")

        video_codec, audio_codec = _extract_codecs(video)
        return XPostMetadata(
            canonical_url=canonical_url,
            media_id=_text(video.get("id")) or canonical_url.rsplit("/", maxsplit=1)[-1],
            caption=_text(video.get("description")) or _text(root.get("description")) or "",
            duration_seconds=_nonnegative_float(video.get("duration")),
            width=_positive_int(video.get("width")),
            height=_positive_int(video.get("height")),
            video_codec=video_codec,
            audio_codec=audio_codec,
        )

    def download(
        self,
        source_url: str,
        *,
        job_id: UUID,
        caption_override: str | None = None,
        attempt_id: UUID | None = None,
    ) -> XDownloadedMedia:
        metadata = self.inspect(source_url)
        job_dir = self._prepare_job_dir(job_id, attempt_id)
        options = self._base_options()
        options.update(
            {
                "format": _FORMAT_SELECTOR,
                "merge_output_format": "mp4",
                "noplaylist": False,
                "playlist_items": "1",
                "outtmpl": {"default": str(job_dir / "video.%(ext)s")},
                "overwrites": True,
            }
        )

        try:
            with self._ydl_factory(options) as ydl:
                raw_info = ydl.extract_info(metadata.canonical_url, download=True)
            video = _single_video(_require_mapping(raw_info))
        except XSourceError:
            raise
        except DownloadError, OSError:
            raise XDownloadError("could not download the X video") from None

        path = output_path(video, job_dir)
        video_codec, audio_codec = _extract_codecs(video)
        if video_codec is not None and not video_codec.startswith(("avc1", "h264")):
            raise XIncompatibleMediaError("downloaded X video is not H.264")
        if audio_codec is not None and not audio_codec.startswith(("mp4a", "aac")):
            raise XIncompatibleMediaError("downloaded X video audio is not AAC")

        try:
            path.chmod(0o600)
            size_bytes = path.stat().st_size
            checksum = _sha256(path)
        except OSError:
            raise XDownloadError("could not read the downloaded X video") from None

        return XDownloadedMedia(
            path=path,
            caption=metadata.caption if caption_override is None else caption_override.strip(),
            mime_type="video/mp4",
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            duration_seconds=_nonnegative_float(video.get("duration")) or metadata.duration_seconds,
            width=_positive_int(video.get("width")) or metadata.width,
            height=_positive_int(video.get("height")) or metadata.height,
        )

    def _base_options(self) -> dict[str, object]:
        options: dict[str, object] = {
            "cachedir": False,
            "logger": _QuietLogger(),
            "no_warnings": True,
            "quiet": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
        }
        cookie_file = self._settings.x_cookie_file
        if cookie_file is not None:
            resolved = cookie_file.expanduser().resolve()
            if not resolved.is_file():
                raise XCookieFileError("configured X cookie file is unavailable")
            options["cookiefile"] = str(resolved)
        return options

    def _prepare_job_dir(self, job_id: UUID, attempt_id: UUID | None) -> Path:
        try:
            self._settings.prepare_runtime()
            jobs_dir = self._settings.jobs_dir.resolve()
            job_dir = jobs_dir / str(job_id)
            if attempt_id is not None:
                job_dir /= str(attempt_id)
            if job_dir.resolve() != job_dir:
                raise ValueError("symlinked media directory")
            job_dir.parent.mkdir(mode=0o700, exist_ok=True)
            job_dir.parent.chmod(0o700)
            job_dir.mkdir(mode=0o700, exist_ok=True)
            job_dir.chmod(0o700)
        except OSError, ValueError:
            raise XDownloadError("invalid job media directory") from None
        return job_dir


def _require_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise XMetadataError("X returned invalid media metadata")
    return cast(Mapping[str, object], value)


def _single_video(info: Mapping[str, object]) -> Mapping[str, object]:
    raw_entries = info.get("entries")
    if raw_entries is None:
        return info
    if isinstance(raw_entries, (str, bytes, Mapping)) or not isinstance(raw_entries, Iterable):
        raise XMetadataError("X returned invalid media entries")

    entries: list[Mapping[str, object]] = []
    for raw_entry in raw_entries:
        if raw_entry is None:
            continue
        entries.append(_require_mapping(raw_entry))
        if len(entries) > 1:
            raise XMultipleVideosError("X posts with multiple videos are not supported")
    if not entries:
        raise XNoVideoError("the X post does not contain a downloadable video")
    return entries[0]


def _has_video(info: Mapping[str, object]) -> bool:
    if _codec(info.get("vcodec")) is not None:
        return True
    raw_formats = info.get("formats")
    if isinstance(raw_formats, Iterable) and not isinstance(raw_formats, (str, bytes, Mapping)):
        for raw_format in raw_formats:
            if isinstance(raw_format, Mapping) and _codec(raw_format.get("vcodec")) is not None:
                return True
    return _text(info.get("ext")) in {"mp4", "mov", "webm"}


def _extract_codecs(info: Mapping[str, object]) -> tuple[str | None, str | None]:
    video_codec = _codec(info.get("vcodec"))
    audio_codec = _codec(info.get("acodec"))
    raw_formats = info.get("requested_formats")
    if isinstance(raw_formats, Iterable) and not isinstance(raw_formats, (str, bytes, Mapping)):
        for raw_format in raw_formats:
            if not isinstance(raw_format, Mapping):
                continue
            video_codec = video_codec or _codec(raw_format.get("vcodec"))
            audio_codec = audio_codec or _codec(raw_format.get("acodec"))
    return video_codec, audio_codec


def _codec(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    return lowered if lowered != "none" else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _nonnegative_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    return None


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as media_file:
        for block in iter(lambda: media_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
