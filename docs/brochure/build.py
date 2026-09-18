"""Build the customer brochure: QR codes, then one PDF per language.

    pip install qrcode
    python build.py

Needs Google Chrome installed and internet access (fonts come from Google Fonts).
Output: acuven-whatsapp-ai-en.pdf, acuven-whatsapp-ai-zh.pdf next to this file.
"""
import shutil
import subprocess
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

# wa.me links: the demo line opens with "menu" typed in; the contact line is the sales WhatsApp.
QR_CODES = {
    "qr-demo.svg": "https://wa.me/60173948123?text=menu",
    "qr-contact.svg": "https://wa.me/601136182335",
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


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return c
    raise SystemExit("Chrome not found; edit CHROME_CANDIDATES in build.py")


def render(chrome: str, lang: str) -> Path:
    out = HERE / f"acuven-whatsapp-ai-{lang}.pdf"
    url = (HERE / "brochure.html").as_uri() + f"?lang={lang}"
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
    chrome = find_chrome()
    for lang in ("en", "zh"):
        print("wrote", render(chrome, lang))
