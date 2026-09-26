"""European Central Bank Data Portal -- SDMX REST, no key, no registration.

    https://data-api.ecb.europa.eu/service/data/<FLOW>/<KEY>?format=csvdata

Two flows fill the euro-shaped hole in the Global block:

  * YC  -- the ECB's euro-area yield curve, fitted daily to AAA-rated central
           government bonds (in practice, Bunds and their peers). Used here
           as the free stand-in for a Bund curve.
  * EST -- euro short-term rate (EUR STR), the euro's overnight benchmark and the
           counterpart to SOFR.

One caveat travels with the curve everywhere it is shown: these are fitted
*spot* (zero-coupon) rates, whereas the UST and JGB lines are *par* yields.
Across most of the curve the two differ by a few basis points, which is fine
for a level-and-shape read and for a UST-EUR spread quoted to whole bp, but it
is not a like-for-like constant-maturity comparison.

ECB statistics may be reused free of charge provided the source is cited.
"""

from __future__ import annotations

import io

import pandas as pd

from .. import cache, http
from ..contract import Series, failed, status_from

API = "https://data-api.ecb.europa.eu/service/data"

# Tenor label -> years. The SDMX data-type code is "SR_" + label.
TENORS: dict[str, float] = {
    "3M": 0.25, "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7,
    "10Y": 10, "15Y": 15, "20Y": 20, "30Y": 30,
}
CURVE_KEY = "B.U2.EUR.4F.G_N_A.SV_C_YM."
ESTR_KEY = "B.EU000A2X2A25.WT"


def parse_csv(text: str, column_from: str | None = None) -> pd.DataFrame:
    """Parse an SDMX `csvdata` payload into a date-indexed frame.

    With `column_from`, pivot one column per distinct value of that SDMX
    dimension (e.g. DATA_TYPE_FM -> SR_10Y); otherwise return one `value`
    column.
    """
    df = pd.read_csv(io.StringIO(text))
    if not {"TIME_PERIOD", "OBS_VALUE"} <= set(df.columns):
        raise ValueError("unexpected ECB payload: no TIME_PERIOD/OBS_VALUE")
    df["date"] = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
    df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df = df.dropna(subset=["date", "OBS_VALUE"])
    if column_from:
        if column_from not in df.columns:
            # Fall back to the last segment of the series key, which carries
            # the same code, rather than failing on a cosmetic schema change.
            df[column_from] = df["KEY"].astype(str).str.split(".").str[-1]
        out = df.pivot_table(index="date", columns=column_from,
                             values="OBS_VALUE", aggfunc="last")
        out.columns = [str(c).removeprefix("SR_") for c in out.columns]
    else:
        out = df.set_index("date")[["OBS_VALUE"]].rename(columns={"OBS_VALUE": "value"})
    out.index.name = "date"
    return out.sort_index()


def _get(flow: str, key: str, start: str) -> str:
    return http.get("ecb", f"{API}/{flow}/{key}?format=csvdata&startPeriod={start}",
                    timeout=40).text


def _start(years: int) -> str:
    return f"{pd.Timestamp.today().year - years}-01-01"


def curve(years: int = 5) -> Series:
    """Euro-area AAA government spot curve, 3M-30Y, daily."""
    key = CURVE_KEY + "+".join(f"SR_{t}" for t in TENORS)

    def pull() -> pd.DataFrame:
        f = parse_csv(_get("YC", key, _start(years)), column_from="DATA_TYPE_FM")
        return f[[t for t in TENORS if t in f.columns]]

    try:
        frame, meta = cache.through("ecb", f"yc_{years}", cache.TTL_DAILY, pull)
    except Exception as e:
        return failed("ecb_yc", "EUR AAA curve", "ECB Data Portal", e)
    return Series(
        key="ecb_yc", label="EUR AAA govt spot curve", frame=frame,
        source="ECB Data Portal", unit="%", cadence_days=1,
        status=status_from(meta),
        note="Fitted zero-coupon (spot) rates on AAA euro-area sovereigns.",
    )


def estr(years: int = 3) -> Series:
    """Euro short-term rate, daily (published ~08:00 CET for the prior day)."""
    try:
        frame, meta = cache.through(
            "ecb", f"estr_{years}", cache.TTL_DAILY,
            lambda: parse_csv(_get("EST", ESTR_KEY, _start(years))))
    except Exception as e:
        return failed("estr", "EUR STR", "ECB Data Portal", e)
    return Series(key="estr", label="EUR STR", frame=frame, source="ECB Data Portal",
                  unit="%", cadence_days=1, status=status_from(meta))
