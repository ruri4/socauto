"""Resolve exactly one finished yt-dlp output, never a pre-merge format path."""

from collections.abc import Mapping
from pathlib import Path

from socauto.sources.x_types import XDownloadError


def output_path(info: Mapping[str, object], job_dir: Path) -> Path:
    downloads = info.get("requested_downloads")
    if downloads is not None:
        if not isinstance(downloads, list) or len(downloads) != 1:
            raise XDownloadError("yt-dlp did not report exactly one downloaded file")
        if not isinstance(downloads[0], Mapping):
            raise XDownloadError("yt-dlp reported invalid download metadata")
        value = downloads[0].get("filepath")
    else:
        value = info.get("filepath") or info.get("_filename")
    if not isinstance(value, str):
        raise XDownloadError("yt-dlp did not report the downloaded file")
    path = Path(value).resolve()
    if path != job_dir / "video.mp4":
        raise XDownloadError("yt-dlp reported an invalid output path")
    if not path.is_file():
        raise XDownloadError("yt-dlp did not produce the expected MP4 file")
    return path
