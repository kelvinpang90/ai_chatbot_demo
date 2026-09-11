"""Messages the bot sends because something happened (task 19).

The one path in this service that sends without having been asked, which is what
makes it the only one that can go wrong silently: there is no request waiting on
it and no customer watching a typing indicator. So what these guard is mostly
what happens when it fails, and what the console is told either way.
"""
import time
from unittest.mock import patch

import pytest

from app.console import events
from app.services import audit, notify, whatsapp, whatsapp_media
from app.services.user_store import user_store

PHONE = "60123456789"
TEXT = "您的订单 SO-1 已确认。 / Your order SO-1 is confirmed. / Pesanan SO-1 disahkan."
TEMPLATE = notify.Template(notify.ORDER_CONFIRMED, ("Kelvin", "SO-1", "RM 657.80"))


def _push(delay: float = 30.0, template: notify.Template | None = TEMPLATE) -> notify.Push:
    return notify.Push(delay_seconds=delay, text=TEXT, template=template)


@pytest.fixture
def _queue():
    """A WhatsApp turn, which is the only kind with a phone to buzz."""
    notify.begin()
    yield
    notify.close()


@pytest.fixture
def _sent():
    with patch.object(whatsapp_media, "send_message") as send:
        yield send


def test_a_tool_can_leave_something_to_be_said_later(_queue):
    assert notify.available() is True
    assert notify.add(_push()) is True


def test_nothing_is_queued_where_nothing_would_ever_send_it():
    """The web chat. A tool has to be able to tell, because a bot that promises
    "I'll message you when it ships" on a laptop has promised nothing."""
    assert notify.available() is False
    assert notify.add(_push()) is False


def test_dispatch_starts_one_clock_per_push_and_empties_the_queue(_queue):
    notify.add(_push(delay=120))
    notify.add(_push(delay=240))

    timers = notify.dispatch(PHONE)

    try:
        assert [timer.interval for timer in timers] == [120, 240]
        assert all(timer.is_alive() for timer in timers)
        # Emptied, or the next message would buzz the phone all over again.
        assert notify.dispatch(PHONE) == []
    finally:
        for timer in timers:
            timer.cancel()


def test_dispatch_without_a_queue_is_a_no_op():
    """Every inbound message reaches it, and most of them queued nothing."""
    assert notify.dispatch(PHONE) == []


def test_inside_the_window_the_push_goes_out_as_plain_text(_sent):
    """Which is every push this demo actually sends: the phone buzzes half a
    minute after the order, and the window is 24 hours wide."""
    notify._send(PHONE, _push(), window_opened_at=time.time())

    payload = _sent.call_args.args[0]
    assert payload["type"] == "text"
    assert payload["to"] == PHONE
    assert payload["text"]["body"] == TEXT


def test_outside_the_window_the_push_goes_out_as_the_approved_template(_sent):
    """WhatsApp carries nothing else once 24 hours have passed. Sending the text
    anyway would be an API error the customer never sees."""
    long_ago = time.time() - notify.CUSTOMER_SERVICE_WINDOW_SECONDS - 60

    notify._send(PHONE, _push(), window_opened_at=long_ago)

    payload = _sent.call_args.args[0]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == notify.ORDER_CONFIRMED
    assert payload["template"]["language"] == {"code": "en"}
    assert [p["text"] for p in payload["template"]["components"][0]["parameters"]] == [
        "Kelvin",
        "SO-1",
        "RM 657.80",
    ]


def test_outside_the_window_with_nothing_approved_to_say_nothing_is_sent(_sent):
    """Better than a Cloud API error nobody is watching for. The push was worth
    making inside the window and is not worth a template outside it."""
    long_ago = time.time() - notify.CUSTOMER_SERVICE_WINDOW_SECONDS - 60

    notify._send(PHONE, _push(template=None), window_opened_at=long_ago)

    _sent.assert_not_called()


def test_the_push_is_filed_so_the_model_knows_it_said_it(_sent):
    """Asked "when will it get here?" straight after, the model is replayed this
    history. Without the push in it, it is answering about a message it cannot
    see itself having sent."""
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)

    notify._send(PHONE, _push(), window_opened_at=time.time())

    stored = user_store.get(PHONE)
    assert [m.content for m in stored.history] == [TEXT]
    assert stored.history[-1].role == "assistant"


def test_a_push_is_recorded_in_the_transcript_as_its_own_turn(_sent):
    """The turn it was queued in closed a long time before it fired, so it opens
    one of its own -- a push belongs to the conversation, not to a reply."""
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)

    with patch.object(audit, "record_message") as recorded:
        notify._send(PHONE, _push(), window_opened_at=time.time())

    assert recorded.call_args.args == ("assistant", TEXT)


def test_a_customer_we_no_longer_hold_is_still_sent_their_message(_sent):
    """Seven days is the record's life and a follow-up could outlive it. The
    message is the point; the transcript entry is the part that can be missed."""
    notify._send("60111222333", _push(), window_opened_at=time.time())

    _sent.assert_called_once()


def test_the_console_shows_the_push_before_the_phone_does(_sent):
    """Scene 3's whole claim is "nobody typed that". The room can only see it on
    the second screen, because on the customer's phone it looks like any other
    message."""
    events.clear()

    notify._send(PHONE, _push(), window_opened_at=time.time())

    spans = [e for e in events.since(0) if e.tool == notify.PUSH_TOOL]
    assert [e.type for e in spans] == [events.TOOL_START, events.TOOL_END]
    assert spans[0].input["to"] == PHONE
    assert spans[0].input["kind"] == "text"
    assert spans[1].status == "ok"
    assert spans[1].output == TEXT
    assert spans[1].duration_ms is not None
    events.clear()


def test_a_push_meta_refuses_is_said_out_loud_rather_than_dying_on_its_thread():
    """It runs on a timer thread with nothing above it: an exception there is a
    traceback in a log nobody is reading. The console is where the one person who
    could notice is looking."""
    events.clear()

    with patch.object(
        whatsapp_media, "send_message", side_effect=whatsapp.WhatsAppSendError("131047")
    ):
        notify._send(PHONE, _push(), window_opened_at=time.time())

    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1
    assert failures[0].tool == notify.PUSH_TOOL
    assert "131047" in failures[0].output
    events.clear()


def test_a_failed_push_is_not_filed_as_something_the_customer_read():
    """The same rule the reply path follows: a message the channel would not
    carry must not become part of the history the model is replayed."""
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)

    with patch.object(
        whatsapp_media, "send_message", side_effect=whatsapp.WhatsAppSendError("131047")
    ):
        notify._send(PHONE, _push(), window_opened_at=time.time())

    assert user_store.get(PHONE).history == []


def test_the_template_names_are_the_ones_the_document_submitted():
    """docs/whatsapp-templates.md is what was pasted into Meta's form, and Meta
    holds the wording. A rename on either side is a send that fails and a phone
    that stays quiet, so the two names are pinned here."""
    assert notify.ORDER_CONFIRMED == "order_confirmed"
    assert notify.ORDER_SHIPPED == "order_shipped"
    assert notify.TEMPLATE_LANGUAGE == "en"


def test_the_clock_really_does_reach_the_send(_queue, _sent):
    """The one seam nothing else covers: `dispatch` hands a push to a timer
    thread, and every other test here calls `_send` directly. A wrong argument
    order between the two would be invisible until a demo went quiet."""
    notify.add(_push(delay=0.05))

    timer = notify.dispatch(PHONE)[0]
    timer.join(timeout=5)

    assert timer.is_alive() is False
    payload = _sent.call_args.args[0]
    assert payload["to"] == PHONE
    assert payload["text"]["body"] == TEXT
