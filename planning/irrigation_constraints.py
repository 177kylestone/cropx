from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

WIND_SPEED_LIMIT_KMH = 20.0


@dataclass(frozen=True)
class IrrigationConstraints:
    max_wind_speed_kmh: float = WIND_SPEED_LIMIT_KMH


def add_wind_constraint_flags(
    weather_df: pd.DataFrame,
    *,
    max_wind_speed_kmh: float = WIND_SPEED_LIMIT_KMH,
) -> pd.DataFrame:
    """
    Add is_irrigable_day based on wind speed (non-irrigable if wind > limit).
    """
    if "wind_speed_kmh" not in weather_df.columns:
        raise ValueError("weather_df missing required column: wind_speed_kmh")

    df = weather_df.copy()
    df["is_irrigable_day"] = df["wind_speed_kmh"] <= max_wind_speed_kmh
    return df
