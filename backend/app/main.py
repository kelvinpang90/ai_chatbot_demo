import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers.chat import router as chat_router
from app.routers.console import router as console_router
from app.routers.internal_whatsapp import router as internal_whatsapp_router
from app.routers.wecom_webhook import router as wecom_webhook_router
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router
from app.services import crm_events
from app.verticals.food.routes import router as food_router
from app.verticals.hotel.routes import router as hotel_router
from app.verticals.realestate.routes import router as realestate_router
from app.verticals.saas.routes import router as saas_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Does nothing unless CRM_EVENTS_ENABLED is on (task 40.1).
    crm_events.start()
    yield


app = FastAPI(title="AI Chatbot Demo", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(whatsapp_webhook_router)
app.include_router(wecom_webhook_router)
app.include_router(internal_whatsapp_router)
app.include_router(console_router)
app.include_router(realestate_router)
app.include_router(food_router)
app.include_router(hotel_router)
app.include_router(saas_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
