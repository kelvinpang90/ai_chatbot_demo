from unittest.mock import patch

import anthropic
import httpx

from app.bots.registry import get_bot
from app.services import llm


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
