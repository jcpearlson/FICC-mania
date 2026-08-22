"""Credit: IG, HY, the ratings ladder, leveraged loans and CLOs.

Where the free-data honesty matters most. There is no free source for CLO
tranche spread curves, primary AAA discount margins, or loan index levels --
those are licensed products. What *is* free is the listed CLO ETF complex
(JAAA, JBBB, CLOA, CLOZ) and the loan ETF BKLN, whose prices and drawdowns
track the underlying complex closely enough to be a daily read. Everything
sourced that way is labelled a proxy on the page, never presented as the index.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import theme, ui
from ..sources import fred, market

# ICE BofA OAS ladder -- the spine of the panel.
LADDER = {
    "BAMLC0A1CAAA": "AAA", "BAMLC0A2CAA": "AA", "BAMLC0A3CA": "A",
    "BAMLC0A4CBBB": "BBB", "BAMLH0A1HYBB": "BB", "BAMLH0A2HYB": "B",
    "BAMLH0A3HYC": "CCC & lower",
}
HEADLINE = {
    "BAMLC0A0CM": "US IG OAS",
    "BAMLH0A0HYM2": "US HY OAS",
    "BAMLEMCBPIOAS": "EM corporate OAS",
    "BAMLHE00EHYIOAS": "Euro HY OAS",
}
YIELDS = {"BAMLC0A0CMEY": "IG yield", "BAMLH0A0HYM2EY": "HY yield"}
BANKS = {"DRTSCILM": "SLOOS: net % tightening C&I (large firms)",
         "TOTCI": "C&I loans outstanding ($bn)"}

# CLOA/CLOZ dropped: redundant with JAAA/JBBB and much younger, which made a
# shared index base impossible without throwing away most of the history.
# JNK dropped for the same reason in reverse -- ~0.99 correlated with HYG.
CLO_ETFS = {"JAAA": "AAA CLO (JAAA)", "JBBB": "BBB CLO (JBBB)",
            "BKLN": "Lev loans (BKLN)"}
CREDIT_ETFS = {"LQD": "IG (LQD)", "HYG": "HY (HYG)", "BKLN": "Lev loans (BKLN)",
               "EMB": "EM $ debt (EMB)", "JAAA": "AAA CLO (JAAA)"}
DEFAULTS = {"DRBLACBS": "Business loan delinquency rate",
            "CORBLACBS": "Business loan charge-off rate"}


@st.cache_data(ttl=900, show_spinner=False)
def _load():
    head = fred.many(HEADLINE)
    ladder = fred.many(LADDER)
    yields = fred.many(YIELDS)
    banks = {k: fred.get(k, v, cadence_days=(90 if k == "DRTSCILM" else 7))
             for k, v in BANKS.items()}
    # total_return=True: these are income instruments. On raw close a JAAA line
    # drifts down several percent a year on distributions alone, and drawdown
    # treats every ex-dividend date as stress. One shared period so the
    # cummax() windows are actually comparable across ETFs.
    clo = market.basket(CLO_ETFS, period="3y", total_return=True)
    etfs = market.basket(CREDIT_ETFS, period="3y", total_return=True)
    vix = fred.get("VIXCLS", "VIX")
    defaults = {k: fred.get(k, v, cadence_days=95) for k, v in DEFAULTS.items()}
    return head, ladder, yields, banks, clo, etfs, vix, defaults


def render() -> None:
    head, ladder, yields, banks, clo, etfs, vix, defaults = _load()

    # ---- headline tiles, colored by where the spread sits in its own history
    tiles = []
    for sid, label in HEADLINE.items():
        s = head[sid]
        if not s.ok:
            continue
        z = an.zscore(s.col, 5)
        tiles.append(ui.tile(
            label, s.latest() * 100 if s.latest() else None, s, unit="bp", dp=0,
            delta=an.pct_change_bp(s.col, 1), mode="risk",
            sub=f"{z.window_label} pct {z.pct:.0f} · {z.verdict}" if z else ""))
    # The dispersion tile: CCC minus BB is where HY stress shows up first.
    bb, ccc = ladder.get("BAMLH0A1HYBB"), ladder.get("BAMLH0A3HYC")
    if bb and ccc and bb.ok and ccc.ok:
        q = ((ccc.col - bb.col).dropna()) * 100
        z = an.zscore(q, 5)
        tiles.append(ui.tile(
            "CCC − BB quality spread", float(q.iloc[-1]), ccc, unit="bp", dp=0,
            delta=float(q.iloc[-1] - q.iloc[-2]) if len(q) > 1 else None, mode="risk",
            sub=f"{z.window_label} pct {z.pct:.0f} · {z.verdict_width}" if z else ""))
    ui.tile_row(tiles[:5])

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.3, 1])

    with c1:
        fig = go.Figure()
        for (sid, label), color in zip(HEADLINE.items(),
                                       (theme.BLUE, theme.ORANGE, theme.AQUA, theme.MAGENTA)):
            s = head[sid]
            if s.ok:
                d = (s.col * 100)
                fig.add_trace(go.Scatter(x=d.index, y=d, name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.0f} bp<extra>"
                                                       f"{label}</extra>"))
        fig.update_layout(
            title="Credit spreads — option-adjusted, full available history",
            yaxis=dict(title="OAS (bp)"))
        ui.chart(fig, height=320)

    with c2:
        # Ratings ladder: today vs 3m ago vs 1y ago. Log scale because CCC is
        # an order of magnitude above AAA and a linear axis flattens the rest.
        rows, ok = [], True
        for sid, label in LADDER.items():
            s = ladder[sid]
            if not s.ok:
                ok = False
                continue
            d = s.col.dropna()
            rows.append({"rating": label, "now": float(d.iloc[-1]) * 100,
                         "m3": float(d.iloc[-64]) * 100 if len(d) > 64 else None,
                         "y1": float(d.iloc[-252]) * 100 if len(d) > 252 else None})
        if rows:
            df = pd.DataFrame(rows)
            fig = go.Figure()
            for col, name, color, w in (("y1", "1y ago", theme.MUTED, 1.5),
                                        ("m3", "3m ago", theme.INK_2, 1.5),
                                        ("now", "Today", theme.BLUE, 2.6)):
                if col in df and df[col].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df["rating"], y=df[col], name=name, mode="lines+markers",
                        line=dict(width=w, color=color,
                                  dash="dot" if col != "now" else "solid"),
                        marker=dict(size=8 if col == "now" else 6),
                        hovertemplate="%{y:.0f} bp<extra>" + name + "</extra>"))
            fig.update_layout(title="Ratings ladder — OAS by rating",
                              yaxis=dict(title="OAS (bp)", type="log"))
            ui.chart(fig, height=320)

    # ---- CLOs and loans -------------------------------------------------
    ui.section("Structured credit & loans",
               "CLO tranche spreads are not public — the listed CLO ETF complex is used as a daily proxy")
    c1, c2, c3 = st.columns(3)

    with c1:
        avail = {lbl: clo[sym].col for sym, lbl in CLO_ETFS.items()
                 if clo.get(sym) and clo[sym].ok}
        if avail:
            idx = an.common_base_index(avail)
            fig = go.Figure()
            for (label, color) in zip(idx.columns, (theme.BLUE, theme.ORANGE, theme.YELLOW)):
                fig.add_trace(go.Scatter(x=idx.index, y=idx[label], name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}<extra>"
                                                       f"{label}</extra>"))
            fig.update_layout(
                title="CLO & loan total return, shared base = 100 (proxy)",
                yaxis=dict(title="Index"))
            ui.chart(fig, height=290)

    with c2:
        # Drawdown is the honest stress read on a price-only proxy.
        fig = go.Figure()
        for (sym, label), color in zip(
                (("JAAA", "AAA CLO"), ("JBBB", "BBB CLO"), ("BKLN", "Lev loans")),
                (theme.BLUE, theme.ORANGE, theme.YELLOW)):
            s_ = clo.get(sym)
            if s_ and s_.ok:
                dd = an.drawdown(s_.col)
                fig.add_trace(go.Scatter(x=dd.index, y=dd, name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.2f}%<extra>"
                                                       f"{label}</extra>"))
        fig.update_layout(title="Total-return drawdown from high (proxy)",
                          yaxis=dict(title="%", ticksuffix="%"))
        ui.chart(fig, height=290)

    with c3:
        s = banks.get("DRTSCILM")
        if s and s.ok:
            d = s.col.tail(80)
            colors = [theme.CRITICAL if v > 0 else theme.GOOD for v in d]
            fig = go.Figure(go.Bar(x=d.index, y=d, marker=dict(color=colors),
                                   hovertemplate="%{y:.1f}%<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1))
            fig.update_layout(
                title="Bank lending standards — SLOOS net % tightening C&I",
                yaxis=dict(title="net %", ticksuffix="%"))
            ui.chart(fig, height=290, legend=False, unified=False)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "Quarterly survey — above zero means banks are tightening. Leads "
                "default rates by roughly three to four quarters.</div>",
                unsafe_allow_html=True)

    # ---- credit vs vol divergence ---------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        hy = head.get("BAMLH0A0HYM2")
        if hy and hy.ok and vix.ok:
            df = pd.concat([(hy.col * 100).rename("hy"), vix.col.rename("vix")],
                           axis=1).dropna()
            # One standardisation, used for both the lines and the quoted gap.
            # Scoring the headline separately from the plot (different ddof,
            # different window) quotes a sigma that matches neither line.
            fig = go.Figure()
            zz = {}
            for col, name, color in (("hy", "HY OAS (z)", theme.ORANGE),
                                     ("vix", "VIX (z)", theme.BLUE)):
                z_ = (df[col] - df[col].mean()) / df[col].std(ddof=0)
                zz[col] = float(z_.iloc[-1])
                fig.add_trace(go.Scatter(x=z_.index, y=z_, name=name,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:+.2f}σ<extra>"
                                                       f"{name}</extra>"))
            gap = zz["hy"] - zz["vix"]
            span = (df.index[-1] - df.index[0]).days / 365.25
            fig.update_layout(
                title=f"Credit vs equity vol — both in z-space · gap {gap:+.2f}σ",
                yaxis=dict(title=f"z-score ({span:.0f}y)", ticksuffix="σ"))
            ui.chart(fig, height=280)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "Both series are standardised so they share one axis. A wide gap — "
                "credit calm while vol is bid, or the reverse — is the divergence "
                "worth acting on.</div>", unsafe_allow_html=True)

    with c2:
        fig = go.Figure()
        avail = {lbl: etfs[sym].col for sym, lbl in CREDIT_ETFS.items()
                 if etfs.get(sym) and etfs[sym].ok}
        if avail:
            idx = an.common_base_index(avail)
            for label, color in zip(idx.columns, theme.SERIES):
                fig.add_trace(go.Scatter(x=idx.index, y=idx[label], name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}<extra>"
                                                       f"{label}</extra>"))
        fig.update_layout(title="Credit ETF total return — shared base = 100",
                          yaxis=dict(title="Index"))
        ui.chart(fig, height=280)

    _risk_premium(head, yields, defaults)
    ui.failures_note([*head.values(), *ladder.values(), *clo.values(), *etfs.values()])
    ui.sources_note([*head.values(), *clo.values()])


def _risk_premium(head, yields, defaults) -> None:
    """Is the spread paying for the risk being taken?

    Two readings a spread level alone cannot give. The implied default rate
    inverts the credit triangle -- PD = OAS / (1 - recovery) -- into the annual
    default rate the market is charging for. Spread share of yield says whether
    the buyer is being paid for credit or simply for duration.
    """
    ui.section("Is the spread paying for the risk?",
               "implied default rate against what actually defaults, and how much of the yield is credit")
    c1, c2 = st.columns(2)

    with c1:
        hy, ig = head.get("BAMLH0A0HYM2"), head.get("BAMLC0A0CM")
        chg = defaults.get("CORBLACBS")
        fig = go.Figure()
        if hy and hy.ok:
            pd_hy = hy.col.apply(an.implied_default_rate)
            fig.add_trace(go.Scatter(x=pd_hy.index, y=pd_hy, name="HY implied default rate",
                                     line=dict(width=2, color=theme.ORANGE),
                                     hovertemplate="%{y:.2f}%<extra>implied</extra>"))
        if chg and chg.ok:
            d = chg.col
            d = d[d.index >= (pd_hy.index[0] if hy and hy.ok else d.index[0])]
            fig.add_trace(go.Scatter(x=d.index, y=d, name="Realised charge-off rate",
                                     line=dict(width=2, color=theme.AQUA),
                                     hovertemplate="%{y:.2f}%<extra>realised</extra>"))
        fig.update_layout(title="HY implied default rate vs what actually defaults",
                          yaxis=dict(title="% per year", ticksuffix="%"))
        ui.chart(fig, height=280)
        if hy and hy.ok:
            imp = an.implied_default_rate(hy.latest())
            real_pd = chg.latest() if chg and chg.ok else float("nan")
            xs = an.excess_over_expected_loss(hy.latest(), real_pd)
            st.markdown(
                f"<div style='font-size:11.5px;color:{theme.INK_2};margin-top:-4px'>"
                f"At 40% recovery, {hy.latest() * 100:.0f}bp implies a "
                f"<b style='color:{theme.INK}'>{imp:.2f}%</b> annual default rate. "
                + (f"Charge-offs are running {real_pd:.2f}%, leaving roughly "
                   f"<b style='color:{theme.INK}'>{xs * 100:.0f}bp</b> of genuine risk "
                   "premium." if real_pd == real_pd else "")
                + "</div>", unsafe_allow_html=True)

    with c2:
        rows = []
        for oas_id, ey_id, name in (("BAMLC0A0CM", "BAMLC0A0CMEY", "IG"),
                                    ("BAMLH0A0HYM2", "BAMLH0A0HYM2EY", "HY")):
            o, y = head.get(oas_id), yields.get(ey_id)
            if o and y and o.ok and y.ok:
                share = (o.col / y.col * 100).dropna()
                rows.append((name, share))
        if rows:
            fig = go.Figure()
            for (name, share), color in zip(rows, (theme.BLUE, theme.ORANGE)):
                fig.add_trace(go.Scatter(x=share.index, y=share, name=name,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}%<extra>"
                                                       f"{name}</extra>"))
            fig.update_layout(title="Spread share of yield — credit vs duration",
                              yaxis=dict(title="OAS / effective yield", ticksuffix="%"))
            ui.chart(fig, height=280)
            bits = " · ".join(f"{n} {s.iloc[-1]:.0f}%" for n, s in rows)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                f"{bits}. A low share means you are mostly being paid for duration, "
                "not for taking credit risk.</div>", unsafe_allow_html=True)
