"""Validated, permission-restricted TikTok session storage."""

import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from socauto.config import Settings
from socauto.db.types import utc_now

REQUIRED_COOKIES = frozenset({"sessionid", "tt-target-idc"})


class TikTokSessionError(ValueError):
    """A TikTok session is invalid or cannot be stored safely."""


class TikTokCookie(BaseModel):
    """Serializable subset of a browser cookie."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    domain: str | None = None
    path: str = "/"
    expires_at: int | None = None
    http_only: bool = False
    secure: bool = False
    same_site: str | None = None


class TikTokSession(BaseModel):
    """Versioned browser session used by the HTTP uploader."""

    schema_version: Literal[1] = 1
    platform: Literal["tiktok"] = "tiktok"
    user_agent: str = Field(min_length=1)
    authenticated_at: datetime = Field(default_factory=utc_now)
    cookies: list[TikTokCookie] = Field(min_length=1)

    @field_validator("cookies")
    @classmethod
    def validate_required_cookies(cls, cookies: list[TikTokCookie]) -> list[TikTokCookie]:
        now = int(utc_now().timestamp())
        usable_names = {
            cookie.name
            for cookie in cookies
            if cookie.value and (cookie.expires_at is None or cookie.expires_at > now)
        }
        missing = REQUIRED_COOKIES - usable_names
        if missing:
            raise ValueError(
                f"missing or expired required TikTok cookies: {', '.join(sorted(missing))}"
            )
        return cookies

    def cookie_value(self, name: str) -> str | None:
        return next((cookie.value for cookie in self.cookies if cookie.name == name), None)


class TikTokSessionStore:
    """Store session JSON beneath the configured private data directory."""

    def __init__(self, settings: Settings) -> None:
        self._data_dir = settings.data_dir.resolve()
        self._sessions_dir = settings.sessions_dir.resolve()

    def save(self, account_id: UUID, session: TikTokSession) -> str:
        self._sessions_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._sessions_dir.chmod(0o700)
        destination = self._sessions_dir / f"{account_id}.json"
        temporary = self._sessions_dir / f".{account_id}.{uuid4().hex}.tmp"
        payload = session.model_dump_json(indent=2).encode()

        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            destination.chmod(0o600)
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise TikTokSessionError("could not store TikTok session") from error

        return destination.relative_to(self._data_dir).as_posix()

    def load(self, session_file: str) -> TikTokSession:
        path = self._safe_path(session_file)
        try:
            return TikTokSession.model_validate_json(path.read_text())
        except (OSError, ValueError) as error:
            raise TikTokSessionError("could not load a valid TikTok session") from error

    def stage_delete(self, session_file: str) -> tuple[Path, Path] | None:
        path = self._safe_path(session_file)
        if not path.exists():
            return None
        staged = self._sessions_dir / f".{path.stem}.{uuid4().hex}.deleting"
        try:
            path.replace(staged)
        except OSError as error:
            raise TikTokSessionError("could not remove TikTok session") from error
        return path, staged

    @staticmethod
    def restore_delete(staged_delete: tuple[Path, Path] | None) -> None:
        if staged_delete is not None:
            destination, staged = staged_delete
            staged.replace(destination)

    @staticmethod
    def finish_delete(staged_delete: tuple[Path, Path] | None) -> None:
        if staged_delete is not None:
            _, staged = staged_delete
            staged.unlink(missing_ok=True)

    def _safe_path(self, session_file: str) -> Path:
        candidate = (self._data_dir / session_file).resolve()
        try:
            candidate.relative_to(self._sessions_dir)
        except ValueError as error:
            raise TikTokSessionError("session path is outside the sessions directory") from error
        return candidate
