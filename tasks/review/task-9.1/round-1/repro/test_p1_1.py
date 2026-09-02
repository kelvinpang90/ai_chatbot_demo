"""P1-1: a crm_os 500 is a rolled-back write, but the lead tool calls it "unknown".

The classification lives in `api_client._composed_by_the_service`, and the comment
justifying it names erp_os: "erp_os and crm_os answer an error they handled with
their own JSON envelope". Half of that is false. crm_os registers no exception
handler at all (`crm_os/backend/app/main.py`), so an error it handled comes back
as Starlette's default -- `text/plain`, body `Internal Server Error`. The JSON
probe fails, the failure is filed as "the gateway answered for us", and a POST
gets `may_have_landed=True`.

Captured from the live service on 2026-09-02:

    POST https://crm.kelvinpeng.com/api/contacts  {"initial_amount": 1e14, ...}
    status=500 ctype=text/plain; charset=utf-8
    body=Internal Server Error

while `get_db` (crm_os/backend/app/database.py) had already rolled the session
back -- a lookup for that phone afterwards returned [].

Task 9.1 is the first task that writes to the CRM, which is the first time
`may_have_landed` means anything on this client. The bytes above are the real
input; the tests shipped with the commit build `ApiClientError(may_have_landed=X)`
by hand and so can only confirm the choice the author already made.
"""
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services import api_client, crm_client
from app.tools import crm

LOGIN = {"success": True, "data": {"access_token": "a", "refresh_token": "r"}}
NO_CONTACTS = {"success": True, "data": {"data": [], "total": 0, "page": 1, "page_size": 100}}

ENQUIRY = "3 units Sony WF-C710N earbuds, COD to Cheras"


@pytest.fixture(autouse=True)
def _a_configured_client(monkeypatch):
    """Credentials, or `_login` refuses before a single byte reaches httpx."""
    monkeypatch.setattr(settings, "crm_email", "admin@crm.com")
    monkeypatch.setattr(settings, "crm_password", "secret")
    crm_client.reset()
    yield
    crm_client.reset()


def _get(url, **_kwargs):
    return httpx.Response(200, json=NO_CONTACTS, request=httpx.Request("GET", url))


def _post(url, **_kwargs):
    request = httpx.Request("POST", url)
    if url.endswith("/api/auth/login"):
        return httpx.Response(200, json=LOGIN, request=request)
    if url.endswith("/api/contacts"):
        # Byte for byte what crm.kelvinpeng.com returned above.
        return httpx.Response(
            500,
            content=b"Internal Server Error",
            headers={"content-type": "text/plain; charset=utf-8"},
            request=request,
        )
    raise AssertionError(f"unexpected POST {url}")


def test_a_crm_500_is_a_lead_that_was_not_recorded_not_a_lead_in_doubt():
    with patch.object(api_client.httpx, "get", side_effect=_get):
        with patch.object(api_client.httpx, "post", side_effect=_post):
            answer = crm.crm_create_lead(
                "Ahmad Faizal", "+60 12-333 4444", ENQUIRY, 986.70
            )

    # crm_os rolled back: there is no contact, no card, and nothing for the
    # "colleague will check" in LEAD_UNKNOWN to find. Saying so is the only
    # answer that gets the lead written -- the model can try again.
    assert answer == crm.LEAD_FAILED
