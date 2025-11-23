from datetime import date, timedelta
from typing import List, Dict, Any

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.db.models import DailyPrice, Stock


# Use small lookback for now so it works with a few days of data
LOOKBACK_DAYS_DEFAULT = 5


def get_price_history(
    db: Session,
    symbol: str,
    end_date: date,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
) -> pd.DataFrame:
    """
    Load recent price history for a symbol up to end_date (inclusive)
    and return as a pandas DataFrame sorted by date.
    """
    # small buffer for weekends/holidays
    start_date = end_date - timedelta(days=lookback_days * 2)

    stmt = (
        select(DailyPrice)
        .where(
            and_(
                DailyPrice.symbol == symbol,
                DailyPrice.date >= start_date,
                DailyPrice.date <= end_date,
            )
        )
        .order_by(DailyPrice.date)
    )
    rows: List[DailyPrice] = db.scalars(stmt).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
    )
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a price history DataFrame, compute:
    - daily returns
    - true range
    - short ATR (3-day)
    - short volume moving average (3-day)
    - volume spike ratio
    - gap vs previous close
    Works even with very few rows (min_periods=1).
    """
    if df.empty or len(df) < 1:
        return df

    df = df.copy()

    # Daily returns
    df["return"] = df["close"].pct_change()

    # Previous close (use same close for first row to avoid NaNs in TR)
    df["prev_close"] = df["close"].shift(1)
    df.loc[df["prev_close"].isna(), "prev_close"] = df.loc[
        df["prev_close"].isna(), "close"
    ]

    # True Range
    df["tr1"] = df["high"] - df["low"]
    df["tr2"] = (df["high"] - df["prev_close"]).abs()
    df["tr3"] = (df["low"] - df["prev_close"]).abs()
    df["true_range"] = df[["tr1", "tr2", "tr3"]].max(axis=1)

    # Short ATR (3-day) with min_periods=1
    df["atr"] = df["true_range"].rolling(window=3, min_periods=1).mean()

    # ATR as % of price
    df["atr_pct"] = df["atr"] / df["close"]

    # Volume moving average & spike (3-day)
    df["vol_ma"] = df["volume"].rolling(window=3, min_periods=1).mean()
    df["vol_spike"] = df["volume"] / df["vol_ma"]

    # Gap vs previous close (today's open vs yesterday's close)
    df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"]

    return df


def score_row(row: pd.Series) -> float:
    """
    Combine features into a single 'interestingness' score.
    Tuned to work even with small history.
    """
    score = 0.0

    atr_pct = row.get("atr_pct")
    vol_spike = row.get("vol_spike")
    gap_pct = row.get("gap_pct")
    ret = row.get("return")

    # ATR% - baseline volatility
    if pd.notna(atr_pct):
        score += float(atr_pct) * 100  # e.g. 0.02 -> +2

    # Volume spike - interest
    if pd.notna(vol_spike):
        # anything above 1 is extra interest
        score += max(0.0, float(vol_spike) - 1.0) * 2.0

    # Gap - overnight surprise
    if pd.notna(gap_pct):
        score += abs(float(gap_pct)) * 10.0

    # Intraday move
    if pd.notna(ret):
        score += abs(float(ret)) * 10.0

    return score


def score_symbol_for_date(
    db: Session,
    symbol: str,
    target_date: date,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
) -> Dict[str, Any] | None:
    """
    Compute features and a score for a single symbol on a given date.
    Returns dict with metrics, or None if there is no data at all.
    """
    df = get_price_history(db, symbol, target_date, lookback_days=lookback_days)
    if df.empty:
        return None

    df = compute_basic_features(df)

    row = df[df["date"] == target_date]
    if row.empty:
        return None

    row = row.iloc[0]
    score = score_row(row)

    return {
        "symbol": symbol,
        "date": target_date,
        "score": float(score),
        "atr_pct": float(row.get("atr_pct") or 0.0),
        "vol_spike": float(row.get("vol_spike") or 0.0),
        "gap_pct": float(row.get("gap_pct") or 0.0),
        "return": float(row.get("return") or 0.0),
    }


def score_all_symbols_for_date(
    db: Session,
    target_date: date,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Score all symbols in stocks table for a given date, return top N.
    """
    symbols = db.scalars(select(Stock.symbol)).all()
    results: List[Dict[str, Any]] = []

    for symbol in symbols:
        metrics = score_symbol_for_date(
            db, symbol, target_date, lookback_days=lookback_days
        )
        if metrics is not None:
            # even if score is 0, include it; we'll sort anyway
            results.append(metrics)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
