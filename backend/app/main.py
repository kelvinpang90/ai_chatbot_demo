import logging

from fastapi import FastAPI

from app.routers.chat import router as chat_router
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Chatbot Demo")
app.include_router(chat_router)
app.include_router(whatsapp_webhook_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
