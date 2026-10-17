"""CFTC Traders in Financial Futures positions from the public Socrata API.

Filter by contract code, set an explicit row limit, and normalize positions
by positive open interest. Reports describe Tuesday positions released Friday."""

from __future__ import annotations

import pandas as pd

from .. import cache, http
from ..contract import Series, failed, status_from

# TFF futures-and-options combined.
URL = "https://publicreporting.cftc.gov/resource/yw9f-hn96.json"

CONTRACTS = {
    "097741": "JPY futures",
    "099741": "EUR futures",
    "043602": "10y note futures",
}


def parse(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    need = {
        "report_date_as_yyyy_mm_dd",
        "open_interest_all",
        "lev_money_positions_long",
        "lev_money_positions_short",
    }
    if df.empty or not need <= set(df.columns):
        raise ValueError("unexpected CFTC payload")

    def num(column: str) -> pd.Series:
        return pd.to_numeric(
            df.get(column, pd.Series(float("nan"), index=df.index)), errors="coerce"
        )

    oi = num("open_interest_all").where(lambda values: values > 0)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce"),
            "open_interest": oi,
            "lev_net": num("lev_money_positions_long") - num("lev_money_positions_short"),
            "am_net": num("asset_mgr_positions_long") - num("asset_mgr_positions_short"),
        }
    )
    out["lev_net_pct_oi"] = out["lev_net"] / oi * 100
    out["am_net_pct_oi"] = out["am_net"] / oi * 100
    out = out.dropna(subset=["date", "lev_net_pct_oi"]).set_index("date").sort_index()
    return out[~out.index.duplicated(keep="last")]


def positioning(code: str, weeks: int = 260) -> Series:
    label = CONTRACTS.get(code, code)

    def pull() -> pd.DataFrame:
        r = http.get(
            "cftc",
            URL,
            timeout=40,
            params={
                "cftc_contract_market_code": code,
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": str(weeks),
            },
        )
        return parse(r.json())

    try:
        frame, meta = cache.through("cftc", f"tff_{code}_{weeks}", cache.TTL_WEEKLY, pull)
    except Exception as e:
        return failed(f"cot_{code}", label, "CFTC COT", e)
    return Series(
        key=f"cot_{code}",
        label=label,
        frame=frame,
        source="CFTC COT (TFF)",
        # 8, not 7: the as-of Tuesday is already three days old on
        # release day, so a weekly cadence would badge a current
        # report amber every Friday morning.
        cadence_days=8,
        status=status_from(meta),
        note="Positions as of Tuesday; published the following Friday.",
    )
