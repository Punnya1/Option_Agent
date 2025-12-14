from datetime import date
from typing import List, Dict, Any, Tuple, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.signals import score_all_symbols_for_date
from app.services.options import get_options_liquidity
from app.core.logging_utils import get_logger

logger = get_logger(__name__)


def classify_direction_and_strategy(metrics: Dict[str, Any]) -> Tuple[str, str]:
    """
    Conservative rule-based direction + strategy.
    """
    logger.debug(f"Classifying direction for {metrics.get('symbol')}...")

    ret = metrics.get("return", 0.0) or 0.0
    vol_spike = metrics.get("vol_spike", 0.0) or 0.0
    gap = metrics.get("gap_pct", 0.0) or 0.0
    atr_pct = metrics.get("atr_pct", 0.0) or 0.0

    direction = "neutral"
    strategy = "no clear directional edge; consider waiting or intraday only"

    # Bullish
    if ret >= 0.03 and vol_spike >= 1.3 and gap > -0.01:
        direction = "bullish"
        if atr_pct < 0.04:
            strategy = "buy near-ATM call; avoid very far OTM strikes"
        else:
            strategy = "bull call spread (buy near-ATM call, sell higher strike)"

    # Bearish
    elif ret <= -0.03 and vol_spike >= 1.3:
        direction = "bearish"
        if atr_pct < 0.04:
            strategy = "buy near-ATM put; avoid very far OTM strikes"
        else:
            strategy = "bear put spread (buy near-ATM put, sell lower strike)"

    # Neutral
    else:
        if abs(ret) < 0.01 and vol_spike < 1.2:
            strategy = "very quiet; probably skip or trade only if intraday setup is clean"
        elif atr_pct >= 0.03:
            strategy = (
                "range-bound options (iron condor / short strangle) if experienced"
            )
        else:
            strategy = "no strong view; consider skipping"

    logger.debug(
        f"Classified {metrics.get('symbol')} as direction={direction}, strategy={strategy}"
    )
    return direction, strategy


def _get_last_trade_date(db: Session, target_date: date) -> Optional[date]:
    """
    Return the most recent trade date <= target_date found in daily_prices.
    Returns None if none exists (DB empty / too early).
    """
    # Use a safe raw SQL scalar query for the max date
    try:
        sql = text("SELECT MAX(date) FROM daily_prices WHERE date <= :d")
        res = db.execute(sql, {"d": target_date}).scalar_one_or_none()
        if res is None:
            return None
        # SQL may return datetime.date already; ensure type correctness
        return res
    except Exception as e:
        logger.exception("Error fetching last trade date up to %s: %s", target_date, e)
        return None


def get_top_candidates_for_date(
    db: Session,
    target_date: date,
    limit: int = 20,
    min_oi: float = 0.0,
    min_volume: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    1) Score symbols using equity signals
    2) Compute options liquidity (with moneyness fallbacks)
    3) Filter by min OI/volume
    4) Add direction + strategy
    5) Return sorted list

    NOTE: If the requested target_date has no trades, we fallback to the last
    available trading date <= target_date.
    """
    logger.info(
        f"Running candidate scan for date={target_date}, "
        f"limit={limit}, min_oi={min_oi}, min_volume={min_volume}"
    )

    # --- fallback to last trading date if needed ---
    actual_date = _get_last_trade_date(db, target_date)
    if actual_date is None:
        logger.info("No trading data available on or before %s. Returning empty list.", target_date)
        return []

    if actual_date != target_date:
        logger.info(
            "Requested date %s had no trades; using last trading date %s instead.",
            target_date,
            actual_date,
        )
        target_date = actual_date

    # Step 1: Equity-based scoring
    try:
        base_results = score_all_symbols_for_date(
            db, target_date, lookback_days=5, limit=500
        )
        logger.info(f"Equity scoring produced {len(base_results)} symbols for date={target_date}.")
    except Exception as e:
        logger.exception(f"Error during equity scoring for date={target_date}: {e}")
        raise

    filtered: List[Dict[str, Any]] = []
    skip_reasons: Dict[str, str] = {}

    # Step 2: Options liquidity for each symbol with moneyness fallbacks
    for r in base_results:
        symbol = r.get("symbol")
        if not symbol:
            logger.debug("Skipping entry without symbol in scoring results.")
            continue

        logger.debug(f"Checking options liquidity for {symbol} at date={target_date}...")

        # Try a list of increasing moneyness bands until we find liquidity
        liq = None
        tried_bands = []
        for band in (0.05, 0.1, 0.2, 0.5):
            tried_bands.append(band)
            try:
                liq = get_options_liquidity(db, symbol, target_date, moneyness_band=band)
            except Exception as e:
                logger.warning("Liquidity fetch error for %s at band %s: %s", symbol, band, e)
                liq = None

            if liq:
                logger.debug("Found liquidity for %s at moneyness band %s", symbol, band)
                break

        if not liq:
            skip_reasons[symbol] = f"no_liquidity_at_bands:{tried_bands}"
            logger.debug("%s skipped: %s", symbol, skip_reasons[symbol])
            continue

        total_oi = liq.get("total_oi", 0) or 0
        total_volume = liq.get("total_volume", 0) or 0

        # Apply the liquidity threshold semantics:
        # current behavior: skip only if BOTH oi < min_oi AND volume < min_volume
        if total_oi < min_oi and total_volume < min_volume:
            skip_reasons[symbol] = f"low_liquidity(oi={total_oi},vol={total_volume})"
            logger.debug("%s skipped: %s", symbol, skip_reasons[symbol])
            continue

        # Merge liquidity info into result dict
        r["spot"] = liq.get("spot")
        r["expiry"] = liq.get("expiry")
        r["total_oi"] = total_oi
        r["total_volume"] = total_volume

        # Step 3: Apply rule-based direction
        direction, strategy = classify_direction_and_strategy(r)
        r["direction"] = direction
        r["strategy_hint"] = strategy

        filtered.append(r)

    logger.info(
        "After liquidity and rule filters, %s candidates remain before sorting (date=%s).",
        len(filtered),
        target_date,
    )

    # Log a short summary of skipped symbols (sample up to 10)
    if skip_reasons:
        sample = ", ".join(f"{k}:{v}" for k, v in list(skip_reasons.items())[:10])
        logger.info("Skipped symbols summary (sample): %s", sample)

    # Step 4: Sort by score descending
    filtered.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    final = filtered[:limit]
    logger.info(f"Returning top {len(final)} candidates for {target_date}")

    return final
