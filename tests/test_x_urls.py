import pytest

from socauto.sources.x import UnsupportedXUrlError, canonicalize_x_url


@pytest.mark.parametrize(
    "value",
    [
        "https://x.com/example/status/123456?s=20",
        "http://www.twitter.com/Example/status/123456/video/1",
        "https://mobile.x.com/i/status/123456#fragment",
    ],
)
def test_canonicalize_x_url(value: str) -> None:
    assert canonicalize_x_url(value) == "https://x.com/i/status/123456"


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/user/status/123",
        "https://x.com/home",
        "https://user:secret@x.com/user/status/123",
        "https://x.com:8443/user/status/123",
    ],
)
def test_reject_unsupported_x_url(value: str) -> None:
    with pytest.raises(UnsupportedXUrlError):
        canonicalize_x_url(value)
