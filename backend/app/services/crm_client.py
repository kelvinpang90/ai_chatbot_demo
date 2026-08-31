from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.services.api_client import JsonApiClient

# The CRM stores whatever the salesperson typed -- "+60 17-394 8123", "017-3948123",
# "60173948123" are all the same person. Comparing the tail sidesteps both the
# punctuation and the country code, and 8 digits is long enough not to collide in a
# book this size.
PHONE_SUFFIX_DIGITS = 8

# Below this a term is a house number or an order quantity, not a phone number.
MIN_PHONE_DIGITS = 7

# crm_os caps a page at 100 server-side regardless of what we ask for.
PAGE_SIZE = 100

# The phone scan pages through contacts, so it needs a stop. 500 is far more than
# the demo book holds, and a miss reads as "not a customer yet" -- which, for the
# lead the next task creates, is the right answer anyway.
MAX_SCAN_PAGES = 5

DEFAULT_RESULT_LIMIT = 5


# Digits plus the punctuation people put between them. A name has none of this.
_PHONE_SHAPED = re.compile(r"^[\d\s+()\-.]+$")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _looks_like_a_phone(term: str) -> bool:
    term = term.strip()
    return bool(_PHONE_SHAPED.match(term)) and len(_digits(term)) >= MIN_PHONE_DIGITS


class CrmClient(JsonApiClient):
    """crm_os over its REST routes."""

    def __init__(self) -> None:
        super().__init__(
            name="crm",
            base_url=settings.crm_base_url,
            email=settings.crm_email,
            password=settings.crm_password,
        )

    def _unwrap(self, payload: Any) -> Any:
        """crm_os wraps every response, tokens included, in `{"success", "data"}`."""
        return payload["data"]

    def _contacts_page(self, *, search: str | None = None, page: int = 1) -> list[dict]:
        # The list route nests again: the envelope's `data` is the page object, whose
        # own `data` is the rows.
        payload = self.get(
            "/api/contacts",
            params={"search": search, "page": page, "page_size": PAGE_SIZE},
        )
        return payload.get("data", [])

    def lookup_contacts(self, term: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Find customers by name, company, or phone number.

        The server's `search` covers name and company only, so a phone number has to
        be matched here. That is why a phone lookup pages instead of querying: the
        WhatsApp number is the one identifier we always have for the person typing,
        and a lookup that silently could not use it would be worse than none.
        """
        if _looks_like_a_phone(term):
            return self._by_phone(term, limit=limit)
        return self._contacts_page(search=term)[:limit]

    def _by_phone(self, term: str, *, limit: int) -> list[dict]:
        wanted = _digits(term)[-PHONE_SUFFIX_DIGITS:]
        matches: list[dict] = []
        for page in range(1, MAX_SCAN_PAGES + 1):
            rows = self._contacts_page(page=page)
            for row in rows:
                if _digits(row.get("phone", "")).endswith(wanted):
                    matches.append(row)
                    if len(matches) >= limit:
                        return matches
            if len(rows) < PAGE_SIZE:
                break
        return matches


_client: CrmClient | None = None


def client() -> CrmClient:
    """One process-wide client, so the cached token is actually shared."""
    global _client
    if _client is None:
        _client = CrmClient()
    return _client


def reset() -> None:
    """Drop the cached client. For tests."""
    global _client
    _client = None
