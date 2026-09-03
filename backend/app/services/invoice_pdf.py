from __future__ import annotations

from decimal import Decimal, InvalidOperation

# erp_os stores an e-Invoice but never renders one: `Invoice.pdf_file_id` has been
# a dangling column since the module was written, and nothing in that repository
# fills it. So the document the customer opens on their phone is built here, from
# the same InvoiceDetail JSON the ERP screen behind us is showing.
#
# Written by hand rather than with reportlab or fpdf2: both pull Pillow and a font
# stack into an image that currently has five runtime dependencies, to lay out one
# page that never changes. What is below is the whole of PDF 1.4 that a one-page
# invoice needs -- a content stream, four of the fourteen fonts every reader is
# required to have, and a cross-reference table.

PAGE_WIDTH = 595  # A4 at 72dpi, in points
PAGE_HEIGHT = 842
MARGIN = 50

# The base-14 fonts, which are never embedded because every PDF reader ships them.
# Helvetica sets the prose; the money columns are Courier because a monospaced
# glyph is exactly 0.6 em wide, which is the whole of the right-alignment maths
# below. The alternative is carrying Helvetica's 300-entry width table around to
# align four numbers.
REGULAR, BOLD, MONO, MONO_BOLD = "F1", "F2", "F3", "F4"
MONO_CHAR_WIDTH = 0.6

# The seller, as `erp_os/backend/scripts/seed_master_data.py:198` seeds it. The
# invoice carries the TIN but no organization name -- nothing in the erp_os API
# exposes one -- so the name is pinned here and the TIN printed beside it comes
# from the invoice itself, where a mismatch would show.
SELLER_NAME = "Demo Malaysia Sdn Bhd"

# Wide enough for the descriptions erp_os generates, narrow enough to leave the
# three money columns room on A4.
DESCRIPTION_CHARS = 38


def _money(value, currency: str = "") -> str:
    """A DECIMAL from the ERP as a person reads it. Blank rather than a lie."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    return f"{currency} {amount:,.2f}".strip()


def _quantity(value) -> str:
    """3 rather than 3.0000, but 2.5 stays 2.5."""
    try:
        quantity = Decimal(str(value)).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "")
    return format(quantity, "f")


def _escape(text: str) -> bytes:
    r"""One string as a PDF literal.

    The base-14 fonts are declared /WinAnsiEncoding, so a byte is a character and
    anything outside it has no glyph to be. erp_os's own data is Latin -- customer
    names, SKU names and MSIC descriptions are all seeded in English or Malay --
    but a stray character must not be allowed to produce a broken file in front of
    a customer, so it degrades to "?" instead.
    """
    encoded = str(text).encode("cp1252", errors="replace")
    for char in (b"\\", b"(", b")"):
        encoded = encoded.replace(char, b"\\" + char)
    return encoded


class _Page:
    """A content stream being written top-down, in a coordinate system that is not.

    PDF measures y up from the bottom of the page; an invoice is written down from
    the top. `self.y` is the PDF coordinate and every helper moves it the way the
    document reads.
    """

    def __init__(self) -> None:
        self._ops: list[bytes] = []
        self.y = float(PAGE_HEIGHT - MARGIN)

    def text(self, x: float, content: str, *, font: str = REGULAR, size: float = 10) -> None:
        self._ops.append(
            b"BT /%s %g Tf 1 0 0 1 %g %g Tm (%s) Tj ET"
            % (font.encode("ascii"), size, x, self.y, _escape(content))
        )

    def right_text(self, x_right: float, content: str, *, font: str = MONO, size: float = 9) -> None:
        """Monospaced only -- see MONO_CHAR_WIDTH for why that is the whole trick."""
        width = len(str(content)) * size * MONO_CHAR_WIDTH
        self.text(x_right - width, content, font=font, size=size)

    def down(self, points: float) -> None:
        self.y -= points

    def rule(self, *, thickness: float = 0.5) -> None:
        self._ops.append(
            b"%g %g %g %g re f" % (MARGIN, self.y, PAGE_WIDTH - 2 * MARGIN, thickness)
        )

    def render(self) -> bytes:
        return b"\n".join(self._ops)


def _document(content: bytes) -> bytes:
    """The six objects, the cross-reference table, and the offsets that tie them.

    Every byte offset in the xref table is the position of an object as written,
    which is why the file is assembled once, in order, and measured as it grows.
    A reader that finds one of them wrong reports a damaged file.
    """
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font "
        b"<< /F1 5 0 R /F2 6 0 R /F3 7 0 R /F4 8 0 R >> >> /Contents 4 0 R >>"
        % (PAGE_WIDTH, PAGE_HEIGHT),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        font % b"Helvetica",
        font % b"Helvetica-Bold",
        font % b"Courier",
        font % b"Courier-Bold",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_at = len(out)
    size = len(objects) + 1
    out += b"xref\n0 %d\n" % size
    out += b"0000000000 65535 f \n"  # the head of the free list, always object 0
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    return bytes(out)


def _header(page: _Page, invoice: dict) -> None:
    page.text(MARGIN, SELLER_NAME, font=BOLD, size=16)
    page.down(14)
    page.text(MARGIN, f"TIN {invoice.get('seller_tin') or '-'}", size=9)

    page.down(30)
    page.text(MARGIN, f"e-Invoice {invoice.get('document_no', '')}", font=BOLD, size=13)
    page.down(16)
    page.text(MARGIN, f"Issued  {invoice.get('business_date', '')}", size=9)
    page.text(200, f"Due  {invoice.get('due_date') or '-'}", size=9)
    page.text(340, f"Sales order  {invoice.get('sales_order_no') or '-'}", size=9)


def _lhdn(page: _Page, invoice: dict) -> None:
    """The line that makes this an e-Invoice rather than a printout.

    A DRAFT has no UIN yet, and saying "pending" is the truthful version of that --
    the alternative is a blank space the customer reads as a missing number.
    """
    uin = invoice.get("uin")
    page.down(18)
    page.text(MARGIN, f"LHDN status  {invoice.get('status', '')}", size=9)
    page.text(200, f"UIN  {uin or 'pending validation'}", size=9)


def _buyer(page: _Page, invoice: dict) -> None:
    page.down(30)
    page.text(MARGIN, "BILL TO", font=BOLD, size=9)
    page.down(14)
    page.text(MARGIN, invoice.get("customer_name") or "-", size=11)
    page.down(13)
    page.text(MARGIN, f"TIN {invoice.get('buyer_tin') or '-'}", size=9)


# The three money columns end here, and the description starts at the margin.
QTY_RIGHT = 355.0
UNIT_PRICE_RIGHT = 445.0
AMOUNT_RIGHT = float(PAGE_WIDTH - MARGIN)


def _lines(page: _Page, invoice: dict) -> None:
    page.down(30)
    page.text(MARGIN, "DESCRIPTION", font=MONO_BOLD, size=9)
    page.right_text(QTY_RIGHT, "QTY", font=MONO_BOLD)
    page.right_text(UNIT_PRICE_RIGHT, "UNIT PRICE", font=MONO_BOLD)
    page.right_text(AMOUNT_RIGHT, "AMOUNT", font=MONO_BOLD)
    page.down(6)
    page.rule()

    for line in invoice.get("lines") or []:
        page.down(16)
        description = line.get("description") or line.get("sku_name") or ""
        page.text(MARGIN, description[:DESCRIPTION_CHARS], font=MONO, size=9)
        page.right_text(QTY_RIGHT, _quantity(line.get("qty")))
        # Both money columns exclude tax, which is the only pairing that reads.
        # Printing the unit price without SST beside a line total with it gave
        # every row of the customer's own invoice an arithmetic they could see
        # was wrong -- 3 x 299.00 = 986.70 -- and left the AMOUNT column summing
        # to something other than the subtotal directly beneath it. Tax is what
        # the two lines under the rule are for.
        page.right_text(UNIT_PRICE_RIGHT, _money(line.get("unit_price_excl_tax")))
        page.right_text(AMOUNT_RIGHT, _money(line.get("line_total_excl_tax")))

    page.down(10)
    page.rule()


def _totals(page: _Page, invoice: dict) -> None:
    currency = invoice.get("currency") or ""
    for label, value in (
        ("Subtotal excl. tax", invoice.get("subtotal_excl_tax")),
        ("Tax", invoice.get("tax_amount")),
    ):
        page.down(16)
        page.right_text(UNIT_PRICE_RIGHT, label, font=MONO)
        page.right_text(AMOUNT_RIGHT, _money(value))

    page.down(20)
    page.right_text(UNIT_PRICE_RIGHT, f"TOTAL {currency}".strip(), font=MONO_BOLD, size=11)
    page.right_text(AMOUNT_RIGHT, _money(invoice.get("total_incl_tax")), font=MONO_BOLD, size=11)


def render(invoice: dict) -> bytes:
    """One erp_os InvoiceDetail as a one-page PDF.

    Only reads the invoice, so it cannot be the step that fails a write: by the
    time this runs the invoice already exists in the ERP.
    """
    page = _Page()
    _header(page, invoice)
    _lhdn(page, invoice)
    _buyer(page, invoice)
    _lines(page, invoice)
    _totals(page, invoice)

    page.y = MARGIN
    page.text(
        MARGIN,
        "Demonstration document generated from the live ERP. Not a tax invoice.",
        size=8,
    )
    return _document(page.render())


def filename_for(invoice: dict) -> str:
    """What the customer sees in their chat. The invoice number, or something."""
    document_no = str(invoice.get("document_no") or "e-invoice").strip()
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in document_no)
    return f"{safe or 'e-invoice'}.pdf"
