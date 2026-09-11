import base64
import json
from unittest.mock import patch

import anthropic
import httpx
from anthropic import beta_tool
from anthropic.types.beta import (
    BetaCitationPageLocation,
    BetaMessage,
    BetaTextBlock,
    BetaToolUseBlock,
    BetaUsage,
)

from app.bots.registry import get_bot
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


def test_a_customer_with_no_number_is_asked_for_one_rather_than_stalled():
    """Everything the back offices can do is keyed on a phone number, so a
    customer who has hidden theirs has to be asked -- early, and without the bot
    holding the conversation hostage until they answer."""
    hidden = UserProfile(key_id="US.1349120865", user_id="US.1349120865", username="kelvin.p")

    text = llm.build_system_blocks(get_bot("retail"), hidden)[1]["text"]

    assert "Ask them for their phone number early" in text
    # Asking is not the same as refusing to help until they answer.
    assert "carry on helping while you wait" in text
    assert "do not refuse to answer questions until they give it" in text


def test_a_customer_who_gave_a_number_is_not_asked_for_it_again():
    text = llm.build_system_blocks(get_bot("retail"), _customer())[1]["text"]

    assert "Ask them for their phone number early" not in text
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
