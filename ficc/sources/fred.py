"""FRED via the keyless CSV endpoint.

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID

No API key, no registration. This is the workhorse: Treasury constant
maturities, ICE BofA OAS credit indices, breakevens, policy rates, financial
conditions indices. Publication lag is typically T+1 for daily series.

Do not send a browser User-Agent here -- see ficc/http.py.
"""

from __future__ import annotations

import io

import pandas as pd

from .. import cache, http
from ..contract import Series, Status, failed

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _download(series_id: str) -> pd.DataFrame:
    r = http.get("fred", f"{BASE}?id={series_id}")
    df = pd.read_csv(io.StringIO(r.text))
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col)
    # FRED encodes missing observations as "."
    col = df.columns[0]
    df[col] = pd.to_numeric(df[col], errors="coerce")
    df.index.name = "date"
    return df[[col]].dropna()


def get(
    series_id: str,
    label: str = "",
    *,
    unit: str = "",
    cadence_days: float = 1.0,
    ttl: int = cache.TTL_DAILY,
    start: str | None = None,
) -> Series:
    try:
        frame, meta = cache.through("fred", series_id, ttl, lambda: _download(series_id))
    except Exception as e:
        return failed(series_id, label or series_id, "FRED", e)
    if start:
        frame = frame[frame.index >= pd.Timestamp(start)]
    status = Status.OK if meta == "live" else Status.CACHED
    note = "served from cache (source unreachable)" if str(meta).startswith("stale") else ""
    if str(meta).startswith("stale"):
        status = Status.STALE
    return Series(
        key=series_id,
        label=label or series_id,
        frame=frame,
        source="FRED",
        status=status,
        unit=unit,
        cadence_days=cadence_days,
        note=note,
    )


def many(spec: dict[str, str], **kw) -> dict[str, Series]:
    """Fetch a {series_id: label} mapping. Failures come back as failed Series."""
    return {sid: get(sid, label, **kw) for sid, label in spec.items()}
