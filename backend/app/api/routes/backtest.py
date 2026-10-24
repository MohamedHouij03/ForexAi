import json
import math

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings

router = APIRouter(tags=["backtest"])
MAX_EQUITY_POINTS = 800
MAX_TRADES = 500


def _clean(value):
    """JSON-safe: NaN/inf -> None."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@router.get("/backtest")
def backtest(
    period: str = Query("test", pattern="^(test|walk_forward)$"),
    version: str | None = Query(None),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Backtest of a model (default: current) on its out-of-sample period: metrics, equity, drawdown, trades."""
    if version is None:
        pointer = settings.models_dir / "current.json"
        if not pointer.exists():
            raise HTTPException(status_code=404, detail="No trained model yet.")
        version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
    folder = settings.models_dir / version
    summary_path = folder / f"backtest_{period}.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail=f"No {period} backtest for {version}. Run scripts\\backtest.cmd")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    equity = pd.read_csv(folder / f"backtest_{period}_equity.csv")
    if len(equity) > MAX_EQUITY_POINTS:  # keep the shape, including the deepest drawdown point
        step = math.ceil(len(equity) / MAX_EQUITY_POINTS)
        keep = set(range(0, len(equity), step)) | {len(equity) - 1, int(equity["drawdown_pct"].idxmin())}
        equity = equity.loc[sorted(keep)]
    trades = pd.read_csv(folder / f"backtest_{period}_trades.csv")
    trades = trades.iloc[::-1].head(MAX_TRADES)  # newest first

    available = [p for p in ("walk_forward", "test") if (folder / f"backtest_{p}.json").exists()]
    return {
        **summary,
        "available_periods": available,
        "equity": [{k: _clean(v) for k, v in row.items()} for row in equity.to_dict("records")],
        "trades": [{k: _clean(v) for k, v in row.items()} for row in trades.to_dict("records")],
        "trades_total": summary["metrics"].get("trades", 0),
    }
