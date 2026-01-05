# ingestion/calendar_ensure_horizon.py

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from data_sources.time_authority import nz_today


def get_season(d: date) -> str:
    """
    Meteorological seasons (Southern Hemisphere / NZ):
    Summer: Dec–Feb, Autumn: Mar–May, Winter: Jun–Aug, Spring: Sep–Nov
    """
    m = d.month
    if m in (12, 1, 2):
        return "Summer"
    if m in (3, 4, 5):
        return "Autumn"
    if m in (6, 7, 8):
        return "Winter"
    if m in (9, 10, 11):
        return "Spring"
    return "Unknown"


@dataclass(frozen=True)
class CalendarEnsureResult:
    existing_max_date: Optional[date]
    required_end_date: date
    inserted_days: int
    forced_future_incomplete_days: int


def ensure_calendar_horizon(
    db_path: Path | str,
    horizon_days: int = 14,
    *,
    start_date_if_empty: Optional[date] = None,
    as_of_date: Optional[date] = None,
    force_future_incomplete: bool = True,
) -> CalendarEnsureResult:
    """
    Extend calendar to cover NZ today + horizon_days.

    Pass as_of_date from the pipeline to keep strict mode stable across
    timezones and midnight boundaries during a run.
    """
    db_path = Path(db_path)

    today = as_of_date or nz_today()
    required_end = today + timedelta(days=horizon_days)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        row = cur.execute("SELECT MAX(date) FROM calendar;").fetchone()
        max_date_str = row[0] if row else None

        if max_date_str is None:
            if start_date_if_empty is None:
                raise RuntimeError(
                    "calendar table is empty. "
                    "Run calendar_builder.py once or pass start_date_if_empty."
                )
            existing_max = None
            insert_start = start_date_if_empty
        else:
            existing_max = date.fromisoformat(str(max_date_str))
            insert_start = existing_max + timedelta(days=1)

        inserted = 0
        if insert_start <= required_end:
            days_to_insert = (required_end - insert_start).days + 1
            payload = []
            for i in range(days_to_insert):
                d = insert_start + timedelta(days=i)
                payload.append(
                    (
                        d.isoformat(),
                        d.timetuple().tm_yday,
                        get_season(d),
                        0,
                    )
                )

            cur.executemany(
                """
                INSERT OR IGNORE INTO calendar (date, day_of_year, season, is_complete)
                VALUES (?, ?, ?, ?);
                """,
                payload,
            )
            inserted = cur.rowcount if cur.rowcount != -1 else len(payload)

        forced = 0
        if force_future_incomplete:
            res = cur.execute(
                "UPDATE calendar SET is_complete = 0 WHERE date > ? AND is_complete != 0;",
                (today.isoformat(),),
            )
            forced = res.rowcount if res.rowcount != -1 else 0

        conn.commit()

        return CalendarEnsureResult(
            existing_max_date=existing_max,
            required_end_date=required_end,
            inserted_days=inserted,
            forced_future_incomplete_days=forced,
        )
    finally:
        conn.close()
