# BSE Announcement Pipeline Documentation

## Overview

This pipeline scrapes BSE corporate announcements, classifies them for high volatility potential using LLM, and researches stocks to generate options trading recommendations for the next trading day.

## Architecture

The pipeline consists of 4 main components:

1. **BSE Scraper** (`app/services/bse_scraper.py`)
   - Uses Playwright to scrape BSE corporate announcements website
   - Stores announcements in the database

2. **Announcement Classifier** (`app/services/announcement_classifier.py`)
   - Uses LLM (Groq) to classify announcements for volatility potential
   - Filters for high-impact events (results, orders, fund raising, etc.)

3. **Stock Researcher** (`app/services/stock_researcher.py`)
   - Combines announcement impact with technical analysis
   - Analyzes OI, volume, price action, and options liquidity
   - Generates trading recommendations

4. **LangGraph Workflow** (`app/services/announcement_workflow.py`)
   - Orchestrates the entire pipeline
   - Manages state and error handling
   - Returns trade-ready recommendations

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

```bash
playwright install chromium
```

### 3. Configure Environment Variables

Make sure your `.env` file has:
```
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=your_database_url
```

## Usage

### Option 1: Run via Script (Recommended for Daily Automation)

```bash
python scripts/run_announcement_pipeline.py --date 2025-12-15
```

Or for today's date:
```bash
python scripts/run_announcement_pipeline.py
```

Save results to JSON:
```bash
python scripts/run_announcement_pipeline.py --date 2025-12-15 --output results.json
```

### Option 2: Run via API Endpoint

Start the FastAPI server:
```bash
uvicorn main:app --reload
```

Run the pipeline:
```bash
curl -X POST "http://localhost:8000/announcements/run-pipeline?target_date=2025-12-15"
```

### Option 3: Use in Python Code

```python
from app.db.sessions import get_db
from app.services.announcement_workflow import run_daily_announcement_pipeline

db = next(get_db())
result = run_daily_announcement_pipeline(db=db, target_date=date.today())

# Access results
trade_recommendations = result["trade_recommendations"]
for rec in trade_recommendations:
    print(f"{rec['symbol']}: {rec['final_recommendation']['direction']}")
```

## Pipeline Flow

```
1. Scrape BSE Announcements
   ↓
2. Classify for High Volatility (LLM)
   ↓
3. Research Stocks (OI, Volume, Price Action)
   ↓
4. Generate Trade Recommendations
```

## Output Structure

The pipeline returns:

```json
{
  "target_date": "2025-12-15",
  "summary": {
    "total_announcements": 150,
    "high_vol_count": 12,
    "researched_count": 12,
    "trade_ready_count": 5
  },
  "trade_recommendations": [
    {
      "symbol": "RELIANCE",
      "announcement_date": "2025-12-15",
      "announcement": {
        "headline": "Q3 Results Announcement",
        "event_type": "results_positive",
        "direction": "bullish",
        "reaction_window": "next_day",
        "confidence": "high"
      },
      "technicals": {
        "direction": "bullish",
        "daily_return": 0.035,
        "vol_spike": 1.8,
        "atr_pct": 0.032
      },
      "final_recommendation": {
        "direction": "bullish",
        "confidence_score": 85,
        "trade_ready": true,
        "suggested_strategy": "Buy near-ATM call options (next trading session)"
      }
    }
  ]
}
```

## BSE Scraper Configuration

**Important**: The BSE scraper (`app/services/bse_scraper.py`) contains template selectors that need to be adjusted based on the actual BSE website structure.

To customize:

1. Inspect the BSE corporate announcements page
2. Update selectors in `scrape_bse_announcements()` function:
   - `announcement_rows`: Selector for announcement table rows
   - `headline_elem`: Selector for headline text
   - `date_elem`: Selector for date
   - `link_elem`: Selector for announcement URL

Example BSE URL structure may vary - adjust `base_url` if needed.

## Classification Criteria

The LLM classifies announcements based on:

- **Event Type**: results_positive, results_negative, order_win, order_loss, fund_raise, regulatory, neutral
- **Direction**: bullish, bearish, neutral
- **Reaction Window**: same_day, next_day, 1_3_days
- **Confidence**: low, medium, high

High-volatility events typically include:
- Quarterly/annual results
- Large order wins/losses (>10% of revenue)
- Fund raising (QIP, rights issue)
- Regulatory actions
- Major corporate actions

## Trading Recommendations

Stocks are marked as "trade-ready" if:
- Confidence score >= 60
- Options liquidity available (OI > 0)
- Clear directional bias (bullish or bearish)

Strategies suggested:
- **Low volatility (ATR < 4%)**: Buy near-ATM calls/puts
- **High volatility (ATR >= 4%)**: Spreads (call/put spreads) to reduce cost

## Scheduling

To run daily after market hours, add to cron:

```bash
# Run at 6 PM daily
0 18 * * * cd /path/to/project && python scripts/run_announcement_pipeline.py --output /path/to/results/$(date +\%Y-\%m-\%d).json
```

## Troubleshooting

### Playwright Issues
- Ensure browsers are installed: `playwright install chromium`
- If headless mode fails, try running with visible browser for debugging

### BSE Scraper Issues
- Website structure may have changed - update selectors
- Check if BSE requires authentication or has rate limits
- Verify the BSE URL is correct

### LLM Classification Issues
- Check GROQ_API_KEY is set correctly
- Monitor API rate limits
- Adjust temperature/confidence thresholds if needed

### Database Issues
- Ensure BSEEvent table exists (run migrations)
- Check database connection string

## API Endpoints

### POST `/announcements/run-pipeline`
Run the complete pipeline.

**Query Parameters:**
- `target_date` (optional): Date to process (YYYY-MM-DD), defaults to today

**Response:** Pipeline results with trade recommendations

### GET `/announcements/research/{symbol}`
Research a specific stock with an announcement.

**Query Parameters:**
- `announcement_date`: Date of the announcement (YYYY-MM-DD)

**Response:** Detailed research for the stock

## Next Steps

1. **Customize BSE Scraper**: Adjust selectors based on actual BSE website
2. **Fine-tune Classification**: Adjust LLM prompts based on your trading style
3. **Add Filters**: Filter by sector, market cap, etc.
4. **Backtesting**: Test recommendations against historical data
5. **Alerts**: Set up notifications for high-confidence trades

