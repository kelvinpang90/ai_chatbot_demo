"""Round 2, P2-1. The description column is cut at 38 characters, mid-token.

The names below are verbatim from the live catalogue behind the demo
(`GET https://erp.kelvinpeng.com/api/skus`, read 2026-09-03): 12 of the 201 SKUs
are longer than `invoice_pdf.DESCRIPTION_CHARS`, and Malaysian FMCG names end in
the pack size, so the cut does not merely shorten the name -- it prints a
different one. "Farm Fresh Chocolate Flavoured Milk 200ml" arrives on the
customer's e-Invoice as "Farm Fresh Chocolate Flavoured Milk 20", and
"Panasonic Electric Kettle 1.8L NC-EG3000" as a model number that does not
exist, "...NC-EG30".

The assertion is the acceptance criterion of task 10 in its plainest form: the
product the ERP named has to be the product the customer's copy names.
"""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from app.services import invoice_pdf

# Every live SKU name longer than DESCRIPTION_CHARS, as the ERP stores it.
LIVE_NAMES_THAT_DO_NOT_FIT = [
    "Panasonic Electric Kettle 1.8L NC-EG3000",
    "Nescafe Classic Instant Coffee Jar 200g",
    "Old Town White Coffee 3-in-1 Original 12s",
    "Dutch Lady Chocolate Flavoured Milk 200ml",
    "Farm Fresh Chocolate Flavoured Milk 200ml",
    "Marigold Full Cream Evaporated Milk 390g",
    "Pantene Total Damage Care Shampoo 400ml",
    "Colgate Total Whitening Toothpaste 200g",
    "Jasmine Thai Hom Mali Fragrant Rice 5kg",
    "Julie's Biscuit Rolls Peanut Butter 126g",
    "Faber-Castell 1432 Ballpoint Pen Blue 12s",
]

# One real invoice header, in the shape erp_os's InvoiceDetail returns.
HEADER = {
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
}


def _rendered_text(description: str) -> str:
    invoice = {
        **HEADER,
        "lines": [
            {
                "description": description,
                "sku_name": description,
                "qty": "10.0000",
                "unit_price_excl_tax": "26.0500",
                "line_total_excl_tax": "260.5000",
                "line_total_incl_tax": "286.5500",
            }
        ],
    }
    reader = PdfReader(io.BytesIO(invoice_pdf.render(invoice)))
    return reader.pages[0].extract_text()


@pytest.mark.parametrize("description", LIVE_NAMES_THAT_DO_NOT_FIT)
def test_the_customers_copy_names_the_product_the_erp_named(description: str) -> None:
    text = _rendered_text(description)

    # The message reads the row off the page rather than recomputing it from a
    # constant in the module: `DESCRIPTION_CHARS` was deleted by the fix, and an
    # assertion message is evaluated only when the assertion fails -- so naming
    # it here turned a future regression into an AttributeError instead of a
    # diagnosis. Round 3, P3-2.
    assert description in text, (
        f"the ERP sells {description!r}; the invoice the customer keeps says "
        f"{next((line for line in text.splitlines() if description[:12] in line), '<no such row>')!r}"
    )
