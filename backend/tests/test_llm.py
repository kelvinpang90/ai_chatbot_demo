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


def test_build_system_prompt_includes_persona_and_identity_data():
    bot = get_bot("retail")
    identity = bot.identities[0]

    prompt = llm.build_system_prompt(bot, identity)

    assert bot.persona_prompt in prompt
    assert identity.profile["customer_name"] in prompt
    assert "Chinese, English, or Malay" in prompt


def test_get_reply_returns_fallback_on_api_error():
    bot = get_bot("retail")
    identity = bot.identities[0]
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    with patch.object(llm._client.messages, "create", side_effect=error):
        reply = llm.get_reply(bot, identity, history=[])

    assert reply == llm.FALLBACK_REPLY


def test_bot_without_tools_takes_the_original_single_turn_path():
    """The regression safety line: no tools means the same endpoint, same parameters."""
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
    assert kwargs["model"] == llm.settings.anthropic_model
    assert kwargs["max_tokens"] == llm.MAX_REPLY_TOKENS
    assert kwargs["system"] == llm.build_system_prompt(bot, identity)
    assert "tools" not in kwargs


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
