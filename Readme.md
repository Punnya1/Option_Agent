# Option Trading Assistant

An AI-powered system for identifying high-volatility trading opportunities from corporate announcements. The system scrapes BSE announcements, classifies them using LLM, and generates options trading recommendations by combining announcement impact with technical analysis.

## 🎯 Features

- **BSE Announcement Scraping**: Automated scraping of corporate announcements from BSE website
- **LLM-Powered Classification**: Uses Groq LLM to classify announcements for volatility potential
- **Smart Filtering**:
  - Filters to only FNO (Futures & Options) universe stocks
  - Deduplicates announcements per symbol (prioritizing results/orders)
  - Pre-filters by keywords to reduce LLM calls
- **Technical Analysis Integration**: Combines announcement impact with:
  - Open Interest (OI) analysis
  - Volume spikes
  - Price action and ATR
  - Options liquidity
- **Trade Recommendations**: Generates actionable options trading strategies with confidence scores

## 🏗️ Architecture

The system uses a LangGraph workflow to orchestrate the pipeline:

```
Scrape → Filter (FNO) → Deduplicate → Classify (LLM) → Research → Recommend
```

### Key Components

1. **BSE Scraper** (`app/services/bse_scraper.py`)

   - Uses Playwright to scrape BSE corporate announcements
   - Stores announcements in PostgreSQL database
   - Deduplicates based on content hash

2. **Announcement Classifier** (`app/services/announcement_classifier.py`)

   - Pre-filters announcements by keywords (results, orders, etc.)
   - Uses LLM to classify volatility potential
   - Deduplicates by symbol (prefers results/orders)
   - Filters by confidence and direction

3. **Stock Researcher** (`app/services/stock_researcher.py`)

   - Checks FNO universe membership
   - Analyzes technical metrics (OI, volume, price)
   - Checks options liquidity
   - Generates trading recommendations

4. **Workflow Orchestrator** (`app/services/announcement_workflow.py`)
   - LangGraph-based workflow
   - Manages state and error handling
   - Coordinates all pipeline steps

## 📋 Prerequisites

- Python 3.13+
- PostgreSQL database
- Groq API key (for LLM classification)
- Playwright (for web scraping)

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Environment Configuration

Create a `.env` file in the project root:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/option_trading

# LLM API Key (required)
GROQ_API_KEY=your_groq_api_key_here

# Optional: News API
GNEWS_API_KEY=your_gnews_api_key_optional
```

### 3. Database Setup

```bash
# Initialize database and seed FNO universe
python scripts/init_db_script.py
```

### 4. Run the API Server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

## 📖 Usage

### Running the Announcement Pipeline

#### Via API

```bash
# Run pipeline for today
curl -X POST "http://localhost:8000/announcements/run-pipeline"

# Run pipeline for specific date
curl -X POST "http://localhost:8000/announcements/run-pipeline?target_date=2025-12-28"
```

#### Via Script

```bash
python scripts/run_announcement_pipeline.py
```

### Pipeline Flow

1. **Scraping**: Fetches BSE announcements for the target date
2. **FNO Filtering**: Filters to only stocks in FNO universe
3. **Pre-Deduplication**: Removes duplicate announcements per symbol (keyword-based)
4. **Classification**: LLM classifies announcements for volatility potential
5. **Post-Deduplication**: Final deduplication based on classification results
6. **Research**: Analyzes technical metrics and options liquidity
7. **Recommendations**: Returns trade-ready stocks with strategies

### Example Response

```json
{
  "target_date": "2025-12-28",
  "summary": {
    "total_announcements": 172,
    "high_vol_count": 2,
    "researched_count": 2,
    "trade_ready_count": 1
  },
  "trade_recommendations": [
    {
      "symbol": "RELIANCE",
      "announcement_date": "2025-12-28",
      "final_recommendation": {
        "direction": "bullish",
        "confidence_score": 75,
        "trade_ready": true,
        "suggested_strategy": "Buy near-ATM call options (next trading session)"
      }
    }
  ]
}
```

## 🔌 API Endpoints

### Announcements

- `POST /announcements/run-pipeline` - Run the complete pipeline
- `GET /announcements/research/{symbol}` - Research a specific stock

### Stocks

- `GET /stocks/` - List all stocks
- `GET /stocks/{symbol}` - Get stock details

### Candidates

- `GET /candidates/` - Get top trading candidates
- `GET /candidates/{date}` - Get candidates for specific date

### News

- `GET /news/{symbol}` - Get news for a symbol

### AI

- `POST /ai/explain` - Explain trading signals using AI

## 🎯 Key Features Explained

### FNO Universe Filtering

The system automatically filters announcements to only include stocks in the FNO (Futures & Options) universe. This ensures:

- Only tradeable stocks are processed
- No wasted LLM calls on non-tradeable stocks
- Faster pipeline execution

### Smart Deduplication

Two-stage deduplication:

1. **Pre-classification**: Removes duplicates based on keywords (before LLM calls)
2. **Post-classification**: Final deduplication based on LLM results

Prioritizes:

- Results announcements (Q1, Q2, Q3, Q4, earnings)
- Orders/contracts (order wins, tenders, awards)
- Higher confidence classifications

### LLM Classification

Uses Groq's Llama 3.3 70B model to classify announcements:

- **Event Type**: results_positive, results_negative, order_win, order_loss, etc.
- **Direction**: bullish, bearish, neutral
- **Confidence**: low, medium, high
- **Reaction Window**: same_day, next_day, 1_3_days

### Technical Analysis

Combines announcement impact with:

- **Open Interest**: Tracks options OI changes
- **Volume Spikes**: Identifies unusual volume
- **Price Action**: Analyzes returns, gaps, ATR
- **Options Liquidity**: Checks OI and volume for tradeability

## 📁 Project Structure

```
option_trading_assistant/
├── app/
│   ├── ai/              # AI/LLM integration
│   ├── announcements/   # Announcement API endpoints
│   ├── candidate/       # Trading candidate logic
│   ├── core/            # Configuration and logging
│   ├── db/              # Database models and sessions
│   ├── news/            # News API endpoints
│   ├── services/        # Core business logic
│   │   ├── announcement_classifier.py
│   │   ├── announcement_workflow.py
│   │   ├── bse_scraper.py
│   │   ├── stock_researcher.py
│   │   └── ...
│   └── stock/           # Stock API endpoints
├── data/
│   ├── fno_universe.csv # FNO universe stocks
│   └── raw/             # Raw data files
├── scripts/             # Utility scripts
├── main.py              # FastAPI application
└── requirements.txt    # Python dependencies
```

## 🔧 Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `GROQ_API_KEY`: Groq API key for LLM classification
- `GNEWS_API_KEY`: (Optional) GNews API key for news features

### Rate Limiting

The system includes rate limiting for LLM calls:

- Default: 2 seconds between calls
- Handles rate limit errors gracefully
- Configurable via `LLM_CALL_DELAY` in `announcement_classifier.py`

## 📊 Data Pipeline

### Daily Pipeline

1. **Data Ingestion**:

   ```bash
   python scripts/ingest_equity_db.py  # Equity data
   python scripts/ingest_fno_db.py     # FNO data
   ```

2. **Announcement Pipeline**:

   ```bash
   python scripts/run_announcement_pipeline.py
   ```

3. **Scoring**:
   ```bash
   python scripts/run_scoring_for_date.py
   ```

## 🐛 Troubleshooting

### Common Issues

1. **No FNO stocks found**: Ensure `data/fno_universe.csv` exists and is populated
2. **LLM rate limits**: Increase `LLM_CALL_DELAY` in `announcement_classifier.py`
3. **Database connection errors**: Check `DATABASE_URL` in `.env`
4. **Playwright errors**: Run `playwright install chromium`

### Logs

Logs are written to the `logs/` directory. Check for:

- Classification results
- Filtering decisions
- Research outcomes
- Error messages

## 📚 Additional Documentation

- [Setup Guide](SETUP_GUIDE.md) - Detailed setup instructions
- [Announcement Pipeline](ANNOUNCEMENT_PIPELINE.md) - Pipeline documentation
- [LLM Usage Guide](LLM_USAGE_GUIDE.md) - LLM integration details

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License

[Add your license here]

## 🙏 Acknowledgments

- Groq for LLM API
- BSE for corporate announcements
- LangGraph for workflow orchestration
