from unittest.mock import Mock

import pytest
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import ConnectionError, Timeout

from socauto.destinations.base import PublishError
from socauto.destinations.tiktok.http import TikTokHTTP


def test_retry_bounds_and_response_cleanup() -> None:
    failed = Mock(status_code=503)
    success = Mock(status_code=200)
    success.json.return_value = {"status_code": 0}
    session = Mock(spec=curl_requests.Session)
    session.request.side_effect = [Timeout("secret"), failed, success]
    sleep = Mock()
    client = TikTokHTTP(session, sleep=sleep)
    assert client.request("GET", "https://www.tiktok.com/", retry_safe=True) == {"status_code": 0}
    assert session.request.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]
    failed.close.assert_called_once()
    success.close.assert_called_once()
    assert session.request.call_args.kwargs["allow_redirects"] is False
    assert session.request.call_args.kwargs["timeout"] == (10, 30)
    assert session.request.call_args.kwargs["impersonate"] == "chrome"
    assert session.request.call_args.kwargs["quote"] is False


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429])
def test_non_transient_responses_do_not_retry(status: int) -> None:
    response = Mock(status_code=status)
    session = Mock(spec=curl_requests.Session)
    session.request.return_value = response
    with pytest.raises(PublishError):
        TikTokHTTP(session).request("GET", "https://www.tiktok.com/", retry_safe=True)
    session.request.assert_called_once()
    response.close.assert_called_once()


def test_network_failure_exhausted_is_safe() -> None:
    session = Mock(spec=curl_requests.Session)
    session.request.side_effect = ConnectionError("credential-bearing-url")
    with pytest.raises(PublishError) as caught:
        TikTokHTTP(session, sleep=Mock()).request("GET", "https://www.tiktok.com/", retry_safe=True)
    assert caught.value.retryable and session.request.call_count == 3
    assert "credential" not in str(caught.value)


def test_malformed_json_after_publish_is_unknown() -> None:
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("secret response body")
    session = Mock(spec=curl_requests.Session)
    session.request.return_value = response
    with pytest.raises(PublishError, match="upload outcome unknown"):
        TikTokHTTP(session).request("POST", "https://www.tiktok.com/", publishing=True)
    session.request.assert_called_once()
    response.close.assert_called_once()


def test_publish_flag_overrides_retry_safety() -> None:
    session = Mock(spec=curl_requests.Session)
    session.request.side_effect = Timeout("secret")
    with pytest.raises(PublishError) as caught:
        TikTokHTTP(session, sleep=Mock()).request(
            "POST", "https://www.tiktok.com/", publishing=True, retry_safe=True
        )
    assert caught.value.code == "upload_outcome_unknown" and not caught.value.retryable
    session.request.assert_called_once()
