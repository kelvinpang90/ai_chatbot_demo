"""Two probes against the unmodified eb791f7e.

1. Round 1's P1-1 fix, checked against the live crm_os rather than a Mock:
   does a real application 500 now come back as "nothing was written"?
2. Round 1's P3-1 was fixed in test_crm_tools.py. Its twin in test_erp_tools.py
   is the test written to close task 8's flagship P1. Does it reach httpx?
"""
import os
from unittest.mock import patch

import httpx

from app.config import settings

settings.crm_email = os.environ["CRM_EMAIL"]
settings.crm_password = os.environ["CRM_PASSWORD"]

from app.services import api_client, crm_client  # noqa: E402
from app.services.api_client import ApiClientError  # noqa: E402
from app.tools import erp  # noqa: E402

print("=== probe 1: a real crm_os 500, straight at the client ===")
client = crm_client.client()
try:
    client.post(
        "/api/contacts",
        json={
            "name": "Review Round Two 500 probe",
            "phone": "+60 11-2266 7799",
            "initial_status": "lead",
            "initial_title": "probe",
            "initial_amount": 1e14,
        },
    )
    print("no error raised -- the write went through")
except ApiClientError as exc:
    print("error          :", exc)
    print("may_have_landed:", exc.may_have_landed, "  (False == 'nothing was written')")

crm_client.reset()
settings.crm_email = os.environ["CRM_EMAIL"]
settings.crm_password = os.environ["CRM_PASSWORD"]
print("contacts on file with that number now:",
      crm_client.client().lookup_contacts("+60 11-2266 7799"))

print()
print("=== probe 2: test_erp_tools.py:108, replayed exactly as shipped ===")
print("settings.erp_email    =", repr(settings.erp_email))
print("settings.erp_password =", repr(settings.erp_password))
for failure in (
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
    httpx.HTTPStatusError(
        "429", request=httpx.Request("POST", "https://erp"), response=httpx.Response(429)
    ),
):
    with patch.object(api_client.httpx, "post", side_effect=failure) as post:
        a = erp.erp_search_sku("fan")
        b = erp.erp_get_inventory("fan")
    print(f"  {type(failure).__name__:17} assertions pass: {a == b == erp.UNAVAILABLE}"
          f" | httpx.post calls: {post.call_count}")
