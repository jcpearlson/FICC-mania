"""Automated data-quality checks for every fetched series.

The freshness badge answers one question -- is the observation date behind
its cadence? -- but free data fails in quieter ways too, and each of these has
happened to a source this app uses:

  * flatline   a dead Yahoo symbol keeps returning its last print, so the
               series looks alive and never moves.
  * jump       a unit change or a bad print (a price in cents, a rate in bp)
               shows up as a single move far outside the series' own history.
  * gap        a source silently skips weeks -- a holiday is fine, a month is
               not.
  * short      a series with too little history for its percentile or
               z-score to mean anything.

None of these block rendering. They are surfaced on the Sources tab so a
reader can see which numbers deserve a second look.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contract import Series, Status


@dataclass(slots=True)
class Report:
    label: str
    source: str
    status: str
    as_of: object | None
    lag_days: int | None
    cadence_days: float
    n_obs: int
    span_years: float
    flags: list[str] = field(default_factory=list)

    @property
    def worst(self) -> str:
        if self.status == "failed":
            return "failed"
        if self.flags or self.status == "stale":
            return "warning"
        return "ok"


def _numeric_col(s: Series, column: str | None) -> pd.Series:
    if column:
        return pd.to_numeric(s.frame[column], errors="coerce").dropna()
    num = s.frame.select_dtypes("number")
    return num.iloc[:, 0].dropna() if num.shape[1] else pd.Series(dtype=float)


def check_label(s: Series, column: str | None = None) -> str:
    return f"{s.label} · {column}" if column else s.label


def assess(s: Series, column: str | None = None, *,
           flat_obs: int = 7, jump_sigma: float = 8.0,
           min_years: float = 1.0) -> Report:
    """Run every check on one series (optionally one column of a wide frame)."""
    label = check_label(s, column)
    freshness = s.freshness.value
    lag = s.lag_days()
    if not s.ok:
        return Report(label, s.source, "failed", None, None, s.cadence_days, 0, 0.0,
                      [s.note or "fetch failed"])
    col = _numeric_col(s, column)
    n = len(col)
    span = (col.index[-1] - col.index[0]).days / 365.25 if n > 1 else 0.0
    flags: list[str] = []

    if lag is not None and lag < 0 and not (s.date_basis == "session" and lag == -1):
        flags.append(f"future observation date: {-lag}d ahead of local calendar")

    if freshness == Status.STALE.value and lag is not None:
        if s.status is Status.STALE:
            flags.append("source unavailable; serving last good cache")
        if lag > s.cadence_days + 3:
            flags.append(f"stale: {lag}d old vs {s.cadence_days:g}d cadence")

    if s.date_basis == "curve":
        # The index holds delivery dates, not price history. Inspect each
        # contract's quote date instead of treating maturities as daily data.
        observed = pd.to_datetime(s.frame["observed_at"])
        if observed.nunique() > 1:
            flags.append(f"mixed quote dates: {observed.min():%d %b}–{observed.max():%d %b}")
        return Report(label, s.source, freshness, s.as_of, lag, s.cadence_days,
                      n, 0.0, flags)

    # Flatline only for market prices. Administered and reference rates
    # (IORB, EFFR) legitimately sit unchanged for weeks; a traded price that
    # has not moved in seven sessions is a dead symbol.
    if s.source.startswith("Yahoo") and n >= flat_obs:
        tail = col.iloc[-flat_obs:]
        if tail.nunique() == 1:
            flags.append(f"flat for last {flat_obs} obs")

    # Jump: the latest move against the robust scale of all prior moves.
    if n >= 60:
        d = col.diff().dropna()
        hist, last = d.iloc[:-1], float(d.iloc[-1])
        mad = float(np.median(np.abs(hist - hist.median()))) * 1.4826
        if mad > 0 and abs(last - float(hist.median())) / mad > jump_sigma:
            flags.append(f"last move {abs(last - float(hist.median())) / mad:.0f}x robust σ")

    # Gaps: allow generous slack for holidays and weekly/monthly cadences.
    if n > 2:
        max_gap = int(col.index.to_series().diff().dt.days.max())
        allowed = max(7, int(s.cadence_days * 2.5))
        if max_gap > allowed:
            flags.append(f"gap of {max_gap}d in history")

    if span < min_years and s.cadence_days <= 7:
        flags.append(f"short history ({span * 12:.0f}m)")

    return Report(label, s.source, freshness, s.as_of, lag, s.cadence_days,
                  n, span, flags)


def assess_many(items: list[tuple[Series | None, str | None]]) -> list[Report]:
    out = []
    for s, col in items:
        if s is None:
            continue
        out.append(assess(s, col))
    order = {"failed": 0, "warning": 1, "ok": 2}
    return sorted(out, key=lambda r: (order[r.worst], r.source, r.label))
