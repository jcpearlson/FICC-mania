"""CFTC Commitments of Traders via the public Socrata API -- no key.

    https://publicreporting.cftc.gov/resource/<dataset>.json

Uses the Traders in Financial Futures (TFF) report, which splits positions
into dealers, asset managers, leveraged funds and other reportables. Two reads
matter for this dashboard:

  * Leveraged-fund net in yen futures -- crowded short-JPY positioning is the
    fuel for the classic carry unwind (see BACKLOG: cheap yen vol plus a
    stretched USDJPY residual plus a crowded short).
  * Leveraged-fund net in 10y note futures -- the persistent large short is
    the futures leg of the cash-futures basis trade.

Rules that corrupt the series if ignored:

  * Socrata's default `$limit` is 1000 and silently truncates. Always set it.
  * Filter on the contract-market *code*, never on a loose name match: "YEN"
    or "GOLD" also match micro and look-alike contracts.
  * Normalise net positioning by open interest before comparing across time;
    open interest itself trends.

Released Fridays 15:30 ET for positions as of the prior Tuesday -- the as-of
date on every tile is therefore the Tuesday, three days before publication.
"""

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
    need = {"report_date_as_yyyy_mm_dd", "open_interest_all",
            "lev_money_positions_long", "lev_money_positions_short"}
    if df.empty or not need <= set(df.columns):
        raise ValueError("unexpected CFTC payload")
    num = lambda c: pd.to_numeric(df.get(c), errors="coerce")  # noqa: E731
    oi = num("open_interest_all")
    out = pd.DataFrame({
        "date": pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce"),
        "open_interest": oi,
        "lev_net": num("lev_money_positions_long") - num("lev_money_positions_short"),
        "am_net": (num("asset_mgr_positions_long") - num("asset_mgr_positions_short")
                   if "asset_mgr_positions_long" in df.columns else float("nan")),
    })
    out["lev_net_pct_oi"] = out["lev_net"] / oi * 100
    out["am_net_pct_oi"] = out["am_net"] / oi * 100
    out = out.dropna(subset=["date"]).set_index("date").sort_index()
    return out[~out.index.duplicated(keep="last")]


def positioning(code: str, weeks: int = 260) -> Series:
    label = CONTRACTS.get(code, code)

    def pull() -> pd.DataFrame:
        r = http.get("cftc", URL, timeout=40, params={
            "cftc_contract_market_code": code,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(weeks),
        })
        return parse(r.json())

    try:
        frame, meta = cache.through("cftc", f"tff_{code}_{weeks}", cache.TTL_WEEKLY, pull)
    except Exception as e:
        return failed(f"cot_{code}", label, "CFTC COT", e)
    return Series(key=f"cot_{code}", label=label, frame=frame, source="CFTC COT (TFF)",
                  # 8, not 7: the as-of Tuesday is already three days old on
                  # release day, so a weekly cadence would badge a current
                  # report amber every Friday morning.
                  cadence_days=8, status=status_from(meta),
                  note="Positions as of Tuesday; published the following Friday.")
