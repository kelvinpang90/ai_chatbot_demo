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

# crm_os column limits, enforced here because MySQL in strict mode answers an
# overflow with an error: a title one character too long is not a truncated card,
# it is a 500 and a lead the salesperson never sees.
MAX_TITLE_CHARS = 200
MAX_NAME_CHARS = 100
MAX_PHONE_CHARS = 30

# `deals.amount` is DECIMAL(15, 2), so this is the first value it cannot hold.
MAX_AMOUNT = 10**13


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

    # -- writes --------------------------------------------------------------

    def create_contact(self, *, name: str, phone: str, title: str, amount: float) -> dict:
        """A new person on the books, plus the lead card crm_os makes alongside them.

        `POST /api/contacts` always auto-creates one Deal out of the `initial_*`
        fields (`services/contact_service.py`), so the enquiry goes in here rather
        than in a second call: posting to `/api/deals` afterwards would leave an
        empty RM 0 card sitting next to the real one, on the very board the demo
        is pointing at.

        Nothing sets `is_gateway` -- the route does not accept it and the column
        defaults to false. That is the point: `utils/demo_scope.py` filters
        flagged contacts out of the pipeline, which would hide the card.
        """
        return self.post(
            "/api/contacts",
            json={
                "name": name,
                "phone": phone,
                "initial_status": "lead",
                "initial_title": title,
                "initial_amount": amount,
            },
        )

    def create_deal(self, *, contact_id: str, title: str, amount: float) -> dict:
        """A new opportunity against somebody already on the books."""
        return self.post(
            "/api/deals",
            json={
                "contact_id": contact_id,
                "status": "lead",
                "title": title,
                "amount": amount,
            },
        )

    def deals_for_contact(self, contact_id: str) -> list[dict]:
        """The contact's deals, newest first.

        This is how the auto-created card is found: `POST /api/contacts` answers
        with the contact alone, so the id of the deal it just made is only
        available by asking for it.
        """
        return self.get("/api/deals", params={"contact_id": contact_id})

    def log_activity(
        self, *, deal_id: str, content: str, activity_type: str = "WhatsApp"
    ) -> dict:
        """Note what was said against the deal, so the card says where it came from.

        The body repeats `deal_id` because `ActivityCreate` requires the field even
        though the route reads it from the path; leaving it out is a 422.
        """
        return self.post(
            f"/api/deals/{deal_id}/activities",
            json={"deal_id": deal_id, "type": activity_type, "content": content},
        )


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
