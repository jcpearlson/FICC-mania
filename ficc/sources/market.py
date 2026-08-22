"""Live-ish market data via yfinance.

Raw HTTP to Yahoo returns 429 from this network; the yfinance client negotiates
the cookie/crumb handshake and succeeds, so we go through the library rather
than rolling our own requests. stooq -- the obvious alternative -- now sits
behind a JavaScript proof-of-work wall and is not usable from a script.

This adapter covers commodities, FX, credit/rates ETFs, vol indices, and the
rate futures strips that give us a forward curve.
"""

from __future__ import annotations

import warnings

import pandas as pd

from .. import cache
from ..contract import Series, Status, failed

warnings.filterwarnings("ignore", module="yfinance")

# CME month codes. SOFR 3M futures trade quarterly (IMM); fed funds are monthly.
MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
               7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
IMM_MONTHS = (3, 6, 9, 12)


def _yf():
    import yfinance as yf
    return yf


def history(symbols: list[str], period: str = "2y", interval: str = "1d",
            total_return: bool = False) -> pd.DataFrame:
    """Close-price frame for a basket of Yahoo symbols.

    `total_return=True` uses Yahoo's adjusted close, which folds distributions
    back in. This is essential for income instruments: a JAAA line built from
    raw close drifts down several percent a year on distributions alone, and a
    drawdown computed off it treats every ex-dividend date as stress. Futures
    and FX are unaffected either way, so raw close stays the default.
    """
    def pull() -> pd.DataFrame:
        yf = _yf()
        raw = yf.download(symbols, period=period, interval=interval,
                          progress=False, auto_adjust=total_return, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if not isinstance(raw.columns, pd.MultiIndex):
            close.columns = symbols[:1]
        return close.dropna(how="all")

    ttl = cache.TTL_INTRADAY if interval != "1d" else cache.TTL_DAILY
    frame, meta = cache.through(
        "yahoo",
        f"hist_{'_'.join(sorted(symbols))}_{period}_{interval}_{int(total_return)}",
        ttl, pull)
    frame.attrs["meta"] = meta
    return frame


def quote(symbol: str, label: str, *, unit: str = "", period: str = "1y",
          total_return: bool = False) -> Series:
    """Single instrument with history, wrapped in the standard contract."""
    try:
        frame = history([symbol], period=period, total_return=total_return)
    except Exception as e:
        return failed(symbol, label, "Yahoo Finance", e)
    if symbol not in frame.columns or frame[symbol].dropna().empty:
        return failed(symbol, label, "Yahoo Finance", "no data returned")
    out = frame[[symbol]].dropna()
    meta = frame.attrs.get("meta", "live")
    return Series(
        key=symbol, label=label, frame=out, source="Yahoo Finance",
        unit=unit, cadence_days=1,
        status=Status.STALE if str(meta).startswith("stale") else Status.OK,
    )


def basket(spec: dict[str, str], period: str = "2y",
           total_return: bool = False) -> dict[str, Series]:
    """Fetch many symbols in one Yahoo round trip, then split into Series.

    One batched download beats N sequential ones by a wide margin, and Yahoo is
    far happier about it.
    """
    symbols = list(spec)
    try:
        frame = history(symbols, period=period, total_return=total_return)
    except Exception as e:
        return {s: failed(s, lbl, "Yahoo Finance", e) for s, lbl in spec.items()}
    meta = frame.attrs.get("meta", "live")
    status = Status.STALE if str(meta).startswith("stale") else Status.OK
    out: dict[str, Series] = {}
    for sym, label in spec.items():
        if sym in frame.columns and frame[sym].notna().any():
            out[sym] = Series(key=sym, label=label, frame=frame[[sym]].dropna(),
                              source="Yahoo Finance", cadence_days=1, status=status)
        else:
            out[sym] = failed(sym, label, "Yahoo Finance", "symbol returned no data")
    return out


# -- rate futures strips -------------------------------------------------

def strip_symbols(root: str, n: int, quarterly: bool,
                  start: pd.Timestamp | None = None) -> list[tuple[str, pd.Timestamp, float]]:
    """Generate the next `n` listed contracts.

    Returns (symbol, contract_month, years_forward_to_reference_midpoint).

    That third element matters and is easy to get wrong. An SR3 contract does
    not describe a rate *at* its contract month -- it settles on compounded
    SOFR over the three months *following* the IMM date, so the rate it
    describes is centred about 1.5 months later. Plotting it at the contract
    month pushes the whole strip left and makes the front point land beside the
    3m bill while describing a different period. ZQ averages over its own
    contract month, so its midpoint is mid-month.

    The current month is skipped: for ZQ it is already part-realised, which
    would otherwise manufacture a phantom gap against spot EFFR.
    """
    today = start or pd.Timestamp.today()
    suffix = ".CME" if root.startswith("SR") else ".CBT"
    # Reference period runs 3 months from IMM for SR3, 1 month for ZQ.
    half_span = 1.5 if quarterly else 0.5
    out: list[tuple[str, pd.Timestamp, float]] = []
    y, m = today.year, today.month
    m += 1                      # skip the current, part-realised month
    if m > 12:
        m, y = 1, y + 1
    while len(out) < n:
        if not quarterly or m in IMM_MONTHS:
            cm = pd.Timestamp(year=y, month=m, day=1)
            mid = cm + pd.Timedelta(days=int(round(half_span * 30.44)))
            yrs = max((mid - today).days / 365.25, 0.01)
            out.append((f"{root}{MONTH_CODES[m]}{str(y)[-2:]}{suffix}", cm, yrs))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def futures_strip(root: str = "SR3", n: int = 12, quarterly: bool = True,
                  label: str = "SOFR futures strip", min_volume: int = 250) -> Series:
    """Forward rate curve implied by a futures strip: rate = 100 - price.

    SR3 (3-month SOFR) gives a genuine forward SOFR curve -- the thing NY Fed's
    published averages cannot provide, since those look backward. ZQ (30-day
    fed funds) gives the policy path.

    Deferred contracts go illiquid fast, and a stale print there flows straight
    into the headline "bp priced by" figure: the far ZQ contracts trade tens of
    lots against six figures at the front, and one of them printing off-market
    puts a visible kink in the path. So contracts are screened on 10-day average
    volume, and the strip is truncated at the first contract that fails -- never
    filtered in the middle, which would leave a misleading gap.
    """
    pairs = strip_symbols(root, n, quarterly)
    spec = {s: s for s, _, _ in pairs}

    def pull() -> pd.DataFrame:
        yf = _yf()
        raw = yf.download(list(spec), period="10d", progress=False,
                          auto_adjust=False, threads=True)
        rows = []
        for sym, expiry, yrs in pairs:
            try:
                close = raw["Close"][sym].dropna()
            except Exception:
                continue
            if close.empty:
                continue
            try:
                vol = raw["Volume"][sym].dropna()
            except Exception:
                vol = None
            # A missing volume series is not evidence of illiquidity -- only an
            # actual low reading is. Absent volume passes, so a Yahoo gap can
            # never silently truncate the whole strip.
            avg_vol = float(vol.mean()) if vol is not None and len(vol) else float("nan")
            if avg_vol == avg_vol and avg_vol < min_volume:
                break          # truncate here; everything beyond is thinner still
            rows.append({"expiry": expiry, "symbol": sym, "years_fwd": yrs,
                         "price": float(close.iloc[-1]),
                         "implied_rate": 100.0 - float(close.iloc[-1]),
                         "avg_volume": avg_vol})
        if not rows:
            raise RuntimeError(f"no liquid {root} contracts returned data")
        return pd.DataFrame(rows).set_index("expiry").sort_index()

    try:
        frame, meta = cache.through("yahoo", f"strip_{root}_{n}_{min_volume}",
                                    cache.TTL_INTRADAY, pull)
    except Exception as e:
        return failed(root, label, "Yahoo Finance (CME futures)", e)
    return Series(
        key=root, label=label, frame=frame,
        source="Yahoo Finance (CME futures)", unit="%", cadence_days=1,
        as_of=pd.Timestamp.today().date(),
        status=Status.STALE if str(meta).startswith("stale") else Status.OK,
        note="Implied rate = 100 - price; plotted at its reference-period midpoint.",
    )


# -- commodity forward curves --------------------------------------------

COMMODITY_EXCHANGE = {"CL": "NYM", "NG": "NYM", "RB": "NYM", "HO": "NYM",
                      "GC": "CMX", "SI": "CMX", "HG": "CMX", "PL": "NYM"}


def commodity_curve(root: str = "CL", n: int = 8, label: str = "") -> Series:
    """Dated futures curve for a commodity -- the contango/backwardation read.

    Yahoo requires the exchange suffix on dated contracts (CLZ26.NYM); the bare
    root+month+year form silently returns nothing through yfinance, so the
    suffix is not optional.
    """
    ex = COMMODITY_EXCHANGE.get(root, "NYM")
    # Start one month out: the current delivery month is usually expired or
    # illiquid, and Yahoo 404s on it noisily.
    today = pd.Timestamp.today() + pd.DateOffset(months=1)
    pairs: list[tuple[str, pd.Timestamp]] = []
    y, m = today.year, today.month
    while len(pairs) < n:
        pairs.append((f"{root}{MONTH_CODES[m]}{str(y)[-2:]}.{ex}",
                      pd.Timestamp(year=y, month=m, day=1)))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    def pull() -> pd.DataFrame:
        frame = history([s for s, _ in pairs], period="5d")
        rows = []
        for sym, expiry in pairs:
            if sym in frame.columns and frame[sym].notna().any():
                rows.append({"expiry": expiry, "symbol": sym,
                             "price": float(frame[sym].dropna().iloc[-1])})
        if not rows:
            raise RuntimeError(f"no {root} contracts returned data")
        return pd.DataFrame(rows).set_index("expiry").sort_index()

    try:
        frame, meta = cache.through("yahoo", f"cmdty_{root}_{n}", cache.TTL_INTRADAY, pull)
    except Exception as e:
        return failed(root, label or root, "Yahoo Finance (CME futures)", e)
    return Series(
        key=root, label=label or root, frame=frame,
        source="Yahoo Finance (CME futures)", cadence_days=1,
        as_of=pd.Timestamp.today().date(),
        status=Status.STALE if str(meta).startswith("stale") else Status.OK,
    )


def curve_shape(frame: pd.DataFrame, months: int = 6) -> float:
    """Annualised slope between the front contract and `months` out, in percent.

    Positive means backwardation (front richer than deferred) -- physical
    tightness. Negative means contango.
    """
    if len(frame) < 2:
        return float("nan")
    f1 = float(frame["price"].iloc[0])
    idx = min(months, len(frame) - 1)
    fn = float(frame["price"].iloc[idx])
    if fn == 0:
        return float("nan")
    return (f1 / fn - 1.0) * (12.0 / idx) * 100.0
