import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
from xml.etree import ElementTree as ET
from urllib.parse import quote_plus
from app.core.config import settings

logger = logging.getLogger(__name__)


def _gnews_fetch(q: str, from_dt: str, api_key: str, max_items: int = 10):
    url = "https://gnews.io/api/v4/search"
    params = {"q": q, "from": from_dt, "max": max_items, "lang": "en", "apikey": api_key}
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    out = []
    for a in data.get("articles", []):
        out.append({
            "title": a.get("title"),
            "summary": a.get("description") or "",
            "url": a.get("url"),
            "published_at": a.get("publishedAt"),
            "source": a.get("source", {}).get("name"),
        })
    return out


def _google_news_rss_fetch(q: str, days: int = 7, max_items: int = 10) -> List[Dict[str, Any]]:
    """Fetch Google News RSS search results (simple fallback)."""
    rss_q = quote_plus(q)
    url = f"https://news.google.com/rss/search?q={rss_q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        cutoff = datetime.utcnow() - timedelta(days=days)
        for it in root.findall(".//item")[:max_items]:
            title = it.findtext("title")
            link = it.findtext("link")
            pub = it.findtext("pubDate")
            # pubDate parse loosely
            items.append({
                "title": title,
                "summary": "",  # RSS doesn't provide summary consistently
                "url": link,
                "published_at": pub,
                "source": "Google News",
            })
        return items
    except Exception as e:
        logger.warning("Google News RSS fetch failed: %s", e)
        return []


def fetch_news_for_symbol(symbol: str, window_days: int = 7, max_items: int = 10) -> List[Dict[str, Any]]:
    """
    Try NewsAPI if NEWSAPI_KEY is present in env, otherwise fallback to Google News RSS search.
    Returns list of dicts: {title, summary, url, published_at, source}
    """
    symbol = symbol.strip()
    logger.info("Fetching news for symbol=%s window_days=%d", symbol, window_days)

    gnews_api_key = settings.gnews_api_key
    # Build query: symbol + company name heuristics could be added later; for now use symbol
    q = f"{symbol} OR {symbol} stock OR {symbol} shares OR {symbol} results OR {symbol} tender"

    from_dt = (datetime.utcnow() - timedelta(days=window_days)).strftime("%Y-%m-%d")

    if gnews_api_key:
        logger.info("Using NewsAPI for news fetch")
        items = _gnews_fetch(q, from_dt, gnews_api_key, max_items=max_items)
        if items:
            return items

    # Fallback to google news rss
    logger.info("Falling back to Google News RSS for %s", symbol)
    items = _google_news_rss_fetch(q, days=window_days, max_items=max_items)
    return items
