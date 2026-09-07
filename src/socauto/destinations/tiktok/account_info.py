"""Read the authenticated account, never infer validity from a public profile."""

from collections.abc import Callable
from typing import Protocol

from curl_cffi import requests as curl_requests
from fastapi import Request
from pydantic import BaseModel, Field, ValidationError

from socauto.config import Settings
from socauto.destinations.base import PublishError
from socauto.destinations.tiktok.cookies import attach_cookies
from socauto.destinations.tiktok.http import TikTokHTTP
from socauto.destinations.tiktok.session import TikTokSession, TikTokSessionError

ACCOUNT_INFO_URL = (
    "https://www.tiktok.com/passport/web/account/info/"
    "?aid=1988&app_name=tiktok_web&device_platform=web_pc"
)


class TikTokAccountInfo(BaseModel):
    user_id: str = Field(pattern=r"^[1-9][0-9]{0,127}$")
    username: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=256)


class TikTokSessionCheckError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code.replace("_", " "))


class SessionChecker(Protocol):
    def check(self, session: TikTokSession) -> TikTokAccountInfo: ...


class TikTokSessionChecker:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: Callable[
            [], curl_requests.Session[curl_requests.Response]
        ] = curl_requests.Session,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def check(self, session: TikTokSession) -> TikTokAccountInfo:
        try:
            credentials = TikTokSession.model_validate(session.model_dump())
            with self.session_factory() as client:
                client.trust_env = False
                client.headers.update(
                    {
                        "User-Agent": credentials.user_agent,
                        "Accept": "application/json",
                        "Referer": "https://www.tiktok.com/",
                        "Origin": "https://www.tiktok.com",
                    }
                )
                attach_cookies(client, credentials)
                result = TikTokHTTP(
                    client,
                    impersonate=self.settings.tiktok_http_impersonate,
                    timeout=self.settings.tiktok_http_timeout_seconds,
                    attempts=self.settings.tiktok_http_attempts,
                ).request("GET", ACCOUNT_INFO_URL, retry_safe=True)
        except (TikTokSessionError, ValidationError):
            raise TikTokSessionCheckError("tiktok_session_invalid") from None
        except PublishError as error:
            raise TikTokSessionCheckError(error.code) from None

        data = result.get("data")
        if not isinstance(data, dict):
            raise TikTokSessionCheckError("tiktok_invalid_response")
        # Passport uses message=success, not the publishing API's status_code contract.
        # Error 13 denotes a logged-out session. Other failures can be challenges or drift.
        if type(data.get("error_code")) is int and data["error_code"] == 13:
            raise TikTokSessionCheckError("tiktok_session_invalid")
        if result.get("message") != "success":
            raise TikTokSessionCheckError("tiktok_account_check_rejected")
        for item in (result, data):
            for key in ("error_code", "status_code"):
                if key in item and (type(item[key]) is not int or item[key] != 0):
                    raise TikTokSessionCheckError("tiktok_account_check_rejected")
        user_id = data.get("user_id_str") or data.get("user_id")
        if type(user_id) is int:
            user_id = str(user_id)
        try:
            return TikTokAccountInfo.model_validate(
                {
                    "user_id": user_id,
                    "username": data.get("username"),
                    "display_name": data.get("screen_name") or None,
                }
            )
        except ValidationError:
            raise TikTokSessionCheckError("tiktok_invalid_response") from None


def get_session_checker(request: Request) -> SessionChecker:
    return TikTokSessionChecker(request.app.state.settings)
