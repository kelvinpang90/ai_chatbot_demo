"""Reviewer scratch: does the shipped transport-failure test reach the transport?"""
from unittest.mock import patch

import httpx

from app.config import settings
from app.services import api_client, crm_client
from app.tools import crm

print("settings.crm_email  =", repr(settings.crm_email))
print("settings.crm_password =", repr(settings.crm_password))

crm_client.reset()
with patch.object(api_client.httpx, "post", side_effect=httpx.ReadTimeout("timed out")) as post:
    answer = crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", "3 units", 986.70)

print("answer is LEAD_FAILED:", answer == crm.LEAD_FAILED)
print("httpx.post called    :", post.call_count, "times")
crm_client.reset()
