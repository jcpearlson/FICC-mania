"""Per-source HTTP configuration.

Sources disagree about what a well-behaved client looks like, and getting this
wrong looks exactly like an outage. Two verified facts drive this module:

  * FRED  returns a connection error if you send a browser User-Agent.
  * treasury.gov  times out if you *don't*.

So headers are per-source, never global. Each source also gets its own
`requests.Session` (connection reuse) and a minimum interval between calls --
concurrent hammering of FRED reproducibly yields empty responses.

Overriding headers
------------------
If a source starts refusing us, copy the request headers out of Chrome's
Network tab and drop them into `headers.local.json` at the repo root:

    { "cme": { "User-Agent": "...", "Cookie": "...", "Accept": "..." } }

Those are merged over the defaults below at import time. The file is
gitignored, since pasted headers usually carry session cookies.
"""

from __future__ import annotations

import json
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

_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "headers.local.json"
if _OVERRIDES_PATH.exists():
    try:
        for _src, _hdrs in json.loads(_OVERRIDES_PATH.read_text()).items():
            _base, _gap = _PROFILES.get(_src, _PROFILES["default"])
            _PROFILES[_src] = ({**_base, **_hdrs}, _gap)
    except Exception:  # a malformed override must not break startup
        pass

_sessions: dict[str, requests.Session] = {}
_last_call: dict[str, float] = {}
_lock = threading.Lock()


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
    with _lock:
        wait = gap - (time.monotonic() - _last_call.get(source, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[source] = time.monotonic()


def get(source: str, url: str, *, timeout: int = 25, retries: int = 1,
        backoff: float = 2.0, **kw) -> requests.Response:
    """GET with the right headers, polite spacing, and one retry on transients.

    The retry is deliberately small: the on-disk cache already serves the last
    good payload when a source is down, so hammering a struggling endpoint buys
    nothing. One backed-off retry absorbs the common blip (a dropped
    connection, a 503 during a publish) without turning an outage into a storm.
    """
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
        time.sleep(backoff * (attempt + 1))
    raise RuntimeError("unreachable")  # pragma: no cover
