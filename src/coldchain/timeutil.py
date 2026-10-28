"""All simulation times are integer epoch-minutes (UTC); strings are produced only at the edges."""
from __future__ import annotations

import numpy as np
import pandas as pd

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
COMPACT_FMT = "%Y%m%dT%H%M%SZ"
T0 = int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()) // 60  # fixed simulation start


def _fmt(minutes, fmt):
    a = np.atleast_1d(np.asarray(minutes, dtype="int64"))
    return pd.to_datetime(a * 60, unit="s").strftime(fmt).to_numpy(dtype=object)


def iso(minutes):
    """Array of epoch-minutes -> array of ISO-8601 UTC strings."""
    return _fmt(minutes, TS_FMT)


def iso1(minute) -> str:
    return str(_fmt([minute], TS_FMT)[0])


def compact(minutes):
    return _fmt(minutes, COMPACT_FMT)


def date_of(minute) -> str:
    return iso1(minute)[:10]


def to_minutes(series: pd.Series) -> np.ndarray:
    """ISO strings -> epoch-minutes (NaN-safe: invalid -> -1).

    Resolution-independent: pandas 2.x parses to datetime64[ns], pandas 3.x to datetime64[us]/[s], so the
    value is computed as a Timedelta division rather than by assuming a unit.
    """
    ts = pd.to_datetime(series, format=TS_FMT, errors="coerce")
    minutes = (ts - pd.Timestamp("1970-01-01")) // pd.Timedelta(minutes=1)
    return minutes.fillna(-1).to_numpy(dtype="int64")
