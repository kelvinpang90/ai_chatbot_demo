import base64
import json
from unittest.mock import patch

import anthropic
import httpx
import pytest
from anthropic import beta_tool
from anthropic.types.beta import (
    BetaCitationPageLocation,
    BetaMessage,
    BetaTextBlock,
    BetaToolUseBlock,
    BetaUsage,
)

from app.bots.registry import get_bot, list_bots
from app.console import events
from app.services import llm, whatsapp
from app.tools import registry as tool_registry
from app.services.user_store import UserProfile
from app.session_store import Message

PHONE = "60173948123"


def _customer(**fields) -> UserProfile:
    """A record of the shape the WhatsApp webhook now hands the model."""
    fields.setdefault("phone", PHONE)
    return UserProfile(key_id=fields["phone"] or "US.1349120865", **fields)


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


def test_system_blocks_carry_the_persona_and_the_customer_on_file():
    bot = get_bot("retail")

    stable, volatile = llm.build_system_blocks(bot, _customer(display_name="Lee Kok Hao"))

    assert bot.persona_prompt in stable["text"]
    assert "Chinese, English, or Malay" in stable["text"]
    assert PHONE in volatile["text"]
    assert "Lee Kok Hao" in volatile["text"]


def test_chinese_means_the_simplified_kind():
    """Found on a real phone: a customer typed simplified and got traditional
    back. Malaysia writes simplified, so that reads as a bot from somewhere
    else - which is the one impression a localised demo cannot afford."""
    stable = llm.build_system_blocks(get_bot("retail"), _customer())[0]

    assert "Simplified Chinese" in stable["text"]
    assert "Traditional" in stable["text"]


def test_the_real_number_is_handed_over_rather_than_asked_for():
    """Task 32's point: WhatsApp already told us the number.

    Since task 29.2 the lookups read it themselves rather than being handed it,
    so what the prompt has to prevent is no longer only the pointless question --
    it is the model trying to look an account up under some other number.
    """
    volatile = llm.build_system_blocks(get_bot("retail"), _customer())[1]

    assert PHONE in volatile["text"]
    assert "Never ask this customer to type their number out" in volatile["text"]
    assert "never try to look up an account under a different one" in volatile["text"]


def test_a_field_we_have_never_asked_about_is_left_out_rather_than_sent_as_null():
    """`"display_name": null` reads as "we looked and there is no name", which
    invites the model to stop asking. Absence says we simply have not asked."""
    volatile = llm.build_system_blocks(get_bot("retail"), _customer())[1]

    assert "display_name" not in volatile["text"]
    assert "null" not in volatile["text"]
    assert PHONE in volatile["text"]


def test_one_bot_cannot_read_the_notes_another_bot_took():
    """The free-form slot is keyed by bot: a budget confided to the property demo
    is not the retail assistant's to bring up."""
    customer = _customer(
        profile={"retail": {"delivery_address": "12 Jalan Ampang"}, "realestate": {"budget_rm": 900000}}
    )

    volatile = llm.build_system_blocks(get_bot("retail"), customer)[1]

    assert "Jalan Ampang" in volatile["text"]
    assert "900000" not in volatile["text"]


def test_a_visitor_with_no_number_is_told_to_be_a_stranger():
    """The web chat has no phone until task 33. An empty record would read as a
    customer we hold nothing on -- close enough to a known one to be greeted as
    one. Say plainly that nobody is on file instead."""
    volatile = llm.build_system_blocks(get_bot("retail"), None)[1]

    assert volatile["text"] == llm.ANONYMOUS_CUSTOMER_TEXT
    assert "no record on file" in volatile["text"]
    assert "{" not in volatile["text"]  # no record rendered, empty or otherwise


def test_only_the_stable_block_is_marked_for_caching():
    """The breakpoint must sit above the customer, or every visitor writes a new entry."""
    bot = get_bot("retail")
    stable, volatile = llm.build_system_blocks(bot, _customer())

    assert stable["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in volatile


def test_the_customer_never_leaks_into_the_cached_prefix():
    bot = get_bot("retail")

    stable_first = llm.build_system_blocks(bot, _customer(display_name="Tan Wei Ling"))[0]
    stable_second = llm.build_system_blocks(bot, UserProfile(key_id="60198704432", phone="60198704432"))[0]
    stable_anonymous = llm.build_system_blocks(bot, None)[0]

    # Byte-identical across customers, which is the whole point: one real number
    # per visitor must not throw away the cached prefix on every conversation.
    assert stable_first == stable_second == stable_anonymous
    assert "Tan Wei Ling" not in stable_first["text"]
    assert "60198704432" not in stable_first["text"]


def test_only_retail_names_a_model_so_the_setting_decides_the_rest():
    """Until 2026-09-14 every bot named its own model, which left ANTHROPIC_MODEL
    in .env doing nothing at all -- the one knob that looked like it chose the
    model chose nothing. Now it does, and a bot names a model of its own only
    when there is a reason it has to differ.

    Retail has one (2026-09-15, the owner's call): on Haiku scene 1 broke three
    ways in one run -- an empty turn, no CRM card after the order, and a guessed
    customer_id on the invoice -- and on Sonnet 5 it played through. A list here
    rather than a blanket rule, so the next bot to opt out has to say so."""
    from app.bots.registry import list_bots

    own_models = {"retail": "claude-sonnet-5"}
    for bot in list_bots():
        assert bot.model == own_models.get(bot.id), f"{bot.id} names {bot.model}"
        assert llm.model_for(bot) == (own_models.get(bot.id) or llm.settings.anthropic_model)


def test_the_model_a_fresh_deployment_gets_is_haiku():
    """Read off the field's declared default rather than off `settings`, which a
    .env on the machine running the tests would be free to override."""
    from app.config import Settings

    assert Settings.model_fields["anthropic_model"].default == "claude-haiku-4-5"


def test_a_bot_can_still_name_a_model_of_its_own():
    bot = get_bot("retail").model_copy(update={"model": "claude-opus-5"})

    assert llm.model_for(bot) == "claude-opus-5"


def test_a_bot_that_declares_no_model_falls_back_to_the_setting():
    bot = get_bot("retail").model_copy(update={"model": None})

    assert llm.model_for(bot) == llm.settings.anthropic_model


def test_get_reply_returns_fallback_on_api_error():
    """Both paths: one bot runs the tool loop, one does not.

    Testing only one of them would leave the other free to raise into the
    webhook, where a customer's message goes unanswered instead of getting an
    apology.

    The tool-less half is constructed rather than named. Every bot carries
    `request_human_help` since task 20 -- the light-tier ones are the least able
    to cope and so the most in need of a way out -- so there is no longer a bot
    that happens to have none. The plain path is still there and still has to
    work, which is what this half is about.
    """
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    # Any bot will do: `get_tools` is patched empty, which is what puts this
    # call on the plain path. It used to name `banking`, the one bot that really
    # had nothing to look anything up in, until task 30 retired it.
    plain = get_bot("hotel")
    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", side_effect=error):
            assert llm.get_reply(plain, _customer(), history=[]) == llm.FALLBACK_REPLY

    with_tools = get_bot("retail")
    assert llm.get_tools(with_tools.id)
    with patch.object(llm._client.beta.messages, "parse", side_effect=error):
        assert llm.get_reply(with_tools, _customer(), history=[]) == llm.FALLBACK_REPLY


def test_bot_without_tools_takes_the_plain_single_turn_path():
    """No tools still means the plain endpoint, never the beta one."""
    bot = get_bot("retail")
    customer = _customer()
    response = _assistant_message([BetaTextBlock(type="text", text="Hello!")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            with patch.object(llm._client.beta.messages, "parse") as mock_parse:
                reply = llm.get_reply(bot, customer, history=[])

    assert reply == "Hello!"
    mock_parse.assert_not_called()  # never touched the beta endpoint
    kwargs = mock_create.call_args.kwargs
    assert kwargs["model"] == llm.model_for(bot)
    assert kwargs["max_tokens"] == llm.MAX_REPLY_TOKENS
    # Not equal any more, and correctly so: taking retail's tools away is the
    # control arm, which appends TOOLS_WITHHELD to the volatile block. The
    # cached prefix is still untouched, which is what this test is about.
    expected = llm.build_system_blocks(bot, customer)
    assert kwargs["system"][0] == expected[0]
    assert kwargs["system"][-1]["text"].startswith(expected[-1]["text"])
    assert "tools" not in kwargs


def test_the_tool_path_uses_the_same_model_and_cached_system_blocks():
    bot = get_bot("retail")
    customer = _customer()

    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        return "12 units in stock"

    final = _assistant_message([BetaTextBlock(type="text", text="Hi")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(llm._client.beta.messages, "parse", return_value=final) as mock_parse:
            llm.get_reply(bot, customer, history=[])

    kwargs = mock_parse.call_args.kwargs
    assert kwargs["model"] == llm.model_for(bot)
    # Tools render before system, so the one breakpoint covers them too.
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def _tool_choice_sent_for(bot_id: str):
    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        return "12 units in stock"

    final = _assistant_message([BetaTextBlock(type="text", text="Hi")], "end_turn")
    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(llm._client.beta.messages, "parse", return_value=final) as mock_parse:
            llm.get_reply(get_bot(bot_id), _customer(), history=[])
    return mock_parse.call_args.kwargs.get("tool_choice")


def test_the_property_bot_is_held_to_one_tool_call_at_a_time():
    """Found on a real phone on 2026-09-14. A viewing was refused for being in
    the past, and in the same breath -- one response, two tool calls -- the model
    had already filed the CRM lead for it. The lead landed; the booking did not
    exist for another three seconds, and would never have existed if the retry
    had failed too. The tool's answer said to record the lead only once the
    viewing was saved, but a model calling both at once has not read that
    answer yet. Only making it wait does."""
    choice = _tool_choice_sent_for("realestate")

    assert choice == {"type": "auto", "disable_parallel_tool_use": True}


def test_the_restaurant_bot_is_held_to_one_tool_call_at_a_time():
    """Setting the cart and placing the order are one write that depends on
    another, the same shape as the property bot's booking and lead. A cart takes
    every dish in one call, so there is nothing to gain from parallel calls."""
    choice = _tool_choice_sent_for("food")

    assert choice == {"type": "auto", "disable_parallel_tool_use": True}


def test_a_bot_that_does_not_ask_for_it_keeps_parallel_tool_calls():
    """Retail looks stock up in three warehouses at once, and that is worth the
    speed. The rule is per bot because the hazard is per bot."""
    choice = _tool_choice_sent_for("retail")

    assert not (isinstance(choice, dict) and choice.get("disable_parallel_tool_use"))


def test_bot_with_tools_calls_the_tool_and_feeds_the_result_back():
    bot = get_bot("retail")
    customer = _customer()
    calls: list[str] = []

    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        calls.append(sku)
        return "12 units in stock"

    wants_tool = _assistant_message(
        [BetaToolUseBlock(type="tool_use", id="tu_1", name="check_stock", input={"sku": "EARBUD-01"})],
        "tool_use",
    )
    final = _assistant_message([BetaTextBlock(type="text", text="Yes, 12 left.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(
            llm._client.beta.messages, "parse", side_effect=[wants_tool, final]
        ) as mock_parse:
            reply = llm.get_reply(bot, customer, history=[])

    assert calls == ["EARBUD-01"]  # the tool actually ran
    assert reply == "Yes, 12 left."

    # The second call must carry the first turn plus the tool result, or the model
    # is answering without ever seeing what the tool returned.
    second_messages = mock_parse.call_args_list[1].kwargs["messages"]
    tool_results = [
        block
        for message in second_messages
        for block in (message["content"] if isinstance(message["content"], list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["tool_use_id"] == "tu_1"
    assert "12 units in stock" in str(tool_results[0]["content"])


def test_tool_loop_is_capped_so_a_demo_cannot_spin_forever():
    bot = get_bot("retail")
    customer = _customer()

    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        return "12 units in stock"

    never_satisfied = _assistant_message(
        [BetaToolUseBlock(type="tool_use", id="tu_1", name="check_stock", input={"sku": "X"})],
        "tool_use",
    )

    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(
            llm._client.beta.messages, "parse", return_value=never_satisfied
        ) as mock_parse:
            llm.get_reply(bot, customer, history=[])

    assert mock_parse.call_count == llm.MAX_TOOL_ITERATIONS


def test_each_tool_call_is_announced_to_the_console_before_and_after():
    bot = get_bot("retail")
    customer = _customer()
    events.clear()

    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        return "12 units in stock"

    wants_tool = _assistant_message(
        [BetaToolUseBlock(type="tool_use", id="tu_1", name="check_stock", input={"sku": "EARBUD-01"})],
        "tool_use",
    )
    final = _assistant_message([BetaTextBlock(type="text", text="Yes, 12 left.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(llm._client.beta.messages, "parse", side_effect=[wants_tool, final]):
            llm.get_reply(bot, customer, history=[])

    start, end = _tool_events()
    assert start.type == events.TOOL_START
    assert start.tool == "check_stock"
    assert start.input == {"sku": "EARBUD-01"}
    assert end.type == events.TOOL_END
    assert end.tool_use_id == start.tool_use_id
    assert "12 units in stock" in end.output
    assert end.status == "ok"
    assert end.duration_ms >= 0

    events.clear()


def test_a_bot_without_tools_shows_no_tool_calls_on_the_console():
    bot = get_bot("retail")
    customer = _customer()
    events.clear()
    response = _assistant_message([BetaTextBlock(type="text", text="Hello!")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response):
            llm.get_reply(bot, customer, history=[])

    assert _tool_events() == []

    events.clear()


def test_every_api_call_in_a_tool_loop_is_costed_not_just_the_last():
    """The console's running total is the whole point of the cost line.

    Counting only the message the reply came out of would put a fraction of what
    was actually spent on the screen -- and the deeper the tool loop, the bigger
    the lie.
    """
    bot = get_bot("retail")
    events.clear()

    @beta_tool
    def check_stock(sku: str) -> str:
        """Look up how many units of a SKU are on hand.

        Args:
            sku: The product code to look up.
        """
        return "12 units in stock"

    wants_tool = _assistant_message(
        [BetaToolUseBlock(type="tool_use", id="tu_1", name="check_stock", input={"sku": "X"})],
        "tool_use",
    )
    final = _assistant_message([BetaTextBlock(type="text", text="Yes, 12 left.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[check_stock]):
        with patch.object(llm._client.beta.messages, "parse", side_effect=[wants_tool, final]):
            llm.get_reply(bot, _customer(), history=[])

    usage = [e for e in events.since(0) if e.type == events.USAGE]
    assert len(usage) == 2  # one per API call, not one per reply
    assert all(e.cost_myr > 0 and e.model == llm.model_for(bot) for e in usage)

    events.clear()


def _tool_events() -> list:
    """The console minus the per-call cost lines, which every turn now emits."""
    return [e for e in events.since(0) if e.type != events.USAGE]


# -- a turn that did not finish is not an answer -------------------------------


def test_a_reply_cut_off_at_the_token_ceiling_becomes_the_fallback():
    """What actually happened: the turn spent all 512 tokens inside a tool call
    and produced no text, and the empty string went to WhatsApp as a reply."""
    bot = get_bot("retail")
    truncated = _assistant_message([], "max_tokens")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=truncated):
            assert llm.get_reply(bot, _customer(), history=[]) == llm.FALLBACK_REPLY


def test_a_sentence_cut_off_mid_word_is_not_sent_either():
    """Half an answer is worse than an apology when the half that survived is a
    price: `RM 26` for `RM 263.67` is a number the customer will hold you to."""
    bot = get_bot("retail")
    truncated = _assistant_message([BetaTextBlock(type="text", text="That comes to RM 26")], "max_tokens")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=truncated):
            assert llm.get_reply(bot, _customer(), history=[]) == llm.FALLBACK_REPLY


def test_a_turn_that_produced_no_text_becomes_the_fallback():
    bot = get_bot("retail")
    silent = _assistant_message([], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=silent):
            assert llm.get_reply(bot, _customer(), history=[]) == llm.FALLBACK_REPLY


def test_get_reply_never_returns_something_whatsapp_would_refuse():
    """The contract the router leans on when it builds the message before
    committing the turn to history."""
    bot = get_bot("retail")
    for content, stop in (([], "end_turn"), ([], "max_tokens"), ([BetaTextBlock(type="text", text="  ")], "end_turn")):
        with patch.object(llm, "get_tools", return_value=[]):
            with patch.object(llm._client.messages, "create", return_value=_assistant_message(content, stop)):
                reply = llm.get_reply(bot, _customer(), history=[])
        assert reply.strip()
        whatsapp.build_text_message("60123456789", reply)  # would raise if unsendable


def test_the_token_ceiling_leaves_room_for_a_reply_and_a_tool_call():
    """512 was the ceiling a turn hit while writing tool arguments, leaving no
    tokens for any text. The number is not sacred; being clear of that is."""
    assert llm.MAX_REPLY_TOKENS >= 1024


# -- a customer who has hidden their phone number ------------------------------


def test_a_customer_with_no_number_is_not_told_they_have_one():
    """Meta lets a customer hide their number behind a username. Left to guess,
    the model reaches for the one identifier it can see and passes a handle to a
    phone lookup, which finds nothing -- and reads back as "you are not a
    customer" to somebody who is."""
    hidden = UserProfile(key_id="US.1349120865", user_id="US.1349120865", username="kelvin.p")

    volatile = llm.build_system_blocks(get_bot("retail"), hidden)[1]

    assert "kelvin.p" in volatile["text"]
    assert "phone" not in json.loads(volatile["text"].split("\n")[1])
    assert volatile["text"].count(llm.NO_PHONE_ON_FILE) == 1
    assert llm.PHONE_ON_FILE not in volatile["text"]


def test_a_customer_with_a_number_still_gets_the_lookup_instruction():
    volatile = llm.build_system_blocks(get_bot("retail"), _customer())[1]

    assert llm.PHONE_ON_FILE in volatile["text"]
    assert llm.NO_PHONE_ON_FILE not in volatile["text"]


def test_a_username_travels_with_the_record():
    volatile = llm.build_system_blocks(get_bot("retail"), _customer(username="kelvin.p"))[1]

    assert "kelvin.p" in volatile["text"]


def test_a_customer_with_no_number_is_helped_rather_than_stalled_or_believed():
    """What a hidden number costs, and what it must not cost (task 29.2).

    The old prompt told the model to ask for a number and then use it "exactly as
    if the channel had supplied it", which is precisely the move that let anyone
    read out anyone's number. The tools refuse that now, so the prompt has to
    stop asking for something it cannot use -- without turning into a bot that
    helps nobody it cannot identify.
    """
    hidden = UserProfile(key_id="US.1349120865", user_id="US.1349120865", username="kelvin.p")

    text = llm.build_system_blocks(get_bot("retail"), hidden)[1]["text"]

    assert "as if the channel had supplied it" not in text
    # Still their customer: everything that needs no account still works.
    assert "help with everything that needs no account" in text
    # And the way out for what does: a number to call back on, and a colleague.
    assert "a colleague can call them back" in text


def test_a_customer_who_gave_a_number_is_not_asked_for_it_again():
    text = llm.build_system_blocks(get_bot("retail"), _customer())[1]["text"]

    assert "ask for a number a colleague can call them back on" not in text
    assert llm.PHONE_ON_FILE in text


def test_the_control_switch_takes_even_a_tooled_bot_down_the_plain_path():
    """Task 12.2, at the layer where the claim is actually settled.

    The endpoints and the console feed are worth their own tests, but neither
    proves the thing the demo rests on: that with the switch thrown, the bot with
    the fullest tool belt in the catalogue reaches the model with no tools at all
    and answers out of its prompt. It never touches the beta endpoint, so it
    cannot call anything even if it wanted to -- and the console stays empty,
    which is the half of the comparison the customer is looking at.
    """
    bot = get_bot("retail")
    assert tool_registry.get_tools(bot.id)  # the switch has something to take away
    events.clear()
    response = _assistant_message([BetaTextBlock(type="text", text="有货的，库存充足。")], "end_turn")

    tool_registry.set_tools_enabled(False)
    try:
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            with patch.object(llm._client.beta.messages, "parse") as mock_parse:
                reply = llm.get_reply(bot, _customer(), history=[])
    finally:
        tool_registry.set_tools_enabled(True)

    assert reply == "有货的，库存充足。"
    mock_parse.assert_not_called()
    assert "tools" not in mock_create.call_args.kwargs
    assert _tool_events() == []

    events.clear()


# -- photos (task 14) ----------------------------------------------------------
#
# A picture is the one thing that cannot become text on the way in, so unlike a
# voice note it does reach `get_reply`. What these guard is where it goes: into
# this turn's request and nowhere else -- not into a message of its own, and not
# into the history that is replayed and paid for on every turn after this one.

PNG_BYTES = b"\x89PNG\r\n\x1a\n-pretend-a-photo"


def test_a_photo_rides_on_this_turns_message_with_the_caption_after_it():
    """The acceptance criterion: the bytes reach the model, in the same message
    as the words that came with them, image first."""
    bot = get_bot("retail")
    history = [Message(role="user", content="[photo] is this covered by warranty?")]
    response = _assistant_message([BetaTextBlock(type="text", text="Let me look.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(
                bot, _customer(), history, image=llm.Image(PNG_BYTES, media_type="image/png")
            )

    content = mock_create.call_args.kwargs["messages"][-1]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.b64encode(PNG_BYTES).decode("ascii"),
    }
    assert content[1]["text"] == "[photo] is this covered by warranty?"


def test_a_photo_reaches_a_bot_that_has_tools_as_well():
    """A bot with tools never touches `messages.create`: it goes to the beta tool
    runner, which validates a request of its own. That is the path the flagship
    retail bot takes and therefore the one scene 2a runs on, and it was an
    assumption rather than an assertion until a live call proved it out."""
    bot = get_bot("retail")
    history = [Message(role="user", content="[photo] what model is this?")]

    @beta_tool
    def erp_search_sku(query: str) -> str:
        """Search the product catalogue.

        Args:
            query: The name or code to look for.
        """
        return "no results"

    final = _assistant_message([BetaTextBlock(type="text", text="SP-1001.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[erp_search_sku]):
        with patch.object(llm._client.beta.messages, "parse", return_value=final) as mock_parse:
            llm.get_reply(
                bot, _customer(), history, image=llm.Image(PNG_BYTES, media_type="image/png")
            )

    content = mock_parse.call_args.kwargs["messages"][-1]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/png"


def test_only_the_newest_turn_carries_the_picture():
    """An earlier photo is gone by the next turn -- that is the whole point of
    keeping it out of the history -- so nothing below the last message may be
    rewritten into blocks."""
    bot = get_bot("retail")
    history = [
        Message(role="user", content="[photo] what is this?"),
        Message(role="assistant", content="A pair of earbuds."),
        Message(role="user", content="how much?"),
    ]
    response = _assistant_message([BetaTextBlock(type="text", text="RM 199.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(
                bot, _customer(), history, image=llm.Image(PNG_BYTES, media_type="image/png")
            )

    sent = mock_create.call_args.kwargs["messages"]
    assert sent[0]["content"] == "[photo] what is this?"
    assert sent[1]["content"] == "A pair of earbuds."
    assert isinstance(sent[2]["content"], list)


def test_a_turn_with_no_photo_still_sends_plain_strings():
    """Every other message in this project comes through here. The image path has
    to stay invisible to them."""
    bot = get_bot("retail")
    history = [Message(role="user", content="do you deliver to Penang?")]
    response = _assistant_message([BetaTextBlock(type="text", text="We do.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history)

    assert mock_create.call_args.kwargs["messages"] == [
        {"role": "user", "content": "do you deliver to Penang?"}
    ]


def test_the_media_type_is_the_bare_type_without_the_headers_parameters():
    assert llm.image_media_type("image/jpeg") == "image/jpeg"
    assert llm.image_media_type("image/JPEG; charset=binary") == "image/jpeg"


def test_a_format_the_model_cannot_read_is_refused_here_rather_than_by_the_api():
    """Anything outside the four types is a 400 from Anthropic that arrives only
    after the customer has already waited for the download."""
    assert llm.image_media_type("image/tiff") is None
    assert llm.image_media_type("application/pdf") is None
    assert llm.image_media_type("") is None


# -- documents (task 15.1) -----------------------------------------------------
#
# A PDF is the one attachment that outlives its turn, so what these guard is
# where it goes back to on every turn after the first: onto the exact line the
# router left in the history, not onto the newest message. That is what keeps it
# cacheable, and it is what makes it expire on its own once the line rolls away.

PDF_BYTES = b"%PDF-1.7-pretend-a-price-list"
PDF_MARKER = "[document] price-list.pdf what does the deluxe room cost?"


def _pdf(marker: str = PDF_MARKER) -> llm.Document:
    return llm.Document(data=PDF_BYTES, filename="price-list.pdf", marker=marker)


def _cited(text: str, page: int, quote: str, title: str = "price-list.pdf") -> BetaTextBlock:
    return BetaTextBlock(
        type="text",
        text=text,
        citations=[
            BetaCitationPageLocation(
                type="page_location",
                cited_text=quote,
                document_index=0,
                document_title=title,
                start_page_number=page,
                end_page_number=page + 1,
            )
        ],
    )


def test_a_pdf_reaches_the_model_as_a_document_with_citations_turned_on():
    """The acceptance criterion. Citations are what make the answer checkable:
    without them a page number in the reply would be the model's own invention,
    which is the one thing this demo exists to disprove."""
    bot = get_bot("retail")
    history = [Message(role="user", content=PDF_MARKER)]
    response = _assistant_message([BetaTextBlock(type="text", text="RM 320.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    content = mock_create.call_args.kwargs["messages"][-1]["content"]
    assert [block["type"] for block in content] == ["document", "text"]
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": base64.b64encode(PDF_BYTES).decode("ascii"),
    }
    assert content[0]["citations"] == {"enabled": True}
    assert content[0]["title"] == "price-list.pdf"
    assert content[1]["text"] == PDF_MARKER


def test_the_pdf_is_cached_rather_than_re_read_on_every_follow_up_question():
    """It is re-sent on every turn of the conversation that follows it, and a
    twenty-page file is tens of thousands of input tokens. Pinned where it
    arrived, the prefix stops changing and the pages are charged once."""
    bot = get_bot("retail")
    history = [Message(role="user", content=PDF_MARKER)]
    response = _assistant_message([BetaTextBlock(type="text", text="RM 320.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    document = mock_create.call_args.kwargs["messages"][-1]["content"][0]
    assert document["cache_control"] == {"type": "ephemeral"}


def test_the_pdf_goes_back_where_it_arrived_not_onto_the_newest_turn():
    """Two questions in, the file is three messages up. Moving it down to the
    latest turn would change the prefix every time and throw the cache away -- and
    would tell the model the customer had just sent it again."""
    bot = get_bot("retail")
    history = [
        Message(role="user", content=PDF_MARKER),
        Message(role="assistant", content="RM 320 a night."),
        Message(role="user", content="and the family room?"),
    ]
    response = _assistant_message([BetaTextBlock(type="text", text="RM 480.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    sent = mock_create.call_args.kwargs["messages"]
    assert [block["type"] for block in sent[0]["content"]] == ["document", "text"]
    assert sent[2]["content"] == "and the family room?"


def test_a_pdf_whose_line_has_rolled_out_of_the_history_is_simply_not_sent():
    """The history is a rolling window. Once the line the file arrived as has
    gone, there is nothing to hang it on -- and a file nobody has mentioned in
    forty messages is not what the current question is about."""
    bot = get_bot("retail")
    history = [Message(role="user", content="do you have parking?")]
    response = _assistant_message([BetaTextBlock(type="text", text="We do.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    assert mock_create.call_args.kwargs["messages"] == [
        {"role": "user", "content": "do you have parking?"}
    ]


def test_a_pdf_reaches_a_bot_that_has_tools_as_well():
    """The flagship bot has tools, so it never touches `messages.create` -- it
    goes to the beta tool runner, which validates a request of its own. Task 14
    learned this the hard way about images."""
    bot = get_bot("retail")
    history = [Message(role="user", content=PDF_MARKER)]

    @beta_tool
    def erp_search_sku(query: str) -> str:
        """Search the product catalogue.

        Args:
            query: The name or code to look for.
        """
        return "no results"

    final = _assistant_message([BetaTextBlock(type="text", text="RM 320.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[erp_search_sku]):
        with patch.object(llm._client.beta.messages, "parse", return_value=final) as mock_parse:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    content = mock_parse.call_args.kwargs["messages"][-1]["content"]
    assert [block["type"] for block in content] == ["document", "text"]


def test_a_photo_and_a_file_already_on_the_table_can_both_be_in_one_request():
    """They attach to different messages and must not overwrite one another: the
    customer photographing something while their price list is still open is an
    ordinary turn, not a special case."""
    bot = get_bot("retail")
    history = [
        Message(role="user", content=PDF_MARKER),
        Message(role="assistant", content="RM 320 a night."),
        Message(role="user", content="[photo] is this the same room?"),
    ]
    response = _assistant_message([BetaTextBlock(type="text", text="It is.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(
                bot,
                _customer(),
                history,
                image=llm.Image(PNG_BYTES, media_type="image/png"),
                document=_pdf(),
            )

    sent = mock_create.call_args.kwargs["messages"]
    assert [block["type"] for block in sent[0]["content"]] == ["document", "text"]
    assert [block["type"] for block in sent[2]["content"]] == ["image", "text"]


def test_the_answer_comes_back_with_the_page_it_was_read_off():
    """Scene 2b as the customer sees it: the answer, and under it the file and
    the page to go and check it against.

    Page numbers and no quotation, which is less than the scene was written
    hoping for -- `_sources` has why, and a live probe on 2026-09-11 has the
    measurements behind it."""
    bot = get_bot("retail")
    response = _assistant_message(
        [_cited("The deluxe room is RM 320 a night.", 4, "Deluxe  \n  RM 320 / night")],
        "end_turn",
    )

    reply = llm._reply_text(bot, response)

    assert reply == "The deluxe room is RM 320 a night.\n\n\U0001F4C4 price-list.pdf · p.4"


def test_a_page_cited_twice_is_named_once_and_the_list_does_not_run_away():
    """The footnote is evidence, not the answer. An answer drawn off eight pages
    is the model working; a reply ending in a paragraph of page numbers is not a
    chat message, so the list is cut and says that it was."""
    bot = get_bot("retail")
    response = _assistant_message(
        [
            _cited("First.", 2, "page two"),
            _cited(" Second.", 2, "a different sentence on the same page"),
            *[_cited(f" {n}.", n, f"page {n}") for n in range(3, 9)],
        ],
        "end_turn",
    )

    reply = llm._reply_text(bot, response)

    assert reply.splitlines()[-1] == (
        "\U0001F4C4 price-list.pdf · p.2, p.3, p.4, p.5, p.6, …"
    )
    assert reply.startswith("First. Second. 3. 4. 5. 6. 7. 8.")


def test_a_citation_that_spans_a_page_break_names_both_pages():
    """`end_page_number` is exclusive. Reading it as a page number would name a
    page the answer was not on, which is worse than naming none."""
    bot = get_bot("retail")
    block = BetaTextBlock(
        type="text",
        text="Breakfast runs until 10:30.",
        citations=[
            BetaCitationPageLocation(
                type="page_location",
                cited_text="...",
                document_index=0,
                document_title="price-list.pdf",
                start_page_number=6,
                end_page_number=8,
            )
        ],
    )

    reply = llm._reply_text(bot, _assistant_message([block], "end_turn"))

    assert reply.splitlines()[-1] == "\U0001F4C4 price-list.pdf · p.6, p.7"


def test_a_reply_with_nothing_cited_is_sent_exactly_as_written():
    """Every reply in this project that is not about a document, and the honest
    answer to a question the file does not cover: no citations, no footnote."""
    bot = get_bot("retail")
    response = _assistant_message(
        [BetaTextBlock(type="text", text="That is not in the document you sent.")], "end_turn"
    )

    assert llm._reply_text(bot, response) == "That is not in the document you sent."


def test_only_a_pdf_is_a_document_the_model_can_be_handed():
    """A .docx is a 400 from Anthropic that arrives after the customer has
    already waited out the download."""
    assert llm.document_media_type("application/pdf") == "application/pdf"
    assert llm.document_media_type("application/PDF; charset=binary") == "application/pdf"
    assert (
        llm.document_media_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        is None
    )
    assert llm.document_media_type("image/jpeg") is None
    assert llm.document_media_type("") is None


def test_the_footnote_is_sent_but_not_remembered():
    """Caught by a live probe on 2026-09-11, not by anything written up front:
    the model, shown its own last answer signed off with a page reference, wrote
    one of its own on the next turn -- a page number off its previous message
    rather than off the file -- and ours was appended under it. So what is
    remembered is what the model actually wrote."""
    assert llm.without_sources(
        "The deluxe room is RM 320 a night.\n\n\U0001F4C4 price-list.pdf · p.4"
    ) == "The deluxe room is RM 320 a night."


def test_a_reply_that_was_never_footnoted_is_remembered_whole():
    """Every reply in this project that is not about a document. Nothing to cut,
    and cutting anything would be losing the message."""
    assert llm.without_sources("We close at 6pm.") == "We close at 6pm."
    assert llm.without_sources("") == ""


def test_an_answer_that_mentions_a_page_itself_is_left_alone():
    """The cut is made at the seam `_reply_text` joined, not at the first page
    number in the text: the model talking about page 4 is still the model."""
    written = "Page 4 covers the warranty, and I've quoted from it above."

    assert llm.without_sources(written) == written


# -- what a real phone found (2026-09-12) --------------------------------------
#
# Four things the suite was green through. Each of these is here because it
# happened in front of a person holding a phone, not because it was imagined.


def test_a_file_the_customer_sent_is_never_outside_this_business():
    """The one that mattered. A customer sent the retail bot their own car
    rental quotation and asked what the annual cost was; the bot said "that is
    not our business" and never read it -- correctly, by `NEVER_INVENT`, and
    fatally, because "send us your own file" is the whole of scene 2b."""
    volatile = llm.build_system_blocks(get_bot("retail"), _customer(), has_document=True)[1]

    assert llm.DOCUMENT_IN_HAND in volatile["text"]
    assert "never \"outside this business\"" in volatile["text"]


def test_nothing_is_said_about_a_file_on_a_turn_without_one():
    """Which is nearly every turn. A standing instruction to answer from a file
    would be an instruction about a file that is not there."""
    volatile = llm.build_system_blocks(get_bot("retail"), _customer())[1]

    assert llm.DOCUMENT_IN_HAND not in volatile["text"]


def test_the_file_note_stays_out_of_the_cached_half():
    """It is true of this turn, not of this bot. Above the breakpoint it would
    both be wrong on every other turn and throw the cached prefix away each time
    a file arrived."""
    stable, volatile = llm.build_system_blocks(get_bot("retail"), _customer(), has_document=True)

    assert llm.DOCUMENT_IN_HAND not in stable["text"]
    assert llm.DOCUMENT_IN_HAND in volatile["text"]
    # Byte-identical to the prefix on a turn with no file, which is what "the
    # cache survives a document" means.
    assert stable == llm.build_system_blocks(get_bot("retail"), _customer())[0]


def test_reading_their_price_list_is_not_stocking_it():
    """The opposite error, and the easier one to fall into once the first is
    fixed: a bot that has just read a quotation must not start selling from it."""
    volatile = llm.build_system_blocks(get_bot("retail"), _customer(), has_document=True)[1]

    assert "not this business's stock" in volatile["text"]
    assert "never place an order for something that only exists in their document" in (
        volatile["text"]
    )


def test_a_document_turn_carries_the_note_as_well_as_the_file():
    """Attached and announced. The attachment puts the file in front of the
    model; the note is what stops it being handed back unread."""
    bot = get_bot("retail")
    history = [Message(role="user", content=PDF_MARKER)]
    response = _assistant_message([BetaTextBlock(type="text", text="RM 320.")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history, document=_pdf())

    system = mock_create.call_args.kwargs["system"]
    assert llm.DOCUMENT_IN_HAND in system[1]["text"]


@pytest.mark.parametrize("bot_id", [bot.id for bot in list_bots()])
def test_a_request_to_see_or_delete_their_data_goes_to_a_person(bot_id):
    """Task 29.3: the public privacy page tells customers to ask here.

    The page at /privacy has no self-serve button behind it - it says to message
    the demo number and that a colleague will follow it up - so the instruction
    has to hold whichever bot the customer happens to be talking to, and it lives
    in the cached prefix every bot shares for exactly that reason. Nothing these
    bots can call deletes anything, which makes "done, I've removed it" the one
    answer that would turn the published page into a false promise.
    """
    bot = get_bot(bot_id)

    stable = llm.build_system_blocks(bot, _customer())[0]

    assert llm.PERSONAL_DATA_REQUESTS in stable["text"]
    # The way out it names has to be a tool this bot actually has.
    assert "request_human_help" in bot.tools


def test_the_bot_is_not_left_room_to_say_the_data_is_gone():
    """The failure mode worth naming: a reassuring bot is a lying bot here."""
    text = llm.PERSONAL_DATA_REQUESTS

    assert "Never say the data has been deleted" in text
    assert "never promise when" in text


# -- the control arm's prompt (task 12.2, fixed 2026-09-16) --------------------
#
# Found on a real phone, 2026-09-16, running section six of the checklist: with
# the switch thrown, retail answered "Sony 那个 earbuds 多少钱" with the literal
# text `[Tool: erp_find_customer]`. Nothing in this repository writes that
# string -- the model wrote it, because the switch takes the tools away and
# leaves the prompt that orders it to call them. It was told every fact must
# come from a tool, given no tools, and did the only thing left: it acted the
# call out in words, and the customer saw an internal tool name.
#
# The control arm is meant to show a bot that answers confidently off the top of
# its head. A leaked tool name is not that; it is the demo showing its wiring.


def test_the_switched_off_bot_is_told_it_has_no_tools():
    """The repro, at the layer where it is decided: with the switch thrown, the
    prompt has to say so, or the persona's tool instructions are the only thing
    the model has left to follow."""
    bot = get_bot("retail")
    assert bot.tools  # the switch has something to take away
    response = _assistant_message([BetaTextBlock(type="text", text="RM 320 左右。")], "end_turn")

    tool_registry.set_tools_enabled(False)
    try:
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            llm.get_reply(bot, _customer(), history=[])
    finally:
        tool_registry.set_tools_enabled(True)

    system = mock_create.call_args.kwargs["system"]
    assert llm.TOOLS_WITHHELD in system[-1]["text"]


def test_the_switched_off_prompt_forbids_acting_a_call_out_in_words():
    """The specific shape that reached a customer's phone."""
    assert "[Tool:" in llm.TOOLS_WITHHELD
    assert "never" in llm.TOOLS_WITHHELD.lower()


def test_a_bot_with_its_tools_is_not_told_it_has_none():
    """The other half: this paragraph must not ride along on an ordinary turn,
    where it would talk the model out of the tools it does have."""
    bot = get_bot("retail")
    captured = {}

    def _capture(bot_, model, system, messages, tools):
        captured["system"] = system
        return _assistant_message([BetaTextBlock(type="text", text="ok")], "end_turn")

    with patch.object(llm, "_reply_with_tools", side_effect=_capture):
        llm.get_reply(bot, _customer(), history=[])

    assert llm.TOOLS_WITHHELD not in captured["system"][-1]["text"]
