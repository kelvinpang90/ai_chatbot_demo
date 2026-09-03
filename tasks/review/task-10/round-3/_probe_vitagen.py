"""Read-only probe: the one live SKU name with a non-ASCII character."""
import io

from pypdf import PdfReader

from app.services import invoice_pdf

NAME = "Vitagen Original Cultured Milk 5 × 125ml"
print("name:", NAME, "len", len(NAME))
print("codepoints:", [hex(ord(c)) for c in NAME if ord(c) > 127])
print("escaped bytes:", invoice_pdf._escape(NAME))
print("rows:", invoice_pdf._description_rows(NAME))

INVOICE = {
    "document_no": "INV-SEED-00003",
    "sales_order_no": "SO-SEED-00003",
    "status": "FINAL",
    "uin": "INV-11660253-DEMO",
    "seller_tin": "EI00000000010",
    "buyer_tin": "C3322332233",
    "customer_name": "Universiti Teknologi Mara Berhad",
    "business_date": "2026-08-31",
    "due_date": None,
    "currency": "MYR",
    "subtotal_excl_tax": "260.5000",
    "tax_amount": "26.0500",
    "total_incl_tax": "286.5500",
    "lines": [
        {
            "description": NAME,
            "sku_name": NAME,
            "qty": "10.0000",
            "unit_price_excl_tax": "26.0500",
            "line_total_excl_tax": "260.5000",
            "line_total_incl_tax": "286.5500",
        }
    ],
}

text = PdfReader(io.BytesIO(invoice_pdf.render(INVOICE))).pages[0].extract_text()
print("---- rendered ----")
print(text)
print("---- name present verbatim?", NAME in text)
row = [ln for ln in text.splitlines() if ln.startswith("Vitagen")]
print("row:", row)
print("row codepoints:", [hex(ord(c)) for c in row[0] if ord(c) > 127] if row else None)
