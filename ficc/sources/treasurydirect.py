"""Treasury auction results from TreasuryDirect -- keyless JSON.

    https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json

The "who is absorbing duration" read: bid-to-cover, and how the competitive
award split between indirect bidders (foreign and domestic real money bidding
through dealers), direct bidders, and the primary dealers who must take up
whatever is left. Dealers absorbing an outsized share is the demand warning.

What is deliberately *not* here is the auction tail. A tail is stop-out yield
minus the 1pm when-issued yield, and the when-issued print is not public.
`highYield - averageMedianYield` is a different statistic and must never be
labelled a tail.

All fields arrive as strings; empty strings mean "not applicable" (bills have
no high yield, only a discount rate).
"""

from __future__ import annotations

import pandas as pd

from .. import cache, http
from ..contract import Series, failed, status_from

URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json"

COUPON_TYPES = ("Note", "Bond", "TIPS", "FRN")


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float("nan"), index=df.index)
    return pd.to_numeric(df[col].replace("", None), errors="coerce")


def parse(records: list[dict]) -> pd.DataFrame:
    """Normalise TreasuryDirect records into one row per coupon auction."""
    df = pd.DataFrame(records)
    need = {"auctionDate", "securityType", "securityTerm", "bidToCoverRatio"}
    if df.empty or not need <= set(df.columns):
        raise ValueError("unexpected TreasuryDirect payload")
    # Derive the instrument kind from flags rather than trusting one field:
    # TIPS and FRNs are flagged ("tips"/"floatingRate" == "Yes") on records
    # whose securityType may read plain Note or Bond.
    kind = df["securityType"].astype(str)
    for flag, name in (("tips", "TIPS"), ("floatingRate", "FRN")):
        if flag in df.columns:
            kind = kind.mask(df[flag].astype(str).eq("Yes"), name)
    df = df.assign(_kind=kind)
    df = df[df["_kind"].isin(COUPON_TYPES)]
    # Competitive accepted is the right denominator for bidder shares: the
    # total also includes non-competitive and SOMA add-ons, which dilute the
    # shares and are not bidding against anyone.
    base = _num(df, "competitiveAccepted")
    base = base.where(base > 0, _num(df, "totalAccepted"))
    out = pd.DataFrame({
        "date": pd.to_datetime(df["auctionDate"], errors="coerce"),
        "term": df["securityTerm"].astype(str),
        "type": df["_kind"],
        "reopening": df.get("reopening", pd.Series("", index=df.index)).astype(str).eq("Yes"),
        "high_yield": _num(df, "highYield"),
        "btc": _num(df, "bidToCoverRatio"),
        "indirect_pct": _num(df, "indirectBidderAccepted") / base * 100,
        "direct_pct": _num(df, "directBidderAccepted") / base * 100,
        "dealer_pct": _num(df, "primaryDealerAccepted") / base * 100,
        "size_bn": _num(df, "offeringAmount") / 1e9,
    })
    out = out.dropna(subset=["date", "btc"]).set_index("date").sort_index()
    return out


def auctions() -> Series:
    def pull() -> pd.DataFrame:
        return parse(http.get("treasurydirect", URL, timeout=40).json())

    try:
        frame, meta = cache.through("treasurydirect", "auctioned", cache.TTL_DAILY, pull)
    except Exception as e:
        return failed("auctions", "Treasury auctions", "TreasuryDirect", e)
    return Series(key="auctions", label="Treasury coupon auctions", frame=frame,
                  source="TreasuryDirect", cadence_days=14, status=status_from(meta))


def with_context(frame: pd.DataFrame, n_prior: int = 6) -> pd.DataFrame:
    """Add each auction's deviation from the average of its own prior auctions.

    A 2.4 bid-to-cover is strong for a 30y and weak for a 2y, so a raw number
    carries no verdict. The practitioner read is always against the same
    security's recent history -- that is what these columns provide.
    """
    f = frame.sort_index().copy()
    key = f["term"] + "|" + f["type"]
    for col in ("btc", "indirect_pct", "dealer_pct"):
        prior = (f.groupby(key)[col]
                 .transform(lambda s: s.shift(1).rolling(n_prior, min_periods=2).mean()))
        f[f"{col}_vs_avg"] = f[col] - prior
    return f
