import logging

from fastapi import FastAPI

from app.routers.chat import router as chat_router
from app.routers.console import router as console_router
from app.routers.internal_whatsapp import router as internal_whatsapp_router
from app.routers.wecom_webhook import router as wecom_webhook_router
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Chatbot Demo")
app.include_router(chat_router)
app.include_router(whatsapp_webhook_router)
app.include_router(wecom_webhook_router)
app.include_router(internal_whatsapp_router)
app.include_router(console_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
