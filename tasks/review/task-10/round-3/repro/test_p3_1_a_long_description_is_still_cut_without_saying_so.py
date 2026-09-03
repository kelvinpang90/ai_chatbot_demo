"""Round 3, P3-1. The wrap fixed the 38-character cut and moved it to 138.

`invoice_pdf._description_rows` wraps at 46 characters and then keeps only
`MAX_DESCRIPTION_ROWS = 3` of them. Past that the tail is dropped with nothing on
the page to say so -- no ellipsis, no marker -- which is the same thing round 2's
P2-1 was about: a row that reads as a complete, correct description on a document
headed e-Invoice and carrying an LHDN UIN, while naming something the ERP does
not sell.

Two sentences in the same file disagree about this. Line 40:

    # Anything past the column now wraps, so no name is ever silently changed

Line 45, five lines later:

    # A description spilling past this many rows would be a name nobody wrote

and the docstring of the function itself says "broken across as many rows as it
needs, never shortened".

What the assertion demands is only what those sentences already promise, and it
is deliberately fix-agnostic: either the whole name reaches the page, or the row
carries a visible mark that it was cut. Raising the cap, dropping it, or
appending an ellipsis all turn this green.

Reachability, stated plainly: no live SKU name comes near 138 characters -- the
longest in the catalogue is 41 -- so nothing in the demo triggers this today. The
route that exists is `SOLineCreate.description`
(`erp_os/backend/app/schemas/sales_order.py:17`), `Optional[str] max_length=500`,
copied verbatim onto the invoice line by `services/einvoice.py:342` and from
there onto the customer's copy. It is filed P3 for that reason. The reason it is
filed at all is that the cap is the previous defect with a bigger number in front
of it, and the file's own comment says it is not.
"""
from __future__ import annotations

import io

from pypdf import PdfReader

from app.services import invoice_pdf

# 208 characters: a line description of the kind erp_os's own API accepts.
LONG_DESCRIPTION = (
    "Panasonic Electric Kettle 1.8L NC-EG3000 Stainless Steel Cordless Jug with "
    "Rapid Boil Dry Protection Removable Filter Two Year Warranty Malaysia Set "
    "Bundled With Free Descaler Sachet And Extended Service Plan"
)

INVOICE = {
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
    "lines": [
        {
            "description": LONG_DESCRIPTION,
            "qty": "3.0000",
            "unit_price_excl_tax": "299.0000",
            "line_total_excl_tax": "897.0000",
            "line_total_incl_tax": "986.7000",
        }
    ],
}

CUT_MARKS = ("...", "…")


def test_the_helper_either_keeps_the_whole_name_or_says_it_cut_it() -> None:
    rows = invoice_pdf._description_rows(LONG_DESCRIPTION)
    printed = " ".join(rows)

    assert printed == LONG_DESCRIPTION or printed.rstrip().endswith(CUT_MARKS), (
        "the ERP line reads "
        f"{LONG_DESCRIPTION!r}; the invoice the customer keeps says "
        f"{printed!r} and nothing on it marks the cut"
    )


def test_the_page_the_customer_opens_carries_the_end_of_the_name() -> None:
    reader = PdfReader(io.BytesIO(invoice_pdf.render(INVOICE)))
    text = reader.pages[0].extract_text()
    # Newlines are where the wrap put them, so compare on the words.
    flattened = " ".join(text.split())

    assert LONG_DESCRIPTION in flattened or any(mark in text for mark in CUT_MARKS), (
        "the last words of the line description "
        f"({LONG_DESCRIPTION[-40:]!r}) are not on the page, and the page does "
        "not say anything was left off"
    )
