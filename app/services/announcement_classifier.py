"""
LLM-based service to classify BSE announcements for high volatility potential.
"""
import time
from typing import Dict, Any, Optional, List
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.config import settings
from app.core.logging_utils import get_logger
from app.ai.ai_validator import AIEventImpact

logger = get_logger(__name__)

# Rate limiting: delay between LLM calls to avoid hitting Groq limits
# Groq free tier: ~30 requests/minute, paid: higher
LLM_CALL_DELAY = 2.0  # seconds between calls (30 calls = 60 seconds = 1 minute)

# High-impact keywords that typically cause significant stock movement
HIGH_IMPACT_KEYWORDS = [
    # Results announcements (highest impact)
    "result", "quarter", "q1", "q2", "q3", "q4", "annual", "financial",
    "earnings", "profit", "revenue", "loss", "guidance", "outlook",
    
    # Orders and contracts (high impact)
    "order", "contract", "tender", "award", "loi", "mou", "agreement",
    "deal", "partnership", "win", "bagged", "received",
    
    # Corporate actions (high impact)
    "merger", "acquisition", "takeover", "buyback", "dividend",
    "bonus", "split", "demerger", "amalgamation",
    
    # Fund raising (high impact)
    "fund raising", "qip", "fpo", "rights issue", "preferential",
    "private placement", "ipo", "offer",
    
    # Regulatory/legal (high impact)
    "sebi", "regulatory", "investigation", "penalty", "fine",
    "court", "litigation", "settlement", "approval", "license",
    
    # Business updates (medium-high impact)
    "expansion", "capacity", "plant", "facility", "project",
    "commissioning", "launch", "new product", "breakthrough",
    
    # Management changes (medium impact)
    "ceo", "md", "director", "resignation", "appointment",
    "board", "management",
]

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
- Results announcements (Q1, Q2, Q3, Q4) are usually high impact - mark as bullish/bearish with medium+ confidence
- Large order wins/losses (>10% of revenue) are high impact - mark as bullish/bearish
- Fund raising (QIP, rights issue) can be volatile - usually bearish short-term
- Regulatory actions can cause high volatility - mark direction based on impact
- Corporate actions (mergers, buybacks) are usually bullish
- Routine announcements (board meetings, AGM notices) are usually neutral/low impact
- IMPORTANT: If an announcement has keywords like "result", "quarter", "order", "contract", "merger", 
  it's likely high-impact. Mark it as bullish or bearish (not neutral) with at least medium confidence.
- Be reasonable: Don't be overly conservative. If it's clearly a results announcement or major order, 
  it WILL move the stock - mark it accordingly.

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


def pre_filter_high_impact_announcements(
    announcements: List[Dict[str, Any]],
    max_results: int = 30
) -> List[Dict[str, Any]]:
    """
    Pre-filter announcements by keywords to prioritize high-impact events
    before sending to LLM. This reduces LLM calls and focuses on announcements
    most likely to cause significant stock movement.
    
    Note: Assumes announcements are already filtered to FNO universe stocks.
    
    Args:
        announcements: List of announcement dicts with headline, symbol, etc.
        max_results: Maximum number of announcements to return
        
    Returns:
        Filtered list prioritized by keyword matches
    """
    if not announcements:
        return []
    
    scored_announcements = []
    
    for ann in announcements:
        headline = ann.get("headline", "").lower()
        category = ann.get("category", "").lower() if ann.get("category") else ""
        combined_text = f"{headline} {category}"
        
        # Calculate score based on keyword matches
        score = 0
        
        # Check for high-impact keywords
        for keyword in HIGH_IMPACT_KEYWORDS:
            if keyword.lower() in combined_text:
                # Results and orders get highest priority
                if keyword in ["result", "quarter", "q1", "q2", "q3", "q4", "order", "contract", "tender", "award"]:
                    score += 3
                # Corporate actions and fund raising get high priority
                elif keyword in ["merger", "acquisition", "fund raising", "qip", "buyback", "dividend"]:
                    score += 2
                # Other keywords get medium priority
                else:
                    score += 1
        
        # Boost score for certain categories
        if "result" in category:
            score += 5
        elif "corp. action" in category or "corporate action" in category:
            score += 3
        elif "board meeting" in category:
            score += 2
        
        # Only include announcements with at least one keyword match
        if score > 0:
            scored_announcements.append((score, ann))
    
    # Sort by score (highest first)
    scored_announcements.sort(key=lambda x: x[0], reverse=True)
    
    # Return top N
    filtered = [ann for _, ann in scored_announcements[:max_results]]
    
    logger.info(
        f"Pre-filtered {len(filtered)} high-impact announcements from {len(announcements)} "
        f"(top {max_results} by keyword relevance)"
    )
    
    return filtered

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
    
    First pre-filters by keywords to prioritize high-impact announcements,
    then uses LLM to classify them.
    
    Args:
        announcements: List of announcement dicts with symbol, headline, event_date, etc.
        min_confidence: Minimum confidence level ("low", "medium", "high")
        max_classifications: Maximum number of announcements to classify (to limit LLM calls)
        
    Returns:
        Filtered list of high-volatility announcements with classification
    """
    confidence_levels = {"low": 1, "medium": 2, "high": 3}
    min_level = confidence_levels.get(min_confidence, 2)
    
    # Step 1: Pre-filter by keywords to prioritize high-impact announcements
    pre_filtered = pre_filter_high_impact_announcements(
        announcements, 
        max_results=max_classifications
    )
    
    if not pre_filtered:
        logger.warning("No high-impact announcements found after keyword pre-filtering")
        return []
    
    # Step 2: Classify pre-filtered announcements with LLM
    logger.info(
        f"Classifying {len(pre_filtered)} pre-filtered high-impact announcements "
        f"(from {len(announcements)} total) with LLM"
    )
    
    high_vol_announcements = []
    
    announcements_to_process = pre_filtered
    
    for idx, ann in enumerate(announcements_to_process):
        symbol = ann.get("symbol")
        headline = ann.get("headline")
        event_date = ann.get("event_date")
        category = ann.get("category")
        
        if not symbol or not headline:
            continue
        
        # Log the headline being classified (first few for debugging)
        if idx < 3:
            logger.info(f"[Sample {idx+1}] Classifying: {symbol} - {headline[:100]}...")
        
        # Rate limiting: add delay between LLM calls to avoid hitting Groq limits
        if idx > 0:  # Don't delay the first call
            time.sleep(LLM_CALL_DELAY)
        
        # Classify using LLM
        try:
            classification = classify_announcement(
                symbol=symbol,
                headline=headline,
                event_date=str(event_date) if event_date else "",
                category=category,
            )
            
            # Log full LLM response for first few (for debugging)
            if idx < 3:
                logger.info(
                    f"[Sample {idx+1}] LLM Response for {symbol}:\n"
                    f"  Direction: {classification.get('ai_direction')}\n"
                    f"  Confidence: {classification.get('confidence')}\n"
                    f"  Event Type: {classification.get('event_type')}\n"
                    f"  Reaction Window: {classification.get('reaction_window')}\n"
                    f"  Explanation: {classification.get('explanation', '')[:150]}"
                )
        except Exception as e:
            # Handle rate limit errors gracefully
            if "429" in str(e) or "rate limit" in str(e).lower():
                logger.warning(f"Rate limit hit for {symbol}, waiting longer before retry...")
                time.sleep(10)  # Wait 10 seconds on rate limit
                try:
                    classification = classify_announcement(
                        symbol=symbol,
                        headline=headline,
                        event_date=str(event_date) if event_date else "",
                        category=category,
                    )
                except Exception as retry_error:
                    logger.error(f"Failed to classify {symbol} after retry: {retry_error}")
                    continue
            else:
                logger.error(f"Error classifying {symbol}: {e}")
                continue
        
        # Filter based on confidence and direction
        conf_level = confidence_levels.get(classification.get("confidence", "low"), 1)
        direction = classification.get("ai_direction", "neutral")
        event_type = classification.get("event_type", "neutral")
        
        # ALWAYS store classification in announcement dict for logging (even if filtered out)
        classification["headline"] = headline  # Include headline in classification
        ann["classification"] = classification
        
        # Include if:
        # 1. Confidence meets threshold
        # 2. Direction is not neutral (bullish or bearish)
        if conf_level >= min_level and direction != "neutral":
            high_vol_announcements.append(ann)
            logger.info(
                f"✓ High volatility announcement: {symbol} - {headline[:50]}... "
                f"({direction}, {classification.get('confidence')} confidence)"
            )
        else:
            # Log why it was filtered out (for first 5)
            if idx < 5:
                reasons = []
                if conf_level < min_level:
                    reasons.append(f"confidence too low ({classification.get('confidence')} < {min_confidence})")
                if direction == "neutral":
                    reasons.append("direction is neutral")
                logger.info(
                    f"✗ Filtered out {symbol}: {', '.join(reasons) if reasons else 'unknown reason'}"
                )
    
    # Summary logging
    total_classified = len(announcements_to_process)
    logger.info(
        f"LLM Classification Summary: {total_classified} classified, "
        f"{len(high_vol_announcements)} passed filter "
        f"(required: confidence>={min_confidence}, direction!=neutral)"
    )
    
    # Log top 15 classification results (all classified announcements, not just filtered ones)
    # Collect all classifications (including filtered out ones) for logging
    all_classifications = []
    for idx, ann in enumerate(announcements_to_process):
        symbol = ann.get("symbol", "UNKNOWN")
        headline = ann.get("headline", "")
        # Get classification if it was added to the announcement
        classification = ann.get("classification")
        if classification:
            all_classifications.append({
                "symbol": symbol,
                "headline": headline,
                "classification": classification
            })
    
    # Log top 15 classification results
    top_n = min(15, len(all_classifications))
    if top_n > 0:
        logger.info(f"\n{'='*80}")
        logger.info(f"TOP {top_n} LLM CLASSIFICATION RESULTS:")
        logger.info(f"{'='*80}")
        for idx, item in enumerate(all_classifications[:top_n], 1):
            cls = item["classification"]
            logger.info(
                f"\n[{idx}] {item['symbol']}\n"
                f"  Headline: {item['headline'][:120]}...\n"
                f"  Direction: {cls.get('ai_direction', 'N/A')}\n"
                f"  Confidence: {cls.get('confidence', 'N/A')}\n"
                f"  Event Type: {cls.get('event_type', 'N/A')}\n"
                f"  Reaction Window: {cls.get('reaction_window', 'N/A')}\n"
                f"  Explanation: {cls.get('explanation', 'N/A')[:200]}"
            )
        logger.info(f"{'='*80}\n")
    
    if len(high_vol_announcements) == 0 and total_classified > 0:
        logger.warning(
            f"No announcements passed the filter! This might mean:\n"
            f"1. LLM is being too conservative (marking everything as neutral/low confidence)\n"
            f"2. Filter criteria is too strict (min_confidence='{min_confidence}')\n"
            f"3. Today's announcements genuinely aren't high-impact\n"
            f"Consider checking LLM responses or lowering min_confidence to 'low'"
        )
    
    return high_vol_announcements


def deduplicate_announcements_by_symbol_pre_classification(
    announcements: list[Dict[str, Any]]
) -> list[Dict[str, Any]]:
    """
    Deduplicate announcements by symbol BEFORE classification.
    Keeps only the best one per symbol based on headline/category keywords.
    Prioritizes results and orders over other types.
    
    Args:
        announcements: List of announcement dicts with symbol, headline, category (no classification yet)
        
    Returns:
        Deduplicated list with one announcement per symbol
    """
    if not announcements:
        return []
    
    # Group by symbol
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for ann in announcements:
        symbol = ann.get("symbol")
        if not symbol:
            continue
        symbol = symbol.upper()
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(ann)
    
    # For each symbol, pick the best announcement based on keywords
    prioritized = []
    
    for symbol, anns in by_symbol.items():
        if len(anns) == 1:
            prioritized.append(anns[0])
            continue
        
        # Score each announcement to pick the best one (based on keywords only, no classification yet)
        best_ann = None
        best_score = -1
        
        for ann in anns:
            score = 0
            headline = ann.get("headline", "").lower()
            category = ann.get("category", "").lower() if ann.get("category") else ""
            combined = f"{headline} {category}"
            
            # Prioritize results announcements
            if any(kw in combined for kw in ["result", "quarter", "q1", "q2", "q3", "q4", "earnings", "financial"]):
                score += 100
            
            # Prioritize orders/contracts
            if any(kw in combined for kw in ["order", "contract", "tender", "award", "loi", "mou", "win", "bagged"]):
                score += 80
            
            # Prioritize corporate actions
            if any(kw in combined for kw in ["merger", "acquisition", "buyback", "dividend", "bonus", "split"]):
                score += 60
            
            # Prioritize fund raising
            if any(kw in combined for kw in ["fund raising", "qip", "fpo", "rights issue", "preferential"]):
                score += 50
            
            # Boost score for certain categories
            if "result" in category:
                score += 50
            elif "corp. action" in category or "corporate action" in category:
                score += 40
            elif "board meeting" in category:
                score += 10
            
            if score > best_score:
                best_score = score
                best_ann = ann
        
        if best_ann:
            prioritized.append(best_ann)
            if len(anns) > 1:
                logger.info(
                    f"Pre-classification deduplication {symbol}: kept 1 announcement out of {len(anns)} "
                    f"(selected: {best_ann.get('headline', '')[:60]}...)"
                )
    
    logger.info(
        f"Pre-classification deduplication: {len(announcements)} -> {len(prioritized)} "
        f"({len(announcements) - len(prioritized)} duplicates removed)"
    )
    
    return prioritized


def deduplicate_announcements_by_symbol(
    announcements: list[Dict[str, Any]]
) -> list[Dict[str, Any]]:
    """
    Deduplicate announcements by symbol, keeping only the best one per symbol.
    Prioritizes results and orders over other types.
    
    Args:
        announcements: List of announcement dicts with symbol, classification, etc.
        
    Returns:
        Deduplicated list with one announcement per symbol
    """
    if not announcements:
        return []
    
    # Group by symbol
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for ann in announcements:
        symbol = ann.get("symbol")
        if not symbol:
            continue
        symbol = symbol.upper()
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(ann)
    
    # For each symbol, pick the best announcement
    prioritized = []
    
    for symbol, anns in by_symbol.items():
        if len(anns) == 1:
            prioritized.append(anns[0])
            continue
        
        # Score each announcement to pick the best one
        best_ann = None
        best_score = -1
        
        for ann in anns:
            score = 0
            classification = ann.get("classification", {})
            headline = ann.get("headline", "").lower()
            category = ann.get("category", "").lower() if ann.get("category") else ""
            combined = f"{headline} {category}"
            
            # Prioritize results announcements
            if any(kw in combined for kw in ["result", "quarter", "q1", "q2", "q3", "q4", "earnings", "financial"]):
                score += 100
            
            # Prioritize orders/contracts
            if any(kw in combined for kw in ["order", "contract", "tender", "award", "loi", "mou", "win", "bagged"]):
                score += 80
            
            # Prioritize by event type
            event_type = classification.get("event_type", "")
            if event_type in ["results_positive", "results_negative"]:
                score += 50
            elif event_type in ["order_win", "order_loss"]:
                score += 40
            
            # Prioritize by confidence
            confidence = classification.get("confidence", "low")
            if confidence == "high":
                score += 20
            elif confidence == "medium":
                score += 10
            
            # Prioritize by direction (bullish/bearish over neutral)
            direction = classification.get("ai_direction", "neutral")
            if direction != "neutral":
                score += 15
            
            if score > best_score:
                best_score = score
                best_ann = ann
        
        if best_ann:
            prioritized.append(best_ann)
            if len(anns) > 1:
                logger.info(
                    f"Deduplicated {symbol}: kept 1 announcement out of {len(anns)} "
                    f"(selected: {best_ann.get('headline', '')[:60]}...)"
                )
    
    logger.info(
        f"Deduplicated announcements: {len(announcements)} -> {len(prioritized)} "
        f"({len(announcements) - len(prioritized)} duplicates removed)"
    )
    
    return prioritized

