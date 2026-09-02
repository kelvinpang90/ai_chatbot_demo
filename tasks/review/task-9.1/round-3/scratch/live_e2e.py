"""Drive the unmodified 22180e0 crm_create_lead against the live CRM.

Round 2 ran this against eb791f7. The commit under review changed which existing
contact a write lands on (`is_the_same_number`), so the returning-customer path
and the collision path have to be re-run on the real book, not on FakeCrm.

Three calls, every row soft-deleted at the end:
  1. a number nobody is on file with  -> one contact, one card
  2. the same number, national notation -> the SAME contact, a second card
  3. "03-8555 1515", which shares eight digits with David Park's US number
     -> a new contact, NOT a card filed onto David Park
"""
import json
import os

import httpx

from app.config import settings

settings.crm_email = os.environ["CRM_EMAIL"]
settings.crm_password = os.environ["CRM_PASSWORD"]

from app.services import crm_client  # noqa: E402
from app.tools import crm  # noqa: E402

BASE = settings.crm_base_url
DAVID = "8d6c83d7-5373-4ca9-a4d1-21e919599d90"

calls = [
    ("+60 11-2266 7799", "Review Round Three", "3 units Sony WF-C710N earbuds, COD to Cheras", 986.70),
    ("011-2266 7799", "Review Round Three", "and a Pensonic stand fan for the shop", 79.90),
    ("03-8555 1515", "Shah Alam Hardware", "20 units ceiling fan, quote please", 4500.00),
]

results = []
for phone, name, enquiry, amount in calls:
    print(f"=== crm_create_lead({name!r}, {phone!r}, ..., {amount}) ===")
    raw = crm.crm_create_lead(name, phone, enquiry, amount)
    print("   ", raw)
    try:
        results.append(json.loads(raw))
    except json.JSONDecodeError:
        results.append(None)
    print()

tok = httpx.post(
    f"{BASE}/api/auth/login",
    json={"email": settings.crm_email, "password": settings.crm_password},
    timeout=30,
).json()["data"]["access_token"]
h = {"Authorization": f"Bearer {tok}"}

print("=== assertions ===")
one, two, three = results
print("1&2 same contact (returning customer):", one and two and one["contact_id"] == two["contact_id"])
print("1&2 different cards:", one and two and one["deal_id"] != two["deal_id"])
print("3 is NOT David Park:", three and three["contact_id"] != DAVID)

print()
print("=== the board ===")
board = httpx.get(f"{BASE}/api/pipeline", headers=h, timeout=30).json()["data"]
lead = [s for s in board["stages"] if s["status"] == "lead"][0]
mine = {c["deal_id"] for c in results if c and c.get("deal_id")}
seen = [d for d in lead["deals"] if d["id"] in mine]
print("lead column holds", lead["count"], "cards;", len(seen), "of", len(mine), "of mine visible")
for d in seen:
    print("   CARD", json.dumps(
        {k: d[k] for k in ("contact_name", "title", "amount", "status", "assigned_to_name")},
        ensure_ascii=False))

print()
print("=== the notes inside those cards ===")
for c in results:
    if not (c and c.get("deal_id")):
        continue
    acts = httpx.get(f"{BASE}/api/deals/{c['deal_id']}/activities", headers=h, timeout=30).json()["data"]
    print(f"   deal {c['deal_id']}: {len(acts)} activity")
    for a in acts:
        print("     ", a["type"], "|", a["content"])

print()
print("=== David Park's deals (must be untouched) ===")
dp = httpx.get(f"{BASE}/api/deals", headers=h, params={"contact_id": DAVID}, timeout=30).json()["data"]
print("   ", [(d["id"], d["title"], d["amount"]) for d in dp])

print()
print("=== contacts on file for +60 11-2266 7799 ===")
crm_client.reset()
print("   ", json.dumps(
    [{"id": r["id"], "name": r["name"], "phone": r["phone"]}
     for r in crm_client.client().lookup_contacts("+60 11-2266 7799")], ensure_ascii=False))

print()
print("=== cleanup ===")
for c in results:
    if c and c.get("deal_id"):
        print("   deal", c["deal_id"],
              httpx.delete(f"{BASE}/api/deals/{c['deal_id']}", headers=h, timeout=30).status_code)
for cid in {c.get("contact_id") for c in results if c and c.get("contact_id")}:
    print("   contact", cid,
          httpx.delete(f"{BASE}/api/contacts/{cid}", headers=h, timeout=30).status_code)
