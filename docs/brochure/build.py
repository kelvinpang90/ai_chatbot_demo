"""Build the customer brochure and the company profile: QR codes, then one PDF per language.

    pip install qrcode pillow numpy
    python build.py

Needs Google Chrome installed and internet access (fonts come from Google Fonts).
Output next to this file: acuven-whatsapp-ai-{en,zh}.pdf (brochure.html) and
acuven-company-profile-{en,zh}.pdf (company.html).
"""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import qrcode
import qrcode.image.svg
from PIL import Image

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SHOTS = HERE / "shots"

# wa.me links: the demo line opens with "menu" typed in; the contact line is the sales WhatsApp.
QR_CODES = {
    "qr-demo.svg": "https://wa.me/60173948123?text=menu",
    "qr-contact.svg": "https://wa.me/601136182335",
}

# Source page -> PDF name stem.
DOCUMENTS = {
    "brochure.html": "acuven-whatsapp-ai",
    "company.html": "acuven-company-profile",
}

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "google-chrome",
    "chromium",
]


def make_qr_codes() -> None:
    ASSETS.mkdir(exist_ok=True)
    for name, url in QR_CODES.items():
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=1)
        img.save(ASSETS / name)


def crop_chat_shots() -> None:
    """Trim the empty wallpaper either side of a WhatsApp Desktop chat.

    A wide desktop window leaves the bubbles in the middle half, which prints
    tiny. Keep only the columns that white (incoming) or green (outgoing)
    bubbles reach, plus a margin. Back office shots (bo-*) are left alone.
    """
    out_dir = SHOTS / "_cropped"
    out_dir.mkdir(exist_ok=True)
    for src in SHOTS.iterdir():
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg") or src.name.startswith("bo-"):
            continue
        im = Image.open(src).convert("RGB")
        px = np.asarray(im).astype(int)
        body = px[int(px.shape[0] * 0.06):]  # skip the chat header bar, also white
        r, g, b = body[..., 0], body[..., 1], body[..., 2]
        white = (r > 250) & (g > 250) & (b > 250)
        green = (abs(r - 217) < 12) & (abs(g - 253) < 8) & (abs(b - 211) < 12)
        cols = np.flatnonzero(((white | green).sum(axis=0)) > 20)
        if cols.size:
            pad = 24
            left, right = max(cols[0] - pad, 0), min(cols[-1] + pad, px.shape[1])
            im = im.crop((left, 0, right, px.shape[0]))
        im.save(out_dir / src.name, quality=92)


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return c
    raise SystemExit("Chrome not found; edit CHROME_CANDIDATES in build.py")


def render(chrome: str, page: str, stem: str, lang: str) -> Path:
    out = HERE / f"{stem}-{lang}.pdf"
    url = (HERE / page).as_uri() + f"?lang={lang}"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--allow-file-access-from-files",
            # Gives the web fonts and screenshots time to load before printing.
            "--virtual-time-budget=20000",
            f"--print-to-pdf={out}",
            url,
        ],
        check=True,
        capture_output=True,
    )
    return out


if __name__ == "__main__":
    make_qr_codes()
    crop_chat_shots()
    chrome = find_chrome()
    for page, stem in DOCUMENTS.items():
        for lang in ("en", "zh"):
            print("wrote", render(chrome, page, stem, lang))
