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
import json
import pickle
import time
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Sensible TTLs in seconds, by cadence class.
TTL_INTRADAY = 120        # live quotes
TTL_DAILY = 30 * 60       # daily-published series
TTL_WEEKLY = 6 * 60 * 60  # weekly releases
TTL_HEAVY = 24 * 60 * 60  # large static-ish downloads (ACM xls, CFTC zip)


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
        age = time.time() - p.stat().st_mtime
        with p.open("rb") as fh:
            return pickle.load(fh), age < ttl, age
    except Exception:
        return None


def store(source: str, key: str, payload: Any, params: Any = None) -> None:
    try:
        with _path(source, key, params).open("wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # a cache write failure is never fatal


def through(source: str, key: str, ttl: int, fn: Callable[[], Any], params: Any = None):
    """Cache-through with stale fallback.

    Returns (payload, meta) where meta is one of "live", "cached", or
    "stale:<age_seconds>" so the caller can badge the tile accordingly.
    """
    hit = load(source, key, ttl, params)
    if hit is not None and hit[1]:
        return hit[0], "cached"
    try:
        payload = fn()
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
            f.unlink(); n += 1
        except Exception:
            pass
    return n
