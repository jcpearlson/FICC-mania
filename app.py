"""FICC Mania — a fixed income, currencies and commodities dashboard.

Run it:   uv run streamlit run app.py

Every number on the page comes from a free, public, keyless source. Nothing
here requires a terminal subscription, a vendor login, or a paid API. Each
tile carries the observation date its source stamped on the data; the pull
time is in the header.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import streamlit as st

# Browser-tab mark: a yield curve in the app's own palette. Regenerate with
# `uv run python assets/make_favicon.py`. Falls back to an emoji if the file
# is missing, so a fresh clone without the asset still starts.
_ICON = Path(__file__).resolve().parent / "assets" / "favicon.png"

st.set_page_config(page_title="FICC Mania",
                   page_icon=str(_ICON) if _ICON.exists() else "📈",
                   layout="wide", initial_sidebar_state="collapsed")

from ficc import cache, theme, ui                      # noqa: E402
from ficc.panels import (  # noqa: E402
    credit, dashboard, fxcommods, overview, rates)

theme.register()
ui.inject_css()

CURVE_YEARS = list(range(dt.date.today().year - 2, dt.date.today().year + 1))


def header() -> None:
    left, right = st.columns([3, 1.15])
    with left:
        st.markdown(
            '<p class="ficc-hdr-title">FICC Mania</p>'
            '<p class="ficc-hdr-sub">Free, public, keyless data · every figure '
            'stamped with its source\'s own observation date.</p>',
            unsafe_allow_html=True)
    with right:
        pulled = dt.datetime.now().astimezone()
        st.markdown(
            f'<div style="text-align:right;padding-top:6px">'
            f'<div style="font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;'
            f'color:{theme.MUTED};font-weight:600">Data pulled</div>'
            f'<div style="font-size:15px;color:{theme.INK};font-variant-numeric:tabular-nums">'
            f'{pulled:%H:%M:%S %Z}</div>'
            f'<div style="font-size:11px;color:{theme.MUTED}">{pulled:%A %d %B %Y}</div>'
            f'</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("Refresh", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        if c2.button("Clear cache", width="stretch",
                     help="Drop the on-disk cache and re-pull every source from scratch"):
            n = cache.clear()
            st.cache_data.clear()
            st.toast(f"Cleared {n} cached payloads")
            st.rerun()


def main() -> None:
    header()
    tabs = st.tabs(["  Dashboard  ", "  Market health  ", "  Rates & curves  ",
                    "  Credit, CLOs & loans  ", "  FX & commodities  ", "  Sources  "])

    with tabs[0]:
        dashboard.render(CURVE_YEARS)
    with tabs[1]:
        overview.render()
    with tabs[2]:
        rates.render(CURVE_YEARS)
    with tabs[3]:
        credit.render()
    with tabs[4]:
        fxcommods.render()
    with tabs[5]:
        sources_tab()


def sources_tab() -> None:
    ui.section("Where every number comes from", "all keyless, all public")
    st.markdown(f"""
<table class="ficc-tbl">
<tr><th style="text-align:left">Source</th><th style="text-align:left">Used for</th>
<th style="text-align:left">Endpoint</th><th style="text-align:left">Freshness</th></tr>
<tr><td>US Treasury</td><td>UST par &amp; real yield curves</td>
    <td>home.treasury.gov daily-treasury-rates CSV</td><td>Same day, ~15:30 ET</td></tr>
<tr><td>FRED (St. Louis Fed)</td><td>ICE BofA OAS indices, breakevens, real yields,
    NFCI/STLFSI4, VIX history, Fed balance sheet</td>
    <td>fredgraph.csv?id=&lt;SERIES&gt; — no API key</td><td>T+1 for daily series</td></tr>
<tr><td>NY Fed markets API</td><td>SOFR (+percentiles, volume), EFFR, SOFR averages</td>
    <td>markets.newyorkfed.org/api</td><td>~08:00 ET, prior business day</td></tr>
<tr><td>MOF Japan</td><td>JGB par curve, 1Y–40Y, history to 1974</td>
    <td>mof.go.jp English CSV (jgbcme.csv + historical)</td><td>T+1</td></tr>
<tr><td>CME futures via Yahoo</td><td>Forward SOFR curve (SR3), Fed policy path (ZQ),
    commodity forward curves</td><td>yfinance</td><td>Intraday, 15-min delayed</td></tr>
<tr><td>Yahoo Finance</td><td>FX spot, metals, energy, ags, credit &amp; CLO ETFs,
    VIX/MOVE/SKEW/VVIX</td><td>yfinance</td><td>Intraday, 15-min delayed</td></tr>
</table>
""", unsafe_allow_html=True)

    ui.section("Deliberate omissions", "things a practitioner will look for and not find here")
    st.markdown(f"""
<div style="font-size:12.5px;color:{theme.INK_2};line-height:1.75;max-width:1000px">
<b>Cross-currency basis.</b> The basis swap is OTC and the quoted series are licensed.
No free source exists. Rather than ship a mislabelled proxy, it is absent — the Fed
swap-line series (<code>SWPT</code>) is tracked in the backlog as a <em>funding-stress</em>
signal, which is a consequence of basis widening, not the basis itself.<br>
<b>CLO tranche spreads.</b> Primary AAA discount margins and tranche spread curves are
licensed products. The listed CLO ETF complex (JAAA, JBBB, CLOA, CLOZ) stands in, and
is labelled a proxy everywhere it appears.<br>
<b>Loan index levels.</b> The S&amp;P/UBS and Morningstar/LSTA loan indices are licensed;
BKLN is the free stand-in.<br>
<b>True equity breadth.</b> Advance/decline and % above 200-day need constituent data.
Sector and equal-weight relative performance is the closest free substitute, and is
labelled as such.<br>
<b>CBOE FX vol indices.</b> EVZ, JYVIX and BPVIX do not resolve through this data path.
See <code>BACKLOG.md</code>.
</div>
""", unsafe_allow_html=True)

    ui.section("How freshness is reported", "")
    st.markdown(f"""
<div style="font-size:12.5px;color:{theme.INK_2};line-height:1.75;max-width:1000px">
Two timestamps are tracked separately for every series, because conflating them
would make the dashboard lie. <b>Observation date</b> is the date the source itself
stamps on the data — that is what each tile's badge shows. <b>Pull time</b> is when
this app fetched it, shown once in the header. A tile reading
<span class="ficc-badge" style="color:{theme.GOOD};border-color:{theme.GOOD}33">● today</span>
was observed today; one reading
<span class="ficc-badge" style="color:{theme.WARNING};border-color:{theme.WARNING}33">▲ 6d ago</span>
is being served but has fallen behind its source's normal cadence. If a source is
unreachable, the last good value is served from disk cache and badged accordingly,
so a single failed fetch never blanks the page.
</div>
""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
