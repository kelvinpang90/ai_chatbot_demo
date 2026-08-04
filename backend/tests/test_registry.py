from app.bots import registry


ALL_BOT_IDS = {"retail", "hotel", "banking", "food", "realestate", "saas"}


def test_all_bots_load_without_error():
    bots = registry.list_bots()
    ids = {bot.id for bot in bots}
    assert ids == ALL_BOT_IDS


def test_each_bot_has_localized_name_and_identities():
    for bot in registry.list_bots():
        assert bot.name.zh and bot.name.en and bot.name.ms
        assert bot.description.zh and bot.description.en and bot.description.ms
        assert bot.disclaimer.zh and bot.disclaimer.en and bot.disclaimer.ms
        assert 2 <= len(bot.identities) <= 3
        assert 3 <= len(bot.quick_questions) <= 4


def test_get_bot_returns_none_for_unknown_id():
    assert registry.get_bot("does-not-exist") is None


def test_get_identity_looks_up_within_bot():
    retail = registry.get_bot("retail")
    assert retail is not None
    identity = registry.get_identity("retail", retail.identities[0].id)
    assert identity is not None
    assert identity.id == retail.identities[0].id

    assert registry.get_identity("retail", "does-not-exist") is None
    assert registry.get_identity("does-not-exist", "does-not-exist") is None
