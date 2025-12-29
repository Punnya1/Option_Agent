"""
Service to research stocks with great announcements - combines OI, volume, and price action.
"""
from datetime import date
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.core.logging_utils import get_logger
from app.services.signals import score_symbol_for_date, get_price_history
from app.services.options import get_options_liquidity
from app.services.universe import get_fno_symbols
from app.candidate.candidate_access import classify_direction_and_strategy

logger = get_logger(__name__)


def research_stock_with_announcement(
    db: Session,
    symbol: str,
    announcement_date: date,
    classification: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Research a stock that has a high-volatility announcement.
    Combines announcement impact with technical analysis (OI, volume, price action).
    
    Args:
        db: Database session
        symbol: Stock symbol
        announcement_date: Date of the announcement
        classification: LLM classification of the announcement
        
    Returns:
        Dictionary with comprehensive research including:
        - Announcement details and classification
        - Technical metrics (OI, volume, price action)
        - Trading recommendation
    """
    symbol_upper = symbol.upper()
    logger.info(f"Researching {symbol_upper} for announcement on {announcement_date}")
    
    # Check if stock is in FNO universe
    fno_symbols = get_fno_symbols()
    if symbol_upper not in fno_symbols:
        logger.warning(
            f"{symbol_upper} is not in FNO universe - skipping technical research. "
            f"Announcement may still be valid but options trading not available."
        )
        return {
            "symbol": symbol_upper,
            "announcement_date": announcement_date,
            "announcement": {
                "headline": classification.get("headline", ""),
                "event_type": classification.get("event_type"),
                "direction": classification.get("ai_direction"),
                "reaction_window": classification.get("reaction_window"),
                "confidence": classification.get("confidence"),
                "explanation": classification.get("explanation", ""),
            },
            "technicals": {
                "direction": "unknown",
                "strategy_hint": "Stock not in FNO universe",
                "daily_return": None,
                "vol_spike": None,
                "atr_pct": None,
                "gap_pct": None,
                "spot_price": None,
            },
            "options_liquidity": {
                "total_oi": 0,
                "total_volume": 0,
                "expiry": None,
            },
            "final_recommendation": {
                "direction": classification.get("ai_direction", "neutral"),
                "confidence_score": 30,  # Lower score since no options available
                "trade_ready": False,
                "suggested_strategy": f"Stock not in FNO universe - cannot trade options. Announcement suggests {classification.get('ai_direction', 'neutral')} direction.",
            },
            "note": "Stock not in FNO universe - options trading not available",
        }
    
    # Get technical metrics for the announcement date
    # Try multiple dates: announcement date, then previous days (up to 5 days back)
    metrics = None
    used_date = None
    from datetime import timedelta
    
    for days_back in range(6):  # Try 0 to 5 days back
        try_date = announcement_date - timedelta(days=days_back)
        metrics = score_symbol_for_date(db, symbol_upper, try_date)
        if metrics:
            used_date = try_date
            if days_back > 0:
                logger.info(f"Using data from {try_date} ({(announcement_date - try_date).days} days before announcement) for {symbol_upper}")
            break
    
    # If still no metrics, return basic research with just announcement data
    if not metrics:
        logger.warning(
            f"No technical metrics found for {symbol_upper} on {announcement_date} "
            f"or up to 5 days before. Possible reasons: "
            f"1. Data not ingested for this date range, "
            f"2. Stock may not have traded recently, "
            f"3. Date may be a non-trading day"
        )
        # Return research with just announcement classification (no technicals)
        return {
            "symbol": symbol_upper,
            "announcement_date": announcement_date,
            "announcement": {
                "headline": classification.get("headline", ""),
                "event_type": classification.get("event_type"),
                "direction": classification.get("ai_direction"),
                "reaction_window": classification.get("reaction_window"),
                "confidence": classification.get("confidence"),
                "explanation": classification.get("explanation", ""),
            },
            "technicals": {
                "direction": "unknown",
                "strategy_hint": "No technical data available",
                "daily_return": None,
                "vol_spike": None,
                "atr_pct": None,
                "gap_pct": None,
                "spot_price": None,
            },
            "options_liquidity": {
                "total_oi": 0,
                "total_volume": 0,
                "expiry": None,
            },
            "final_recommendation": {
                "direction": classification.get("ai_direction", "neutral"),
                "confidence_score": 50 if classification.get("confidence") == "high" else 30,
                "trade_ready": False,  # Can't trade without technical data
                "suggested_strategy": f"Wait for technical data. Announcement suggests {classification.get('ai_direction', 'neutral')} direction.",
            },
            "note": "No technical data available - recommendation based on announcement only. Check if data is ingested for this date range.",
        }
    
    # Get options liquidity - try announcement date first, then used_date if different
    liquidity = None
    for try_date in [announcement_date, used_date] if used_date and used_date != announcement_date else [announcement_date]:
        liquidity = get_options_liquidity(db, symbol_upper, try_date, moneyness_band=0.1)
        if liquidity:
            break
        # Try wider band
        liquidity = get_options_liquidity(db, symbol_upper, try_date, moneyness_band=0.2)
        if liquidity:
            break
    
    # Get price history for context - use used_date if available
    price_history = get_price_history(
        db, symbol_upper, 
        used_date if used_date else announcement_date, 
        lookback_days=10
    )
    
    # Classify direction based on technicals
    direction, strategy_hint = classify_direction_and_strategy(metrics)
    
    # Combine announcement direction with technical direction
    announcement_direction = classification.get("ai_direction", "neutral")
    reaction_window = classification.get("reaction_window", "next_day")
    
    # Determine final recommendation
    # If announcement is bullish and technicals are bullish -> strong bullish
    # If announcement is bearish and technicals are bearish -> strong bearish
    # If they conflict -> neutral or wait
    
    final_direction = "neutral"
    if announcement_direction == "bullish" and direction in ["bullish", "neutral"]:
        final_direction = "bullish"
    elif announcement_direction == "bearish" and direction in ["bearish", "neutral"]:
        final_direction = "bearish"
    elif announcement_direction == direction and direction != "neutral":
        final_direction = direction  # Both agree
    else:
        final_direction = "neutral"  # Conflict or both neutral
    
    # Calculate confidence score (0-100)
    confidence_score = 50  # Base
    
    # Increase confidence if announcement and technicals agree
    if announcement_direction == direction and direction != "neutral":
        confidence_score += 20
    
    # Increase based on announcement confidence
    ann_confidence = classification.get("confidence", "low")
    if ann_confidence == "high":
        confidence_score += 15
    elif ann_confidence == "medium":
        confidence_score += 10
    
    # Increase based on technical strength
    vol_spike = metrics.get("vol_spike", 0) or 0
    daily_return = abs(metrics.get("return", 0) or 0)
    
    if vol_spike > 1.5:
        confidence_score += 10
    if daily_return > 0.03:
        confidence_score += 10
    
    confidence_score = min(confidence_score, 100)
    
    # Build recommendation
    recommendation = {
        "symbol": symbol_upper,
        "announcement_date": announcement_date,
        "announcement": {
            "headline": classification.get("headline", ""),
            "event_type": classification.get("event_type"),
            "direction": announcement_direction,
            "reaction_window": reaction_window,
            "confidence": ann_confidence,
            "explanation": classification.get("explanation", ""),
        },
        "technicals": {
            "direction": direction,
            "strategy_hint": strategy_hint,
            "daily_return": metrics.get("return", 0),
            "vol_spike": vol_spike,
            "atr_pct": metrics.get("atr_pct", 0),
            "gap_pct": metrics.get("gap_pct", 0),
            "spot_price": liquidity.get("spot") if liquidity else None,
        },
        "options_liquidity": {
            "total_oi": liquidity.get("total_oi", 0) if liquidity else 0,
            "total_volume": liquidity.get("total_volume", 0) if liquidity else 0,
            "expiry": liquidity.get("expiry") if liquidity else None,
        },
        "final_recommendation": {
            "direction": final_direction,
            "confidence_score": confidence_score,
            "trade_ready": confidence_score >= 60 and liquidity and liquidity.get("total_oi", 0) > 0,
            "suggested_strategy": _generate_strategy_recommendation(
                final_direction, announcement_direction, direction, 
                liquidity, metrics, reaction_window
            ),
        },
    }
    
    return recommendation


def _generate_strategy_recommendation(
    final_direction: str,
    announcement_dir: str,
    technical_dir: str,
    liquidity: Optional[Dict[str, Any]],
    metrics: Dict[str, Any],
    reaction_window: str
) -> str:
    """Generate a specific options trading strategy recommendation."""
    
    if final_direction == "neutral":
        return "Wait for clearer signals or trade intraday only"
    
    atr_pct = metrics.get("atr_pct", 0) or 0
    total_oi = liquidity.get("total_oi", 0) if liquidity else 0
    
    if reaction_window == "same_day":
        timing = "immediate"
    elif reaction_window == "next_day":
        timing = "next trading session"
    else:
        timing = "within 1-3 days"
    
    if final_direction == "bullish":
        if atr_pct < 0.04:
            return f"Buy near-ATM call options ({timing}) - low volatility, expect sharp move"
        else:
            return f"Bull call spread ({timing}) - buy ATM call, sell OTM call to reduce cost"
    else:  # bearish
        if atr_pct < 0.04:
            return f"Buy near-ATM put options ({timing}) - low volatility, expect sharp move"
        else:
            return f"Bear put spread ({timing}) - buy ATM put, sell OTM put to reduce cost"


def research_multiple_stocks(
    db: Session,
    announcements: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Research multiple stocks with announcements.
    
    Args:
        db: Database session
        announcements: List of announcement dicts with symbol, event_date, classification
        
    Returns:
        List of research results, sorted by confidence score
    """
    results = []
    
    for ann in announcements:
        symbol = ann.get("symbol")
        event_date = ann.get("event_date")
        classification = ann.get("classification", {})
        
        if not symbol or not event_date:
            continue
        
        try:
            research = research_stock_with_announcement(
                db, symbol, event_date, classification
            )
            results.append(research)
        except Exception as e:
            logger.error(f"Error researching {symbol}: {e}")
            continue
    
    # Sort by confidence score (highest first)
    results.sort(
        key=lambda x: x.get("final_recommendation", {}).get("confidence_score", 0),
        reverse=True
    )
    
    return results

