"""Transparent market-conditions heuristic, independent of Streamlit and network.

Historical values use trailing reference samples and bounded observation carry.
They use the currently available source vintage, not a point-in-time backtest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .analytics import regime_score
from .contract import Series

WEIGHTS = {"credit": .25, "vol": .25, "conditions": .20, "growth": .15, "trend": .15}
NAMES = {"credit": "Credit", "vol": "Volatility", "conditions": "Financial conditions",
         "growth": "Growth proxy", "trend": "Equity trend"}
MIN_COVERAGE = .80
MIN_HISTORY = 252
WINDOW = "1826D"


@dataclass
class Signal:
    component: str
    name: str
    history: pd.Series
    raw: pd.Series
    sources: tuple[Series, ...]
    method: str
    share: float = 1.0


@dataclass
class Result:
    score: float
    label: str
    coverage: float
    components: dict[str, float]
    weights: dict[str, float]
    contributions: dict[str, float]
    audit: pd.DataFrame
    history: pd.DataFrame

    @property
    def mixed(self) -> bool:
        vals = list(self.components.values())
        return any(v >= .25 for v in vals) and any(v <= -.25 for v in vals)

    @property
    def explanation(self) -> str:
        if not np.isfinite(self.score):
            return "Insufficient fresh inputs: requires 80% of intended weight, credit and volatility."
        pos = sorted(self.contributions, key=self.contributions.get, reverse=True)
        up = next((k for k in pos if self.contributions[k] > 0), None)
        down = next((k for k in reversed(pos) if self.contributions[k] < 0), None)
        parts = []
        if up:
            parts.append(f"{NAMES[up]} supports risk appetite ({self.contributions[up]:+.3f})")
        if down:
            parts.append(f"{NAMES[down]} offsets it ({self.contributions[down]:+.3f})")
        return "; ".join(parts) + "." if parts else "Available components are close to their anchors."


def _clean(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def normalized(s: pd.Series, *, invert=False, center=True) -> pd.Series:
    """Prior observations only, at least 252 prints; +/-2 sigma maps to +/-1."""
    s = _clean(s)
    prior = s.rolling(WINDOW, min_periods=MIN_HISTORY, closed="left")
    sd = prior.std(ddof=0).where(lambda v: v > 1e-12)
    values = (s - prior.mean() if center else s) / sd / 2
    return values.clip(-1, 1) * (-1 if invert else 1)


def _raw(s: Series | None) -> pd.Series:
    return _clean(s.col) if s is not None and s.ok else pd.Series(dtype=float, index=pd.DatetimeIndex([]))


def _signals(f, slow, mkt) -> list[Signal]:
    out = []

    def add(component, name, source, method, share=1, native=False, trend=False):
        raw = _raw(source)
        if trend:
            raw = (raw / raw.rolling(200, min_periods=200).mean() - 1).dropna()
        history = (-raw / 2).clip(-1, 1) if native else normalized(
            raw, invert=component in ("credit", "vol"), center=not trend)
        out.append(Signal(component, name, history, raw,
                          (source,) if source is not None else (), method, share))

    add("credit", "HY OAS", f.get("BAMLH0A0HYM2"), "Inverted trailing level z / 2")
    add("vol", "VIX", f.get("VIXCLS"), "Inverted trailing level z / 2", .5)
    add("vol", "MOVE", mkt.get("^MOVE"), "Inverted trailing level z / 2", .5)
    for key in ("NFCI", "STLFSI4"):
        add("conditions", key, slow.get(key), "Native index: -level / 2; zero = historical normal", .5, native=True)
    cu, au = mkt.get("HG=F"), mkt.get("GC=F")
    pair = pd.concat([_raw(cu).rename("c"), _raw(au).rename("g")], axis=1).dropna()
    raw = (pair.c / pair.g.where(pair.g > 0)).dropna()
    out.append(Signal("growth", "Copper / gold", normalized(raw), raw,
                      tuple(s for s in (cu, au) if s is not None),
                      "Trailing ratio z / 2; commodity futures proxy"))
    add("trend", "S&P 500 vs 200-day MA", mkt.get("^GSPC"),
        "Distance from MA / (2 x trailing distance SD); zero = MA", trend=True)
    return out


def _carry(s: pd.Series, grid: pd.DatetimeIndex, days: float) -> pd.Series:
    """Carry a print for a bounded age; never interpolate or backfill."""
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return pd.Series(np.nan, index=grid)
    union = s.index.union(grid).sort_values()
    values = s.reindex(union).ffill().reindex(grid)
    dates = pd.Series(s.index, index=s.index).reindex(union).ffill().reindex(grid)
    age = (pd.Series(grid, index=grid) - dates).dt.total_seconds() / 86400
    return values.where(age <= days)


def analyze(f, slow, mkt, *, as_of=None) -> Result:
    today = pd.Timestamp(as_of if as_of is not None else pd.Timestamp.now().date()).normalize()
    signals = _signals(f, slow, mkt)
    start = min((s.raw.index.min() for s in signals if not s.raw.empty), default=today)
    grid = pd.date_range(min(start, today), today, freq="D")
    component_num = pd.DataFrame(0., index=grid, columns=WEIGHTS)
    component_weight = component_num.copy()
    audit = []
    for signal in signals:
        sources = signal.sources
        grace = min((s.cadence_days + 3 for s in sources), default=4)
        raw = signal.raw.loc[signal.raw.index <= today]
        history = signal.history.loc[signal.history.index <= today]
        values = _carry(history, grid, grace)
        # Both underlying legs must be fresh at each date for a ratio to count.
        for source in sources:
            available = _carry(_raw(source), grid, source.cadence_days + 3).notna()
            values = values.where(available)
        reason = "Used"
        if not sources or any(not s.ok for s in sources) or (signal.component == "growth" and len(sources) != 2):
            reason = "Missing source"
            values[:] = np.nan
        elif any(s.as_of and pd.Timestamp(s.as_of) > max(today, pd.Timestamp.now().normalize()) for s in sources):
            reason = "Future observation date"
            values.iloc[-1] = np.nan
        elif raw.empty:
            reason = "No finite observations"
        elif (today - raw.index[-1]).days > grace or any(
                not _raw(s).empty and (today - _raw(s).index[-1]).days > s.cadence_days + 3
                for s in sources):
            reason = "Stale observation"
        elif pd.isna(values.iloc[-1]):
            reason = "Insufficient history or zero variance"
        component_num[signal.component] += values.fillna(0) * signal.share
        component_weight[signal.component] += values.notna() * signal.share
        past = raw.loc[(raw.index < raw.index[-1]) & (raw.index >= raw.index[-1] - pd.Timedelta(WINDOW))] if len(raw) else raw
        span = ((past.index[-1] - past.index[0]).days / 365.25) if len(past) > 1 else 0
        audit.append({"Component": NAMES[signal.component], "Input": signal.name,
                      "Value": float(raw.iloc[-1]) if len(raw) else np.nan,
                      "As of": raw.index[-1].date().isoformat() if len(raw) else "—",
                      "Score": float(values.iloc[-1]),
                      "Intended weight": WEIGHTS[signal.component] * signal.share,
                      "Reference": "Native zero" if signal.component == "conditions" else f"{span:.1f}y / {len(past)} prints",
                      "Method": signal.method, "Status": reason,
                      "Source": " + ".join(s.source for s in sources),
                      "Last pull": " / ".join(s.fetched_at.astimezone().strftime("%d %b %H:%M %Z") for s in sources if s.ok)})
    weights = component_weight.mul(pd.Series(WEIGHTS))
    coverage = weights.sum(axis=1)
    components = component_num.div(component_weight.where(component_weight > 0))
    total = component_num.mul(pd.Series(WEIGHTS)).sum(axis=1).div(coverage.where(coverage > 0))
    eligible = (coverage >= MIN_COVERAGE - 1e-9) & (component_weight.credit > 0) & (component_weight.vol > 0)
    total = total.where(eligible)
    score = float(total.iloc[-1])
    label = regime_score({"score": score})[1] if np.isfinite(score) else "Insufficient data"
    effective = weights.iloc[-1] / coverage.iloc[-1] if coverage.iloc[-1] else weights.iloc[-1]
    latest = components.iloc[-1].dropna().to_dict()
    contributions = {k: float(latest[k] * effective[k]) for k in latest}
    audit = pd.DataFrame(audit)
    audit["Effective weight"] = np.where(audit.Score.notna(), audit["Intended weight"] / coverage.iloc[-1], 0) if coverage.iloc[-1] else 0
    audit["Contribution"] = audit.Score * audit["Effective weight"]
    history = components.copy()
    history["score"], history["coverage"] = total, coverage
    return Result(score, label, float(coverage.iloc[-1]), latest, effective.to_dict(),
                  contributions, audit, history)
