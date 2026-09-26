"""US Treasury daily yield curve, straight from home.treasury.gov.

Published same day (~15:30 ET), which makes it fresher than FRED's mirror of
the same numbers. Requires a browser User-Agent or the request hangs.

Also serves the daily *real* (TIPS) curve and the daily par yield curve for
prior years, which is what the history-dependent z-scores need.
"""

from __future__ import annotations

import io

import pandas as pd

from .. import cache, http
from ..contract import Series, failed, worst_status

BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"

NOMINAL = "daily_treasury_yield_curve"
REAL = "daily_treasury_real_yield_curve"
BILL = "daily_treasury_bill_rates"

# Canonical tenor ordering and their maturity in years, for curve plotting.
TENORS: dict[str, float] = {
    "1 Mo": 1 / 12, "1.5 Month": 0.125, "2 Mo": 2 / 12, "3 Mo": 0.25,
    "4 Mo": 4 / 12, "6 Mo": 0.5, "1 Yr": 1, "2 Yr": 2, "3 Yr": 3,
    "5 Yr": 5, "7 Yr": 7, "10 Yr": 10, "20 Yr": 20, "30 Yr": 30,
}


def _download(year: int, kind: str) -> pd.DataFrame:
    url = (
        f"{BASE}/{year}/all?type={kind}"
        f"&field_tdr_date_value={year}&page&_format=csv"
    )
    r = http.get("treasury", url)
    df = pd.read_csv(io.StringIO(r.text))
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
    df.index.name = "date"
    return df.apply(pd.to_numeric, errors="coerce")


def curve(years: list[int], kind: str = NOMINAL, label: str = "UST par curve") -> Series:
    """Concatenated daily curve history across `years`."""
    frames, metas = [], []
    for y in years:
        try:
            f, m = cache.through("treasury", f"{kind}_{y}", cache.TTL_DAILY,
                                 lambda y=y: _download(y, kind))
            frames.append(f)
            metas.append(m)
        except Exception:
            continue
    if not frames:
        return failed("ust_curve", label, "US Treasury", "all years failed")
    frame = pd.concat(frames).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    status = worst_status(metas)
    return Series(
        key=f"ust_{kind}",
        label=label,
        frame=frame,
        source="US Treasury (home.treasury.gov)",
        status=status,
        unit="%",
        cadence_days=1,
    )
