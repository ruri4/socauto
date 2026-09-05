"""Interactive TikTok browser authentication."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Any, Protocol

from fastapi import Request
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

from socauto.config import Settings
from socauto.destinations.tiktok.session import REQUIRED_COOKIES, TikTokCookie, TikTokSession


class TikTokAuthTimeoutError(TimeoutError):
    """The user did not complete TikTok authentication in time."""


class TikTokAuthUnavailableError(RuntimeError):
    """The interactive browser could not be started or used."""


class TikTokAuthenticator(Protocol):
    def authenticate(self) -> TikTokSession: ...


class SeleniumTikTokAuthenticator:
    """Open a visible Chromium login and capture the resulting session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(self) -> TikTokSession:
        self._settings.prepare_runtime()
        try:
            with TemporaryDirectory(
                prefix="tiktok-auth-",
                dir=self._settings.sessions_dir,
                ignore_cleanup_errors=True,
            ) as profile_dir:
                driver = self._open_browser(Path(profile_dir))
                try:
                    driver.get(self._settings.tiktok_login_url)
                    cookies = self._wait_for_cookies(driver)
                    return TikTokSession(
                        user_agent=self._settings.tiktok_user_agent,
                        cookies=[self._convert_cookie(cookie) for cookie in cookies],
                    )
                finally:
                    driver.quit()
        except TikTokAuthTimeoutError:
            raise
        except WebDriverException as error:
            raise TikTokAuthUnavailableError("TikTok login browser failed") from error

    def _open_browser(self, profile_dir: Path) -> WebDriver:
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-agent={self._settings.tiktok_user_agent}")
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--disable-dev-shm-usage")
        if self._settings.tiktok_chromium_binary is not None:
            options.binary_location = str(self._settings.tiktok_chromium_binary)
        return webdriver.Chrome(options=options)

    def _wait_for_cookies(self, driver: WebDriver) -> Sequence[Mapping[str, Any]]:
        deadline = monotonic() + self._settings.tiktok_auth_timeout_seconds
        while monotonic() < deadline:
            cookies = driver.get_cookies()
            names = {str(cookie.get("name", "")) for cookie in cookies}
            if names >= REQUIRED_COOKIES:
                return cookies
            sleep(1)
        raise TikTokAuthTimeoutError("TikTok login timed out")

    @staticmethod
    def _convert_cookie(cookie: Mapping[str, Any]) -> TikTokCookie:
        expiry = cookie.get("expiry")
        return TikTokCookie(
            name=str(cookie.get("name", "")),
            value=str(cookie.get("value", "")),
            domain=str(cookie["domain"]) if cookie.get("domain") else None,
            path=str(cookie.get("path", "/")),
            expires_at=int(expiry) if isinstance(expiry, int | float) else None,
            http_only=bool(cookie.get("httpOnly", False)),
            secure=bool(cookie.get("secure", False)),
            same_site=str(cookie["sameSite"]) if cookie.get("sameSite") else None,
        )


def get_tiktok_authenticator(request: Request) -> TikTokAuthenticator:
    settings: Settings = request.app.state.settings
    return SeleniumTikTokAuthenticator(settings)
