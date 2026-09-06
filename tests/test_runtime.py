"""Local process checks. These never log in to or publish on a platform."""

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlmodel import Session, SQLModel

from socauto.config import Settings
from socauto.db.engine import create_db_engine
from socauto.db.models import Account
from socauto.destinations.tiktok.signer import PUBLISH_URL, BunSigner, validate_signed_url


@contextmanager
def api_process(settings: Settings) -> Iterator[httpx.Client]:
    # Pass a bound socket to Uvicorn rather than racing for a free port.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "socauto.app:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
            ],
            pass_fds=(listener.fileno(),),
            env={**os.environ, "SOCAUTO_DATA_DIR": str(settings.data_dir)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    trust_env=False,
                    timeout=0.5,
                ) as client:
                    deadline = time.monotonic() + 10
                    while True:
                        assert process.poll() is None, "API exited before readiness"
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        assert time.monotonic() < deadline, "API readiness timed out"
                        time.sleep(0.05)
                    yield client
                process.send_signal(signal.SIGTERM)
                _, diagnostics = process.communicate(timeout=10)
                # Uvicorn re-raises captured signals after graceful lifespan cleanup.
                assert process.returncode in (0, -signal.SIGTERM)
                assert "Application shutdown complete" in diagnostics
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


def test_api_process_restart_preserves_queued_job(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    engine = create_db_engine(settings)
    try:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as db:
            account = Account(session_file="sessions/offline-fixture.json")
            db.add(account)
            db.commit()
            account_id = str(account.id)
    finally:
        engine.dispose()
    with api_process(settings) as client:
        created = client.post(
            "/v1/jobs",
            json={
                "source_url": "https://x.com/fixture/status/123",
                "destination_account_id": account_id,
            },
        )
        assert created.status_code == 202
        location = created.headers["Location"]
        assert created.json()["state"] == "pending"
        assert client.get("/openapi.json").status_code == 200
    with api_process(settings) as client:
        assert client.get(location).json() == created.json()
        assert client.get("/v1/jobs").json()["total"] == 1
        assert client.delete(location).json()["state"] == "cancelled"


@pytest.mark.skipif(
    not os.environ.get("SOCAUTO_TIKTOK_CHROMIUM_BINARY"),
    reason="set SOCAUTO_TIKTOK_CHROMIUM_BINARY for offline Python/Bun/Chromium IPC",
)
def test_real_python_bun_signer_ipc() -> None:
    settings = Settings()
    original = PUBLISH_URL + "?aid=1988&msToken=synthetic-offline-token"
    signed = BunSigner(settings).sign(original, settings.tiktok_user_agent)
    validate_signed_url(original, signed)
    query = parse_qs(urlsplit(signed).query)
    assert len(query["_signature"][0]) > 10
    assert len(query["X-Bogus"][0]) > 10
    assert query["verifyFp"][0].startswith("verify_")
