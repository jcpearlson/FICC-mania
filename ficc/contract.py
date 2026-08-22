"""The data contract every fetcher in this project returns.

Two timestamps matter and they are not the same thing:

    as_of      -- the observation date the *source* stamps on the data.
    fetched_at -- the wall-clock moment *we* pulled it.

Conflating them makes the dashboard lie. FRED's USDJPY series can be six days
old while treasury.gov has already published today's curve; a tile that says
"updated 4 seconds ago" over a six-day-old print is worse than no timestamp at
all. Every panel renders both.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

UTC = _dt.timezone.utc


def now() -> _dt.datetime:
    return _dt.datetime.now(UTC)


class Status(str, Enum):
    OK = "ok"           # fetched fresh, within expected cadence
    STALE = "stale"     # served, but older than the source's cadence implies
    CACHED = "cached"   # served from disk cache without a network round trip
    FAILED = "failed"   # fetch raised; last-known-value served if we had one


@dataclass(slots=True)
class Series:
    """A time series plus its provenance.

    `frame` is a DataFrame indexed by date. Single-value quotes are just a
    one-row frame, so panels never branch on "is this a scalar or a series".
    """

    key: str
    label: str
    frame: pd.DataFrame
    source: str
    fetched_at: _dt.datetime = field(default_factory=now)
    as_of: _dt.date | None = None
    status: Status = Status.OK
    unit: str = ""
    note: str = ""
    cadence_days: float = 1.0   # expected publication cadence, in days

    def __post_init__(self) -> None:
        if self.as_of is None and len(self.frame):
            idx = self.frame.index[-1]
            self.as_of = idx.date() if hasattr(idx, "date") else idx

    # -- accessors -------------------------------------------------------
    @property
    def ok(self) -> bool:
        return self.status is not Status.FAILED and len(self.frame) > 0

    @property
    def col(self) -> pd.Series:
        """The first (usually only) data column."""
        return self.frame.iloc[:, 0]

    def latest(self, column: str | None = None) -> float | None:
        if not len(self.frame):
            return None
        s = self.frame[column] if column else self.col
        s = s.dropna()
        return float(s.iloc[-1]) if len(s) else None

    def change(self, periods: int = 1, column: str | None = None) -> float | None:
        """Absolute change over `periods` observations."""
        s = (self.frame[column] if column else self.col).dropna()
        if len(s) <= periods:
            return None
        return float(s.iloc[-1] - s.iloc[-1 - periods])

    def lag_days(self) -> float | None:
        """How many days behind today the observation is.

        Clamped at zero: some administered rates (IORB) are published with a
        forward effective date, which would otherwise give a negative lag and
        badge a not-yet-applicable rate as fresher than today's data.
        """
        if self.as_of is None:
            return None
        return max(0, (now().date() - self.as_of).days)

    @property
    def freshness(self) -> Status:
        """Status re-derived from how far `as_of` trails the expected cadence.

        A weekly series two days old is fine; a daily series two days old is
        not. Grace of 3 days absorbs weekends and holidays.
        """
        if self.status is Status.FAILED:
            return Status.FAILED
        lag = self.lag_days()
        if lag is None:
            return self.status
        if lag > self.cadence_days + 3:
            return Status.STALE
        return self.status

    def with_status(self, status: Status, note: str = "") -> "Series":
        self.status = status
        if note:
            self.note = note
        return self


def failed(key: str, label: str, source: str, err: Any) -> Series:
    """An empty Series carrying the error, so one dead fetcher never blanks a page."""
    return Series(
        key=key,
        label=label,
        frame=pd.DataFrame(),
        source=source,
        status=Status.FAILED,
        note=str(err)[:300],
    )
