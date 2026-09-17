"""Which of the demo's three languages a customer writes in (task 38.1).

The model already answers in whatever language it is written to. This is for the
lines it never sees: the handover sentence, the apology when a voice note will
not transcribe, the push half a minute after an order. Those went out in all
three languages at once, and a customer who wrote "找人工客服" got a Chinese
sentence with an English and a Malay one hanging off it.

So each such line is written three times over, and the one sent is picked by the
language this customer last wrote in -- remembered on their record, because the
apology for an unreadable voice note has no words of theirs to read. Where we
have never seen them write a thing, all three still go: a guess in the wrong
language is worse than the long line.

Chinese is certain: a Han character means Chinese, and that includes Malaysian
code-mixing like "我要买两个 fan, hantar ke Johor", which the model also answers in
Chinese. Malay against English is not certain and is not pretended to be: a
short list of words English does not use. "ok" and "hi" decide nothing, so they
cannot knock a Chinese customer's record over to English.
"""
from __future__ import annotations

import re
from typing import NamedTuple

ZH, EN, MS = "zh", "en", "ms"

_HAN = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z]+")

# Common enough that almost any Malay sentence carries one, and not English
# words. Chosen for what a customer types to a shop, not for coverage of the
# language: a miss falls through to English, which is the smaller mistake.
MALAY_WORDS = frozenset(
    {
        "saya", "aku", "awak", "anda", "kami", "kita", "dia", "mereka",
        "nak", "mahu", "hendak", "boleh", "tak", "tidak", "bukan", "belum",
        "sudah", "dah", "ada", "ini", "itu", "yang", "dengan", "untuk", "dan",
        "atau", "tapi", "kalau", "juga", "lagi", "sahaja", "saja", "je",
        "lah", "kan", "pun", "ke", "kat", "dekat", "dari", "pada", "di",
        "apa", "mana", "bila", "berapa", "kenapa", "bagaimana", "macam",
        "tolong", "sila", "terima", "kasih", "maaf", "selamat", "pagi",
        "petang", "malam", "esok", "semalam", "hari", "harga", "beli",
        "bayar", "hantar", "barang", "pesanan", "nombor", "alamat",
        "cakap", "orang", "manusia", "encik", "cik", "puan", "tuan", "baik",
    }
)


def detect(said: str) -> str | None:
    """The language of the customer's own words, or None if they do not say.

    Pass only what the customer wrote or spoke: a filename or one of our own
    markers ("[photo]") is not theirs and would read as English.
    """
    if not said:
        return None
    if _HAN.search(said):
        return ZH
    words = [word.lower() for word in _WORD.findall(said)]
    if any(word in MALAY_WORDS for word in words):
        return MS
    if len(words) >= 2:
        return EN
    return None


def remember(profile, said: str) -> None:
    """File the language of `said` on the customer's record, if it has one."""
    found = detect(said)
    if found:
        profile.language = found


class Localized(NamedTuple):
    """One line the model does not write, in each of the three languages."""

    zh: str
    en: str
    ms: str

    def pick(self, language: str | None) -> str:
        """The line in `language`, or all three when we do not know theirs."""
        if language in (ZH, EN, MS):
            return getattr(self, language)
        return " / ".join(self)

    def format(self, **values) -> Localized:
        return Localized(*(line.format(**values) for line in self))
