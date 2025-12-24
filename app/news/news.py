from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
import logging
import json

from app.core.config import settings
from app.core.logging_utils import get_logger
from app.db.sessions import get_db
from app.news.news_service import fetch_news_for_symbol
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.news.news_validator import AIResponseSchema, AIStockNewsView
logger = get_logger(__name__)
router = APIRouter(prefix="/news", tags=["News"])


prompt_template = ChatPromptTemplate.from_template(
    """
You are an experienced Indian market derivatives analyst. You are given:
- symbol: {symbol}
- window_days: {window_days}
- A blob of recent news/events (each item on its own line). Example lines:
  Title: <headline> | Published: <date> | URL: <url>

Recent news/events:
{news_blob}

Task:
1) Summarize the main developments in 2-4 sentences.
2) Give a single-line directional view for the NEXT 1-3 trading sessions: one of "bullish", "bearish", or "neutral".
3) Return a one-line suggested options strategy (concise).
4) Give a short confidence tag: "low", "medium", or "high".

Return JSON with keys:
{format_instructions}
"""
)

# Output parser schema

parser = JsonOutputParser(pydantic_object=AIResponseSchema)

# LLM client
llm = ChatGroq(
    model="llama-3.1-8b-instant", 
    temperature=0.15,
    groq_api_key=settings.groq_api_key,
)

chain = prompt_template | llm | parser


@router.get("/{symbol}/news-ai", response_model=AIStockNewsView)
def stock_news_ai(
    symbol: str,
    window_days: int = Query(7, ge=1, le=30),
    max_items: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    Return recent news/events for a symbol and an AI-generated short view.
    GET /stocks/JSWENERGY/news-ai?window_days=7
    """
    symbol = symbol.upper().strip()
    logger.info("Request news-ai for symbol=%s window_days=%d", symbol, window_days)

    events = fetch_news_for_symbol(symbol, window_days=window_days, max_items=max_items)

    if not events:
        logger.info("No news found for %s in last %d days", symbol, window_days)
    news_text_lines = []
    for e in events:
        published = e.get("published_at") or e.get("published") or ""
        title = e.get("title") or e.get("headline") or ""
        url = e.get("url") or ""
        news_text_lines.append(f"Title: {title}\nPublished: {published}\nURL: {url}\n")

    news_blob = "\n\n".join(news_text_lines) or "No news found."

    payload = {
        "symbol": symbol,
        "window_days": window_days,
        "news_blob": news_blob[:4000],  
        "format_instructions": parser.get_format_instructions(),
    }

    try:
        ai_resp = chain.invoke(payload)
    except Exception as e:
        logger.exception("LLM call failed for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail="AI annotation failed")

    try:
        ai_dict = ai_resp.dict() if not isinstance(ai_resp, dict) else ai_resp
    except Exception:
        try:
            ai_dict = json.loads(ai_resp)
        except Exception:
            ai_dict = {
                "ai_direction": None,
                "ai_confidence": "low",
                "ai_explanation": str(ai_resp),
                "suggested_strategy": None,
            }

    out = {
        "symbol": symbol,
        "window_days": window_days,
        "events": events,
        "ai_direction": ai_dict.get("ai_direction"),
        "ai_confidence": ai_dict.get("ai_confidence"),
        "ai_explanation": ai_dict.get("ai_explanation"),
        "suggested_strategy": ai_dict.get("suggested_strategy"),
    }

    logger.info("Returning news-ai for %s: direction=%s confidence=%s", symbol, out["ai_direction"], out["ai_confidence"])
    return out
