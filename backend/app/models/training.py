"""Phases 5-6 - the three candidate models.

All output class probabilities P(SELL), P(WAIT), P(BUY). None is assumed to be
best: they are compared on unseen data (see evaluation.py / training pipeline).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

CLASSES = np.array([-1, 0, 1])  # SELL, WAIT, BUY
MODEL_NAMES = ("logistic_regression", "random_forest", "xgboost")
PROBA_COLUMNS = ["p_sell", "p_wait", "p_buy"]


def make_model(name: str, n_jobs: int = -1, random_state: int = 42):
    if name == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500))
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=200, max_depth=10, min_samples_leaf=200, max_features="sqrt",
            max_samples=0.25, n_jobs=n_jobs, random_state=random_state,
        )
    if name == "xgboost":
        return XGBClassifier(
            objective="multi:softprob", n_estimators=800, learning_rate=0.03, max_depth=4,
            min_child_weight=50, subsample=0.8, colsample_bytree=0.8, reg_lambda=5.0,
            tree_method="hist", n_jobs=n_jobs, random_state=random_state,
            eval_metric="mlogloss", early_stopping_rounds=50,
        )
    raise ValueError(f"Unknown model {name!r}; choose from {MODEL_NAMES}")


def fit_model(name: str, X: pd.DataFrame, y: np.ndarray, X_val: pd.DataFrame | None = None,
              y_val: np.ndarray | None = None, n_jobs: int = -1):
    """Fit and return the model. y uses -1/0/1; internally mapped to 0/1/2."""
    model = make_model(name, n_jobs=n_jobs)
    y_enc = np.searchsorted(CLASSES, y)
    if name == "xgboost":
        if X_val is not None:
            model.fit(X, y_enc, eval_set=[(X_val, np.searchsorted(CLASSES, y_val))], verbose=False)
        else:  # no validation set (final refit): keep the tree count found earlier, or the default
            model.set_params(early_stopping_rounds=None)
            model.fit(X, y_enc, verbose=False)
    else:
        model.fit(X, y_enc)
    return model


def predict_proba(model, X: pd.DataFrame) -> pd.DataFrame:
    proba = model.predict_proba(X)
    return pd.DataFrame(proba, columns=PROBA_COLUMNS, index=X.index)


def feature_importance(name: str, model, features: list[str]) -> dict[str, float]:
    """Normalised importance (sums to 1)."""
    if name == "logistic_regression":
        raw = np.abs(model[-1].coef_).mean(axis=0)
    else:
        raw = np.asarray(model.feature_importances_, dtype=float)
    total = raw.sum() or 1.0
    ranked = sorted(zip(features, raw / total), key=lambda kv: kv[1], reverse=True)
    return {k: round(float(v), 5) for k, v in ranked}
