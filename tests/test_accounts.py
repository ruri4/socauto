from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel

from socauto.app import create_app
from socauto.config import Settings
from socauto.db.engine import create_db_engine, get_request_session
from socauto.db.jobs import create_job
from socauto.destinations.tiktok.auth import (
    SeleniumTikTokAuthenticator,
    TikTokAuthenticator,
    TikTokAuthTimeoutError,
    get_tiktok_authenticator,
)
from socauto.destinations.tiktok.session import (
    TikTokCookie,
    TikTokSession,
    TikTokSessionError,
    TikTokSessionStore,
)


class FakeAuthenticator:
    def authenticate(self) -> TikTokSession:
        return TikTokSession(
            user_agent="test-agent",
            cookies=[
                TikTokCookie(name="sessionid", value="secret-session", domain=".tiktok.com"),
                TikTokCookie(name="tt-target-idc", value="useast2a", domain=".tiktok.com"),
                TikTokCookie(name="msToken", value="secret-token", domain=".tiktok.com"),
            ],
        )


class TimeoutAuthenticator:
    def authenticate(self) -> TikTokSession:
        raise TikTokAuthTimeoutError


@pytest.fixture
def account_client(tmp_path: Path) -> Iterator[tuple[TestClient, Settings, Engine]]:
    settings = Settings(data_dir=tmp_path / "data")
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    app = create_app(settings)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def auth_override() -> TikTokAuthenticator:
        return FakeAuthenticator()

    app.dependency_overrides[get_request_session] = session_override
    app.dependency_overrides[get_tiktok_authenticator] = auth_override
    with TestClient(app) as client:
        yield client, settings, engine
    engine.dispose()


def test_authenticate_list_and_delete_account(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, _ = account_client

    created = client.post("/v1/accounts/tiktok/auth")
    assert created.status_code == 201
    account = created.json()
    assert account["platform"] == "tiktok"
    assert account["status"] == "active"
    assert account["platform_user_id"] is None
    assert "session_file" not in account

    session_path = settings.sessions_dir / f"{account['id']}.json"
    assert session_path.stat().st_mode & 0o777 == 0o600
    assert (
        TikTokSessionStore(settings)
        .load(f"sessions/{account['id']}.json")
        .cookie_value("sessionid")
        == "secret-session"
    )

    listed = client.get("/v1/accounts")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [account["id"]]

    deleted = client.delete(f"/v1/accounts/{account['id']}")
    assert deleted.status_code == 204
    assert not session_path.exists()
    assert client.get("/v1/accounts").json()["items"] == []


def test_auth_timeout_has_machine_readable_safe_error(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, _, _ = account_client
    cast(FastAPI, client.app).dependency_overrides[get_tiktok_authenticator] = lambda: (
        TimeoutAuthenticator()
    )

    response = client.post("/v1/accounts/tiktok/auth")

    assert response.status_code == 504
    assert response.json() == {
        "detail": {
            "code": "tiktok_auth_timeout",
            "message": "TikTok login was not completed in time",
        }
    }


def test_missing_account_returns_not_found(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, _, _ = account_client
    response = client.delete("/v1/accounts/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "account_not_found"


def test_session_requires_both_publish_cookies() -> None:
    with pytest.raises(ValueError, match="tt-target-idc"):
        TikTokSession(
            user_agent="test-agent",
            cookies=[TikTokCookie(name="sessionid", value="do-not-print")],
        )


def test_session_rejects_expired_required_cookie() -> None:
    with pytest.raises(ValueError, match="sessionid"):
        TikTokSession(
            user_agent="test-agent",
            cookies=[
                TikTokCookie(name="sessionid", value="do-not-print", expires_at=1),
                TikTokCookie(name="tt-target-idc", value="useast2a"),
            ],
        )


def test_account_with_job_cannot_be_deleted(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, engine = account_client
    account = client.post("/v1/accounts/tiktok/auth").json()
    session_path = settings.sessions_dir / f"{account['id']}.json"
    with Session(engine) as db:
        create_job(
            db,
            source_url="https://x.com/example/status/123",
            destination_account_id=UUID(account["id"]),
        )

    response = client.delete(f"/v1/accounts/{account['id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_in_use"
    assert session_path.exists()


def test_session_store_rejects_paths_outside_private_directory(tmp_path: Path) -> None:
    store = TikTokSessionStore(Settings(data_dir=tmp_path / "data"))
    with pytest.raises(TikTokSessionError, match="outside"):
        store.load("../credentials.json")


def test_selenium_authenticator_closes_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDriver:
        visited_url: str | None = None
        closed = False

        def get(self, url: str) -> None:
            self.visited_url = url

        def get_cookies(self) -> list[dict[str, object]]:
            return [
                {"name": "sessionid", "value": "secret-session"},
                {"name": "tt-target-idc", "value": "useast2a"},
            ]

        def quit(self) -> None:
            self.closed = True

    settings = Settings(data_dir=tmp_path / "data")
    authenticator = SeleniumTikTokAuthenticator(settings)
    driver = FakeDriver()
    monkeypatch.setattr(authenticator, "_open_browser", lambda _: driver)

    authenticated = authenticator.authenticate()

    assert authenticated.cookie_value("sessionid") == "secret-session"
    assert driver.visited_url == settings.tiktok_login_url
    assert driver.closed
