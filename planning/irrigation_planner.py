from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import sys
from typing import Dict, Optional, Tuple
import uuid

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data_sources.time_authority import utc_now_iso_z
from ingestion.ingest_irrigation_recommendations import ingest_irrigation_recommendations
from planning.irrigation_constraints import WIND_SPEED_LIMIT_KMH

DEFAULT_IRRIGATION_MONTHS = {9, 10, 11, 12, 1, 2, 3, 4}


@dataclass(frozen=True)
class RecommendationConfig:
    horizon_days: int = 7
    target_paw_pct: float = 100.0
    max_daily_irrigation_mm: float = 6.0
    min_irrigation_event_mm: float = 5.0
    irrigation_allowed_months: Optional[set[int]] = None
    wind_speed_limit_kmh: float = WIND_SPEED_LIMIT_KMH
    kc_default: float = 1.0
    p_default: float = 0.45
    rainfall_efficiency: float = 1.0


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
        raise RuntimeError("weather_forecast is empty; cannot plan recommendations.")
    return latest


def _get_latest_soil_state_date(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT MAX(date) FROM soil_water_state;").fetchone()
    latest = _date_from_db(row[0]) if row else None
    if latest is None:
        raise RuntimeError("soil_water_state is empty; cannot plan recommendations.")
    return latest


def _load_soil_state(conn: sqlite3.Connection, state_date: date) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT zone_id, PAW_pct
        FROM soil_water_state
        WHERE date = ?
        ORDER BY zone_id ASC;
        """,
        conn,
        params=(state_date.isoformat(),),
    )
    if df.empty:
        raise RuntimeError(f"No soil_water_state rows for {state_date.isoformat()}.")
    return df


def _select_limiting_zone(soil_state_df: pd.DataFrame) -> Tuple[str, float]:
    ordered = soil_state_df.sort_values(["PAW_pct", "zone_id"], ascending=[True, True])
    row = ordered.iloc[0]
    return str(row["zone_id"]), float(row["PAW_pct"])


def _load_zone_total_paw(conn: sqlite3.Connection) -> Dict[str, float]:
    rows = conn.execute(
        """
        SELECT zone_id, PAW_mm_per_m, effective_root_depth_m
        FROM soil_zones;
        """
    ).fetchall()
    if not rows:
        raise RuntimeError("soil_zones is empty; cannot plan recommendations.")
    return {zone_id: float(paw_mm_per_m) * float(root_depth_m) for zone_id, paw_mm_per_m, root_depth_m in rows}


def _load_forecast(
    conn: sqlite3.Connection,
    forecast_issue_date: date,
    *,
    horizon_days: int,
) -> pd.DataFrame:
    end_date = forecast_issue_date + timedelta(days=horizon_days - 1)
    df = pd.read_sql_query(
        """
        SELECT target_date, rainfall_mm_discounted, ET0_mm, wind_speed_kmh
        FROM weather_forecast
        WHERE forecast_issue_date = ?
          AND target_date BETWEEN ? AND ?
        ORDER BY target_date ASC;
        """,
        conn,
        params=(forecast_issue_date.isoformat(), forecast_issue_date.isoformat(), end_date.isoformat()),
    )
    if df.empty:
        raise RuntimeError(
            f"No weather_forecast rows for issue_date {forecast_issue_date.isoformat()}."
        )
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df


def _load_crop_params(
    conn: sqlite3.Connection,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT date, Kc, depletion_fraction_p
        FROM crop_parameters
        WHERE date BETWEEN ? AND ?;
        """,
        conn,
        params=(start_date.isoformat(), end_date.isoformat()),
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _create_model_run(conn: sqlite3.Connection, forecast_issue_date: date) -> str:
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
        (run_id, utc_now_iso_z(), forecast_issue_date.isoformat(), "Irrigation recommendations"),
    )
    return run_id


def plan_irrigation_recommendations(
    forecast_df: pd.DataFrame,
    crop_params_df: pd.DataFrame,
    *,
    limiting_zone_id: str,
    limiting_zone_paw_pct: float,
    total_paw_mm: float,
    recommendation_date: date,
    state_date: date,
    config: RecommendationConfig,
) -> pd.DataFrame:
    if total_paw_mm <= 0:
        raise ValueError("total_paw_mm must be positive.")
    if config.target_paw_pct <= 0 or config.target_paw_pct > 100:
        raise ValueError("target_paw_pct must be in (0, 100].")

    allowed_months = config.irrigation_allowed_months or DEFAULT_IRRIGATION_MONTHS
    crop_map = {
        row["date"]: (float(row["Kc"]), float(row["depletion_fraction_p"]))
        for _, row in crop_params_df.iterrows()
    }

    storage_mm = total_paw_mm * (limiting_zone_paw_pct / 100.0)
    target_storage = total_paw_mm * (config.target_paw_pct / 100.0)

    rows = []
    for _, row in forecast_df.iterrows():
        day = row["target_date"]
        kc, p = crop_map.get(day, (config.kc_default, config.p_default))
        min_paw_pct = max(0.0, min(100.0, (1.0 - p) * 100.0))
        min_storage = total_paw_mm * (min_paw_pct / 100.0)

        etc_mm = float(row["ET0_mm"]) * kc
        effective_rain = float(row["rainfall_mm_discounted"]) * config.rainfall_efficiency
        projected_storage = storage_mm + effective_rain - etc_mm

        irrigation_mm = 0.0
        reasons = []
        if day.month not in allowed_months:
            reasons.append("Off-season")
        if float(row["wind_speed_kmh"]) > config.wind_speed_limit_kmh:
            reasons.append("Wind limit exceeded")

        if not reasons and projected_storage < min_storage:
            needed = target_storage - projected_storage
            if needed >= config.min_irrigation_event_mm:
                irrigation_mm = min(needed, config.max_daily_irrigation_mm)

        storage_mm = projected_storage + irrigation_mm
        if storage_mm > total_paw_mm:
            storage_mm = total_paw_mm
        if storage_mm < 0:
            storage_mm = 0.0

        rationale = f"Limiting zone {limiting_zone_id}."
        if reasons:
            rationale = f"{rationale} " + "; ".join(reasons) + "."

        rows.append(
            {
                "recommendation_date": recommendation_date,
                "target_date": day,
                "recommended_depth_mm": float(irrigation_mm),
                "limiting_zone": limiting_zone_id,
                "rationale": rationale,
            }
        )

    return pd.DataFrame(rows)


def run_irrigation_recommendations(
    *,
    db_path: Path | str,
    forecast_issue_date: Optional[date] = None,
    config: Optional[RecommendationConfig] = None,
) -> str:
    db_path = Path(db_path)
    config = config or RecommendationConfig()

    conn = _connect(db_path)
    try:
        issue_date = forecast_issue_date or _get_latest_forecast_issue_date(conn)
        state_date = _get_latest_soil_state_date(conn)
        if state_date not in {issue_date, issue_date - timedelta(days=1)}:
            raise RuntimeError(
                "soil_water_state date does not align with forecast issue date. "
                f"latest soil state={state_date.isoformat()}, "
                f"forecast issue date={issue_date.isoformat()}."
            )

        soil_state_df = _load_soil_state(conn, state_date)
        limiting_zone_id, limiting_zone_paw_pct = _select_limiting_zone(soil_state_df)
        zone_paw = _load_zone_total_paw(conn)
        total_paw_mm = zone_paw[limiting_zone_id]

        forecast_df = _load_forecast(conn, issue_date, horizon_days=config.horizon_days)
        if len(forecast_df) < config.horizon_days:
            raise RuntimeError(
                f"weather_forecast has only {len(forecast_df)} days; "
                f"need {config.horizon_days}."
            )

        crop_df = _load_crop_params(
            conn,
            forecast_df["target_date"].min(),
            forecast_df["target_date"].max(),
        )

        run_id = _create_model_run(conn, issue_date)
        recommendations = plan_irrigation_recommendations(
            forecast_df=forecast_df,
            crop_params_df=crop_df,
            limiting_zone_id=limiting_zone_id,
            limiting_zone_paw_pct=limiting_zone_paw_pct,
            total_paw_mm=total_paw_mm,
            recommendation_date=issue_date,
            state_date=state_date,
            config=config,
        )
    finally:
        conn.close()

    recommendations["run_id"] = run_id
    ingest_irrigation_recommendations(recommendations, db_path=str(db_path))
    return run_id


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate irrigation recommendations.")
    parser.add_argument("--db-path", default=str(PROJECT_ROOT / "db" / "cropx.db"))
    parser.add_argument("--forecast-issue-date", default=None, help="YYYY-MM-DD (default: latest)")
    parser.add_argument("--horizon-days", type=int, default=7)
    parser.add_argument("--target-paw-pct", type=float, default=100.0)
    parser.add_argument("--max-daily-irrigation-mm", type=float, default=6.0)
    parser.add_argument("--min-irrigation-event-mm", type=float, default=5.0)
    parser.add_argument("--irrigation-months", default="9,10,11,12,1,2,3,4")
    parser.add_argument("--wind-speed-limit-kmh", type=float, default=WIND_SPEED_LIMIT_KMH)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    issue_date = date.fromisoformat(args.forecast_issue_date) if args.forecast_issue_date else None
    irrigation_months = {
        int(m.strip()) for m in args.irrigation_months.split(",") if m.strip()
    }
    config = RecommendationConfig(
        horizon_days=args.horizon_days,
        target_paw_pct=args.target_paw_pct,
        max_daily_irrigation_mm=args.max_daily_irrigation_mm,
        min_irrigation_event_mm=args.min_irrigation_event_mm,
        irrigation_allowed_months=irrigation_months,
        wind_speed_limit_kmh=args.wind_speed_limit_kmh,
    )
    run_id = run_irrigation_recommendations(
        db_path=Path(args.db_path),
        forecast_issue_date=issue_date,
        config=config,
    )
    print(f"Irrigation recommendations stored. run_id={run_id}")
