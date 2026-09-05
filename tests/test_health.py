from pathlib import Path

from fastapi.testclient import TestClient

from socauto.app import create_app
from socauto.config import Settings


def test_health_and_runtime_directories(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert settings.jobs_dir.is_dir()
    assert settings.sessions_dir.is_dir()
    assert settings.sessions_dir.stat().st_mode & 0o777 == 0o700
