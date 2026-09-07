"""Bounded curl_cffi calls with credential-safe failures and no redirects."""

import time
from collections.abc import Callable
from typing import Any, Literal, Protocol, cast

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import ConnectionError, RequestException, Timeout

from socauto.destinations.base import PublishError

CurlSession = curl_requests.Session[curl_requests.Response]
HttpMethod = Literal[
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "OPTIONS",
    "HEAD",
    "TRACE",
    "PATCH",
    "QUERY",
]


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...

    def close(self) -> None: ...


class TikTokHTTP:
    def __init__(
        self,
        session: CurlSession,
        *,
        impersonate: str = "chrome",
        attempts: int = 3,
        timeout: float = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.impersonate = impersonate
        self.attempts = attempts
        self.timeout = timeout
        self.sleep = sleep

    def _send(
        self,
        method: HttpMethod,
        url: str,
        data: bytes | None,
        headers: dict[str, str] | None,
    ) -> _Response:
        return cast(
            _Response,
            self.session.request(
                method,
                url,
                data=data,
                headers=headers,
                timeout=(10, self.timeout),
                allow_redirects=False,
                impersonate=cast(Any, self.impersonate),
                quote=False,
            ),
        )

    def request(
        self,
        method: HttpMethod,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        retry_safe: bool = False,
        publishing: bool = False,
        json_response: bool = True,
    ) -> dict[str, Any]:
        retry_safe = retry_safe and not publishing
        attempts = self.attempts if retry_safe else 1
        for attempt in range(attempts):
            try:
                response = self._send(method, url, data, headers)
            except (ConnectionError, Timeout):
                if attempt + 1 < attempts:
                    self.sleep(2**attempt)
                    continue
                raise PublishError(
                    "upload_outcome_unknown" if publishing else "tiktok_network_error",
                    retryable=retry_safe,
                ) from None
            except RequestException:
                raise PublishError(
                    "upload_outcome_unknown" if publishing else "tiktok_request_failed"
                ) from None
            try:
                if 500 <= response.status_code <= 599:
                    if attempt + 1 < attempts:
                        self.sleep(2**attempt)
                        continue
                    raise PublishError(
                        "upload_outcome_unknown" if publishing else "tiktok_unavailable",
                        retryable=retry_safe,
                    )
                if response.status_code in (401, 403):
                    raise PublishError("tiktok_auth_rejected")
                if response.status_code == 429:
                    raise PublishError("tiktok_rate_limited")
                if not 200 <= response.status_code < 300:
                    raise PublishError(
                        "upload_outcome_unknown" if publishing else "tiktok_http_rejected"
                    )
                if not json_response:
                    return {}
                try:
                    result = response.json()
                    if not isinstance(result, dict):
                        raise ValueError
                except ValueError:
                    raise PublishError(
                        "upload_outcome_unknown" if publishing else "tiktok_invalid_response"
                    ) from None
                return result
            finally:
                response.close()
        raise AssertionError("HTTP attempts exhausted without a result")


def check_status(data: dict[str, Any], *, publishing: bool = False) -> None:
    code = data.get("status_code")
    if type(code) is not int:
        raise PublishError("upload_outcome_unknown" if publishing else "tiktok_invalid_response")
    if code != 0:
        raise PublishError("tiktok_publish_rejected" if publishing else "tiktok_api_rejected")
