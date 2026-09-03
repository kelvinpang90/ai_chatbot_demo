"""Read-only probe: render invoices through the commit's own invoice_pdf and look
at what actually lands on the page. Run inside the pytest_docker image."""
import io
import re

from pypdf import PdfReader

from app.services import invoice_pdf

BASE = {
    "document_no": "INV-2026-0007",
    "sales_order_no": "SO-2026-0042",
    "status": "VALIDATED",
    "uin": "MY-UIN-8891234",
    "seller_tin": "C2584563200",
    "buyer_tin": "C1234567890",
    "customer_name": "Sunrise Hypermart Sdn Bhd",
    "business_date": "2026-09-03",
    "due_date": "2026-10-03",
    "currency": "MYR",
    "subtotal_excl_tax": "897.0000",
    "tax_amount": "89.7000",
    "total_incl_tax": "986.7000",
    "lines": [],
}


def text(inv):
    return PdfReader(io.BytesIO(invoice_pdf.render(inv))).pages[0].extract_text()


def line(desc, qty="3.0000", up="299.0000", ex="897.0000"):
    return {
        "description": desc,
        "qty": qty,
        "unit_price_excl_tax": up,
        "line_total_excl_tax": ex,
        "line_total_incl_tax": "986.7000",
    }


print("=== width")
print(invoice_pdf._description_rows("x" * 200))

print("\n=== 1. wrapped name actually rendered?")
long_name = "Panasonic Electric Kettle 1.8L NC-EG3000 Stainless Steel Cordless Jug"
t = text({**BASE, "lines": [line(long_name)]})
print(repr(t))
print("rows present:", [r in t for r in invoice_pdf._description_rows(long_name)])

print("\n=== 2. very long description (500-char column max)")
name = (
    "Panasonic Electric Kettle 1.8L NC-EG3000 Stainless Steel Cordless Jug with "
    "Rapid Boil Dry Protection Removable Filter Two Year Warranty Malaysia Set "
    "Bundled With Free Descaler Sachet And Extended Service Plan"
)
print("len", len(name))
rows = invoice_pdf._description_rows(name)
print("rows", rows)
print("join == name?", " ".join(rows) == name)
t2 = text({**BASE, "lines": [line(name)]})
print("tail present?", name[-30:] in t2)
print("ellipsis anywhere?", "..." in t2 or "…" in t2)

print("\n=== 3. quantities test fixture (no line_total_excl_tax)")
t3 = text(
    {
        **BASE,
        "total_incl_tax": "1234567.8900",
        "lines": [
            {
                "description": "Half a metre",
                "qty": "0.5000",
                "unit_price_excl_tax": "8.0000",
                "line_total_incl_tax": "8.4800",
            }
        ],
    }
)
row = [ln for ln in t3.splitlines() if ln.startswith("Half a metre")]
print("row:", row)
print("money on row:", re.findall(r"[\d,]+\.\d\d", row[0]) if row else None)

print("\n=== 4. four seeded-style lines, page geometry")
four = {
    **BASE,
    "lines": [line(n) for n in [
        "Old Town White Coffee 3-in-1 Original 12s",
        "Farm Fresh Chocolate Flavoured Milk 200ml",
        "Marigold Full Cream Evaporated Milk 390g",
        "Panasonic Electric Kettle 1.8L NC-EG3000",
    ]],
}
print(text(four))

print("\n=== 5. lowest y written on the page for N lines")
for n in (1, 4, 10, 20, 30, 40):
    inv = {**BASE, "lines": [line("Milo Tin 400g") for _ in range(n)]}
    pdf = invoice_pdf.render(inv)
    ys = [float(m) for m in re.findall(rb"Tm", pdf) and re.findall(r"1 0 0 1 [\d.\-]+ ([\d.\-]+) Tm", pdf.decode("latin-1"))]
    print(n, "lines -> lowest y:", min(ys))
