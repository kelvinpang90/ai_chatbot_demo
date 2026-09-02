"""Reviewer scratch: run the shipped tool against the live crm_os and read the board back."""
import json
import sys

import httpx

from app.tools import crm
from app.services import crm_client

PHONE = "+60 11-9001 2345"
NAME = "Review Bot Nine One"
ENQUIRY = "3 units Sony WF-C710N earbuds, COD to Cheras"

print("=== crm_create_lead (live) ===")
out = crm.crm_create_lead(NAME, PHONE, ENQUIRY, 986.70)
print(out)

try:
    payload = json.loads(out)
except Exception:
    sys.exit(1)

c = crm_client.client()
print("\n=== GET /api/pipeline ===")
board = c.get("/api/pipeline")
found = None
for stage in board["stages"]:
    for d in stage["deals"]:
        if d["id"] == payload["deal_id"]:
            found = (stage["status"], d)
print("card on board:", json.dumps(found, ensure_ascii=False, default=str))

print("\n=== GET /api/deals/{id}/activities ===")
acts = c.get(f"/api/deals/{payload['deal_id']}/activities")
print(json.dumps(acts, ensure_ascii=False, default=str))

print("\n=== second call, same phone (returning customer) ===")
out2 = crm.crm_create_lead(NAME, PHONE, "another 2 units, pickup", 500.0)
print(out2)
p2 = json.loads(out2)
print("same contact?", p2["contact_id"] == payload["contact_id"])

print("\n=== deals for that contact ===")
deals = c.get("/api/deals", params={"contact_id": payload["contact_id"]})
print(json.dumps([{k: d[k] for k in ("id", "title", "amount", "status", "assigned_to_name")} for d in deals], ensure_ascii=False))

print("\nCONTACT_ID_FOR_CLEANUP=" + str(payload["contact_id"]))
