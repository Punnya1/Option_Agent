from datetime import date
import requests

from sqlalchemy.orm import Session
from sqlalchemy import exists

from app.core.logging_utils import get_logger
from app.db.models import BSEEvent

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}

KEYWORDS_RESULTS = ["result", "financial", "quarter", "q1", "q2", "q3", "q4"]
KEYWORDS_ORDER = ["order", "contract", "tender", "award", "loi"]


def classify_event(text: str):
    t = text.lower()
    if any(k in t for k in KEYWORDS_RESULTS):
        return "results"
    if any(k in t for k in KEYWORDS_ORDER):
        return "order"
    return None


def ingest_bse_events(db: Session, lookback_days: int = 7) -> int:
    logger.info("Ingesting NSE corporate announcements")

    session = requests.Session()
    session.headers.update(HEADERS)

    # Prime cookies
    session.get("https://www.nseindia.com", timeout=10)

    r = session.get(
        "https://www.nseindia.com/api/corporate-announcements?index=equities",
        timeout=15,
    )
    r.raise_for_status()

    data = r.json()
    inserted = 0

    for row in data:
        symbol = row.get("symbol")
        headline = row.get("subject")

        if not symbol or not headline:
            continue

        category = classify_event(headline)
        if not category:
            continue

        exists_q = db.query(
            exists().where(
                (BSEEvent.symbol == symbol)
                & (BSEEvent.headline == headline)
            )
        ).scalar()

        if exists_q:
            continue

        event = BSEEvent(
            symbol=symbol,
            event_date=date.today(),
            headline=headline,
            category=category,
            source="nse",
        )

        db.add(event)
        inserted += 1

    if inserted:
        db.commit()

    logger.info("Inserted %d NSE events", inserted)
    return inserted
