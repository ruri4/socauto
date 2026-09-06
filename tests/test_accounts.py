import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel

from socauto.app import create_app
from socauto.config import Settings
from socauto.db.engine import create_db_engine, get_request_session
from socauto.db.jobs import create_job
from socauto.destinations.tiktok.account_info import (
    TikTokAccountInfo,
    get_session_checker,
)
from socauto.destinations.tiktok.session import (
    TikTokCookie,
    TikTokSession,
    TikTokSessionError,
    TikTokSessionStore,
)


def tiktok_session(user_id: str = "70001") -> TikTokSession:
    return TikTokSession(
        user_agent="test-agent",
        cookies=[
            TikTokCookie(name="sessionid", value=f"session-{user_id}", domain=".tiktok.com"),
            TikTokCookie(name="tt-target-idc", value="useast2a", domain=".tiktok.com"),
            TikTokCookie(name="msToken", value="secret-token", domain=".tiktok.com"),
        ],
    )


def cookie_export(user_id: str = "70001") -> bytes:
    return json.dumps([cookie.model_dump() for cookie in tiktok_session(user_id).cookies]).encode()


class FakeChecker:
    def check(self, session: TikTokSession) -> TikTokAccountInfo:
        value = session.cookie_value("sessionid")
        assert value is not None
        user_id = value.removeprefix("session-")
        return TikTokAccountInfo(
            user_id=user_id,
            username=f"user_{user_id}",
            display_name=f"User {user_id}",
        )


def import_account(client: TestClient, user_id: str = "70001") -> dict[str, Any]:
    response = client.post(
        "/v1/accounts/tiktok/import",
        files={"file": ("cookies.json", cookie_export(user_id), "application/json")},
        data={"user_agent": "test-agent"},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["account"])


@pytest.fixture
def account_client(tmp_path: Path) -> Iterator[tuple[TestClient, Settings, Engine]]:
    settings = Settings(data_dir=tmp_path / "data")
    engine = create_db_engine(settings)
    SQLModel.metadata.create_all(engine)
    app = create_app(settings)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_request_session] = session_override
    app.dependency_overrides[get_session_checker] = FakeChecker
    with TestClient(app) as client:
        yield client, settings, engine
    engine.dispose()


def test_import_list_and_delete_account(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, _ = account_client

    response = client.post(
        "/v1/accounts/tiktok/import",
        files={"file": ("cookies.json", cookie_export(), "application/json")},
        data={"user_agent": "test-agent"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["valid"] is True
    assert response.json()["user"]["username"] == "user_70001"
    account = response.json()["account"]
    assert account["platform"] == "tiktok"
    assert account["status"] == "active"
    assert account["platform_user_id"] == "70001"
    assert "session_file" not in account

    session_path = settings.sessions_dir / f"{account['id']}.json"
    assert session_path.stat().st_mode & 0o777 == 0o600
    assert (
        TikTokSessionStore(settings)
        .load(f"sessions/{account['id']}.json")
        .cookie_value("sessionid")
        == "session-70001"
    )

    listed = client.get("/v1/accounts")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [account["id"]]

    deleted = client.delete(f"/v1/accounts/{account['id']}")
    assert deleted.status_code == 204
    assert not session_path.exists()
    assert client.get("/v1/accounts").json()["items"] == []


def test_import_upserts_identity_and_supports_multiple_accounts(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, engine = account_client
    first = import_account(client)
    with Session(engine) as db:
        create_job(
            db,
            source_url="https://x.com/example/status/456",
            destination_account_id=UUID(first["id"]),
        )
    replacement = import_account(client)
    second = import_account(client, "70002")

    assert replacement["id"] == first["id"]
    assert second["id"] != first["id"]
    listing = client.get("/v1/accounts").json()
    assert listing["total"] == 2
    assert {item["platform_user_id"] for item in listing["items"]} == {"70001", "70002"}
    assert sorted(path.name for path in settings.sessions_dir.iterdir()) == sorted(
        (f"{first['id']}.json", f"{second['id']}.json")
    )


def test_browser_auth_endpoint_is_removed(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, _, _ = account_client
    assert client.post("/v1/accounts/tiktok/auth").status_code == 404


def test_import_openapi_uses_multipart_file(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, _, _ = account_client
    operation = client.get("/openapi.json").json()["paths"]["/v1/accounts/tiktok/import"]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    assert "200" in operation["responses"]


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
    account = import_account(client)
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
