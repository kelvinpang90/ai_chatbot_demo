import json
from unittest.mock import patch

import anthropic
import httpx
from anthropic import beta_tool
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

from app.bots.registry import get_bot
from app.console import events
from app.services import llm, whatsapp
from app.services.user_store import UserProfile

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


def test_the_real_number_is_handed_over_rather_than_asked_for():
    """Task 32's point: WhatsApp already told us the number.

    The model has phone-keyed lookups in `crm_lookup_customer` and
    `erp_find_customer`; a prompt that does not say the number is verified leaves
    it asking a customer to type out the number it is reading them from.
    """
    volatile = llm.build_system_blocks(get_bot("retail"), _customer())[1]

    assert PHONE in volatile["text"]
    assert "asking them to type it out" in volatile["text"]


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


def test_each_tier_gets_the_model_its_bot_declares():
    assert llm.model_for(get_bot("retail")) == "claude-opus-5"  # flagship
    assert llm.model_for(get_bot("food")) == "claude-opus-5"  # deep vertical
    assert llm.model_for(get_bot("hotel")) == "claude-sonnet-5"  # light tier
    assert llm.model_for(get_bot("saas")) == "claude-sonnet-5"


def test_a_bot_that_declares_no_model_falls_back_to_the_setting():
    bot = get_bot("retail").model_copy(update={"model": None})

    assert llm.model_for(bot) == llm.settings.anthropic_model


def test_get_reply_returns_fallback_on_api_error():
    """Both paths, since task 11: `retail` runs the tool loop, `banking` does not.

    Testing only one of them would leave the other free to raise into the
    webhook, where a customer's message goes unanswered instead of getting an
    apology.
    """
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    plain = get_bot("banking")
    assert llm.get_tools(plain.id) == []
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
    assert kwargs["system"] == llm.build_system_blocks(bot, customer)
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
    assert kwargs["model"] == "claude-opus-5"
    # Tools render before system, so the one breakpoint covers them too.
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


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

    start, end = events.since(0)
    assert start.type == events.TOOL_START
    assert start.tool == "check_stock"
    assert start.input == {"sku": "EARBUD-01"}
    assert end.type == events.TOOL_END
    assert end.tool_use_id == start.tool_use_id
    assert "12 units in stock" in end.output
    assert end.status == "ok"
    assert end.duration_ms >= 0

    events.clear()


def test_a_bot_without_tools_says_nothing_to_the_console():
    bot = get_bot("retail")
    customer = _customer()
    events.clear()
    response = _assistant_message([BetaTextBlock(type="text", text="Hello!")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response):
            llm.get_reply(bot, customer, history=[])

    assert events.since(0) == []


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
