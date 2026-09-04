import json

import pytest

from app.bots import registry
from app.tools import registry as tool_registry


ALL_BOT_IDS = {"retail", "hotel", "banking", "food", "realestate", "saas"}


def test_all_bots_load_without_error():
    bots = registry.list_bots()
    ids = {bot.id for bot in bots}
    assert ids == ALL_BOT_IDS


def test_each_bot_has_localized_name_and_quick_questions():
    for bot in registry.list_bots():
        assert bot.name.zh and bot.name.en and bot.name.ms
        assert bot.description.zh and bot.description.en and bot.description.ms
        assert bot.disclaimer.zh and bot.disclaimer.en and bot.disclaimer.ms
        assert 3 <= len(bot.quick_questions) <= 4


def test_get_bot_returns_none_for_unknown_id():
    assert registry.get_bot("does-not-exist") is None


def test_no_bot_still_carries_a_pick_your_own_identity_menu():
    """Task 32: the phone number is the identity, so the menu of pretend ones is
    gone -- from the model, from the JSON, and from the loader.

    A leftover `identities` key would load silently (pydantic drops what the
    model does not declare) and read as still supported by whoever opens the
    file next.
    """
    assert not hasattr(registry, "Identity")
    assert not hasattr(registry, "get_identity")
    for path in sorted(registry.DATA_DIR.glob("*.json")):
        assert "identities" not in json.loads(path.read_text(encoding="utf-8")), path.name
        assert not hasattr(registry.get_bot(path.stem), "identities")


def test_every_tool_a_bot_declares_actually_exists():
    """A name that resolves to nothing is a bot that quietly makes things up."""
    for bot in registry.list_bots():
        for name in bot.tools:
            assert name in tool_registry.CATALOGUE


def test_retail_is_wired_to_the_erp_and_crm_it_demonstrates():
    retail = registry.get_bot("retail")
    assert retail is not None
    assert set(retail.tools) == {
        "erp_search_sku",
        "erp_get_inventory",
        "erp_find_customer",
        "erp_list_orders",
        "erp_create_sales_order",
        "erp_generate_einvoice",
        "crm_lookup_customer",
        "crm_create_lead",
    }
    assert [tool.name for tool in tool_registry.get_tools("retail")] == retail.tools


def test_retail_no_longer_carries_the_answers_it_is_supposed_to_look_up():
    """The static catalogue and the fake order history were the thing to remove.

    Left in place they are not merely redundant: the model reads them, answers
    from them, and the console shows no tool call at all -- which is the one
    claim this whole demo is making.
    """
    retail = registry.get_bot("retail")
    assert retail is not None
    assert "products" not in retail.context_data


def test_a_bot_with_no_tools_declared_still_gets_an_empty_list():
    """The pre-tool path is a contract, not a gap: bots without tools answer in
    one turn exactly as they did before the runner existed."""
    assert registry.get_bot("banking").tools == []
    assert tool_registry.get_tools("banking") == []
    assert tool_registry.get_tools("does-not-exist") == []


def test_a_tool_name_that_does_not_exist_stops_the_process_rather_than_the_demo():
    with pytest.raises(ValueError) as failure:
        tool_registry._resolve("retail", ["erp_search_sku", "erp_serch_sku"])

    # The message has to name the typo and the alternatives, or whoever hits it
    # at startup is left guessing which of eight names is wrong.
    assert "erp_serch_sku" in str(failure.value)
    assert "erp_search_sku" in str(failure.value)
