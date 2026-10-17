"""Disk TTL cache with atomic writes, preserved pull times and stale fallback."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import pickle
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
logger = logging.getLogger(__name__)

# Sensible TTLs in seconds, by cadence class.
TTL_INTRADAY = 120  # live quotes
TTL_DAILY = 30 * 60  # daily-published series
TTL_WEEKLY = 6 * 60 * 60  # weekly releases
TTL_HEAVY = 24 * 60 * 60  # bulk historical downloads
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
    try:
        written = p.stat().st_mtime
        age = max(0.0, time.time() - written)
        with p.open("rb") as fh:
            # Legacy payloads have no timestamp; their write time is the best
            # available pull time. Never replace it with the current time.
            payload = _stamp(
                _check(pickle.load(fh)), dt.datetime.fromtimestamp(written, dt.timezone.utc)
            )
            return payload, age < ttl, age
    except Exception:
        logger.debug("Cache miss or unreadable entry: %s", p, exc_info=True)
        return None


def store(source: str, key: str, payload: Any, params: Any = None) -> None:
    temporary = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Readers must see either the previous complete payload or the new one.
        with tempfile.NamedTemporaryFile(dir=CACHE_DIR, suffix=".tmp", delete=False) as fh:
            temporary = Path(fh.name)
            pickle.dump(
                _stamp(payload, dt.datetime.now(dt.timezone.utc)),
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        temporary.replace(_path(source, key, params))
    except Exception:
        logger.warning("Could not write cache entry for %s/%s", source, key, exc_info=True)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove temporary cache entry", exc_info=True)


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
        numeric = payload.select_dtypes("number") if isinstance(payload, pd.DataFrame) else payload
        if numeric.empty or not np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan)).any():
            raise EmptyPayload("source returned no finite numeric observations")
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
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Could not remove cache entry: %s", f, exc_info=True)
    return n
