# app/db/init_db.py

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.sessions import engine, Base
# Import all models so SQLAlchemy knows about them when creating tables
from app.db.models import (
    Stock,
    DailyPrice,
    OptionChain,
    News,
    NewsImpact,
    DailyCandidate,
    BSEEvent,
    ProcessedRun,
)
from app.services.universe import get_fno_universe


def seed_stocks(db: Session):
    """Insert F&O universe into stocks table if not present."""
    df = get_fno_universe()

    existing_symbols = {
        s[0]
        for s in db.execute(select(Stock.symbol))
    }

    new_rows = []
    for _, row in df.iterrows():
        symbol = row["symbol"]
        if symbol in existing_symbols:
            continue

        stock = Stock(
            symbol=symbol,
            name=row.get("name"),
            segment=row.get("segment"),
        )
        new_rows.append(stock)

    if new_rows:
        db.add_all(new_rows)
        db.commit()
        print(f"Inserted {len(new_rows)} stocks into 'stocks' table.")
    else:
        print("No new stocks to insert; already up to date.")


def init_db():
    """Create all tables and seed initial data."""
    # 1) Create tables
    print("Creating tables (if not exist)...")
    Base.metadata.create_all(bind=engine)

    # 2) Seed data
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        seed_stocks(db)
    finally:
        db.close()
