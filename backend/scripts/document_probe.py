"""Send a PDF through the WhatsApp path by hand and read what the bot says back.

Task 15.1 wired inbound documents up. The tests prove the plumbing; this proves
the two things they cannot -- that Claude actually reads the file, and that the
page numbers under the answer are the model's citations rather than anyone's
guess -- without a phone having to be picked up.

It goes through `dispatch_message`, not around it, so what runs is the real
branch: the same download seam, the same `llm.Document`, the same content
blocks. The only thing replaced is `fetch_media` -- there is no inbound WhatsApp
message to fetch, and `dispatch_message` returns payloads rather than sending
them, so nothing leaves the machine and no customer is messaged.

Three questions, in one conversation, because the interesting ones are the
second and third:

    1. something on page 1   -- did it read the file, and cite the right page
    2. something on page 2   -- is the file STILL there a turn later, which is
                                the whole difference between a document and a
                                photo in this codebase
    3. something in no page  -- does NEVER_INVENT hold against the customer's
                                own document, or does it make an answer up

Needs ANTHROPIC_API_KEY. Run it wherever that is set -- the VPS container, or
locally in the container image:

    python scripts/document_probe.py                   # a generated PDF, contents known
    python scripts/document_probe.py ~/menu.pdf        # a real file, with your own questions
    python scripts/document_probe.py ~/menu.pdf --tools

With no file it writes its own two-page price list, by hand for want of a PDF
library -- the same trick `invoice_pdf` plays and the same happy side effect the
image probe's generated PNG has: the contents are known exactly, so "did the
model read page 2" has a yes-or-no answer. The SKUs and prices in it are
deliberately nothing like the retail bot's seeded catalogue, so an answer that is
right can only have come off the page.

`--tools` attaches the read-only ERP and CRM tools, which is the path the retail
demo really takes: a bot with tools goes to the beta endpoint rather than
`messages.create`, and that endpoint validates a request of its own.

This is not the acceptance criterion. That one is task 17: a real phone, a
customer's own PDF, over the deployed webhook.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.whatsapp_webhook import dispatch_message  # noqa: E402
from app.services import llm, whatsapp_media  # noqa: E402
from app.services.user_store import user_store  # noqa: E402
from app.tools import registry as tool_registry  # noqa: E402

# Its own number, so a probe never lands in a real demo conversation's history.
PHONE = "60100000015"
BOT = "retail"
READ_ONLY_TOOLS = ["erp_search_sku", "erp_get_inventory", "erp_list_orders", "crm_lookup_customer"]

PAGE_WIDTH, PAGE_HEIGHT, MARGIN, LEADING = 595, 842, 60, 22

# Nothing here is in the seeded catalogue, and the prices end in odd sen on
# purpose: a right answer cannot have been remembered, only read.
PAGES = [
    [
        "ACUVEN GADGET SUPPLY - TRADE PRICE LIST 2026",
        "",
        "TX-7742  Solar Power Bank 20000mAh .......... RM 287.50",
        "TX-7801  Rugged Action Camera .............. RM 1,142.00",
        "TX-6620  Mesh Wi-Fi Node (3-pack) ........... RM 733.90",
        "",
        "All prices are ex-warehouse Shah Alam and exclude SST.",
    ],
    [
        "ACUVEN GADGET SUPPLY - TRADE TERMS",
        "",
        "TX-9915  Noise-Cancelling Headset .......... RM 1,459.00",
        "",
        "Bulk orders above 50 units carry a 12% trade discount.",
        "Warranty claims are settled within 14 working days.",
        "Payment terms are strictly 30 days from invoice date.",
    ],
]

QUESTIONS = [
    "What does the TX-7742 solar power bank cost in this price list?",
    "And the noise-cancelling headset?",
    "Does this price list say anything at all about free shipping?",
]
WHY = [
    "page 1 -- did it read the file",
    "page 2 -- is the file still there a turn later",
    "nowhere -- does it say so, or make one up",
]


def _escape(line: str) -> bytes:
    encoded = line.encode("cp1252", errors="replace")
    for char in (b"\\", b"(", b")"):
        encoded = encoded.replace(char, b"\\" + char)
    return encoded


def _stream(lines: list[str]) -> bytes:
    ops = []
    y = PAGE_HEIGHT - MARGIN
    for line in lines:
        ops.append(b"BT /F1 12 Tf 1 0 0 1 %g %g Tm (%s) Tj ET" % (MARGIN, y, _escape(line)))
        y -= LEADING
    return b"\n".join(ops)


def drawn_document(pages: list[list[str]]) -> bytes:
    """A PDF whose contents we know, written out by hand for want of a library.

    Same six-object shape `invoice_pdf._document` builds, widened to as many
    pages as it is given -- a one-page file cannot show whether a page number in
    the answer means anything.
    """
    streams = [_stream(lines) for lines in pages]
    first_page_object = 3
    page_ids = [first_page_object + 2 * n for n in range(len(pages))]
    font_id = first_page_object + 2 * len(pages)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % n for n in page_ids), len(pages)),
    ]
    for index, stream in enumerate(streams):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font "
            b"<< /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, font_id, page_ids[index] + 1)
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_at = len(out)
    size = len(objects) + 1
    out += b"xref\n0 %d\n" % size
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    return bytes(out)


def _say(message: dict, tools: list) -> None:
    with patch.object(llm, "get_tools", return_value=tools):
        payloads = dispatch_message(message)
    for payload in payloads:
        print(payload.get("text", {}).get("body", f"<{payload['type']} message>"))
    print()


def main(argv: list[str]) -> int:
    with_tools = "--tools" in argv
    paths = [arg for arg in argv if not arg.startswith("--")]

    if paths:
        content = Path(paths[0]).read_bytes()
        filename = Path(paths[0]).name
        where = paths[0]
        questions = QUESTIONS
        if len(paths) > 1:
            questions = paths[1:]
    else:
        content = drawn_document(PAGES)
        filename = "trade-price-list-2026.pdf"
        where = "a generated two-page price list, contents known"
        questions = QUESTIONS

    print(f"file:   {where}")
    print(f"type:   {filename} ({len(content)} bytes)")
    if not content.startswith(b"%PDF"):
        print("\nThat is not a PDF. The model is handed nothing else in this demo.")
        return 1

    profile = user_store.get_or_create(PHONE)
    profile.bot_id = BOT
    profile.history.clear()
    user_store.save(profile)

    tools = [tool_registry.CATALOGUE[name] for name in READ_ONLY_TOOLS] if with_tools else []
    print(f"bot:    {BOT}, tools {'read-only: ' + ', '.join(READ_ONLY_TOOLS) if tools else 'off'}\n")

    media = whatsapp_media.Media(content=content, mime_type="application/pdf")
    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        for index, question in enumerate(questions):
            reason = WHY[index] if questions is QUESTIONS else "your question"
            print(f"--- {index + 1}. {question}   [{reason}]")
            if index == 0:
                # Only the first turn carries the file; the rest are plain text,
                # which is exactly the thing being tested.
                _say(
                    {
                        "id": f"wamid.probe.{PHONE}.0",
                        "from": PHONE,
                        "type": "document",
                        "document": {
                            "id": "probe-doc-1",
                            "mime_type": "application/pdf",
                            "filename": filename,
                            "caption": question,
                        },
                    },
                    tools,
                )
            else:
                _say(
                    {
                        "id": f"wamid.probe.{PHONE}.{index}",
                        "from": PHONE,
                        "type": "text",
                        "text": {"body": question},
                    },
                    tools,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
