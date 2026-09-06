from collections.abc import Iterator
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session
from test_accounts import account_client as account_client
from test_jobs_api import ClientContext, set_state, submit

from socauto.db.engine import get_request_session
from socauto.db.jobs import JobConflictError, retry_failed_job
from socauto.db.models import Job, JobState
from socauto.db.types import utc_now
from socauto.services import jobs


def test_busy_database_has_safe_retry_response(account_client: ClientContext) -> None:
    client, _, engine = account_client
    account_id = client.post("/v1/accounts/tiktok/auth").json()["id"]
    app = cast(FastAPI, client.app)

    def short_timeout() -> Iterator[Session]:
        with Session(engine) as session:
            session.execute(text("PRAGMA busy_timeout=1"))
            yield session

    app.dependency_overrides[get_request_session] = short_timeout
    with engine.connect() as blocker:
        blocker.execute(text("BEGIN IMMEDIATE"))
        try:
            response = client.post(
                "/v1/jobs",
                json={
                    "source_url": "https://x.com/u/status/1?secret=do-not-echo",
                    "destination_account_id": account_id,
                },
            )
        finally:
            blocker.rollback()
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["detail"]["code"] == "database_busy"
    assert "do-not-echo" not in response.text


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("programming bug"), OperationalError("secret-sql", {}, Exception("not busy"))],
)
def test_unexpected_errors_are_not_swallowed(
    account_client: ClientContext,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    client, _, _ = account_client
    account_id = client.post("/v1/accounts/tiktok/auth").json()["id"]
    job_id = submit(client, account_id)

    def fail(*args: object, **kwargs: object) -> Job:
        raise failure

    monkeypatch.setattr(jobs, "retry_failed_job", fail)
    with pytest.raises(type(failure)):
        client.post(f"/v1/jobs/{job_id}/retry")


def test_retry_conflict_is_safe(
    account_client: ClientContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = account_client
    account_id = client.post("/v1/accounts/tiktok/auth").json()["id"]
    job_id = submit(client, account_id)

    def fail(*args: object, **kwargs: object) -> Job:
        raise JobConflictError("internal details")

    monkeypatch.setattr(jobs, "retry_failed_job", fail)
    response = client.post(f"/v1/jobs/{job_id}/retry")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "job_changed"
    assert "internal details" not in response.text


def test_retry_rejects_stale_failure_snapshot(account_client: ClientContext) -> None:
    client, _, engine = account_client
    account_id = client.post("/v1/accounts/tiktok/auth").json()["id"]
    job_id = submit(client, account_id)
    set_state(engine, job_id, JobState.FAILED, "x_download_failed")
    with Session(engine) as db:
        stale = db.get(Job, UUID(job_id))
        assert stale is not None
        db.expunge(stale)
    with Session(engine) as db:
        current = db.get(Job, UUID(job_id))
        assert current is not None
        current.updated_at = utc_now()
        current.error_code = "upload_outcome_unknown"
        db.add(current)
        db.commit()
    with Session(engine) as db, pytest.raises(JobConflictError):
        retry_failed_job(db, stale)
    assert client.get(f"/v1/jobs/{job_id}").json()["error_code"] == "upload_outcome_unknown"


def test_framework_errors_do_not_echo_inputs(account_client: ClientContext) -> None:
    client, _, _ = account_client
    response = client.post(
        "/v1/jobs", content=b'{"secret":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "secret" not in response.text
    assert client.get("/nonexistent").json()["detail"]["code"] == "http_404"
    response = client.put("/v1/jobs", json={})
    assert response.status_code == 405
    assert "allow" in response.headers
