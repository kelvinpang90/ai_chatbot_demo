"""Send a photo through the WhatsApp path by hand and read what the bot says back.

Task 14 wired inbound images up. The tests prove the plumbing; this proves the
thing the tests cannot -- that Claude actually sees the picture -- without anyone
having to pick up a phone, and it is the fastest way to check that again after
touching `llm._as_messages` or the webhook's image branch.

It goes through `dispatch_message`, not around it, so what runs is the real
branch: the same download seam, the same `llm.Image`, the same content blocks.
The only thing replaced is `fetch_media` -- there is no inbound WhatsApp message
to fetch, and `dispatch_message` returns payloads rather than sending them, so
nothing leaves the machine and no customer is messaged.

Needs ANTHROPIC_API_KEY. Run it wherever that is set -- the VPS container, or
locally in the container image:

    python scripts/image_probe.py                     # a generated image, contents known
    python scripts/image_probe.py ~/earbuds.jpg       # a real photo off your phone
    python scripts/image_probe.py ~/earbuds.jpg --tools

With no file, it draws its own: "SP-1001" over a red square and a green circle.
Nothing in the repo to photograph and no Pillow in the runtime image, so the PNG
is written out by hand -- which has the happy side effect that its contents are
known exactly, and "did the model see it" has a yes-or-no answer.

`--tools` attaches the read-only ERP and CRM tools, which is the path the retail
demo really takes: a bot with tools goes to the beta endpoint rather than
`messages.create`. The write tools are deliberately held back -- a capability
check has no business leaving a junk order or a junk lead in the demo back
offices.

This is not the acceptance criterion. That one is task 17: a real phone, a real
photo, over the deployed webhook.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.whatsapp_webhook import dispatch_message  # noqa: E402
from app.services import llm, whatsapp_media  # noqa: E402
from app.services.user_store import user_store  # noqa: E402
from app.tools import registry as tool_registry  # noqa: E402

# Its own number, so a probe never lands in a real demo conversation's history.
PHONE = "60100000014"
BOT = "retail"
READ_ONLY_TOOLS = ["erp_search_sku", "erp_get_inventory", "erp_list_orders", "crm_lookup_customer"]
CAPTION = "What is in this picture? Describe exactly what you can see."

# What each format announces itself as, so the media type is read off the bytes
# rather than trusted from a filename someone may have renamed.
MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
]

GLYPHS = {
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
}
TEXT = "SP-1001"
SCALE, GAP, MARGIN, SHAPE = 12, 12, 24, 90
WIDTH = len(TEXT) * 5 * SCALE + (len(TEXT) - 1) * GAP + 2 * MARGIN
HEIGHT = 3 * MARGIN + 7 * SCALE + SHAPE


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def drawn_image() -> bytes:
    """A PNG whose contents we know, encoded by hand for want of Pillow."""
    pixels = [[(255, 255, 255)] * WIDTH for _ in range(HEIGHT)]

    x = MARGIN
    for char in TEXT:
        for row, bits in enumerate(GLYPHS[char]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(SCALE):
                        for dx in range(SCALE):
                            pixels[MARGIN + row * SCALE + dy][x + col * SCALE + dx] = (0, 0, 0)
        x += 5 * SCALE + GAP

    top = 2 * MARGIN + 7 * SCALE
    for y in range(top, top + SHAPE):
        for px in range(MARGIN, MARGIN + SHAPE):
            pixels[y][px] = (220, 30, 30)
    radius = SHAPE // 2
    cx, cy = WIDTH - MARGIN - radius, top + radius
    for y in range(top, top + SHAPE):
        for px in range(cx - radius, cx + radius):
            if (px - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                pixels[y][px] = (30, 160, 60)

    raw = b"".join(
        b"\x00" + b"".join(struct.pack("BBB", *px) for px in row) for row in pixels
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def media_type_of(content: bytes) -> str:
    for prefix, mime in MAGIC:
        if content.startswith(prefix):
            return mime
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def main(argv: list[str]) -> int:
    with_tools = "--tools" in argv
    paths = [arg for arg in argv if not arg.startswith("--")]

    if paths:
        content = Path(paths[0]).read_bytes()
        where = paths[0]
    else:
        content = drawn_image()
        where = "a generated image: 'SP-1001' over a red square and a green circle"
    mime_type = media_type_of(content)

    print(f"photo:  {where}")
    print(f"type:   {mime_type} ({len(content)} bytes)")
    if llm.image_media_type(mime_type) is None:
        print("\nThe model cannot read this format. Send a jpeg, png, gif or webp.")
        return 1

    profile = user_store.get_or_create(PHONE)
    profile.bot_id = BOT
    profile.history.clear()
    user_store.save(profile)

    message = {
        "id": f"wamid.probe.{PHONE}",
        "from": PHONE,
        "type": "image",
        "image": {"id": "probe-media-1", "mime_type": mime_type, "caption": CAPTION},
    }
    media = whatsapp_media.Media(content=content, mime_type=mime_type)
    tools = [tool_registry.CATALOGUE[name] for name in READ_ONLY_TOOLS] if with_tools else []
    print(f"bot:    {BOT}, tools {'read-only: ' + ', '.join(READ_ONLY_TOOLS) if tools else 'off'}")
    print(f"asked:  {CAPTION}\n")

    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        # `llm` imported the name, so that binding is the one to replace.
        with patch.object(llm, "get_tools", return_value=tools):
            payloads = dispatch_message(message)

    for payload in payloads:
        print(payload.get("text", {}).get("body", f"<{payload['type']} message>"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
