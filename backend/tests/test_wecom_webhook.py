"""Tests for the 微信客服 callback endpoint.

The GET case is the one that has to be right on the first live attempt: WeCom
runs it once, while the admin is saving the callback config, and a wrong answer
means the config cannot be saved and the API Secret is never issued.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import wecom_webhook
from app.services import wecom_crypto
from tests.test_wecom_crypto import AES_KEY, CORPID, NONCE, TIMESTAMP, TOKEN, _encrypt

client = TestClient(app)

ECHOSTR_PLAINTEXT = "1616140317555161061"


@pytest.fixture
def wecom_configured():
    """Credentials good enough for the route to attempt real work."""
    with patch.object(settings, "wecom_corpid", CORPID):
        with patch.object(settings, "wecom_token", TOKEN):
            with patch.object(settings, "wecom_encoding_aes_key", AES_KEY):
                yield


def _query(encrypt: str, signature: str | None = None) -> dict:
    return {
        "msg_signature": (
            signature
            if signature is not None
            else wecom_crypto.signature(TOKEN, TIMESTAMP, NONCE, encrypt)
        ),
        "timestamp": TIMESTAMP,
        "nonce": NONCE,
    }


# --- GET: the one-shot handshake ---------------------------------------------


def test_get_returns_the_decrypted_echostr_as_bare_text(wecom_configured):
    echostr = _encrypt(ECHOSTR_PLAINTEXT)
    response = client.get("/webhook/wecom", params={**_query(echostr), "echostr": echostr})

    assert response.status_code == 200
    assert response.text == ECHOSTR_PLAINTEXT
    # No quotes, no BOM, no newline -- WeCom compares the body byte for byte.
    assert response.content == ECHOSTR_PLAINTEXT.encode()
    assert response.headers["content-type"].startswith("text/plain")


def test_get_rejects_a_bad_signature(wecom_configured):
    echostr = _encrypt(ECHOSTR_PLAINTEXT)
    response = client.get(
        "/webhook/wecom",
        params={**_query(echostr, signature="0" * 40), "echostr": echostr},
    )
    assert response.status_code == 401


def test_get_rejects_an_echostr_for_another_enterprise(wecom_configured):
    """Correctly signed with our token, but encrypted to somebody else's corpid."""
    echostr = _encrypt(ECHOSTR_PLAINTEXT, receiveid="ww_someone_else_00")
    response = client.get("/webhook/wecom", params={**_query(echostr), "echostr": echostr})
    assert response.status_code == 401


def test_get_without_an_echostr_is_a_bad_request(wecom_configured):
    response = client.get("/webhook/wecom", params=_query(""))
    assert response.status_code == 400


def test_get_reports_unconfigured_rather_than_pretending_to_verify():
    """No credentials is a deployment state, not a forged request."""
    with patch.object(settings, "wecom_token", ""):
        response = client.get("/webhook/wecom", params={"echostr": "anything"})
    assert response.status_code == 503


# --- POST: acknowledge, do not act -------------------------------------------


def _event_body(encrypt: str) -> bytes:
    return (
        f"<xml><ToUserName><![CDATA[{CORPID}]]></ToUserName>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>"
    ).encode()


def test_post_acknowledges_a_signed_event(wecom_configured):
    encrypt = _encrypt("<xml><Event><![CDATA[kf_msg_or_event]]></Event></xml>")
    response = client.post("/webhook/wecom", params=_query(encrypt), content=_event_body(encrypt))
    assert response.status_code == 200


def test_post_rejects_an_unsigned_event(wecom_configured):
    encrypt = _encrypt("<xml></xml>")
    response = client.post(
        "/webhook/wecom",
        params=_query(encrypt, signature="0" * 40),
        content=_event_body(encrypt),
    )
    assert response.status_code == 401


def test_post_rejects_a_body_with_no_encrypt_element(wecom_configured):
    encrypt = _encrypt("<xml></xml>")
    response = client.post(
        "/webhook/wecom", params=_query(encrypt), content=b"<xml><Nope/></xml>"
    )
    assert response.status_code == 401


# --- the hand-rolled <Encrypt> reader ----------------------------------------


def test_encrypt_field_reads_a_cdata_wrapped_value():
    assert wecom_webhook._encrypt_field(_event_body("abc123")) == "abc123"


def test_encrypt_field_reads_a_bare_value():
    body = b"<xml><Encrypt>abc123</Encrypt></xml>"
    assert wecom_webhook._encrypt_field(body) == "abc123"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<xml></xml>",
        b"<xml><Encrypt>unterminated</xml>",
        b"not xml at all",
        b"\xff\xfe\x00garbage",
    ],
)
def test_encrypt_field_returns_empty_rather_than_raising(body):
    """Every one of these arrives before the signature has been checked."""
    assert wecom_webhook._encrypt_field(body) == ""
