"""Reusable Streamlit pieces: stat tiles, freshness badges, section chrome.

The freshness badge is the heart of it. Every tile shows the source's own
observation date (`as_of`), not our pull time, and turns amber when that date
trails the series' expected cadence. The pull time lives in the header, once.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from . import theme
from .contract import Series

CSS = f"""
<style>
  .stApp {{ background: {theme.PAGE}; }}
  .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1600px; }}

  .ficc-card {{
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
    border-radius: 10px; padding: 14px 16px; height: 100%;
  }}
  .ficc-tile-label {{
    font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
    color: {theme.MUTED}; margin: 0 0 6px 0; font-weight: 600;
  }}
  .ficc-tile-value {{
    font-size: 26px; font-weight: 650; color: {theme.INK};
    line-height: 1.1; margin: 0;
  }}
  .ficc-tile-unit {{ font-size: 14px; color: {theme.INK_2}; font-weight: 500; margin-left: 3px; }}
  .ficc-tile-delta {{ font-size: 12px; font-weight: 600; margin-top: 5px; font-variant-numeric: tabular-nums; }}
  .ficc-tile-sub {{ font-size: 11px; color: {theme.MUTED}; margin-top: 4px; }}

  .ficc-badge {{
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 10px; font-weight: 600; letter-spacing: .03em;
    padding: 1px 6px; border-radius: 20px; border: 1px solid {theme.BORDER};
    color: {theme.MUTED};
  }}

  .ficc-section {{
    display: flex; align-items: baseline; gap: 12px;
    margin: 26px 0 12px 0; padding-bottom: 8px;
    border-bottom: 1px solid {theme.BORDER};
  }}
  .ficc-section h2 {{
    font-size: 15px; font-weight: 680; color: {theme.INK}; margin: 0;
    letter-spacing: .01em;
  }}
  .ficc-section span {{ font-size: 12px; color: {theme.MUTED}; }}

  .ficc-hdr-title {{ font-size: 27px; font-weight: 700; color: {theme.INK}; margin: 0; letter-spacing:-.01em;}}
  .ficc-hdr-sub {{ font-size: 12.5px; color: {theme.MUTED}; margin: 4px 0 0 0; }}

  .ficc-regime {{
    display:inline-block; padding: 5px 14px; border-radius: 6px;
    font-size: 13px; font-weight: 700; letter-spacing: .02em;
  }}
  div[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
  table.ficc-tbl {{ width:100%; border-collapse: collapse; font-size: 12px;
                    font-variant-numeric: tabular-nums; }}
  table.ficc-tbl th {{ text-align: right; color: {theme.MUTED}; font-weight: 600;
                       padding: 5px 8px; border-bottom: 1px solid {theme.BORDER};
                       font-size: 10.5px; text-transform: uppercase; letter-spacing:.05em;}}
  table.ficc-tbl th:first-child, table.ficc-tbl td:first-child {{ text-align: left; }}
  table.ficc-tbl td {{ padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,.04);
                       color: {theme.INK_2}; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# -- freshness -----------------------------------------------------------

def badge_html(s: Series) -> str:
    """Freshness pill: the source's observation date, colored by staleness."""
    status = s.freshness.value
    color = theme.STATUS_COLORS.get(status, theme.MUTED)
    icon = theme.STATUS_ICONS.get(status, "●")
    if s.as_of is None:
        text = "no data"
    else:
        lag = s.lag_days()
        if lag is not None and lag <= 0:
            text = "today"
        elif lag == 1:
            text = "1d ago"
        else:
            text = f"{lag}d ago"
        text = f"{s.as_of:%d %b} · {text}"
    if status == "failed":
        text = "unavailable"
    return (f'<span class="ficc-badge" style="color:{color};border-color:{color}33">'
            f'{icon} {text}</span>')


def fmt(v: float | None, dp: int = 2, plus: bool = False) -> str:
    if v is None or v != v:
        return "—"
    return f"{v:+,.{dp}f}" if plus else f"{v:,.{dp}f}"


# -- tiles ---------------------------------------------------------------

def tile(label: str, value: float | None, s: Series | None = None, *,
         unit: str = "", dp: int = 2, delta: float | None = None,
         delta_unit: str = "bp", invert: bool = False, sub: str = "",
         mode: str = "perf") -> str:
    """One stat tile as HTML.

    `mode` picks the delta convention: "perf" (up is good), "risk" (up is bad --
    spreads and vol), or "rates" (up is neither good nor bad, just a selloff --
    rendered red for higher yields, blue for lower, as a rates desk would).
    """
    val = fmt(value, dp)
    parts = [
        '<div class="ficc-card">',
        f'<p class="ficc-tile-label">{label}</p>',
        f'<p class="ficc-tile-value">{val}'
        f'{f"<span class=ficc-tile-unit>{unit}</span>" if unit else ""}</p>',
    ]
    if delta is not None and delta == delta:
        c = theme.delta_color(delta, invert, mode)
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "■")
        parts.append(f'<div class="ficc-tile-delta" style="color:{c}">'
                     f'{arrow} {fmt(abs(delta), 1)} {delta_unit} 1d</div>')
    if sub:
        parts.append(f'<div class="ficc-tile-sub">{sub}</div>')
    if s is not None:
        parts.append(f'<div style="margin-top:8px">{badge_html(s)}</div>')
    parts.append("</div>")
    return "".join(parts)


def tile_row(tiles: list[str]) -> None:
    for col, html in zip(st.columns(len(tiles)), tiles):
        col.markdown(html, unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    st.markdown(
        f'<div class="ficc-section"><h2>{title}</h2><span>{note}</span></div>',
        unsafe_allow_html=True,
    )


def sources_note(series: list[Series]) -> None:
    """Per-panel provenance line: which source, observed when."""
    seen: dict[str, Series] = {}
    for s in series:
        if s is not None and s.source not in seen:
            seen[s.source] = s
    bits = []
    for src, s in seen.items():
        stamp = f"{s.as_of:%d %b %Y}" if s.as_of else "n/a"
        bits.append(f"{src} · obs {stamp}")
    if bits:
        st.markdown(
            f'<div style="font-size:10.5px;color:{theme.MUTED};margin-top:4px">'
            f'Sources: {"  |  ".join(bits)}</div>', unsafe_allow_html=True)


def failures_note(series: list[Series]) -> None:
    bad = [s for s in series if s is not None and s.freshness.value == "failed"]
    if bad:
        names = ", ".join(f"{s.label}" for s in bad[:6])
        st.markdown(
            f'<div style="font-size:11px;color:{theme.WARNING};margin-top:6px">'
            f'▲ Unavailable this pull: {names}</div>', unsafe_allow_html=True)


def chart(fig, **kw) -> None:
    st.plotly_chart(theme.apply(fig, **kw), width="stretch",
                    config={"displayModeBar": False, "scrollZoom": False})


DENSE_CSS = f"""
<style>
  /* Terminal density: reclaim the padding Streamlit spends on breathing room. */
  .ficc-dense .ficc-section {{ margin: 12px 0 6px 0; padding-bottom: 4px; }}
  .ficc-dense .ficc-section h2 {{ font-size: 11px; letter-spacing: .09em;
                                  text-transform: uppercase; color: {theme.BLUE}; }}
  .ficc-dense .ficc-section span {{ font-size: 10.5px; }}
  .ficc-strip {{
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
    border-radius: 8px; padding: 8px 14px; margin-bottom: 10px;
  }}
  .ficc-strip .k {{ font-size: 9.5px; text-transform: uppercase;
                    letter-spacing: .07em; color: {theme.MUTED}; font-weight: 700; }}
  .ficc-strip .v {{ font-size: 15px; font-weight: 680; color: {theme.INK};
                    font-variant-numeric: tabular-nums; margin-left: 5px; }}
  .ficc-strip .sep {{ width:1px; height:22px; background:{theme.BORDER}; }}
</style>
"""


def dense_css() -> None:
    st.markdown(DENSE_CSS, unsafe_allow_html=True)


def strip(items: list[tuple[str, str, str]]) -> None:
    """A one-line status strip: (label, value, color) triples."""
    bits = []
    for i, (k, v, c) in enumerate(items):
        if i:
            bits.append('<div class="sep"></div>')
        bits.append(f'<div><span class="k">{k}</span>'
                    f'<span class="v" style="color:{c}">{v}</span></div>')
    st.markdown(f'<div class="ficc-strip">{"".join(bits)}</div>',
                unsafe_allow_html=True)


def stamp(fetched: dt.datetime) -> str:
    return fetched.astimezone().strftime("%H:%M:%S %Z, %d %b %Y")
