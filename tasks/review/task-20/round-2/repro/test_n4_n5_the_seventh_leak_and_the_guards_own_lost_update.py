"""N4 and N5, both about paths the round-1 fixes did not reach.

N4 -- `_handle_interactive_reply` is the seventh leak, and the only one that is
      not an apology: a customer taken over before they picked a demo taps one
      off the list and the bot sends the greeting and the buttons.
N5 -- the round-1 mid-turn guard reintroduced the lost update one line below
      where it fixed it: a message filed by the silent path while the model
      thought is erased by the save that drops the answer.
"""
from unittest.mock import patch

from app.routers.whatsapp_webhook import dispatch_message
from app.services import handover, llm
from app.services.user_store import user_store


def _held(phone: str):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(phone))


def _said(phone: str, text: str, seq: int) -> dict:
    return {"id": f"wamid.{phone}.{seq}", "from": phone, "type": "text", "text": {"body": text}}


def test_n4_tapping_a_button_does_not_interrupt_a_person():
    phone = "60129990401"
    profile = user_store.get_or_create(phone)
    user_store.save(profile)
    handover.begin(user_store.get(phone))

    sent = dispatch_message(
        {
            "id": f"wamid.{phone}.1",
            "from": phone,
            "type": "interactive",
            "interactive": {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}},
        }
    )

    assert sent == [], sent


def test_n5_a_message_that_arrived_while_the_model_thought_is_not_erased():
    phone = "60129990402"
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)

    def take_over_and_let_another_message_land(*_args, **_kwargs):
        handover.begin(user_store.get(phone))
        dispatch_message(_said(phone, "the address is 12 Jalan Ampang", 3))
        return "Sorry, I'm not sure."

    with patch.object(llm, "get_reply", side_effect=take_over_and_let_another_message_land):
        dispatch_message(_said(phone, "how much?", 2))

    said = [m.content for m in user_store.get(phone).history]
    assert "the address is 12 Jalan Ampang" in said, said
