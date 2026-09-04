"""Tests for the WeCom callback signature and AES scheme.

These build their own ciphertext, so they prove the parser is self-consistent
and that every malformed shape is refused -- not that we match Tencent byte for
byte. The only thing that proves conformance is WeCom accepting the callback
URL, which it verifies at the moment the config is saved. Until that happens,
treat "254 passed" as necessary and not sufficient.
"""

import base64
import hashlib
import struct

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services import wecom_crypto

# 32 known bytes, base64'd, minus the trailing "=" -- exactly the shape the
# admin console hands out.
AES_KEY = base64.b64encode(bytes(range(32))).decode()[:-1]
OTHER_AES_KEY = base64.b64encode(bytes(range(100, 132))).decode()[:-1]

CORPID = "ww7c0ec00000000000"
TOKEN = "test-callback-token"
TIMESTAMP = "1757000000"
NONCE = "1372623149"


def _encrypt(msg: str, receiveid: str = CORPID, aes_key: str = AES_KEY) -> str:
    key = base64.b64decode(aes_key + "=")
    payload = msg.encode("utf-8")
    body = b"0123456789abcdef" + struct.pack(">I", len(payload)) + payload + receiveid.encode()
    pad = 32 - (len(body) % 32)
    body += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(encryptor.update(body) + encryptor.finalize()).decode()


# --- signature ---------------------------------------------------------------


def test_signature_is_sha1_of_the_sorted_fields():
    encrypt = "some-encrypted-blob"
    expected = hashlib.sha1(
        "".join(sorted([TOKEN, TIMESTAMP, NONCE, encrypt])).encode()
    ).hexdigest()
    assert wecom_crypto.signature(TOKEN, TIMESTAMP, NONCE, encrypt) == expected


def test_signature_ignores_the_order_the_fields_arrive_in():
    """The four values are sorted, so mixing up which is which cannot matter.

    This is the part that is easy to get wrong by writing an f-string.
    """
    a = wecom_crypto.signature("aaa", "bbb", "ccc", "ddd")
    b = wecom_crypto.signature("ddd", "ccc", "bbb", "aaa")
    assert a == b


def test_verify_signature_accepts_a_correct_signature():
    encrypt = _encrypt("<xml></xml>")
    good = wecom_crypto.signature(TOKEN, TIMESTAMP, NONCE, encrypt)
    assert wecom_crypto.verify_signature(TOKEN, TIMESTAMP, NONCE, encrypt, good) is True


def test_verify_signature_rejects_a_tampered_body():
    encrypt = _encrypt("<xml></xml>")
    good = wecom_crypto.signature(TOKEN, TIMESTAMP, NONCE, encrypt)
    assert wecom_crypto.verify_signature(TOKEN, TIMESTAMP, NONCE, "tampered", good) is False


def test_verify_signature_rejects_the_wrong_token():
    encrypt = _encrypt("<xml></xml>")
    signed_with_other_token = wecom_crypto.signature("other-token", TIMESTAMP, NONCE, encrypt)
    assert (
        wecom_crypto.verify_signature(TOKEN, TIMESTAMP, NONCE, encrypt, signed_with_other_token)
        is False
    )


@pytest.mark.parametrize("missing", [None, ""])
def test_verify_signature_rejects_a_missing_signature(missing):
    assert wecom_crypto.verify_signature(TOKEN, TIMESTAMP, NONCE, "blob", missing) is False


# --- decrypt -----------------------------------------------------------------


def test_decrypt_round_trips_an_echostr():
    assert wecom_crypto.decrypt(AES_KEY, CORPID, _encrypt("1616140317555161061")) == (
        "1616140317555161061"
    )


def test_decrypt_round_trips_utf8_beyond_ascii():
    """The kf callbacks carry Chinese, and msg_len counts bytes rather than characters."""
    message = "<xml><Event><![CDATA[未来智能科技客服]]></Event></xml>"
    assert wecom_crypto.decrypt(AES_KEY, CORPID, _encrypt(message)) == message


def test_decrypt_round_trips_when_the_body_lands_on_a_block_boundary():
    """Padding is a full 32 bytes here, the largest value the parser may see."""
    # 16 random + 4 length + 18 corpid = 38, so a 26-byte message reaches 64.
    message = "a" * 26
    assert wecom_crypto.decrypt(AES_KEY, CORPID, _encrypt(message)) == message


def test_decrypt_rejects_a_message_for_another_enterprise():
    encrypt = _encrypt("<xml></xml>", receiveid="ww_someone_else_00")
    with pytest.raises(wecom_crypto.WecomCryptoError, match="different enterprise"):
        wecom_crypto.decrypt(AES_KEY, CORPID, encrypt)


def test_decrypt_rejects_the_wrong_key():
    encrypt = _encrypt("<xml></xml>", aes_key=OTHER_AES_KEY)
    with pytest.raises(wecom_crypto.WecomCryptoError, match="padding"):
        wecom_crypto.decrypt(AES_KEY, CORPID, encrypt)


def test_decrypt_rejects_a_non_base64_body():
    with pytest.raises(wecom_crypto.WecomCryptoError, match="base64"):
        wecom_crypto.decrypt(AES_KEY, CORPID, "not base64 at all!!")


def test_decrypt_rejects_a_partial_aes_block():
    truncated = base64.b64encode(b"only-nine").decode()
    with pytest.raises(wecom_crypto.WecomCryptoError, match="whole number of AES blocks"):
        wecom_crypto.decrypt(AES_KEY, CORPID, truncated)


def test_decrypt_rejects_an_empty_body():
    with pytest.raises(wecom_crypto.WecomCryptoError, match="whole number of AES blocks"):
        wecom_crypto.decrypt(AES_KEY, CORPID, "")


def test_decrypt_rejects_a_length_header_that_overruns_the_plaintext():
    """A correctly encrypted payload can still lie about how long its message is."""
    key = base64.b64decode(AES_KEY + "=")
    body = b"0123456789abcdef" + struct.pack(">I", 9999) + b"short" + CORPID.encode()
    pad = 32 - (len(body) % 32)
    body += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    forged = base64.b64encode(encryptor.update(body) + encryptor.finalize()).decode()

    with pytest.raises(wecom_crypto.WecomCryptoError, match="runs past the plaintext"):
        wecom_crypto.decrypt(AES_KEY, CORPID, forged)


@pytest.mark.parametrize("bad_key", ["", "too-short", AES_KEY + "extra"])
def test_decrypt_rejects_a_malformed_encoding_aes_key(bad_key):
    with pytest.raises(wecom_crypto.WecomCryptoError, match="43 characters"):
        wecom_crypto.decrypt(bad_key, CORPID, _encrypt("<xml></xml>"))
