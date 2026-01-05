"""
initialize_soil_state.py

Initialize baseline soil water state for all soil zones
under a newly created run_id.

Authoritative assumptions:
- Initialization is calendar-anchored
- One record per (date, zone_id)
- Baseline state is Field Capacity (PAW = 100%)
"""

import sqlite3
from datetime import date
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "cropx.db"


def get_initialization_date(conn: sqlite3.Connection) -> str:
    """
    Select the earliest complete calendar date as initialization date.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date
        FROM calendar
        WHERE is_complete = 1
        ORDER BY date ASC
        LIMIT 1
    """)
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("No complete calendar date available for initialization.")
    return row[0]


def initialize_soil_water_state(run_id: str) -> None:
    """
    Initialize soil_water_state for all zones on the initialization date.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    init_date = get_initialization_date(conn)

    # Validate run_id exists
    cursor.execute("""
        SELECT 1 FROM model_runs WHERE run_id = ?
    """, (run_id,))
    if cursor.fetchone() is None:
        raise ValueError(f"run_id '{run_id}' does not exist in model_runs.")

    # Fetch soil zones
    cursor.execute("""
        SELECT zone_id, PAW_mm_per_m, effective_root_depth_m
        FROM soil_zones
    """)
    zones = cursor.fetchall()

    if not zones:
        raise RuntimeError("No soil zones found. Cannot initialize soil water state.")

    records = []
    for zone in zones:
        total_paw_mm = zone["PAW_mm_per_m"] * zone["effective_root_depth_m"]

        records.append((
            init_date,
            zone["zone_id"],
            100.0,                 # PAW_pct
            0.0,                   # water_deficit_mm
            False,                 # drainage_flag
            "initialized",         # data_quality
            run_id
        ))

    cursor.executemany("""
        INSERT OR REPLACE INTO soil_water_state (
            date,
            zone_id,
            PAW_pct,
            water_deficit_mm,
            drainage_flag,
            data_quality,
            run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, records)

    conn.commit()
    conn.close()

    print(f"Initialized soil_water_state for {len(records)} zones on {init_date} (run_id={run_id}).")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("Usage: python initialize_soil_state.py <run_id>")

    initialize_soil_water_state(sys.argv[1])
