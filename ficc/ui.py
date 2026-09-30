"""Reusable Streamlit pieces: stat tiles, freshness badges, section chrome.

The freshness badge is the heart of it. Every tile shows the source's own
observation date (`as_of`), not our pull time, and turns amber when that date
trails the series' expected cadence. Actual pull times live with the payload.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import re

import pandas as pd
import streamlit as st

from . import quality, theme
from .contract import Series

CSS = f"""
<style>
  .stApp {{ background: {theme.PAGE}; }}
  .block-container {{ padding: 4.5rem 2rem 3rem; max-width: 1500px; }}
  .st-key-ficc-phone-nav {{ display:none; }}
  [data-testid="stMainBlockContainer"] {{ min-width: 0; }}
  [data-testid="stColumn"] {{ min-width: 0; }}
  .ficc-masthead {{ display:flex; justify-content:space-between; align-items:center;
                    gap:24px; padding:12px 0 16px; border-bottom:1px solid {theme.BORDER}; }}
  .ficc-wordmark {{ font-family: 'Avenir Next', 'Trebuchet MS', sans-serif;
                    font-size:32px !important; letter-spacing:-.045em; font-weight:750;
                    margin:0 !important; padding:0 !important; color:{theme.INK}; }}
  .ficc-eyebrow {{ font-size:10px; font-weight:700; letter-spacing:.15em;
                   text-transform:uppercase; color:{theme.BLUE}; margin-bottom:6px; }}
  .ficc-clock {{ text-align:right; font-size:12px; color:{theme.INK_2}; white-space:nowrap; }}
  .ficc-clock .label {{ font-size:10px; text-transform:uppercase; letter-spacing:.08em;
                        color:{theme.MUTED}; }}
  .ficc-clock .time {{ font-family:'SFMono-Regular', Consolas, monospace;
                       font-size:15px; color:{theme.INK}; margin:4px 0; }}
  [data-testid="stMarkdownContainer"] .ficc-hdr-sub {{ font-size:12px; margin:7px 0 0;
                                                     color:{theme.INK_2}; line-height:1.5; }}
  .ficc-tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(145px, 1fr));
                 gap:12px; margin:8px 0 4px; }}

  .ficc-card {{
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
    border-radius: 6px; padding: 14px 16px; height: 100%; box-sizing:border-box;
    box-shadow:inset 0 2px 0 rgba(57,135,229,.12);
  }}
  [data-testid="stMarkdownContainer"] .ficc-tile-label {{
    font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
    color: {theme.MUTED}; margin: 0 0 6px 0; font-weight: 600;
  }}
  [data-testid="stMarkdownContainer"] .ficc-tile-value {{
    font-size: 26px; font-weight: 650; color: {theme.INK};
    line-height: 1.15; margin: 0; font-family:'SFMono-Regular', Consolas, monospace;
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
    display: flex; align-items: baseline; gap: 12px; flex-wrap:wrap;
    margin: 26px 0 12px 0; padding-bottom: 8px;
    border-bottom: 1px solid {theme.BORDER};
  }}
  [data-testid="stMarkdownContainer"] .ficc-section h2 {{
    font-size: 15px; font-weight: 680; color: {theme.INK}; margin: 0;
    letter-spacing: .01em;
  }}
  .ficc-section span {{ font-size: 12px; color: {theme.MUTED}; }}
  [data-testid="stMarkdownContainer"] .ficc-chart-heading {{ font-size:13px;
      font-weight:650; line-height:1.5; color:{theme.INK}; margin:12px 0 4px;
      overflow-wrap:anywhere; }}
  .ficc-quality {{ display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 16px;
      font-size:12px; padding:10px 12px; border-left:2px solid {theme.WARNING};
      background:{theme.SURFACE}; margin:4px 0 10px; color:{theme.INK_2}; }}
  .ficc-quality strong {{ color:{theme.WARNING}; }}
  .ficc-quality-details {{ color:{theme.INK_2}; font-size:12px; line-height:1.65; }}
  .ficc-table-scroll {{ overflow-x:auto; max-width:100%; border:1px solid {theme.BORDER};
      border-radius:6px; scrollbar-color:{theme.AXIS} {theme.PAGE}; }}
  [data-testid="stMarkdownContainer"]:has(table.ficc-tbl) {{ overflow-x:auto; }}
  table.ficc-tbl {{ min-width:520px; }}
  .ficc-help {{ font-size:11px; color:{theme.INK_2}; line-height:1.65; }}
  .ficc-provenance {{ font-size:11px; color:{theme.MUTED}; line-height:1.7; margin-top:12px; }}
  [data-testid="stTabs"] [role="tab"] {{ font-size:12px; font-weight:550; }}
  @media (max-width:1100px) {{
    [class*="st-key-ficc-grid"] [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; }}
    [class*="st-key-ficc-grid"] [data-testid="stColumn"] {{
      flex:1 1 360px !important; min-width:min(100%,360px) !important; }}
  }}
  @media (max-width:700px) {{
    .block-container {{ padding:4.5rem 1rem 2rem; }}
    .st-key-ficc-phone-nav {{ display:block; }}
    [data-testid="stTabs"] [role="tablist"] {{ display:none; }}
    .ficc-masthead {{ gap:12px; align-items:flex-start; padding-top:0; }}
    .ficc-wordmark {{ font-size:26px !important; }}
    .ficc-clock .time {{ font-size:12px; }}
    .ficc-clock .date {{ display:none; }}
    .ficc-eyebrow {{ font-size:9px; letter-spacing:.08em; }}
    .ficc-masthead .ficc-hdr-sub {{ display:none; }}
    .ficc-tiles {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .ficc-card {{ padding:12px; }}
    [data-testid="stMarkdownContainer"] .ficc-tile-value {{ font-size:23px; }}
    [class*="st-key-ficc-grid"] [data-testid="stColumn"] {{ flex-basis:100% !important; }}
    .ficc-section {{ gap:4px; margin-top:18px; }}
    .ficc-section span {{ width:100%; line-height:1.5; }}
  }}

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
    st.session_state["_ficc_grid_count"] = 0
    st.html(CSS)


def columns(spec):
    """Chart grids wrap at useful reading widths, rather than squeezing three plots."""
    count = st.session_state.get("_ficc_grid_count", 0)
    st.session_state["_ficc_grid_count"] = count + 1
    with st.container(key=f"ficc-grid-{count}"):
        return st.columns(spec, gap="medium")


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
        if s.date_basis == "session":
            text = "source session" + (f" ({s.observation_timezone})" if s.observation_timezone else "")
        elif lag is not None and lag < 0:
            text = f"future date · {-lag}d ahead"
            color, icon = theme.WARNING, "▲"
        elif lag == 0:
            text = "today"
        elif lag == 1:
            text = "1d ago"
        else:
            text = f"{lag}d ago"
        text = f"{s.as_of:%d %b} · {text}"
    if status == "failed":
        text = "unavailable"
    details = (f"{s.source} · pulled {stamp(s.fetched_at)}" if s.ok
               else f"{s.source} · no successful data pull")
    if s.note:
        details += f" · {s.note}"
    return (f'<span class="ficc-badge" title="{esc(details)}" '
            f'style="color:{color};border-color:{color}33">{icon} {esc(text)}</span>')


def esc(v: object) -> str:
    """Escape a value before it goes into an `unsafe_allow_html` block.

    Every label in this app is currently a hardcoded constant, so nothing here
    is exploitable today. That is a property of the current call sites, not of
    the rendering code -- the moment a label, source name or error string comes
    from a fetched payload, an unescaped f-string becomes an injection. Escaping
    at the boundary means that change stays safe by default.
    """
    return _html.escape(str(v), quote=True)


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
        f'<p class="ficc-tile-label">{esc(label)}</p>',
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
    if tiles:
        st.markdown(f'<div class="ficc-tiles">{"".join(tiles)}</div>', unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    st.markdown(
        f'<div class="ficc-section"><h2>{esc(title)}</h2>'        f'<span>{esc(note)}</span></div>',
        unsafe_allow_html=True,
    )


def sources_note(series: list[Series]) -> None:
    """Per-panel provenance line: which source, observed when."""
    seen: dict[str, list[Series]] = {}
    for s in series:
        if s is not None and s.ok:
            seen.setdefault(s.source, []).append(s)
    bits = []
    for src, group in seen.items():
        dates = sorted({date for s in group for date in
                        (pd.to_datetime(s.frame["observed_at"]).dt.date if s.date_basis == "curve"
                         else [s.as_of]) if date})
        observed = (f"{dates[0]:%d %b %Y}" if len(dates) == 1 else
                    f"{dates[0]:%d %b}–{dates[-1]:%d %b %Y}" if dates else "unavailable")
        pulled = min(s.fetched_at for s in group)
        bits.append(f"{esc(src)} · observations {observed} · earliest pull {stamp(pulled)}")
    if bits:
        st.markdown(
            '<div class="ficc-provenance">'
            f'Sources: {"  |  ".join(bits)}</div>', unsafe_allow_html=True)


def failures_note(series: list[Series]) -> None:
    bad = [s for s in series if s is not None and s.freshness.value == "failed"]
    if bad:
        names = ", ".join(esc(s.label) for s in bad[:6])
        st.markdown(
            f'<div style="font-size:11px;color:{theme.WARNING};margin-top:6px">'
            f'▲ Unavailable this pull: {names}</div>', unsafe_allow_html=True)


def chart(fig, **kw) -> None:
    # The installed browser renderer falls back to raw floats for +.2f-style
    # hover formats. Plain .2f retains negative signs and reliably rounds.
    # Explicit plus signs can still be supplied as preformatted customdata.
    for trace in fig.data:
        template = getattr(trace, "hovertemplate", None)
        if isinstance(template, str):
            trace.hovertemplate = re.sub(r":\+(\.\d+f)", r":\1", template)
    title = fig.layout.title.text
    if title:
        # Chart captions wrap in the document; SVG titles do not. Retain the
        # caption in figure metadata for exports and accessibility tooling.
        caption = re.sub(r"<[^>]+>", "", _html.unescape(title))
        st.markdown(f'<div class="ficc-chart-heading">{esc(caption)}</div>',
                    unsafe_allow_html=True)
        fig.update_layout(title_text="", meta={"caption": caption})
    st.plotly_chart(theme.apply(fig, **kw), width="stretch",
                    config={"displayModeBar": False, "scrollZoom": False})


def quality_summary(items: list[tuple[Series | None, str | None]]) -> None:
    """Warnings next to the panel that uses the values, with inspectable details."""
    unique = {}
    for s, col in items:
        if s is not None:
            unique.setdefault((s.source, s.key, col), (s, col))
    reports = quality.assess_many(list(unique.values()))
    bad = [r for r in reports if r.worst != "ok"]
    if bad:
        st.markdown(
            f'<div class="ficc-quality"><strong>▲ {len(bad)} data warnings</strong>'
            f'<span>{len(reports)} series checked · observation dates and history</span></div>',
            unsafe_allow_html=True)
        with st.expander("Inspect data warnings"):
            for r in bad:
                flags = "; ".join(r.flags) or r.status
                st.markdown(f'<div class="ficc-quality-details"><b>{esc(r.label)}</b>'
                            f' · {esc(flags)}</div>', unsafe_allow_html=True)


DENSE_CSS = f"""
<style>
  /* Terminal density: reclaim the padding Streamlit spends on breathing room. */
  .st-key-ficc-view-0 .ficc-section {{ margin: 12px 0 6px 0; padding-bottom: 4px; }}
  .st-key-ficc-view-0 .ficc-section h2 {{ font-size: 12px; letter-spacing: .09em;
                                  text-transform: uppercase; color: {theme.BLUE}; }}
  .st-key-ficc-view-0 .ficc-section span {{ font-size: 11px; }}
  .ficc-strip {{
    display: grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px 18px;
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
    border-radius: 8px; padding: 8px 14px; margin-bottom: 10px;
  }}
  .ficc-strip .k {{ font-size: 9.5px; text-transform: uppercase;
                    letter-spacing: .07em; color: {theme.MUTED}; font-weight: 700; }}
  .ficc-strip .v {{ font-size: 15px; font-weight: 680; color: {theme.INK};
                    font-variant-numeric: tabular-nums; margin-left: 5px; }}
  @media(max-width:700px) {{
    .ficc-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; padding:10px; }}
    .ficc-strip .v {{ font-size:13px; }}
  }}
</style>
"""


def dense_css() -> None:
    st.html(DENSE_CSS)


def strip(items: list[tuple[str, str, str]]) -> None:
    """A one-line status strip: (label, value, color) triples."""
    bits = []
    for k, v, c in items:
        bits.append(f'<div><span class="k">{k}</span>'
                    f'<span class="v" style="color:{c}">{v}</span></div>')
    st.markdown(f'<div class="ficc-strip">{"".join(bits)}</div>',
                unsafe_allow_html=True)


def stamp(fetched: dt.datetime) -> str:
    return fetched.astimezone().strftime("%H:%M:%S %Z, %d %b %Y")
