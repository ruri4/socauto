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
from test_accounts import FakeAuthenticator
from test_accounts import account_client as account_client

from socauto.config import Settings
from socauto.db.models import Account
from socauto.destinations.tiktok.auth import TikTokAuthUnavailableError, get_tiktok_authenticator
from socauto.destinations.tiktok.session import TikTokSessionStore
from socauto.services.accounts import AccountInUseError, create_tiktok_account, delete_account


def test_auth_browser_failure_is_safe(account_client: tuple[TestClient, Settings, Engine]) -> None:
    client, settings, _ = account_client

    class UnavailableAuthenticator:
        def authenticate(self) -> None:
            raise TikTokAuthUnavailableError("secret-browser-diagnostic")

    cast(FastAPI, client.app).dependency_overrides[get_tiktok_authenticator] = (
        UnavailableAuthenticator
    )
    response = client.post("/v1/accounts/tiktok/auth")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "tiktok_auth_unavailable"
    assert "secret" not in response.text
    assert list(settings.sessions_dir.iterdir()) == []


def test_failed_atomic_session_write_cleans_temporary_file(
    account_client: tuple[TestClient, Settings, Engine],
) -> None:
    client, settings, engine = account_client
    with patch("socauto.destinations.tiktok.session.os.replace", side_effect=PermissionError):
        response = client.post("/v1/accounts/tiktok/auth")
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
            create_tiktok_account(db, settings, FakeAuthenticator().authenticate())
        assert db.exec(select(Account)).first() is None
    assert list(settings.sessions_dir.iterdir()) == []


@pytest.mark.parametrize("integrity", [False, True])
def test_account_delete_rollback_restores_credentials(
    account_client: tuple[TestClient, Settings, Engine],
    integrity: bool,
) -> None:
    _, settings, engine = account_client
    with Session(engine) as db:
        account = create_tiktok_account(db, settings, FakeAuthenticator().authenticate())
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
    account = client.post("/v1/accounts/tiktok/auth").json()
    with patch.object(Path, "replace", side_effect=PermissionError("secret-file-path")):
        response = client.delete(f"/v1/accounts/{account['id']}")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "session_storage_failed"
    assert "secret" not in response.text
    assert client.get("/v1/accounts").json()["total"] == 1
    assert TikTokSessionStore(settings).load(f"sessions/{account['id']}.json")
