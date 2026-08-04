from fastapi import FastAPI

app = FastAPI(title="AI Chatbot Demo")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
