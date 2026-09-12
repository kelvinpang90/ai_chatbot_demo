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

from app.bots import registry
from app.bots.registry import get_bot
from app.console import events
from app.main import app
from app.routers.whatsapp_webhook import _asked_for_a_person, dispatch_message
from app.services import audit, handover, llm, notify
from app.tools import human, local
from app.services.user_store import user_store
from app.session_store import session_store

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


# -- what the cold review found (2026-09-12) -----------------------------------
#
# Every one of these was green before the review ran and red after it. They are
# kept in the reviewer's own words where possible, because the value is in the
# examples rather than in the mechanism.


@pytest.mark.parametrize(
    "said",
    [
        # "Is this an AI?" -- the likeliest question anybody asks an AI demo, and
        # 人工智能 contains 人工.
        "你们这是人工智能吗？",
        "这是人工智能做的吗",
        # realestate's own persona tells the bot to offer this word.
        "I bought it from your agent last week, can I return it?",
        "Do you have an agent in Penang?",
        "is this suitable for human resources teams?",
        "human error la",
    ],
)
def test_ordinary_sentences_do_not_silence_the_bot(said):
    """The first version matched "human", "agent" and "人工" as substrings. Each
    of these muted the bot for seven days."""
    assert _asked_for_a_person(said) is False, said


@pytest.mark.parametrize(
    "said",
    [
        "我要转人工",
        "找真人",
        "可以帮我转人工客服吗",
        "can I speak to a human please",
        "i want to talk to a person",
        "boleh cakap dengan orang sebenar tak",
    ],
)
def test_somebody_actually_asking_still_gets_a_person(said):
    assert _asked_for_a_person(said) is True, said


@pytest.mark.parametrize(
    "message",
    [
        {"type": "sticker", "sticker": {"id": "media-stk-1"}},
        {"type": "audio", "audio": {"mime_type": "audio/ogg"}},
        {"type": "image", "image": {"mime_type": "image/jpeg"}},
        {"type": "document", "document": {"mime_type": "application/pdf"}},
    ],
)
def test_the_bots_own_apologies_do_not_interrupt_a_person(message):
    """Five paths return before the guard inside `_handle_text_message`, and the
    lines they send are the ones that announce there is a bot at all. "This demo
    can only read text, voice, photo and PDF", arriving in the middle of a human
    conversation, is the join made visible in a single line."""
    phone = "60129998020"
    _customer(phone)
    _take_over(phone)

    sent = dispatch_message({"id": f"wamid.{phone}.20", "from": phone, **message})

    assert sent == []


def test_the_daily_cap_does_not_interrupt_a_person():
    """The same shape as the four above, from further up the function."""
    phone = "60129998021"
    _customer(phone)
    _take_over(phone)

    with patch.object(session_store, "check_and_increment_daily_count", return_value=False):
        sent = dispatch_message(_said(phone, "hello?", seq=21))

    assert sent == []


def test_a_push_queued_before_the_handover_does_not_interrupt_it():
    """The worst shape of the six: the others are the bot answering, this one is
    the bot interrupting. Order placed, push queued, customer asks for a person,
    and a minute later "your order is on its way" lands on top of whatever the
    colleague is typing."""
    phone = "60129998022"
    _customer(phone)
    _take_over(phone)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify._send(phone, notify.Push(delay_seconds=0, text="您的订单已确认"), time.time())

    send.assert_not_called()


def test_a_person_typing_is_never_swallowed_as_a_push():
    """The guard above must not silence the thing it exists to protect."""
    phone = "60129998023"
    _customer(phone)
    _take_over(phone)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify.send_now(phone, "Boss, I'll sort it", label=notify.HUMAN_TOOL, source=audit.HUMAN)

    send.assert_called_once()


def test_a_person_taking_over_mid_turn_stops_the_answer_going_out():
    """A turn takes seconds and several tool calls, and the moment somebody
    reaches for the console is the moment the bot is visibly struggling. The
    router has held a copy of the record the whole time and knows nothing."""
    phone = "60129998024"
    _customer(phone)

    def take_over_while_it_thinks(*_args, **_kwargs):
        _take_over(phone)
        return "Sorry, I'm not sure about that."

    with patch.object(llm, "get_reply", side_effect=take_over_while_it_thinks):
        sent = dispatch_message(_said(phone, "can you do it or not", seq=24))

    assert sent == []
    # And the answer nobody sent is not in the history the model is replayed.
    assert [m.role for m in user_store.get(phone).history] == ["user"]
    # And the save that recorded the question did not undo the takeover that
    # caused it -- the copy being saved was loaded before the console was
    # clicked, which is the lost update this whole shape exists to avoid.
    assert handover.active(user_store.get(phone)) is True


def test_the_console_types_to_the_newest_handover_not_the_oldest():
    """One conversation nobody handed back last week is enough to make the
    default wrong for every demo after it: the banner names the wrong customer
    and every line the owner types lands on a stranger's phone."""
    _customer("60129998025", name="Last week")
    _take_over("60129998025")
    time.sleep(0.01)
    _customer("60129998026", name="Today")
    _take_over("60129998026")

    assert [row["key_id"] for row in handover.waiting()][0] == "60129998026"


def test_a_customer_who_hides_their_number_can_still_be_answered(_console_token):
    """Silenced by the keyword path and then never answered by anybody, bot or
    human, because the reply endpoint wanted a phone number that a BSUID record
    does not have -- while every other path addresses them by key perfectly well."""
    hidden = "US.1349120865"
    profile = user_store.get_or_create(hidden)
    profile.bot_id = "retail"
    user_store.save(profile)
    _take_over(hidden)

    with patch.object(notify, "send_now") as sent:
        response = client.post(
            "/console/reply",
            json={"key_id": hidden, "text": "Boss, we can do that."},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 200
    assert sent.call_args.args[0] == hidden


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/console/reply", {"key_id": PHONE, "text": "hello"}),
        ("post", "/console/handover", {"key_id": PHONE, "active": True}),
        ("post", "/console/tools", {"enabled": False}),
        ("post", "/console/demo-summary", {}),
    ],
)
def test_a_token_in_the_url_cannot_write(_console_token, method, path, body):
    """It lands in the nginx access log and in browser history by design. That
    was an acceptable key for reading a feed; it is not one for silencing the bot
    or putting arbitrary text on a customer's phone."""
    response = getattr(client, method)(f"{path}?token={TOKEN}", json=body)

    assert response.status_code == 401


def test_a_token_in_the_url_can_still_read(_console_token):
    """EventSource cannot send a header, so reading has to keep accepting it."""
    assert client.get(f"/console/handover?token={TOKEN}").status_code == 200


# -- what round two of the cold review found (2026-09-12) ----------------------


def test_the_closing_summary_is_not_swallowed_by_a_handover(_console_token):
    """N1, a regression the round-one fix introduced. The guard keyed on the
    label, so task 19.1's summary -- sent with the default one -- was dropped
    while the endpoint went on reporting success: the console said it had gone
    to Kelvin and the phone got nothing."""
    _customer()
    _take_over(PHONE)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify.send_now(PHONE, "📋 刚才这 10 分钟里…")

    send.assert_called_once()


def test_only_the_bots_own_timed_push_is_dropped():
    """What separates the two is not who they are addressed to but who started
    them: a timer, or a person's finger."""
    phone = "60129998030"
    _customer(phone)
    _take_over(phone)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify._send(phone, notify.Push(delay_seconds=30, text="您的订单已确认"), time.time())

    send.assert_not_called()


@pytest.mark.parametrize(
    "said",
    [
        "转接人工",  # how every Malaysian bank chat words it
        "能不能转真人",
        "人工在吗",
        "get me a human",
        "speak to an agent",
        "can I chat with a human",
        "nak cakap dengan manusia",
        "boleh saya bercakap dengan wakil",
    ],
)
def test_the_ways_people_actually_ask_for_a_person(said):
    """N2. The phrase list that replaced the word list missed 23 of 25 realistic
    phrasings -- an over-correction, and on the bots with no tools it was the
    only path there was."""
    assert _asked_for_a_person(said) is True, said


@pytest.mark.parametrize(
    "said",
    [
        "Let me talk to someone in my team and get back to you",
        "I need to speak to someone in accounts first",
        "I'll talk to someone about the budget",
        "我想找个人一起拼单",
        "我找同事帮我下单",
        "boleh saya cakap dengan orang yang hantar barang tu?",
        "I want a personal recommendation",
    ],
)
def test_deciding_out_loud_is_not_asking_for_a_person(said):
    """N3, the other direction. The first three are what a prospect says as they
    are deciding to buy -- the bot went silent at the close."""
    assert _asked_for_a_person(said) is False, said


def test_every_bot_can_reach_a_person():
    """N2's structural half. The keyword floor has now been wrong in both
    directions; judgement belongs to the model, and the light-tier bots are the
    ones least able to cope and so most in need of the way out."""
    for bot in registry.list_bots():
        assert "request_human_help" in bot.tools, bot.id


def test_tapping_a_button_does_not_interrupt_a_person():
    """N4, the seventh leak and the only one that is not an apology: a customer
    taken over before they had picked a demo taps one off the list."""
    phone = "60129998031"
    profile = user_store.get_or_create(phone)
    user_store.save(profile)
    _take_over(phone)

    sent = dispatch_message(
        {
            "id": f"wamid.{phone}.31",
            "from": phone,
            "type": "interactive",
            "interactive": {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}},
        }
    )

    assert sent == []


def test_a_message_that_arrived_while_the_model_thought_is_not_erased():
    """N5, the mid-turn guard's own lost update -- the bug it was written to
    prevent, reintroduced one line lower. Two messages in flight: the second is
    filed by the silent path, and the first then saves the copy it loaded before
    the second existed."""
    phone = "60129998032"
    _customer(phone)

    def take_over_and_let_another_message_land(*_args, **_kwargs):
        _take_over(phone)
        # The second message, handled by the silent path while this turn runs.
        dispatch_message(_said(phone, "the address is 12 Jalan Ampang", seq=33))
        return "Sorry, I'm not sure."

    with patch.object(llm, "get_reply", side_effect=take_over_and_let_another_message_land):
        dispatch_message(_said(phone, "how much?", seq=32))

    said = [m.content for m in user_store.get(phone).history]
    assert "the address is 12 Jalan Ampang" in said
    assert "how much?" in said
    assert "Sorry, I'm not sure." not in said


def _idle_for(phone: str, seconds: float) -> None:
    """Age the takeover so the person has been quiet for `seconds`."""
    profile = user_store.get(phone)
    profile.handover_active_at = time.time() - seconds
    user_store.save(profile)


def test_a_takeover_nobody_is_attending_lapses_on_its_own():
    """A1, the root the review pressed on in the confrontation pass: both
    round-one findings trace back to a flag with no ceiling, and the mitigation
    recorded for it -- the console banner -- is visible only to somebody with a
    console open on the day."""
    phone = "60129998033"
    _customer(phone)
    _take_over(phone)

    _idle_for(phone, handover.MAX_IDLE_SECONDS + 60)

    assert handover.active(user_store.get(phone)) is False
    assert [row["key_id"] for row in handover.waiting()] == []


def test_a_takeover_somebody_is_still_working_holds():
    phone = "60129998034"
    _customer(phone)
    _take_over(phone)

    _idle_for(phone, handover.MAX_IDLE_SECONDS - 600)

    assert handover.active(user_store.get(phone)) is True


def test_a_colleague_who_keeps_replying_never_runs_out_of_time(_console_token):
    """The reason the clock is idle-based rather than absolute. A ceiling on the
    whole takeover would drop a colleague mid-sentence at two hours and one
    minute, and the customer would watch the bot take over the conversation they
    were having with a person. Each reply puts the clock back to zero."""
    phone = "60129998035"
    _customer(phone)
    _take_over(phone)
    # Nearly out of time, in the way somebody who stepped away for coffee is.
    _idle_for(phone, handover.MAX_IDLE_SECONDS - 60)

    with patch.object(notify, "send_now"):
        response = client.post(
            "/console/reply",
            json={"key_id": phone, "text": "still here Boss, checking with the warehouse"},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 200
    # Back to zero: not "an hour and fifty-nine minutes used up".
    fresh = user_store.get(phone)
    assert time.time() - fresh.handover_active_at < 5
    assert handover.active(fresh) is True


def test_once_it_has_lapsed_the_console_has_to_take_it_over_again(_console_token):
    """The bot is answering this conversation again. Somebody typing into it
    from the console would be the second voice all over again, so the reply is
    refused rather than quietly delivered beside the bot's."""
    phone = "60129998038"
    _customer(phone)
    _take_over(phone)
    _idle_for(phone, handover.MAX_IDLE_SECONDS + 60)

    with patch.object(notify, "send_now") as sent:
        response = client.post(
            "/console/reply",
            json={"key_id": phone, "text": "sorry for the wait"},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 409
    sent.assert_not_called()


def test_a_customer_typing_into_the_silence_does_not_keep_it_alive():
    """Only the person's own actions count. Somebody still writing to a
    conversation nobody is reading is the failure this ceiling exists for, not
    evidence against it."""
    phone = "60129998036"
    _customer(phone)
    _take_over(phone)
    _idle_for(phone, handover.MAX_IDLE_SECONDS - 30)

    with patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
        dispatch_message(_said(phone, "hello? anyone there?", seq=36))

    _idle_for(phone, handover.MAX_IDLE_SECONDS + 60)
    assert handover.active(user_store.get(phone)) is False


def test_a_record_from_before_the_idle_clock_still_expires():
    """Written while the ceiling measured from the takeover itself. There is no
    activity stamp on it, and the moment it began is the honest thing to measure
    from -- which is exactly what the previous version did for everybody."""
    phone = "60129998037"
    _customer(phone)
    _take_over(phone)

    old = user_store.get(phone)
    old.handover_active_at = 0.0
    old.handover_since = time.time() - handover.MAX_IDLE_SECONDS - 60
    user_store.save(old)

    assert handover.active(user_store.get(phone)) is False


def test_a_fresh_takeover_already_counts_as_a_sign_of_life():
    """Taking it over is itself the person doing something. Without the stamp the
    clock would lean on the compatibility fallback for every new takeover, which
    would make that fallback load-bearing instead of what it is."""
    phone = "60129998039"
    _customer(phone)

    _take_over(phone)

    fresh = user_store.get(phone)
    assert time.time() - fresh.handover_active_at < 5


def test_a_record_from_before_the_idle_clock_is_still_held_if_it_is_recent():
    """The other half of the fallback, and the half that matters: a takeover
    written by the previous build has no activity stamp, and reading that as
    "idle since 1970" would hand every one of them back to the bot at once."""
    phone = "60129998040"
    _customer(phone)
    _take_over(phone)

    old = user_store.get(phone)
    old.handover_active_at = 0.0
    old.handover_since = time.time() - 60
    user_store.save(old)

    assert handover.active(user_store.get(phone)) is True


def test_handing_back_leaves_nothing_behind_on_the_record():
    """Both fields, not just the one `active` happens to read first. Stale data
    left on a record is how the next bug gets built."""
    phone = "60129998041"
    _customer(phone)
    _take_over(phone)

    _give_back(phone)

    fresh = user_store.get(phone)
    assert fresh.handover_since == 0.0
    assert fresh.handover_active_at == 0.0


def test_touching_a_conversation_the_bot_still_has_stamps_nothing():
    """`touch` says "the person holding this is still here". There is no person
    holding this one."""
    phone = "60129998042"
    _customer(phone)

    handover.touch(user_store.get(phone))

    assert user_store.get(phone).handover_active_at == 0.0
