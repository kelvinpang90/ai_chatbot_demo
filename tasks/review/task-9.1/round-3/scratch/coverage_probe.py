"""Which URL does the new "regression twin" test actually raise its failure at?

test_a_real_transport_failure_on_a_lead_degrades_instead_of_escaping patches
httpx.post with a bare side_effect, so the *first* post raises -- and the first
post a lead makes is the login, not the write. Print the URLs to see whether
/api/contacts is ever reached.
"""
from unittest.mock import patch

import httpx

from app.config import settings
from app.services import api_client, crm_client
from app.tools import crm

FAILURES = [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
    httpx.HTTPStatusError(
        "429", request=httpx.Request("POST", "https://crm"), response=httpx.Response(429)
    ),
]

for failure in FAILURES:
    crm_client.reset()
    seen = []

    def spy(url, **kwargs):
        seen.append(url)
        raise failure

    with patch.object(settings, "crm_email", "demo@crm.test"):
        with patch.object(settings, "crm_password", "pw"):
            with patch.object(api_client.httpx, "post", side_effect=spy):
                answer = crm.crm_create_lead(
                    "Ahmad Faizal", "+60 12-333 4444", "3 units earbuds", 986.70
                )
    print(type(failure).__name__)
    print("   urls posted:", seen)
    print("   reached /api/contacts:", any("/api/contacts" in u for u in seen))
    print("   answer:", "LEAD_FAILED" if answer == crm.LEAD_FAILED else answer[:40])

crm_client.reset()
