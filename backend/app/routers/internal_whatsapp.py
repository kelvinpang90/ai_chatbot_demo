from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.routers.whatsapp_webhook import dispatch_message

router = APIRouter(prefix="/internal/whatsapp")


@router.post("/inbound")
async def receive_inbound(request: Request, x_internal_secret: str | None = Header(default=None)) -> dict:
    if not settings.internal_shared_secret or x_internal_secret != settings.internal_shared_secret:
        raise HTTPException(status_code=401)

    body = await request.json()
    message = body.get("message")
    if not isinstance(message, dict):
        raise HTTPException(status_code=400, detail="Missing 'message'")

    return {"messages": dispatch_message(message)}
