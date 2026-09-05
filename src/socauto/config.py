"""Application configuration and runtime paths."""

from functools import lru_cache
from pathlib import Path

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

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

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
