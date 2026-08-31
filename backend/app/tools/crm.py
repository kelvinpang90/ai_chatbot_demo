from __future__ import annotations

import json
import logging

from anthropic import beta_tool

from app.services import crm_client
from app.services.api_client import ApiClientError

logger = logging.getLogger(__name__)

UNAVAILABLE = "The CRM system could not be reached, so this could not be checked."
NOT_FOUND = "No matching customer found in the CRM."


@beta_tool
def crm_lookup_customer(name_or_phone: str) -> str:
    """Look up an existing customer in the CRM by name, company, or phone number.

    Use this to find out whether the person you are talking to is already a customer
    and what business they have done before. A phone number may be written in any
    format. If nothing comes back, treat them as a new customer -- do not guess.

    Args:
        name_or_phone: A customer or company name, or a phone number in any format.
    """
    try:
        contacts = crm_client.client().lookup_contacts(name_or_phone)
    except ApiClientError:
        logger.exception("crm_lookup_customer failed for %r", name_or_phone)
        return UNAVAILABLE

    if not contacts:
        return NOT_FOUND

    return json.dumps(
        [
            {
                "contact_id": contact.get("id"),
                "name": contact.get("name"),
                "company": contact.get("company"),
                "phone": contact.get("phone"),
                "email": contact.get("email"),
                "total_deal_amount": contact.get("total_deal_amount"),
                "deal_count": contact.get("deal_count"),
            }
            for contact in contacts
        ],
        ensure_ascii=False,
        default=str,
    )


TOOLS = [crm_lookup_customer]
