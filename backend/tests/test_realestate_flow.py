"""The native booking form, both directions (task 24).

Out: a tool puts a Flow on the customer's screen, populated from the listings
that are really on the agency's books. In: the filled form comes back as an
inbound `nfm_reply` hours later and has to become a row in the back office
whether or not the model does anything sensible afterwards.

What none of this can check is Meta's half -- whether the Flow JSON in
docs/whatsapp-flows.md is accepted by Flow Builder, and whether the form renders
on a phone. That is task 26, and the plan says so.
"""
import json
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from app.config import settings
from app.routers.whatsapp_webhook import dispatch_message
from app.services import handover, llm, outbox, whatsapp
from app.services.user_store import user_store
from app.tools import realestate
from app.verticals.db import StoreUnavailable
from app.verticals.realestate import models

FLOW_ID = "1122334455"

LISTINGS = [
    models.Listing(
        listing_id="PROP-202",
        property_type="Condo",
        area="Bangsar South, KL",
        size_sqft=950,
        bedrooms=2,
        price_rm=620000.0,
        status="Available",
    ),
    models.Listing(
        listing_id="PROP-207",
        property_type="Apartment",
        area="Ampang, KL",
        size_sqft=800,
        bedrooms=2,
        price_rm=380000.0,
        status="Under offer",
    ),
]

BOOKED = models.Viewing(
    id=7,
    listing_id="PROP-202",
    customer_name="陈家明",
    phone="60129993001",
    viewing_date="2026-09-21",
    preferred_time="petang",
    created_at="2026-09-13 10:00:00.000",
    area="Bangsar South, KL",
    property_type="Condo",
    price_rm=620000.0,
)


@pytest.fixture
def flow_configured():
    with patch.object(settings, "whatsapp_flow_id", FLOW_ID):
        yield


@pytest.fixture
def on_whatsapp():
    """An open outbox, which is what makes this the WhatsApp line and not the web."""
    outbox.begin()
    yield
    outbox.close()


@pytest.fixture
def listings():
    with patch.object(models, "listings", return_value=list(LISTINGS)):
        yield


def _form_reply(phone: str, fields: dict, seq: int = 1) -> dict:
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "name": "flow",
                "body": "Sent",
                "response_json": json.dumps(fields, ensure_ascii=False),
            },
        },
    }


def _in_the_property_demo(phone: str) -> None:
    profile = user_store.get_or_create(phone)
    profile.bot_id = "realestate"
    user_store.save(profile)


# --- sending the form ---------------------------------------------------------


def test_the_form_carries_the_listings_that_are_actually_for_sale(
    flow_configured, on_whatsapp, listings
):
    """Whatever they pick exists, at the price the listing carries -- which is the
    same property the back office and the bot's own prompt agree on."""
    answer = realestate.offer_viewing_form("3 bedrooms in Bangsar")

    assert answer == realestate.FORM_SENT
    form = outbox.drain("60129993001")[0]
    options = form["interactive"]["action"]["parameters"]["flow_action_payload"]["data"]["listings"]
    assert [option["id"] for option in options] == ["PROP-202"]
    assert "Bangsar South, KL" in options[0]["title"]
    assert "RM 620,000" in options[0]["title"]


def test_a_property_under_offer_is_not_offered_for_viewing(
    flow_configured, on_whatsapp, listings
):
    realestate.offer_viewing_form()

    form = outbox.drain("60129993001")[0]
    options = form["interactive"]["action"]["parameters"]["flow_action_payload"]["data"]["listings"]
    assert "PROP-207" not in [option["id"] for option in options]


def test_without_a_flow_configured_the_bot_is_told_to_ask_in_chat(on_whatsapp, listings):
    """The degrade path the plan asks for, and the state the demo is in until
    somebody publishes a Flow in Meta's console."""
    with patch.object(settings, "whatsapp_flow_id", ""):
        answer = realestate.offer_viewing_form()

    assert answer == realestate.NO_FORM
    assert outbox.drain("60129993001") == []


def test_on_the_web_chat_line_there_is_no_form_either(flow_configured, listings):
    """No outbox open means no channel that can carry one. The bot must not
    promise a form that will never appear."""
    answer = realestate.offer_viewing_form()

    assert answer == realestate.NO_FORM


def test_a_back_office_that_is_down_does_not_produce_an_empty_form(
    flow_configured, on_whatsapp
):
    with patch.object(models, "listings", side_effect=StoreUnavailable("down")):
        answer = realestate.offer_viewing_form()

    assert answer == realestate.BACK_OFFICE_DOWN
    assert outbox.drain("60129993001") == []


def test_the_form_is_sent_as_a_navigate_flow_not_a_data_exchange(
    flow_configured, on_whatsapp, listings
):
    """The decision the whole feature rests on: data_exchange would need a public
    endpoint of ours and a key exchange to keep. See build_flow_message."""
    realestate.offer_viewing_form()

    parameters = outbox.drain("60129993001")[0]["interactive"]["action"]["parameters"]
    assert parameters["flow_action"] == "navigate"
    assert parameters["flow_message_version"] == "3"
    assert parameters["flow_id"] == FLOW_ID
    assert parameters["flow_action_payload"]["screen"] == realestate.SCREEN


def test_a_draft_flow_is_marked_as_one(flow_configured, on_whatsapp, listings):
    """Meta refuses `mode: draft` for a published Flow and refuses to open an
    unpublished one without it, so this cannot be a constant."""
    # Drained inside each block on purpose: an outbox item is built when it is
    # drained, not when it is queued, so the setting is read at that moment.
    with patch.object(settings, "whatsapp_flow_mode", "draft"):
        realestate.offer_viewing_form()
        drafted = outbox.drain("60129993001")[0]

    with patch.object(settings, "whatsapp_flow_mode", "published"):
        realestate.offer_viewing_form()
        published = outbox.drain("60129993001")[0]

    assert drafted["interactive"]["action"]["parameters"]["mode"] == "draft"
    assert "mode" not in published["interactive"]["action"]["parameters"]


def test_the_flow_token_is_not_the_customers_phone_number(
    flow_configured, on_whatsapp, listings
):
    """It travels through Meta's systems and comes back in a webhook payload.
    There is no reason for a number to make that trip twice."""
    realestate.offer_viewing_form()

    token = outbox.drain("60129993001")[0]["interactive"]["action"]["parameters"]["flow_token"]
    assert "60129993001" not in token


# --- the form coming back -----------------------------------------------------


def test_a_submitted_form_becomes_a_booking():
    with patch.object(models, "book_viewing", return_value=7) as written:
        with patch.object(models, "get_viewing", return_value=BOOKED):
            said = realestate.book_from_form(
                {
                    "response_json": json.dumps(
                        {
                            "customer_name": "陈家明",
                            "listing_id": "PROP-202",
                            "viewing_date": "2026-09-21",
                            "preferred_time": "petang",
                        }
                    )
                },
                phone="60129993001",
            )

    request = written.call_args.args[0]
    assert request.customer_name == "陈家明"
    assert request.listing_id == "PROP-202"
    assert request.viewing_date == date(2026, 9, 21)
    assert request.phone == "60129993001"
    assert "#7" in said and "PROP-202" in said


def test_the_date_picker_sends_milliseconds_and_they_are_read_as_the_day_picked():
    """Meta's DatePicker sends epoch milliseconds as a string, measured from UTC
    midnight. Read in local time it lands a day early for half the world.

    Built here rather than written as a constant: a magic 13-digit number is not
    something a reader can check, and getting it wrong is exactly the mistake
    this test exists to catch.
    """
    picked = int(datetime(2026, 9, 21, tzinfo=UTC).timestamp() * 1000)

    assert realestate._as_date(str(picked)) == date(2026, 9, 21)


def test_a_date_typed_rather_than_picked_is_accepted_too():
    """What the degrade path and a hand-written test send."""
    assert realestate._as_date("2026-09-21") == date(2026, 9, 21)
    assert realestate._as_date("21/09/2026") == date(2026, 9, 21)
    assert realestate._as_date("not a date") is None
    assert realestate._as_date("") is None


def test_a_form_missing_a_field_saves_nothing_and_says_so():
    """Never "booked" over a record that does not exist."""
    with patch.object(models, "book_viewing") as written:
        said = realestate.book_from_form(
            {"response_json": json.dumps({"customer_name": "Ali"})}, phone="60129993002"
        )

    assert said == realestate.FORM_UNREADABLE
    written.assert_not_called()


def test_a_response_that_is_not_json_saves_nothing_and_says_so():
    said = realestate.book_from_form({"response_json": "<html>nope</html>"}, phone="6012")

    assert said == realestate.FORM_UNREADABLE


def test_a_back_office_that_is_down_is_told_to_the_customer_not_hidden():
    """The worst thing this demo could do is say a viewing is confirmed over an
    empty back office. The store raises so that this line can exist."""
    with patch.object(models, "book_viewing", side_effect=StoreUnavailable("down")):
        said = realestate.book_from_form(
            {
                "response_json": json.dumps(
                    {
                        "customer_name": "Ali",
                        "listing_id": "PROP-202",
                        "viewing_date": "2026-09-21",
                    }
                )
            },
            phone="60129993003",
        )

    assert said == realestate.FORM_NOT_SAVED
    assert "booked" not in said.lower().split("never")[0]


# --- through the webhook ------------------------------------------------------


def test_a_form_submitted_on_a_phone_reaches_the_model_as_a_booking_made():
    """The acceptance for this task's code half: an nfm_reply must not sit there
    as an interactive message nobody handles."""
    phone = "60129993010"
    _in_the_property_demo(phone)
    seen = {}

    def capture(bot, customer, history, image=None, document=None):
        seen["said"] = history[-1].content
        return "Noted, our agent will call you."

    with patch.object(models, "book_viewing", return_value=7):
        with patch.object(models, "get_viewing", return_value=BOOKED):
            with patch.object(llm, "get_reply", side_effect=capture):
                sent = dispatch_message(
                    _form_reply(
                        phone,
                        {
                            "customer_name": "陈家明",
                            "listing_id": "PROP-202",
                            "viewing_date": "2026-09-21",
                        },
                    )
                )

    assert "#7" in seen["said"]
    assert [message["type"] for message in sent] == ["text"]
    assert [m.role for m in user_store.get(phone).history] == ["user", "assistant"]


def test_a_form_submitted_while_a_person_has_the_conversation_is_still_filed():
    """Both halves matter: the booking is the customer's, so it is saved; the
    bot stays silent, because a colleague is typing."""
    phone = "60129993011"
    _in_the_property_demo(phone)
    profile = user_store.get_or_create(phone)
    handover.begin(profile, reason="wants a discount")
    user_store.save(profile)

    with patch.object(models, "book_viewing", return_value=7) as written:
        with patch.object(models, "get_viewing", return_value=BOOKED):
            sent = dispatch_message(
                _form_reply(
                    phone,
                    {
                        "customer_name": "Ali",
                        "listing_id": "PROP-202",
                        "viewing_date": "2026-09-21",
                    },
                )
            )

    assert sent == []
    written.assert_called_once()


def test_the_form_message_stays_inside_metas_limits(flow_configured, on_whatsapp, listings):
    """Same reasoning as every other builder in whatsapp.py: over a cap is a 400
    that takes the whole message, so the customer gets nothing."""
    realestate.offer_viewing_form()
    parameters = outbox.drain("60129993001")[0]["interactive"]["action"]["parameters"]

    assert len(parameters["flow_cta"]) <= whatsapp.MAX_BUTTON_TITLE_CHARS
