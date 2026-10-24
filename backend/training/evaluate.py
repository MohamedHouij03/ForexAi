"""Phase 7 - print the evaluation report of the current model (training/train.py creates it).

Usage (from backend/):  python -m training.evaluate
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.pipeline import current_report


def _fmt(stats: dict | None) -> str:
    if not stats or not stats.get("trades"):
        return "no trades"
    return (f"{stats['trades']:>5} trades  mean {stats['expectancy_r']:+.3f} R  win {stats['win_rate']:.1%}  "
            f"PF {stats['profit_factor']}  total {stats['total_r']:+.1f} R")


def main() -> int:
    report = current_report(get_settings())
    if report is None:
        print("No trained model yet. Run: python -m training.train", file=sys.stderr)
        return 1
    p = report["periods"]
    print(f"Model {report['version']}: {report['model']}  threshold {report['threshold']}")
    print(f"Instruments: {', '.join(report['instruments'])}")
    print(f"Train {p['train']['start'][:10]} -> {p['train']['end'][:10]} | validation {p['validation']['start'][:10]} "
          f"-> {p['validation']['end'][:10]} | test {p['test']['start'][:10]} -> {p['test']['end'][:10]}\n")
    print("Model comparison (validation = model selection data; walk-forward = stability over time):")
    for name, c in report["comparison"].items():
        print(f"  {name:<20} validation  {_fmt(c['validation']['chosen'])}")
        print(f"  {'':<20} walk-forward {_fmt(c['walk_forward'])}  profitable folds "
              f"{c['walk_forward']['positive_fold_share']:.0%}")
    t = report["test"]
    print(f"\nFINAL TEST ({report['model']}, untouched period): {_fmt(t)}")
    for inst, s in t.get("by_instrument", {}).items():
        print(f"  {inst:<9} {_fmt(s)}")
    cls = t["classification"]
    print(f"  log-loss {cls['log_loss']} vs no-skill baseline {cls['log_loss_baseline']}")
    print("\nDEPLOYABLE: " + ("YES" if report["deployable"] else "NO - the assistant keeps answering WAIT"))
    for reason in report["not_deployable_reasons"]:
        print(f"  - {reason}")
    print("\nTop features:", ", ".join(list(report["feature_importance"])[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
