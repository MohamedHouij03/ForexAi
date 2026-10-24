"""Build the ML-ready dataset from raw provider candles.

The database keeps candles exactly as downloaded (auditable). This step
produces the dataset that feature engineering and training use:

  * rows with structural errors (missing values, impossible OHLC, ask < bid)
    are REMOVED, never repaired - repairing would invent prices;
  * duplicate timestamps keep the first row;
  * candles in the weekend closure (see app.core.market_hours; forex and
    metals differ) are removed: some feeds publish indicative weekend quotes
    that no broker would fill, and the live system does not trade then.
    Candles inside a metal's daily break are kept.

Removed rows become gaps, which validation reports. Every removed row is kept
with its reason so it can be inspected.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.instruments import get_instrument
from app.core.market_hours import weekly_open_mask
from app.data.validation import prepare_candles, row_error_masks

MARKET_CLOSED = "market_closed"
DUPLICATE = "duplicate"


@dataclass
class CleaningResult:
    clean: pd.DataFrame
    rejected: pd.DataFrame  # raw rows plus a `reason` column

    @property
    def summary(self) -> dict:
        counts = self.rejected["reason"].value_counts().to_dict() if len(self.rejected) else {}
        return {
            "rows_raw": len(self.clean) + len(self.rejected),
            "rows_removed": len(self.rejected),
            "removed_by_reason": {k: int(v) for k, v in sorted(counts.items())},
        }


def clean_candles(df: pd.DataFrame, instrument: str) -> CleaningResult:
    if df.empty:
        return CleaningResult(df.copy(), df.assign(reason=pd.Series(dtype=str)))

    prepared, available = prepare_candles(df)
    prepared = prepared.sort_values("time", kind="stable").reset_index(drop=True)
    reason = np.full(len(prepared), "", dtype=object)

    def mark(mask: np.ndarray, name: str) -> None:
        reason[(reason == "") & mask] = name  # first matching reason wins

    for name, (mask, _) in row_error_masks(prepared, available).items():
        mark(mask, name)
    mark(prepared["time"].duplicated(keep="first").to_numpy(), DUPLICATE)
    mark(~weekly_open_mask(prepared["time"], get_instrument(instrument).asset_class), MARKET_CLOSED)

    keep = reason == ""
    clean = prepared[keep].reset_index(drop=True)
    rejected = prepared[~keep].assign(reason=reason[~keep]).reset_index(drop=True)
    return CleaningResult(clean, rejected)
