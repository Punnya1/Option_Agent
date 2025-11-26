from datetime import date as date_type
from typing import Optional
from pydantic import BaseModel


class CandidateOut(BaseModel):
    symbol: str
    date: date_type
    score: float

    atr_pct: float
    vol_spike: float
    gap_pct: float
    daily_return: float

    spot: Optional[float] = None
    expiry: Optional[date_type] = None
    total_oi: Optional[float] = None
    total_volume: Optional[float] = None

    direction: Optional[str] = None
    strategy_hint: Optional[str] = None

    ai_direction: Optional[str] = None
    ai_strategy_hint: Optional[str] = None
    ai_explanation: Optional[str] = None

    class Config:
        from_attributes = True
