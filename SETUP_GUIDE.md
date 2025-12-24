# Setup Guide - BSE Announcement Pipeline

## Prerequisites

✅ **Dependencies Installed** - You've already done this!

## Step 1: Environment Configuration

Make sure your `.env` file has the required variables:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/option_trading

# LLM API Key (required for announcement classification)
GROQ_API_KEY=your_groq_api_key_here

# Optional: News API (if you want to use news features)
GNEWS_API_KEY=your_gnews_api_key_optional
```

## Step 2: Database Setup

Ensure your database is initialized with all tables:

```bash
python scripts/init_db_script.py
```

This will:

- Create all necessary tables (including `bse_events`)
- Seed the F&O universe stocks

## Step 3: Customize BSE Scraper (IMPORTANT!)

The BSE scraper needs to be customized for the actual BSE website structure.

### Option A: Use the existing NSE scraper (Quick Start)

If you want to test the pipeline quickly, you can temporarily use the existing NSE scraper:

```bash
# The existing bse_ingest.py actually scrapes NSE
# You can use it to test the pipeline flow
```

### Option B: Customize BSE Scraper (Production)

1. **Inspect BSE Website:**

   - Go to https://www.bseindia.com/corporates/
   - Open browser DevTools (F12)
   - Inspect the corporate announcements page structure

2. **Update Selectors in `app/services/bse_scraper.py`:**

   - Line ~60: Update `base_url` if needed
   - Line ~70-80: Update CSS selectors for announcement rows
   - Line ~90-100: Update selectors for headline, date, symbol extraction

3. **Test the scraper:**

   ```python
   from app.db.sessions import get_db
   from app.services.bse_scraper import ingest_bse_announcements

   db = next(get_db())
   count = ingest_bse_announcements(db, lookback_days=1)
   print(f"Inserted {count} announcements")
   ```

## Step 4: Test the Pipeline

### Test Individual Components

1. **Test Announcement Classification:**

   ```python
   from app.services.announcement_classifier import classify_announcement

   result = classify_announcement(
       symbol="RELIANCE",
       headline="Q3 Results Announcement - Strong Growth",
       event_date="2025-12-15",
       category="results"
   )
   print(result)
   ```

2. **Test Stock Research:**

   ```python
   from app.db.sessions import get_db
   from app.services.stock_researcher import research_stock_with_announcement
   from datetime import date

   db = next(get_db())
   classification = {
       "event_type": "results_positive",
       "ai_direction": "bullish",
       "reaction_window": "next_day",
       "confidence": "high",
       "explanation": "Strong quarterly results"
   }

   research = research_stock_with_announcement(
       db, "RELIANCE", date.today(), classification
   )
   print(research)
   ```

### Run Full Pipeline

**Via Script (Recommended):**

```bash
# For today's date
python scripts/run_announcement_pipeline.py

# For a specific date
python scripts/run_announcement_pipeline.py --date 2025-12-15

# Save results to JSON
python scripts/run_announcement_pipeline.py --date 2025-12-15 --output results.json
```

**Via API:**

```bash
# Start the server
uvicorn main:app --reload

# In another terminal, run the pipeline
curl -X POST "http://localhost:8000/announcements/run-pipeline?target_date=2025-12-15"
```

## Step 5: Verify Data Flow

1. **Check if announcements are being scraped:**

   ```sql
   SELECT COUNT(*), event_date
   FROM bse_events
   GROUP BY event_date
   ORDER BY event_date DESC
   LIMIT 10;
   ```

2. **Check classified announcements:**

   ```python
   from app.db.sessions import get_db
   from app.db.models import BSEEvent

   db = next(get_db())
   events = db.query(BSEEvent).filter(BSEEvent.event_date == date.today()).all()
   print(f"Found {len(events)} events for today")
   ```

## Step 6: Schedule Daily Runs

Add to your cron (runs at 6 PM daily):

```bash
# Edit crontab
crontab -e

# Add this line (adjust paths):
0 18 * * * cd /path/to/option_trading_assistant && /path/to/venv/bin/python scripts/run_announcement_pipeline.py --output /path/to/results/$(date +\%Y-\%m-\%d).json
```

## Troubleshooting

### Issue: "No module named 'playwright'"

**Solution:** Install playwright browsers:

```bash
playwright install chromium
```

### Issue: "GROQ_API_KEY not found"

**Solution:** Add `GROQ_API_KEY` to your `.env` file

### Issue: "Database connection error"

**Solution:**

- Check `DATABASE_URL` in `.env`
- Ensure database is running
- Run `python scripts/init_db_script.py` to create tables

### Issue: "No announcements scraped"

**Solution:**

- BSE scraper selectors need customization (see Step 3)
- Check BSE website structure hasn't changed
- Verify network connectivity

### Issue: "LangGraph import errors"

**Solution:**

- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version (3.8+ required)

## Next Steps

1. ✅ Customize BSE scraper for production use
2. ✅ Fine-tune LLM prompts in `announcement_classifier.py` for your trading style
3. ✅ Add filters (sector, market cap, etc.) in the workflow
4. ✅ Set up alerts/notifications for high-confidence trades
5. ✅ Backtest recommendations against historical data

## Quick Reference

**Key Files:**

- `app/services/bse_scraper.py` - BSE announcement scraper
- `app/services/announcement_classifier.py` - LLM classification
- `app/services/stock_researcher.py` - Stock analysis
- `app/services/announcement_workflow.py` - LangGraph orchestration
- `scripts/run_announcement_pipeline.py` - Daily pipeline script

**API Endpoints:**

- `POST /announcements/run-pipeline` - Run full pipeline
- `GET /announcements/research/{symbol}` - Research specific stock

**Database Tables:**

- `bse_events` - Scraped announcements
- `stocks` - F&O universe
- `daily_prices` - Price data
- `option_chain` - Options data
