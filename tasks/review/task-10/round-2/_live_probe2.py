"""Read-only: how much of the live catalogue and customer book the PDF can print."""
import os

import httpx

BASE = "https://erp.kelvinpeng.com"
login = httpx.post(
    f"{BASE}/api/auth/login",
    json={"email": os.environ["ERP_EMAIL"], "password": os.environ["ERP_PASSWORD"]},
    timeout=30,
)
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}


def page_all(path, key="items", **params):
    out, page = [], 1
    while True:
        r = httpx.get(f"{BASE}{path}", params={**params, "page": page, "page_size": 100},
                      headers=headers, timeout=30).json()
        rows = r.get(key, [])
        out += rows
        if len(rows) < 100:
            return out
        page += 1


skus = page_all("/api/skus")
customers = page_all("/api/customers")
print("skus:", len(skus), "customers:", len(customers))

LIMIT = 38
long_skus = [s["name"] for s in skus if len(s["name"]) > LIMIT]
print(f"\nSKU names longer than DESCRIPTION_CHARS={LIMIT}: {len(long_skus)} / {len(skus)}")
for n in long_skus[:25]:
    print(f"  {len(n):>3}  {n!r}  -> printed as {n[:LIMIT]!r}")


def unprintable(text):
    try:
        text.encode("cp1252")
        return False
    except UnicodeEncodeError:
        return True


bad_sku = [s["name"] for s in skus if unprintable(s["name"])]
bad_cust = [c["name"] for c in customers if unprintable(c["name"])]
print("\nSKU names with no WinAnsi glyph:", len(bad_sku), bad_sku[:10])
print("Customer names with no WinAnsi glyph:", len(bad_cust), bad_cust[:10])

long_cust = [c["name"] for c in customers if len(c["name"]) > 45]
print("\nCustomer names longer than 45 chars:", len(long_cust), long_cust[:10])

# How many lines an invoice can have, against the one page the renderer draws.
inv = page_all("/api/invoices")
print("\ninvoices:", len(inv))
