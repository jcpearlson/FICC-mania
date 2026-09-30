"""On-disk TTL cache keyed by (source, key, params).

Two jobs. First, stop a widget interaction from re-fetching sixty series and
getting us rate-limited. Second -- and the reason it stores payloads rather
than just memoising -- let a panel serve last-known-value with an honest
"stale since" badge when a source is down, instead of rendering blank.

TTLs are matched to publication cadence, not chosen arbitrarily: a FRED daily
series does not change within the hour, so re-pulling it is pure waste.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import pickle
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Sensible TTLs in seconds, by cadence class.
TTL_INTRADAY = 120        # live quotes
TTL_DAILY = 30 * 60       # daily-published series
TTL_WEEKLY = 6 * 60 * 60  # weekly releases
TTL_HEAVY = 24 * 60 * 60  # large static-ish downloads (ACM xls, CFTC zip)
FETCHED_AT = "ficc_fetched_at"


def _stamp(payload: Any, fetched_at: dt.datetime) -> Any:
    """Keep the successful pull time with the payload, including on cache hits."""
    if isinstance(payload, (pd.DataFrame, pd.Series)):
        payload = payload.copy()
        payload.attrs.setdefault(FETCHED_AT, fetched_at)
    return payload


def _path(source: str, key: str, params: Any = None) -> Path:
    raw = f"{source}|{key}|{json.dumps(params, sort_keys=True, default=str)}"
    return CACHE_DIR / f"{source}_{hashlib.sha1(raw.encode()).hexdigest()[:20]}.pkl"


def load(source: str, key: str, ttl: int, params: Any = None) -> tuple[Any, bool, float] | None:
    """Return (payload, fresh, age_seconds), or None if nothing is cached.

    `fresh` False means the entry is past its TTL but still usable as a
    fallback -- the caller decides whether to try the network first.
    """
    p = _path(source, key, params)
    if not p.exists():
        return None
    try:
        written = p.stat().st_mtime
        age = time.time() - written
        with p.open("rb") as fh:
            # Legacy payloads have no timestamp; their write time is the best
            # available pull time. Never replace it with the current time.
            payload = _stamp(pickle.load(fh), dt.datetime.fromtimestamp(written, dt.timezone.utc))
            return payload, age < ttl, age
    except Exception:
        return None


def store(source: str, key: str, payload: Any, params: Any = None) -> None:
    try:
        with _path(source, key, params).open("wb") as fh:
            pickle.dump(_stamp(payload, dt.datetime.now(dt.timezone.utc)), fh,
                        protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # a cache write failure is never fatal


class EmptyPayload(ValueError):
    """A fetch that 'succeeded' but returned nothing usable."""


def _check(payload: Any) -> Any:
    """Refuse to cache an empty frame.

    Several sources answer a bad day with HTTP 200 and no rows -- FRED under
    concurrent load, yfinance for a symbol it cannot resolve. Caching that
    would overwrite the last good payload with nothing and then serve the
    nothing for a full TTL, which is strictly worse than the stale fallback.
    Raising here routes it into the same path as a network failure.
    """
    if isinstance(payload, (pd.DataFrame, pd.Series)):
        if payload.empty or payload.isna().all(axis=None):
            raise EmptyPayload("source returned no usable rows")
    return payload


def through(source: str, key: str, ttl: int, fn: Callable[[], Any], params: Any = None):
    """Cache-through with stale fallback.

    Returns (payload, meta) where meta is one of "live", "cached", or
    "stale:<age_seconds>" so the caller can badge the tile accordingly.
    """
    hit = load(source, key, ttl, params)
    if hit is not None and hit[1]:
        return hit[0], "cached"
    try:
        payload = _stamp(_check(fn()), dt.datetime.now(dt.timezone.utc))
        store(source, key, payload, params)
        return payload, "live"
    except Exception:
        if hit is not None:
            return hit[0], f"stale:{int(hit[2])}"
        raise


def clear() -> int:
    n = 0
    for f in CACHE_DIR.glob("*.pkl"):
        try:
            f.unlink()
            n += 1
        except Exception:
            pass
    return n
