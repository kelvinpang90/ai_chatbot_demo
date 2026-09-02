"""Drive the shipped crm_create_lead at the live CRM, read the board back, clean up.

Runs the unmodified eb791f7e code. Two calls on one number: the first exercises
the new-contact path, the second the returning-customer path that round 1 only
touched in passing. Everything created here is soft-deleted at the end.
"""
import json
import os

import httpx

from app.config import settings

settings.crm_email = os.environ["CRM_EMAIL"]
settings.crm_password = os.environ["CRM_PASSWORD"]

from app.services import crm_client  # noqa: E402
from app.tools import crm  # noqa: E402

PHONE = "+60 11-2266 7788"
BASE = settings.crm_base_url

print("=== call 1: nobody on file with that number ===")
first = crm.crm_create_lead(
    "Review Round Two", PHONE, "2 units Sony WF-C710N earbuds, COD to Cheras", 986.70
)
print(first)

print("\n=== call 2: same number again ===")
second = crm.crm_create_lead(
    "Review Round Two", PHONE, "and a Pensonic stand fan for the shop", 79.90
)
print(second)

tok = httpx.post(
    f"{BASE}/api/auth/login",
    json={"email": settings.crm_email, "password": settings.crm_password},
    timeout=30,
).json()["data"]["access_token"]
h = {"Authorization": f"Bearer {tok}"}

created = []
for raw in (first, second):
    try:
        created.append(json.loads(raw))
    except json.JSONDecodeError:
        print("NOT JSON:", raw)

print("\n=== the board ===")
board = httpx.get(f"{BASE}/api/pipeline", headers=h, timeout=30).json()["data"]
lead_stage = [s for s in board["stages"] if s["status"] == "lead"][0]
print("lead column holds", lead_stage["count"], "cards")
mine = [d for d in lead_stage["deals"] if d["id"] in {c.get("deal_id") for c in created}]
for d in mine:
    print("  CARD", json.dumps(
        {k: d[k] for k in ("id", "contact_name", "title", "amount", "status", "assigned_to_name")},
        ensure_ascii=False,
    ))
print("cards of mine visible on the board:", len(mine), "of", len(created))

print("\n=== the notes inside those cards ===")
for c in created:
    if not c.get("deal_id"):
        continue
    acts = httpx.get(
        f"{BASE}/api/deals/{c['deal_id']}/activities", headers=h, timeout=30
    ).json()["data"]
    print(f"  deal {c['deal_id']}: {len(acts)} activity")
    for a in acts:
        print("   ", a["type"], "|", a["content"])

print("\n=== contacts now on file with that number ===")
crm_client.reset()
print(json.dumps(
    [{"id": r["id"], "name": r["name"], "phone": r["phone"]}
     for r in crm_client.client().lookup_contacts(PHONE)],
    ensure_ascii=False,
))

print("\n=== cleanup ===")
for c in created:
    if c.get("deal_id"):
        r = httpx.delete(f"{BASE}/api/deals/{c['deal_id']}", headers=h, timeout=30)
        print("  deal", c["deal_id"], r.status_code)
for cid in {c.get("contact_id") for c in created if c.get("contact_id")}:
    r = httpx.delete(f"{BASE}/api/contacts/{cid}", headers=h, timeout=30)
    print("  contact", cid, r.status_code)
