from datetime import date
from typing import Optional, Any

from pydantic import BaseModel


class StockBase(BaseModel):
    symbol: str
    name: Optional[str] = None
    segment: Optional[str] = None


class StockOut(StockBase):
    id: int

    class Config:
        from_attributes = True  


class DailyCandidateOut(BaseModel):
    symbol: str
    date: date
    score: float
    bias: str
    metadata_json: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True
