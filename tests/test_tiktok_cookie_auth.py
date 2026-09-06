import json
from typing import Any, cast

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from requests.adapters import HTTPAdapter
from test_accounts import account_client as account_client
from test_accounts import import_account

from socauto.config import Settings
from socauto.destinations.tiktok.account_info import (
    ACCOUNT_INFO_URL,
    TikTokAccountInfo,
    TikTokSessionChecker,
    TikTokSessionCheckError,
    get_session_checker,
)
from socauto.destinations.tiktok.cookies import (
    MAX_COOKIE_FILE_BYTES,
    TikTokCookieImportError,
    parse_cookie_export,
)
from socauto.destinations.tiktok.session import TikTokCookie, TikTokSession


def cookie_rows() -> list[dict[str, object]]:
    return [
        {"domain": ".tiktok.com", "path": "/", "name": "sessionid", "value": "session"},
        {
            "domain": ".tiktok.com",
            "path": "/",
            "name": "tt-target-idc",
            "value": "useast2a",
        },
        {"domain": ".example.com", "path": "/", "name": "secret", "value": "ignored"},
    ]


def test_imports_browser_json() -> None:
    session = parse_cookie_export(json.dumps(cookie_rows()).encode(), "exporting-browser")

    assert session.user_agent == "exporting-browser"
    assert session.cookie_value("sessionid") == "session"
    assert session.cookie_value("secret") is None


def test_ignores_empty_optional_cookies() -> None:
    rows = [
        *cookie_rows(),
        {"domain": ".tiktok.com", "path": "/", "name": "optional", "value": ""},
    ]

    session = parse_cookie_export(json.dumps(rows).encode(), "exporting-browser")

    assert session.cookie_value("optional") is None


def test_imports_wrapped_browser_json() -> None:
    content = json.dumps({"cookies": cookie_rows(), "origins": []}).encode()
    assert parse_cookie_export(content, "agent").cookie_value("sessionid") == "session"


def test_imports_netscape_cookie_file() -> None:
    content = (
        b"# Netscape HTTP Cookie File\n"
        b"#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tsession\n"
        b".tiktok.com\tTRUE\t/\tTRUE\t0\ttt-target-idc\tuseast2a\n"
    )

    session = parse_cookie_export(content, "agent")

    assert {cookie.name for cookie in session.cookies} == {"sessionid", "tt-target-idc"}
    assert next(cookie for cookie in session.cookies if cookie.name == "sessionid").http_only


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"not a cookie file", "tiktok_cookie_export_invalid"),
        (json.dumps(cookie_rows()[:1]).encode(), "tiktok_required_cookies_missing"),
        (b"x" * (MAX_COOKIE_FILE_BYTES + 1), "tiktok_cookie_export_too_large"),
    ],
)
def test_rejects_invalid_cookie_exports(content: bytes, code: str) -> None:
    with pytest.raises(TikTokCookieImportError) as error:
        parse_cookie_export(content, "agent")
    assert error.value.code == code
    assert "session" not in str(error.value)


class AccountInfoAdapter(HTTPAdapter):
    def __init__(self, *, payload: object, status: int = 200) -> None:
        super().__init__()
        self.payload = payload
        self.status = status
        self.request: requests.PreparedRequest | None = None

    def send(
        self, request: requests.PreparedRequest, *args: Any, **kwargs: Any
    ) -> requests.Response:
        self.request = request
        response = requests.Response()
        response.status_code = self.status
        response._content = json.dumps(self.payload).encode()
        response.request = request
        response.url = str(request.url)
        return response


def tiktok_session() -> TikTokSession:
    return TikTokSession(
        user_agent="exporting-browser",
        cookies=[
            TikTokCookie(name="sessionid", value="session", domain=".tiktok.com"),
            TikTokCookie(name="tt-target-idc", value="useast2a", domain=".tiktok.com"),
            TikTokCookie(name="unrelated", value="hidden", domain=".example.com"),
        ],
    )


def test_live_checker_returns_identity_and_scopes_cookies() -> None:
    adapter = AccountInfoAdapter(
        payload={
            "message": "success",
            "data": {
                "user_id": "70001",
                "username": "tiktok_user",
                "screen_name": "TikTok User",
            },
        }
    )

    def factory() -> requests.Session:
        client = requests.Session()
        client.mount("https://", adapter)
        return client

    info = TikTokSessionChecker(Settings(), session_factory=factory).check(tiktok_session())

    assert info == TikTokAccountInfo(
        user_id="70001", username="tiktok_user", display_name="TikTok User"
    )
    assert adapter.request is not None
    assert adapter.request.url == ACCOUNT_INFO_URL
    assert adapter.request.headers["User-Agent"] == "exporting-browser"
    assert "sessionid=session" in adapter.request.headers["Cookie"]
    assert "hidden" not in adapter.request.headers["Cookie"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"message": "session_expired", "data": {"error_code": 13}}, "tiktok_session_invalid"),
        ({"message": "success", "data": {"username": "missing-id"}}, "tiktok_invalid_response"),
        ({"message": "challenge", "data": {}}, "tiktok_account_check_rejected"),
    ],
)
def test_live_checker_rejects_invalid_or_ambiguous_responses(payload: object, code: str) -> None:
    adapter = AccountInfoAdapter(payload=payload)

    def factory() -> requests.Session:
        client = requests.Session()
        client.mount("https://", adapter)
        return client

    with pytest.raises(TikTokSessionCheckError) as error:
        TikTokSessionChecker(Settings(), session_factory=factory).check(tiktok_session())
    assert error.value.code == code


def test_cookie_import_and_session_endpoint(
    account_client: tuple[TestClient, Settings, object],
) -> None:
    client, _, _ = account_client
    account = import_account(client)

    response = client.post(f"/v1/accounts/{account['id']}/session/validate")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["valid"] is True
    assert response.json()["user"] == {
        "user_id": "70001",
        "username": "user_70001",
        "display_name": "User 70001",
    }
    assert "cookie" not in response.text.lower()


def test_cookie_import_errors_are_safe(
    account_client: tuple[TestClient, Settings, object],
) -> None:
    client, settings, _ = account_client
    response = client.post(
        "/v1/accounts/tiktok/import",
        files={"file": ("secret-name.json", b"not cookies", "application/json")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "tiktok_cookie_export_invalid"
    assert "secret-name" not in response.text
    assert list(settings.sessions_dir.iterdir()) == []


def test_session_endpoint_maps_safe_failure(
    account_client: tuple[TestClient, Settings, object],
) -> None:
    client, _, _ = account_client
    account_id = import_account(client)["id"]

    class RejectedChecker:
        def check(self, session: TikTokSession) -> TikTokAccountInfo:
            raise TikTokSessionCheckError("tiktok_rate_limited")

    cast(FastAPI, client.app).dependency_overrides[get_session_checker] = lambda: RejectedChecker()
    response = client.post(f"/v1/accounts/{account_id}/session/validate")
    assert response.status_code == 429
    assert response.json()["detail"] == {
        "code": "tiktok_rate_limited",
        "message": "TikTok session could not be verified",
    }
    assert "session" not in response.text.lower().replace("tiktok session", "")


def test_invalid_session_marks_account_expired(
    account_client: tuple[TestClient, Settings, object],
) -> None:
    client, _, _ = account_client
    account_id = import_account(client)["id"]

    class InvalidChecker:
        def check(self, session: TikTokSession) -> TikTokAccountInfo:
            raise TikTokSessionCheckError("tiktok_session_invalid")

    cast(FastAPI, client.app).dependency_overrides[get_session_checker] = InvalidChecker
    response = client.post(f"/v1/accounts/{account_id}/session/validate")

    assert response.status_code == 401
    assert client.get("/v1/accounts").json()["items"][0]["status"] == "expired"


def test_validation_rejects_changed_identity(
    account_client: tuple[TestClient, Settings, object],
) -> None:
    client, _, _ = account_client
    account_id = import_account(client)["id"]

    class OtherAccountChecker:
        def check(self, session: TikTokSession) -> TikTokAccountInfo:
            return TikTokAccountInfo(user_id="70002", username="other")

    cast(FastAPI, client.app).dependency_overrides[get_session_checker] = OtherAccountChecker
    response = client.post(f"/v1/accounts/{account_id}/session/validate")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_identity_changed"
