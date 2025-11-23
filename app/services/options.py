from datetime import date
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.db.models import OptionChain, DailyPrice


def get_spot_price(db: Session, symbol: str, trade_date: date) -> Optional[float]:
    """
    Get underlying close price (spot proxy) from daily_prices.
    """
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date == trade_date)
        .scalar()
    )
    return float(row) if row is not None else None


def get_nearest_expiry(
    db: Session, symbol: str, trade_date: date
) -> Optional[date]:
    """
    Get nearest expiry >= trade_date for which we have option_chain data.
    """
    expiry = (
        db.query(func.min(OptionChain.expiry))
        .filter(
            OptionChain.symbol == symbol,
            OptionChain.date == trade_date,
            OptionChain.expiry >= trade_date,
        )
        .scalar()
    )
    return expiry


def get_options_liquidity(
    db: Session,
    symbol: str,
    trade_date: date,
    moneyness_band: float = 0.1,
) -> Optional[Dict[str, Any]]:
    """
    Compute a simple liquidity metric for a symbol on a given date:

    - use nearest expiry
    - sum OI and volume for strikes within +/- moneyness_band around spot
      (e.g. 0.1 -> strikes within +/-10% of spot)

    Returns dict with spot, expiry, total_oi, total_volume, or None if
    we can't compute anything.
    """
    spot = get_spot_price(db, symbol, trade_date)
    if spot is None or spot <= 0:
        return None

    expiry = get_nearest_expiry(db, symbol, trade_date)
    if expiry is None:
        return None

    lower_strike = spot * (1.0 - moneyness_band)
    upper_strike = spot * (1.0 + moneyness_band)

    q = (
        db.query(
            func.coalesce(func.sum(OptionChain.oi), 0.0).label("total_oi"),
            func.coalesce(func.sum(OptionChain.volume), 0.0).label("total_volume"),
        )
        .filter(
            OptionChain.symbol == symbol,
            OptionChain.date == trade_date,
            OptionChain.expiry == expiry,
            OptionChain.strike >= lower_strike,
            OptionChain.strike <= upper_strike,
        )
    )

    row = q.one()
    total_oi = float(row.total_oi)
    total_volume = float(row.total_volume)

    # If completely dead, you can return None instead
    if total_oi == 0.0 and total_volume == 0.0:
        return None

    return {
        "symbol": symbol,
        "date": trade_date,
        "spot": float(spot),
        "expiry": expiry,
        "total_oi": total_oi,
        "total_volume": total_volume,
    }
