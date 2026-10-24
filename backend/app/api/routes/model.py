from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.models.pipeline import current_report

router = APIRouter(tags=["model"])


@router.get("/model")
def model_summary(settings: Settings = Depends(get_settings)) -> dict:
    """The current trained model: what it is, how it was tested, and whether it may give live signals."""
    report = current_report(settings)
    if report is None:
        raise HTTPException(status_code=404, detail="No model trained yet. Run scripts\\train.cmd")

    def brief(stats: dict | None) -> dict | None:
        if not stats:
            return None
        keys = ("trades", "expectancy_r", "lower_bound_r", "win_rate", "profit_factor", "total_r",
                "buy_trades", "buy_expectancy_r", "sell_trades", "sell_expectancy_r")
        return {k: stats.get(k) for k in keys}

    test = report["test"]
    return {
        "version": report["version"],
        "created_at": report["created_at"],
        "model": report["model"],
        "deployable": report["deployable"],
        "not_deployable_reasons": report["not_deployable_reasons"],
        "threshold": report["threshold"],
        "instruments": report["instruments"],
        "periods": report["periods"],
        "target": report["target"],
        "test": {**brief(test), "by_instrument": {k: brief(v) for k, v in test.get("by_instrument", {}).items()},
                 "classification": test["classification"]},
        "comparison": {
            name: {"threshold": c["threshold"], "validation": brief(c["validation"]["chosen"]),
                   "walk_forward": {**brief(c["walk_forward"]),
                                    "positive_fold_share": c["walk_forward"].get("positive_fold_share")},
                   "log_loss": c["validation"]["classification"]["log_loss"],
                   "log_loss_baseline": c["validation"]["classification"]["log_loss_baseline"]}
            for name, c in report["comparison"].items()
        },
        "feature_importance": dict(list(report["feature_importance"].items())[:15]),
        "prior_runs_seen_test": report.get("prior_runs_seen_test"),
    }
