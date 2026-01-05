from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class SoilWaterBalanceResult:
    soil_state: pd.DataFrame
    irrigation_events: pd.DataFrame


def simulate_soil_water_balance(
    weather_df: pd.DataFrame,
    *,
    total_paw_mm: float,
    initial_paw_pct: float = 85.0,
    kc_by_date: Optional[Dict[pd.Timestamp, float]] = None,
    kc_default: float = 1.0,
    rainfall_efficiency: float = 0.9,
    target_paw_pct: Optional[float] = None,
    min_paw_pct: Optional[float] = None,
    irrigation_allowed_months: Optional[Iterable[int]] = None,
    max_daily_irrigation_mm: float = 6.0,
    min_irrigation_event_mm: float = 5.0,
) -> SoilWaterBalanceResult:
    """
    Simulate daily soil water balance from weather inputs.
    """
    if total_paw_mm <= 0:
        raise ValueError("total_paw_mm must be positive.")
    if not 0 < initial_paw_pct <= 100:
        raise ValueError("initial_paw_pct must be in (0, 100].")
    if "date" not in weather_df.columns:
        raise ValueError("weather_df missing required column: date")

    if target_paw_pct is not None and min_paw_pct is None:
        raise ValueError("min_paw_pct is required when target_paw_pct is set.")

    weather = weather_df.copy()
    weather["date"] = pd.to_datetime(weather["date"]).dt.date
    weather = weather.sort_values("date")

    storage_mm = total_paw_mm * (initial_paw_pct / 100.0)
    soil_rows = []
    irrig_rows = []

    allowed_months = set(irrigation_allowed_months) if irrigation_allowed_months else None

    for _, row in weather.iterrows():
        day = row["date"]
        kc = kc_by_date.get(day, kc_default) if kc_by_date else kc_default
        et0_mm = float(row["ET0_mm"])
        rainfall_mm = float(row["rainfall_mm"])

        etc_mm = et0_mm * kc
        effective_rain = max(0.0, rainfall_mm * rainfall_efficiency)

        irrigation_mm = 0.0
        projected_storage = storage_mm + effective_rain - etc_mm

        if target_paw_pct is not None and min_paw_pct is not None:
            if allowed_months is None or day.month in allowed_months:
                min_storage = total_paw_mm * (min_paw_pct / 100.0)
                target_storage = total_paw_mm * (target_paw_pct / 100.0)
                if projected_storage < min_storage:
                    needed = target_storage - projected_storage
                    if needed >= min_irrigation_event_mm:
                        irrigation_mm = min(needed, max_daily_irrigation_mm)

        storage_mm = projected_storage + irrigation_mm
        drainage_flag = storage_mm > total_paw_mm
        if drainage_flag:
            storage_mm = total_paw_mm
        if storage_mm < 0:
            storage_mm = 0.0

        paw_pct = (storage_mm / total_paw_mm) * 100.0
        water_deficit_mm = total_paw_mm - storage_mm

        soil_rows.append(
            {
                "date": day,
                "PAW_pct": paw_pct,
                "water_deficit_mm": water_deficit_mm,
                "drainage_flag": drainage_flag,
            }
        )

        if irrigation_mm > 0:
            irrig_rows.append(
                {
                    "date": day,
                    "depth_mm": irrigation_mm,
                }
            )

    soil_df = pd.DataFrame(soil_rows)
    irrigation_df = pd.DataFrame(irrig_rows)
    return SoilWaterBalanceResult(soil_state=soil_df, irrigation_events=irrigation_df)
