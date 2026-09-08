import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session
from test_accounts import account_client as account_client
from test_accounts import import_account
from test_worker import FakeDestination, FakeSource

from socauto.config import Settings
from socauto.db.models import Account, AccountStatus, Job, JobState
from socauto.destinations.base import PublishError
from socauto.services.pipeline import Pipeline
from socauto.worker import Worker

ClientContext = tuple[TestClient, Settings, Engine]


@pytest.fixture
def job_api(account_client: ClientContext) -> Iterator[tuple[ClientContext, str]]:
    client, _, _ = account_client
    account_id = str(import_account(client)["id"])
    yield account_client, account_id


def submit(
    client: TestClient,
    account_id: str,
    tweet: int = 123,
    visibility: str | None = None,
) -> str:
    body: dict[str, object] = {
        "source_url": f"https://twitter.com/u/status/{tweet}?s=20",
        "destination_account_id": account_id,
    }
    if visibility is not None:
        body["visibility"] = visibility
    response = client.post("/v1/jobs", json=body)
    assert response.status_code == 202
    job_id = str(response.json()["id"])
    assert response.headers["location"] == f"/v1/jobs/{job_id}"
    return job_id


def set_state(engine: Engine, job_id: str, state: JobState, error: str | None = None) -> None:
    with Session(engine) as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        job.state = state
        job.error_code = error
        db.add(job)
        db.commit()


def test_submission_detail_deduplication_and_history(job_api: tuple[ClientContext, str]) -> None:
    (client, _, _), account_id = job_api
    job_id = submit(client, account_id)
    job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["state"] == "pending"
    assert job["canonical_url"] == "https://x.com/i/status/123"
    assert job["caption_override"] is None
    assert job["visibility"] == "private"
    assert job["created_at"].endswith("Z")
    assert not {"worker_id", "lease_expires_at", "session_file", "error_message"} & job.keys()
    assert client.delete(f"/v1/jobs/{job_id}").status_code == 200
    assert client.delete(f"/v1/jobs/{job_id}").json()["state"] == "cancelled"
    assert client.get(f"/v1/jobs/{job_id}").status_code == 200
    duplicate = client.post(
        "/v1/jobs",
        json={
            "source_url": "https://x.com/i/status/123/video/1",
            "destination_account_id": account_id,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_job_id"] == job_id
    assert duplicate.json()["detail"]["code"] == "duplicate_job"
    assert client.delete(f"/v1/accounts/{account_id}").status_code == 409
    other_id = str(import_account(client, "70002")["id"])
    assert submit(client, other_id) != job_id


def test_public_visibility_is_persisted_in_detail_and_listing(
    job_api: tuple[ClientContext, str],
) -> None:
    (client, _, _), account_id = job_api
    job_id = submit(client, account_id, visibility="public")

    assert client.get(f"/v1/jobs/{job_id}").json()["visibility"] == "public"
    assert client.get("/v1/jobs").json()["items"][0]["visibility"] == "public"


def test_paginated_filtered_listing(job_api: tuple[ClientContext, str]) -> None:
    (client, _, _), account_id = job_api
    first, second = submit(client, account_id, 1), submit(client, account_id, 2)
    client.delete(f"/v1/jobs/{first}")
    page = client.get("/v1/jobs?limit=1").json()
    assert page["total"] == 2
    assert page["items"][0]["id"] == second
    assert client.get("/v1/jobs?offset=1&limit=1").json()["items"][0]["id"] == first
    assert client.get("/v1/jobs?offset=99").json()["items"] == []
    filtered = client.get(f"/v1/jobs?state=cancelled&destination_account_id={account_id}").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == first
    assert client.get(f"/v1/jobs?destination_account_id={uuid4()}").json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"source_url": "https://other.test/secret"},
        {"source_url": ""},
        {"destination_account_id": "bad-id"},
        {"caption_override": "a" * 2201},
        {"caption_override": "😀" * 1101},
        {"caption_override": "\ud800"},
        {"caption_override": 123},
        {"visibility": 0},
        {"visibility": True},
        {"visibility": False},
        {"visibility": None},
        {"visibility": "friends"},
    ],
)
def test_create_validation(job_api: tuple[ClientContext, str], payload: dict[str, object]) -> None:
    (client, _, _), account_id = job_api
    body = {
        "source_url": "https://x.com/u/status/1",
        "destination_account_id": account_id,
        **payload,
    }
    response = client.post(
        "/v1/jobs", content=json.dumps(body), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert "secret" not in response.text
    assert client.get("/v1/jobs").json()["total"] == 0


@pytest.mark.parametrize(
    "query", ["offset=-1", "limit=0", "limit=101", "state=nope", "destination_account_id=bad"]
)
def test_query_validation(job_api: tuple[ClientContext, str], query: str) -> None:
    (client, _, _), _ = job_api
    assert client.get(f"/v1/jobs?{query}").status_code == 422


def test_missing_and_inactive_accounts(job_api: tuple[ClientContext, str]) -> None:
    (client, _, engine), account_id = job_api
    response = client.post(
        "/v1/jobs",
        json={"source_url": "https://x.com/u/status/1", "destination_account_id": str(uuid4())},
    )
    assert response.status_code == 404
    job_id = submit(client, account_id)
    set_state(engine, job_id, JobState.FAILED, "x_download_failed")
    with Session(engine) as db:
        account = db.get(Account, UUID(account_id))
        assert account is not None
        account.status = AccountStatus.EXPIRED
        db.add(account)
        db.commit()
    response = client.post(
        "/v1/jobs",
        json={"source_url": "https://x.com/u/status/2", "destination_account_id": account_id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_unavailable"
    assert client.post(f"/v1/jobs/{job_id}/retry").status_code == 409


@pytest.mark.parametrize("state", list(JobState))
def test_cancellation_and_retry_states(job_api: tuple[ClientContext, str], state: JobState) -> None:
    (client, _, engine), account_id = job_api
    job_id = submit(client, account_id)
    set_state(engine, job_id, state, "x_download_failed" if state is JobState.FAILED else None)
    retry = client.post(f"/v1/jobs/{job_id}/retry")
    assert retry.status_code == (202 if state is JobState.FAILED else 409)
    if state is JobState.FAILED:
        assert retry.json()["state"] == "pending"
        assert retry.json()["error_code"] is None
    response = client.delete(f"/v1/jobs/{job_id}")
    expected = (
        409
        if state in {JobState.UPLOADING, JobState.POSTED}
        else (202 if state is JobState.DOWNLOADING else 200)
    )
    assert response.status_code == expected
    if expected == 202:
        assert response.json()["state"] == "downloading"
        assert response.json()["cancel_requested_at"] is not None


def test_unknown_outcome_requires_acknowledgement(job_api: tuple[ClientContext, str]) -> None:
    (client, _, engine), account_id = job_api
    job_id = submit(client, account_id)
    set_state(engine, job_id, JobState.FAILED, "upload_outcome_unknown")
    endpoint = f"/v1/jobs/{job_id}/retry"
    assert (
        client.post(endpoint).json()["detail"]["code"] == "duplicate_risk_acknowledgement_required"
    )
    assert client.post(endpoint, json={"acknowledge_duplicate_risk": "true"}).status_code == 422
    assert client.post(endpoint, json={"acknowledge_duplicate_risk": True}).status_code == 202


def test_not_found_and_invalid_ids(job_api: tuple[ClientContext, str]) -> None:
    (client, _, _), _ = job_api
    for method, suffix in [("GET", ""), ("DELETE", ""), ("POST", "/retry")]:
        response = client.request(method, f"/v1/jobs/{uuid4()}{suffix}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "job_not_found"
        assert client.request(method, f"/v1/jobs/not-a-uuid{suffix}").status_code == 422


@pytest.mark.parametrize("visibility, adapter_visibility", [("private", 1), ("public", 0)])
@pytest.mark.parametrize("caption", [None, "", "😀" * 1100])
def test_api_worker_retry_and_publication(
    job_api: tuple[ClientContext, str],
    caption: str | None,
    visibility: str,
    adapter_visibility: int,
) -> None:
    (client, settings, engine), account_id = job_api
    response = client.post(
        "/v1/jobs",
        json={
            "source_url": "https://x.com/u/status/1",
            "destination_account_id": account_id,
            "caption_override": caption,
            "visibility": visibility,
        },
    )
    assert response.status_code == 202
    endpoint = response.headers["location"]
    source, destination = FakeSource(settings), FakeDestination()
    worker = Worker(
        engine,
        settings,
        Pipeline(engine, settings, source=source, destination_factory=lambda account: destination),
    )
    assert worker.run_once()
    assert client.get(endpoint).json()["state"] == "downloaded"
    destination.error = PublishError("upload_outcome_unknown")
    assert worker.run_once()
    assert client.get(endpoint).json()["error_code"] == "upload_outcome_unknown"
    retry = client.post(f"{endpoint}/retry", json={"acknowledge_duplicate_risk": True})
    assert retry.status_code == 202
    assert retry.json()["state"] == "downloaded"
    assert retry.json()["visibility"] == visibility
    destination.error = None
    assert worker.run_once()
    job = client.get(endpoint).json()
    assert job["state"] == "posted"
    assert job["visibility"] == visibility
    assert job["creation_id"] == "project-1"
    assert job["post_id"] == "123" and job["posted_url"] is None
    assert job["attempt_count"] == 2
    assert source.calls == 1
    assert destination.calls[-1][1:] == (
        "tweet caption" if caption is None else caption,
        adapter_visibility,
    )
    assert not destination.calls[-1][0].exists()


def test_openapi_contract(job_api: tuple[ClientContext, str]) -> None:
    (client, _, _), _ = job_api
    spec = client.get("/openapi.json").json()
    assert "202" in spec["paths"]["/v1/jobs"]["post"]["responses"]
    assert "202" in spec["paths"]["/v1/jobs/{job_id}"]["delete"]["responses"]
    for path in ("/v1/jobs", "/v1/jobs/{job_id}", "/v1/jobs/{job_id}/retry"):
        for operation in spec["paths"][path].values():
            schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/ErrorResponse")
    fields = spec["components"]["schemas"]["JobResponse"]["properties"]
    assert "worker_id" not in fields and "session_file" not in fields
