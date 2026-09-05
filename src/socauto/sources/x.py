"""X/Twitter URL handling."""

import re
from urllib.parse import urlsplit

_X_HOSTS = {
    "mobile.twitter.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "www.x.com",
    "x.com",
}
_STATUS_PATH = re.compile(r"^/[^/]+/status/(?P<id>[0-9]+)(?:/.*)?$")


class UnsupportedXUrlError(ValueError):
    """Raised when a URL is not a supported X status URL."""


def canonicalize_x_url(value: str) -> str:
    """Normalize supported X/Twitter status links for durable deduplication."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise UnsupportedXUrlError("invalid X URL") from error

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname not in _X_HOSTS
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsupportedXUrlError("URL must be an HTTP(S) X or Twitter status link")

    match = _STATUS_PATH.fullmatch(parsed.path)
    if match is None:
        raise UnsupportedXUrlError("URL must point to a single X status")

    return f"https://x.com/i/status/{match.group('id')}"
