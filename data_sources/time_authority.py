# data_sources/time_authority.py
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NZ_TZ_NAME = "Pacific/Auckland"

try:
    NZ_TZ = ZoneInfo(NZ_TZ_NAME)
except ZoneInfoNotFoundError as e:
    raise RuntimeError(
        "IANA timezone data not found for 'Pacific/Auckland'. "
        "On Windows, install tzdata: pip install tzdata"
    ) from e


def nz_now() -> datetime:
    """Timezone-aware 'now' in NZ time."""
    return datetime.now(tz=NZ_TZ)


def nz_today(as_of: Optional[datetime] = None) -> date:
    """Authoritative 'today' date in NZ time.

    If as_of is provided, it must be timezone-aware; it will be converted to NZ time.
    """
    if as_of is None:
        return nz_now().date()
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (tzinfo set).")
    return as_of.astimezone(NZ_TZ).date()


def nz_yesterday(as_of: Optional[datetime] = None) -> date:
    """Authoritative NZ 'yesterday' (avoid partial-day totals)."""
    return nz_today(as_of=as_of) - timedelta(days=1)


def utc_now() -> datetime:
    """Timezone-aware 'now' in UTC."""
    return datetime.now(tz=timezone.utc)


def utc_now_iso_z(timespec: str = "seconds") -> str:
    """UTC timestamp as ISO8601 with Z suffix (stable across environments)."""
    return utc_now().isoformat(timespec=timespec).replace("+00:00", "Z")
