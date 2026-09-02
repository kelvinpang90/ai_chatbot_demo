"""22180e0 replaced "did the body parse as JSON" with a hard-coded list of three
proxy status codes, and named the assumption it rests on:

    "nginx answers for an upstream it cannot reach or wait for with 502, 503
     or 504, never with a bare 500. A 500 always came from the application."

nginx is not the only proxy in front of these two services. Both
crm.kelvinpeng.com and erp.kelvinpeng.com are proxied by Cloudflare:

    $ python probe_edge.py
    https://crm.kelvinpeng.com/api/health 200
        server = cloudflare
        cf-ray = a34b2147fc69933e-SIN
        cf-cache-status = DYNAMIC
    https://erp.kelvinpeng.com/ 200
        server = cloudflare
        cf-ray = a34b214efd4984cc-HKG

Cloudflare does not answer for a failing origin with 502/503/504. It answers
with its own 52x range, and two of those are exactly the case `may_have_landed`
exists for -- the request reached the application and no answer came back:

  520  origin returned an empty, unknown or malformed response (a worker killed
       or a connection dropped *after* the commit looks like this)
  524  origin accepted the connection and did not answer in time

The commit under review classifies both as "the application composed this, so
its transaction was rolled back, so nothing was written". Nothing was rolled
back; the row may be there. The model is told the lead was NOT saved and to try
once more, and the board grows the second card this whole design exists to
prevent.

The previous implementation got these right by accident: a Cloudflare error page
is HTML, so "it did not send JSON" put it in the uncertain tier.
"""
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services import api_client, crm_client
from app.services.api_client import ApiClientError
from app.tools import crm

# Verbatim shape of a Cloudflare origin error: an HTML interstitial, no JSON.
CLOUDFLARE_BODY = (
    b"<!DOCTYPE html><html><head><title>crm.kelvinpeng.com | 520: Web server is "
    b"returning an unknown error</title></head><body>Error 520</body></html>"
)

# 521/522/523 are left out on purpose -- those really do mean the request never
# reached the application, and False is the right answer for them.
LANDED_UNKNOWN = [520, 524]


@pytest.fixture
def crm_credentials():
    crm_client.reset()
    with patch.object(settings, "crm_email", "demo@crm.test"):
        with patch.object(settings, "crm_password", "not-a-real-password"):
            yield
    crm_client.reset()


def _cloudflare(status):
    return httpx.Response(
        status,
        content=CLOUDFLARE_BODY,
        headers={"content-type": "text/html; charset=UTF-8", "server": "cloudflare"},
        request=httpx.Request("POST", "https://crm.kelvinpeng.com/api/contacts"),
    )


def _login():
    return httpx.Response(
        200,
        json={"success": True, "data": {"access_token": "a", "refresh_token": "r"}},
        request=httpx.Request("POST", "https://crm.kelvinpeng.com/api/auth/login"),
    )


def _empty_book():
    return httpx.Response(
        200,
        json={"success": True, "data": {"data": [], "total": 0, "page": 1, "page_size": 100}},
        request=httpx.Request("GET", "https://crm.kelvinpeng.com/api/contacts"),
    )


@pytest.mark.parametrize("status", LANDED_UNKNOWN)
def test_a_cloudflare_error_on_a_write_is_not_certain(status, crm_credentials):
    """At the client boundary: 520/524 must leave `may_have_landed` open."""
    client = crm_client.client()

    with patch.object(
        api_client.httpx, "post", side_effect=[_login(), _cloudflare(status)]
    ):
        with pytest.raises(ApiClientError) as raised:
            client.post("/api/contacts", json={})

    assert raised.value.may_have_landed is True


@pytest.mark.parametrize("status", LANDED_UNKNOWN)
def test_a_lead_cloudflare_could_not_get_an_answer_for_is_not_called_a_failure(
    status, crm_credentials
):
    """And at the tool: "try once more" is what puts two cards on the board."""
    with patch.object(api_client.httpx, "get", return_value=_empty_book()):
        with patch.object(
            api_client.httpx, "post", side_effect=[_login(), _cloudflare(status)]
        ):
            answer = crm.crm_create_lead(
                "Ahmad Faizal", "+60 12-333 4444", "3 units Sony WF-C710N earbuds", 986.70
            )

    assert answer == crm.LEAD_UNKNOWN
