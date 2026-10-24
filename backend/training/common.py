"""Helpers shared by the training/data scripts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app.data.pipeline import DatasetResult


def parse_utc(value: str) -> datetime:
    """Accept 'YYYY-MM-DD' or a full ISO timestamp; naive values are treated as UTC."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def format_dataset_result(result: DatasetResult) -> str:
    raw_problems = [f"{c.name} ({c.count:,})" for c in result.raw_report.checks
                    if not c.passed and c.severity == "error"]
    closed = result.cleaning.summary["removed_by_reason"].get("market_closed", 0)
    lines = [
        f"RAW DATA (as downloaded): {result.raw_report.rows:,} rows, status {result.raw_report.status}"
        + (f" - errors: {', '.join(raw_problems)}" if raw_problems else "")
        + (f"; {closed:,} candles outside market hours" if closed else ""),
        "  -> such rows are removed from the ML dataset (never repaired); see data/reports/rejected_*.csv",
        "",
        result.report.format_text(),
    ]
    if result.parquet_path:
        lines.append(f"ML dataset: {result.parquet_path}")
    return "\n".join(lines)
