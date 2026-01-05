# run_pipeline.py
"""
CropX Workshop – Pipeline Orchestrator (Strict Mode)

Order of operations:
  0) Ensure calendar horizon (authoritative date spine)
  1) Backfill weather_legacy up to NZ yesterday (DB-derived start; gap-aware)
  2) Fetch + ingest 7-day forecast weather
  3) Register model_runs row
"""

import sys
from pathlib import Path
import sqlite3
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.calendar_ensure_horizon import ensure_calendar_horizon
from ingestion.backfill_weather_legacy import backfill_weather_legacy
from data_sources.weather_fetcher import fetch_forecast_weather
from ingestion.ingest_weather_forecast import ingest_weather_forecast
from data_sources.time_authority import nz_now, utc_now_iso_z

DB_PATH = PROJECT_ROOT / "db" / "cropx.db"

LATITUDE = -43.6
LONGITUDE = 172.2

FORECAST_DISCOUNT_FACTOR = 0.8
CALENDAR_HORIZON_DAYS = 14

WEATHER_FILL_GAPS = True
MARK_CALENDAR_COMPLETE_FROM_WEATHER = False


def create_model_run(db_path: Path, forecast_issue_date: str) -> str:
    """
    Create a new model run record and return run_id.
    """
    run_id = str(uuid.uuid4())
    run_timestamp = utc_now_iso_z()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        conn.execute(
            """
            INSERT INTO model_runs (
                run_id,
                run_timestamp,
                weather_forecast_issue_date,
                notes
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                run_timestamp,
                forecast_issue_date,
                "Weather ingestion run",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return run_id


def run_weather_pipeline() -> str:
    print("Starting CropX pipeline (strict calendar + weather stage)...")

    # Single-run NZ time authority (prevents timezone drift + midnight boundary inconsistencies)
    as_of_nz = nz_now()
    as_of_date = as_of_nz.date()

    print("Ensuring calendar horizon...")
    cal_result = ensure_calendar_horizon(
        db_path=DB_PATH,
        horizon_days=CALENDAR_HORIZON_DAYS,
        as_of_date=as_of_date,
    )
    print(
        f"Calendar ready. inserted_days={cal_result.inserted_days}, "
        f"forced_future_incomplete_days={cal_result.forced_future_incomplete_days}, "
        f"required_end_date={cal_result.required_end_date}"
    )

    print("Backfilling weather_legacy up to NZ yesterday (DB-derived)...")
    backfill_result = backfill_weather_legacy(
        db_path=DB_PATH,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        fill_gaps=WEATHER_FILL_GAPS,
        mark_calendar_complete=MARK_CALENDAR_COMPLETE_FROM_WEATHER,
        as_of_date=as_of_date,
    )

    if backfill_result.did_work:
        print(
            "weather_legacy backfill done:",
            f"window={backfill_result.hist_start.isoformat()} → {backfill_result.hist_end.isoformat()}",
            f"fetched_rows={backfill_result.fetched_rows}",
            sep="\n  ",
        )
    else:
        print("No weather_legacy backfill needed:", backfill_result.reason)

    print("Fetching forecast weather data...")
    forecast_df = fetch_forecast_weather(
        latitude=LATITUDE,
        longitude=LONGITUDE,
        discount_factor=FORECAST_DISCOUNT_FACTOR,
        forecast_issue_date=as_of_date,
    )

    forecast_issue_date = as_of_date.isoformat()

    print(f"Ingesting {len(forecast_df)} forecast records...")
    ingest_weather_forecast(
        df=forecast_df,
        db_path=str(DB_PATH),
    )

    run_id = create_model_run(
        db_path=DB_PATH,
        forecast_issue_date=forecast_issue_date,
    )

    print(f"Model run registered: {run_id}")
    print("Weather stage completed successfully.")
    return run_id


if __name__ == "__main__":
    run_weather_pipeline()
