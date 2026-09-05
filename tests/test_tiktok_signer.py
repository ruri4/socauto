import json
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
import requests

from socauto.config import Settings
from socauto.destinations.base import PublishError
from socauto.destinations.tiktok import aws, signer
from socauto.destinations.tiktok.aws import UploadCredentials, VODAuth
from socauto.destinations.tiktok.signer import PUBLISH_URL, BunSigner, validate_signed_url

URL = PUBLISH_URL + "?aid=1988&msToken=secret-token"
SIGNED = URL + "&verifyFp=test&_signature=test-signature&X-Bogus=test-bogus"


def test_vod_signature_matches_botocore_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    # Independently verified with botocore.auth.SigV4Auth; no AWS SDK needed at runtime.
    clock = Mock()
    clock.now.return_value = datetime(2026, 9, 6, tzinfo=UTC)
    monkeypatch.setattr(aws, "datetime", clock)
    credentials = UploadCredentials.model_validate(
        {
            "access_key_id": "TESTACCESS",
            "secret_acess_key": "testsecret",
            "session_token": "testtoken",
        }
    )
    request = requests.Request(
        "POST",
        "https://www.tiktok.com/top/v1?Action=CommitUploadInner&Version=2020-11-19&SpaceName=tiktok",
        data=b'{"SessionKey":"test"}',
    ).prepare()
    assert VODAuth(credentials)(request) is request
    assert request.headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=TESTACCESS/20260906/ap-singapore-1/vod/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date;x-amz-security-token, "
        "Signature=48a9e07d237c8422914dac096a28aaac83ae6fc00c388f3f6e165ca7037d9244"
    )
    assert "testsecret" not in repr(credentials) and "testtoken" not in repr(credentials)


@pytest.mark.parametrize(
    "signed",
    [
        SIGNED.replace("www.tiktok.com", "evil.test"),
        SIGNED.replace("secret-token", "changed"),
        SIGNED + "&aid=1988",
        SIGNED + "#fragment",
        URL,
        SIGNED + "&extra=1",
        SIGNED.replace("test-bogus", ""),
    ],
)
def test_signer_output_cannot_change_request(signed: str) -> None:
    with pytest.raises(PublishError, match="signer invalid output"):
        validate_signed_url(URL, signed)


def signer_process(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, Mock]:
    process = MagicMock()
    process.__enter__.return_value = process
    process.returncode = 0
    process.pid = 123
    process.communicate.return_value = (
        json.dumps({"signed_url": SIGNED, "user_agent": "test-agent"}),
        None,
    )
    popen = Mock(return_value=process)
    monkeypatch.setattr("socauto.destinations.tiktok.signer.subprocess.Popen", popen)
    monkeypatch.setattr(signer, "which", lambda name: "/usr/bin/" + name)
    return process, popen


def test_signer_ipc_keeps_secrets_off_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    process, popen = signer_process(monkeypatch)
    assert BunSigner(Settings()).sign(URL, "test-agent") == SIGNED
    assert "secret-token" not in repr(popen.call_args)
    assert "secret-token" in process.communicate.call_args.args[0]
    assert popen.call_args.kwargs["stderr"] == subprocess.DEVNULL
    process.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        "[]",
        '{"signed_url":"secret-token"}',
        json.dumps({"signed_url": SIGNED, "user_agent": "wrong-agent"}),
    ],
)
def test_signer_invalid_stdout_is_safe(monkeypatch: pytest.MonkeyPatch, output: str) -> None:
    process, _ = signer_process(monkeypatch)
    process.communicate.return_value = (output, None)
    with pytest.raises(PublishError, match="signer invalid output") as caught:
        BunSigner(Settings()).sign(URL, "test-agent")
    assert "secret-token" not in str(caught.value)


def test_signer_timeout_kills_browser_group(monkeypatch: pytest.MonkeyPatch) -> None:
    process, _ = signer_process(monkeypatch)
    process.communicate.side_effect = [subprocess.TimeoutExpired("bun", 45), ("", None)]
    kill = Mock()
    monkeypatch.setattr("socauto.destinations.tiktok.signer.os.killpg", kill)
    with pytest.raises(PublishError, match="signer timeout"):
        BunSigner(Settings()).sign(URL, "test-agent")
    kill.assert_called_once_with(123, signal.SIGKILL)
    assert process.communicate.call_count == 2
    process.__exit__.assert_called_once()


def test_signer_missing_asset_fails_safely(tmp_path: Path) -> None:
    with pytest.raises(PublishError, match="signer unavailable"):
        BunSigner(Settings(tiktok_signer_script=tmp_path / "missing.js")).sign(URL, "test-agent")
