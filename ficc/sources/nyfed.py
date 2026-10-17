"""NY Fed reference rates and backward-looking compounded SOFR averages.

Forward rates come from futures in market.py, not from these averages."""

from __future__ import annotations

import pandas as pd

from .. import cache, http
from ..contract import Series, failed, status_from

API = "https://markets.newyorkfed.org/api"


def _json(path: str):
    return http.get("nyfed", f"{API}/{path}").json()


def reference_rate(rate: str = "sofr", kind: str = "secured", n: int = 750) -> Series:
    """Daily history for one reference rate (sofr, effr, obfr, tgcr, bgcr)."""
    key = f"{kind}_{rate}_{n}"

    def pull() -> pd.DataFrame:
        data = _json(f"rates/{kind}/{rate}/last/{n}.json")["refRates"]
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["effectiveDate"])
        keep = [
            c
            for c in [
                "percentRate",
                "percentPercentile1",
                "percentPercentile25",
                "percentPercentile75",
                "percentPercentile99",
                "volumeInBillions",
            ]
            if c in df.columns
        ]
        if "percentRate" not in keep:
            raise ValueError("unexpected NY Fed payload: no percentRate")
        return (
            df.set_index("date")[keep]
            .sort_index()
            .apply(pd.to_numeric, errors="coerce")
            .dropna(subset=["percentRate"])
        )

    try:
        frame, meta = cache.through("nyfed", key, cache.TTL_DAILY, pull)
    except Exception as e:
        return failed(rate, rate.upper(), "NY Fed", e)
    return Series(
        key=rate,
        label=rate.upper(),
        frame=frame,
        source="NY Fed markets API",
        status=status_from(meta),
        unit="%",
        cadence_days=1,
    )


def sofr_averages(n: int = 750) -> Series:
    """30/90/180-day compounded SOFR averages -- backward-looking, by construction."""

    def pull() -> pd.DataFrame:
        data = _json(f"rates/secured/sofrai/last/{n}.json")["refRates"]
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["effectiveDate"])
        keep = [c for c in ["average30day", "average90day", "average180day"] if c in df.columns]
        return df.set_index("date")[keep].sort_index().apply(pd.to_numeric, errors="coerce")

    try:
        frame, meta = cache.through("nyfed", f"sofrai_{n}", cache.TTL_DAILY, pull)
    except Exception as e:
        return failed("sofrai", "SOFR averages", "NY Fed", e)
    return Series(
        key="sofrai",
        label="SOFR compounded averages",
        frame=frame,
        source="NY Fed markets API",
        status=status_from(meta),
        unit="%",
        cadence_days=1,
        note="Backward-looking compounded averages, not forward rates.",
    )
