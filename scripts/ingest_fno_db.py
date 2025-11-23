import sys
import os
from pathlib import Path
from datetime import datetime, date
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

# Ensure project root is on sys.path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.sessions import SessionLocal
from app.db.models import Stock, OptionChain


def parse_trade_date(raw: str) -> date:
    """
    Parse trade date like '20/NOV/2025' into a date object.
    """
    raw = str(raw).strip()
    return datetime.strptime(raw, "%d/%b/%Y").date()


def parse_expiry(raw) -> date:
    """
    Parse expiry like 30122025 (int) or '30122025' into a date object (DDMMYYYY).
    """
    s = str(raw).strip()
    if len(s) != 8:
        raise ValueError(f"Unexpected expiry format: {raw!r}")
    return datetime.strptime(s, "%d%m%Y").date()


def auto_add_stock_if_missing(db: Session, symbol: str) -> str:
    """
    Ensure the underlying symbol exists in stocks table.
    Returns normalized symbol.
    """
    symbol_norm = symbol.strip().upper()
    exists = db.query(Stock).filter(Stock.symbol == symbol_norm).first()
    if not exists:
        db.add(Stock(symbol=symbol_norm, name=None, segment="FNO"))
    return symbol_norm


def to_float_or_none(x) -> Optional[float]:
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def ingest_fno_file(filepath: Path, trade_date_str: Optional[str] = None):
    print(f"Processing F&O file: {filepath}")

    # No header in .dat/.csv, so we use header=None
    df = pd.read_csv(filepath, header=None)

    # Strip whitespace from all string fields
    df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

    num_cols = df.shape[1]
    print(f"Detected {num_cols} columns in F&O file")

    # Expecting 26 columns based on your sample
    if num_cols < 22:
        raise ValueError(f"Expected at least 22 columns, got {num_cols}")

    # Map the columns we care about
    df = df.rename(
        columns={
            0: "contract_id",      # e.g. ABB25DEC4100CE
            1: "instrument",       # OPTSTK / FUTSTK / OPTIDX / FUTIDX
            2: "underlying",       # ABB
            3: "expiry_raw",       # 30122025 (int)
            4: "strike_raw",       # 4100.0
            5: "option_type",      # CE / PE
            9: "price_1",
            10: "price_2",
            11: "price_3",
            12: "price_4",
            13: "price_5",
            15: "contracts_traded",
            16: "turnover",
            17: "oi_1",
            18: "oi_2",
            21: "trade_date_raw",  # '20/NOV/2025'
        }
    )

    # Filter to stock options only
    df = df[df["instrument"] == "OPTSTK"]
    print(f"Rows with OPTSTK: {len(df)}")

    if df.empty:
        print("No OPTSTK rows found, nothing to insert.")
        return

    # Determine trade date: from param or from file
    if trade_date_str is not None:
        trade_date = datetime.fromisoformat(trade_date_str).date()
    else:
        first_td = df["trade_date_raw"].dropna().iloc[0]
        trade_date = parse_trade_date(first_td)
    print(f"Using trade date: {trade_date}")

    # Parse expiry and strike
    df["expiry"] = df["expiry_raw"].apply(parse_expiry)
    df["strike"] = df["strike_raw"].astype(float)

    # Normalize option type
    df["option_type"] = df["option_type"].astype(str).str.upper()

    # Choose an LTP from the price columns (they're already floats)
    price_cols = ["price_1", "price_2", "price_3", "price_4", "price_5"]

    def pick_ltp(row):
        # Prefer later fields, but you can change this if needed
        for col in reversed(price_cols):
            val = row.get(col)
            if pd.notna(val):
                try:
                    return float(val)
                except ValueError:
                    continue
        return None

    df["ltp"] = df.apply(pick_ltp, axis=1)

    # Volume/contracts and open interest
    df["contracts_traded"] = df["contracts_traded"].apply(to_float_or_none)
    df["oi"] = df["oi_1"].apply(
        lambda x: float(x) if pd.notna(x) else None
    )

    db = SessionLocal()
    try:
        inserted = 0

        for _, row in df.iterrows():
            underlying = str(row["underlying"])
            symbol = auto_add_stock_if_missing(db, underlying)

            expiry = row["expiry"]
            strike = row["strike"]
            opt_type = row["option_type"]
            ltp = row["ltp"]
            oi = row["oi"]
            volume = row["contracts_traded"]

            # Optional: skip completely dead contracts
            # if (oi is None or oi == 0) and (volume is None or volume == 0):
            #     continue

            exists = (
                db.query(OptionChain)
                .filter(
                    OptionChain.symbol == symbol,
                    OptionChain.date == trade_date,
                    OptionChain.expiry == expiry,
                    OptionChain.strike == strike,
                    OptionChain.option_type == opt_type,
                )
                .first()
            )
            if exists:
                continue

            oc = OptionChain(
                symbol=symbol,
                date=trade_date,
                expiry=expiry,
                strike=strike,
                option_type=opt_type,
                ltp=ltp,
                oi=oi,
                volume=volume,
            )
            db.add(oc)
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} rows into option_chain.")
    except Exception as e:
        db.rollback()
        print("Error during F&O ingest:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_fno_db.py path/to/FNO_BCYYYYMMDD.csv [YYYY-MM-DD]")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    trade_date_str = sys.argv[2] if len(sys.argv) >= 3 else None

    ingest_fno_file(filepath, trade_date_str)
