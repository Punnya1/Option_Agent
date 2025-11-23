from datetime import date
from typing import List, Dict, Any

from sqlalchemy.orm import Session

from app.services.signals import score_all_symbols_for_date
from app.services.options import get_options_liquidity


def get_top_candidates_for_date(
    db: Session,
    target_date: date,
    limit: int = 20,
    min_oi: float = 0.0,
    min_volume: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    1) Use equity signals to score all symbols
    2) For each, compute options liquidity
    3) Keep only those with sufficient OI/volume
    4) Return top 'limit' by score
    """
    # Start with more symbols than we return, to allow filtering
    base_results = score_all_symbols_for_date(
        db, target_date, lookback_days=5, limit=500
    )

    filtered: List[Dict[str, Any]] = []

    for r in base_results:
        symbol = r["symbol"]
        liq = get_options_liquidity(db, symbol, target_date, moneyness_band=0.1)
        if liq is None:
            continue

        total_oi = liq["total_oi"]
        total_volume = liq["total_volume"]

        # Check liquidity thresholds
        if total_oi < min_oi and total_volume < min_volume:
            continue

        # Merge liquidity info into result
        r["spot"] = liq["spot"]
        r["expiry"] = liq["expiry"]
        r["total_oi"] = total_oi
        r["total_volume"] = total_volume

        filtered.append(r)

    # Sort again by score just in case
    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:limit]
