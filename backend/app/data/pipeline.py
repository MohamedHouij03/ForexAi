"""Raw candles -> validated raw report -> cleaned ML dataset -> validated dataset report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.core.config import Settings
from app.data.cleaning import CleaningResult, clean_candles
from app.data.storage import dataset_path, rejected_rows_path, save_parquet, validation_report_path
from app.data.validation import ValidationReport, validate_candles


@dataclass
class DatasetResult:
    raw_report: ValidationReport
    report: ValidationReport  # the cleaned dataset; this is the one that gates ML work
    cleaning: CleaningResult
    parquet_path: Path | None


def validate_with_settings(df: pd.DataFrame, settings: Settings, instrument: str, granularity: str) -> ValidationReport:
    return validate_candles(
        df, instrument, granularity,
        min_coverage=settings.validation_min_coverage,
        max_normal_spread_bps=settings.validation_max_normal_spread_bps,
        max_abs_return=settings.validation_max_abs_return,
    )


def build_dataset(raw: pd.DataFrame, settings: Settings, instrument: str, granularity: str) -> DatasetResult:
    reports = settings.reports_dir
    raw_report = validate_with_settings(raw, settings, instrument, granularity)
    raw_report.save_json(validation_report_path(reports, instrument, granularity, raw=True))

    cleaning = clean_candles(raw, instrument)
    report = validate_with_settings(cleaning.clean, settings, instrument, granularity)
    report.cleaning = cleaning.summary
    report.save_json(validation_report_path(reports, instrument, granularity))

    rejected_path = rejected_rows_path(reports, instrument, granularity)
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    cleaning.rejected.to_csv(rejected_path, index=False)

    parquet = None
    if len(cleaning.clean):
        parquet = save_parquet(cleaning.clean, dataset_path(settings.data_dir, instrument, granularity))
    return DatasetResult(raw_report, report, cleaning, parquet)
