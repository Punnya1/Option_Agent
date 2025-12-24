"""
LLM-based service to classify BSE announcements for high volatility potential.
"""
from typing import Dict, Any, Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.config import settings
from app.core.logging_utils import get_logger
from app.ai.ai_validator import AIEventImpact

logger = get_logger(__name__)

# Prompt template for classifying announcements
classification_prompt = ChatPromptTemplate.from_template(
    """
You are an expert Indian stock market analyst specializing in derivatives trading.
You analyze corporate announcements to predict which ones will cause high volatility
in stock prices the NEXT trading day, making them suitable for options trading.

Given a corporate announcement headline and context, classify:
1. Event type (results_positive, results_negative, order_win, order_loss, fund_raise, regulatory, neutral)
2. Expected market direction (bullish, bearish, neutral)
3. When the reaction will occur (same_day, next_day, 1_3_days)
4. Confidence level (low, medium, high)
5. Brief explanation

Guidelines:
- Focus on events that typically cause 2%+ price moves (high volatility)
- Results announcements (Q1, Q2, Q3, Q4) are usually high impact
- Large order wins/losses (>10% of revenue) are high impact
- Fund raising (QIP, rights issue) can be volatile
- Regulatory actions can cause high volatility
- Routine announcements (board meetings, AGM notices) are usually neutral/low impact
- Be conservative: only mark as high confidence if the event is clearly significant

Announcement Details:
- Symbol: {symbol}
- Headline: {headline}
- Date: {event_date}
- Category: {category}

Return JSON matching this schema:
{format_instructions}
"""
)

# Output parser
parser = JsonOutputParser(pydantic_object=AIEventImpact)

# LLM client
llm = ChatGroq(
    model="llama-3.3-70b-versatile",  # Changed from model_name to model for langchain-core 1.x
    temperature=0.2,
    groq_api_key=settings.groq_api_key,
)

# Chain
classification_chain = classification_prompt | llm | parser


def classify_announcement(
    symbol: str,
    headline: str,
    event_date: str,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Classify a BSE announcement using LLM to determine volatility potential.
    
    Args:
        symbol: Stock symbol
        headline: Announcement headline
        event_date: Event date (string format)
        category: Optional category (results, order, etc.)
        
    Returns:
        Dictionary with event_type, ai_direction, reaction_window, confidence, explanation
    """
    try:
        result = classification_chain.invoke({
            "symbol": symbol,
            "headline": headline,
            "event_date": event_date,
            "category": category or "unknown",
            "format_instructions": parser.get_format_instructions(),
        })
        
        logger.debug(f"Classified announcement for {symbol}: {result.get('ai_direction')} ({result.get('confidence')} confidence)")
        return result
        
    except Exception as e:
        logger.error(f"Error classifying announcement for {symbol}: {e}")
        # Return neutral/default classification on error
        return {
            "event_type": "neutral",
            "ai_direction": "neutral",
            "reaction_window": "1_3_days",
            "confidence": "low",
            "explanation": f"Classification error: {str(e)}",
        }


def filter_high_volatility_announcements(
    announcements: list[Dict[str, Any]],
    min_confidence: str = "medium",
    max_classifications: int = 20  # Limit LLM calls to avoid rate limits
) -> list[Dict[str, Any]]:
    """
    Filter announcements that are likely to cause high volatility.
    
    Args:
        announcements: List of announcement dicts with symbol, headline, event_date, etc.
        min_confidence: Minimum confidence level ("low", "medium", "high")
        max_classifications: Maximum number of announcements to classify (to limit LLM calls)
        
    Returns:
        Filtered list of high-volatility announcements with classification
    """
    confidence_levels = {"low": 1, "medium": 2, "high": 3}
    min_level = confidence_levels.get(min_confidence, 2)
    
    high_vol_announcements = []
    
    # Limit the number of announcements to classify to avoid hitting LLM rate limits
    announcements_to_process = announcements[:max_classifications]
    logger.info(f"Classifying {len(announcements_to_process)} out of {len(announcements)} announcements (limited to avoid rate limits)")
    
    for ann in announcements_to_process:
        symbol = ann.get("symbol")
        headline = ann.get("headline")
        event_date = ann.get("event_date")
        category = ann.get("category")
        
        if not symbol or not headline:
            continue
        
        # Classify using LLM
        classification = classify_announcement(
            symbol=symbol,
            headline=headline,
            event_date=str(event_date) if event_date else "",
            category=category,
        )
        
        # Filter based on confidence and direction
        conf_level = confidence_levels.get(classification.get("confidence", "low"), 1)
        direction = classification.get("ai_direction", "neutral")
        
        # Include if:
        # 1. Confidence meets threshold
        # 2. Direction is not neutral (bullish or bearish)
        if conf_level >= min_level and direction != "neutral":
            # Add classification to announcement dict
            classification["headline"] = headline  # Include headline in classification
            ann["classification"] = classification
            high_vol_announcements.append(ann)
            logger.info(
                f"High volatility announcement: {symbol} - {headline[:50]}... "
                f"({direction}, {classification.get('confidence')} confidence)"
            )
    
    logger.info(f"Found {len(high_vol_announcements)} high-volatility announcements after LLM classification")
    return high_vol_announcements

