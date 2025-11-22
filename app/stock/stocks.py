# app/routers/stocks/stock_router.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.sessions import get_db
from .stock_validator import StockOut
from .stock_access import get_all_stocks

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/", response_model=list[StockOut])
def list_stocks(db: Session = Depends(get_db)):
    stocks = get_all_stocks(db)
    return stocks
