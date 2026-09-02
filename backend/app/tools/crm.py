from __future__ import annotations

import json
import logging
import math
from typing import NamedTuple

from anthropic import beta_tool

from app.services import crm_client
from app.services.api_client import ApiClientError
from app.services.phone import is_the_same_number, looks_like_a_phone

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


# A write needs its own vocabulary, as the ERP side found: "could not be checked"
# is the wrong thing to say about a record that may or may not now exist.
LEAD_FAILED = (
    "The lead was NOT saved and nothing was recorded, so there is no card for a "
    "colleague to find and nothing to promise the customer. Try once more. If it "
    "fails again, take the customer's details down in the conversation so someone "
    "can enter them by hand."
)
# The write went out and no answer came back. Saving it again would put two cards
# for one customer on the board the salesperson works from.
LEAD_UNKNOWN = (
    "The CRM stopped responding while the lead was being saved, so it is NOT known "
    "whether it was recorded. Do not save it again -- a colleague will check."
)
BAD_LEAD = (
    "The lead details were not usable. A lead needs the customer name, their "
    "phone number, a short description of what they are asking for, and an "
    "estimated value of zero or more."
)


class _Lead(NamedTuple):
    """A lead in the shape crm_os will take it. `title` is `requirement`, trimmed."""

    name: str
    phone: str
    title: str
    requirement: str
    amount: float


def _usable(name: str, phone: str, requirement: str, amount: float) -> _Lead | None:
    """The lead as the CRM will accept it, or None if it is not worth writing.

    Name and enquiry are trimmed to fit their columns: a shortened name is still
    the same person and a shortened enquiry still reads. A phone number is
    neither -- trimming one stores a different, wrong number in the field a
    salesperson dials -- so an unusable one is refused instead. A lead nobody can
    ring back is not a lead.
    """
    name = str(name or "").strip()
    phone = str(phone or "").strip()
    requirement = str(requirement or "").strip()
    if not name or not requirement:
        return None
    if len(phone) > crm_client.MAX_PHONE_CHARS or not looks_like_a_phone(phone):
        return None
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    # NaN slips past both comparisons below and reaches MySQL as a DECIMAL it
    # rejects, so it is ruled out first. The ceiling is tested against the
    # rounded value because DECIMAL(15, 2) rounds before it range-checks:
    # 9999999999999.998 is inside the limit right up until MySQL makes it 10**13
    # and 500s the write -- which is the one thing this guard exists to prevent.
    if not math.isfinite(amount) or not 0 <= round(amount, 2) < crm_client.MAX_AMOUNT:
        return None
    return _Lead(
        name=name[: crm_client.MAX_NAME_CHARS],
        phone=phone,
        title=requirement[: crm_client.MAX_TITLE_CHARS],
        requirement=requirement,
        amount=amount,
    )


def _auto_created_card(client: crm_client.CrmClient, contact_id: str | None) -> dict | None:
    """The card `POST /api/contacts` just made, found by asking for the deals.

    Failing here does not fail the lead: the contact and its card are already on
    the board, and all that is lost is the note we wanted to hang on it. Letting
    the error out would reach the caller as "nothing was recorded", which by this
    point is false -- and would send the model round again to make a second card.
    """
    if not contact_id:
        return None
    try:
        deals = client.deals_for_contact(contact_id)
    except ApiClientError:
        logger.exception("could not find the card just created for contact %s", contact_id)
        return None
    return deals[0] if deals else None


def _card(client: crm_client.CrmClient, lead: _Lead) -> tuple[dict, dict | None]:
    """The contact this lead belongs to, and the card that now represents it.

    Somebody already on the books gets a new opportunity rather than a second copy
    of themselves. This demo is run against the same phone number again and again,
    and a pipeline showing five identical contacts argues against the product it
    is there to sell.

    The candidates arrive on the loose suffix rule the lookup tools share, and
    are then held to `is_the_same_number`. What is being decided here is where a
    write goes, and the two ways of being wrong do not cost the same: a
    duplicate contact is a visible mess somebody can merge, while a card filed
    onto a stranger who happens to share eight digits is a silent one.
    """
    existing = client.lookup_contacts(lead.phone, limit=crm_client.DEFAULT_RESULT_LIMIT)
    contact = next(
        (row for row in existing if is_the_same_number(row.get("phone", ""), lead.phone)),
        None,
    )
    if contact:
        deal = client.create_deal(
            contact_id=contact.get("id"), title=lead.title, amount=lead.amount
        )
        return contact, deal

    contact = client.create_contact(
        name=lead.name, phone=lead.phone, title=lead.title, amount=lead.amount
    )
    return contact, _auto_created_card(client, contact.get("id"))


def _activity_note(lead: _Lead) -> str:
    """What the salesperson reads inside the card.

    Deliberately the full enquiry rather than the trimmed title: the column is
    TEXT, and this is the one place the customer own words survive whole.
    """
    return (
        f"{lead.requirement} -- estimated MYR {lead.amount:,.2f}, "
        "captured by the WhatsApp assistant."
    )


@beta_tool
def crm_create_lead(name: str, phone: str, requirement: str, amount: float) -> str:
    """Record a sales lead in the CRM so a salesperson can follow it up.

    Call this once the customer has shown real interest -- named what they want,
    asked for a quote, agreed to buy -- and not for a passing question. It writes
    to the live CRM: the lead shows up on the sales pipeline board immediately.

    Somebody already in the CRM gets the new opportunity added to their existing
    record instead of a duplicate entry, so this is safe to call for a returning
    customer.

    Args:
        name: The customer name, as they gave it.
        phone: Their phone number -- normally the WhatsApp number they are
            writing from -- in any format.
        requirement: What they are asking for, in their own words. This becomes
            the title on the pipeline card.
        amount: The estimated value in MYR. Use the quoted total when there is
            one, otherwise a reasonable estimate, or 0 with nothing to go on.
    """
    lead = _usable(name, phone, requirement, amount)
    if lead is None:
        logger.warning("crm_create_lead got unusable details for %r", name)
        return BAD_LEAD

    client = crm_client.client()
    try:
        contact, deal = _card(client, lead)
    except ApiClientError as exc:
        logger.exception("crm_create_lead failed for %r", lead.name)
        # "It failed" and "I do not know" send the model to two different places,
        # and only one of them risks a duplicate card.
        return LEAD_UNKNOWN if exc.may_have_landed else LEAD_FAILED

    deal_id = deal.get("id") if deal else None
    activity_logged = False
    if deal_id:
        try:
            client.log_activity(deal_id=deal_id, content=_activity_note(lead))
            activity_logged = True
        except ApiClientError:
            # The card is on the board; only the note explaining it is missing.
            # Worth reporting, not worth calling the lead a failure.
            logger.exception("could not note the enquiry on deal %s", deal_id)

    return json.dumps(
        {
            "contact_id": contact.get("id"),
            "contact_name": contact.get("name"),
            "deal_id": deal_id,
            "title": deal.get("title") if deal else lead.title,
            "amount": deal.get("amount") if deal else lead.amount,
            "status": deal.get("status") if deal else None,
            "activity_logged": activity_logged,
        },
        ensure_ascii=False,
        default=str,
    )


TOOLS = [crm_lookup_customer, crm_create_lead]
