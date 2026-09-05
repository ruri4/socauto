"""Bun signer IPC; secrets travel over stdin, never argv or diagnostics."""

import json
import os
import signal
import subprocess
from pathlib import Path
from shutil import which
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit

from socauto.config import Settings
from socauto.destinations.base import PublishError

PUBLISH_URL = "https://www.tiktok.com/tiktok/web/project/post/v1/"


class Signer(Protocol):
    def sign(self, url: str, user_agent: str) -> str: ...


def validate_signed_url(original: str, signed: str) -> None:
    before, after = urlsplit(original), urlsplit(signed)
    if (after.scheme, after.netloc, after.path) != (before.scheme, before.netloc, before.path):
        raise PublishError("tiktok_signer_invalid_output")
    items = parse_qsl(after.query, keep_blank_values=True)
    query = dict(items)
    if after.fragment or len(items) != len(query):
        raise PublishError("tiktok_signer_invalid_output")
    source = dict(parse_qsl(before.query, keep_blank_values=True))
    if any(query.get(key) != value for key, value in source.items()):
        raise PublishError("tiktok_signer_invalid_output")
    if set(query) != set(source) | {"verifyFp", "_signature", "X-Bogus"}:
        raise PublishError("tiktok_signer_invalid_output")
    if any(not query.get(key) for key in ("verifyFp", "_signature", "X-Bogus")):
        raise PublishError("tiktok_signer_invalid_output")


class BunSigner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def sign(self, url: str, user_agent: str) -> str:
        binary = self.settings.tiktok_chromium_binary
        executable = (
            str(binary)
            if binary
            else next(
                (
                    path
                    for name in ("chromium-browser", "chromium", "google-chrome")
                    if (path := which(name))
                ),
                None,
            )
        )
        bun = which("bun")
        script: Path = self.settings.tiktok_signer_script.resolve()
        if not bun or not executable or not script.is_file():
            raise PublishError("tiktok_signer_unavailable")
        payload = json.dumps({"url": url, "user_agent": user_agent, "executable_path": executable})
        try:
            with subprocess.Popen(
                [bun, "run", str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            ) as process:
                try:
                    output, _ = process.communicate(
                        payload, timeout=self.settings.tiktok_signer_timeout_seconds
                    )
                except subprocess.TimeoutExpired:
                    # Kill the process group, including Chromium, on the Linux worker host.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise PublishError("tiktok_signer_timeout") from None
                if process.returncode != 0 or len(output) > 32768:
                    raise PublishError("tiktok_signer_failed")
        except OSError:
            raise PublishError("tiktok_signer_unavailable") from None
        try:
            result = json.loads(output)
            if not isinstance(result, dict) or result.get("user_agent") != user_agent:
                raise ValueError
            signed = result.get("signed_url")
            if not isinstance(signed, str):
                raise ValueError
            validate_signed_url(url, signed)
            return signed
        except (ValueError, TypeError):
            raise PublishError("tiktok_signer_invalid_output") from None
