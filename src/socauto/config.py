"""Application configuration and runtime paths."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SOCAUTO_",
        case_sensitive=False,
        extra="ignore",
    )

    data_dir: Path = Path("data")
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=2, ge=0.1, le=60)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3600)
    x_cookie_file: Path | None = None
    tiktok_chromium_binary: Path | None = None
    tiktok_signer_script: Path = Path("signer/tiktok/sign.js")
    tiktok_signer_timeout_seconds: int = Field(default=45, ge=10, le=120)
    tiktok_http_timeout_seconds: int = Field(default=30, ge=5, le=120)
    tiktok_http_attempts: int = Field(default=3, ge=1, le=5)
    tiktok_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "socauto.db"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def prepare_runtime(self) -> None:
        """Create private directories needed by API and worker processes."""
        for path in (self.data_dir, self.jobs_dir, self.sessions_dir):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.chmod(0o700)


@lru_cache
def get_settings() -> Settings:
    return Settings()
