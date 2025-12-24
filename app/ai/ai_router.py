from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.candidate.candidate_access import get_top_candidates_for_date
from app.candidate.candidate_validator import CandidateOut
from app.db.sessions import get_db
from app.ai.ai_access import get_event_candidates
from app.core.logging_utils import get_logger
from .ai_explainer import get_ai_annotation_for_candidate

router = APIRouter(
    prefix="/candidates",
    tags=["candidates-ai"],
)
logger = get_logger(__name__)


@router.get("/ai", response_model=List[CandidateOut])
def list_candidates_with_ai(
    target_date: date = Query(..., alias="date"),
    limit: int = Query(10, ge=1, le=50),
    min_oi: float = Query(0.0, ge=0.0),
    min_volume: float = Query(0.0, ge=0.0),
    db: Session = Depends(get_db),
):
    """
    Same as /candidates, but additionally calls the LLM (Groq)
    to add ai_direction, ai_strategy_hint, ai_explanation.

    NOTE: This will make 1 LLM call per candidate (limit),
    so keep 'limit' modest (e.g. 5–10).
    """
    base = get_top_candidates_for_date(
        db, target_date, limit=limit, min_oi=min_oi, min_volume=min_volume
    )

    enriched = []
    for r in base:
        ai = get_ai_annotation_for_candidate(r)
        r["ai_direction"] = ai["ai_direction"]
        r["ai_strategy_hint"] = ai["ai_strategy_hint"]
        r["ai_explanation"] = ai["ai_explanation"]
        enriched.append(r)

    # Reuse CandidateOut but we need to extend it a bit (next step)
    result: List[CandidateOut] = []
    for r in enriched:
        result.append(
            CandidateOut(
                symbol=r["symbol"],
                date=r["date"],
                score=r["score"],
                atr_pct=r.get("atr_pct", 0.0),
                vol_spike=r.get("vol_spike", 0.0),
                gap_pct=r.get("gap_pct", 0.0),
                daily_return=r.get("return", 0.0),
                spot=r.get("spot"),
                expiry=r.get("expiry"),
                total_oi=r.get("total_oi"),
                total_volume=r.get("total_volume"),
                direction=r.get("direction"),
                strategy_hint=r.get("strategy_hint"),
                ai_direction=r.get("ai_direction"),
                ai_strategy_hint=r.get("ai_strategy_hint"),
                ai_explanation=r.get("ai_explanation"),
            )
        )

    return result


@router.get("/candidates")
def event_candidates(
    window_days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """
    Event-driven stock ideas based on BSE corporate announcements.
    """
    logger.info("Fetching event candidates window_days=%d", window_days)
    return get_event_candidates(db, window_days)