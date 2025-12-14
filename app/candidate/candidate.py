from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.candidate.candidate_access import get_top_candidates_for_date
from app.candidate.candidate_validator import CandidateOut
from app.db.sessions import get_db
from app.core.logging_utils import get_logger

router = APIRouter(
    prefix="/candidates",
    tags=["candidates"],
)
logger = get_logger(__name__)


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

    logger.info(
        f"Fetching candidates for date={target_date}, limit={limit}, "
        f"min_oi={min_oi}, min_volume={min_volume}"
    )

    try:
        raw_results = get_top_candidates_for_date(
            db, target_date, limit=limit, min_oi=min_oi, min_volume=min_volume
        )
    except Exception as e:
        logger.exception(f"Error fetching candidates for date={target_date}: {e}")
        raise

    logger.info(f"Fetched {len(raw_results)} raw candidates for {target_date}")

    candidates: List[CandidateOut] = []
    for r in raw_results:
        logger.debug(f"Parsing candidate symbol={r.get('symbol')}")

        candidates.append(
            CandidateOut(
                symbol=r.get("symbol"),
                date=r.get("date"),
                score=r.get("score"),
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
            )
        )

    logger.info(f"Returning {len(candidates)} candidates for {target_date}")
    return candidates
