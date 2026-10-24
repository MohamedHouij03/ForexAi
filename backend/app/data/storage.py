"""Local file storage for datasets (Parquet: compact, typed, fast to load)."""

from pathlib import Path

import pandas as pd


def dataset_path(data_dir: Path, instrument: str, granularity: str) -> Path:
    """Cleaned, ML-ready candles (raw provider data stays in the database)."""
    return data_dir / "datasets" / f"{instrument}_{granularity}.parquet"


def validation_report_path(reports_dir: Path, instrument: str, granularity: str, raw: bool = False) -> Path:
    return reports_dir / f"validation_{instrument}_{granularity}{'_raw' if raw else ''}.json"


def rejected_rows_path(reports_dir: Path, instrument: str, granularity: str) -> Path:
    return reports_dir / f"rejected_{instrument}_{granularity}.csv"


def save_parquet(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # atomic: readers never see a half-written file
    return path


def load_parquet(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df
