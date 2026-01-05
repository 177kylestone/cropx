# ingestion/ingest_weather_legacy.py

import sqlite3
import pandas as pd


def ingest_weather_legacy(
    df: pd.DataFrame,
    db_path: str,
):
    """
    Insert or replace historical weather records.
    """
    required_cols = {
        "date",
        "rainfall_mm",
        "ET0_mm",
        "wind_speed_kmh",
        "Tmin_C",
        "Tmax_C",
        "data_quality",
    }

    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Missing required columns: {missing}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        sql = """
        INSERT OR REPLACE INTO weather_legacy (
            date,
            rainfall_mm,
            ET0_mm,
            wind_speed_kmh,
            Tmin_C,
            Tmax_C,
            data_quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        conn.executemany(
            sql,
            df[
                [
                    "date",
                    "rainfall_mm",
                    "ET0_mm",
                    "wind_speed_kmh",
                    "Tmin_C",
                    "Tmax_C",
                    "data_quality",
                ]
            ].itertuples(index=False),
        )

        conn.commit()
    finally:
        conn.close()
