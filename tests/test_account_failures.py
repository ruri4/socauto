"""Credential-safe operational errors and filesystem/transaction rollback."""

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from test_accounts import account_client as account_client
from test_accounts import cookie_export, import_account, tiktok_session

from socauto.config import Settings
from socauto.db.models import Account
from socauto.destinations.tiktok.account_info import (
    TikTokAccountInfo,
    TikTokSessionCheckError,
    get_session_checker,
)
from socauto.destinations.tiktok.session import TikTokSession, TikTokSessionStore
from socauto.services.accounts import AccountInUseError, delete_account, import_tiktok_account


def account_info(user_id: str = "70001") -> TikTokAccountInfo:
    return TikTokAccountInfo(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"User {user_id}",
    )


def test_live_import_failure_is_safe(account_client: tuple[TestClient, Settings, Engine]) -> None:
    client, settings, _ = account_client

    class UnavailableChecker:
        def check(self, credentials: TikTokSession) -> TikTokAccountInfo:
            raise TikTokSessionCheckError("tiktok_network_error")

    cast(FastAPI, client.app).dependency_overrides[get_session_checker] = UnavailableChecker
    response = client.post(
        "/v1/accounts/tiktok/import",
        files={"file": ("cookies.json", cookie_export(), "application/json")},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "tiktok_network_error"
    assert "secret" not in response.text
    assert list(settings.sessions_dir.iterdir()) == []


def test_failed_atomic_session_write_cleans_temporary_file(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, engine = account_client
    with patch("socauto.destinations.tiktok.session.os.replace", side_effect=PermissionError):
        response = client.post(
            "/v1/accounts/tiktok/import",
            files={"file": ("cookies.json", cookie_export(), "application/json")},
        )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "session_storage_failed"
    assert "secret-session" not in response.text
    assert list(settings.sessions_dir.iterdir()) == []
    with Session(engine) as db:
        assert db.exec(select(Account)).first() is None


def test_account_create_rollback_removes_credentials(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    _, settings, engine = account_client
    with Session(engine) as db:
        with (
            patch.object(db, "commit", side_effect=RuntimeError("database failure")),
            pytest.raises(RuntimeError, match="database failure"),
        ):
            import_tiktok_account(db, settings, tiktok_session(), account_info())
        assert db.exec(select(Account)).first() is None
    assert list(settings.sessions_dir.iterdir()) == []


def test_account_update_rollback_restores_credentials(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    _, settings, engine = account_client
    with Session(engine) as db:
        account = import_tiktok_account(db, settings, tiktok_session(), account_info())
        path = settings.data_dir / account.session_file
        original = path.read_bytes()
    replacement = tiktok_session()
    replacement.cookies[0].value = "replacement-secret"
    with (
        Session(engine) as db,
        patch.object(db, "commit", side_effect=RuntimeError("database failure")),
        pytest.raises(RuntimeError, match="database failure"),
    ):
        import_tiktok_account(db, settings, replacement, account_info())
    assert path.read_bytes() == original
    assert list(settings.sessions_dir.iterdir()) == [path]


@pytest.mark.parametrize("integrity", [False, True])
def test_account_delete_rollback_restores_credentials(
    account_client: tuple[TestClient, Settings, Engine],
    integrity: bool,
) -> None:
    _, settings, engine = account_client
    with Session(engine) as db:
        account = import_tiktok_account(db, settings, tiktok_session(), account_info())
        path = settings.data_dir / account.session_file
        original = path.read_bytes()
        failure = IntegrityError("delete", {}, Exception()) if integrity else RuntimeError()
        expected = AccountInUseError if integrity else RuntimeError
        with patch.object(db, "commit", side_effect=failure), pytest.raises(expected):
            delete_account(db, settings, account.id)
        assert db.get(Account, account.id) is not None
        assert path.read_bytes() == original
        assert path.stat().st_mode & 0o777 == 0o600
        assert list(settings.sessions_dir.iterdir()) == [path]


def test_account_delete_storage_error_preserves_account(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, _ = account_client
    account = import_account(client)
    with patch.object(Path, "replace", side_effect=PermissionError("secret-file-path")):
        response = client.delete(f"/v1/accounts/{account['id']}")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "session_storage_failed"
    assert "secret" not in response.text
    assert client.get("/v1/accounts").json()["total"] == 1
    assert TikTokSessionStore(settings).load(f"sessions/{account['id']}.json")
