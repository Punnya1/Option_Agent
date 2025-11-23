import sys
import os
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.sessions import SessionLocal
from app.services.signals import score_all_symbols_for_date


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_scoring_for_date.py YYYY-MM-DD")
        sys.exit(1)

    target_date = date.fromisoformat(sys.argv[1])

    db = SessionLocal()
    try:
        results = score_all_symbols_for_date(db, target_date, lookback_days=14, limit=20)
        for r in results:
            print(
                f"{r['symbol']:10s} "
                f"score={r['score']:.2f} "
                f"ATR%={r['atr_pct']*100:.2f}% "
                f"vol_spike={r['vol_spike']:.2f} "
                f"gap={r['gap_pct']*100:.2f}% "
                f"ret={r['return']*100:.2f}%"
            )
    finally:
        db.close()
