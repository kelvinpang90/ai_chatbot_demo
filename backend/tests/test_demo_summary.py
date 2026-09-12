"""The closing message a demo leaves on the customer's phone (task 19.1).

Every number in it comes out of the audit log, which is the whole point rather
than an implementation detail: the demo spends eight minutes arguing that this
bot does not make things up, and one invented figure on the last line would
undo the argument. So most of what is guarded here is that a count is a count.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.console import summary
from app.main import app
from app.services import notify
from app.services.audit import audit_store
from app.services.user_store import user_store

client = TestClient(app)

CONVERSATION = "11111111-2222-3333-4444-555555555555"
PHONE = "60123456789"
TOKEN = "console-token-for-tests"

STARTED = datetime(2026, 9, 12, 14, 0, 0)


def _messages(count: int = 6, minutes: float = 8) -> list[dict]:
    """One row per message, spread evenly over `minutes`, oldest first."""
    step = timedelta(minutes=minutes) / max(count - 1, 1)
    return [{"created_at": STARTED + step * n} for n in range(count)]


def _call(tool: str, output: str | None = None) -> dict:
    return {"tool": tool, "output": output}


@pytest.fixture
def _audit():
    """An audit log that answers, with the two queries `tally` makes."""
    with patch.object(type(audit_store), "enabled", property(lambda self: True)):
        yield


@pytest.fixture
def _console_token():
    with patch.object(summary.__dict__["logger"].parent, "level", 50):  # quieten the warning
        pass
    with patch("app.routers.console.settings.console_token", TOKEN):
        yield


def _answers(spans: list[dict], calls: list[dict]):
    """`tally` asks for the span first and the tool calls second."""
    return [spans, calls]


def test_the_counts_are_what_actually_ran(_audit):
    """The acceptance criterion: the numbers match the real thing."""
    calls = [
        _call("erp_search_sku"),
        _call("erp_get_inventory"),
        _call("erp_create_sales_order", '{"order_no": "SO-2026-00001"}'),
        _call("erp_generate_einvoice", '{"invoice_no": "INV-2026-00001"}'),
        _call("crm_create_lead"),
    ]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        counted = summary.tally(CONVERSATION)

    assert counted.minutes == 8
    assert counted.counted == 5
    phrases = {line[0].tools[0]: (line[1], line[2]) for line in counted.lines}
    assert phrases["erp_search_sku"] == (2, [])
    assert phrases["erp_create_sales_order"] == (1, ["SO-2026-00001"])
    assert phrases["erp_generate_einvoice"] == (1, ["INV-2026-00001"])
    assert phrases["crm_create_lead"] == (1, [])


def test_a_failed_tool_call_is_not_something_to_boast_about(_audit):
    """Only `status = 'ok'` rows are asked for, which is the honest half of the
    claim: a stock check that could not reach the ERP did not check stock."""
    with patch.object(audit_store, "query", side_effect=_answers(_messages(), [])) as query:
        summary.tally(CONVERSATION)

    assert "status = 'ok'" in query.call_args_list[1].args[0]


def test_the_document_numbers_come_out_of_what_the_tool_returned(_audit):
    """The part that makes the message checkable rather than impressive: the
    customer reads SO-2026-00001 here and finds it on the screen behind you."""
    calls = [
        _call("erp_create_sales_order", '{"order_no": "SO-2026-00001"}'),
        _call("erp_create_sales_order", '{"order_no": "SO-2026-00002"}'),
    ]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "SO-2026-00001, SO-2026-00002" in text


def test_a_tool_result_that_is_not_json_does_not_take_the_summary_down(_audit):
    """A refusal comes back as a sentence. It is still a call that ran, and it
    still must not become a document number in the closing message."""
    calls = [_call("erp_create_sales_order", "The order could not be created.")]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "（" not in text
    assert "1 real order placed" in text


def test_the_same_document_is_named_once_however_often_it_was_touched(_audit):
    calls = [
        _call("erp_generate_einvoice", '{"invoice_no": "INV-2026-00001"}'),
        _call("erp_generate_einvoice", '{"invoice_no": "INV-2026-00001"}'),
    ]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert text.count("INV-2026-00001") == 3  # once per language, not once per call


def test_a_long_list_of_documents_is_cut_rather_than_pasted_in(_audit):
    calls = [
        _call("erp_create_sales_order", '{"order_no": "SO-%d"}' % n) for n in range(1, 8)
    ]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "SO-1, SO-2, SO-3" in text
    assert "SO-4" not in text


def test_the_bots_own_push_is_not_counted_as_something_it_did(_audit):
    """This message is a push. A summary that counted itself would be strange,
    and the one the order sent is not an achievement worth listing either."""
    with patch.object(
        audit_store, "query", side_effect=_answers(_messages(), [_call("notify.push")])
    ):
        counted = summary.tally(CONVERSATION)

    assert counted.lines == []


def test_a_demo_where_nothing_was_called_says_so_rather_than_inventing(_audit):
    """A conversation that stayed on questions. The keepsake line is still true
    and is still the point of sending anything at all."""
    with patch.object(audit_store, "query", side_effect=_answers(_messages(), [])):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "我们聊了 8 分钟" in text
    assert "ERP" not in text
    assert "留在您手机里" in text


def test_a_twelve_second_conversation_is_still_a_minute(_audit):
    """Zero reads as a bug rather than as brevity. Twelve seconds rather than
    forty, which is what this test was written with first: `round` carries forty
    to one on its own, so that version proved nothing about the floor it exists
    to test, and a mutation that deleted the floor left it green."""
    with patch.object(
        audit_store, "query", side_effect=_answers(_messages(minutes=0.2), [])
    ):
        assert summary.tally(CONVERSATION).minutes == 1


def test_a_conversation_nothing_was_recorded_for_is_not_summarised(_audit):
    """Different from a demo in which nothing happened, and only one of the two
    is worth a message."""
    with patch.object(audit_store, "query", side_effect=_answers([], [])):
        assert summary.tally(CONVERSATION) is None


def test_a_demo_picked_up_hours_later_is_not_counted_from_the_morning(_audit):
    """Found in the live audit log rather than written up front: the first real
    conversation on file ran 16:34 to 19:25, because the demo was chosen in the
    afternoon and the photo arrived that evening. One id, two sittings -- and
    "in the last 171 minutes I..." is a different claim, not a rounded one."""
    morning = [
        {"created_at": STARTED},
        {"created_at": STARTED + timedelta(minutes=2)},
    ]
    evening = [
        {"created_at": STARTED + timedelta(hours=3)},
        {"created_at": STARTED + timedelta(hours=3, minutes=6)},
    ]

    with patch.object(audit_store, "query", side_effect=_answers(morning + evening, [])) as query:
        counted = summary.tally(CONVERSATION)

    assert counted.minutes == 6
    # And the calls are read off the same stretch, or the two halves of the
    # sentence would be counting different things.
    assert query.call_args_list[1].args[1][1] == evening[0]["created_at"]


def test_a_single_message_hours_later_is_a_sitting_of_its_own(_audit):
    """The shape the live log actually had: an afternoon of conversation, then
    one photo that evening. The gap is immediately before the newest message, so
    nothing is walked back over -- and where the count starts from decides
    everything. Written after a mutation survived that changed exactly that."""
    stamps = [
        {"created_at": STARTED},
        {"created_at": STARTED + timedelta(minutes=4)},
        {"created_at": STARTED + timedelta(hours=3)},
    ]

    with patch.object(audit_store, "query", side_effect=_answers(stamps, [])):
        counted = summary.tally(CONVERSATION)

    assert counted.minutes == 1  # the floor, not 180


def test_a_demo_with_ordinary_pauses_in_it_is_one_sitting(_audit):
    """People think, and look things up on their phone. A gap has to be long
    enough to mean they left."""
    stamps = [
        {"created_at": STARTED},
        {"created_at": STARTED + timedelta(minutes=9)},
        {"created_at": STARTED + timedelta(minutes=20)},
    ]

    with patch.object(audit_store, "query", side_effect=_answers(stamps, [])):
        assert summary.tally(CONVERSATION).minutes == 20


def test_without_an_audit_log_nothing_is_even_asked():
    """The numbers have one source. With it switched off the honest answer is
    none, not an estimate off the console's ring buffer.

    Asserting that no query was attempted is what separates the guard from the
    empty result the store would have returned anyway -- without this line,
    deleting the guard changed nothing any test could see."""
    with patch.object(type(audit_store), "enabled", property(lambda self: False)):
        with patch.object(audit_store, "query") as query:
            assert summary.tally(CONVERSATION) is None

    query.assert_not_called()


def test_the_message_is_written_in_all_three_languages(_audit):
    calls = [_call("erp_create_sales_order", '{"order_no": "SO-1"}')]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    def chinese(part: str) -> bool:
        return any("一" <= ch <= "鿿" for ch in part)

    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 3
    assert chinese(paragraphs[0])
    # Not `isascii`: every paragraph opens with the same emoji. What must not
    # leak across is Chinese text and Chinese punctuation -- a full-width bracket
    # in an English sentence reads as a font that failed to load, which is how
    # this test earned its keep the first time it was run.
    assert not chinese(paragraphs[1]) and "（" not in paragraphs[1]
    assert not chinese(paragraphs[2]) and "（" not in paragraphs[2]
    # WhatsApp refuses a text body over 4096 characters, and this is the longest
    # thing this project sends.
    assert len(text) <= 4096


def test_english_counts_one_thing_singular_and_two_plural(_audit):
    one = [_call("erp_create_sales_order", '{"order_no": "SO-1"}')]
    two = one + [_call("erp_create_sales_order", '{"order_no": "SO-2"}')]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), one)):
        first = summary.compose(summary.tally(CONVERSATION))
    with patch.object(audit_store, "query", side_effect=_answers(_messages(), two)):
        second = summary.compose(summary.tally(CONVERSATION))

    assert "1 real order placed" in first
    assert "2 real orders placed" in second


# -- the button on the console ------------------------------------------------


def _profile(phone: str = PHONE, name: str | None = "Kelvin Peng"):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    profile.display_name = name
    profile.conversation_id = CONVERSATION
    user_store.save(profile)
    return profile


def _post(body: dict | None = None):
    return client.post(
        "/console/demo-summary",
        json=body or {},
        headers={"X-Console-Token": TOKEN},
    )


def test_the_button_sends_the_summary_to_that_customers_phone(_audit, _console_token):
    """The acceptance criterion, from the operator's end: one press, and the
    message is on the phone in the customer's hand."""
    _profile()
    calls = [_call("erp_create_sales_order", '{"order_no": "SO-2026-00001"}')]
    rows = [{"key_id": PHONE, "conversation_id": CONVERSATION}]

    with patch.object(
        audit_store, "query", side_effect=[rows, *_answers(_messages(), calls)]
    ):
        with patch.object(notify, "send_now") as sent:
            response = _post()

    assert response.status_code == 200
    body = response.json()
    assert body["key_id"] == PHONE
    assert body["display_name"] == "Kelvin Peng"
    assert body["minutes"] == 8
    assert body["tool_calls"] == 1
    assert "SO-2026-00001" in body["text"]
    to, text = sent.call_args.args
    assert to == PHONE
    assert text == body["text"]


def test_the_answer_names_who_it_went_to(_audit, _console_token):
    """The live feed carries no customer on it, so the screen does not know who
    is being served and the backend takes the most recent conversation. With
    three customers in the room, this is the difference between right and lucky."""
    _profile()
    rows = [{"key_id": PHONE, "conversation_id": CONVERSATION}]

    with patch.object(audit_store, "query", side_effect=[rows, *_answers(_messages(), [])]):
        with patch.object(notify, "send_now"):
            response = _post()

    assert response.json()["conversation_id"] == CONVERSATION
    assert response.json()["key_id"] == PHONE


def test_a_named_customer_is_looked_up_however_their_number_was_typed(
    _audit, _console_token
):
    """The operator reads the number off a phone, not out of the database."""
    _profile()
    rows = [{"key_id": PHONE, "conversation_id": CONVERSATION}]

    with patch.object(audit_store, "query", side_effect=[rows, *_answers(_messages(), [])]) as q:
        with patch.object(notify, "send_now"):
            _post({"key_id": "+60 12-345 6789"})

    assert q.call_args_list[0].args[1] == (PHONE,)


def test_nothing_is_sent_for_a_customer_with_no_number_on_file(_audit, _console_token):
    """A record that expired, or somebody who reached us behind a username.
    Neither is a number Meta will deliver to."""
    profile = user_store.get_or_create("US.1349120865")
    profile.bot_id = "retail"
    user_store.save(profile)
    rows = [{"key_id": "US.1349120865", "conversation_id": CONVERSATION}]

    with patch.object(audit_store, "query", side_effect=[rows, *_answers(_messages(), [])]):
        with patch.object(notify, "send_now") as sent:
            response = _post()

    assert response.status_code == 409
    sent.assert_not_called()


def test_a_demo_nobody_recorded_is_refused_rather_than_faked(_audit, _console_token):
    with patch.object(audit_store, "query", return_value=[]):
        with patch.object(notify, "send_now") as sent:
            response = _post()

    assert response.status_code == 404
    sent.assert_not_called()


def test_the_button_is_behind_the_console_token(_console_token):
    """It puts a message on a customer's phone, which is more than the token was
    originally guarding. Worth its own test for exactly that reason."""
    with patch.object(notify, "send_now") as sent:
        response = client.post("/console/demo-summary", json={})

    assert response.status_code == 401
    sent.assert_not_called()


def test_only_the_back_offices_that_were_written_to_are_named(_audit):
    """The first real run said "written into a real ERP and CRM" on a demo where
    nothing had gone anywhere near the CRM -- a small lie in the one message
    whose entire job is being checkable."""
    calls = [_call("erp_create_sales_order", '{"order_no": "SO-1"}')]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "真实的 ERP，" in text
    assert "a real ERP," in text
    assert "CRM" not in text


def test_both_are_named_when_both_were_written_to(_audit):
    calls = [
        _call("erp_create_sales_order", '{"order_no": "SO-1"}'),
        _call("crm_create_lead"),
    ]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "真实的 ERP 和 CRM" in text
    assert "a real ERP and CRM" in text
    assert "ERP dan CRM sebenar" in text


def test_a_demo_that_only_read_things_claims_no_system_at_all(_audit):
    """A photo read and a voice note understood are worth saying and are not
    writes. "All of it written into a real ERP" would be untrue of both."""
    calls = [_call("image.download"), _call("voice.transcribe")]

    with patch.object(audit_store, "query", side_effect=_answers(_messages(), calls)):
        text = summary.compose(summary.tally(CONVERSATION))

    assert "ERP" not in text and "CRM" not in text
    assert "写进" not in text
    assert "听懂了 1 条语音" in text
    assert "留在您手机里" in text
