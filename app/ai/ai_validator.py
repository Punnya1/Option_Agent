from pydantic import BaseModel
from typing import Literal

class AIEventImpact(BaseModel):
    event_type: Literal[
        "results_positive",
        "results_negative",
        "order_win",
        "order_loss",
        "fund_raise",
        "regulatory",
        "neutral"
    ]
    ai_direction: Literal["bullish", "bearish", "neutral"]
    reaction_window: Literal["same_day", "next_day", "1_3_days"]
    confidence: Literal["low", "medium", "high"]
    explanation: str
