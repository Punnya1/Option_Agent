# LLM Usage and Rate Limit Management

## Pipeline Flow and LLM Call Count

### Current Pipeline Flow:

```
1. Scrape BSE Announcements (No LLM calls)
   ↓
2. Classify Announcements (LLM calls here!)
   - Calls `classify_announcement()` for each announcement
   - Limited to 20 announcements by default
   ↓
3. Research Stocks (No LLM calls)
   - Uses already-classified announcements
   - Only queries database for technical data
```

### LLM Call Count:

**Per Pipeline Run:**
- **Maximum**: 20 LLM calls (default limit)
- **Typical**: 5-15 calls (after filtering low-confidence/neutral announcements)
- **Location**: `app/services/announcement_classifier.py::filter_high_volatility_announcements()`

**Why 20?**
- Groq free tier: ~30 requests/minute
- Groq paid tier: Higher limits
- Default limit of 20 ensures we stay under rate limits

### Adjusting LLM Call Limits:

**Option 1: Change Default Limit**
```python
# In app/services/announcement_workflow.py
high_vol = filter_high_volatility_announcements(
    announcements=announcements,
    min_confidence="medium",
    max_classifications=10  # Reduce to 10 for more conservative usage
)
```

**Option 2: Use API Parameter**
```python
# Add to API endpoint
@router.post("/announcements/run-pipeline")
def run_pipeline(
    target_date: date = Query(None),
    max_llm_calls: int = Query(20, ge=1, le=50),  # Add this parameter
    db: Session = Depends(get_db),
):
    # Pass to workflow
    result = run_daily_announcement_pipeline(
        db=db, 
        target_date=target_date,
        max_classifications=max_llm_calls
    )
```

**Option 3: Pre-filter Before LLM**
```python
# Add keyword-based pre-filtering to reduce LLM calls
def pre_filter_announcements(announcements):
    """Filter announcements by keywords before LLM classification."""
    high_priority_keywords = [
        "result", "quarter", "q1", "q2", "q3", "q4",
        "order", "contract", "award", "tender",
        "merger", "acquisition", "fund raising"
    ]
    # Only classify announcements with high-priority keywords
    return [a for a in announcements if any(kw in a.get("headline", "").lower() for kw in high_priority_keywords)]
```

## Groq Rate Limits

### Free Tier:
- **Rate Limit**: ~30 requests/minute
- **Daily Limit**: Varies
- **Model**: llama-3.1-8b-instant (faster, cheaper)

### Paid Tier:
- **Rate Limit**: Higher (check Groq dashboard)
- **Model**: llama-3.3-70b-versatile (better quality)

### Current Configuration:
- **Model**: `llama-3.3-70b-versatile` (in `announcement_classifier.py`)
- **Temperature**: 0.2 (low randomness)
- **Max Calls**: 20 per pipeline run

## Optimizations to Reduce LLM Calls

### 1. **Keyword Pre-filtering** (Recommended)
Filter announcements by keywords before LLM classification:

```python
def pre_filter_by_keywords(announcements):
    """Filter to only high-impact announcements."""
    keywords = ["result", "quarter", "order", "contract", "merger", "fund"]
    return [
        a for a in announcements 
        if any(kw in a.get("headline", "").lower() for kw in keywords)
    ]
```

### 2. **Caching Classifications**
Cache LLM results for similar announcements:

```python
# Add caching layer
from functools import lru_cache
import hashlib

@lru_cache(maxsize=1000)
def cached_classify(headline_hash, symbol, category):
    # Check cache first
    # Only call LLM if not cached
    pass
```

### 3. **Batch Classification** (Future)
If Groq supports batch API:
```python
# Classify multiple announcements in one call
classifications = classify_announcements_batch(announcements[:20])
```

### 4. **Use Faster Model for Initial Filter**
```python
# Use faster model for initial classification
# Then use better model only for high-confidence ones
if initial_confidence == "high":
    # Re-classify with better model
    pass
```

## Monitoring LLM Usage

### Add Usage Tracking:
```python
# Track LLM calls
llm_call_count = 0

def classify_announcement(...):
    global llm_call_count
    llm_call_count += 1
    logger.info(f"LLM call #{llm_call_count}")
    # ... rest of function
```

### Check Groq Dashboard:
- Monitor usage at: https://console.groq.com/
- Set up alerts for rate limit warnings

## Expected Response for Stock Research

### Normal Response (with technical data):
```json
{
  "symbol": "RELIANCE",
  "announcement": {...},
  "technicals": {
    "direction": "bullish",
    "daily_return": 0.035,
    "vol_spike": 1.8,
    "atr_pct": 0.032
  },
  "final_recommendation": {
    "direction": "bullish",
    "confidence_score": 85,
    "trade_ready": true
  }
}
```

### Expected Response (no technical data):
```json
{
  "symbol": "RELIANCE",
  "announcement": {...},
  "technicals": {
    "direction": "unknown",
    "note": "No technical data available"
  },
  "final_recommendation": {
    "direction": "bullish",  // Based on announcement only
    "confidence_score": 50,  // Lower confidence
    "trade_ready": false,     // Can't trade without technicals
    "suggested_strategy": "Wait for technical data..."
  },
  "note": "No technical data available - recommendation based on announcement only"
}
```

**This is expected when:**
- Date is in the future (announcement today, trade tomorrow)
- No price data exists for that date yet
- Stock is not in F&O universe
- Market was closed on that date

## Best Practices

1. **Run pipeline after market hours** - ensures price data is available
2. **Use `max_classifications=10-20`** - balance between coverage and rate limits
3. **Pre-filter by keywords** - reduce LLM calls by 50-70%
4. **Monitor Groq dashboard** - track usage and adjust limits
5. **Cache results** - avoid re-classifying same announcements
6. **Use faster model** - `llama-3.1-8b-instant` for initial filtering

## Example: Optimized Pipeline

```python
# 1. Pre-filter by keywords (no LLM)
filtered = pre_filter_by_keywords(announcements)  # 50 -> 15

# 2. Classify with LLM (limited calls)
high_vol = filter_high_volatility_announcements(
    filtered,
    max_classifications=15  # Only classify pre-filtered ones
)  # 15 LLM calls max

# 3. Research stocks (no LLM)
research_results = research_multiple_stocks(db, high_vol)
```

This reduces LLM calls from 50 to 15 (70% reduction)!

