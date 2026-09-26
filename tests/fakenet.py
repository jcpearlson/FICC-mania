"""A fake network that answers every source in its real wire format.

The app is built on a dozen public endpoints, none reachable from CI. This
module stands in for them -- `http.get` and `yfinance.download` -- with
deterministic synthetic data shaped exactly like each source's payload, so the
parsers, the analytics and every panel's render path run end to end offline.

Values are random walks around plausible levels; nothing here is market data.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

TODAY = pd.Timestamp.today().normalize()


def _bdays(years: float) -> pd.DatetimeIndex:
    return pd.bdate_range(end=TODAY - pd.Timedelta(days=1), periods=int(252 * years))


def _walk(n: int, level: float, step: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level + np.cumsum(rng.normal(0, step, n))


def _seed(s: str) -> int:
    return sum(map(ord, s)) % 10_000


# FRED series id -> (level, daily step, cadence: D / W / Q)
FRED = {
    "BAMLH0A0HYM2": (3.0, 0.03, "D"), "BAMLC0A0CM": (0.9, 0.01, "D"),
    "BAMLEMCBPIOAS": (1.9, 0.02, "D"), "BAMLHE00EHYIOAS": (3.2, 0.03, "D"),
    "BAMLC0A1CAAA": (0.4, 0.005, "D"), "BAMLC0A2CAA": (0.55, 0.005, "D"),
    "BAMLC0A3CA": (0.75, 0.008, "D"), "BAMLC0A4CBBB": (1.1, 0.01, "D"),
    "BAMLH0A1HYBB": (1.9, 0.02, "D"), "BAMLH0A2HYB": (3.0, 0.03, "D"),
    "BAMLH0A3HYC": (8.0, 0.08, "D"), "BAMLC0A0CMEY": (5.1, 0.03, "D"),
    "BAMLH0A0HYM2EY": (7.2, 0.04, "D"), "VIXCLS": (16, 0.6, "D"),
    "T10Y2Y": (0.5, 0.03, "D"), "DGS10": (4.2, 0.05, "D"), "DFII10": (1.9, 0.04, "D"),
    "T10YIE": (2.3, 0.02, "D"), "T5YIFR": (2.2, 0.02, "D"),
    "THREEFYTP10": (0.6, 0.03, "D"), "IORB": (4.4, 0.0, "D"),
    "RRPONTSYD": (150, 8, "D"), "RIFSPPNA2P2D90NB": (4.5, 0.02, "D"),
    "DCPN3M": (4.2, 0.02, "D"),
    "NFCI": (-0.5, 0.02, "W"), "STLFSI4": (-0.6, 0.05, "W"),
    "WALCL": (6_700_000, 5000, "W"), "WTREGEN": (800, 20, "W"),
    "WRESBAL": (3200, 30, "W"), "TOTCI": (2800, 5, "W"),
    "DRTSCILM": (5, 4, "Q"), "DRBLACBS": (1.3, 0.05, "Q"), "CORBLACBS": (0.6, 0.05, "Q"),
}

TSY_TENORS = ["1 Mo", "1.5 Month", "2 Mo", "3 Mo", "4 Mo", "6 Mo", "1 Yr", "2 Yr",
              "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]
TSY_LEVEL = [4.3, 4.3, 4.28, 4.25, 4.2, 4.1, 3.95, 3.8, 3.8, 3.85, 3.95, 4.15, 4.6, 4.7]


class FakeResponse:
    def __init__(self, text: str = "", payload=None, status: int = 200):
        self.text = text if payload is None else json.dumps(payload)
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fred_csv(sid: str) -> str:
    level, step, cad = FRED.get(sid, (1.0, 0.01, "D"))
    if cad == "D":
        idx = pd.bdate_range(end=TODAY - pd.Timedelta(days=1), periods=252 * 3)
    elif cad == "W":
        idx = pd.date_range(end=TODAY - pd.Timedelta(days=2), periods=52 * 6, freq="W-WED")
    else:
        idx = pd.date_range(end=TODAY - pd.Timedelta(days=60), periods=60, freq="QS")
    v = _walk(len(idx), level, step, _seed(sid))
    rows = [f"{d:%Y-%m-%d},{x:.4f}" for d, x in zip(idx, v)]
    rows[len(rows) // 2] = rows[len(rows) // 2].split(",")[0] + ",."   # FRED's missing marker
    if sid == "IORB":   # forward-dated administered rate, as FRED publishes it
        rows.append(f"{TODAY + pd.Timedelta(days=2):%Y-%m-%d},4.1500")
    return "observation_date," + sid + "\n" + "\n".join(rows) + "\n"


def treasury_csv(year: int, kind: str) -> str:
    idx = [d for d in _bdays(3) if d.year == year]
    if kind == "daily_treasury_real_yield_curve":
        cols, lv = ["5 YR", "7 YR", "10 YR", "20 YR", "30 YR"], [1.5, 1.7, 1.9, 2.2, 2.3]
    else:
        cols, lv = TSY_TENORS, TSY_LEVEL
    common = _walk(len(idx), 0, 0.04, year)
    lines = ["Date," + ",".join(f'"{c}"' for c in cols)]
    for i, d in enumerate(reversed(idx)):         # treasury.gov is newest-first
        j = len(idx) - 1 - i
        lines.append(f"{d:%m/%d/%Y}," + ",".join(f"{x + common[j]:.2f}" for x in lv))
    return "\n".join(lines) + "\n"


def mof_csv() -> str:
    idx = _bdays(3)
    tenors = ["1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y",
              "15Y", "20Y", "25Y", "30Y", "40Y"]
    base = _walk(len(idx), 0, 0.02, 7)
    lines = ["Interest Rate,(Unit : %)", "Date," + ",".join(tenors)]
    for k, d in enumerate(idx):
        lines.append(f"{d:%Y/%m/%d}," + ",".join(
            f"{0.5 + 0.08 * i + base[k]:.3f}" for i in range(len(tenors))))
    return "\n".join(lines) + "\n"


def nyfed_json(path: str) -> dict:
    idx = _bdays(3)
    if "sofrai" in path:
        return {"refRates": [{"effectiveDate": f"{d:%Y-%m-%d}", "average30day": 4.3,
                              "average90day": 4.32, "average180day": 4.35} for d in idx]}
    base = 4.33 if "sofr" in path else 4.33
    v = base + _walk(len(idx), 0, 0.005, _seed(path))
    return {"refRates": [{
        "effectiveDate": f"{d:%Y-%m-%d}", "percentRate": round(x, 2),
        "percentPercentile1": round(x - 0.05, 2), "percentPercentile25": round(x - 0.01, 2),
        "percentPercentile75": round(x + 0.01, 2), "percentPercentile99": round(x + 0.08, 2),
        "volumeInBillions": 2400} for d, x in zip(idx, v)]}


def ecb_csv(url: str) -> str:
    idx = _bdays(3)
    head = "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE"
    lines = [head]
    if "/EST/" in url:
        for d, x in zip(idx, _walk(len(idx), 1.92, 0.003, 3)):
            lines.append(f"EST.B.EU000A2X2A25.WT,B,,,,,,,{d:%Y-%m-%d},{x:.3f}")
        return "\n".join(lines) + "\n"
    key = urlparse(url).path.split("/")[-1]
    codes = key.split(".")[-1].split("+")
    for i, code in enumerate(codes):
        for d, x in zip(idx, _walk(len(idx), 1.9 + 0.1 * i, 0.03, i)):
            lines.append(f"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.{code},B,U2,EUR,4F,G_N_A,SV_C_YM,"
                         f"{code},{d:%Y-%m-%d},{x:.4f}")
    return "\n".join(lines) + "\n"


def treasurydirect_json() -> list[dict]:
    out = []
    terms = [("2-Year", "Note"), ("10-Year", "Note"), ("30-Year", "Bond"),
             ("5-Year", "Note"), ("4-Week", "Bill")]
    for k in range(30):
        term, st = terms[k % len(terms)]
        d = TODAY - pd.Timedelta(days=7 * k + 1)
        comp = 60e9
        out.append({
            "auctionDate": f"{d:%Y-%m-%dT00:00:00}", "securityType": st,
            "securityTerm": term, "type": st, "reopening": "No", "tips": "No",
            "floatingRate": "No", "highYield": "" if st == "Bill" else f"{4 + k * 0.01:.3f}",
            "bidToCoverRatio": f"{2.4 + (k % 4) * 0.05:.2f}",
            "competitiveAccepted": f"{comp:.0f}", "totalAccepted": f"{comp * 1.05:.0f}",
            "indirectBidderAccepted": f"{comp * 0.68:.0f}",
            "directBidderAccepted": f"{comp * 0.18:.0f}",
            "primaryDealerAccepted": f"{comp * 0.14:.0f}", "offeringAmount": f"{comp:.0f}",
        })
    return out


def cftc_json(params: dict) -> list[dict]:
    code = params.get("cftc_contract_market_code", "0")
    n = int(params.get("$limit", 100))
    idx = pd.date_range(end=TODAY - pd.Timedelta(days=3), periods=n, freq="W-TUE")[::-1]
    v = _walk(n, -20_000, 4000, _seed(code))
    return [{"report_date_as_yyyy_mm_dd": f"{d:%Y-%m-%dT00:00:00.000}",
             "cftc_contract_market_code": code, "open_interest_all": "200000",
             "lev_money_positions_long": f"{40_000:.0f}",
             "lev_money_positions_short": f"{40_000 - x:.0f}",
             "asset_mgr_positions_long": "50000", "asset_mgr_positions_short": "30000"}
            for d, x in zip(idx, v)]


def fake_get(source: str, url: str, **kw) -> FakeResponse:
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if source == "fred":
        return FakeResponse(fred_csv(q["id"]))
    if source == "treasury":
        return FakeResponse(treasury_csv(int(q["field_tdr_date_value"]), q["type"]))
    if source == "mof":
        return FakeResponse(mof_csv())
    if source == "nyfed":
        return FakeResponse(payload=nyfed_json(u.path))
    if source == "ecb":
        return FakeResponse(ecb_csv(url))
    if source == "treasurydirect":
        return FakeResponse(payload=treasurydirect_json())
    if source == "cftc":
        return FakeResponse(payload=cftc_json({**q, **kw.get("params", {})}))
    raise RuntimeError(f"no fake for {source} {url}")


def _yf_level(sym: str) -> float:
    if re.match(r"^(SR3|ZQ)", sym):
        return 95.8
    return {"JPY=X": 150, "DX-Y.NYB": 100, "^MOVE": 95, "^GSPC": 5500, "GC=F": 2400,
            "HG=F": 4.3, "SI=F": 29}.get(sym, 60.0)


def fake_download(tickers, period="1y", **kw) -> pd.DataFrame:
    syms = [tickers] if isinstance(tickers, str) else list(tickers)
    years = {"5d": 0.03, "10d": 0.05, "1y": 1, "2y": 2, "3y": 3, "5y": 5}.get(period, 2)
    idx = _bdays(years)
    close = {}
    for s in syms:
        lvl = _yf_level(s)
        step = 0.01 if lvl == 95.8 else lvl * 0.01
        m = re.search(r"[FGHJKMNQUVXZ](\d\d)\.", s)
        if lvl == 95.8 and m:   # a gently rising futures strip
            lvl += (int(m.group(1)) - TODAY.year % 100) * 0.1 + (_seed(s) % 7) * 0.01
            step = 0.002
        close[s] = np.abs(_walk(len(idx), lvl, step, _seed(s))) + 0.01
    closes = pd.DataFrame(close, index=idx)
    vol = pd.DataFrame(10_000, index=idx, columns=syms)
    return pd.concat({"Close": closes, "Volume": vol}, axis=1)
