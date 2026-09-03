"""Read-only probe of the live ERP: render a real invoice with the reviewed code.

Only GETs after one login. Nothing is written to erp_os.
"""
import io
import json
import os
import re
import sys
from decimal import Decimal

import httpx
from pypdf import PdfReader

sys.path.insert(0, "/app")
from app.services import invoice_pdf  # noqa: E402

BASE = "https://erp.kelvinpeng.com"

login = httpx.post(
    f"{BASE}/api/auth/login",
    json={"email": os.environ["ERP_EMAIL"], "password": os.environ["ERP_PASSWORD"]},
    timeout=30,
)
print("login:", login.status_code)
if login.status_code != 200:
    print(login.text[:500])
    raise SystemExit("login failed -- stopping, per the one-attempt rule")

token = login.json().get("access_token") or login.json().get("token")
headers = {"Authorization": f"Bearer {token}"}

listing = httpx.get(f"{BASE}/api/invoices", params={"page_size": 5}, headers=headers, timeout=30)
print("list:", listing.status_code)
items = listing.json().get("items", [])
print("invoice rows:", [(i["id"], i["document_no"], i["status"], i.get("sales_order_no")) for i in items])

for row in items[:3]:
    detail = httpx.get(f"{BASE}/api/invoices/{row['id']}", headers=headers, timeout=30).json()
    print("\n=== invoice", detail["document_no"], detail["status"], "===")
    print("header:", json.dumps({k: detail.get(k) for k in (
        "customer_name", "sales_order_no", "seller_tin", "buyer_tin", "currency",
        "subtotal_excl_tax", "tax_amount", "discount_amount", "total_incl_tax",
        "business_date", "due_date", "uin")}, default=str))
    for ln in detail.get("lines", []):
        print("  line:", json.dumps({k: ln.get(k) for k in (
            "description", "sku_name", "qty", "unit_price_excl_tax",
            "line_total_excl_tax", "line_total_incl_tax", "discount_amount")}, default=str))

    pdf = invoice_pdf.render(detail)
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    print("--- rendered page ---")
    print(text)

    # The three arithmetics a customer can do on the page as printed.
    printed = [Decimal(m.replace(",", "")) for m in re.findall(r"[\d,]+\.\d\d", text)]
    subtotal = Decimal(str(detail["subtotal_excl_tax"])).quantize(Decimal("0.01"))
    tax = Decimal(str(detail["tax_amount"])).quantize(Decimal("0.01"))
    total = Decimal(str(detail["total_incl_tax"])).quantize(Decimal("0.01"))
    line_sum = sum(
        (Decimal(str(ln["line_total_excl_tax"])).quantize(Decimal("0.01"))
         for ln in detail.get("lines", [])),
        Decimal("0"),
    )
    print("CHECK line_sum == subtotal:", line_sum, subtotal, line_sum == subtotal)
    print("CHECK subtotal + tax == total:", subtotal + tax, total, subtotal + tax == total)
    for ln in detail.get("lines", []):
        q = Decimal(str(ln["qty"])).quantize(Decimal("0.0001"))
        u = Decimal(str(ln["unit_price_excl_tax"])).quantize(Decimal("0.01"))
        a = Decimal(str(ln["line_total_excl_tax"])).quantize(Decimal("0.01"))
        print("CHECK row multiplies out:", q, "x", u, "=", (q * u).quantize(Decimal("0.01")),
              "printed", a, (q * u).quantize(Decimal("0.01")) == a)
