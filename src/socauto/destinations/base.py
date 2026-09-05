"""Destination contract, independent of queue and API concerns."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class PublishResult:
    """An acknowledged publish request, not a guarantee of public visibility."""

    creation_id: str
    video_id: str
    post_id: str | None = None
    post_url: str | None = None


class PublishError(Exception):
    """Safe diagnostics; uncertain publishes must not be automatically retried."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.replace("_", " "))


class Destination(Protocol):
    def publish(
        self,
        media: Path,
        caption: str,
        *,
        visibility: Literal[0, 1] = 1,
        before_publish: Callable[[], None] | None = None,
    ) -> PublishResult: ...
