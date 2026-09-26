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

from ficc import cache, quality, theme, ui             # noqa: E402
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
    st.markdown("""
<table class="ficc-tbl">
<tr><th style="text-align:left">Source</th><th style="text-align:left">Used for</th>
<th style="text-align:left">Endpoint</th><th style="text-align:left">Freshness</th></tr>
<tr><td>US Treasury</td><td>UST par &amp; real yield curves</td>
    <td>home.treasury.gov daily-treasury-rates CSV</td><td>Same day, ~15:30 ET</td></tr>
<tr><td>FRED (St. Louis Fed)</td><td>ICE BofA OAS indices, breakevens, real yields,
    term premium, NFCI/STLFSI4, VIX history, Fed balance sheet / TGA / ON RRP /
    reserves, commercial paper rates, SLOOS, bank charge-offs</td>
    <td>fredgraph.csv?id=&lt;SERIES&gt; — no API key</td><td>T+1 for daily series</td></tr>
<tr><td>NY Fed markets API</td><td>SOFR (+percentiles, volume), EFFR, SOFR averages</td>
    <td>markets.newyorkfed.org/api</td><td>~08:00 ET, prior business day</td></tr>
<tr><td>MOF Japan</td><td>JGB par curve, 1Y–40Y, history to 1974</td>
    <td>mof.go.jp English CSV (jgbcme.csv + historical)</td><td>T+1</td></tr>
<tr><td>CME futures via Yahoo</td><td>Forward SOFR curve (SR3), Fed policy path (ZQ),
    commodity forward curves</td><td>yfinance</td><td>Intraday, 15-min delayed</td></tr>
<tr><td>Yahoo Finance</td><td>FX spot, metals, energy, ags, credit &amp; CLO ETFs,
    VIX/MOVE/SKEW/VVIX</td><td>yfinance</td><td>Intraday, 15-min delayed</td></tr>
<tr><td>ECB Data Portal</td><td>Euro-area AAA government spot curve, EUR STR</td>
    <td>data-api.ecb.europa.eu SDMX CSV</td><td>T+1, ~12:00 CET</td></tr>
<tr><td>TreasuryDirect</td><td>Coupon auction results: bid-to-cover, bidder shares</td>
    <td>treasurydirect.gov/TA_WS JSON</td><td>Same day as auction</td></tr>
<tr><td>CFTC</td><td>Traders in Financial Futures positioning (JPY, EUR)</td>
    <td>publicreporting.cftc.gov Socrata</td><td>Weekly, Friday for Tuesday</td></tr>
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
licensed products. The listed CLO ETFs JAAA and JBBB stand in (total return, so
distributions do not read as losses), and are labelled a proxy everywhere they appear.<br>
<b>Loan index levels.</b> The S&amp;P/UBS and Morningstar/LSTA loan indices are licensed;
BKLN is the free stand-in.<br>
<b>True equity breadth.</b> Advance/decline and % above 200-day need constituent data.
Sector and equal-weight relative performance is the closest free substitute, and is
labelled as such.<br>
<b>CBOE FX vol indices.</b> EVZ, JYVIX and BPVIX do not resolve through this data path.
See <code>BACKLOG.md</code>.
</div>
""", unsafe_allow_html=True)

    _quality_table()

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


def _quality_table() -> None:
    """Every loaded series run through ficc.quality. All loaders are cache hits."""
    from ficc.panels import credit as cr, fxcommods as fx, overview as ov, rates as rt

    (ust, jgb, _sfwd, _ff, sofr_on, effr, _savg, extras, move, real) = rt._load(CURVE_YEARS)
    plumbing, cp, eur, estr, auctions = rt._load_extra()
    head, ladder, yields, banks, clo, etfs, vix, defaults = cr._load()
    fxb, metals, energy, ags, vols, _w, _n, _r, _u, _j = fx._load()
    f, slow, mkt = ov._load()
    items = [(ust, "10 Yr"), (real, None), (jgb, "10Y"), (sofr_on, "percentRate"),
             (effr, "percentRate"), (move, None), (eur, "10Y"), (estr, None),
             (auctions, "btc"),
             *[(s, None) for s in (*extras.values(), *plumbing.values(), *cp.values(),
                                   *head.values(), *ladder.values(), *yields.values(),
                                   *banks.values(), *defaults.values(), *slow.values())],
             *[(s, None) for d in (clo, etfs, fxb, metals, energy, ags, vols, mkt)
               for s in d.values()],
             *[(s, "lev_net_pct_oi") for s in fx._load_cot().values()]]
    # One report per (source, key) -- several panels share the same series.
    seen, uniq = set(), []
    for s, col in items:
        if s is not None and (s.source, s.key) not in seen:
            seen.add((s.source, s.key))
            uniq.append((s, col))
    reports = quality.assess_many(uniq)
    n_bad = sum(r.worst != "ok" for r in reports)
    ui.section("Data quality", f"{len(reports)} series checked · {n_bad} flagged — "
               "staleness, flatlines, outsized jumps, gaps and short history")
    colour = {"failed": theme.CRITICAL, "warning": theme.WARNING, "ok": theme.GOOD}
    rows = "".join(
        f"<tr><td style='color:{colour[r.worst]}'>{theme.STATUS_ICONS.get(r.status, '●')}</td>"
        f"<td>{ui.esc(r.label)}</td><td>{ui.esc(r.source)}</td>"
        f"<td style='text-align:right'>{f'{r.as_of:%d %b %Y}' if r.as_of else '—'}</td>"
        f"<td style='text-align:right'>{r.n_obs:,}</td>"
        f"<td style='text-align:right'>{r.span_years:.1f}y</td>"
        f"<td style='text-align:left;color:{colour[r.worst] if r.flags else theme.MUTED}'>"
        f"{ui.esc('; '.join(r.flags)) or 'clean'}</td></tr>"
        for r in reports)
    with st.expander(f"Per-series checks ({n_bad} flagged)", expanded=n_bad > 0):
        st.markdown(
            '<table class="ficc-tbl"><tr><th></th><th style="text-align:left">Series</th>'
            '<th style="text-align:left">Source</th><th>As of</th><th>Obs</th><th>Span</th>'
            f'<th style="text-align:left">Flags</th></tr>{rows}</table>',
            unsafe_allow_html=True)


if __name__ == "__main__":
    main()
