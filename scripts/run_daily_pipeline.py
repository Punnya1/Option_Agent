"""
Daily pipeline:
- Downloads NSE equity + FNO bhavcopies (optional)
- Saves them under data/raw/
- Calls existing ingestion scripts

Safe to re-run (idempotent ingestion).
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, date
import subprocess
import requests

# --------------------------------------------------
# Ensure project root is importable
# --------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.logging_utils import get_logger

logger = get_logger("run_daily_pipeline")

DATA_RAW_EQ = ROOT / "data" / "raw" / "equity"
DATA_RAW_FNO = ROOT / "data" / "raw" / "fno"
DATA_RAW_EQ.mkdir(parents=True, exist_ok=True)
DATA_RAW_FNO.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------
# HTTP session for NSE
# --------------------------------------------------
def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://www.nseindia.com/",
        "Accept": "*/*",
    })
    try:
        s.get("https://www.nseindia.com", timeout=10)
    except Exception as e:
        logger.warning(f"NSE homepage not reachable: {e}")
    return s

# --------------------------------------------------
# Downloaders
# --------------------------------------------------
def download_equity_bhavcopy(session: requests.Session, d: date) -> Path:
    dd = d.strftime("%d%m%Y")
    fname = f"sec_bhavdata_full_{dd}.csv"
    out = DATA_RAW_EQ / fname

    urls = [
        f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{d.strftime('%b').upper()}/{fname}",
        f"https://www1.nseindia.com/content/historical/EQUITIES/{d.year}/{d.strftime('%b').upper()}/{fname}",
    ]

    for url in urls:
        logger.info(f"Trying equity URL: {url}")
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            out.write_text(r.content.decode("utf-8", errors="replace"))
            logger.info(f"Saved equity bhavcopy → {out}")
            return out
        except Exception as e:
            logger.warning(f"Equity download failed: {e}")

    raise RuntimeError("Equity bhavcopy not available")

def download_fno_bhavcopy(session: requests.Session, d: date) -> Path:
    dd = d.strftime("%d%m%Y")
    fname = f"FNO_BC{dd}.DAT"
    out = DATA_RAW_FNO / f"FNO_BC{dd}.csv"

    urls = [
        f"https://archives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{d.strftime('%b').upper()}/{fname}",
        f"https://www1.nseindia.com/content/historical/DERIVATIVES/{d.year}/{d.strftime('%b').upper()}/{fname}",
    ]

    for url in urls:
        logger.info(f"Trying FNO URL: {url}")
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            out.write_text(r.content.decode("utf-8", errors="replace"))
            logger.info(f"Saved FNO bhavcopy → {out}")
            return out
        except Exception as e:
            logger.warning(f"FNO download failed: {e}")

    raise RuntimeError("FNO bhavcopy not available")

# --------------------------------------------------
# Ingestion runners
# --------------------------------------------------
def run_ingest(script: str, path: Path, trade_date: date):
    cmd = ["python", script, str(path), trade_date.isoformat()]
    logger.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

# --------------------------------------------------
# Main
# --------------------------------------------------
def main(trade_date: date, skip_download: bool):
    logger.info(f"Starting pipeline for {trade_date} (skip_download={skip_download})")

    session = None if skip_download else make_session()
    dd = trade_date.strftime("%d%m%Y")

    # ---------------- Equity ----------------
    try:
        eq_file = DATA_RAW_EQ / f"sec_bhavdata_full_{dd}.csv"
        if not skip_download:
            eq_file = download_equity_bhavcopy(session, trade_date)

        if eq_file.exists():
            run_ingest("scripts/ingest_equity_db.py", eq_file, trade_date)
        else:
            logger.warning("Equity file not found; skipping ingestion.")
    except Exception as e:
        logger.warning(f"Equity step skipped: {e}")

    # ---------------- FNO ----------------
    try:
        fno_file = DATA_RAW_FNO / f"FNO_BC{dd}.csv"
        if not skip_download:
            fno_file = download_fno_bhavcopy(session, trade_date)

        if fno_file.exists():
            run_ingest("scripts/ingest_fno_db.py", fno_file, trade_date)
        else:
            logger.warning("FNO file not found; skipping ingestion.")
    except Exception as e:
        logger.warning(f"FNO step skipped: {e}")

    logger.info(f"Pipeline finished for {trade_date}")

# --------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip NSE download and ingest existing files only",
    )
    args = parser.parse_args()

    main(
        datetime.strptime(args.date, "%Y-%m-%d").date(),
        skip_download=args.skip_download,
    )
