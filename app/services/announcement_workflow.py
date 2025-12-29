"""
LangGraph workflow for BSE announcement scraping, classification, and stock research.
"""
from datetime import date
from typing import Dict, Any, List, TypedDict, Optional
from datetime import date

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.core.logging_utils import get_logger
from app.services.bse_scraper import ingest_bse_announcements
from app.services.announcement_classifier import (
    filter_high_volatility_announcements,
    deduplicate_announcements_by_symbol,
    deduplicate_announcements_by_symbol_pre_classification,
)
from app.services.stock_researcher import research_multiple_stocks
from app.services.universe import get_fno_symbols
from app.db.models import BSEEvent

logger = get_logger(__name__)


class WorkflowState(TypedDict):
    """State for the announcement workflow."""
    target_date: date
    announcements: List[Dict[str, Any]]
    high_vol_announcements: List[Dict[str, Any]]
    research_results: List[Dict[str, Any]]
    errors: List[str]
    step: str


def scrape_announcements(state: WorkflowState, db: Session) -> WorkflowState:
    """Step 1: Scrape BSE announcements."""
    logger.info(f"Step 1: Scraping BSE announcements for {state['target_date']}")
    
    try:
        # Scrape and ingest announcements
        inserted = ingest_bse_announcements(
            db=db,
            target_date=state["target_date"],
            lookback_days=1
        )
        
        # Fetch recent announcements from database
        from datetime import timedelta
        since = state["target_date"] - timedelta(days=2)
        
        events = (
            db.query(BSEEvent)
            .filter(BSEEvent.event_date >= since)
            .filter(BSEEvent.event_date <= state["target_date"])
            .order_by(BSEEvent.event_date.desc())
            .all()
        )
        
        announcements = []
        for event in events:
            announcements.append({
                "symbol": event.symbol,
                "headline": event.headline,
                "event_date": event.event_date,
                "url": event.url,
                "category": event.category,
                "source": event.source,
            })
        
        logger.info(f"Found {len(announcements)} announcements")
        
        # Filter to only FNO universe stocks BEFORE classification to avoid wasting LLM calls
        fno_symbols = set(s.upper() for s in get_fno_symbols())
        fno_announcements = []
        skipped_symbols = set()
        
        for ann in announcements:
            symbol = ann.get("symbol")
            if symbol and symbol.upper() in fno_symbols:
                fno_announcements.append(ann)
            elif symbol:
                skipped_symbols.add(symbol.upper())
        
        if skipped_symbols:
            logger.info(
                f"Filtered out {len(announcements) - len(fno_announcements)} announcements "
                f"for {len(skipped_symbols)} stocks not in FNO universe "
                f"(examples: {', '.join(list(skipped_symbols)[:5])})"
            )
        
        logger.info(f"Proceeding with {len(fno_announcements)} announcements from FNO universe stocks")
        
        return {
            **state,
            "announcements": fno_announcements,
            "step": "scraped",
        }
        
    except Exception as e:
        logger.error(f"Error scraping announcements: {e}")
        return {
            **state,
            "errors": state.get("errors", []) + [f"Scraping error: {str(e)}"],
            "step": "error",
        }


def classify_announcements(state: WorkflowState, max_classifications: int = 20) -> WorkflowState:
    """Step 2: Classify announcements for high volatility potential."""
    logger.info("Step 2: Classifying announcements for high volatility")
    
    announcements = state.get("announcements", [])
    
    if not announcements:
        logger.warning("No announcements to classify")
        return {
            **state,
            "high_vol_announcements": [],
            "step": "classified",
        }
    
    try:
        # Deduplicate BEFORE classification to avoid wasting LLM calls on duplicates
        # Pick one announcement per symbol (preferring results/orders)
        deduplicated = deduplicate_announcements_by_symbol_pre_classification(announcements)
        
        # Filter for high volatility announcements
        # Limit classifications to avoid hitting Groq rate limits
        high_vol = filter_high_volatility_announcements(
            announcements=deduplicated,
            min_confidence="medium",
            max_classifications=max_classifications
        )
        
        # Final deduplication after classification (in case classification changes priorities)
        high_vol = deduplicate_announcements_by_symbol(high_vol)
        
        logger.info(f"Found {len(high_vol)} high-volatility announcements (after deduplication)")
        
        return {
            **state,
            "high_vol_announcements": high_vol,
            "step": "classified",
        }
        
    except Exception as e:
        logger.error(f"Error classifying announcements: {e}")
        return {
            **state,
            "errors": state.get("errors", []) + [f"Classification error: {str(e)}"],
            "step": "error",
        }


def research_stocks(state: WorkflowState, db: Session) -> WorkflowState:
    """Step 3: Research stocks with high-volatility announcements."""
    logger.info("Step 3: Researching stocks with announcements")
    
    high_vol = state.get("high_vol_announcements", [])
    
    if not high_vol:
        logger.warning("No high-volatility announcements to research")
        return {
            **state,
            "research_results": [],
            "step": "completed",
        }
    
    try:
        # Research each stock
        research_results = research_multiple_stocks(db=db, announcements=high_vol)
        
        # Filter to only trade-ready stocks (confidence >= 60, has liquidity)
        trade_ready = [
            r for r in research_results
            if r.get("final_recommendation", {}).get("trade_ready", False)
        ]
        
        logger.info(f"Researched {len(research_results)} stocks, {len(trade_ready)} are trade-ready")
        
        return {
            **state,
            "research_results": research_results,
            "step": "completed",
        }
        
    except Exception as e:
        logger.error(f"Error researching stocks: {e}")
        return {
            **state,
            "errors": state.get("errors", []) + [f"Research error: {str(e)}"],
            "step": "error",
        }


def create_announcement_workflow(db: Session, max_classifications: int = 20) -> StateGraph:
    """
    Create the LangGraph workflow for announcement processing.
    
    Args:
        db: Database session
        
    Returns:
        Compiled StateGraph workflow
    """
    # Create the graph
    workflow = StateGraph(WorkflowState)
    
    # Add nodes
    workflow.add_node("scrape", lambda state: scrape_announcements(state, db))
    workflow.add_node("classify", lambda state: classify_announcements(state, max_classifications))
    workflow.add_node("research", lambda state: research_stocks(state, db))
    
    # Define the flow
    workflow.set_entry_point("scrape")
    workflow.add_edge("scrape", "classify")
    workflow.add_edge("classify", "research")
    workflow.add_edge("research", END)
    
    # Compile the workflow
    app = workflow.compile()
    
    return app


def run_daily_announcement_pipeline(
    db: Session,
    target_date: Optional[date] = None,
    max_classifications: int = 20
) -> Dict[str, Any]:
    """
    Run the complete daily pipeline for BSE announcements.
    
    Args:
        db: Database session
        target_date: Date to process (defaults to today)
        
    Returns:
        Dictionary with workflow results including:
        - announcements: All scraped announcements
        - high_vol_announcements: Filtered high-volatility announcements
        - research_results: Stock research results
        - trade_recommendations: Final trade-ready recommendations
    """
    if target_date is None:
        target_date = date.today()
    
    logger.info(f"Running daily announcement pipeline for {target_date}")
    
    # Create workflow
    app = create_announcement_workflow(db, max_classifications=max_classifications)
    
    # Initial state
    initial_state: WorkflowState = {
        "target_date": target_date,
        "announcements": [],
        "high_vol_announcements": [],
        "research_results": [],
        "errors": [],
        "step": "started",
    }
    
    # Run workflow
    try:
        final_state = app.invoke(initial_state)
        
        # Extract trade-ready recommendations
        research_results = final_state.get("research_results", [])
        trade_recommendations = [
            r for r in research_results
            if r.get("final_recommendation", {}).get("trade_ready", False)
        ]
        
        return {
            "target_date": target_date,
            "announcements": final_state.get("announcements", []),
            "high_vol_announcements": final_state.get("high_vol_announcements", []),
            "research_results": research_results,
            "trade_recommendations": trade_recommendations,
            "errors": final_state.get("errors", []),
            "summary": {
                "total_announcements": len(final_state.get("announcements", [])),
                "high_vol_count": len(final_state.get("high_vol_announcements", [])),
                "researched_count": len(research_results),
                "trade_ready_count": len(trade_recommendations),
            },
        }
        
    except Exception as e:
        logger.error(f"Workflow execution error: {e}")
        return {
            "target_date": target_date,
            "error": str(e),
            "announcements": [],
            "high_vol_announcements": [],
            "research_results": [],
            "trade_recommendations": [],
        }

