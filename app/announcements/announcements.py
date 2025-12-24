"""
API endpoints for BSE announcement pipeline.
"""
from datetime import date
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.sessions import get_db
from app.core.logging_utils import get_logger
from app.services.announcement_workflow import run_daily_announcement_pipeline

logger = get_logger(__name__)
router = APIRouter(prefix="/announcements", tags=["Announcements"])


class TradeRecommendation(BaseModel):
    """Trade recommendation model."""
    symbol: str
    announcement_date: str
    direction: str
    confidence_score: int
    suggested_strategy: str
    announcement_headline: str
    technical_direction: str


class PipelineResponse(BaseModel):
    """Response model for pipeline execution."""
    target_date: str
    summary: Dict[str, int]
    trade_recommendations: List[TradeRecommendation]
    errors: List[str]


@router.post("/run-pipeline", response_model=PipelineResponse)
def run_pipeline(
    target_date: date = Query(None, description="Date to process (defaults to today)"),
    db: Session = Depends(get_db),
):
    """
    Run the complete BSE announcement pipeline:
    1. Scrape BSE corporate announcements
    2. Classify for high volatility potential
    3. Research stocks with great announcements
    4. Return trade-ready recommendations
    """
    try:
        result = run_daily_announcement_pipeline(db=db, target_date=target_date)
        
        # Format trade recommendations
        trade_recs = []
        for rec in result.get("trade_recommendations", []):
            final_rec = rec.get("final_recommendation", {})
            announcement = rec.get("announcement", {})
            technicals = rec.get("technicals", {})
            
            trade_recs.append(TradeRecommendation(
                symbol=rec.get("symbol", ""),
                announcement_date=str(rec.get("announcement_date", "")),
                direction=final_rec.get("direction", "neutral"),
                confidence_score=final_rec.get("confidence_score", 0),
                suggested_strategy=final_rec.get("suggested_strategy", ""),
                announcement_headline=announcement.get("headline", ""),
                technical_direction=technicals.get("direction", "neutral"),
            ))
        
        return PipelineResponse(
            target_date=str(result.get("target_date", "")),
            summary=result.get("summary", {}),
            trade_recommendations=trade_recs,
            errors=result.get("errors", []),
        )
        
    except Exception as e:
        logger.error(f"Pipeline execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/research/{symbol}")
def get_stock_research(
    symbol: str,
    announcement_date: date = Query(..., description="Date of the announcement"),
    db: Session = Depends(get_db),
):
    """
    Research a specific stock with an announcement on a given date.
    """
    from app.services.stock_researcher import research_stock_with_announcement
    from app.db.models import BSEEvent
    
    # Find the announcement
    event = (
        db.query(BSEEvent)
        .filter(BSEEvent.symbol == symbol.upper())
        .filter(BSEEvent.event_date == announcement_date)
        .first()
    )
    
    if not event:
        raise HTTPException(
            status_code=404,
            detail=f"No announcement found for {symbol} on {announcement_date}"
        )
    
    # Classify the announcement
    from app.services.announcement_classifier import classify_announcement
    
    classification = classify_announcement(
        symbol=event.symbol,
        headline=event.headline,
        event_date=str(event.event_date),
        category=event.category,
    )
    
    # Research the stock
    research = research_stock_with_announcement(
        db=db,
        symbol=symbol.upper(),
        announcement_date=announcement_date,
        classification=classification,
    )
    
    return research

