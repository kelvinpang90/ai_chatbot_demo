"""The 微信客服 callback endpoint.

Only the handshake half is here. WeCom will not release the API Secret until
the callback config is saved, and it verifies the URL at the moment of saving,
so this endpoint has to exist and answer before the credential that the rest of
the channel needs can be obtained at all. Reading the messages it later
announces needs that Secret, and lands with the sync_msg client.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.services import wecom_crypto

router = APIRouter(prefix="/webhook/wecom")
logger = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(
        settings.wecom_corpid and settings.wecom_token and settings.wecom_encoding_aes_key
    )


def _signature_ok(request: Request, encrypt: str) -> bool:
    params = request.query_params
    return wecom_crypto.verify_signature(
        settings.wecom_token,
        params.get("timestamp", ""),
        params.get("nonce", ""),
        encrypt,
        params.get("msg_signature"),
    )


@router.get("")
def verify_webhook(request: Request) -> Response:
    """Answer the challenge WeCom sends when the callback URL is saved.

    The reply is the decrypted echostr and nothing else: no quotes, no BOM, no
    trailing newline, inside one second. `Response` with a str body writes
    exactly those bytes, which is why this does not go through a JSON response.
    """
    if not _configured():
        logger.warning("WeCom URL verification arrived but the channel has no credentials")
        return Response(status_code=503)

    echostr = request.query_params.get("echostr", "")
    if not echostr:
        return Response(status_code=400)

    if not _signature_ok(request, echostr):
        logger.warning("Rejected WeCom URL verification with an invalid signature")
        return Response(status_code=401)

    try:
        plaintext = wecom_crypto.decrypt(
            settings.wecom_encoding_aes_key, settings.wecom_corpid, echostr
        )
    except wecom_crypto.WecomCryptoError:
        logger.exception("WeCom URL verification did not decrypt")
        return Response(status_code=401)

    logger.info("Answered WeCom URL verification")
    return Response(content=plaintext, media_type="text/plain")


@router.post("")
async def receive_webhook(request: Request) -> Response:
    """Acknowledge an event without acting on it yet.

    The moment the callback config is saved WeCom starts posting here, and a
    404 or 405 to every one of those would pile up as delivery failures against
    the account. Acknowledging costs nothing: the callback carries no message
    anyway, and sync_msg can still fetch anything announced in the last three
    days once there is a client to fetch it with.
    """
    if not _configured():
        return Response(status_code=503)

    raw_body = await request.body()
    if not _signature_ok(request, _encrypt_field(raw_body)):
        logger.warning("Rejected WeCom callback with an invalid signature")
        return Response(status_code=401)

    logger.info("Acknowledged WeCom callback event; message retrieval is not wired up yet")
    return Response(status_code=200)


def _encrypt_field(raw_body: bytes) -> str:
    """The <Encrypt> element the signature is computed over.

    Parsed by hand rather than with an XML parser: the body is attacker-reachable
    and unauthenticated at this point -- checking its signature is the very thing
    we are about to do -- so it never becomes a document tree.
    """
    text = raw_body.decode("utf-8", errors="replace")
    start = text.find("<Encrypt>")
    end = text.find("</Encrypt>")
    if start == -1 or end == -1 or end < start:
        return ""
    inner = text[start + len("<Encrypt>") : end].strip()
    if inner.startswith("<![CDATA[") and inner.endswith("]]>"):
        inner = inner[len("<![CDATA[") : -len("]]>")]
    return inner
