"""Read-only probe of the live crm_os routes the new write path depends on.

No writes. Answers three questions the unit tests only assert the developer's
assumption about:
  1. What shape does GET /api/deals?contact_id=X come back in, after _unwrap?
  2. Does /api/deals honour contact_id at all, or ignore an unknown query param?
  3. What is in the contact book (the phone collision round 2 talked about)?
"""
import json
import os

import httpx

BASE = "https://crm.kelvinpeng.com"
tok = httpx.post(
    f"{BASE}/api/auth/login",
    json={"email": os.environ["CRM_EMAIL"], "password": os.environ["CRM_PASSWORD"]},
    timeout=30,
).json()["data"]["access_token"]
h = {"Authorization": f"Bearer {tok}"}


def show(label, r):
    print(f"--- {label}: HTTP {r.status_code}")
    try:
        body = r.json()
    except Exception:
        print("   non-json:", r.text[:200])
        return None
    print("   top-level type:", type(body).__name__, "keys:", list(body)[:6] if isinstance(body, dict) else "")
    data = body.get("data") if isinstance(body, dict) else body
    print("   after _unwrap -> type:", type(data).__name__)
    if isinstance(data, dict):
        print("   unwrapped keys:", list(data))
    elif isinstance(data, list):
        print("   unwrapped len:", len(data))
    return data


contacts = show("GET /api/contacts?page=1", httpx.get(
    f"{BASE}/api/contacts", headers=h, params={"page": 1, "page_size": 100}, timeout=30))
rows = contacts.get("data", []) if isinstance(contacts, dict) else contacts
print("   contacts on page 1:", len(rows))
print("   total:", contacts.get("total") if isinstance(contacts, dict) else "?")
for r in rows[:60]:
    print("      ", r.get("id"), "|", r.get("name"), "|", r.get("phone"))

cid = rows[0].get("id") if rows else None
print()
deals = show(f"GET /api/deals?contact_id={cid}", httpx.get(
    f"{BASE}/api/deals", headers=h, params={"contact_id": cid}, timeout=30))
print("   raw:", json.dumps(deals, ensure_ascii=False)[:600])

print()
all_deals = show("GET /api/deals (no filter)", httpx.get(
    f"{BASE}/api/deals", headers=h, timeout=30))
print("   raw:", json.dumps(all_deals, ensure_ascii=False)[:400])

print()
print("=== does contact_id actually filter? ===")
def ids(d):
    seq = d.get("data") if isinstance(d, dict) else d
    return [x.get("id") for x in seq] if isinstance(seq, list) else "NOT-A-LIST"
print("   filtered:", ids(deals))
print("   unfiltered:", ids(all_deals))

print()
print("=== bogus contact_id (does an unknown id filter to empty, or ignore?) ===")
bogus = show("GET /api/deals?contact_id=00000000-0000-0000-0000-000000000000", httpx.get(
    f"{BASE}/api/deals", headers=h,
    params={"contact_id": "00000000-0000-0000-0000-000000000000"}, timeout=30))
print("   ids:", ids(bogus))
