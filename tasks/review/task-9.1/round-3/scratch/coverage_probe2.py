"""Is the write boundary itself right, even though no test reaches it?

Let the login succeed, then raise the transport failure at POST /api/contacts.
"""
from unittest.mock import patch

import httpx

from app.config import settings
from app.services import api_client, crm_client
from app.tools import crm

LOGIN = httpx.Response(
    200,
    json={"success": True, "data": {"access_token": "a", "refresh_token": "r"}},
    request=httpx.Request("POST", "https://crm/api/auth/login"),
)
BOOK = httpx.Response(
    200,
    json={"success": True, "data": {"data": [], "total": 0, "page": 1, "page_size": 100}},
    request=httpx.Request("GET", "https://crm/api/contacts"),
)

NAMES = {
    "LEAD_FAILED": crm.LEAD_FAILED,
    "LEAD_UNKNOWN": crm.LEAD_UNKNOWN,
    "BAD_LEAD": crm.BAD_LEAD,
}

for failure in [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
    httpx.RemoteProtocolError("server disconnected"),
]:
    crm_client.reset()
    with patch.object(settings, "crm_email", "demo@crm.test"):
        with patch.object(settings, "crm_password", "pw"):
            with patch.object(api_client.httpx, "get", return_value=BOOK):
                with patch.object(api_client.httpx, "post", side_effect=[LOGIN, failure]):
                    answer = crm.crm_create_lead(
                        "Ahmad Faizal", "+60 12-333 4444", "3 units earbuds", 986.70
                    )
    label = next((k for k, v in NAMES.items() if v == answer), answer[:60])
    print(f"{type(failure).__name__:22} at POST /api/contacts -> {label}")

crm_client.reset()
