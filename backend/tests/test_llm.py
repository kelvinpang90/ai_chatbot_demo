from unittest.mock import patch

import anthropic
import httpx
from anthropic import beta_tool
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

from app.bots.registry import get_bot
from app.console import events
from app.services import llm


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


def test_system_blocks_carry_the_persona_and_the_identity():
    bot = get_bot("retail")
    identity = bot.identities[0]

    stable, volatile = llm.build_system_blocks(bot, identity)

    assert bot.persona_prompt in stable["text"]
    assert "Chinese, English, or Malay" in stable["text"]
    assert identity.profile["customer_name"] in volatile["text"]


def test_only_the_stable_block_is_marked_for_caching():
    """The breakpoint must sit above the identity, or every visitor writes a new entry."""
    bot = get_bot("retail")
    stable, volatile = llm.build_system_blocks(bot, bot.identities[0])

    assert stable["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in volatile


def test_the_identity_never_leaks_into_the_cached_prefix():
    bot = get_bot("retail")
    first, second = bot.identities[0], bot.identities[1]

    stable_first = llm.build_system_blocks(bot, first)[0]
    stable_second = llm.build_system_blocks(bot, second)[0]

    # Byte-identical across identities, which is the whole point: switching who is
    # talking must not throw away the cached prefix.
    assert stable_first == stable_second
    assert first.profile["customer_name"] not in stable_first["text"]


def test_each_tier_gets_the_model_its_bot_declares():
    assert llm.model_for(get_bot("retail")) == "claude-opus-5"  # flagship
    assert llm.model_for(get_bot("food")) == "claude-opus-5"  # deep vertical
    assert llm.model_for(get_bot("hotel")) == "claude-sonnet-5"  # light tier
    assert llm.model_for(get_bot("saas")) == "claude-sonnet-5"


def test_a_bot_that_declares_no_model_falls_back_to_the_setting():
    bot = get_bot("retail").model_copy(update={"model": None})

    assert llm.model_for(bot) == llm.settings.anthropic_model


def test_get_reply_returns_fallback_on_api_error():
    bot = get_bot("retail")
    identity = bot.identities[0]
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    with patch.object(llm._client.messages, "create", side_effect=error):
        reply = llm.get_reply(bot, identity, history=[])

    assert reply == llm.FALLBACK_REPLY


def test_bot_without_tools_takes_the_plain_single_turn_path():
    """No tools still means the plain endpoint, never the beta one."""
    bot = get_bot("retail")
    identity = bot.identities[0]
    response = _assistant_message([BetaTextBlock(type="text", text="Hello!")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response) as mock_create:
            with patch.object(llm._client.beta.messages, "parse") as mock_parse:
                reply = llm.get_reply(bot, identity, history=[])

    assert reply == "Hello!"
    mock_parse.assert_not_called()  # never touched the beta endpoint
    kwargs = mock_create.call_args.kwargs
    assert kwargs["model"] == llm.model_for(bot)
    assert kwargs["max_tokens"] == llm.MAX_REPLY_TOKENS
    assert kwargs["system"] == llm.build_system_blocks(bot, identity)
    assert "tools" not in kwargs


def test_the_tool_path_uses_the_same_model_and_cached_system_blocks():
    bot = get_bot("retail")
    identity = bot.identities[0]

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
            llm.get_reply(bot, identity, history=[])

    kwargs = mock_parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    # Tools render before system, so the one breakpoint covers them too.
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_bot_with_tools_calls_the_tool_and_feeds_the_result_back():
    bot = get_bot("retail")
    identity = bot.identities[0]
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
            reply = llm.get_reply(bot, identity, history=[])

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
    identity = bot.identities[0]

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
            llm.get_reply(bot, identity, history=[])

    assert mock_parse.call_count == llm.MAX_TOOL_ITERATIONS


def test_each_tool_call_is_announced_to_the_console_before_and_after():
    bot = get_bot("retail")
    identity = bot.identities[0]
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
            llm.get_reply(bot, identity, history=[])

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
    identity = bot.identities[0]
    events.clear()
    response = _assistant_message([BetaTextBlock(type="text", text="Hello!")], "end_turn")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", return_value=response):
            llm.get_reply(bot, identity, history=[])

    assert events.since(0) == []
