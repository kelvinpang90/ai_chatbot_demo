"""Tools for the bots that have no back office behind them.

`retail` calls a real ERP and a real CRM. `hotel` and `saas` have neither, and
until now they answered out of the JSON in their bot file alone -- which on the
console screen looks like nothing happening at all, next to a bot whose every
sentence is a visible call. Same shell, then: these tools read the bot's own
`context_data` and keep whatever the customer creates in that customer's slot of
their profile record.

Read-only would have given away the trick immediately. A support bot that cannot
open a ticket and a hotel bot that cannot change a booking are two questions away
from being caught, and those are the two questions everybody asks.

What is stored lives in `UserProfile.profile[bot_id]`, i.e. in the same record
the customer's phone number keys -- so a ticket opened on Monday is still there on
Wednesday, for as long as the record lives. The tools mutate the profile object
the router is holding rather than saving one of their own: the router saves at
the end of the turn, and a second copy written here would simply be overwritten
by it.

Hotel bookings are the exception since task 38.3: they are written to the resort's
own table (`verticals/hotel`), so a back office can list every guest's, and the
guest's record holds none of them.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime

from anthropic import beta_tool

from app.bots.registry import BotConfig
from app.services.user_store import UserProfile
from app.verticals import StoreUnavailable
from app.verticals.hotel import models as hotel_bookings

logger = logging.getLogger(__name__)

# A tool that ran outside a conversation has nobody to answer about and nowhere
# to write. It should say so rather than invent a guest.
NO_TURN = "This could not be checked because the conversation is not open."

NO_ROOMS = (
    "No room type matches that. Tell the guest plainly and offer what is "
    "available instead -- do not invent a room or a rate."
)
NO_BOOKING = (
    "There is no booking on file for this guest. Say so plainly -- never invent "
    "a booking number -- and offer to make one."
)
# The resort's booking system (task 38.3). The same posture as the restaurant's:
# a database that is down must never become "your room is booked".
NO_GUEST = (
    "This conversation has no guest record to hold a booking, so nothing can be "
    "booked or looked up here. Say you cannot book it right now and offer to "
    "have a colleague call them back."
)
BOOKING_NOT_SAVED = (
    "The room could NOT be booked -- the resort's booking system is unreachable. "
    "Tell the guest plainly that it did not go through and offer to have a "
    "colleague call them back. Never tell them it is booked and never make up a "
    "booking number."
)
BOOKING_NOT_CHANGED = (
    "The booking could NOT be changed -- the resort's booking system is "
    "unreachable, so it stands as it was. Tell the guest plainly and offer to "
    "have a colleague call them back. Do not tell them it has changed."
)
# Found running task 38.3 through the real model: a guest's "帮我订" was booked
# at once and again on "确认", and the back office showed the same stay twice.
ALREADY_BOOKED = (
    "This exact stay was already booked for this guest, so no second booking was "
    "made. Give them this booking number. Do not call it a new or a corrected "
    "booking."
)
BOOKINGS_UNREADABLE = (
    "The resort's booking system could not be reached just now, so their bookings "
    "could not be checked. Say so plainly and offer to have a colleague call them "
    "back. Do not repeat dates or totals from earlier in the conversation."
)
NO_TICKET = (
    "There are no support tickets on file for this customer. Say so plainly and "
    "offer to open one; never invent a ticket number."
)
NO_KNOWN_ISSUE = (
    "Nothing in the known-issues list matches that. Say it is not a known issue, "
    "do not guess a fix, and offer to open a support ticket."
)

# Tickets live inside one customer's profile in Redis. Twenty is far more than a
# demo will ever make and still small enough that a runaway loop cannot grow the
# record without bound.
MAX_RECORDS = 20

# A stay nobody would book by chat. Mostly a guard against a mistyped year
# turning into a four-figure bill.
MAX_NIGHTS = 30

# A subject is a label, so trimming one still reads. A description is trimmed far
# less tightly because it is what the support engineer actually reads.
MAX_SUBJECT_CHARS = 120
MAX_DESCRIPTION_CHARS = 2000

PRIORITIES = ("low", "normal", "high", "urgent")

# Scored keyword matching over a five-line list, which is all this needs to be.
# Without the stopwords a question phrased as a sentence matches every issue on
# the list, because "the" appears in all of them.
STOPWORDS = frozenset(
    {
        "and", "are", "but", "can", "for", "get", "has", "have", "how",
        "its", "not", "the", "this", "that", "was", "what", "when", "why",
        "with", "you", "your",
    }
)
MAX_ISSUE_RESULTS = 3


class _Refused(Exception):
    """A booking the data does not support. Its text is what the model gets back."""


@dataclass
class _Serving:
    """Which bot is answering, and where that bot's records for this customer are.

    `store` is a live reference into `UserProfile.profile[bot.id]`, not a copy:
    writing through it is what puts a ticket on the record the router saves. For
    a visitor we hold no profile for it is a plain dict that dies with the turn,
    so the tools still work within the conversation and simply do not outlive it.
    """

    bot: BotConfig
    store: dict
    # The record itself, or None for a visitor we hold nothing for. A live
    # reference for the same reason `store` is: the router saves this object when
    # the turn ends, so a tool that writes to a second copy has written nothing.
    # Only one tool needs it, and it needs it for the one fact a tool's own
    # arguments can never carry -- whose conversation this is. The model must not
    # be in a position to name somebody else's.
    customer: "UserProfile | None" = None


_serving: ContextVar[_Serving | None] = ContextVar("local_tools_serving", default=None)


@contextmanager
def serving(bot: BotConfig, customer: UserProfile | None):
    """Open a turn for these tools: this bot, this customer's records.

    A ContextVar for the same reason the audit log uses one -- the tool functions
    are module-level and take only the arguments the model fills in, and each
    inbound message is handled in its own context, so two customers writing at
    once cannot see each other's bookings.
    """
    store = {} if customer is None else customer.profile.get(bot.id)
    if not isinstance(store, dict):
        # A slot that is not a dict can only be a record from somewhere else --
        # the profile is read back off Redis, and `_deserialise` heals the fields
        # it knows about but cannot vouch for this free-form one. Start it over
        # rather than raise in the middle of a customer's sentence.
        store = {}
        if customer is not None:
            customer.profile[bot.id] = store
    token = _serving.set(
        _Serving(bot=bot, store=store, customer=customer)
    )
    try:
        yield
    finally:
        _serving.reset(token)


def _current() -> _Serving:
    current = _serving.get()
    if current is None:
        raise _Refused(NO_TURN)
    return current


def customer() -> "UserProfile | None":
    """Whose conversation this turn belongs to, or None outside one.

    Exported because a tool that hands the conversation to a person has to know
    which conversation, and must not be able to get that from the model. Returns
    None rather than raising: "there is nobody here to hand over" is an answer
    the caller gives the customer, not a failure.
    """
    current = _serving.get()
    return None if current is None else current.customer


def customer_language() -> str | None:
    """The language on this customer's record, for a line a tool writes itself.

    None outside a conversation or before they have written anything we could
    read, which a `Localized` line answers in all three (task 38.1).
    """
    current = customer()
    return current.language if current is not None else None


def caller_phone() -> str:
    """The number the channel itself established for this conversation, or "".

    The one identifier in a turn that the model cannot have made up: WhatsApp
    puts it on the message, and the web chat keys the record by it. Everything
    else a tool is handed -- a name, a company, a number read out in the chat --
    is the customer's word for who they are, which is exactly what the back
    office tools must not act on.

    Empty for a customer whose number Meta hides behind a username. That is a
    real state, not a failure, and the caller decides what to do about it: for
    the ERP and the CRM it means the account tools have nothing to bind to.
    """
    current = customer()
    return (current.phone if current is not None else "") or ""


def records() -> dict | None:
    """This customer's slot for the answering bot, or None outside a turn.

    The same live reference the tools below write through, exported for the
    food tools' cart (task 25) so there is one place that decides where a
    customer's in-progress things are kept.
    """
    current = _serving.get()
    return None if current is None else current.store


def _catalogue(key: str) -> list[dict]:
    """A list out of the bot's own JSON, which is the only data these bots have."""
    rows = _current().bot.context_data.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _stored(name: str) -> list[dict]:
    """What this customer has on file, without creating the slot to say "none"."""
    rows = _current().store.get(name)
    return rows if isinstance(rows, list) else []


def _store(name: str, records: list[dict]) -> None:
    _current().store[name] = records[-MAX_RECORDS:]


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _reference(prefix: str) -> str:
    """A booking or ticket number.

    Random rather than counted: a counter would need somewhere of its own to
    live, and two customers whose first booking is both numbered 1001 would look
    wrong on a screen the whole demo is watched through.
    """
    return f"{prefix}-{secrets.randbelow(9000) + 1000}"


def _now() -> str:
    """The local wall clock, which the compose files pin to Asia/Kuala_Lumpur."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# Hotel
# --------------------------------------------------------------------------- #


def _room(room_type: str) -> dict:
    wanted = str(room_type or "").strip().casefold()
    for room in _catalogue("room_types"):
        if str(room.get("room_type", "")).strip().casefold() == wanted:
            return room
    names = ", ".join(str(room.get("room_type")) for room in _catalogue("room_types"))
    raise _Refused(
        f"There is no room type called {room_type!r}. The rooms that exist are: "
        f"{names}. Offer one of those -- never a rate for a room the resort does not have."
    )


def _day(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        # Today travels with the refusal because the model has no idea what the
        # date is: without it, "next Friday" cannot be turned into the YYYY-MM-DD
        # this wants, and the retry would be the same guess again.
        raise _Refused(
            f"{label} was not a date this can use. Dates must be written "
            f"YYYY-MM-DD, and today is {date.today().isoformat()}. If the guest "
            f"said something like 'next weekend', confirm the exact dates with "
            f"them before booking."
        ) from None


def _stay(
    room_type: str, check_in: str, check_out: str, guests: int, arriving_is_new: bool = True
) -> dict:
    """One booking, priced off the catalogue, or a refusal explaining itself.

    Every field the guest is told is worked out here rather than taken from the
    model: the rate comes off the room, the nights off the dates and the total off
    both. The one thing a bot with no booking system must not do is agree to a
    price nothing produced.

    `arriving_is_new` is false when a stay already under way is being changed:
    the rule is that nobody may be checked in to a date that has gone, not that a
    guest standing at the desk cannot add a night.
    """
    room = _room(room_type)
    arrive = _day(check_in, "The check-in date")
    leave = _day(check_out, "The check-out date")
    nights = (leave - arrive).days

    if nights < 1:
        raise _Refused("The check-out date must be after the check-in date.")
    if arriving_is_new and arrive < date.today():
        raise _Refused(
            f"That check-in date has already passed -- today is "
            f"{date.today().isoformat()}. Confirm the dates with the guest."
        )
    if nights > MAX_NIGHTS:
        raise _Refused(
            f"A stay of {nights} nights is longer than this can book "
            f"({MAX_NIGHTS} maximum). Check the dates with the guest."
        )

    try:
        party = int(guests)
    except (TypeError, ValueError):
        party = 0
    if party < 1:
        raise _Refused("Ask the guest how many people are staying.")
    capacity = int(room.get("max_guests") or 0)
    if party > capacity:
        raise _Refused(
            f"{room.get('room_type')} sleeps {capacity}, not {party}. Offer a "
            f"room that fits the party, or more than one room."
        )

    rate = float(room.get("price_per_night_rm") or 0)
    return {
        "room_type": room.get("room_type"),
        "location": room.get("location"),
        "check_in": arrive.isoformat(),
        "check_out": leave.isoformat(),
        "nights": nights,
        "guests": party,
        "rate_per_night_rm": rate,
        "total_rm": round(rate * nights, 2),
    }


@beta_tool
def hotel_search_rooms(location: str = "", guests: int = 0, max_price_rm: float = 0) -> str:
    """Search the resort's room types, rates and capacity.

    Call this before quoting any room or price. You have no room list in front of
    you: if you have not called this, you do not know what the resort has or what
    it costs.

    Args:
        location: Which property, "Langkawi" or "Penang". Leave empty for both.
        guests: How many people will stay. Rooms that cannot hold that many are
            left out. Leave as 0 if the guest has not said.
        max_price_rm: The most they want to pay per night in RM. Leave as 0 for
            no limit.
    """
    try:
        rooms = _catalogue("room_types")
    except _Refused as refusal:
        return str(refusal)

    where = str(location or "").strip().casefold()
    try:
        party = max(0, int(guests))
    except (TypeError, ValueError):
        party = 0
    try:
        ceiling = float(max_price_rm)
    except (TypeError, ValueError):
        ceiling = 0.0

    matches = [
        room
        for room in rooms
        if (not where or where in str(room.get("location", "")).casefold())
        and (not party or int(room.get("max_guests") or 0) >= party)
        and (ceiling <= 0 or float(room.get("price_per_night_rm") or 0) <= ceiling)
    ]
    return _dump(matches) if matches else NO_ROOMS


def _guest() -> UserProfile:
    """The guest this turn belongs to, or a refusal saying why there is none.

    Outside a conversation is NO_TURN, as for every tool here. A conversation with
    no record behind it cannot hold a booking any more: bookings are filed under
    the customer the channel established, and there is nobody to file this one
    under -- the restaurant's tools draw the same line.
    """
    current = _current()
    if current.customer is None:
        raise _Refused(NO_GUEST)
    return current.customer


def _same_stay(bookings: list, stay: dict):
    """The booking among these that is exactly this stay, if there is one."""
    wanted = (stay["room_type"], stay["check_in"], stay["check_out"], stay["guests"])
    return next(
        (b for b in bookings if (b.room_type, b.check_in, b.check_out, b.guests) == wanted),
        None,
    )


@beta_tool
def hotel_create_booking(room_type: str, check_in: str, check_out: str, guests: int) -> str:
    """Book a room for this guest and give them the booking number.

    Call this only once the guest has agreed to the room and the dates. The rate,
    the number of nights and the total are worked out here from the room
    catalogue -- quote back what this returns rather than a total of your own.

    Args:
        room_type: The exact room type from hotel_search_rooms.
        check_in: Arrival date as YYYY-MM-DD.
        check_out: Departure date as YYYY-MM-DD.
        guests: How many people are staying.
    """
    try:
        stay = _stay(room_type, check_in, check_out, guests)
        guest = _guest()
    except _Refused as refusal:
        return str(refusal)

    try:
        # The same stay twice is the model repeating itself -- once when the guest
        # says "book it" and again when they say "yes", or two calls in one turn --
        # not a guest who wants two identical rooms on the same nights. The
        # booking that exists is the answer; a second row is a back office that
        # shows the demo tripping over itself.
        same = _same_stay(hotel_bookings.bookings_for(guest.key_id), stay)
        if same is not None:
            return _dump({**same.for_the_guest(), "note": ALREADY_BOOKED})
        booking = hotel_bookings.book(
            customer_key=guest.key_id,
            customer_name=guest.display_name or "",
            phone=guest.phone or "",
            stay=stay,
            at=time.time(),
        )
    except StoreUnavailable:
        logger.warning("hotel booking not saved: the booking system is unreachable")
        return BOOKING_NOT_SAVED

    logger.info("hotel booking %s created for the current guest", booking.booking_id)
    return _dump(booking.for_the_guest())


@beta_tool
def hotel_get_booking(booking_id: str = "") -> str:
    """Look up this guest's bookings.

    Always call this before saying anything about a booking, including one made
    earlier in this conversation: what you were told about this guest when the
    conversation opened is a snapshot, and a booking changed since is a guest
    told the wrong dates.

    Args:
        booking_id: A specific booking number. Leave empty for all of theirs.
    """
    try:
        guest = _guest()
    except _Refused as refusal:
        return str(refusal)

    try:
        found = hotel_bookings.bookings_for(guest.key_id, str(booking_id or "").strip())
    except StoreUnavailable:
        return BOOKINGS_UNREADABLE
    return _dump([booking.for_the_guest() for booking in found]) if found else NO_BOOKING


@beta_tool
def hotel_modify_booking(
    booking_id: str,
    room_type: str = "",
    check_in: str = "",
    check_out: str = "",
    guests: int = 0,
) -> str:
    """Change an existing booking: different dates, room type or party size.

    Everything left empty stays as it is. The rate and the total are worked out
    again from the room catalogue, so a shorter stay really does cost less -- quote
    back what this returns.

    Args:
        booking_id: The booking number to change, from hotel_get_booking.
        room_type: A different room type, exactly as hotel_search_rooms spells it.
        check_in: A new arrival date as YYYY-MM-DD.
        check_out: A new departure date as YYYY-MM-DD.
        guests: A new party size.
    """
    try:
        guest = _guest()
    except _Refused as refusal:
        return str(refusal)

    number = str(booking_id or "").strip()
    try:
        # Theirs or nothing: the lookup is by this guest as well as the number.
        found = hotel_bookings.bookings_for(guest.key_id, number) if number else []
    except StoreUnavailable:
        return BOOKINGS_UNREADABLE
    if not found:
        return NO_BOOKING

    current = found[0]
    try:
        # Priced from scratch off whatever the booking now says, so a change of
        # room and a change of dates cannot leave a total belonging to neither.
        changed = _stay(
            room_type or current.room_type,
            check_in or current.check_in,
            check_out or current.check_out,
            guests or current.guests,
            arriving_is_new=bool(str(check_in or "").strip()),
        )
    except _Refused as refusal:
        return str(refusal)

    try:
        updated = hotel_bookings.change(current, changed, at=time.time())
    except StoreUnavailable:
        logger.warning("hotel booking %s not changed: the booking system is unreachable", number)
        return BOOKING_NOT_CHANGED
    return _dump(updated.for_the_guest())


# --------------------------------------------------------------------------- #
# SaaS support
# --------------------------------------------------------------------------- #


def _words(text: str) -> set[str]:
    return {
        word
        for word in re.split(r"\W+", str(text or "").casefold())
        if len(word) > 2 and word not in STOPWORDS
    }


@beta_tool
def saas_search_known_issues(query: str) -> str:
    """Search the known-issues list for what the customer is reporting.

    Call this before offering any fix. The fixes you may give are the ones this
    returns; if it finds nothing, the honest answer is that it is not a known
    issue and the next step is a ticket.

    Args:
        query: What the customer described, in their words.
    """
    try:
        issues = _catalogue("known_issues")
    except _Refused as refusal:
        return str(refusal)

    wanted = _words(query)
    if not wanted:
        return NO_KNOWN_ISSUE

    scored = [
        (len(wanted & _words(f"{issue.get('issue', '')} {issue.get('fix', '')}")), issue)
        for issue in issues
    ]
    matches = [issue for score, issue in sorted(scored, key=lambda row: -row[0]) if score]
    return _dump(matches[:MAX_ISSUE_RESULTS]) if matches else NO_KNOWN_ISSUE


@beta_tool
def saas_create_ticket(subject: str, description: str, priority: str = "normal") -> str:
    """Open a support ticket and give the customer the ticket number.

    Open one when the known issues do not cover the problem, when the fix did not
    work, or when the customer asks for a human. Tell them the number this
    returns -- it is the only one that exists.

    Args:
        subject: One line naming the problem.
        description: What the customer reported, including anything they have
            already tried, in their own words.
        priority: One of low, normal, high, urgent. Use urgent only for something
            that has stopped them working entirely.
    """
    try:
        tickets = list(_stored("tickets"))
    except _Refused as refusal:
        return str(refusal)

    subject = str(subject or "").strip()
    description = str(description or "").strip()
    if not subject or not description:
        return (
            "A ticket needs a one-line subject and a description of the problem. "
            "Ask the customer what happened before opening one."
        )

    level = str(priority or "").strip().casefold()
    if level not in PRIORITIES:
        # Quietly filing an "urgent" as normal would be a promise broken out of
        # sight of everyone who could notice.
        return f"Priority must be one of: {', '.join(PRIORITIES)}."

    ticket = {
        "ticket_id": _reference("TCK"),
        "subject": subject[:MAX_SUBJECT_CHARS],
        "description": description[:MAX_DESCRIPTION_CHARS],
        "priority": level,
        "status": "open",
        "opened_at": _now(),
    }
    tickets.append(ticket)
    _store("tickets", tickets)
    logger.info("support ticket %s opened for the current customer", ticket["ticket_id"])
    return _dump(ticket)


@beta_tool
def saas_get_tickets(ticket_id: str = "") -> str:
    """Look up this customer's support tickets and their status.

    Always call this before saying anything about a ticket, including one opened
    earlier in this conversation -- never quote a ticket number from memory.

    Args:
        ticket_id: A specific ticket number. Leave empty for all of theirs.
    """
    try:
        tickets = _stored("tickets")
    except _Refused as refusal:
        return str(refusal)

    wanted = str(ticket_id or "").strip().casefold()
    if wanted:
        tickets = [t for t in tickets if str(t.get("ticket_id", "")).casefold() == wanted]
    return _dump(tickets) if tickets else NO_TICKET


TOOLS = [
    hotel_search_rooms,
    hotel_create_booking,
    hotel_get_booking,
    hotel_modify_booking,
    saas_search_known_issues,
    saas_create_ticket,
    saas_get_tickets,
]
