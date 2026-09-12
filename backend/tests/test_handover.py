"""A person takes the conversation, and gives it back (task 20).

The answer to the last question anybody asks before buying: "and when it cannot
cope?". What these guard is the state machine and the one property the acceptance
criterion is written in terms of -- the customer never sees the join. So there is
no announcement on the way back, and while a person holds the conversation the
bot sends nothing at all, not even an apology.
"""
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.console import events
from app.main import app
from app.routers.whatsapp_webhook import dispatch_message
from app.services import audit, handover, llm, notify
from app.tools import human, local
from app.services.user_store import user_store

client = TestClient(app)

PHONE = "60123456789"
TOKEN = "console-token-for-tests"


@pytest.fixture
def _console_token():
    with patch("app.routers.console.settings.console_token", TOKEN):
        yield


def _customer(phone: str = PHONE, name: str | None = "Kelvin Peng"):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    profile.display_name = name
    user_store.save(profile)
    return profile


def _take_over(phone: str = PHONE, reason: str = "") -> bool:
    """What every caller does: act on the record rather than on a key. See
    `handover.begin` for why that distinction is load-bearing."""
    return handover.begin(user_store.get(phone), reason=reason)


def _give_back(phone: str = PHONE) -> bool:
    return handover.end(user_store.get(phone))


def _said(phone: str, text: str, seq: int = 1) -> dict:
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "text",
        "text": {"body": text},
    }


# -- the state machine ---------------------------------------------------------


def test_a_conversation_starts_in_the_bots_hands():
    assert handover.active(_customer()) is False


def test_taking_it_over_and_giving_it_back():
    _customer()

    assert _take_over(PHONE, reason="wants a person") is True
    assert handover.active(user_store.get(PHONE)) is True

    assert _give_back(PHONE) is True
    assert handover.active(user_store.get(PHONE)) is False


def test_taking_over_twice_is_not_a_second_takeover():
    """A customer who asks again while waiting has not asked for anything new,
    and the console would otherwise show the clock restarting."""
    _customer()
    _take_over(PHONE)
    first = user_store.get(PHONE).handover_since

    _take_over(PHONE)

    assert user_store.get(PHONE).handover_since == first


def test_giving_back_something_nobody_took_changes_nothing():
    _customer()

    assert _give_back(PHONE) is False


def test_a_stranger_cannot_be_handed_over():
    """Nothing on file means no conversation to take, which is the web chat's
    case and the case of a phone number somebody typed wrong."""
    assert handover.begin(user_store.get("60111000111")) is False


def test_it_survives_the_process_that_started_it():
    """The reason this lives on the record and not in `session_store`, which is
    where the plan put it: a redeploy mid-demo would drop the flag and set the
    bot talking over whoever was mid-sentence on the second screen."""
    _customer()
    _take_over(PHONE)

    # Everything this process was holding, gone. The record is not.
    stored = user_store._memory.copy()
    user_store.reset()
    user_store._memory.update(stored)

    assert handover.active(user_store.get(PHONE)) is True


def test_the_console_is_told_who_is_being_held_and_since_when():
    _customer()
    before = time.time()

    _take_over(PHONE)

    waiting = handover.waiting()
    assert [row["key_id"] for row in waiting] == [PHONE]
    assert waiting[0]["display_name"] == "Kelvin Peng"
    assert waiting[0]["since"] >= before


def test_the_room_sees_it_happen_and_sees_it_end():
    """Scene 3's second screen. The customer's phone shows nothing at all at this
    moment, so the console is the only place the handover is visible."""
    _customer()
    events.clear()

    _take_over(PHONE, reason="wants the rider to leave it at the door")
    _give_back(PHONE)

    spans = [e for e in events.since(0) if e.tool == handover.HANDOVER_TOOL]
    assert [e.type for e in spans] == [events.TOOL_START, events.TOOL_END]
    assert "rider" in spans[0].input["reason"]
    assert spans[1].status == "ok"
    events.clear()


# -- what the customer sees ----------------------------------------------------


def test_asking_for_a_person_hands_it_over_and_says_so_once():
    phone = "60129998001"
    _customer(phone)

    # Patched even though the handover should stop it being reached: without
    # this, the day the short-circuit breaks is the day this test quietly starts
    # calling the live model instead of failing. Two mutation runs took twenty
    # seconds each before this line existed.
    with patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
        sent = dispatch_message(_said(phone, "can I speak to a human please"))

    assert sent[0]["text"]["body"] == handover.HANDED_OVER_MESSAGE
    assert handover.active(user_store.get(phone)) is True


def test_the_words_a_malaysian_customer_actually_uses():
    for phone, said in (
        ("60129998002", "我要转人工"),
        ("60129998003", "找真人"),
        ("60129998004", "boleh cakap dengan orang sebenar tak"),
    ):
        _customer(phone)
        with patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
            dispatch_message(_said(phone, said))
        assert handover.active(user_store.get(phone)) is True, said


def test_the_bot_says_nothing_at_all_once_a_person_has_it():
    """Not an apology, not a holding line. The customer is talking to a person
    now and a machine interjecting is the join becoming visible."""
    phone = "60129998005"
    _customer(phone)
    _take_over(phone)

    with patch.object(llm, "get_reply") as get_reply:
        sent = dispatch_message(_said(phone, "so can you do it or not?", seq=2))

    assert sent == []
    get_reply.assert_not_called()


def test_what_the_customer_says_while_waiting_is_still_written_down():
    """The transcript has to be whole whoever was typing, and the bot has to have
    read it when it gets the conversation back -- a customer who explained their
    problem to a person and finds the bot has never heard of it has been handed
    back badly."""
    phone = "60129998006"
    _customer(phone)
    _take_over(phone)

    with patch.object(llm, "get_reply"):
        dispatch_message(_said(phone, "the address is 12 Jalan Ampang", seq=3))

    assert user_store.get(phone).history[-1].content == "the address is 12 Jalan Ampang"


def test_the_bot_picks_up_again_after_it_is_handed_back(_console_token):
    """And says nothing about having been away."""
    phone = "60129998007"
    _customer(phone)
    _take_over(phone)
    _give_back(phone)

    with patch.object(llm, "get_reply", return_value="RM 328.90 each.") as get_reply:
        sent = dispatch_message(_said(phone, "how much are they?", seq=4))

    get_reply.assert_called_once()
    assert sent[0]["text"]["body"] == "RM 328.90 each."


def test_nothing_is_sent_to_the_customer_when_the_bot_takes_over_again():
    """The acceptance criterion in one line: the customer never sees the join."""
    phone = "60129998008"
    _customer(phone)
    _take_over(phone)

    with patch.object(notify, "send_now") as sent:
        _give_back(phone)

    sent.assert_not_called()


# -- the console's half --------------------------------------------------------


def test_the_console_can_take_a_conversation_and_hand_it_back(_console_token):
    _customer()

    taken = client.post(
        "/console/handover",
        json={"key_id": "+60 12-345 6789", "active": True},
        headers={"X-Console-Token": TOKEN},
    )
    assert taken.status_code == 200
    assert [c["key_id"] for c in taken.json()["customers"]] == [PHONE]

    given_back = client.post(
        "/console/handover",
        json={"key_id": PHONE, "active": False},
        headers={"X-Console-Token": TOKEN},
    )
    assert given_back.json()["customers"] == []


def test_a_typed_reply_reaches_the_customer_as_the_business(_console_token):
    """No mark on it, filed as an assistant turn: to the customer it is simply
    the answer. Only the audit log knows a person wrote it."""
    _customer()
    _take_over(PHONE)

    with patch.object(notify, "send_now") as sent:
        response = client.post(
            "/console/reply",
            json={"key_id": PHONE, "text": "Boss, I'll get the rider to leave it at the door."},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 200
    to, text = sent.call_args.args
    assert to == PHONE
    assert text == "Boss, I'll get the rider to leave it at the door."
    assert sent.call_args.kwargs["source"] == audit.HUMAN
    assert sent.call_args.kwargs["label"] == notify.HUMAN_TOOL


def test_typing_into_a_conversation_the_bot_still_has_is_refused(_console_token):
    """Two voices the customer cannot tell apart, neither aware of the other."""
    _customer()

    with patch.object(notify, "send_now") as sent:
        response = client.post(
            "/console/reply",
            json={"key_id": PHONE, "text": "hello?"},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 409
    sent.assert_not_called()


def test_an_empty_reply_is_not_sent(_console_token):
    _customer()
    _take_over(PHONE)

    with patch.object(notify, "send_now") as sent:
        response = client.post(
            "/console/reply",
            json={"key_id": PHONE, "text": "   "},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 400
    sent.assert_not_called()


def test_the_handover_controls_are_behind_the_console_token(_console_token):
    """They silence the bot and put words on a customer's phone."""
    for path, body in (
        ("/console/handover", {"key_id": PHONE, "active": True}),
        ("/console/reply", {"key_id": PHONE, "text": "hello"}),
    ):
        assert client.post(path, json=body).status_code == 401
    assert client.get("/console/handover").status_code == 401


# -- the tool the bot calls when it decides for itself --------------------------


def test_the_bot_can_hand_over_the_conversation_it_is_in():
    """Scene 3's move: the customer asks for something outside what any tool can
    do, and the bot passes it on rather than guessing. The conversation it hands
    over is the one it is in -- the model never names it, and could not."""
    profile = _customer("60129998010")

    with local.serving(get_bot("retail"), profile):
        answer = human.request_human_help("wants the rider to leave it at the door")

    assert answer == human.HANDED_OVER
    assert handover.active(profile) is True


def test_the_reason_reaches_the_colleague_picking_it_up():
    profile = _customer("60129998011")
    events.clear()

    with local.serving(get_bot("retail"), profile):
        human.request_human_help("wants to add chilli sauce and pay the difference")

    started = [e for e in events.since(0) if e.tool == handover.HANDOVER_TOOL][0]
    assert "chilli sauce" in started.input["reason"]
    events.clear()


def test_the_flag_lands_on_the_record_the_router_is_about_to_save():
    """The bug this shape exists to prevent: the tool runs mid-turn while the
    router holds the record, and the router saves it when the turn ends. A flag
    set on any other copy is one that copy is about to overwrite."""
    profile = _customer("60129998012")

    with local.serving(get_bot("retail"), profile):
        human.request_human_help("needs a manager")

    # Exactly what the router does next.
    user_store.save(profile)
    assert handover.active(user_store.get("60129998012")) is True


def test_a_visitor_with_no_record_is_not_promised_a_colleague():
    """The web chat. Better to say there is nobody to hand to than to let the bot
    tell somebody a colleague is coming who never will."""
    with local.serving(get_bot("retail"), None):
        answer = human.request_human_help("wants a person")

    assert answer == human.NO_ONE_TO_HAND_TO


def test_the_tool_outside_a_turn_hands_over_nothing():
    assert human.request_human_help("...") == human.NO_ONE_TO_HAND_TO


def test_asking_twice_does_not_announce_it_twice():
    """A bot that called it, was told it had happened, and called it again."""
    profile = _customer("60129998013")
    events.clear()

    with local.serving(get_bot("retail"), profile):
        human.request_human_help("first")
        human.request_human_help("second")

    started = [e for e in events.since(0) if e.type == events.TOOL_START]
    assert len(started) == 1
    events.clear()


def test_starting_the_demo_over_takes_it_back_from_the_person_too():
    """`menu` is the reset, and a flag that outlived the conversation it belonged
    to would show the customer the demo list and then say nothing ever again."""
    phone = "60129998014"
    _customer(phone)
    _take_over(phone)

    sent = dispatch_message(_said(phone, "menu", seq=9))

    assert sent  # the demo list, not silence
    assert handover.active(user_store.get(phone)) is False
