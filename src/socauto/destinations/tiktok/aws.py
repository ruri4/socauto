"""Minimal AWS Signature V4 for TikTok's temporary VOD credentials."""

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlsplit

from pydantic import BaseModel, Field, SecretStr


class UploadCredentials(BaseModel):
    access_key_id: SecretStr = Field(min_length=1)
    secret_acess_key: SecretStr = Field(min_length=1)  # Upstream's spelling.
    session_token: SecretStr = Field(min_length=1)


class VODAuth:
    def __init__(self, credentials: UploadCredentials) -> None:
        self.credentials = credentials

    def headers(
        self, method: str, url_string: str, body: bytes | str | None = None
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        date = stamp[:8]
        url = urlsplit(url_string)
        body = body or b""
        if isinstance(body, str):
            body = body.encode()
        if not isinstance(body, bytes):
            raise TypeError("VOD signing requires a byte body")
        digest = hashlib.sha256(body).hexdigest()
        headers = {
            "host": url.netloc,
            "x-amz-content-sha256": digest,
            "x-amz-date": stamp,
            "x-amz-security-token": self.credentials.session_token.get_secret_value(),
        }
        names = ";".join(sorted(headers))
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
        query = "&".join(
            f"{key}={value}"
            for key, value in sorted(
                (quote(key, safe="-_.~"), quote(value, safe="-_.~"))
                for key, value in parse_qsl(url.query, keep_blank_values=True)
            )
        )
        canonical = "\n".join([method, url.path or "/", query, canonical_headers, names, digest])
        scope = f"{date}/ap-singapore-1/vod/aws4_request"
        to_sign = (
            f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
        )
        key = ("AWS4" + self.credentials.secret_acess_key.get_secret_value()).encode()
        for part in (date, "ap-singapore-1", "vod", "aws4_request"):
            key = hmac.digest(key, part.encode(), "sha256")
        signature = hmac.new(key, to_sign.encode(), "sha256").hexdigest()
        access = self.credentials.access_key_id.get_secret_value()
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
            f"SignedHeaders={names}, Signature={signature}"
        )
        return headers
