"""The PDF the customer opens on their phone.

Two kinds of assertion here, and the second exists because the first is not
enough. `pypdf` reads a damaged file as happily as a sound one -- given a
cross-reference table pointing at the wrong bytes it prints a warning, rebuilds
the table by scanning, and hands back the page -- so a test that only reads the
output back would stay green through exactly the bug that matters. The offsets
are therefore checked directly, against the file.
"""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

from app.services import invoice_pdf

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
            "description": "Pensonic Stand Fan 16 inch",
            "qty": "3.0000",
            "unit_price_excl_tax": "299.0000",
            "line_total_incl_tax": "986.7000",
        }
    ],
}


def _text(invoice: dict) -> str:
    reader = PdfReader(io.BytesIO(invoice_pdf.render(invoice)))
    assert len(reader.pages) == 1
    return reader.pages[0].extract_text()


def test_a_real_pdf_reader_finds_everything_the_customer_needs_to_recognise_the_bill():
    text = _text(INVOICE)

    # Who is billing whom, for which order.
    assert invoice_pdf.SELLER_NAME in text
    assert "Sunrise Hypermart Sdn Bhd" in text
    assert "INV-2026-0007" in text
    assert "SO-2026-0042" in text
    # The line, and the three numbers that have to reconcile with the ERP screen.
    assert "Pensonic Stand Fan 16 inch" in text
    assert "897.00" in text and "89.70" in text and "986.70" in text
    # What makes it an e-Invoice rather than a printout.
    assert "MY-UIN-8891234" in text


def test_a_draft_says_the_uin_is_pending_rather_than_leaving_a_gap():
    """MyInvois was not reachable; the invoice is still real and still goes out."""
    text = _text({**INVOICE, "status": "DRAFT", "uin": None})

    assert "pending validation" in text
    assert "MY-UIN-8891234" not in text


def test_quantities_and_money_are_rendered_the_way_a_person_writes_them():
    text = _text(
        {
            **INVOICE,
            "total_incl_tax": "1234567.8900",
            "lines": [{"description": "Half a metre", "qty": "0.5000",
                       "unit_price_excl_tax": "8.0000", "line_total_incl_tax": "8.4800"}],
        }
    )

    assert "0.5" in text and "0.5000" not in text
    assert "1,234,567.89" in text


def test_a_character_with_no_glyph_does_not_produce_a_broken_file():
    """erp_os's data is Latin, but a file that fails to open is the one outcome
    worth spending five lines to rule out."""
    text = _text({**INVOICE, "customer_name": "陈氏电器 Sdn Bhd"})

    assert "Sdn Bhd" in text  # the file still opens and still reads


def test_the_filename_is_the_invoice_number_the_customer_can_quote_back():
    assert invoice_pdf.filename_for(INVOICE) == "INV-2026-0007.pdf"
    assert invoice_pdf.filename_for({"document_no": "INV/2026 0007"}) == "INV-2026-0007.pdf"
    assert invoice_pdf.filename_for({}) == "e-invoice.pdf"


def test_every_cross_reference_offset_points_at_the_object_it_claims():
    """The one thing a PDF reader will silently paper over. See the module docstring."""
    pdf = invoice_pdf.render(INVOICE)

    start = int(re.search(rb"startxref\s+(\d+)", pdf).group(1))
    assert pdf[start:start + 4] == b"xref"
    count = int(re.match(rb"xref\s+0 (\d+)", pdf[start:]).group(1))

    entries = re.findall(rb"(\d{10}) (\d{5}) ([nf]) \n", pdf[start:])
    assert len(entries) == count
    assert entries[0][2] == b"f"  # object 0 is always the free-list head

    for number, (offset, _generation, kind) in enumerate(entries[1:], start=1):
        assert kind == b"n"
        assert pdf[int(offset):].startswith(b"%d 0 obj" % number)


def test_the_declared_stream_length_matches_the_bytes_between_the_keywords():
    """A /Length that disagrees with the stream is the other way a reader gives up."""
    pdf = invoice_pdf.render(INVOICE)

    declared = int(re.search(rb"<< /Length (\d+) >>", pdf).group(1))
    body = pdf.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
    assert len(body) == declared
