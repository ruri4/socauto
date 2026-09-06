"""Parse TikTok cookie exports and scope cookies for checks and publishing."""

import json
import re
import time
from collections.abc import Mapping

import requests

from socauto.destinations.tiktok.session import (
    REQUIRED_COOKIES,
    TikTokCookie,
    TikTokSession,
    TikTokSessionError,
)

MAX_COOKIE_FILE_BYTES = 1024 * 1024
DOMAINS = {"tiktok.com", ".tiktok.com", "www.tiktok.com", ".www.tiktok.com"}


class TikTokCookieImportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code.replace("_", " "))


def usable_cookies(cookies: list[TikTokCookie]) -> list[TikTokCookie]:
    now = time.time()
    selected: dict[tuple[str, str], TikTokCookie] = {}
    required: dict[str, str] = {}
    for cookie in cookies:
        domain = (cookie.domain or ".tiktok.com").lower()
        if domain not in DOMAINS or cookie.path != "/":
            continue
        if cookie.expires_at is not None and cookie.expires_at <= now:
            continue
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", cookie.name):
            raise TikTokSessionError("invalid cookie name")
        if not cookie.value or any(ord(c) < 33 or ord(c) > 126 or c == ";" for c in cookie.value):
            raise TikTokSessionError("invalid cookie value")
        key = (domain, cookie.name)
        if key in selected and selected[key].value != cookie.value:
            raise TikTokSessionError("conflicting cookie values")
        if cookie.name in REQUIRED_COOKIES:
            if cookie.name in required and required[cookie.name] != cookie.value:
                raise TikTokSessionError("conflicting required cookies")
            required[cookie.name] = cookie.value
        selected[key] = cookie.model_copy(update={"domain": domain})
    if not required.keys() >= REQUIRED_COOKIES:
        raise TikTokSessionError("missing or expired required TikTok cookies")
    return list(selected.values())


def attach_cookies(client: requests.Session, session: TikTokSession) -> None:
    for cookie in usable_cookies(session.cookies):
        client.cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain or ".tiktok.com",
            path="/",
            secure=True,
            expires=cookie.expires_at,
        )


def _netscape(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line.removeprefix("#HttpOnly_")
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError
        domain, subdomains, path, secure, expires, name, value = fields
        if domain.lower() not in DOMAINS:
            continue
        if subdomains not in ("TRUE", "FALSE") or secure not in ("TRUE", "FALSE"):
            raise ValueError
        rows.append(
            {
                "domain": domain,
                "path": path,
                "name": name,
                "value": value,
                "secure": secure == "TRUE",
                "httpOnly": http_only,
                "expiry": int(expires),
            }
        )
    return rows


def _parse_cookie(row: object) -> TikTokCookie | None:
    if not isinstance(row, Mapping):
        raise ValueError
    domain = row.get("domain")
    if not isinstance(domain, str):
        raise ValueError
    if domain.lower() not in DOMAINS:
        return None
    expiry = row.get("expirationDate", row.get("expiry", row.get("expires_at")))
    if expiry is not None and (type(expiry) not in (int, float) or expiry < -1):
        raise ValueError
    return TikTokCookie.model_validate(
        {
            "name": row.get("name"),
            "value": row.get("value"),
            "domain": domain.lower(),
            "path": row.get("path", "/"),
            "secure": row.get("secure", False),
            "http_only": row.get("httpOnly", row.get("http_only", False)),
            "same_site": row.get("sameSite", row.get("same_site")),
            "expires_at": int(expiry) if expiry is not None and expiry > 0 else None,
        }
    )


def parse_cookie_export(content: bytes, user_agent: str) -> TikTokSession:
    """Parse an uploaded export without retaining its original representation."""
    if len(content) > MAX_COOKIE_FILE_BYTES:
        raise TikTokCookieImportError("tiktok_cookie_export_too_large")
    try:
        text = content.decode("utf-8-sig").strip()
        parsed: object = json.loads(text) if text.startswith(("[", "{")) else _netscape(text)
        if isinstance(parsed, Mapping):
            parsed = parsed.get("cookies")
        if not isinstance(parsed, list) or len(parsed) > 3000:
            raise ValueError
        cookies = [cookie for row in parsed if (cookie := _parse_cookie(row)) is not None]
        selected = usable_cookies(cookies)
        return TikTokSession(user_agent=user_agent, cookies=selected)
    except TikTokSessionError as error:
        code = (
            "tiktok_required_cookies_missing"
            if str(error).startswith("missing or expired")
            else "tiktok_cookie_export_invalid"
        )
        raise TikTokCookieImportError(code) from None
    except (ValueError, OverflowError, UnicodeError):
        raise TikTokCookieImportError("tiktok_cookie_export_invalid") from None
