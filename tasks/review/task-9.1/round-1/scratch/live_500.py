"""Reviewer scratch: a lead that passes _usable but makes crm_os answer 500."""
import json

from app.tools import crm
from app.services import crm_client

NAME = "ZZ Review Probe C"
PHONE = "+60 11-9001 0003"

# Passes `0 <= amount < MAX_AMOUNT`, but DECIMAL(15,2) rounds it up to 10**13.
AMOUNT = 9999999999999.998
print("amount:", repr(AMOUNT), "< MAX_AMOUNT:", AMOUNT < crm_client.MAX_AMOUNT)

out = crm.crm_create_lead(NAME, PHONE, "probe: does a crm_os 500 read as unknown?", AMOUNT)
print("\ntool said:", out)
print("is LEAD_UNKNOWN:", out == crm.LEAD_UNKNOWN)
print("is LEAD_FAILED :", out == crm.LEAD_FAILED)

c = crm_client.client()
found = c.lookup_contacts(PHONE)
print("\ncontacts now on file with that phone:", json.dumps(found, ensure_ascii=False, default=str))
