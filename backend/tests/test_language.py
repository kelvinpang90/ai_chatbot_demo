import pytest

from app.services import language
from app.services.language import Localized
from app.services.user_store import UserProfile


@pytest.mark.parametrize(
    "said, expected",
    [
        ("找人工客服", "zh"),
        # Malaysian code-mixing: the model answers this in Chinese, so we do too.
        ("我要买两个 fan, hantar ke Johor", "zh"),
        ("saya nak cakap dengan orang", "ms"),
        ("Berapa harga earbuds ni?", "ms"),
        ("can I speak to a human please", "en"),
        ("How much is the Sony earbuds", "en"),
    ],
)
def test_what_a_customer_writes_decides_their_language(said, expected):
    assert language.detect(said) == expected


@pytest.mark.parametrize("said", ["", "ok", "hi", "👍", "60123456789", "SKU-1001"])
def test_a_word_that_could_be_anyone_decides_nothing(said):
    """The point of None: "ok" from a Chinese customer must not make them English."""
    assert language.detect(said) is None


def test_the_record_keeps_its_language_through_a_message_that_says_nothing():
    profile = UserProfile(key_id="60129996001", phone="60129996001")

    language.remember(profile, "东西什么时候到？")
    language.remember(profile, "ok")

    assert profile.language == "zh"


def test_a_known_language_gets_one_line_and_an_unknown_one_gets_all_three():
    line = Localized(zh="你好", en="Hello", ms="Hai")

    assert line.pick("zh") == "你好"
    assert line.pick("ms") == "Hai"
    assert line.pick(None) == "你好 / Hello / Hai"
    assert line.pick("fr") == "你好 / Hello / Hai"


def test_a_line_with_blanks_is_filled_in_every_language():
    line = Localized(zh="订单 {no}", en="Order {no}", ms="Pesanan {no}").format(no="SO-1")

    assert line == Localized(zh="订单 SO-1", en="Order SO-1", ms="Pesanan SO-1")
