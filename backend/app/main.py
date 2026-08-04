from fastapi import FastAPI

from app.routers.chat import router as chat_router

app = FastAPI(title="AI Chatbot Demo")
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
