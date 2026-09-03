"""Round 2, P3-1. The round-1 fix moved the AMOUNT column onto
`line_total_excl_tax` and updated one fixture, in `tests/test_invoice_pdf.py`.
The fixture the tool-level tests use, `tests/test_erp_tools.DRAFT_INVOICE`, was
left on the old field, so the four tests that drive `erp_generate_einvoice` end
to end now render an invoice whose AMOUNT column is blank on every row -- and
none of them notices, because all they assert about the bytes handed to Meta is
that they start with `%PDF-`.

`_money` returning "" for a missing value is deliberate ("Blank rather than a
lie"), which is exactly why nothing raises. Against the live ERP the field is
required and always present, so this is a hole in the tests rather than a bug in
the document -- but it is the hole through which a second regression of the
round-1 kind would travel unseen.
"""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

from app.services import invoice_pdf
from tests.test_erp_tools import DRAFT_INVOICE


def _row_for(invoice: dict, description: str) -> str:
    reader = PdfReader(io.BytesIO(invoice_pdf.render(invoice)))
    text = reader.pages[0].extract_text()
    return next(line for line in text.splitlines() if line.startswith(description))


def test_the_fixture_the_tool_tests_render_still_has_an_amount_column() -> None:
    row = _row_for(DRAFT_INVOICE, "TWS Earbuds Pro")
    money = re.findall(r"[\d,]+\.\d\d", row)

    assert money == ["299.00", "897.00"], (
        "the PDF the einvoice tool tests hand to Meta prints "
        f"{money} on its only line -- the AMOUNT column is empty"
    )
