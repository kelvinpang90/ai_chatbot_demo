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
        name="erp", base_url=BASE_URL, email="tester@example.test", password="not-a-real-password"
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


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", BASE_URL), response=httpx.Response(429)
        ),
    ],
    ids=["dead-host", "timeout", "rate-limited"],
)
def test_every_transport_failure_arrives_as_one_error_type(failure):
    """None of httpx's exceptions derive from OSError, so callers cannot catch that.

    The rate limit matters most: 10 logins a minute is the limit this whole class
    exists to stay under, and hitting it must not escape as a raw httpx error.
    """
    client = _client()

    with patch.object(api_client.httpx, "post", side_effect=failure):
        with pytest.raises(ApiClientError):
            client.get("/api/skus")


def test_a_malformed_base_url_is_wrapped_like_any_other_outage():
    """A typo in ERP_BASE_URL reaches us through a hand-edited .env on the VPS.

    `httpx.InvalidURL` derives from Exception, not HTTPError, so it used to sail
    past the boundary and out of the tool as a raw httpx error.
    """
    client = JsonApiClient(
        name="erp", base_url="http://[::1", email="a@b.c", password="x"
    )

    with pytest.raises(ApiClientError, match="failed"):
        client.get("/api/skus")


def test_the_transport_error_list_still_covers_everything_reachable():
    """Pins the audit, so a new httpx release cannot quietly reopen this hole.

    Anything httpx can raise that is not in TRANSPORT_ERRORS must be unreachable
    for a client that reads its responses whole -- cookies we never set, or a
    stream we never leave unread.
    """
    escapes = {
        name
        for name, obj in vars(httpx).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseException)
        and not issubclass(obj, api_client.TRANSPORT_ERRORS)
    }

    assert escapes == {
        "CookieConflict",  # needs cookies; we set none
        "StreamError",  # the four below need an unread response; get/post read theirs
        "StreamConsumed",
        "StreamClosed",
        "ResponseNotRead",
        "RequestNotRead",
    }


def test_a_dead_host_on_the_data_call_is_also_wrapped():
    client = _client()

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")):
        with patch.object(
            api_client.httpx, "get", side_effect=httpx.ConnectError("connection refused")
        ):
            with pytest.raises(ApiClientError):
                client.get("/api/skus")


def test_missing_credentials_name_the_variable_instead_of_pretending_to_log_in():
    client = JsonApiClient(name="erp", base_url=BASE_URL, email="", password="")

    with patch.object(api_client.httpx, "post") as post:
        with pytest.raises(ApiClientError, match="ERP_EMAIL"):
            client.get("/api/skus")

    post.assert_not_called()  # never sent empty credentials to the back end


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


# -- writes ------------------------------------------------------------------


def test_a_write_carries_the_token_and_the_body():
    client = _client()
    created = _json_response({"id": 77}, status_code=201)

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), created]
    ) as post:
        payload = client.post("/api/sales-orders", json={"customer_id": 3})

    assert payload == {"id": 77}
    write = post.call_args_list[1]
    assert write.args[0] == f"{BASE_URL}/api/sales-orders"
    assert write.kwargs["json"] == {"customer_id": 3}
    assert write.kwargs["headers"]["Authorization"] == "Bearer acc-1"


def test_a_401_on_a_write_re_logs_in_and_retries_exactly_once():
    """Safe to retry only because a 401 is refused before the route runs.

    If this ever retried a request that had actually reached the handler, the
    customer would get two orders for one confirmation.
    """
    client = _client()
    created = _json_response({"id": 77}, status_code=201)

    with patch.object(
        api_client.httpx,
        "post",
        side_effect=[
            _tokens("acc-1", "ref-1"),
            _json_response({}, status_code=401),
            _tokens("acc-9", "ref-9"),
            created,
        ],
    ) as post:
        assert client.post("/api/sales-orders", json={}) == {"id": 77}

    assert _paths(post) == [
        f"{BASE_URL}/api/auth/login",
        f"{BASE_URL}/api/sales-orders",
        f"{BASE_URL}/api/auth/login",
        f"{BASE_URL}/api/sales-orders",
    ]


def test_a_refused_write_keeps_the_reason_the_service_gave():
    """"Insufficient stock" and "no such customer" are different answers to give
    a customer waiting on WhatsApp; a bare 400 cannot tell them apart."""
    client = _client()
    refused = _json_response({}, status_code=400)
    refused.text = '{"detail":"Insufficient stock for SKU-ELE-0001."}'

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), refused]
    ) as post:
        with pytest.raises(ApiClientError, match="Insufficient stock"):
            client.post("/api/sales-orders", json={})

    assert post.call_count == 2  # a 400 is final, unlike a 401


def test_a_transport_failure_on_a_write_is_wrapped_like_any_other():
    client = _client()

    with patch.object(
        api_client.httpx,
        "post",
        side_effect=[_tokens("acc-1", "ref-1"), httpx.ConnectError("connection refused")],
    ):
        with pytest.raises(ApiClientError, match="POST /api/sales-orders"):
            client.post("/api/sales-orders", json={})


@pytest.mark.parametrize(
    ("failure", "may_have_landed"),
    [
        (httpx.ConnectError("refused"), False),
        (httpx.ConnectTimeout("no route"), False),
        (httpx.UnsupportedProtocol("ftp://"), False),
        (httpx.ReadTimeout("timed out"), True),
        (httpx.WriteTimeout("timed out"), True),
        (httpx.RemoteProtocolError("server disconnected"), True),
        (httpx.ReadError("dropped"), True),
    ],
    ids=[
        "refused",
        "connect-timeout",
        "bad-scheme",
        "read-timeout",
        "write-timeout",
        "disconnected",
        "read-error",
    ],
)
def test_a_failure_knows_whether_the_request_could_have_been_acted_on(failure, may_have_landed):
    """The distinction a write depends on: a connection that was never made
    cannot have written anything, but a request that went out and never came
    back can have. Getting this backwards either tells a customer their order
    failed when it exists, or leaves a phantom order they were promised."""
    client = _client()

    with patch.object(api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), failure]):
        with pytest.raises(ApiClientError) as raised:
            client.post("/api/sales-orders", json={})

    assert raised.value.may_have_landed is may_have_landed


@pytest.mark.parametrize("status", [400, 404, 422])
def test_a_refusal_is_certain(status):
    client = _client()

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), _json_response({}, status)]
    ):
        with pytest.raises(ApiClientError) as raised:
            client.post("/api/sales-orders", json={})

    assert raised.value.may_have_landed is False


def test_a_5xx_the_service_composed_itself_is_also_certain():
    """erp_os only writes its own error envelope after rolling back: `get_db`
    rolls the session back and re-raises, and the catch-all handler turns that
    into 500 INTERNAL_ERROR. An unknown customer_id lands here as a foreign key
    violation, and calling that "the order might exist" would forbid the retry
    that could still make the sale."""
    client = _client()
    handled = _json_response({"error_code": "INTERNAL_ERROR"}, status_code=500)

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), handled]
    ):
        with pytest.raises(ApiClientError) as raised:
            client.post("/api/sales-orders", json={})

    assert raised.value.may_have_landed is False


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_gateway_answering_for_a_silent_service_is_not_certain(status):
    """nginx hands back an HTML page for a service that never said what it did."""
    client = _client()
    gateway = Mock(spec=httpx.Response)
    gateway.status_code = status
    gateway.text = "<html><head><title>504 Gateway Time-out</title></head></html>"
    gateway.json.side_effect = ValueError("not json")

    with patch.object(
        api_client.httpx, "post", side_effect=[_tokens("acc-1", "ref-1"), gateway]
    ):
        with pytest.raises(ApiClientError) as raised:
            client.post("/api/sales-orders", json={})

    assert raised.value.may_have_landed is True


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("timed out"), httpx.RemoteProtocolError("disconnected")],
    ids=["read-timeout", "disconnected"],
)
def test_a_read_never_claims_a_write_may_have_happened(failure):
    """Review round 2, P1-1. The order tool reads the catalogue before it posts
    anything, through this same client. A slow catalogue used to reach the tool
    as "the order may already exist, do not place it again" -- losing the sale
    and forbidding the retry, with nothing ever written."""
    client = _client()

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")):
        with patch.object(api_client.httpx, "get", side_effect=failure):
            with pytest.raises(ApiClientError) as raised:
                client.get("/api/skus/12")

    assert raised.value.may_have_landed is False


@pytest.mark.parametrize("status", [500, 502, 504])
def test_a_read_that_got_a_server_error_claims_nothing_either(status):
    client = _client()
    gateway = Mock(spec=httpx.Response)
    gateway.status_code = status
    gateway.text = "<html>502</html>"
    gateway.json.side_effect = ValueError("not json")

    with patch.object(api_client.httpx, "post", return_value=_tokens("acc-1", "ref-1")):
        with patch.object(api_client.httpx, "get", return_value=gateway):
            with pytest.raises(ApiClientError) as raised:
                client.get("/api/skus/12")

    assert raised.value.may_have_landed is False
