"""Bounded HTTP calls with credential-safe failures and no redirects."""

import logging
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

import requests
from requests.auth import AuthBase

from socauto.destinations.base import PublishError

_private_request: ContextVar[bool] = ContextVar("tiktok_private_request", default=False)


class _TransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # urllib3 DEBUG messages include signed URLs. Suppress only this call context.
        return not _private_request.get()


for _namespace in ("urllib3.connectionpool", "urllib3.util.retry"):
    logging.getLogger(_namespace).addFilter(_TransportFilter())


class TikTokHTTP:
    def __init__(
        self,
        session: requests.Session,
        *,
        attempts: int = 3,
        timeout: float = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.attempts = attempts
        self.timeout = timeout
        self.sleep = sleep

    def _send(
        self,
        method: str,
        url: str,
        data: bytes | None,
        headers: dict[str, str] | None,
        auth: AuthBase | None,
    ) -> requests.Response:
        token = _private_request.set(True)
        try:
            return self.session.request(
                method,
                url,
                data=data,
                headers=headers,
                auth=auth,
                timeout=(10, self.timeout),
                allow_redirects=False,
            )
        finally:
            _private_request.reset(token)

    def request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        auth: AuthBase | None = None,
        retry_safe: bool = False,
        publishing: bool = False,
        json_response: bool = True,
    ) -> dict[str, Any]:
        retry_safe = retry_safe and not publishing
        attempts = self.attempts if retry_safe else 1
        for attempt in range(attempts):
            try:
                response = self._send(method, url, data, headers, auth)
            except (requests.ConnectionError, requests.Timeout):
                if attempt + 1 < attempts:
                    self.sleep(2**attempt)
                    continue
                raise PublishError(
                    "upload_outcome_unknown" if publishing else "tiktok_network_error",
                    retryable=retry_safe,
                ) from None
            except requests.RequestException:
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
