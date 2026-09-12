"""N2 and N3: the phrase list that replaced the word list over-corrected.

N2 -- 23 of 25 realistic requests for a person miss, 转接人工 among them, which
     is how every Malaysian bank chat words it. banking, food and realestate had
     no tool at all, so this list was their only path.
N3 -- and it still fires on what a prospect says as they decide to buy.
"""
import pytest

from app.routers.whatsapp_webhook import _asked_for_a_person


@pytest.mark.parametrize(
    "said",
    [
        "转接人工",
        "能不能转真人",
        "人工在吗",
        "get me a human",
        "speak to an agent",
        "can I chat with a human",
        "nak cakap dengan manusia",
        "boleh saya bercakap dengan wakil",
    ],
)
def test_n2_the_ways_people_actually_ask(said):
    assert _asked_for_a_person(said) is True, said


@pytest.mark.parametrize(
    "said",
    [
        "Let me talk to someone in my team and get back to you",
        "I need to speak to someone in accounts first",
        "I'll talk to someone about the budget",
        "我想找个人一起拼单",
        "我找同事帮我下单",
        "boleh saya cakap dengan orang yang hantar barang tu?",
    ],
)
def test_n3_deciding_out_loud_is_not_asking_for_a_person(said):
    assert _asked_for_a_person(said) is False, said
