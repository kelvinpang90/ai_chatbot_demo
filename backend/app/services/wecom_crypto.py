"""WXBizMsgCrypt: the signature and AES scheme WeCom wraps its callbacks in.

Meta signs a callback by putting an HMAC of the raw body in a header
(`whatsapp.verify_signature`). WeCom does neither half that way: the signature
is a SHA1 over four *sorted* fields carried as query parameters, and the body
is not merely signed but encrypted, so there is nothing to read until it has
been decrypted with a key the enterprise configured in the admin console.

Only the receiving half lives here. A reply to 微信客服 goes out through the
send_msg API, not back down the callback, so nothing in this codebase ever
needs to encrypt -- and an unused encryptor is a thing that can be wrong
without anyone noticing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# The console hands out a 43-character EncodingAESKey, which is a 32-byte key
# with its final base64 pad character stripped. Putting the "=" back is the
# whole derivation -- there is no KDF.
ENCODING_AES_KEY_LENGTH = 43
AES_KEY_BYTES = 32

# Tencent's own sample pads to 32 rather than to the 16-byte AES block, so a
# padding byte can legitimately be anything up to 32. Decryption only reads the
# length back, but it has to accept the wider range or valid messages look
# corrupt.
MAX_PAD_BYTES = 32

# random(16) + msg_len(4, big-endian) + msg + receiveid
RANDOM_PREFIX_BYTES = 16
MSG_LEN_BYTES = 4
_HEADER_BYTES = RANDOM_PREFIX_BYTES + MSG_LEN_BYTES


class WecomCryptoError(Exception):
    """A callback that did not decrypt to something we are willing to act on."""


def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """The msg_signature WeCom should have sent for these four fields.

    Sorted as strings and concatenated -- not in the order they appear in the
    query string, which is why this cannot be written as an f-string.
    """
    joined = "".join(sorted([token, timestamp, nonce, encrypt]))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def verify_signature(
    token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str | None
) -> bool:
    """Whether msg_signature proves this callback came from WeCom."""
    if not msg_signature:
        return False
    return hmac.compare_digest(signature(token, timestamp, nonce, encrypt), msg_signature)


def decrypt(encoding_aes_key: str, receiveid: str, encrypt: str) -> str:
    """The plaintext inside an `Encrypt` field, or an echostr.

    `receiveid` is checked, not returned: a correctly encrypted message meant
    for a different enterprise is still not ours to answer.
    """
    key = _aes_key(encoding_aes_key)
    try:
        ciphertext = base64.b64decode(encrypt, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WecomCryptoError("encrypt field is not valid base64") from exc

    # AES-CBC cannot even start on a partial block, and failing here keeps the
    # error about the input rather than about the cipher.
    if not ciphertext or len(ciphertext) % 16:
        raise WecomCryptoError("ciphertext is not a whole number of AES blocks")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    pad = padded[-1]
    if not 1 <= pad <= MAX_PAD_BYTES or pad > len(padded):
        raise WecomCryptoError("bad padding: wrong key, or not a WeCom payload")
    plain = padded[:-pad]

    if len(plain) < _HEADER_BYTES:
        raise WecomCryptoError("plaintext is too short to carry a length header")
    (msg_len,) = struct.unpack(">I", plain[RANDOM_PREFIX_BYTES:_HEADER_BYTES])
    if msg_len > len(plain) - _HEADER_BYTES:
        raise WecomCryptoError("declared message length runs past the plaintext")

    msg = plain[_HEADER_BYTES : _HEADER_BYTES + msg_len]
    trailing = plain[_HEADER_BYTES + msg_len :]
    try:
        decoded_receiveid = trailing.decode("utf-8")
        decoded_msg = msg.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WecomCryptoError("plaintext is not utf-8") from exc

    if not hmac.compare_digest(decoded_receiveid, receiveid):
        raise WecomCryptoError("callback is addressed to a different enterprise")
    return decoded_msg


def _aes_key(encoding_aes_key: str) -> bytes:
    if len(encoding_aes_key) != ENCODING_AES_KEY_LENGTH:
        raise WecomCryptoError(
            f"EncodingAESKey must be {ENCODING_AES_KEY_LENGTH} characters, "
            f"got {len(encoding_aes_key)}"
        )
    try:
        key = base64.b64decode(encoding_aes_key + "=")
    except (binascii.Error, ValueError) as exc:
        raise WecomCryptoError("EncodingAESKey is not valid base64") from exc
    if len(key) != AES_KEY_BYTES:
        raise WecomCryptoError("EncodingAESKey did not decode to a 32-byte key")
    return key
