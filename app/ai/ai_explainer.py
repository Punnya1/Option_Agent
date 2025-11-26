from json import load
from typing import Dict, Any
from typing import Literal

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.config import settings
from app.core.logging_utils import get_logger

# Logger for this module
logger = get_logger(__name__)


# 1) Define the JSON schema we want back from the LLM
class AICandidateExplanation(BaseModel):
    ai_direction: Literal["bullish", "bearish", "neutral"] = Field(
        description="Overall directional bias for the NEXT trading session."
    )
    ai_strategy_hint: str = Field(
        description="Very short suggestion of which options strategy might fit this view."
    )
    ai_explanation: str = Field(
        description="2–4 sentence explanation of why this symbol looks this way."
    )


parser = JsonOutputParser(pydantic_object=AICandidateExplanation)

# 2) Prompt template
prompt = ChatPromptTemplate.from_template(
    """
You are an experienced derivatives trader in the Indian market.
You are given EOD statistics for a single F&O stock and some basic
rule-based labels. Your job is to form a conservative opinion about
the directional bias for the NEXT trading session and briefly explain it.

ALWAYS think in terms of probability, NOT certainty.
If signals are mixed or weak, choose "neutral".

Return ONLY JSON that matches this schema:
{format_instructions}

Inputs:
- Symbol: {symbol}
- Date (EOD data as of): {date}
- Spot price: {spot}
- Daily return: {daily_return:.4f} (fraction, e.g. -0.0400 = -4%)
- ATR%: {atr_pct:.4f}
- Volume spike vs recent average: {vol_spike:.4f}
- Gap% vs previous close: {gap_pct:.4f}
- Total OI near ATM: {total_oi}
- Total option volume near ATM: {total_volume}
- Rule-based direction label: {direction}
- Rule-based strategy hint: {strategy_hint}

Guidelines:
- If daily_return is strongly positive, vol_spike > 1 and ATR% is not tiny,
  you may lean "bullish".
- If daily_return is strongly negative, vol_spike > 1 and ATR% is not tiny,
  you may lean "bearish".
- If signals conflict, are small, or OI/volume are low, choose "neutral".
- Strategy hint should be very short, e.g. "bull call spread near ATM",
  "buy put near ATM", "no clear trade, wait for better setup", etc.
- Explanation should mention price move, volume behaviour and OI/liquidity.
"""
)

# 3) LLM client (Groq)
logger.info("Initializing Groq LLM client for AI explainer...")
llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",  # or "llama-3.1-8b-instant" if you prefer cheaper/faster
    temperature=0.2,                        # small randomness
    groq_api_key=settings.groq_api_key,
)
logger.info("Groq LLM client initialized successfully.")

# 4) Full chain: prompt -> LLM -> JSON parser
chain = prompt | llm | parser


def get_ai_annotation_for_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Take one candidate dict (from your existing scoring pipeline)
    and return the parsed AI explanation as a plain dict.
    """
    symbol = candidate.get("symbol")
    logger.info(f"Generating AI annotation for symbol={symbol}")

    # Defensive defaults
    payload = {
        "symbol": symbol,
        "date": str(candidate.get("date")),
        "spot": float(candidate.get("spot") or 0),
        "daily_return": float(
            candidate.get("return") or candidate.get("daily_return") or 0.0
        ),
        "atr_pct": float(candidate.get("atr_pct") or 0.0),
        "vol_spike": float(candidate.get("vol_spike") or 0.0),
        "gap_pct": float(candidate.get("gap_pct") or 0.0),
        "total_oi": float(candidate.get("total_oi") or 0.0),
        "total_volume": float(candidate.get("total_volume") or 0.0),
        "direction": candidate.get("direction") or "neutral",
        "strategy_hint": candidate.get("strategy_hint") or "",
        "format_instructions": parser.get_format_instructions(),
    }

    logger.debug(f"AI payload for {symbol}: {payload}")

    try:
        result: AICandidateExplanation = chain.invoke(payload)
        logger.info(f"AI annotation received for symbol={symbol}")
    except Exception as e:
        logger.exception(f"Error while invoking AI chain for symbol={symbol}: {e}")
        raise

    # Convert Pydantic model → dict
    if isinstance(result, dict):
        logger.debug(f"AI result (dict) for {symbol}: {result}")
        return result

    # If model sometimes returns a Pydantic model or LC object:
    try:
        result_dict = result.dict()
        logger.debug(f"AI result (pydantic) for {symbol}: {result_dict}")
        return result_dict
    except AttributeError:
        # maybe result is a string with JSON -> parse it
        import json
        logger.warning(f"AI result for {symbol} not a dict/model, attempting JSON parse...")
        try:
            parsed = json.loads(result)
            logger.debug(f"AI result (parsed JSON) for {symbol}: {parsed}")
            return parsed
        except Exception:
            # last resort: wrap raw text
            logger.error(f"Failed to parse AI result for {symbol}, returning raw text.")
            return {
                "direction": None,
                "explanation": str(result),
                "strategy_hint": None,
            }
