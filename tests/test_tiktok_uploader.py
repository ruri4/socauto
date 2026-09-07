import json
import zlib
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import Timeout

from socauto.config import Settings
from socauto.destinations.base import PublishError
from socauto.destinations.tiktok.session import TikTokCookie, TikTokSession
from socauto.destinations.tiktok.transfer import CHUNK_SIZE, UploadNode, storage_url
from socauto.destinations.tiktok.uploader import TikTokDestination, publish_payload


class FakeSigner:
    def __init__(self) -> None:
        self.url = ""
        self.user_agent = ""

    def sign(self, url: str, user_agent: str) -> str:
        self.user_agent = user_agent
        self.url = url + "&verifyFp=test-fp&_signature=test-signature&X-Bogus=test-bogus"
        return self.url


class Call:
    def __init__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body


class CurlResponse:
    def __init__(self, payload: object, status: int, url: str) -> None:
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.url = url

    def json(self) -> object:
        return self._payload

    def close(self) -> None:
        return None


class CurlSession:
    def __init__(self, upstream: "Upstream") -> None:
        self.upstream = upstream
        self.headers: dict[str, str] = {}
        self.cookies = curl_requests.Cookies()
        self.trust_env = True

    def __enter__(self) -> "CurlSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.upstream.closed += 1

    def request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> CurlResponse:
        merged = dict(self.headers)
        merged.update(headers or {})
        host = urlsplit(url).hostname or ""
        cookie_values = [
            f"{name}={value}"
            for name in self.cookies
            if (host == "tiktok.com" or host.endswith(".tiktok.com"))
            and (value := self.cookies.get(name))
        ]
        if cookie_values:
            merged["Cookie"] = "; ".join(cookie_values)
        return self.upstream.respond(method, url, merged, data)


class Upstream:
    """Exercise curl session preparation, cookies and headers, replacing only the wire."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.closed = 0
        self.failure: tuple[str, int, object] | None = None
        self.timeout_at: str | None = None

    def session(self) -> CurlSession:
        return CurlSession(self)

    def respond(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> CurlResponse:
        self.calls.append(Call(method, url, headers, body))
        if self.timeout_at and self.timeout_at in url:
            raise Timeout("secret-token " + url)
        status = 200
        payload: object
        if self.failure and self.failure[0] in url:
            _, status, payload = self.failure
        elif "/project/create/" in url:
            payload = {"status_code": 0, "project": {"project_id": "project-1"}}
        elif "/upload/auth/" in url:
            payload = {
                "status_code": 0,
                "video_token_v5": {
                    "access_key_id": "test-access",
                    "secret_acess_key": "test-secret",
                    "session_token": "test-session-token",
                },
            }
        elif "ApplyUploadInner" in url:
            payload = {
                "ResponseMetadata": {},
                "Result": {
                    "InnerUploadAddress": {
                        "UploadNodes": [
                            {
                                "Vid": "video-1",
                                "SessionKey": "vod-session",
                                "UploadHost": "upload.byteoversea.com",
                                "StoreInfos": [{"StoreUri": "tos/video", "Auth": "storage-secret"}],
                            }
                        ]
                    }
                },
            }
        elif "CommitUploadInner" in url:
            payload = {
                "ResponseMetadata": {},
                "Result": {"Results": [{"Vid": "video-1", "Code": 2000}]},
            }
        elif "phase=transfer" in url or "phase=finish" in url:
            payload = {"code": 2000}
        elif method == "HEAD":
            payload = {}
        elif "/project/post/" in url:
            payload = {"status_code": 0, "item_id": "12345"}
        else:
            raise AssertionError("unexpected HTTP step")
        return CurlResponse(payload, status, url)


def credentials() -> TikTokSession:
    return TikTokSession(
        user_agent="test-agent",
        cookies=[
            TikTokCookie(name="sessionid", value="secret-session", domain=".tiktok.com"),
            TikTokCookie(name="tt-target-idc", value="useast2a", domain=".tiktok.com"),
            TikTokCookie(name="msToken", value="secret-token", domain=".tiktok.com"),
        ],
    )


def destination(tmp_path: Path, upstream: Upstream) -> tuple[TikTokDestination, FakeSigner, Path]:
    def factory() -> CurlSession:
        return upstream.session()

    signer = FakeSigner()
    target = TikTokDestination(
        Settings(data_dir=tmp_path),
        credentials(),
        signer=signer,
        session_factory=cast(Any, factory),
    )
    media = tmp_path / "video.mp4"
    media.write_bytes(b"a" * CHUNK_SIZE + b"b")
    return target, signer, media


def test_full_upload_prepared_requests_and_lifecycle(tmp_path: Path) -> None:
    upstream = Upstream()
    target, signer, media = destination(tmp_path, upstream)
    result = target.publish(media, "hello #world")
    assert result.video_id == "video-1" and result.post_id == "12345"
    assert result.post_url is None
    assert len(upstream.calls) == 9 and upstream.closed == 2
    assert signer.user_agent == "test-agent"
    assert upstream.calls[-1].url == signer.url
    for call in upstream.calls:
        assert call.headers["User-Agent"] == signer.user_agent
        if urlsplit(str(call.url)).hostname == "www.tiktok.com":
            assert "secret-session" in call.headers["Cookie"]
        else:
            assert "Cookie" not in call.headers
    chunks = upstream.calls[3:5]
    assert [len(call.body) for call in chunks if isinstance(call.body, bytes)] == [CHUNK_SIZE, 1]
    crcs = [f"{zlib.crc32(data):08x}" for data in (b"a" * CHUNK_SIZE, b"b")]
    assert [call.headers["Content-Crc32"] for call in chunks] == crcs
    assert upstream.calls[5].body == f"1:{crcs[0]},2:{crcs[1]}".encode()
    assert (
        parse_qs(urlsplit(str(chunks[0].url)).query)["uploadID"]
        == parse_qs(urlsplit(str(chunks[1].url)).query)["uploadID"]
    )
    for index in (2, 6):
        assert upstream.calls[index].headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    body = upstream.calls[-1].body
    assert isinstance(body, bytes)
    payload = json.loads(body)
    assert payload["feature_common_info_list"][0]["privacy_setting_info"]["visibility_type"] == 1
    assert media.exists()  # Worker, not uploader, owns cleanup.


def test_guard_aborts_before_irreversible_publish(tmp_path: Path) -> None:
    upstream = Upstream()
    target, _, media = destination(tmp_path, upstream)

    def lost_claim() -> None:
        raise RuntimeError("lost claim")

    with pytest.raises(RuntimeError, match="lost claim"):
        target.publish(media, "caption", before_publish=lost_claim)
    assert len(upstream.calls) == 8 and upstream.closed == 2
    assert not any("/project/post/" in str(call.url) for call in upstream.calls)
    assert media.is_file()


@pytest.mark.parametrize(
    ("step", "status", "payload", "code"),
    [
        ("/project/create/", 200, {}, "tiktok_invalid_response"),
        ("/upload/auth/", 403, {"secret": "secret-token"}, "tiktok_auth_rejected"),
        ("/upload/auth/", 200, {"status_code": 0}, "tiktok_invalid_upload_credentials"),
        (
            "ApplyUploadInner",
            200,
            {"ResponseMetadata": {"Error": {"Code": "bad"}}},
            "tiktok_vod_rejected",
        ),
        (
            "phase=transfer",
            200,
            {"code": 2000, "data": {"crc32": "bad"}},
            "tiktok_chunk_crc_mismatch",
        ),
        ("phase=finish", 200, {"code": 4}, "tiktok_chunk_rejected"),
        (
            "CommitUploadInner",
            200,
            {"ResponseMetadata": {}, "Result": {"Results": []}},
            "tiktok_invalid_commit_response",
        ),
        (
            "/project/post/",
            200,
            {"status_code": 9, "message": "secret-token"},
            "tiktok_publish_rejected",
        ),
        ("/project/post/", 200, {"status_code": False}, "upload_outcome_unknown"),
        ("/project/post/", 200, [], "upload_outcome_unknown"),
        ("/project/post/", 503, {}, "upload_outcome_unknown"),
    ],
)
def test_fail_closed_without_secret_diagnostics(
    tmp_path: Path,
    step: str,
    status: int,
    payload: object,
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = Upstream()
    upstream.failure = (step, status, payload)
    target, _, media = destination(tmp_path, upstream)
    with pytest.raises(PublishError) as caught:
        target.publish(media, "test")
    assert caught.value.code == code and not caught.value.retryable
    assert sum(step in str(call.url) for call in upstream.calls) == 1
    assert upstream.closed == 2 and media.exists()
    assert "secret-token" not in str(caught.value) + caplog.text


def test_publish_timeout_is_never_retried(tmp_path: Path) -> None:
    upstream = Upstream()
    upstream.timeout_at = "/project/post/"
    target, _, media = destination(tmp_path, upstream)
    with pytest.raises(PublishError, match="upload outcome unknown") as caught:
        target.publish(media, "test")
    assert not caught.value.retryable and caught.value.__suppress_context__
    assert sum("/project/post/" in str(call.url) for call in upstream.calls) == 1
    assert upstream.closed == 2


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "evil.test",
        "evil.test/tiktok.com",
        "tiktok.com.evil.test",
        "user@tiktok.com",
        "tiktok.com:443",
    ],
)
def test_upload_host_allowlist(host: str) -> None:
    node = UploadNode.model_validate(
        {
            "Vid": "video",
            "SessionKey": "secret",
            "UploadHost": host,
            "StoreInfos": [{"StoreUri": "video", "Auth": "secret"}],
        }
    )
    with pytest.raises(PublishError, match="upload host rejected"):
        storage_url(node)


def test_expired_and_wrong_domain_sessions_fail_before_network(tmp_path: Path) -> None:
    upstream = Upstream()
    target, _, media = destination(tmp_path, upstream)
    target.session.cookies[0].expires_at = 1
    with pytest.raises(PublishError, match="session expired"):
        target.publish(media, "test")
    target.session = credentials()
    target.session.cookies[0].domain = "evil.test"
    with pytest.raises(PublishError, match="session invalid"):
        target.publish(media, "test")
    assert not upstream.calls


def test_utf16_hashtags() -> None:
    payload = publish_payload("creation", "video", "😀 #猫 #hello", 1)
    tags = payload["single_post_req_list"][0]["single_post_feature_info"]["text_extra"]
    markup = payload["single_post_req_list"][0]["single_post_feature_info"]["markup_text"]
    assert markup == '😀 <h id="0">#猫</h> <h id="1">#hello</h>'
    assert [(tag["start"], tag["end"], tag["hashtag_name"]) for tag in tags] == [
        (3, 5, "猫"),
        (6, 12, "hello"),
    ]
