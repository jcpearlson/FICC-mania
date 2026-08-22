"""The dense monitor table -- the centrepiece of the terminal-style view.

One row per instrument, ~22px tall, showing level, four lookback changes, a
position-in-range marker, a sparkline and the source's observation date. The
goal is that roughly thirty instruments fit above the fold on a portrait
screen, which is what makes a glance actually a glance.

Every column in this table uses ONE directional convention: red means the
number went up, blue means it went down. Not the good/bad convention used on
the stat tiles elsewhere in the app.

That is deliberate. In a grid of thirty mixed instruments, a green print on the
credit rows and a red print on the rates rows would mean opposite things two
lines apart, and "good" is a position-dependent judgement anyway -- tighter
spreads are only good if you are long credit. Direction is position-neutral and
reads consistently down the whole column.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import analytics as an
from . import sparkline as sp
from . import theme
from .contract import Series

LOOKBACKS = (("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63))


@dataclass(slots=True)
class Row:
    label: str
    series: pd.Series | None            # history, for spark + percentile
    value: float | None
    unit: str = ""
    dp: int = 2
    mode: str = "rates"                 # rates | risk | perf
    chg_unit: str = "bp"                # bp | % | pts
    as_of: object | None = None
    note: str = ""
    scale: float = 1.0                  # multiply level for display (e.g. %→bp)
    chg_dp: int | None = None           # override decimals on change columns


def row_from(s: Series | None, label: str, *, mode: str = "rates",
             unit: str = "%", dp: int = 2, chg_unit: str = "bp",
             col: str | None = None, scale: float = 1.0,
             transform=None) -> Row | None:
    """Build a Row straight off a fetched Series, preserving its as_of."""
    if s is None or not s.ok:
        return None
    ser = s.frame[col] if col else s.col
    if transform is not None:
        ser = transform(ser)
    ser = pd.Series(ser).dropna()
    if ser.empty:
        return None
    return Row(label=label, series=ser, value=float(ser.iloc[-1]) * scale,
               unit=unit, dp=dp, mode=mode, chg_unit=chg_unit, as_of=s.as_of,
               scale=scale)


def _change(ser: pd.Series, periods: int, chg_unit: str) -> float | None:
    ser = ser.dropna()
    if len(ser) <= periods:
        return None
    now, then = float(ser.iloc[-1]), float(ser.iloc[-1 - periods])
    if chg_unit == "bp":
        return (now - then) * 100.0
    if chg_unit == "%":
        return (now / then - 1.0) * 100.0 if then else None
    return now - then


def _fmt(v: float | None, dp: int) -> str:
    return "—" if v is None or v != v else f"{v:,.{dp}f}"


def _fmt_chg(v: float | None, chg_unit: str, dp: int | None = None) -> str:
    if v is None or v != v:
        return "—"
    if dp is None:
        dp = 0 if chg_unit == "bp" else (2 if abs(v) < 10 else 1)
    return f"{v:+,.{dp}f}"


def render_html(groups: list[tuple[str, list[Row | None]]],
                spark_years: float = 3.0) -> str:
    """Render grouped rows as one compact HTML table."""
    # Sparkline sits next to Last so level and shape read as one glance, and
    # the range bar carries its own percentile number rather than spending a
    # separate column restating the same scalar.
    head = (
        '<tr class="mon-head">'
        '<th class="mon-name">Instrument</th><th>Last</th>'
        '<th class="mon-spk">3y</th>'
        + "".join(f"<th>{n}</th>" for n, _ in LOOKBACKS)
        + '<th class="mon-rng">Range in own history</th>'
        '<th class="mon-as">As of</th></tr>'
    )
    ncols = 8 + len(LOOKBACKS)
    body: list[str] = []
    for gname, rows in groups:
        live = [r for r in rows if r is not None]
        if not live:
            continue
        body.append(
            f'<tr class="mon-grp"><td colspan="{ncols}">{gname}</td></tr>')
        for r in live:
            ser = r.series
            z = an.zscore(ser, spark_years) if ser is not None else None
            pct = z.pct if z else None

            cells = [f'<td class="mon-name">{r.label}</td>',
                     f'<td class="mon-val">{_fmt(r.value, r.dp)}'
                     f'<span class="mon-unit">{r.unit}</span></td>',
                     f'<td class="mon-spk">{sp.spark(ser)}</td>']
            for _, per in LOOKBACKS:
                c = _change(ser, per, r.chg_unit) if ser is not None else None
                # Direction only -- see the module docstring.
                color = theme.delta_color(c, mode="rates")
                cells.append(f'<td class="mon-chg" style="color:{color}">'
                             f'{_fmt_chg(c, r.chg_unit, r.chg_dp)}</td>')

            pcol = (theme.SERIOUS if pct is not None and (pct >= 90 or pct <= 10)
                    else theme.MUTED)
            ptxt = "—" if pct is None else f"{pct:.0f}"
            cells.append(
                f'<td class="mon-rng">{sp.range_bar(pct)}'
                f'<span class="mon-pct" style="color:{pcol}">{ptxt}</span></td>')

            stamp = f"{r.as_of:%d %b}" if r.as_of else "—"
            cells.append(f'<td class="mon-as">{stamp}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")

    return (f'<table class="mon">{head}{"".join(body)}</table>')


CSS = f"""
<style>
  table.mon {{
    width: 100%; border-collapse: collapse;
    font-variant-numeric: tabular-nums; font-size: 11.5px;
  }}
  table.mon th {{
    font-size: 9.5px; text-transform: uppercase; letter-spacing: .07em;
    color: {theme.MUTED}; font-weight: 700; text-align: right;
    padding: 0 7px 5px 7px; border-bottom: 1px solid {theme.BORDER};
    white-space: nowrap;
  }}
  table.mon td {{
    padding: 2px 7px; text-align: right; white-space: nowrap;
    border-bottom: 1px solid rgba(255,255,255,.035);
    color: {theme.INK_2}; line-height: 1.55;
  }}
  table.mon tr:hover td {{ background: rgba(255,255,255,.035); }}
  .mon-name {{ text-align: left !important; color: {theme.INK} !important;
               font-weight: 550; }}
  .mon-val  {{ color: {theme.INK} !important; font-weight: 650; }}
  .mon-unit {{ color: {theme.MUTED}; font-weight: 400; font-size: 9.5px;
               margin-left: 2px; }}
  .mon-chg  {{ font-weight: 600; }}
  .mon-pct  {{ font-size: 10px; margin-left: 5px; font-weight: 600;
               display: inline-block; min-width: 16px; text-align: right;
               vertical-align: middle; }}
  .mon-as   {{ color: {theme.MUTED} !important; font-size: 9.5px; }}
  .mon-rng {{ padding: 0 6px !important; white-space: nowrap; }}
  .mon-spk {{ padding: 0 6px !important; }}
  tr.mon-grp td {{
    text-align: left !important; padding: 9px 7px 3px 7px;
    font-size: 9.5px; font-weight: 700; letter-spacing: .09em;
    text-transform: uppercase; color: {theme.BLUE};
    border-bottom: 1px solid {theme.BORDER};
  }}
  tr.mon-grp:first-child td {{ padding-top: 2px; }}
</style>
"""
