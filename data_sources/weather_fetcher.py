# data_sources/weather_fetcher.py

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

from datetime import date
from typing import Optional

from data_sources.time_authority import NZ_TZ, nz_today


def _build_client(cache_expire_seconds: int):
    """
    Build Open-Meteo client with caching and retries.
    """
    cache_session = requests_cache.CachedSession(
        ".cache",
        expire_after=cache_expire_seconds,
    )
    retry_session = retry(
        cache_session,
        retries=5,
        backoff_factor=0.2,
    )
    return openmeteo_requests.Client(session=retry_session)


def fetch_historical_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Fetch historical daily weather and normalize to NZ calendar dates.

    Returns a DataFrame ready for ingestion into weather_legacy.
    """
    client = _build_client(cache_expire_seconds=-1)

    url = "https://archive-api.open-meteo.com/v1/archive"
    daily_vars = [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "et0_fao_evapotranspiration",
        "wind_speed_10m_max",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": daily_vars,
        "timezone": "Pacific/Auckland",
    }

    response = client.weather_api(url, params=params)[0]
    daily = response.Daily()

    start_ts = (
        pd.to_datetime(daily.Time(), unit="s", utc=True)
        .tz_convert(NZ_TZ)
        .normalize()
    )

    values = {
        name: daily.Variables(i).ValuesAsNumpy()
        for i, name in enumerate(daily_vars)
    }
    n_days = len(values["temperature_2m_max"])

    dates = pd.date_range(
        start=start_ts,
        periods=n_days,
        freq="D",
    )

    df = pd.DataFrame(
        {
            "date": dates.date,
            "rainfall_mm": values["precipitation_sum"],
            "ET0_mm": values["et0_fao_evapotranspiration"],
            "wind_speed_kmh": values["wind_speed_10m_max"],
            "Tmin_C": values["temperature_2m_min"],
            "Tmax_C": values["temperature_2m_max"],
            "data_quality": "archive_openmeteo",
        }
    )

    return df


def fetch_forecast_weather(
    latitude: float,
    longitude: float,
    discount_factor: float = 0.8,
    *,
    forecast_issue_date: Optional[date] = None,
) -> pd.DataFrame:
    """
    Fetch daily forecast weather with explicit forecast metadata.

    To keep strict mode stable across timezones (and across midnight boundaries
    during a single run), prefer passing forecast_issue_date from the pipeline's
    single NZ "as_of" date.
    """
    client = _build_client(cache_expire_seconds=3600)

    if forecast_issue_date is None:
        forecast_issue_date = nz_today()

    url = "https://api.open-meteo.com/v1/forecast"
    daily_vars = [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "et0_fao_evapotranspiration",
        "wind_speed_10m_max",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": daily_vars,
        "timezone": "Pacific/Auckland",
    }

    response = client.weather_api(url, params=params)[0]
    daily = response.Daily()

    start_ts = (
        pd.to_datetime(daily.Time(), unit="s", utc=True)
        .tz_convert(NZ_TZ)
        .normalize()
    )

    values = {
        name: daily.Variables(i).ValuesAsNumpy()
        for i, name in enumerate(daily_vars)
    }
    n_days = len(values["temperature_2m_max"])

    target_dates = pd.date_range(
        start=start_ts,
        periods=n_days,
        freq="D",
    )

    rainfall_raw = values["precipitation_sum"]

    df = pd.DataFrame(
        {
            "target_date": target_dates.date,
            "forecast_issue_date": forecast_issue_date,
            "rainfall_mm_raw": rainfall_raw,
            "rainfall_mm_discounted": rainfall_raw * discount_factor,
            "ET0_mm": values["et0_fao_evapotranspiration"],
            "wind_speed_kmh": values["wind_speed_10m_max"],
            "Tmin_C": values["temperature_2m_min"],
            "Tmax_C": values["temperature_2m_max"],
        }
    )

    return df
