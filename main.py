# app/main.py
from fastapi import FastAPI

from app.stock import stocks

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(stocks.router)
