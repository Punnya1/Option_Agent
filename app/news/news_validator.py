from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AIStockNewsView(BaseModel):
    symbol: str
    window_days: int
    events: List[Dict[str, Any]]
    ai_direction: Optional[str] = None
    ai_confidence: Optional[str] = None
    ai_explanation: Optional[str] = None
    suggested_strategy: Optional[str] = None

class AIResponseSchema(BaseModel):
    ai_direction: str = Field(description="bullish|bearish|neutral")
    ai_confidence: str = Field(description="low|medium|high")
    ai_explanation: str = Field(description="short explanation")
    suggested_strategy: str = Field(description="short strategy hint")

