"""Build features from the clean dataset.

Features are NOT stored by default: they take under a second to compute, and
recomputing from the clean dataset keeps a single source of truth (no stale
files, no ~50 MB per instrument). `load_features()` is what training and the
API use. Only a small metadata/statistics JSON is written, plus the full table
when explicitly requested (save_table=True) for inspection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import Settings
from app.data.storage import dataset_path, load_parquet, save_parquet
from app.features.engineering import DISPLAY_COLUMNS, FEATURE_VERSION, MODEL_FEATURES, build_features


def features_path(data_dir: Path, instrument: str, granularity: str) -> Path:
    return data_dir / "features" / f"{instrument}_{granularity}.parquet"


def features_meta_path(data_dir: Path, instrument: str, granularity: str) -> Path:
    return data_dir / "features" / f"{instrument}_{granularity}.meta.json"


@dataclass
class FeatureBuildResult:
    instrument: str
    rows: int
    ready_rows: int
    segments: int
    first_ready: str | None
    last_time: str | None
    path: Path | None

    def summary(self) -> str:
        return (f"{self.instrument:<9} {self.rows:>9,} candles  {self.ready_rows:>9,} ready for training  "
                f"{self.segments} segment(s)  up to {self.last_time}")


def load_features(settings: Settings, instrument: str, granularity: str, tail: int | None = None) -> pd.DataFrame:
    """Compute features from the clean dataset (optionally only from the last `tail` candles)."""
    src = dataset_path(settings.data_dir, instrument, granularity)
    if not src.exists():
        raise FileNotFoundError(f"No clean dataset for {instrument} at {src}. Run the downloader first.")
    candles = load_parquet(src)
    if tail is not None:
        candles = candles.tail(tail)
    return build_features(candles, instrument, granularity)


def build_and_save(settings: Settings, instrument: str, granularity: str, save_table: bool = False) -> FeatureBuildResult:
    feats = load_features(settings, instrument, granularity)
    path = save_parquet(feats, features_path(settings.data_dir, instrument, granularity)) if save_table else None
    features_meta_path(settings.data_dir, instrument, granularity).parent.mkdir(parents=True, exist_ok=True)

    ready = feats[feats["ready"]]
    result = FeatureBuildResult(
        instrument=instrument,
        rows=len(feats),
        ready_rows=len(ready),
        segments=int(feats["segment"].nunique()) if len(feats) else 0,
        first_ready=ready["time"].iloc[0].isoformat() if len(ready) else None,
        last_time=feats["time"].iloc[-1].isoformat() if len(feats) else None,
        path=path,
    )
    meta = {
        "instrument": instrument,
        "granularity": granularity,
        "feature_version": FEATURE_VERSION,
        "model_features": MODEL_FEATURES,
        "display_columns": DISPLAY_COLUMNS,
        "rows": result.rows,
        "ready_rows": result.ready_rows,
        "segments": result.segments,
        "first_ready": result.first_ready,
        "last_time": result.last_time,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "feature_stats": _stats(ready),
    }
    features_meta_path(settings.data_dir, instrument, granularity).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result


def _stats(ready: pd.DataFrame) -> dict:
    if ready.empty:
        return {}
    d = ready[MODEL_FEATURES].describe().T
    return {name: {k: round(float(d.loc[name, k]), 6) for k in ("mean", "std", "min", "max")} for name in MODEL_FEATURES}
