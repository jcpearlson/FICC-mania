"""Provider-specific HTTP sessions, headers, request spacing and transient retries.

Optional headers.local.json profiles override defaults. Keep this file private;
browser headers can contain session cookies. FRED uses a non-browser profile,
while Treasury requests use a browser User-Agent."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import requests

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# source key -> (headers, min seconds between requests)
_PROFILES: dict[str, tuple[dict[str, str], float]] = {
    # FRED actively rejects browser UAs. Send nothing but Accept.
    "fred": ({"Accept": "text/csv,*/*"}, 0.35),
    # treasury.gov requires a browser UA or it hangs until timeout.
    "treasury": ({"User-Agent": CHROME_UA, "Accept": "text/csv,*/*"}, 0.35),
    "nyfed": ({"Accept": "application/json"}, 0.2),
    "mof": ({"User-Agent": CHROME_UA, "Accept": "text/csv,*/*"}, 0.5),
    "cftc": ({"User-Agent": CHROME_UA}, 1.0),
    # ECB Data Portal (SDMX REST) and TreasuryDirect are plain public APIs;
    # neither needs a browser disguise, but both are asked to be spared bursts.
    "ecb": ({"Accept": "text/csv,*/*"}, 0.5),
    "treasurydirect": ({"User-Agent": CHROME_UA, "Accept": "application/json"}, 0.5),
    "default": ({"User-Agent": CHROME_UA}, 0.25),
}

logger = logging.getLogger(__name__)


def _load_overrides(path: Path) -> None:
    try:
        overrides = json.loads(path.read_text())
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        logger.warning("Could not read HTTP header overrides")
        return
    if not isinstance(overrides, dict):
        logger.warning("HTTP header overrides must be an object")
        return
    for source, headers in overrides.items():
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            logger.warning("Ignoring invalid HTTP header profile")
            continue
        base, gap = _PROFILES.get(source, _PROFILES["default"])
        _PROFILES[source] = ({**base, **headers}, gap)


_load_overrides(Path(__file__).resolve().parent.parent / "headers.local.json")

_sessions: dict[str, requests.Session] = {}
_last_call: dict[str, float] = {}
_lock = threading.Lock()
_source_locks: dict[str, threading.RLock] = {}


def _profile(source: str) -> tuple[dict[str, str], float]:
    return _PROFILES.get(source, _PROFILES["default"])


def session(source: str) -> requests.Session:
    with _lock:
        if source not in _sessions:
            s = requests.Session()
            s.headers.clear()
            s.headers.update(_profile(source)[0])
            _sessions[source] = s
        return _sessions[source]


# Transient failures worth one more try. A 4xx other than 429 is a real
# answer (bad series id, moved endpoint) and retrying it only adds load.
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _wait_turn(source: str) -> None:
    gap = _profile(source)[1]
    previous = _last_call.get(source)
    wait = gap - (time.monotonic() - previous) if previous is not None else 0
    if wait > 0:
        time.sleep(wait)
    _last_call[source] = time.monotonic()


def get(
    source: str, url: str, *, timeout: int = 25, retries: int = 1, backoff: float = 2.0, **kw
) -> requests.Response:
    """GET with the right headers, polite spacing, and one retry on transients.

    The retry is deliberately small: the on-disk cache already serves the last
    good payload when a source is down, so hammering a struggling endpoint buys
    nothing. One backed-off retry absorbs the common blip (a dropped
    connection, a 503 during a publish) without turning an outage into a storm.
    """
    if retries < 0 or backoff < 0:
        raise ValueError("retries and backoff must be non-negative")
    with _lock:
        source_lock = _source_locks.setdefault(source, threading.RLock())
    # Sessions are shared across Streamlit users. Serialize requests to the
    # same provider without blocking unrelated providers during throttling.
    with source_lock:
        for attempt in range(retries + 1):
            _wait_turn(source)
            try:
                r = session(source).get(url, timeout=timeout, **kw)
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= retries:
                    raise
            else:
                if r.status_code not in _RETRY_STATUS or attempt >= retries:
                    r.raise_for_status()
                    return r
                r.close()
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError("unreachable")  # pragma: no cover
