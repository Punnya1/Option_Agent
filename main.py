from fastapi import FastAPI

from app.candidate import candidate
from app.stock import stocks

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(stocks.router)
app.include_router(candidate.router)