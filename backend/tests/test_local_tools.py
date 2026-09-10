"""The hotel and SaaS tools: the bots whose back office is their own JSON.

Two things are worth holding on to here. One is that nothing the guest is told
is arithmetic the model did -- the rate, the nights and the total all come off
the catalogue, because a bot with no booking system behind it is exactly the one
that could quietly agree to a price nobody can honour. The other is where a
write lands: in the profile object the router is about to save, not in a copy of
it.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

from app.bots.registry import get_bot
from app.console import events
from app.services import llm
from app.services.user_store import UserProfile
from app.tools import local

HOTEL = get_bot("hotel")
SAAS = get_bot("saas")

# Far enough out that a stay booked in a test is never in the past, whatever day
# the suite happens to run on.
SOON = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=33)).isoformat()


def _guest(**fields) -> UserProfile:
    fields.setdefault("phone", "60173948123")
    return UserProfile(key_id=fields["phone"], **fields)


def _booking(profile: UserProfile) -> dict:
    """One confirmed three-night stay, made the way the model would make it."""
    with local.serving(HOTEL, profile):
        return json.loads(local.hotel_create_booking("Sea View Suite", SOON, LATER, 2))


# --------------------------------------------------------------------------- #
# Hotel: the catalogue
# --------------------------------------------------------------------------- #


def test_room_search_returns_the_resort_catalogue():
    with local.serving(HOTEL, _guest()):
        rooms = json.loads(local.hotel_search_rooms())
    assert {room["room_type"] for room in rooms} == {
        room["room_type"] for room in HOTEL.context_data["room_types"]
    }


def test_room_search_narrows_by_property_party_size_and_budget():
    with local.serving(HOTEL, _guest()):
        penang = json.loads(local.hotel_search_rooms(location="Penang"))
        family = json.loads(local.hotel_search_rooms(guests=5))
        cheap = json.loads(local.hotel_search_rooms(max_price_rm=250))

    assert {room["location"] for room in penang} == {"Penang"}
    # Only the Family Suite sleeps five; a room that cannot hold the party is
    # not an option to offer them.
    assert [room["room_type"] for room in family] == ["Family Suite"]
    assert all(room["price_per_night_rm"] <= 250 for room in cheap)


def test_a_search_that_matches_nothing_says_so_rather_than_offering_a_room():
    with local.serving(HOTEL, _guest()):
        assert local.hotel_search_rooms(location="Ipoh") == local.NO_ROOMS


# --------------------------------------------------------------------------- #
# Hotel: booking
# --------------------------------------------------------------------------- #


def test_a_booking_is_priced_off_the_catalogue_rather_than_by_the_model():
    booking = _booking(_guest())
    assert booking["nights"] == 3
    assert booking["rate_per_night_rm"] == 580
    assert booking["total_rm"] == 1740
    assert booking["location"] == "Langkawi"
    assert booking["status"] == "Confirmed"
    assert booking["booking_id"].startswith("BK-")


def test_a_room_the_resort_does_not_have_is_refused_with_the_ones_it_does():
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Presidential Suite", SOON, LATER, 2)
    assert "Presidential Suite" in answer
    assert "Sea View Suite" in answer  # what it may offer instead
    assert "BK-" not in answer


def test_a_party_bigger_than_the_room_is_refused():
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Standard Twin Room", SOON, LATER, 4)
    assert "sleeps 2" in answer
    assert "BK-" not in answer


def test_a_date_the_tool_cannot_read_comes_back_with_today_attached():
    """The model has no idea what day it is, so the refusal has to say."""
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Sea View Suite", "next weekend", LATER, 2)
    assert date.today().isoformat() in answer
    assert "BK-" not in answer


def test_a_stay_that_ends_before_it_starts_is_refused():
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Sea View Suite", LATER, SOON, 2)
    assert "after the check-in date" in answer


def test_a_check_in_that_has_already_passed_is_refused():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Sea View Suite", yesterday, tomorrow, 2)
    assert "already passed" in answer
    assert date.today().isoformat() in answer


def test_a_stay_longer_than_the_ceiling_is_refused():
    far = (date.today() + timedelta(days=30 + local.MAX_NIGHTS + 1)).isoformat()
    with local.serving(HOTEL, _guest()):
        answer = local.hotel_create_booking("Sea View Suite", SOON, far, 2)
    assert str(local.MAX_NIGHTS) in answer
    assert "BK-" not in answer


# --------------------------------------------------------------------------- #
# Hotel: reading it back and changing it
# --------------------------------------------------------------------------- #


def test_a_booking_made_this_turn_is_found_again_in_the_same_turn():
    profile = _guest()
    booking = _booking(profile)
    with local.serving(HOTEL, profile):
        found = json.loads(local.hotel_get_booking())
        by_number = json.loads(local.hotel_get_booking(booking["booking_id"]))
    assert [row["booking_id"] for row in found] == [booking["booking_id"]]
    assert by_number == found


def test_a_guest_with_nothing_on_file_is_told_so_rather_than_given_a_booking():
    with local.serving(HOTEL, _guest()):
        assert local.hotel_get_booking() == local.NO_BOOKING
        assert local.hotel_get_booking("BK-9999") == local.NO_BOOKING


def test_shortening_a_stay_really_does_lower_the_total():
    profile = _guest()
    booking = _booking(profile)
    shorter = (date.today() + timedelta(days=32)).isoformat()

    with local.serving(HOTEL, profile):
        changed = json.loads(local.hotel_modify_booking(booking["booking_id"], check_out=shorter))
        on_file = json.loads(local.hotel_get_booking())

    assert changed["nights"] == 2
    assert changed["total_rm"] == 1160
    assert changed["booking_id"] == booking["booking_id"]
    # And the change is the record, not a second copy of it.
    assert [row["total_rm"] for row in on_file] == [1160]


def test_changing_the_room_reprices_the_stay_at_the_new_rate():
    profile = _guest()
    booking = _booking(profile)
    with local.serving(HOTEL, profile):
        changed = json.loads(
            local.hotel_modify_booking(booking["booking_id"], room_type="Beachfront Villa")
        )
    assert changed["rate_per_night_rm"] == 950
    assert changed["total_rm"] == 2850


def test_a_guest_already_staying_can_still_add_a_night():
    """The rule is that nobody is checked in to a date that has gone, not that a
    guest standing at the desk cannot extend. Refusing here would be the bot
    telling someone in the room that their own stay is in the past."""
    profile = _guest()
    with local.serving(HOTEL, profile):
        booking = json.loads(
            local.hotel_create_booking(
                "Sea View Suite",
                date.today().isoformat(),
                (date.today() + timedelta(days=2)).isoformat(),
                2,
            )
        )
    # A day passes: the stay is now under way.
    profile.profile["hotel"]["bookings"][0]["check_in"] = (
        date.today() - timedelta(days=1)
    ).isoformat()

    with local.serving(HOTEL, profile):
        extended = json.loads(
            local.hotel_modify_booking(
                booking["booking_id"], check_out=(date.today() + timedelta(days=3)).isoformat()
            )
        )
    assert extended["nights"] == 4
    assert extended["total_rm"] == 2320


def test_a_change_cannot_move_a_check_in_into_the_past():
    profile = _guest()
    booking = _booking(profile)
    with local.serving(HOTEL, profile):
        answer = local.hotel_modify_booking(
            booking["booking_id"], check_in=(date.today() - timedelta(days=1)).isoformat()
        )
    assert "already passed" in answer


def test_changing_a_booking_nobody_has_is_refused():
    with local.serving(HOTEL, _guest()):
        assert local.hotel_modify_booking("BK-9999", guests=3) == local.NO_BOOKING


def test_a_change_the_room_cannot_take_leaves_the_booking_as_it_was():
    profile = _guest()
    booking = _booking(profile)
    with local.serving(HOTEL, profile):
        answer = local.hotel_modify_booking(booking["booking_id"], guests=9)
        on_file = json.loads(local.hotel_get_booking())
    assert "sleeps 3" in answer
    assert on_file[0]["guests"] == 2
    assert on_file[0]["total_rm"] == 1740


# --------------------------------------------------------------------------- #
# SaaS support
# --------------------------------------------------------------------------- #


def test_the_known_issue_search_finds_the_issue_the_customer_described():
    with local.serving(SAAS, _guest()):
        matches = json.loads(local.saas_search_known_issues("I can't log in, invalid credentials"))
    assert "log in" in matches[0]["issue"]
    assert len(matches) <= local.MAX_ISSUE_RESULTS


def test_a_problem_outside_the_list_gets_no_invented_fix():
    with local.serving(SAAS, _guest()):
        assert local.saas_search_known_issues("printing gantt charts to A3") == (
            local.NO_KNOWN_ISSUE
        )


def test_a_question_of_nothing_but_filler_words_matches_nothing():
    """Without the stopwords, "how can you help" would match every issue there is."""
    with local.serving(SAAS, _guest()):
        assert local.saas_search_known_issues("how can you help") == local.NO_KNOWN_ISSUE


def test_a_ticket_opened_is_found_again_in_the_same_conversation():
    profile = _guest()
    with local.serving(SAAS, profile):
        opened = json.loads(
            local.saas_create_ticket("Export to CSV fails", "Clicking export does nothing.", "high")
        )
        found = json.loads(local.saas_get_tickets())
        by_number = json.loads(local.saas_get_tickets(opened["ticket_id"]))

    assert opened["ticket_id"].startswith("TCK-")
    assert opened["status"] == "open"
    assert opened["priority"] == "high"
    assert [row["ticket_id"] for row in found] == [opened["ticket_id"]]
    assert by_number == [opened]


def test_a_customer_with_no_tickets_is_told_so_rather_than_given_a_number():
    with local.serving(SAAS, _guest()):
        assert local.saas_get_tickets() == local.NO_TICKET


def test_a_ticket_needs_a_subject_and_what_actually_happened():
    with local.serving(SAAS, _guest()):
        assert "subject" in local.saas_create_ticket("", "nothing works")
        assert "subject" in local.saas_create_ticket("Cannot log in", "  ")


def test_an_unknown_priority_is_refused_rather_than_quietly_downgraded():
    profile = _guest()
    with local.serving(SAAS, profile):
        answer = local.saas_create_ticket("Site down", "Nobody can log in.", "P0")
    assert "low, normal, high, urgent" in answer
    assert profile.profile.get("saas", {}).get("tickets") is None


def test_a_long_description_is_kept_within_the_record_it_lives_in():
    profile = _guest()
    with local.serving(SAAS, profile):
        ticket = json.loads(
            local.saas_create_ticket("Long one", "x" * (local.MAX_DESCRIPTION_CHARS + 500))
        )
    assert len(ticket["description"]) == local.MAX_DESCRIPTION_CHARS


# --------------------------------------------------------------------------- #
# Where the writes land
# --------------------------------------------------------------------------- #


def test_a_write_lands_on_the_profile_the_router_is_about_to_save():
    """The whole mechanism: the tool mutates the caller's object, not a copy.

    A tool that saved a profile of its own would have its work overwritten a
    moment later by the router saving the one it has been holding all along.
    """
    profile = _guest()
    booking = _booking(profile)
    assert profile.profile["hotel"]["bookings"][0]["booking_id"] == booking["booking_id"]


def test_a_slot_that_came_back_unusable_is_started_over_rather_than_raised():
    """The profile is free-form and read back off Redis; a customer mid-sentence
    is the wrong moment to discover that something else once wrote there."""
    profile = _guest()
    profile.profile["hotel"] = "written by something that is not this"
    booking = _booking(profile)
    assert profile.profile["hotel"]["bookings"][0]["booking_id"] == booking["booking_id"]


def test_one_bot_does_not_write_into_another_bot_slot():
    profile = _guest()
    _booking(profile)
    with local.serving(SAAS, profile):
        local.saas_create_ticket("Slow dashboard", "Takes a minute to load.")
    assert set(profile.profile) == {"hotel", "saas"}
    assert "tickets" not in profile.profile["hotel"]
    assert "bookings" not in profile.profile["saas"]


def test_one_guest_cannot_see_another_guest_booking():
    booked = _guest(phone="60173948123")
    _booking(booked)
    stranger = _guest(phone="60129998888")
    with local.serving(HOTEL, stranger):
        assert local.hotel_get_booking() == local.NO_BOOKING


def test_a_visitor_we_hold_no_record_for_still_gets_a_working_booking():
    """The web chat can reach a bot with no profile behind it. Better a booking
    that lives for the conversation than a tool that fails in front of a customer.
    """
    with local.serving(HOTEL, None):
        booking = json.loads(local.hotel_create_booking("Family Suite", SOON, LATER, 4))
        assert json.loads(local.hotel_get_booking())[0]["booking_id"] == booking["booking_id"]


def test_a_tool_called_outside_a_conversation_says_so_instead_of_crashing():
    assert local.hotel_get_booking() == local.NO_TURN
    assert local.saas_get_tickets() == local.NO_TURN
    assert local.hotel_search_rooms() == local.NO_TURN
    assert local.hotel_create_booking("Sea View Suite", SOON, LATER, 2) == local.NO_TURN
    assert local.saas_create_ticket("Anything", "at all") == local.NO_TURN


def test_a_record_cannot_grow_without_bound():
    """It lives inside one Redis key alongside the conversation history."""
    profile = _guest()
    with local.serving(SAAS, profile):
        for index in range(local.MAX_RECORDS + 5):
            local.saas_create_ticket(f"Ticket {index}", "Something happened.")
        kept = json.loads(local.saas_get_tickets())
    assert len(kept) == local.MAX_RECORDS
    # The oldest go, not the newest: the ones still being talked about are recent.
    assert kept[-1]["subject"] == f"Ticket {local.MAX_RECORDS + 4}"


# --------------------------------------------------------------------------- #
# The wiring, end to end
# --------------------------------------------------------------------------- #


def _assistant_message(content: list, stop_reason: str) -> BetaMessage:
    return BetaMessage(
        id="msg_test",
        model="claude-sonnet-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        content=content,
        usage=BetaUsage(input_tokens=1, output_tokens=1),
    )


def test_get_reply_opens_the_turn_so_a_ticket_reaches_the_customer_record():
    """Without this, every tool above answers NO_TURN in production.

    The tools take only the arguments the model fills in, so "whose conversation
    is this" can only arrive out of band. This is the seam that carries it.
    """
    profile = _guest()
    wants_tool = _assistant_message(
        [
            BetaToolUseBlock(
                type="tool_use",
                id="tu_1",
                name="saas_create_ticket",
                input={
                    "subject": "Export to CSV fails",
                    "description": "Clicking export does nothing.",
                    "priority": "high",
                },
            )
        ],
        "tool_use",
    )
    final = _assistant_message([BetaTextBlock(type="text", text="Ticket opened.")], "end_turn")

    events.clear()
    with patch.object(llm._client.beta.messages, "parse", side_effect=[wants_tool, final]):
        reply = llm.get_reply(SAAS, profile, history=[])

    assert reply == "Ticket opened."
    tickets = profile.profile["saas"]["tickets"]
    assert [ticket["subject"] for ticket in tickets] == ["Export to CSV fails"]

    # And it goes up on the console the same way a retail ERP call does, which is
    # the whole reason these bots have tools at all.
    start, end = [event for event in events.since(0) if event.type != events.USAGE]
    assert start.type == events.TOOL_START and start.tool == "saas_create_ticket"
    assert end.type == events.TOOL_END and end.status == "ok"
    assert tickets[0]["ticket_id"] in end.output
    events.clear()

    # And the turn is closed behind it, rather than leaking into the next one.
    assert local.saas_get_tickets() == local.NO_TURN
