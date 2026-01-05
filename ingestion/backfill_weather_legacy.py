# ingestion/backfill_weather_legacy.py

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

from data_sources.time_authority import nz_yesterday
from data_sources.weather_fetcher import fetch_historical_weather
from ingestion.ingest_weather_legacy import ingest_weather_legacy


@dataclass(frozen=True)
class BackfillWindow:
    start: date
    end: date


@dataclass(frozen=True)
class BackfillResult:
    did_work: bool
    reason: str
    hist_start: Optional[date] = None
    hist_end: Optional[date] = None
    fetched_rows: int = 0


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _get_calendar_min_max(conn: sqlite3.Connection) -> Tuple[Optional[date], Optional[date]]:
    row = conn.execute("SELECT MIN(date), MAX(date) FROM calendar;").fetchone()
    if not row or row[0] is None or row[1] is None:
        return None, None
    return date.fromisoformat(row[0]), date.fromisoformat(row[1])


def _fail_fast_if_calendar_not_extended(conn: sqlite3.Connection, required_end: date) -> None:
    cal_min, cal_max = _get_calendar_min_max(conn)
    if cal_min is None or cal_max is None:
        raise RuntimeError(
            "calendar table is empty. Strict mode requires calendar as the date spine. "
            "Run ingestion/calendar_builder.py once, then ingestion/calendar_ensure_horizon.py."
        )

    if cal_max < required_end:
        raise RuntimeError(
            f"Strict-mode fail-fast: calendar max date is {cal_max.isoformat()}, "
            f"but NZ yesterday is {required_end.isoformat()}. "
            "Extend calendar first (run ingestion/calendar_ensure_horizon.py)."
        )

    expected_days = (required_end - cal_min).days + 1
    row = conn.execute(
        "SELECT COUNT(*) FROM calendar WHERE date BETWEEN ? AND ?;",
        (cal_min.isoformat(), required_end.isoformat()),
    ).fetchone()
    actual_days = int(row[0]) if row else 0
    if actual_days != expected_days:
        raise RuntimeError(
            "Strict-mode fail-fast: calendar is not contiguous for the required history window. "
            f"Expected {expected_days} dates between {cal_min.isoformat()} and {required_end.isoformat()}, "
            f"found {actual_days}. Repair calendar continuity before weather backfill."
        )


def _derive_backfill_window(
    conn: sqlite3.Connection,
    hist_end: date,
    *,
    fill_gaps: bool = True,
) -> Optional[BackfillWindow]:
    cal_min, _ = _get_calendar_min_max(conn)
    if cal_min is None:
        raise RuntimeError("calendar table is empty; cannot derive backfill window.")

    if fill_gaps:
        row = conn.execute(
            """
            SELECT MIN(c.date)
            FROM calendar c
            WHERE c.date <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM weather_legacy w WHERE w.date = c.date
              );
            """,
            (hist_end.isoformat(),),
        ).fetchone()
        missing_str = row[0] if row else None
        if missing_str is None:
            return None
        start = date.fromisoformat(missing_str)
        return BackfillWindow(start=start, end=hist_end)

    row = conn.execute("SELECT MAX(date) FROM weather_legacy;").fetchone()
    max_weather_str = row[0] if row else None
    if max_weather_str is None:
        start = cal_min
    else:
        start = date.fromisoformat(max_weather_str) + timedelta(days=1)

    if start > hist_end:
        return None
    return BackfillWindow(start=start, end=hist_end)


def backfill_weather_legacy(
    *,
    db_path: Path | str,
    latitude: float,
    longitude: float,
    fill_gaps: bool = True,
    mark_calendar_complete: bool = False,
    as_of_date: Optional[date] = None,
) -> BackfillResult:
    """
    Backfill weather_legacy up to NZ yesterday, deriving HIST_START from DB.

    Pass as_of_date from the pipeline to make the cutoff stable across timezones
    and midnight boundaries during a run.
    """
    db_path = Path(db_path)
    hist_end = (as_of_date - timedelta(days=1)) if as_of_date else nz_yesterday()

    conn = _connect(db_path)
    try:
        _fail_fast_if_calendar_not_extended(conn, required_end=hist_end)

        window = _derive_backfill_window(conn, hist_end=hist_end, fill_gaps=fill_gaps)
        if window is None:
            return BackfillResult(
                did_work=False,
                reason="weather_legacy already complete through NZ yesterday (no gaps / nothing new).",
            )
    finally:
        conn.close()

    df = fetch_historical_weather(
        latitude=latitude,
        longitude=longitude,
        start_date=window.start.isoformat(),
        end_date=window.end.isoformat(),
    )

    ingest_weather_legacy(df=df, db_path=str(db_path))

    if mark_calendar_complete:
        conn2 = _connect(db_path)
        try:
            conn2.execute(
                """
                UPDATE calendar
                SET is_complete = 1
                WHERE date BETWEEN ? AND ?
                  AND EXISTS (SELECT 1 FROM weather_legacy w WHERE w.date = calendar.date);
                """,
                (window.start.isoformat(), window.end.isoformat()),
            )
            conn2.commit()
        finally:
            conn2.close()

    return BackfillResult(
        did_work=True,
        reason="Backfill completed.",
        hist_start=window.start,
        hist_end=window.end,
        fetched_rows=len(df),
    )
