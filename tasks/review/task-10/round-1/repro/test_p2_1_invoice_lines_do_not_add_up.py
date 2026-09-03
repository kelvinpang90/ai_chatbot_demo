"""The invoice the customer keeps has to add up when they read it.

`invoice_pdf._lines` prints `unit_price_excl_tax` under UNIT PRICE and
`line_total_incl_tax` under AMOUNT. The two are on different tax bases, so every
row of the document contradicts itself in the customer's hands:

    DESCRIPTION                 QTY  UNIT PRICE  AMOUNT
    TWS Earbuds Pro               3      299.00  986.70     <- 3 x 299 = 897.00
    Pensonic Stand Fan 16 inch    1      299.00  328.90     <- 1 x 299 = 299.00
                        Subtotal excl. tax     1,196.00     <- column sums 1,315.60
                        Tax                      119.60
                        TOTAL MYR              1,315.60

erp_os's InvoiceLineResponse already carries `line_total_excl_tax`, so the two
columns can be put on one basis without asking the ERP for anything new.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal

from pypdf import PdfReader

from app.services import invoice_pdf

# One erp_os InvoiceDetail, shaped exactly as the ERP answers: unit price
# exclusive of SST, line totals inclusive of it, at the 10% the demo seeds.
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
    "subtotal_excl_tax": "1196.0000",
    "tax_amount": "119.6000",
    "total_incl_tax": "1315.6000",
    "lines": [
        {
            "description": "TWS Earbuds Pro",
            "qty": "3.0000",
            "unit_price_excl_tax": "299.0000",
            "line_total_excl_tax": "897.0000",
            "line_total_incl_tax": "986.7000",
        },
        {
            "description": "Pensonic Stand Fan",
            "qty": "1.0000",
            "unit_price_excl_tax": "299.0000",
            "line_total_excl_tax": "299.0000",
            "line_total_incl_tax": "328.9000",
        },
    ],
}

# "TWS Earbuds Pro 3 299.00 986.70" as pypdf reads one row back.
ROW = re.compile(r"^(?P<description>\D.*?) (?P<qty>[\d.]+) (?P<unit>[\d,]+\.\d\d) (?P<amount>[\d,]+\.\d\d)$")
SUBTOTAL = re.compile(r"^Subtotal excl\. tax (?P<amount>[\d,]+\.\d\d)$", re.MULTILINE)


def _amount(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _rows(text: str) -> list[re.Match]:
    return [match for line in text.splitlines() if (match := ROW.match(line.strip()))]


def test_each_printed_line_multiplies_out_to_the_amount_beside_it():
    text = PdfReader(io.BytesIO(invoice_pdf.render(INVOICE))).pages[0].extract_text()

    rows = _rows(text)
    assert len(rows) == len(INVOICE["lines"]), f"could not read the line rows back from:\n{text}"

    for row in rows:
        quantity = Decimal(row["qty"])
        unit = _amount(row["unit"])
        printed = _amount(row["amount"])
        assert printed == quantity * unit, (
            f"{row['description']}: the page says {row['qty']} x {row['unit']} = "
            f"{row['amount']}, which is wrong by {printed - quantity * unit}"
        )


def test_the_amount_column_reconciles_with_the_subtotal_printed_under_it():
    text = PdfReader(io.BytesIO(invoice_pdf.render(INVOICE))).pages[0].extract_text()

    column = sum(_amount(row["amount"]) for row in _rows(text))
    subtotal = _amount(SUBTOTAL.search(text)["amount"])

    assert column == subtotal, (
        f"the AMOUNT column adds up to {column} but the line under it says the "
        f"subtotal is {subtotal}"
    )
