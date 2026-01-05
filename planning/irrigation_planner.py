from __future__ import annotations

import pandas as pd

from planning.irrigation_constraints import add_wind_constraint_flags, WIND_SPEED_LIMIT_KMH


def apply_wind_constraints(
    recommendations_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    *,
    date_col: str = "target_date",
    max_wind_speed_kmh: float = WIND_SPEED_LIMIT_KMH,
) -> pd.DataFrame:
    """
    Zero out recommendations on non-irrigable days (wind > limit).
    """
    if date_col not in recommendations_df.columns:
        raise ValueError(f"recommendations_df missing required column: {date_col}")
    if date_col not in forecast_df.columns:
        raise ValueError(f"forecast_df missing required column: {date_col}")

    constrained_forecast = add_wind_constraint_flags(
        forecast_df,
        max_wind_speed_kmh=max_wind_speed_kmh,
    )

    merged = recommendations_df.merge(
        constrained_forecast[[date_col, "is_irrigable_day"]],
        on=date_col,
        how="left",
    )

    if "recommended_depth_mm" not in merged.columns:
        raise ValueError("recommendations_df missing required column: recommended_depth_mm")

    is_irrigable = merged["is_irrigable_day"].fillna(True)
    merged.loc[~is_irrigable, "recommended_depth_mm"] = 0.0

    if "rationale" in merged.columns:
        merged.loc[~is_irrigable, "rationale"] = (
            merged.loc[~is_irrigable, "rationale"].fillna("").astype(str)
            + " Wind limit exceeded; irrigation disabled."
        ).str.strip()

    return merged.drop(columns=["is_irrigable_day"])
