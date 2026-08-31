from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import api_client
from app.services.api_client import ApiClientError, JsonApiClient

BASE_URL = "https://erp.example.test"


def _json_response(payload: dict, status_code: int = 200) -> Mock:
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _tokens(access: str, refresh: str, expires_in: int = 900) -> Mock:
    return _json_response(
        {"access_token": access, "refresh_token": refresh, "expires_in": expires_in}
    )


def _client() -> JsonApiClient:
    return JsonApiClient(
        name="erp", base_url=BASE_URL, email="admin@demo.my", password="secret"
    )


def _paths(mock_post) -> list[str]:
    return [call.args[0] for call in mock_post.call_args_list]


def test_a_cached_token_is_reused_instead_of_logging_in_again():
    """One demo makes more tool calls than the 10-logins-a-minute limit allows."""
    client = _client()

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")) as post:
        with patch.object(
            api_client.httpx, "get", return_value=_json_response({"items": []})
        ) as get:
            client.get("/api/skus")
            client.get("/api/skus")

    assert post.call_count == 1
    assert _paths(post) == [f"{BASE_URL}/api/auth/login"]
    assert get.call_count == 2
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer acc-1"


def test_an_expired_token_is_refreshed_rather_than_re_logged_in():
    client = _client()
    # expires_in 0 lands behind the safety margin, so the very next call is stale.
    expired_login = _tokens("acc-1", "ref-1", expires_in=0)
    refreshed = _tokens("acc-2", "ref-2")

    with patch.object(api_client.httpx, "post", side_effect=[expired_login, refreshed]) as post:
        with patch.object(
            api_client.httpx, "get", return_value=_json_response({"items": []})
        ) as get:
            client.get("/api/skus")
            client.get("/api/skus")

    assert _paths(post) == [
        f"{BASE_URL}/api/auth/login",
        f"{BASE_URL}/api/auth/refresh",
    ]
    assert post.call_args_list[1].kwargs["json"] == {"refresh_token": "ref-1"}
    assert get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer acc-2"


def test_a_rejected_refresh_falls_back_to_logging_in_again():
    """Refresh tokens are one-time-use, so a spent one is routine, not an outage."""
    client = _client()
    expired_login = _tokens("acc-1", "ref-1", expires_in=0)
    rejected = httpx.HTTPStatusError(
        "401", request=httpx.Request("POST", BASE_URL), response=httpx.Response(401)
    )
    fresh_login = _tokens("acc-3", "ref-3")

    with patch.object(
        api_client.httpx, "post", side_effect=[expired_login, rejected, fresh_login]
    ) as post:
        with patch.object(api_client.httpx, "get", return_value=_json_response({"items": []})):
            client.get("/api/skus")
            client.get("/api/skus")

    assert _paths(post) == [
        f"{BASE_URL}/api/auth/login",
        f"{BASE_URL}/api/auth/refresh",
        f"{BASE_URL}/api/auth/login",
    ]


def test_a_401_on_a_data_call_re_logs_in_and_retries_once():
    """Covers what the clock cannot see: a revoked session, a restarted back end."""
    client = _client()
    rows = _json_response({"items": [{"code": "SKU-1"}]})

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), _tokens("acc-9", "ref-9")]
    ) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=[_json_response({}, status_code=401), rows]
        ) as get:
            payload = client.get("/api/skus")

    assert payload == {"items": [{"code": "SKU-1"}]}
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer acc-9"
    assert _paths(post) == [f"{BASE_URL}/api/auth/login"] * 2


def test_a_401_that_survives_a_fresh_login_is_an_error_not_a_loop():
    client = _client()

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")):
        with patch.object(
            api_client.httpx, "get", return_value=_json_response({}, status_code=401)
        ) as get:
            with pytest.raises(ApiClientError):
                client.get("/api/skus")

    assert get.call_count == 2


def test_other_error_statuses_are_raised_without_a_retry():
    client = _client()

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")):
        with patch.object(
            api_client.httpx, "get", return_value=_json_response({}, status_code=500)
        ) as get:
            with pytest.raises(ApiClientError):
                client.get("/api/skus")

    assert get.call_count == 1


def test_a_service_that_omits_a_ttl_still_caches_the_token():
    """crm_os returns no expires_in at all; the documented 15 minutes is the default."""
    client = _client()
    no_ttl = _json_response({"access_token": "acc-1", "refresh_token": "ref-1"})

    with patch.object(api_client.httpx, "post", return_value=no_ttl) as post:
        with patch.object(api_client.httpx, "get", return_value=_json_response({})):
            client.get("/api/skus")
            client.get("/api/skus")

    assert post.call_count == 1


def test_a_subclass_can_strip_a_response_envelope():
    """crm_os wraps everything, tokens included, in {"success", "data"}."""

    class Wrapped(JsonApiClient):
        def _unwrap(self, payload):
            return payload["data"]

    client = Wrapped(name="crm", base_url=BASE_URL, email="a@b.c", password="x")
    login = _json_response(
        {"success": True, "data": {"access_token": "acc-1", "refresh_token": "ref-1"}}
    )
    rows = _json_response({"success": True, "data": {"total": 1}})

    with patch.object(api_client.httpx, "post", return_value=login):
        with patch.object(api_client.httpx, "get", return_value=rows) as get:
            payload = client.get("/api/contacts")

    assert payload == {"total": 1}
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer acc-1"
