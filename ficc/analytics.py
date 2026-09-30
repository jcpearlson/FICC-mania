"""Derived analytics -- the numbers practitioners actually quote.

Nothing here touches the network. Everything takes a Series (or a plain
DataFrame) and returns a scalar, a frame, or a small verdict object, so it
stays trivially testable and reusable across panels.
"""

from __future__ import annotations

from dataclasses import asdict as _asdict
from dataclasses import dataclass

import numpy as np
import pandas as pd


BP = 100.0  # percent -> basis points


# -- distribution context ------------------------------------------------

@dataclass(slots=True)
class ZScore:
    value: float
    mean: float
    sd: float
    z: float
    pct: float          # percentile rank within the window, 0-100
    window_label: str

    def _phrase(self, low: str, high: str) -> str:
        a = abs(self.z)
        side = low if self.z < 0 else high
        if a < 0.5:
            return "in line with history"
        if a < 1.0:
            return f"modestly {side}"
        if a < 2.0:
            return f"{side} vs history"
        return f"extremely {side}"

    @property
    def verdict(self) -> str:
        """Valuation read, for things that can be rich or cheap (spread levels)."""
        return self._phrase("rich", "cheap")

    @property
    def verdict_width(self) -> str:
        """For spreads and slopes, which are wide or narrow -- never rich or cheap.

        A curve slope is not a valuation; calling an inverted 2s10s "rich"
        is a category error a rates person would notice immediately.
        """
        return self._phrase("narrow", "wide")


def zscore(s: pd.Series, window_years: float = 5.0, label: str | None = None) -> ZScore | None:
    """Z-score and percentile of the latest print within a trailing window.

    `window_label` reports the span actually used, not the span requested.
    This matters more than it looks: FRED's keyless endpoint silently caps the
    licensed ICE BofA credit series at exactly three years, so asking for a 5y
    window on HY OAS quietly gets you 3y. Deriving the label from the data
    means a tile can never claim more history than it has.
    """
    s = pd.Series(s).dropna()
    if len(s) < 30:
        return None
    cutoff = s.index[-1] - pd.Timedelta(days=int(365.25 * window_years))
    w = s[s.index >= cutoff]
    if len(w) < 30:
        w = s
    val, mean, sd = float(w.iloc[-1]), float(w.mean()), float(w.std(ddof=0))
    z = (val - mean) / sd if sd > 0 else 0.0
    pct = float((w <= val).sum()) / len(w) * 100.0
    span = (w.index[-1] - w.index[0]).days / 365.25
    auto = f"{span:.0f}y" if span >= 1.5 else f"{span * 12:.0f}m"
    return ZScore(val, mean, sd, z, pct, label or auto)


def percentile_bands(s: pd.Series, window_years: float = 5.0) -> dict[str, float]:
    s = pd.Series(s).dropna()
    cutoff = s.index[-1] - pd.Timedelta(days=int(365.25 * window_years))
    w = s[s.index >= cutoff]
    return {f"p{p}": float(np.percentile(w, p)) for p in (0, 10, 25, 50, 75, 90, 100)}


# -- curve mathematics ---------------------------------------------------

def spread(frame: pd.DataFrame, long_leg: str, short_leg: str) -> pd.Series:
    """Curve slope in basis points, e.g. 2s10s = 10Y - 2Y."""
    return (frame[long_leg] - frame[short_leg]).dropna() * BP


def curve_snapshot(frame: pd.DataFrame, tenor_map: dict[str, float],
                   offsets: tuple[int, ...] = (0, 1, 5, 21, 63, 252)) -> pd.DataFrame:
    """Today's curve plus the same curve N sessions ago, tidy for plotting.

    Returns one row per (tenor, offset) with the maturity in years, so a curve
    chart and a change table both read off the same object.
    """
    cols = [c for c in frame.columns if c in tenor_map]
    rows = []
    for off in offsets:
        if off >= len(frame):
            continue
        row = frame[cols].iloc[-1 - off]
        stamp = frame.index[-1 - off]
        for c in cols:
            if pd.notna(row[c]):
                rows.append({"tenor": c, "years": tenor_map[c], "yield": float(row[c]),
                             "offset": off, "date": stamp})
    return pd.DataFrame(rows).sort_values(["offset", "years"])


def curve_changes(frame: pd.DataFrame, tenor_map: dict[str, float],
                  offsets: dict[str, int]) -> pd.DataFrame:
    """Per-tenor change in bp over several lookbacks -- the morning 'what moved' grid."""
    cols = [c for c in frame.columns if c in tenor_map]
    latest = frame[cols].iloc[-1]
    out = {"tenor": cols, "years": [tenor_map[c] for c in cols],
           "level": [float(latest[c]) if pd.notna(latest[c]) else np.nan for c in cols]}
    for name, off in offsets.items():
        if off < len(frame):
            prior = frame[cols].iloc[-1 - off]
            out[name] = [(float(latest[c]) - float(prior[c])) * BP
                         if pd.notna(latest[c]) and pd.notna(prior[c]) else np.nan
                         for c in cols]
    return pd.DataFrame(out).sort_values("years")


def butterfly(frame: pd.DataFrame, wing1: str, body: str, wing2: str) -> pd.Series:
    """Classic fly in bp: 2*body - wing1 - wing2."""
    return ((2 * frame[body] - frame[wing1] - frame[wing2]) * BP).dropna()


def forward_rate(y_short: float, t_short: float, y_long: float, t_long: float) -> float:
    """Continuously-compounded implied forward between two zero tenors."""
    if t_long <= t_short:
        return float("nan")
    return (y_long * t_long - y_short * t_short) / (t_long - t_short)


# -- cross-market ratios and regressions ---------------------------------

def ratio(a: pd.Series, b: pd.Series, name: str = "ratio") -> pd.Series:
    df = pd.concat([pd.Series(a).rename("a"), pd.Series(b).rename("b")], axis=1).dropna()
    return (df["a"] / df["b"]).rename(name)


def align_recent(series_map: dict[str, pd.Series], max_age_days: int = 7) -> pd.DataFrame:
    """Align holiday calendars without extending a stopped source indefinitely."""
    data = {k: pd.Series(v).replace([np.inf, -np.inf], np.nan).dropna().sort_index()
            for k, v in series_map.items()}
    frame = pd.concat(data, axis=1).sort_index()
    for name, values in data.items():
        dates = pd.Series(values.index, index=values.index).reindex(frame.index).ffill()
        age = (pd.Series(frame.index, index=frame.index) - dates).dt.total_seconds() / 86400
        frame[name] = frame[name].ffill().where(age <= max_age_days)
    return frame.dropna()


def beta(y: pd.Series, x: pd.Series, window_days: int = 252) -> tuple[float, float, float]:
    """OLS slope, intercept and R^2 of y on x over a trailing window.

    Used for the USDJPY vs UST-JGB spread relationship, where the residual --
    how far spot sits from what rates justify -- is the actual signal.
    """
    df = pd.concat([pd.Series(y).rename("y"), pd.Series(x).rename("x")], axis=1).dropna()
    if len(df) > window_days:
        df = df.iloc[-window_days:]
    if len(df) < 20:
        return float("nan"), float("nan"), float("nan")
    slope, intercept = np.polyfit(df["x"], df["y"], 1)
    resid = df["y"] - (slope * df["x"] + intercept)
    ss_tot = float(((df["y"] - df["y"].mean()) ** 2).sum())
    r2 = 1 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    return float(slope), float(intercept), float(r2)


def residual_now(y: pd.Series, x: pd.Series, window_days: int = 252) -> float:
    """Current deviation of y from its fitted relationship with x."""
    slope, intercept, _ = beta(y, x, window_days)
    df = pd.concat([pd.Series(y).rename("y"), pd.Series(x).rename("x")], axis=1).dropna()
    if not len(df) or np.isnan(slope):
        return float("nan")
    last = df.iloc[-1]
    return float(last["y"] - (slope * last["x"] + intercept))


def rolling_beta(y: pd.Series, x: pd.Series, window: int = 250) -> pd.Series:
    """Trailing OLS slope of y on x, vectorised: cov(x, y) / var(x).

    Identical to refitting `beta()` at every date, without a Python loop of
    several hundred `polyfit` calls per render.
    """
    df = pd.concat([pd.Series(y).rename("y"), pd.Series(x).rename("x")], axis=1).dropna()
    cov = df["y"].rolling(window).cov(df["x"])
    var = df["x"].rolling(window).var()
    return (cov / var.where(var > 0)).rename("beta")


def realised_vol(s: pd.Series, window: int = 21, annualise: int = 252) -> pd.Series:
    r = pd.Series(s).dropna().pct_change()
    return (r.rolling(window).std() * np.sqrt(annualise) * 100).dropna()


def drawdown(s: pd.Series) -> pd.Series:
    s = pd.Series(s).dropna()
    return (s / s.cummax() - 1.0) * 100


def pct_return(s: pd.Series, periods: int = 1) -> float | None:
    """Percentage change over N observations, measured against the *earlier* value."""
    s = pd.Series(s).dropna()
    if len(s) <= periods:
        return None
    then = float(s.iloc[-1 - periods])
    return (float(s.iloc[-1]) / then - 1.0) * 100.0 if then else None


def value_at_or_before(s: pd.Series, when: pd.Timestamp) -> float | None:
    """Last observation on or before `when` -- for calendar-based lookbacks."""
    s = pd.Series(s).dropna()
    s = s[s.index <= when]
    return float(s.iloc[-1]) if len(s) else None


def pct_change_bp(s: pd.Series, periods: int) -> float | None:
    """Change over N observations, in bp -- for rates/spreads quoted in percent."""
    s = pd.Series(s).dropna()
    if len(s) <= periods:
        return None
    return float(s.iloc[-1] - s.iloc[-1 - periods]) * BP


# -- risk regime scoring -------------------------------------------------

def regime_score(components: dict[str, float]) -> tuple[float, str]:
    """Blend signed component scores (-1 risk-off .. +1 risk-on) into one read.

    Deliberately simple and transparent: an opaque composite that cannot be
    decomposed on the page is not useful to a practitioner.
    """
    vals = [v for v in components.values() if v is not None and np.isfinite(v)]
    if not vals:
        return float("nan"), "no data"
    score = float(np.mean(vals))
    if score <= -0.5:
        return score, "Risk-off"
    if score <= -0.15:
        return score, "Cautious"
    if score < 0.15:
        return score, "Neutral"
    if score < 0.5:
        return score, "Constructive"
    return score, "Risk-on"


def signed_z(s: pd.Series, window_years: float = 5.0, invert: bool = False,
             cap: float = 2.0) -> float:
    """Z-score squashed to roughly [-1, 1] for regime blending.

    `invert=True` for series where *higher is worse* (spreads, vol), so that a
    positive contribution always means risk-on.
    """
    z = zscore(s, window_years)
    if z is None:
        return float("nan")
    v = max(-cap, min(cap, z.z)) / cap
    return -v if invert else v


# -- carry and roll-down -------------------------------------------------

def duration(y: float, t: float, freq: int = 2) -> float:
    """Modified duration of a par bond at yield `y` (percent), maturity `t` years.

    For a par bond the Macaulay duration collapses to a closed form in periods:

        D_mac = (1 + i) / i * (1 - (1 + i)^-n)

    with i the per-period yield and n the number of periods. It behaves at both
    limits -- n = 1 gives exactly one period, and n -> infinity gives the
    perpetuity duration (1 + i)/i. Modified duration is then D_mac / (1 + i).
    """
    if t <= 0:
        return 0.0
    n = max(1, int(round(t * freq)))
    per = (y / 100.0) / freq
    if abs(per) < 1e-12:          # zero-yield limit
        return t
    mac_periods = (1 + per) / per * (1 - (1 + per) ** (-n))
    return (mac_periods / freq) / (1 + per)


def interp_curve(tenors: dict[str, float], levels: dict[str, float], t: float) -> float:
    """Linear interpolation along the par curve at maturity `t` years."""
    pts = sorted((yrs, levels[k]) for k, yrs in tenors.items()
                 if k in levels and levels[k] == levels[k])
    if not pts:
        return float("nan")
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= t <= x1:
            w = (t - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + w * (y1 - y0)
    return float("nan")


@dataclass(slots=True)
class CarryRoll:
    tenor: str
    years: float
    yield_now: float
    carry_bp: float
    roll_bp: float
    total_bp: float
    breakeven_bp: float
    duration: float

    @property
    def caption(self) -> str:
        return (f"{self.tenor} earns {self.total_bp:.0f}bp over the horizon; "
                f"it takes a {self.breakeven_bp:.0f}bp selloff to break even")


def carry_rolldown(tenors: dict[str, float], levels: dict[str, float],
                   front_rate: float, horizon_years: float = 0.25) -> pd.DataFrame:
    """Carry, roll-down and the breakeven yield rise for each tenor.

    This is the calculation that turns a curve picture into a trade:

        carry      = (y_T - r_f) * h
        roll-down  = (y_T - y_{T-h}) * D_{T-h}
        breakeven  = (carry + roll-down) / D_T

    `front_rate` is the financing rate (3m bill or SOFR). All outputs in bp.
    """
    rows = []
    for name, t in sorted(tenors.items(), key=lambda kv: kv[1]):
        y = levels.get(name)
        if y is None or y != y or t < horizon_years:
            continue
        y_roll = interp_curve(tenors, levels, t - horizon_years)
        d_now = duration(y, t)
        d_roll = duration(y_roll, t - horizon_years)
        carry = (y - front_rate) * horizon_years * BP
        roll = (y - y_roll) * d_roll * BP
        total = carry + roll
        be = total / d_now if d_now > 0 else float("nan")
        rows.append(CarryRoll(name, t, y, carry, roll, total, be, d_now))
    return pd.DataFrame([_asdict(r) for r in rows])


def common_base_index(series_map: dict[str, pd.Series], base: float = 100.0) -> pd.DataFrame:
    """Index several series to a *shared* start date, not to each one's own.

    Normalising each line to its own first observation silently compares
    different start dates whenever the instruments have different inception
    dates -- a younger ETF looks like it outperformed simply because its
    window is shorter. Aligning on the latest common start fixes that.
    """
    df = pd.concat({k: pd.Series(v).dropna() for k, v in series_map.items()}, axis=1)
    df = df.dropna()
    if df.empty:
        return df
    return df / df.iloc[0] * base


def implied_default_rate(oas_pct: float, recovery: float = 0.40) -> float:
    """Annual default rate the spread is compensating for, in percent.

        PD = OAS / (1 - R)

    The standard credit-triangle inversion. At 40% recovery an OAS of 275bp
    implies roughly a 4.6% annual default rate -- the number that turns a
    spread level into a testable view.
    """
    if oas_pct != oas_pct or recovery >= 1:
        return float("nan")
    return oas_pct / (1.0 - recovery)


def excess_over_loss(oas_pct: float, loss_rate_pct: float) -> float:
    """OAS minus the realised annual *loss* rate -- the credit risk premium.

    Takes a loss rate, not a default rate. A charge-off rate is already net of
    recovery (it is the loss), so multiplying it by (1 - R) again -- as if it
    were a default rate -- understates expected loss by 40% and overstates the
    premium. Convert a genuine default rate with `default_pct * (1 - R)`
    before calling this.
    """
    if oas_pct != oas_pct or loss_rate_pct != loss_rate_pct:
        return float("nan")
    return oas_pct - loss_rate_pct


def loss_to_default_rate(loss_pct: float | pd.Series, recovery: float = 0.40):
    """Default rate implied by a loss rate at the given recovery: L / (1 - R).

    Puts a charge-off series on the same footing as `implied_default_rate`,
    so the two can share an axis honestly.
    """
    return loss_pct / (1.0 - recovery)


def net_liquidity(walcl_mn: pd.Series, tga_mn: pd.Series, rrp_bn: pd.Series) -> pd.Series:
    """Fed balance sheet minus TGA minus ON RRP, in $ trillions.

    The market's shorthand for how much central-bank liquidity is actually in
    the private system. Units differ at source -- WALCL is in $ millions,
    WTREGEN is also in $ millions; RRPONTSYD is in $ billions. This is the kind of thing
    that silently produces a 1000x error, so the conversion lives here once.

    Evaluated on the balance-sheet dates (weekly, Wednesday); the daily RRP is
    taken as its last value on or before each date.
    """
    w = pd.Series(walcl_mn).dropna() / 1e6
    parts = pd.concat([w.rename("w"),
                       (pd.Series(tga_mn) / 1e6).rename("t"),
                       (pd.Series(rrp_bn) / 1e3).rename("r")], axis=1).sort_index()
    parts[["t", "r"]] = parts[["t", "r"]].ffill()
    parts = parts.loc[parts.index.isin(w.index)].dropna()
    return (parts["w"] - parts["t"] - parts["r"]).rename("net_liquidity")
