from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.candidate.candidate_access import get_top_candidates_for_date
from app.candidate.candidate_validator import CandidateOut
from app.db.sessions import get_db

router = APIRouter(
    prefix="/candidates",
    tags=["candidates"],
)


@router.get("/", response_model=List[CandidateOut])
def list_candidates(
    target_date: date = Query(..., alias="date"),
    limit: int = Query(20, ge=1, le=200),
    min_oi: float = Query(0.0, ge=0.0),
    min_volume: float = Query(0.0, ge=0.0),
    db: Session = Depends(get_db),
):
    """
    Return top 'limit' symbols for a given date based on equity price/volume
    signals AND options liquidity.

    Example:
    GET /candidates?date=2025-11-21&limit=20&min_oi=10000&min_volume=100
    """
    raw_results = get_top_candidates_for_date(
        db, target_date, limit=limit, min_oi=min_oi, min_volume=min_volume
    )

    candidates: List[CandidateOut] = []
    for r in raw_results:
        candidates.append(
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
            )
        )

    return candidates
