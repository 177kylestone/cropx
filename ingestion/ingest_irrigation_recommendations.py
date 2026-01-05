from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Iterable

import pandas as pd


def _normalize_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)


def ingest_irrigation_recommendations(
    df: pd.DataFrame,
    db_path: str,
) -> None:
    """
    Insert irrigation recommendations with versioning per (recommendation_date, target_date).
    """
    required_cols = {
        "recommendation_date",
        "target_date",
        "recommended_depth_mm",
        "limiting_zone",
        "run_id",
    }
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Missing required columns: {missing}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        for record in df.to_dict(orient="records"):
            rec_date = _normalize_date(record["recommendation_date"])
            target_date = _normalize_date(record["target_date"])
            depth_mm = float(record["recommended_depth_mm"])
            limiting_zone = record["limiting_zone"]
            rationale = record.get("rationale")
            run_id = record["run_id"]

            version = record.get("version")
            if version is None:
                row = cur.execute(
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM irrigation_recommendations
                    WHERE recommendation_date = ? AND target_date = ?;
                    """,
                    (rec_date, target_date),
                ).fetchone()
                version = int(row[0]) + 1 if row else 1

            cur.execute(
                """
                INSERT OR REPLACE INTO irrigation_recommendations (
                    recommendation_date,
                    target_date,
                    recommended_depth_mm,
                    limiting_zone,
                    version,
                    rationale,
                    run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rec_date,
                    target_date,
                    depth_mm,
                    limiting_zone,
                    int(version),
                    rationale,
                    run_id,
                ),
            )

        conn.commit()
    finally:
        conn.close()
