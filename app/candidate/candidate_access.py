from datetime import date
from typing import List, Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.services.signals import score_all_symbols_for_date
from app.services.options import get_options_liquidity


def classify_direction_and_strategy(metrics: Dict[str, Any]) -> Tuple[str, str]:
    """
    Conservative rule-based direction + strategy.

    Uses:
    - daily_return
    - vol_spike
    - gap_pct
    - atr_pct
    """

    ret = metrics.get("return", 0.0) or 0.0
    vol_spike = metrics.get("vol_spike", 0.0) or 0.0
    gap = metrics.get("gap_pct", 0.0) or 0.0
    atr_pct = metrics.get("atr_pct", 0.0) or 0.0

    direction = "neutral"
    strategy = "no clear directional edge; consider waiting or intraday only"

    # Conservative thresholds
    # Bullish: strong upmove + higher volume, no nasty gap-down
    if ret >= 0.03 and vol_spike >= 1.3 and gap > -0.01:
        direction = "bullish"
        if atr_pct < 0.04:
            strategy = "buy near-ATM call; avoid very far OTM strikes"
        else:
            strategy = "bull call spread (buy near-ATM call, sell slightly higher strike)"

    # Bearish: strong downmove + higher volume
    elif ret <= -0.03 and vol_spike >= 1.3:
        direction = "bearish"
        if atr_pct < 0.04:
            strategy = "buy near-ATM put; avoid very far OTM strikes"
        else:
            strategy = "bear put spread (buy near-ATM put, sell slightly lower strike)"

    else:
        # Neutral-ish day
        if abs(ret) < 0.01 and vol_spike < 1.2:
            strategy = "very quiet; probably skip or trade only if intraday setup is very clean"
        elif atr_pct >= 0.03:
            strategy = "range-bound options strategy (e.g. iron condor / short strangle) only if you understand the risks"
        else:
            strategy = "no strong view; consider skipping and wait for clearer move"

    return direction, strategy


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
    4) Add conservative direction + strategy
    5) Return top 'limit' by score
    """
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

        if total_oi < min_oi and total_volume < min_volume:
            continue

        # Merge liquidity info into result
        r["spot"] = liq["spot"]
        r["expiry"] = liq["expiry"]
        r["total_oi"] = total_oi
        r["total_volume"] = total_volume

        # Add direction + strategy
        direction, strategy = classify_direction_and_strategy(r)
        r["direction"] = direction
        r["strategy_hint"] = strategy

        filtered.append(r)

    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:limit]
