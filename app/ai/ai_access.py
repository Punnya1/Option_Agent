from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.db.models import BSEEvent
from app.services.announcement_classifier import classify_announcement


def get_event_candidates(
    db: Session,
    window_days: int = 7,
):
    since = date.today() - timedelta(days=window_days)

    events = (
        db.query(BSEEvent)
        .filter(BSEEvent.event_date >= since)
        .order_by(BSEEvent.event_date.desc())
        .all()
    )

    results = []
    for e in events:
        # Classify the announcement using LLM
        ai = classify_announcement(
            symbol=e.symbol,
            headline=e.headline,
            event_date=str(e.event_date),
            category=e.category,
        )
        
        if ai.get("ai_direction") == "neutral":
            continue

        results.append({
            "symbol": e.symbol,
            "event_date": e.event_date,
            "headline": e.headline,
            **ai,
        })

    return results
