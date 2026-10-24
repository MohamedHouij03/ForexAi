"""Phase 7 - walk-forward results of the current training run.

Walk-forward validation runs inside training/train.py (every candidate model is
retrained on an expanding window and tested on the next period, all before the
untouched test period). This script prints those fold-by-fold results.

Usage (from backend/):  python -m training.walk_forward
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.pipeline import current_report


def main() -> int:
    report = current_report(get_settings())
    if report is None:
        print("No trained model yet. Run: python -m training.train", file=sys.stderr)
        return 1
    for name, c in report["comparison"].items():
        wf = c["walk_forward"]
        print(f"\n{name}  (threshold {c['threshold']})  pooled: {wf['trades']} trades, mean {wf['expectancy_r']} R, "
              f"profitable folds {wf['positive_fold_share']:.0%}")
        for f in wf["folds"]:
            exp = f"{f['expectancy_r']:+.3f}" if f["expectancy_r"] is not None else "   n/a"
            print(f"  fold {f['fold']}  {f['start'][:10]} -> {f['end'][:10]}  train {f['train_rows']:>7,}  "
                  f"trades {f['trades']:>4}  mean {exp} R  top-5% {f['top_5pct_expectancy_r']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
