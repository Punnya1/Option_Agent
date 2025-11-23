import sys
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import select

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.sessions import SessionLocal
from app.db.models import Stock, DailyPrice


def ingest_bhavcopy(filepath: Path, trade_date_str: str):
    trade_date = datetime.fromisoformat(trade_date_str).date()
    print(f"Processing file: {filepath}")
    print(f"Trade date: {trade_date}")

    df = pd.read_csv(filepath)

    # Normalize columns
    df.columns = df.columns.str.strip().str.upper().str.replace(" ", "_")

    required_cols = [
        "SYMBOL",
        "OPEN_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "CLOSE_PRICE",
        "TTL_TRD_QNTY",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns after normalization: {missing}")

    # Normalize values
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip().str.upper()
    if "SERIES" in df.columns:
        df["SERIES"] = df["SERIES"].astype(str).str.strip().str.upper()
        df = df[df["SERIES"] == "EQ"]

    db = SessionLocal()
    try:
        # 🔹 Load existing stock symbols from DB
        existing_symbols = {
            s for (s,) in db.query(Stock.symbol).all()
        }
        print(f"Existing symbols in stocks table: {len(existing_symbols)}")

        inserted_prices = 0
        inserted_stocks = 0

        for _, row in df.iterrows():
            symbol = row["SYMBOL"]

            # 🔹 If symbol not present in stocks, add it
            if symbol not in existing_symbols:
                new_stock = Stock(
                    symbol=symbol,
                    name=None,         # you can fill later if you want
                    segment="EQ",      # since this is equity bhavcopy
                )
                db.add(new_stock)
                existing_symbols.add(symbol)
                inserted_stocks += 1

            open_price = float(row["OPEN_PRICE"])
            high_price = float(row["HIGH_PRICE"])
            low_price = float(row["LOW_PRICE"])
            close_price = float(row["CLOSE_PRICE"])
            volume = float(row["TTL_TRD_QNTY"])

            # Idempotent insert into daily_prices
            existing_price = (
                db.query(DailyPrice)
                .filter(DailyPrice.symbol == symbol, DailyPrice.date == trade_date)
                .first()
            )
            if existing_price:
                continue

            dp = DailyPrice(
                symbol=symbol,
                date=trade_date,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
            db.add(dp)
            inserted_prices += 1

        db.commit()
        print(f"Inserted {inserted_stocks} new stocks into stocks table.")
        print(f"Inserted {inserted_prices} rows into daily_prices.")
    except Exception as e:
        db.rollback()
        print("Error during ingest:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/ingest_equity_db.py path/to/bhavcopy.csv YYYY-MM-DD")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    trade_date_str = sys.argv[2]
    ingest_bhavcopy(filepath, trade_date_str)
