"""Load only the dashboard's inputs, sharing overlapping source series."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import streamlit as st

from .contract import Series
from .sources import ecb, fred, market, mof, nyfed, treasury

EXTRAS = {
    "DFII10": "10y TIPS real yield",
    "T10YIE": "10y breakeven",
    "T5YIFR": "5y5y fwd inflation",
    "THREEFYTP10": "10y term premium (Kim-Wright)",
    "IORB": "Interest on reserve balances",
    "DGS10": "10y UST (long history)",
}
HEADLINE = {
    "BAMLC0A0CM": "US IG OAS",
    "BAMLH0A0HYM2": "US HY OAS",
    "BAMLEMCBPIOAS": "EM corporate OAS",
    "BAMLHE00EHYIOAS": "Euro HY OAS",
}
LADDER = {
    "BAMLC0A4CBBB": "BBB",
    "BAMLH0A1HYBB": "BB",
    "BAMLH0A3HYC": "CCC & lower",
}
CONDITIONS = {"NFCI": "Chicago Fed NFCI", "STLFSI4": "St. Louis Fed FSI"}
CP = {"RIFSPPNA2P2D90NB": "A2/P2 nonfinancial CP 90d", "DCPN3M": "AA nonfinancial CP 90d"}
MARKET = {
    "^MOVE": "MOVE",
    "^GSPC": "S&P 500",
    "HG=F": "Copper",
    "GC=F": "Gold",
    "DX-Y.NYB": "DXY",
    "JPY=X": "USDJPY",
}


@dataclass
class DashboardData:
    ust: Series
    jgb: Series
    sofr_fwd: Series
    ff: Series
    sofr_on: Series
    effr: Series
    extras: dict[str, Series]
    head: dict[str, Series]
    ladder: dict[str, Series]
    f: dict[str, Series]
    slow: dict[str, Series]
    mkt: dict[str, Series]
    plumbing: dict[str, Series]
    cp: dict[str, Series]
    eur: Series
    estr: Series

    @property
    def move(self) -> Series:
        return self.mkt["^MOVE"]

    @property
    def vix(self) -> Series:
        return self.f["VIXCLS"]

    @property
    def jpy(self) -> Series:
        return self.mkt["JPY=X"]


@st.cache_data(ttl=120, show_spinner=False)
def load_treasury(years: list[int]) -> Series:
    """Allow the landing page to show Treasuries before other providers finish."""
    return treasury.curve(years)


def _load_fred() -> dict[str, Series]:
    spec = {
        **EXTRAS,
        **HEADLINE,
        **LADDER,
        **CONDITIONS,
        **CP,
        "VIXCLS": "VIX",
        "RRPONTSYD": "ON RRP take-up ($bn)",
    }
    return {
        key: fred.get(key, label, cadence_days=7 if key in CONDITIONS else 1)
        for key, label in spec.items()
    }


def _load_market() -> tuple[Series, Series, dict[str, Series]]:
    # Keep Yahoo downloads together; the source batches each history request.
    sofr = market.futures_strip("SR3", 16, True, "SOFR futures forward path")
    ff = market.futures_strip("ZQ", 15, False, "Fed funds futures path")
    return sofr, ff, market.basket(MARKET, period="5y")


def _load_funding() -> tuple[Series, Series]:
    return nyfed.reference_rate("sofr"), nyfed.reference_rate("effr", "unsecured")


def _load_europe() -> tuple[Series, Series]:
    return ecb.curve(), ecb.estr()


@st.cache_data(ttl=120, show_spinner=False)
def load(years: list[int]) -> DashboardData:
    """Fetch independent providers concurrently, retaining their disk-cache fallback."""
    ust = load_treasury(years)
    with ThreadPoolExecutor(max_workers=4) as pool:
        fred_task = pool.submit(_load_fred)
        market_task = pool.submit(_load_market)
        japan_task = pool.submit(mof.curve)
        funding_task = pool.submit(_load_funding)
        europe_task = pool.submit(_load_europe)
        values = fred_task.result()
        sofr_fwd, ff, mkt = market_task.result()
        jgb = japan_task.result()
        sofr_on, effr = funding_task.result()
        eur, estr = europe_task.result()

    return DashboardData(
        ust=ust,
        jgb=jgb,
        sofr_fwd=sofr_fwd,
        ff=ff,
        sofr_on=sofr_on,
        effr=effr,
        extras={key: values[key] for key in EXTRAS},
        head={key: values[key] for key in HEADLINE},
        ladder={key: values[key] for key in LADDER},
        f={key: values[key] for key in ("BAMLH0A0HYM2", "VIXCLS")},
        slow={key: values[key] for key in CONDITIONS},
        mkt=mkt,
        plumbing={"RRPONTSYD": values["RRPONTSYD"]},
        cp={key: values[key] for key in CP},
        eur=eur,
        estr=estr,
    )
