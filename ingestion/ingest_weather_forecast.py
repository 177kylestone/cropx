# ingestion/ingest_weather_forecast.py

import sqlite3
import pandas as pd


def ingest_weather_forecast(
    df: pd.DataFrame,
    db_path: str,
):
    """
    Insert forecast weather records with versioning via forecast_issue_date.
    """
    required_cols = {
        "target_date",
        "forecast_issue_date",
        "rainfall_mm_raw",
        "rainfall_mm_discounted",
        "ET0_mm",
        "Tmin_C",
        "Tmax_C",
    }

    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Missing required columns: {missing}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        sql = """
        INSERT OR REPLACE INTO weather_forecast (
            target_date,
            forecast_issue_date,
            rainfall_mm_raw,
            rainfall_mm_discounted,
            ET0_mm,
            Tmin_C,
            Tmax_C
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        conn.executemany(
            sql,
            df[
                [
                    "target_date",
                    "forecast_issue_date",
                    "rainfall_mm_raw",
                    "rainfall_mm_discounted",
                    "ET0_mm",
                    "Tmin_C",
                    "Tmax_C",
                ]
            ].itertuples(index=False),
        )

        conn.commit()
    finally:
        conn.close()
