"""Training data: features + targets for all instruments, and chronological splits.

The model is trained on all instruments together (features are scale-free),
with two context features:
  is_metal    - 1 for gold/silver/..., 0 for forex
  spread_atr  - trading cost relative to current volatility (spread / ATR);
                the same spread hurts much more when the market is quiet.

Splits are by TIME, never shuffled:
  TRAIN (oldest ~60%) | VALIDATION (~20%) | TEST (most recent ~20%, untouched until the very end)
The boundaries are shared by all instruments. Around each boundary an embargo
of `horizon` candles is removed: a label at time t uses prices up to t+horizon,
so training rows right before the boundary would otherwise "see" validation data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.features.engineering import MODEL_FEATURES
from app.features.store import load_features
from app.models.targets import TargetConfig, make_targets

CONTEXT_FEATURES = ["is_metal", "spread_atr"]
FEATURES = MODEL_FEATURES + CONTEXT_FEATURES


def add_context_features(df: pd.DataFrame, instrument: str, spread_pips: float) -> pd.DataFrame:
    """Instrument context known at decision time. Used identically in training and live."""
    inst = get_instrument(instrument)
    out = df.copy()
    out["is_metal"] = np.int8(inst.asset_class == "metal")
    out["spread_atr"] = inst.pips_to_price(spread_pips) / out["atr_14"]
    return out


def target_config(settings: Settings, instrument: str, horizon: int | None = None) -> TargetConfig:
    return TargetConfig(
        horizon=horizon or settings.max_holding_candles,
        sl_atr=settings.stop_loss_atr_multiplier,
        tp_atr=settings.take_profit_atr_multiplier,
        spread_pips=settings.spread_pips(instrument),
    )


def build_training_frame(settings: Settings, instruments: list[str], granularity: str = "M15",
                         horizon: int | None = None, labelled_only: bool = True) -> pd.DataFrame:
    """Features + context + targets for every instrument.

    labelled_only=True keeps rows usable for training (valid label). False keeps every
    candle whose features are ready - the backtester needs predictions for those too.
    """
    frames = []
    for name in instruments:
        feats = load_features(settings, name, granularity)
        feats = add_context_features(feats, name, settings.spread_pips(name))
        labelled = make_targets(feats, name, target_config(settings, name, horizon), granularity)
        keep = labelled["label_valid"] if labelled_only else labelled["ready"]
        labelled = labelled[keep].copy()
        labelled.insert(0, "instrument", name)
        frames.append(labelled)
    df = pd.concat(frames, ignore_index=True).sort_values(["time", "instrument"], kind="stable")
    df[FEATURES] = df[FEATURES].astype(np.float32)
    return df.reset_index(drop=True)


@dataclass(frozen=True)
class SplitBoundaries:
    validation_start: pd.Timestamp
    test_start: pd.Timestamp
    embargo: pd.Timedelta

    def to_dict(self) -> dict:
        return {"validation_start": self.validation_start.isoformat(), "test_start": self.test_start.isoformat(),
                "embargo_hours": self.embargo.total_seconds() / 3600}


def chronological_boundaries(times: pd.Series, horizon: int, granularity: str = "M15",
                             train_frac: float = 0.6, val_frac: float = 0.2) -> SplitBoundaries:
    """Boundaries at the train/validation/test time quantiles of the (pooled) data."""
    t = pd.Series(pd.to_datetime(times, utc=True)).sort_values()
    val_start = t.iloc[int(len(t) * train_frac)].floor("D")
    test_start = t.iloc[int(len(t) * (train_frac + val_frac))].floor("D")
    embargo = pd.Timedelta(seconds=GRANULARITY_SECONDS[granularity] * horizon)
    return SplitBoundaries(val_start, test_start, embargo)


def split_masks(times: pd.Series, b: SplitBoundaries) -> dict[str, np.ndarray]:
    """Boolean masks for train / validation / test with embargoes before each boundary."""
    t = pd.to_datetime(times, utc=True)
    return {
        "train": (t < b.validation_start - b.embargo).to_numpy(),
        "validation": ((t >= b.validation_start) & (t < b.test_start - b.embargo)).to_numpy(),
        "test": (t >= b.test_start).to_numpy(),
    }


def walk_forward_folds(times: pd.Series, end: pd.Timestamp, n_folds: int, embargo: pd.Timedelta,
                       min_train_frac: float = 0.4) -> list[dict]:
    """Expanding-window folds inside [start, end): train on everything before each fold, test on the fold.

    Only data before `end` (the test start) is used, so the final test period stays untouched.
    """
    t = pd.to_datetime(times, utc=True)
    inside = t[t < end - embargo].sort_values()
    first_fold_start = inside.iloc[int(len(inside) * min_train_frac)]
    edges = pd.date_range(first_fold_start, end - embargo, periods=n_folds + 1)
    folds = []
    for i in range(n_folds):
        start, stop = edges[i], edges[i + 1]
        folds.append({
            "fold": i + 1,
            "train": (t < start - embargo).to_numpy(),
            "test": ((t >= start) & (t < stop - (embargo if i < n_folds - 1 else pd.Timedelta(0)))).to_numpy(),
            "start": start.isoformat(),
            "end": stop.isoformat(),
        })
    return folds
