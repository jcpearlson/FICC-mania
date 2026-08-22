"""Japanese Government Bond yield curve from the Ministry of Finance.

MOF publishes two files. The Japanese-language `jgbcm.csv` is Shift-JIS encoded
with Reiwa-era dates ("R8.8.3" = 2026-08-03), which is a decoding tax for no
benefit. The English mirror is plain ASCII with ISO-ish dates, so we use that:

    .../interest_rate/jgbcme.csv                  current fiscal year
    .../interest_rate/historical/jgbcme_all.csv   full history back to 1974

We stitch both: the `_all` file lags by a few weeks, the current-year file
carries the last few sessions. History matters here because the JGB z-scores
and the "where is 10y vs the old YCC band" read are the whole point.
"""

from __future__ import annotations

import io

import pandas as pd

from .. import cache, http
from ..contract import Series, Status, failed

BASE = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate"
CURRENT = f"{BASE}/jgbcme.csv"
HISTORY = f"{BASE}/historical/jgbcme_all.csv"

TENORS = {"1Y": 1, "2Y": 2, "3Y": 3, "4Y": 4, "5Y": 5, "6Y": 6, "7Y": 7,
          "8Y": 8, "9Y": 9, "10Y": 10, "15Y": 15, "20Y": 20, "25Y": 25,
          "30Y": 30, "40Y": 40}


def _parse(text: str) -> pd.DataFrame:
    # Row 0 is a "(Unit : %)" banner; the real header is row 1.
    df = pd.read_csv(io.StringIO(text), skiprows=1)
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"], format="%Y/%m/%d", errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df[[c for c in df.columns if c in TENORS]]


def _download(url: str) -> pd.DataFrame:
    return _parse(http.get("mof", url, timeout=60).text)


def curve(with_history: bool = True) -> Series:
    frames, metas = [], []
    targets = [("jgbcme_current", CURRENT, cache.TTL_DAILY)]
    if with_history:
        targets.append(("jgbcme_all", HISTORY, cache.TTL_HEAVY))
    for key, url, ttl in targets:
        try:
            f, m = cache.through("mof", key, ttl, lambda u=url: _download(u))
            frames.append(f)
            metas.append(m)
        except Exception:
            continue
    if not frames:
        return failed("jgb", "JGB curve", "MOF Japan", "no MOF file reachable")
    frame = pd.concat(frames).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return Series(
        key="jgb", label="JGB par curve", frame=frame,
        source="MOF Japan", unit="%", cadence_days=1,
        status=Status.STALE if any(str(m).startswith("stale") for m in metas) else Status.OK,
    )
