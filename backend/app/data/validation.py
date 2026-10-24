"""Dataset quality checks for downloaded candles.

Status semantics:
  PASS - no problems found.
  WARN - usable, but review the warnings (gaps, unusual spreads, big moves).
  FAIL - structurally broken data (duplicates, impossible prices, bad
         timestamps). Must be fixed before any feature engineering / training.

Missing candles are *reported, never filled*: inventing prices would leak
fabricated information into the model.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.core.market_hours import expected_candle_times, holiday_mask, weekly_open_mask

Severity = Literal["error", "warning", "info"]  # "info" never changes the status
CORE_COLUMNS = ("time", "open", "high", "low", "close")
BID_ASK_COLUMNS = tuple(f"{side}_{k}" for side in ("bid", "ask") for k in ("open", "high", "low", "close"))
# Optional field groups: checked only when the provider supplies them (e.g. Twelve Data has neither).
OPTIONAL_GROUPS = {"bid_ask": BID_ASK_COLUMNS, "volume": ("volume",)}
PRICE_EPS = 1e-9
MID_TOLERANCE = 1.5e-5  # OANDA rounds mid to 5 dp, so (bid+ask)/2 may differ by 0.000005
SHORT_GAP_CANDLES = 4  # <= 1 hour on M15
LONG_GAP_SECONDS = 24 * 3600


@dataclass
class Check:
    name: str
    severity: Severity
    count: int
    message: str
    examples: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.count == 0

    def to_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


@dataclass
class ValidationReport:
    instrument: str
    granularity: str
    generated_at: str
    rows: int
    fields_available: dict
    first_time: str | None
    last_time: str | None
    checks: list[Check]
    coverage: dict
    coverage_by_year: list[dict]
    gaps: dict
    spread_pips: dict
    cleaning: dict = field(default_factory=dict)

    @property
    def status(self) -> Literal["PASS", "WARN", "FAIL"]:
        failed = [c for c in self.checks if not c.passed and c.severity != "info"]
        if any(c.severity == "error" for c in failed):
            return "FAIL"
        return "WARN" if failed else "PASS"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status
        data["checks"] = [c.to_dict() for c in self.checks]
        return data

    def save_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

    def format_text(self) -> str:
        lines = [
            "=" * 72,
            f"DATASET VALIDATION  {self.instrument} {self.granularity}   STATUS: {self.status}",
            "=" * 72,
            f"Rows:        {self.rows:,}",
            f"Range (UTC): {self.first_time}  ->  {self.last_time}",
            "Fields:      mid OHLC"
            + (" + bid/ask" if self.fields_available.get("bid_ask") else " (no bid/ask)")
            + (" + volume" if self.fields_available.get("volume") else " (no volume)"),
        ]
        if self.cleaning:
            removed = ", ".join(f"{k}: {v:,}" for k, v in self.cleaning["removed_by_reason"].items()) or "none"
            lines.append(f"Cleaning:    {self.cleaning['rows_raw']:,} raw rows -> {self.rows:,} kept (removed {removed})")
        cov = self.coverage
        if cov:
            lines.append(
                f"Coverage:    {cov['coverage_pct']:.3f}%  "
                f"({cov['present']:,} of {cov['expected_excluding_holidays']:,} expected trading candles; "
                f"{cov['missing_excluding_holidays']:,} missing, {cov['holiday_missing']:,} holiday closures)"
            )
        if self.spread_pips:
            s = self.spread_pips
            lines.append(
                f"Spread pips: median {s['median']:.2f} | mean {s['mean']:.2f} | p95 {s['p95']:.2f} | max {s['max']:.2f}"
            )
        lines.append("")
        lines.append("Checks:")
        for c in self.checks:
            mark = "OK  " if c.passed else {"error": "FAIL", "warning": "WARN", "info": "INFO"}[c.severity]
            lines.append(f"  [{mark}] {c.name:<32} {c.count:>8,}  {c.message}")
            for ex in c.examples[:3]:
                lines.append(f"           e.g. {ex}")
        if self.gaps.get("largest"):
            lines.append("")
            lines.append("Largest non-holiday gaps (missing candles during market hours):")
            for g in self.gaps["largest"][:10]:
                lines.append(f"  {g['start']} -> {g['end']}  {g['missing_candles']:>5} candles  ({g['category']})")
        if self.coverage_by_year:
            lines.append("")
            lines.append("Coverage by year:")
            for y in self.coverage_by_year:
                lines.append(
                    f"  {y['year']}: {y['present']:>6,} candles, {y['missing']:>5,} missing, {y['coverage_pct']:.2f}%"
                )
        lines.append("=" * 72)
        return "\n".join(lines)


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


def _examples(times: pd.Series, mask, limit: int) -> list[str]:
    return [_iso(t) for t in times[mask].head(limit)]


def prepare_candles(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, bool]]:
    """Copy with UTC times and numeric optional columns, plus which optional field groups are present."""
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for cols in OPTIONAL_GROUPS.values():
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    available = {g: bool(df[list(cols)].notna().any().any()) for g, cols in OPTIONAL_GROUPS.items()}
    return df, available


def row_error_masks(df: pd.DataFrame, available: dict[str, bool]) -> dict[str, tuple[np.ndarray, str]]:
    """Row-level structural errors (per candle): name -> (mask, message). Input from prepare_candles()."""
    required = list(CORE_COLUMNS) + [c for g, cols in OPTIONAL_GROUPS.items() if available[g] for c in cols]
    null_mask = df[required].isna().any(axis=1).to_numpy()
    valid = ~null_mask
    masks = {"null_values": (null_mask, "rows with missing price/volume/time values")}

    price_sets = {"mid": ""} | ({"bid": "bid_", "ask": "ask_"} if available["bid_ask"] else {})
    for label, prefix in price_sets.items():
        o, h, l, c = (df[f"{prefix}{k}"].to_numpy() for k in ("open", "high", "low", "close"))
        with np.errstate(invalid="ignore"):
            non_pos = (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)
            bad = (h + PRICE_EPS < np.maximum(o, c)) | (l - PRICE_EPS > np.minimum(o, c)) | (h + PRICE_EPS < l)
        masks[f"{label}_non_positive_price"] = (valid & non_pos, f"{label} prices <= 0")
        masks[f"{label}_ohlc_inconsistent"] = (valid & bad, f"{label} high/low do not bracket open/close")

    if available["bid_ask"]:
        crossed = np.zeros(len(df), dtype=bool)
        for k in ("open", "high", "low", "close"):
            crossed |= (df[f"ask_{k}"] + PRICE_EPS < df[f"bid_{k}"]).to_numpy()
        masks["ask_below_bid"] = (valid & crossed, "ask price below bid price (negative spread)")
    if available["volume"]:
        masks["negative_volume"] = ((df["volume"] < 0).to_numpy(), "negative tick volume")
    return masks


def validate_candles(
    df: pd.DataFrame,
    instrument: str,
    granularity: str,
    *,
    min_coverage: float = 0.98,
    max_normal_spread_bps: float = 10.0,
    max_abs_return: float | None = None,
    max_examples: int = 10,
) -> ValidationReport:
    inst = get_instrument(instrument)
    if max_abs_return is None:
        max_abs_return = inst.default_max_abs_return
    freq_seconds = GRANULARITY_SECONDS[granularity]
    now = datetime.now(timezone.utc).isoformat()
    checks: list[Check] = []

    def add(name: str, severity: Severity, mask, message: str, times: pd.Series | None = None) -> None:
        mask = np.asarray(mask, dtype=bool)
        examples = _examples(times, mask, max_examples) if times is not None else []
        checks.append(Check(name, severity, int(mask.sum()), message, examples))

    missing_cols = [c for c in CORE_COLUMNS if c not in df.columns]
    if missing_cols or df.empty:
        msg = f"missing columns: {missing_cols}" if missing_cols else "dataset is empty"
        checks.append(Check("dataset_structure", "error", 1, msg))
        return ValidationReport(instrument, granularity, now, len(df), {}, None, None, checks, {}, [], {}, {})

    df, available = prepare_candles(df)
    times = df["time"]
    has_bid_ask, has_volume = available["bid_ask"], available["volume"]
    errors = row_error_masks(df, available)
    null_mask = errors["null_values"][0]
    valid = ~null_mask

    # ---------------------------------------------------------- structure
    add("null_values", "error", null_mask, errors["null_values"][1], times)

    dup_mask = times.duplicated(keep=False)
    add("duplicate_timestamps", "error", dup_mask, "rows sharing a timestamp", times)

    unsorted = np.r_[False, (times.diff().dt.total_seconds() <= 0).to_numpy()[1:]] & ~dup_mask.to_numpy()
    add("out_of_order", "error", unsorted, "timestamps not strictly increasing", times)

    epoch_seconds = (times - pd.Timestamp(0, tz="UTC")).dt.total_seconds()  # resolution-independent
    add("unaligned_timestamps", "error", (epoch_seconds % freq_seconds) != 0,
        f"timestamps not aligned to {granularity} boundaries", times)

    # ------------------------------------------------------------- prices
    for name, (mask, message) in errors.items():
        if name not in ("null_values", "negative_volume"):
            add(name, "error", mask, message, times)

    if has_bid_ask:
        mid_off = (
            ((df["open"] - (df["bid_open"] + df["ask_open"]) / 2).abs() > MID_TOLERANCE)
            | ((df["close"] - (df["bid_close"] + df["ask_close"]) / 2).abs() > MID_TOLERANCE)
        )
        add("mid_not_between_bid_ask", "warning", valid & mid_off, "mid open/close differs from (bid+ask)/2", times)

        spread_pips = (df["ask_close"] - df["bid_close"]) / inst.pip_size
        add("zero_spread", "warning", valid & (spread_pips.abs() <= PRICE_EPS), "closing spread of exactly zero", times)
        spread_bps = (df["ask_close"] - df["bid_close"]) / df["close"] * 1e4
        add("wide_spread", "warning", spread_bps > max_normal_spread_bps,
            f"closing spread > {max_normal_spread_bps:g} bp of price (rollover/news/illiquid periods)", times)
    else:
        checks.append(Check("bid_ask_not_provided", "info", len(df),
                            "source provides mid prices only; backtests must apply a modelled spread"))

    if has_volume:
        add("negative_volume", "error", errors["negative_volume"][0], errors["negative_volume"][1], times)
        add("zero_volume", "warning", df["volume"] == 0, "zero tick volume (no price updates)", times)
    else:
        checks.append(Check("volume_not_provided", "info", len(df), "source provides no volume"))

    returns = df["close"].pct_change().abs()
    add("extreme_returns", "warning", returns > max_abs_return,
        f"close-to-close move > {max_abs_return:.1%} between consecutive candles", times)

    # ------------------------------------------------------ market hours
    add("candles_while_market_closed", "warning", ~weekly_open_mask(times, inst.asset_class),
        "candles stamped during the weekend closure", times)

    # --------------------------------------------------------------- gaps
    coverage, coverage_by_year, gaps, gap_checks = _gap_analysis(
        times, freq_seconds, inst.asset_class, min_coverage, max_examples
    )
    checks.extend(gap_checks)

    spread_stats = {}
    if has_bid_ask and valid.any():
        sp = spread_pips[valid]
        spread_stats = {
            "mean": float(sp.mean()), "median": float(sp.median()),
            "p95": float(sp.quantile(0.95)), "p99": float(sp.quantile(0.99)),
            "min": float(sp.min()), "max": float(sp.max()),
        }

    return ValidationReport(
        instrument=instrument,
        granularity=granularity,
        generated_at=now,
        rows=len(df),
        fields_available=available,
        first_time=_iso(times.min()),
        last_time=_iso(times.max()),
        checks=checks,
        coverage=coverage,
        coverage_by_year=coverage_by_year,
        gaps=gaps,
        spread_pips=spread_stats,
    )


def _gap_analysis(times: pd.Series, freq_seconds: int, asset_class: str, min_coverage: float, max_examples: int):
    expected = expected_candle_times(times.min(), times.max(), freq_seconds, asset_class)
    missing = ~expected.isin(pd.DatetimeIndex(times.unique()))
    holiday = holiday_mask(expected, asset_class)

    # Run-length encode the missing flags over the expected-candle sequence.
    runs = []
    holiday_run_mask = np.zeros(len(expected), dtype=bool)
    if missing.any():
        padded = np.r_[0, missing.astype(np.int8), 0]
        edges = np.flatnonzero(np.diff(padded))
        for s, e in zip(edges[0::2], edges[1::2] - 1):
            n = int(e - s + 1)
            is_holiday = bool(holiday[s:e + 1].any())
            if is_holiday:
                category = "holiday"
                holiday_run_mask[s:e + 1] = True
            elif n <= SHORT_GAP_CANDLES:
                category = "short"
            elif n * freq_seconds <= LONG_GAP_SECONDS:  # count trading time only; gaps may straddle a weekend
                category = "medium"
            else:
                category = "long"
            runs.append({"start": _iso(expected[s]), "end": _iso(expected[e]),
                         "missing_candles": n, "category": category})

    considered = ~holiday_run_mask
    expected_n = int(considered.sum())
    missing_n = int((missing & considered).sum())
    coverage_ratio = (expected_n - missing_n) / expected_n if expected_n else 1.0
    coverage = {
        "expected_excluding_holidays": expected_n,
        "present": expected_n - missing_n,
        "missing_excluding_holidays": missing_n,
        "holiday_missing": int((missing & holiday_run_mask).sum()),
        "coverage_pct": round(coverage_ratio * 100, 4),
        "min_coverage_pct": min_coverage * 100,
    }

    by_year = []
    years = expected.year
    for year in np.unique(years):
        m = (years == year) & considered
        exp_y, miss_y = int(m.sum()), int((missing & m).sum())
        by_year.append({
            "year": int(year), "expected": exp_y, "present": exp_y - miss_y, "missing": miss_y,
            "coverage_pct": round((exp_y - miss_y) / exp_y * 100, 3) if exp_y else 100.0,
        })

    non_holiday = [r for r in runs if r["category"] != "holiday"]
    summary = {cat: {"gaps": sum(1 for r in runs if r["category"] == cat),
                     "missing_candles": sum(r["missing_candles"] for r in runs if r["category"] == cat)}
               for cat in ("short", "medium", "long", "holiday")}
    gaps = {
        "summary": summary,
        "largest": sorted(non_holiday, key=lambda r: r["missing_candles"], reverse=True)[:25],
    }

    long_runs = [r for r in runs if r["category"] == "long"]
    checks = [
        Check("coverage_below_threshold", "warning", int(coverage_ratio < min_coverage),
              f"coverage {coverage_ratio:.2%} vs required {min_coverage:.2%}"),
        Check("long_gaps", "warning", len(long_runs),
              "non-holiday gaps of more than 1 day of trading candles",
              [f"{r['start']} -> {r['end']} ({r['missing_candles']} candles)" for r in long_runs[:max_examples]]),
        Check("missing_candles", "info", missing_n,
              f"expected market-hours candles absent ({summary['short']['gaps']} short, "
              f"{summary['medium']['gaps']} medium, {summary['long']['gaps']} long gaps)",
              [f"{r['start']} ({r['missing_candles']} candles)" for r in non_holiday[:max_examples]]),
    ]
    return coverage, by_year, gaps, checks
