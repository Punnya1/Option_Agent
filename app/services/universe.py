from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
FNO_PATH = BASE_DIR / "data" / "fno_universe.csv"


def get_fno_universe():
    df = pd.read_csv(FNO_PATH, comment="#").dropna(subset=["symbol"])
    return df


def get_fno_symbols():
    return get_fno_universe()["symbol"].tolist()
