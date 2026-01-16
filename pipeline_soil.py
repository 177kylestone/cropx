from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional
import uuid
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_sources.time_authority import nz_yesterday, utc_now_iso_z
from models.soil_water_balance import simulate_soil_water_balance


DB_PATH = PROJECT_ROOT / "db" / "cropx.db"


@dataclass(frozen=True)
class BackfillResult:
    run_id: str
    start_date: date
    end_date: date
    rows_inserted: int


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _date_from_db(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _get_latest_forecast_issue_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT MAX(forecast_issue_date) FROM weather_forecast;").fetchone()
    latest = _date_from_db(row[0]) if row else None
    if latest is None:
        raise RuntimeError("weather_forecast is empty; cannot determine backfill end date.")
    return latest


def _get_latest_weather_legacy_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT MAX(date) FROM weather_legacy;").fetchone()
    latest = _date_from_db(row[0]) if row else None
    if latest is None:
        raise RuntimeError("weather_legacy is empty; cannot determine backfill end date.")
    return latest


def _get_min_weather_legacy_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT MIN(date) FROM weather_legacy;").fetchone()
    earliest = _date_from_db(row[0]) if row else None
    if earliest is None:
        raise RuntimeError("weather_legacy is empty; cannot determine backfill start date.")
    return earliest


def _get_latest_soil_state_date(conn: sqlite3.Connection) -> Optional[date]:
    row = conn.execute("SELECT MAX(date) FROM soil_water_state;").fetchone()
    return _date_from_db(row[0]) if row else None


def _resolve_backfill_window(
    conn: sqlite3.Connection,
    *,
    start_date: Optional[date],
    end_date: Optional[date],
) -> Optional[tuple[date, date]]:
    if end_date is None:
        latest_forecast_issue = _get_latest_forecast_issue_date(conn)
        latest_weather = _get_latest_weather_legacy_date(conn)
        end_date = min(latest_forecast_issue, latest_weather)

    if start_date is None:
        last_soil_date = _get_latest_soil_state_date(conn)
        if last_soil_date:
            start_date = last_soil_date + timedelta(days=1)
        else:
            start_date = _get_min_weather_legacy_date(conn)

    if start_date > end_date:
        return None

    return start_date, end_date


def _require_calendar_contiguous(conn: sqlite3.Connection, start: date, end: date) -> None:
    expected = (end - start).days + 1
    row = conn.execute(
        "SELECT COUNT(*) FROM calendar WHERE date BETWEEN ? AND ?;",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    actual = int(row[0]) if row else 0
    if actual != expected:
        raise RuntimeError(
            "calendar table is not contiguous for the requested backfill window. "
            f"Expected {expected} dates, found {actual}."
        )


def _require_weather_legacy(conn: sqlite3.Connection, start: date, end: date) -> None:
    expected = (end - start).days + 1
    row = conn.execute(
        "SELECT COUNT(*) FROM weather_legacy WHERE date BETWEEN ? AND ?;",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    actual = int(row[0]) if row else 0
    if actual != expected:
        raise RuntimeError(
            "weather_legacy is incomplete for the requested backfill window. "
            f"Expected {expected} dates, found {actual}."
        )


def _fetch_kc_by_date(conn: sqlite3.Connection, start: date, end: date) -> Dict[date, float]:
    rows = conn.execute(
        "SELECT date, Kc FROM crop_parameters WHERE date BETWEEN ? AND ?;",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return {date.fromisoformat(r[0]): float(r[1]) for r in rows}


def _create_model_run(conn: sqlite3.Connection, notes: str) -> str:
    run_id = str(uuid.uuid4())
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
        (run_id, utc_now_iso_z(), None, notes),
    )
    return run_id


def backfill_soil_water_state(
    *,
    db_path: Path | str = DB_PATH,
    start_date: date,
    end_date: Optional[date] = None,
    initial_paw_pct: float = 85.0,
    target_paw_pct: float = 100.0,
    min_paw_pct: float = 55.0,
    irrigation_allowed_months: Optional[set[int]] = None,
    max_daily_irrigation_mm: float = 6.0,
    min_irrigation_event_mm: float = 5.0,
    fill_missing_irrigation: bool = True,
    kc_default: float = 1.0,
    rainfall_efficiency: float = 0.9,
) -> BackfillResult:
    """
    Backfill soil_water_state using weather_legacy for the given date window.
    """
    db_path = Path(db_path)
    end_date = end_date or nz_yesterday()

    conn = _connect(db_path)
    try:
        _require_calendar_contiguous(conn, start_date, end_date)
        _require_weather_legacy(conn, start_date, end_date)

        weather_df = pd.read_sql_query(
            """
            SELECT date, rainfall_mm, ET0_mm
            FROM weather_legacy
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC;
            """,
            conn,
            params=(start_date.isoformat(), end_date.isoformat()),
        )

        zones = conn.execute(
            """
            SELECT zone_id, PAW_mm_per_m, effective_root_depth_m
            FROM soil_zones
            ORDER BY zone_id;
            """
        ).fetchall()
        if not zones:
            raise RuntimeError("No soil_zones configured; cannot backfill soil state.")

        kc_by_date = _fetch_kc_by_date(conn, start_date, end_date)

        run_id = _create_model_run(conn, notes="Synthetic soil water backfill")

        records = []
        irrigation_records = []
        for zone_id, paw_mm_per_m, root_depth_m in zones:
            total_paw_mm = float(paw_mm_per_m) * float(root_depth_m)
            result = simulate_soil_water_balance(
                weather_df,
                total_paw_mm=total_paw_mm,
                initial_paw_pct=initial_paw_pct,
                target_paw_pct=target_paw_pct,
                min_paw_pct=min_paw_pct,
                irrigation_allowed_months=irrigation_allowed_months,
                max_daily_irrigation_mm=max_daily_irrigation_mm,
                min_irrigation_event_mm=min_irrigation_event_mm,
                kc_by_date=kc_by_date,
                kc_default=kc_default,
                rainfall_efficiency=rainfall_efficiency,
            )

            zone_df = result.soil_state
            zone_df["zone_id"] = zone_id
            zone_df["data_quality"] = "synthetic_weather_only"
            zone_df["run_id"] = run_id

            records.extend(
                zone_df[
                    [
                        "date",
                        "zone_id",
                        "PAW_pct",
                        "water_deficit_mm",
                        "drainage_flag",
                        "data_quality",
                        "run_id",
                    ]
                ].itertuples(index=False)
            )

            if not result.irrigation_events.empty:
                zone_irrig = result.irrigation_events.copy()
                zone_irrig["zone_id"] = zone_id
                zone_irrig["source"] = "synthetic_backfill"
                irrigation_records.extend(
                    zone_irrig[
                        [
                            "date",
                            "zone_id",
                            "depth_mm",
                            "source",
                        ]
                    ].itertuples(index=False)
                )

        conn.executemany(
            """
            INSERT OR REPLACE INTO soil_water_state (
                date,
                zone_id,
                PAW_pct,
                water_deficit_mm,
                drainage_flag,
                data_quality,
                run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            records,
        )

        if irrigation_records:
            conn.executemany(
                """
                INSERT OR REPLACE INTO irrigation_applied (
                    date,
                    zone_id,
                    depth_mm,
                    source
                )
                VALUES (?, ?, ?, ?);
                """,
                irrigation_records,
            )

        if fill_missing_irrigation:
            unique_dates = weather_df["date"].astype(str).unique().tolist()
            baseline_records = [
                (dt, zone_id, 0.0, "synthetic_backfill_none")
                for zone_id, _, _ in zones
                for dt in unique_dates
            ]
            conn.executemany(
                """
                INSERT OR IGNORE INTO irrigation_applied (
                    date,
                    zone_id,
                    depth_mm,
                    source
                )
                VALUES (?, ?, ?, ?);
                """,
                baseline_records,
            )
        conn.commit()

        return BackfillResult(
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            rows_inserted=len(records),
        )
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill synthetic soil water state.")
    parser.add_argument(
        "--start-date",
        default=None,
        help="YYYY-MM-DD (default: day after latest soil state)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="YYYY-MM-DD (default: min(latest forecast issue, latest weather_legacy))",
    )
    parser.add_argument("--initial-paw-pct", type=float, default=85.0)
    parser.add_argument("--target-paw-pct", type=float, default=100.0)
    parser.add_argument("--min-paw-pct", type=float, default=55.0)
    parser.add_argument("--irrigation-months", default="9,10,11,12,1,2,3,4")
    parser.add_argument("--max-daily-irrigation-mm", type=float, default=6.0)
    parser.add_argument("--min-irrigation-event-mm", type=float, default=5.0)
    parser.add_argument("--no-fill-missing-irrigation", action="store_true")
    parser.add_argument("--kc-default", type=float, default=1.0)
    parser.add_argument("--rainfall-efficiency", type=float, default=0.9)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else None
    irrigation_months = {
        int(m.strip()) for m in args.irrigation_months.split(",") if m.strip()
    }
    conn = _connect(DB_PATH)
    try:
        window = _resolve_backfill_window(conn, start_date=start, end_date=end)
    finally:
        conn.close()

    if window is None:
        print("No missing soil water dates to backfill.")
        raise SystemExit(0)

    start, end = window
    result = backfill_soil_water_state(
        start_date=start,
        end_date=end,
        initial_paw_pct=args.initial_paw_pct,
        target_paw_pct=args.target_paw_pct,
        min_paw_pct=args.min_paw_pct,
        irrigation_allowed_months=irrigation_months,
        max_daily_irrigation_mm=args.max_daily_irrigation_mm,
        min_irrigation_event_mm=args.min_irrigation_event_mm,
        fill_missing_irrigation=not args.no_fill_missing_irrigation,
        kc_default=args.kc_default,
        rainfall_efficiency=args.rainfall_efficiency,
    )
    print(
        "Soil water backfill complete:",
        f"run_id={result.run_id}",
        f"window={result.start_date.isoformat()} → {result.end_date.isoformat()}",
        f"rows_inserted={result.rows_inserted}",
        sep="\n  ",
    )
