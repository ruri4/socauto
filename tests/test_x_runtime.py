"""Exercise real yt-dlp downloads/FFmpeg against synthetic loopback media, never X."""

import json
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
import yt_dlp

from socauto.config import Settings
from socauto.sources.x import XSourceAdapter

if TYPE_CHECKING:
    from yt_dlp import _Params
    from yt_dlp.extractor.common import _InfoDict


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def media_server(tmp_path: Path) -> Iterator[str]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("offline media runtime tests require FFmpeg and ffprobe")
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "0.3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(tmp_path / "combined.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    for filename, selection in (("video.mp4", "-an"), ("audio.m4a", "-vn")):
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(tmp_path / "combined.mp4"),
                selection,
                "-c",
                "copy",
                str(tmp_path / filename),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("merge", [False, True], ids=["progressive", "split-av-playlist"])
def test_real_download_and_merge(media_server: str, tmp_path: Path, merge: bool) -> None:
    closed: list[bool] = []

    class FixtureDownloader:
        def __init__(self, downloader: yt_dlp.YoutubeDL) -> None:
            self.downloader = downloader

        def extract_info(self, url: str, *, download: bool = True) -> object:
            assert url == "https://x.com/i/status/123"
            formats = [
                {
                    "format_id": "combined",
                    "url": media_server + "/combined.mp4",
                    "ext": "mp4",
                    "vcodec": "avc1.64000a",
                    "acodec": "mp4a.40.2",
                    "width": 64,
                    "height": 64,
                }
            ]
            if merge:
                formats = [
                    {
                        "format_id": "video",
                        "url": media_server + "/video.mp4",
                        "ext": "mp4",
                        "vcodec": "avc1.64000a",
                        "acodec": "none",
                        "width": 64,
                        "height": 64,
                    },
                    {
                        "format_id": "audio",
                        "url": media_server + "/audio.m4a",
                        "ext": "m4a",
                        "vcodec": "none",
                        "acodec": "mp4a.40.2",
                    },
                ]
            info = {
                "id": "123",
                "title": "synthetic video",
                "description": "fixture caption",
                "extractor": "fixture",
                "extractor_key": "Fixture",
                "duration": 0.3,
                "webpage_url": url,
                "formats": formats,
            }
            # Only replace remote metadata extraction. Keep real format selection,
            # HTTP downloading, postprocessing and result-shape behavior.
            if merge:
                return self.downloader.process_ie_result(
                    cast(
                        "_InfoDict",
                        {
                            "_type": "playlist",
                            "id": "123",
                            "entries": [info],
                            "extractor": "fixture",
                            "extractor_key": "Fixture",
                        },
                    ),
                    download=download,
                )
            return self.downloader.process_ie_result(cast("_InfoDict", info), download=download)

    @contextmanager
    def factory(options: dict[str, object]) -> Iterator[FixtureDownloader]:
        options["proxy"] = ""  # Never send loopback fixtures through an operator's proxy.
        with yt_dlp.YoutubeDL(cast("_Params", options)) as downloader:
            yield FixtureDownloader(downloader)
        closed.append(True)

    settings = Settings(data_dir=tmp_path / "data", x_cookie_file=None)
    job_id, attempt_id = uuid4(), uuid4()
    result = XSourceAdapter(settings, ydl_factory=factory).download(
        "https://twitter.com/fixture/status/123", job_id=job_id, attempt_id=attempt_id
    )
    assert closed == [True, True]
    assert result.path == settings.jobs_dir / str(job_id) / str(attempt_id) / "video.mp4"
    assert result.path.stat().st_mode & 0o777 == 0o600
    assert result.path.parent.stat().st_mode & 0o777 == 0o700
    assert result.size_bytes == result.path.stat().st_size > 0
    assert result.checksum_sha256 == sha256(result.path.read_bytes()).hexdigest()
    assert result.caption == "fixture caption"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(result.path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    codecs = {stream["codec_name"] for stream in json.loads(probe.stdout)["streams"]}
    assert codecs == {"h264", "aac"}
