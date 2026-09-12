"""The one tool that asks a question with a form instead of a sentence (task 24).

Every other tool in here answers the customer. This one interrupts them: it puts
a native WhatsApp form on their screen, and the conversation pauses until they
fill it in -- which may be in ten seconds or after lunch, because the reply comes
back as an ordinary inbound message whenever they get round to it.

**The form is a nicety, not the mechanism.** A Flow has to be built and published
in Meta's console, and until it is (or if Meta refuses it on the day) there is no
`WHATSAPP_FLOW_ID`, and there is none at all on the web chat line. So the tool
answers the model differently rather than failing: without a form it says to ask
for the three details in chat, and the booking still gets made by the same code
on the way back in. The plan calls this the degrade path; it is built in rather
than kept in reserve, because the version nobody exercises is the version that
does not work.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

from anthropic import beta_tool

from app.config import settings
from app.services import audit, outbox
from app.verticals import StoreUnavailable
from app.verticals.realestate import models

logger = logging.getLogger(__name__)

# The screen id inside the Flow JSON. Changing it here without changing it in
# docs/whatsapp-flows.md gets a Flow that opens on nothing.
SCREEN = "BOOK_VIEWING"

# What the button under the message says. Meta caps this; `build_flow_message`
# clips rather than letting the whole message 400.
CTA = "Book a viewing"

# Meta's Dropdown takes at most this many options on one screen.
MAX_FORM_LISTINGS = 20

FORM_SENT = (
    "The booking form is now on the customer's screen. Tell them in one short "
    "sentence that the form is there and to fill it in -- name, date and which "
    "property. Do not ask them for those details yourself, do not repeat them "
    "back, and do not say the viewing is booked: nothing is booked until they "
    "submit it, which may be a while. Then stop and wait."
)

NO_FORM = (
    "There is no form available on this channel, so ask for the details in the "
    "conversation instead: their name, which property, and which date suits "
    "them. Ask for all three in one short message rather than one at a time. "
    "When they answer, say their agent will confirm the viewing."
)

BACK_OFFICE_DOWN = (
    "The property list could not be read just now, so the form cannot be built. "
    "Do not offer a form and do not invent a property. Say plainly that you "
    "cannot pull the listings up at the moment and offer to have an agent call "
    "them back."
)


@beta_tool
def offer_viewing_form(conversation_note: str = "") -> str:
    """Put a booking form on the customer's screen so they can arrange a viewing.

    Call this as soon as a customer says they want to see a property -- a
    particular one, or any of the ones you have shown them. Do not collect their
    name or a date first: the form asks for those, and asking twice is how a
    demo starts to look like a questionnaire.

    The form lists the properties that are actually on the agency's books, so it
    is also the honest way to let them choose: whatever they pick exists, at the
    price the listing carries.

    Do not call this to confirm a viewing that has already been booked, and do
    not call it twice in a row -- the form is already on their screen and a
    second one on top of it is confusing.

    Args:
        conversation_note: What the customer said they were after, in one line,
            in their own words -- "3 bedrooms in Puchong under 600k". It is not
            shown to them; it goes in the log next to the form so the agent
            reading the booking afterwards knows what the enquiry was about.
    """
    try:
        listings = [row for row in models.listings() if row.status == "Available"]
    except StoreUnavailable:
        logger.warning("offer_viewing_form could not read the listings")
        return BACK_OFFICE_DOWN

    if not listings:
        # The table is there and empty, which is a different thing from the
        # database being down and is not supposed to happen -- the eight are
        # seeded on first use. Say so rather than send a form with no options.
        logger.warning("offer_viewing_form found no available listings")
        return BACK_OFFICE_DOWN

    if not settings.whatsapp_flow_id or not outbox.available():
        logger.info(
            "no viewing form to send (flow_id=%s, outbox=%s)",
            bool(settings.whatsapp_flow_id),
            outbox.available(),
        )
        return NO_FORM

    sent = outbox.add(
        outbox.FlowForm(
            body="Pick a property and a date that suits you.",
            flow_id=settings.whatsapp_flow_id,
            flow_token=_flow_token(),
            cta=CTA,
            screen=SCREEN,
            data={"listings": [_option(row) for row in listings[:MAX_FORM_LISTINGS]]},
        )
    )
    if not sent:
        return NO_FORM
    logger.info("viewing form queued: %s", str(conversation_note or "").strip()[:200])
    return FORM_SENT


def _option(listing: models.Listing) -> dict:
    """One row of the form's property dropdown.

    Meta's Dropdown wants `id` and `title` and nothing else, so the price and the
    area go into the title -- the customer is choosing between properties, and
    "PROP-202" on its own is not a choice anybody can make.
    """
    price = f"RM {round(listing.price_rm):,}"
    return {
        "id": listing.listing_id,
        "title": f"{listing.area} · {listing.bedrooms}BR · {price}",
    }


def _flow_token() -> str:
    """What Meta echoes back with the filled form, tying it to this conversation.

    The conversation id, which is already the key the transcript is filed under
    -- so a booking can be lined up against what was said before it. Never the
    phone number: this string travels through Meta's systems and comes back in a
    webhook payload, and there is no reason for a customer's number to make that
    trip twice.
    """
    turn = audit.current()
    return turn.conversation_id if turn else "viewing"


TOOLS = [offer_viewing_form]


# -- the way back in -----------------------------------------------------------
#
# A filled form does not return to the tool that sent it. It arrives hours later
# as an inbound `nfm_reply` on the webhook, and everything below is what the
# router does with it. It lives here rather than in the router because the shape
# of the payload is decided by the Flow JSON in docs/whatsapp-flows.md, and one
# module should own both ends of that agreement.

# Field names as the Flow's Form declares them. Changing one means changing it in
# docs/whatsapp-flows.md too, and a mismatch is silent -- the field simply
# arrives empty.
FIELD_NAME = "customer_name"
FIELD_LISTING = "listing_id"
FIELD_DATE = "viewing_date"
FIELD_TIME = "preferred_time"

FORM_UNREADABLE = (
    "The customer submitted the booking form but it could not be read, so "
    "nothing has been saved. Apologise in one line, ask them for their name, "
    "the property and the date in the chat instead, and do not pretend the "
    "booking exists."
)
FORM_NOT_SAVED = (
    "The customer submitted the booking form and it could NOT be saved -- the "
    "property back office is unreachable. Tell them plainly that it did not go "
    "through and that you will have an agent call them back. Never tell them "
    "the viewing is booked."
)


def book_from_form(payload: dict, phone: str) -> str:
    """File the viewing a customer just submitted, and say what to tell them.

    Returns the line the model reads next, always. The booking is written here
    rather than by a tool the model may or may not call, because by this point
    the customer has already tapped submit: the record has to exist whether or
    not the model does anything sensible with the sentence below.
    """
    fields = _submitted_fields(payload)
    name = str(fields.get(FIELD_NAME) or "").strip()
    listing_id = str(fields.get(FIELD_LISTING) or "").strip()
    viewing_date = _as_date(fields.get(FIELD_DATE))
    if not name or not listing_id or viewing_date is None:
        logger.warning("unreadable viewing form: fields=%s", sorted(fields))
        return FORM_UNREADABLE

    try:
        request = models.ViewingRequest(
            listing_id=listing_id,
            customer_name=name[:128],
            viewing_date=viewing_date,
            phone=phone[:32],
            preferred_time=str(fields.get(FIELD_TIME) or "").strip()[:32],
        )
        booked = models.get_viewing(models.book_viewing(request))
    except StoreUnavailable:
        logger.exception("a submitted viewing form could not be saved")
        return FORM_NOT_SAVED
    except ValueError:
        # Pydantic refused what the form sent -- a name past the column, a
        # listing id that is not one. The customer is owed the truth, not a
        # traceback.
        logger.exception("a submitted viewing form failed validation")
        return FORM_UNREADABLE

    if booked is None:
        return FORM_NOT_SAVED
    return _confirmation(booked)


def _confirmation(booked: models.Viewing) -> str:
    where = " · ".join(part for part in (booked.property_type, booked.area) if part)
    price = f"RM {round(booked.price_rm):,}" if booked.price_rm is not None else "price unknown"
    when = booked.viewing_date + (f" ({booked.preferred_time})" if booked.preferred_time else "")
    return (
        f"The customer filled in the booking form and it IS ALREADY SAVED in the "
        f"property back office as viewing #{booked.id}: {booked.customer_name}, "
        f"{booked.listing_id} ({where}, {price}), on {when}. "
        "Do not book it again and do not ask them to confirm the details. "
        "Reply in one short message: say the request is in and their agent will "
        "call to confirm the time. Then record the enquiry with crm_create_lead "
        "using their name, this phone number, the property and date as the "
        "requirement, and the listing price as the amount."
    )


def _submitted_fields(payload: dict) -> dict:
    """The answers out of an `nfm_reply`.

    Meta puts them in `response_json`, as a JSON *string* rather than an object.
    A dict is accepted too: it costs one line and saves the next person wondering
    why the payload they pasted into a test does not work.
    """
    raw = payload.get("response_json")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("nfm_reply response_json is not JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_date(value) -> date | None:
    """The picked date, whichever way the Flow spells it.

    Meta's DatePicker sends milliseconds since the epoch, as a string -- read at
    UTC, which is where that midnight was measured from; reading it in local time
    would land the day before for anyone west of Greenwich. The other two forms
    are what a text field or a hand-written test sends, and accepting them is
    what lets the degrade path and the tests share this one function.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    logger.warning("a viewing form sent a date in no format this understands")
    return None
