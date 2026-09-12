"""P1-1: the keyword list matches bare words as substrings, so ordinary
sentences hand the conversation to a person and mute the bot for seven days.

`你们这是人工智能吗？` is Chinese for "is this an AI?" and contains 人工; the
realestate persona itself tells the bot to offer the word "agent".
"""
import pytest

from app.routers.whatsapp_webhook import _asked_for_a_person


@pytest.mark.parametrize(
    "said",
    [
        "你们这是人工智能吗？",
        "这是人工智能做的吗",
        "I bought it from your agent last week, can I return it?",
        "Do you have an agent in Penang?",
        "is this suitable for human resources teams?",
        "human error la",
    ],
)
def test_an_ordinary_sentence_does_not_ask_for_a_person(said):
    assert _asked_for_a_person(said) is False, said


@pytest.mark.parametrize(
    "said",
    ["我要转人工", "找真人", "can I speak to a human please", "boleh cakap dengan orang sebenar tak"],
)
def test_somebody_actually_asking_still_gets_one(said):
    assert _asked_for_a_person(said) is True, said
