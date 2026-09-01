from __future__ import annotations

from typing import Any

from app.config import settings
from app.services import phone
from app.services.api_client import JsonApiClient

# The phone-matching rules moved to app.services.phone when the ERP side needed
# the same ones: "which digits count" must not drift apart between two systems
# that answer questions about the same person.
PAGE_SIZE = phone.PAGE_SIZE
MAX_SCAN_PAGES = phone.MAX_SCAN_PAGES

DEFAULT_RESULT_LIMIT = 5


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
        if phone.looks_like_a_phone(term):
            return self._by_phone(term, limit=limit)
        return self._contacts_page(search=term)[:limit]

    def _by_phone(self, term: str, *, limit: int) -> list[dict]:
        matches: list[dict] = []
        for page in range(1, MAX_SCAN_PAGES + 1):
            rows = self._contacts_page(page=page)
            for row in rows:
                if phone.matches(row.get("phone", ""), term):
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
