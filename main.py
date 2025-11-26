from fastapi import FastAPI

from app.candidate import candidate
from app.stock import stocks
from app.ai import ai_router

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(stocks.router)
app.include_router(candidate.router)
app.include_router(ai_router.router)
