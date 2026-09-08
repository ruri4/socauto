from collections.abc import Iterator
from contextlib import AbstractContextManager
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from yt_dlp.utils import DownloadError

from socauto.config import Settings
from socauto.sources.x import XSourceAdapter, _youtube_dl_factory
from socauto.sources.x_output import output_path
from socauto.sources.x_types import (
    XCookieFileError,
    XDownloadError,
    XIncompatibleMediaError,
    XMetadataError,
    XMultipleVideosError,
    XNoVideoError,
)


class FakeYoutubeDL(AbstractContextManager["FakeYoutubeDL"]):
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.entered = False
        self.exited = False
        self.calls: list[tuple[str, bool]] = []

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True

    def extract_info(self, url: str, *, download: bool = True) -> object:
        self.calls.append((url, download))
        if self.error is not None:
            raise self.error
        return self.result


class FakeFactory:
    def __init__(self, instances: Iterator[FakeYoutubeDL]) -> None:
        self._instances = instances
        self.options: list[dict[str, object]] = []
        self.created: list[FakeYoutubeDL] = []

    def __call__(self, options: dict[str, object]) -> AbstractContextManager[FakeYoutubeDL]:
        instance = next(self._instances)
        self.options.append(options)
        self.created.append(instance)
        return instance


def video_info(**changes: object) -> dict[str, object]:
    info: dict[str, object] = {
        "id": "media-123",
        "description": "tweet caption https://t.co/media",
        "duration": 12.5,
        "width": 1080,
        "height": 1920,
        "formats": [{"vcodec": "avc1.640028", "acodec": "mp4a.40.2"}],
        "vcodec": "avc1.640028",
        "acodec": "mp4a.40.2",
        "ext": "mp4",
    }
    info.update(changes)
    return info


def adapter_with(
    tmp_path: Path,
    *instances: FakeYoutubeDL,
    cookie_file: Path | None = None,
) -> tuple[XSourceAdapter, FakeFactory]:
    factory = FakeFactory(iter(instances))
    adapter = XSourceAdapter(
        Settings(data_dir=tmp_path / "data", x_cookie_file=cookie_file),
        ydl_factory=factory,
    )
    return adapter, factory


def test_default_youtube_dl_factory_constructs_without_network() -> None:
    with _youtube_dl_factory({"cachedir": False, "no_warnings": True, "quiet": True}) as downloader:
        assert downloader is not None


def test_inspect_extracts_single_video_metadata(tmp_path: Path) -> None:
    ydl = FakeYoutubeDL(video_info())
    adapter, factory = adapter_with(tmp_path, ydl)

    metadata = adapter.inspect("https://twitter.com/user/status/123?ref=secret")

    assert metadata.canonical_url == "https://x.com/i/status/123"
    assert metadata.media_id == "media-123"
    assert metadata.caption == "tweet caption https://t.co/media"
    assert metadata.duration_seconds == 12.5
    assert (metadata.width, metadata.height) == (1080, 1920)
    assert metadata.video_codec == "avc1.640028"
    assert metadata.audio_codec == "mp4a.40.2"
    assert ydl.calls == [("https://x.com/i/status/123", False)]
    assert ydl.entered and ydl.exited
    assert factory.options[0]["quiet"] is True


@pytest.mark.parametrize("attempt_id", [None, UUID("ef4d80cb-71d3-4aa8-8d87-83ed93dbd785")])
def test_download_uses_private_controlled_mp4_and_override(
    tmp_path: Path,
    attempt_id: UUID | None,
) -> None:
    job_id = UUID("54a035f4-af85-4fba-a043-a58792135f67")
    directory = tmp_path / "data" / "jobs" / str(job_id)
    if attempt_id is not None:
        directory /= str(attempt_id)
    output = directory / "video.mp4"
    output.parent.mkdir(parents=True)
    content = b"downloaded video"
    output.write_bytes(content)
    inspected = FakeYoutubeDL(video_info())
    downloaded = FakeYoutubeDL(video_info(filepath=str(output)))
    adapter, factory = adapter_with(tmp_path, inspected, downloaded)

    result = adapter.download(
        "https://x.com/user/status/123",
        job_id=job_id,
        caption_override="  custom caption  ",
        attempt_id=attempt_id,
    )

    assert result.path == output
    assert result.caption == "custom caption"
    assert result.mime_type == "video/mp4"
    assert result.size_bytes == len(content)
    assert result.checksum_sha256 == sha256(content).hexdigest()
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert output.parent.parent.stat().st_mode & 0o777 == 0o700
    assert output.stat().st_mode & 0o777 == 0o600
    download_options = factory.options[1]
    assert download_options["merge_output_format"] == "mp4"
    assert download_options["playlist_items"] == "1"
    assert download_options["retries"] == 3
    assert download_options["socket_timeout"] == 30
    assert download_options["outtmpl"] == {"default": str(output.parent / "video.%(ext)s")}
    selected_format = download_options["format"]
    assert isinstance(selected_format, str)
    assert "vcodec^=avc1" in selected_format
    assert downloaded.calls == [("https://x.com/i/status/123", True)]
    assert all(instance.entered and instance.exited for instance in factory.created)


def test_download_uses_tweet_text_without_override(tmp_path: Path) -> None:
    job_id = uuid4()
    output = tmp_path / "data" / "jobs" / str(job_id) / "video.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"video")
    adapter, _ = adapter_with(
        tmp_path,
        FakeYoutubeDL(video_info(description="  source caption  ")),
        FakeYoutubeDL(video_info(filepath=str(output))),
    )

    result = adapter.download("https://x.com/user/status/123", job_id=job_id)

    assert result.caption == "source caption"


def test_inspect_rejects_multiple_videos_before_download(tmp_path: Path) -> None:
    adapter, factory = adapter_with(
        tmp_path,
        FakeYoutubeDL({"entries": [video_info(id="one"), video_info(id="two")]}),
    )

    with pytest.raises(XMultipleVideosError) as error:
        adapter.download("https://x.com/user/status/123", job_id=uuid4())

    assert error.value.code == "x_multiple_videos_unsupported"
    assert len(factory.created) == 1


def test_inspect_rejects_post_without_video(tmp_path: Path) -> None:
    adapter, _ = adapter_with(tmp_path, FakeYoutubeDL({"id": "123", "ext": "jpg"}))

    with pytest.raises(XNoVideoError) as error:
        adapter.inspect("https://x.com/user/status/123")

    assert error.value.code == "x_video_not_found"


def test_cookie_file_is_forwarded_without_exposing_it_in_errors(tmp_path: Path) -> None:
    cookie_file = tmp_path / "x-private-cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    upstream = FakeYoutubeDL(error=DownloadError(f"failed using {cookie_file}: super-secret"))
    adapter, factory = adapter_with(tmp_path, upstream, cookie_file=cookie_file)

    with pytest.raises(XMetadataError) as error:
        adapter.inspect("https://x.com/user/status/123")

    assert "super-secret" not in str(error.value)
    assert str(cookie_file) not in str(error.value)
    assert factory.options[0]["cookiefile"] == str(cookie_file.resolve())
    assert upstream.exited


def test_missing_cookie_file_fails_before_opening_yt_dlp(tmp_path: Path) -> None:
    adapter, factory = adapter_with(
        tmp_path,
        FakeYoutubeDL(video_info()),
        cookie_file=tmp_path / "missing.txt",
    )

    with pytest.raises(XCookieFileError) as error:
        adapter.inspect("https://x.com/user/status/123")

    assert error.value.code == "x_cookie_file_unavailable"
    assert factory.created == []


def test_download_rejects_reported_path_outside_job_directory(tmp_path: Path) -> None:
    outside = tmp_path / "video.mp4"
    outside.write_bytes(b"video")
    adapter, _ = adapter_with(
        tmp_path,
        FakeYoutubeDL(video_info()),
        FakeYoutubeDL(video_info(filepath=str(outside))),
    )

    with pytest.raises(XDownloadError, match="invalid output path"):
        adapter.download("https://x.com/user/status/123", job_id=uuid4())


def test_download_rejects_incompatible_video_codec(tmp_path: Path) -> None:
    job_id = uuid4()
    output = tmp_path / "data" / "jobs" / str(job_id) / "video.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"video")
    adapter, _ = adapter_with(
        tmp_path,
        FakeYoutubeDL(video_info()),
        FakeYoutubeDL(video_info(filepath=str(output), vcodec="vp9")),
    )

    with pytest.raises(XIncompatibleMediaError) as error:
        adapter.download("https://x.com/user/status/123", job_id=job_id)

    assert error.value.code == "x_media_incompatible"


@pytest.mark.parametrize("downloads", [[], [{}, {}], "invalid", [None], [{}]])
def test_download_rejects_ambiguous_or_incomplete_outputs(
    tmp_path: Path, downloads: object
) -> None:
    output = tmp_path / "video.mp4"
    output.write_bytes(b"video")
    # A plausible top-level filename must not hide an incomplete download result.
    with pytest.raises(XDownloadError):
        output_path({"requested_downloads": downloads, "_filename": str(output)}, tmp_path)


def test_download_uses_finished_path_instead_of_premerge_filename(tmp_path: Path) -> None:
    output = tmp_path / "video.mp4"
    output.write_bytes(b"video")
    info = {
        "requested_downloads": [{"filepath": str(output), "_filename": "video.f1.mp4"}],
        "_filename": "video.f1.mp4",
    }
    assert output_path(info, tmp_path) == output


def test_download_rejects_symlinked_output(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    output = tmp_path / "video.mp4"
    output.symlink_to(outside)
    with pytest.raises(XDownloadError, match="invalid output path"):
        output_path({"requested_downloads": [{"filepath": str(output)}]}, tmp_path)
