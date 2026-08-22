"""The one-page glance -- terminal density, built for a portrait monitor.

The design premise: on a vertical screen you have ~1000px of width and a lot of
height, and the thing that makes a glance a *glance* is how many instruments
are visible before you scroll. So the page leads with a monitor table -- around
thirty rows, each with level, four lookback changes, position in its own range,
a sparkline and its observation date -- rather than with big stat tiles. Six
tiles occupy the vertical space that thirty table rows do, and carry a fifth of
the information.

Charts come after, as small multiples two across, because once the table has
told you *what* moved, the charts only need to show *shape*: a curve, a path, a
level against its history. None of that needs 340px of height.

Order is still the design: the further down something sits, the less often it
changes the answer to "how is fixed income doing right now".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import monitor, theme, ui
from ..sources import market, mof, treasury
from . import credit as credit_panel
from . import overview as overview_panel
from . import rates as rates_panel

H = 190          # small-multiple height
H_TALL = 230     # for the curve, which earns a little more


def render(years: list[int]) -> None:
    ui.dense_css()
    st.markdown(monitor.CSS, unsafe_allow_html=True)
    st.markdown('<div class="ficc-dense">', unsafe_allow_html=True)

    # Cache hits, not refetches.
    (ust, jgb, sofr_fwd, ff, sofr_on, effr, sofr_avg,
     extras, move, real) = rates_panel._load(years)
    head, ladder, yields, banks, clo, etfs, vix, defaults = credit_panel._load()
    f, slow, mkt = overview_panel._load()
    # The shared overview basket has no yen, and the yen is the whole point of
    # the global block -- pull it here (cached, one symbol).
    jpy = _usdjpy()

    hy, ig = head.get("BAMLH0A0HYM2"), head.get("BAMLC0A0CM")
    bb, ccc = ladder.get("BAMLH0A1HYBB"), ladder.get("BAMLH0A3HYC")
    long_ust = extras.get("DGS10")
    iorb = extras.get("IORB")

    # ------------------------------------------------------ status strip
    comp = overview_panel._components(f, slow, mkt)
    valid = {k: v for k, v in comp.items() if v == v}
    score = (sum(overview_panel.WEIGHTS[k] * v for k, v in valid.items())
             / sum(overview_panel.WEIGHTS[k] for k in valid)) if valid else float("nan")
    _, label = an.regime_score({"s": score})
    band = (theme.CRITICAL if score <= -0.5 else theme.SERIOUS if score <= -0.15
            else theme.INK_2 if score < 0.15 else theme.GOOD)

    def _d(v, unit="bp"):
        """Level plus its 1-day change -- a level alone cannot say 'selloff'."""
        if v is None or v != v:
            return ""
        c = theme.delta_color(v, mode="rates")
        return (f"<span style='font-size:10.5px;color:{c};margin-left:5px'>"
                f"{v:+.0f}{unit}</span>")

    items = [("Regime", f"{score:+.2f} {label}", band)]
    if ust.ok:
        items.append(("10Y", f"{ust.frame['10 Yr'].iloc[-1]:.2f}%"
                      + _d(an.pct_change_bp(ust.frame["10 Yr"], 1)), theme.INK))
        sl = an.spread(ust.frame, "10 Yr", "2 Yr")
        items.append(("2s10s", f"{sl.iloc[-1]:.0f}bp"
                      + _d(float(sl.iloc[-1] - sl.iloc[-2]) if len(sl) > 1 else None),
                      theme.INK))
    if hy and hy.ok:
        items.append(("HY OAS", f"{hy.latest() * 100:.0f}bp"
                      + _d(an.pct_change_bp(hy.col, 1)), theme.INK))
    if bb and ccc and bb.ok and ccc.ok:
        q = ((ccc.col - bb.col).dropna()) * 100
        zq = an.zscore(q, 5)
        qc = theme.SERIOUS if zq and (zq.pct >= 90 or zq.pct <= 10) else theme.INK
        items.append(("CCC−BB", f"{q.iloc[-1]:.0f}bp"
                      + _d(float(q.iloc[-1] - q.iloc[-2]) if len(q) > 1 else None), qc))
    if ff.ok and effr.ok:
        pr = (float(ff.frame["implied_rate"].iloc[-1]) - effr.latest("percentRate")) * 100
        items.append((f"Priced {ff.frame.index[-1]:%b%y}", f"{pr:+.0f}bp",
                      theme.RED_RATE if pr > 0 else theme.BLUE_RATE))
    ui.strip(items)

    # ---------------------------------------------------- monitor table
    R = monitor.row_from
    rates_rows = []
    if ust.ok:
        # Maturity order, shortest first -- the 3m bill anchors the ladder, so
        # appending it after the 30y (as this once did) breaks the one ordering
        # a rates reader relies on.
        rates_rows.append(R(ust, "3m bill", col="3 Mo", mode="rates"))
        for t in ("2 Yr", "5 Yr", "10 Yr", "30 Yr"):
            if t in ust.frame.columns:
                rates_rows.append(R(ust, f"UST {t.replace(' Yr', 'Y')}",
                                    col=t, mode="rates"))

    curve_rows = []
    if ust.ok:
        for name, lo, hi in (("2s10s", "2 Yr", "10 Yr"), ("5s30s", "5 Yr", "30 Yr"),
                             ("3m10y", "3 Mo", "10 Yr")):
            if lo in ust.frame.columns and hi in ust.frame.columns:
                curve_rows.append(_slope_row(ust, name, lo, hi))

    front_rows = [
        R(sofr_on, "SOFR o/n", col="percentRate", mode="rates"),
        R(effr, "EFFR", col="percentRate", mode="rates"),
        R(iorb, "IORB", mode="rates"),
    ]
    if sofr_on.ok and iorb and iorb.ok:
        last = sofr_on.frame.index.max()
        d = pd.concat([sofr_on.frame["percentRate"].rename("s"),
                       iorb.col.rename("i")], axis=1).ffill()
        d = d[d.index <= last].dropna()
        front_rows.append(monitor.Row(
            "SOFR − IORB", (d["s"] - d["i"]) * 100,
            float((d["s"] - d["i"]).iloc[-1] * 100), unit="bp", dp=0,
            mode="risk", chg_unit="pts", chg_dp=0, as_of=sofr_on.as_of))

    infl_rows = [
        R(extras.get("T10YIE"), "10y breakeven", mode="rates"),
        R(extras.get("T5YIFR"), "5y5y fwd infl", mode="rates"),
        R(extras.get("DFII10"), "10y real yield", mode="rates"),
        R(extras.get("THREEFYTP10"), "10y term premium", mode="rates"),
    ]

    credit_rows = [
        R(ig, "IG OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(ladder.get("BAMLC0A4CBBB"), "BBB OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(hy, "HY OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(bb, "BB OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(ccc, "CCC OAS", mode="risk", unit="bp", dp=0, scale=100),
    ]
    if bb and ccc and bb.ok and ccc.ok:
        q = (ccc.col - bb.col).dropna() * 100
        credit_rows.append(monitor.Row("CCC − BB dispersion", q, float(q.iloc[-1]),
                                       unit="bp", dp=0, mode="risk",
                                       chg_unit="pts", chg_dp=0, as_of=ccc.as_of))
    credit_rows += [
        R(head.get("BAMLEMCBPIOAS"), "EM corp OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(head.get("BAMLHE00EHYIOAS"), "Euro HY OAS", mode="risk", unit="bp", dp=0, scale=100),
    ]

    vol_rows = [
        R(move, "MOVE (rate vol)", mode="risk", unit="", dp=1, chg_unit="pts"),  # noqa: E501
        R(vix, "VIX", mode="risk", unit="", dp=2, chg_unit="pts"),
        R(slow.get("NFCI"), "Chicago Fed NFCI", mode="risk", unit="", dp=2, chg_unit="pts"),
    ]

    global_rows = []
    if jgb.ok:
        for t in ("2Y", "10Y", "30Y"):
            if t in jgb.frame.columns:
                global_rows.append(R(jgb, f"JGB {t}", col=t, mode="rates"))
    if long_ust and long_ust.ok and jgb.ok and "10Y" in jgb.frame.columns:
        d = pd.concat([long_ust.col.rename("u"), jgb.frame["10Y"].rename("j")],
                      axis=1).ffill().dropna()
        spd = (d["u"] - d["j"]) * 100
        global_rows.append(monitor.Row("10y UST − JGB", spd, float(spd.iloc[-1]),
                                       unit="bp", dp=0, mode="rates",
                                       chg_unit="pts", chg_dp=0,
                                       as_of=long_ust.as_of))
    if jpy is not None and jpy.ok:
        global_rows.append(R(jpy, "USDJPY", mode="perf", unit="", dp=2, chg_unit="%"))
    dxy = mkt.get("DX-Y.NYB")
    if dxy and dxy.ok:
        global_rows.append(R(dxy, "DXY", mode="perf", unit="", dp=2, chg_unit="%"))

    # Credit sits third, not fifth: after the curve and its slopes, credit is
    # the next thing any fixed-income desk looks at, and it is the group most
    # likely to be telling you something. Funding, inflation and vol are
    # context blocks; Global stays last.
    st.markdown(monitor.render_html([
        ("US Treasuries", rates_rows),
        ("Curve", curve_rows),
        ("Credit", credit_rows),
        ("Front end & funding", front_rows),
        ("Inflation & term premium", infl_rows),
        ("Volatility & conditions", vol_rows),
        ("Global", global_rows),
    ]), unsafe_allow_html=True)

    st.markdown(
        f"<div style='font-size:9.5px;color:{theme.MUTED};margin-top:6px;line-height:1.6'>"
        f"One convention throughout: <span style='color:{theme.RED_RATE}'>red</span> "
        f"= the number rose, <span style='color:{theme.BLUE_RATE}'>blue</span> = it "
        "fell — for every row, and for the sparkline too. Not good/bad, because "
        "tighter spreads are only good if you are long. Range is each series "
        "against its own available history; "
        f"<span style='color:{theme.SERIOUS}'>amber</span> marks past the 10th/90th "
        "percentile. 'As of' is the source's observation date, not the pull time."
        "</div>", unsafe_allow_html=True)

    # ------------------------------------------------------- the charts
    ui.section("Curves", "US, Japan, and the forward path the market is pricing")
    c1, c2 = st.columns([1.15, 1])
    with c1:
        fig = go.Figure()
        if ust.ok:
            snap = an.curve_snapshot(ust.frame, treasury.TENORS, offsets=(0,))
            cur = snap[snap.offset == 0]
            fig.add_trace(go.Scatter(x=cur["years"], y=cur["yield"], name="UST",
                                     mode="lines+markers",
                                     line=dict(width=2.2, color=theme.BLUE),
                                     marker=dict(size=6),
                                     hovertemplate="%{y:.2f}%<extra>UST</extra>"))
        if sofr_fwd.ok:
            fw = sofr_fwd.frame
            fig.add_trace(go.Scatter(x=fw["years_fwd"], y=fw["implied_rate"],
                                     name="SOFR fwd", mode="lines+markers",
                                     line=dict(width=2.2, color=theme.ORANGE),
                                     marker=dict(size=6),
                                     hovertemplate="%{y:.2f}%<extra>SOFR fwd</extra>"))
        if jgb.ok:
            jr = jgb.frame.iloc[-1]
            xs = [mof.TENORS[c] for c in jgb.frame.columns
                  if c in mof.TENORS and pd.notna(jr[c])]
            ys = [float(jr[c]) for c in jgb.frame.columns
                  if c in mof.TENORS and pd.notna(jr[c])]
            fig.add_trace(go.Scatter(x=xs, y=ys, name="JGB", mode="lines+markers",
                                     line=dict(width=2.2, color=theme.AQUA),
                                     marker=dict(size=6),
                                     hovertemplate="%{y:.2f}%<extra>JGB</extra>"))
        fig.update_layout(
            title="Yield curves — US & Japan",
            xaxis=dict(type="log", tickvals=[0.25, 1, 2, 5, 10, 30],
                       ticktext=["3m", "1y", "2y", "5y", "10y", "30y"]),
            yaxis=dict(ticksuffix="%"))
        ui.chart(fig, height=H_TALL, compact=True)
    with c2:
        if ust.ok:
            ch = an.curve_changes(ust.frame, treasury.TENORS,
                                  {"1D": 1, "1W": 5, "1M": 21, "3M": 63})
            cols = [c for c in ("1D", "1W", "1M", "3M") if c in ch.columns]
            raw = ch[cols].T.values.astype(float)
            # Normalise each row to its own scale. A single scale spanning the
            # 3M range renders the 1D row -- the one a trader reads first --
            # almost entirely neutral. Hover still shows true basis points.
            norm = np.zeros_like(raw)
            for i in range(raw.shape[0]):
                m = np.nanmax(np.abs(raw[i])) if np.isfinite(raw[i]).any() else 0
                norm[i] = raw[i] / m if m else 0
            labels = [t.replace("1.5 Month", "6 Wk").replace(" Mo", "m")
                       .replace(" Yr", "y") for t in ch["tenor"]]
            fig = go.Figure(go.Heatmap(
                z=norm, x=labels, y=cols, customdata=raw,
                colorscale=theme.DIVERGING, zmid=0, zmin=-1, zmax=1,
                xgap=1, ygap=1, showscale=False,
                hovertemplate="%{x} · %{y}: %{customdata:+.1f} bp<extra></extra>"))
            fig.update_layout(title="Change by tenor — each row scaled to itself",
                              yaxis=dict(autorange="reversed"),
                              xaxis=dict(tickangle=-60))
            ui.chart(fig, height=H_TALL, legend=False, unified=False, compact=True)
            spans = " · ".join(
                f"{c} ±{np.nanmax(np.abs(ch[c].values)):.0f}bp"
                for c in cols if np.isfinite(ch[c].values).any())
            st.markdown(
                f"<div style='font-size:9.5px;color:{theme.MUTED};margin-top:-8px'>"
                "Colour is intensity <em>within each row</em>, so a strong 1D cell "
                "means the biggest move of that day, not a big move outright. "
                f"Row maxima: {spans}. Hover for basis points.</div>",
                unsafe_allow_html=True)

    # Credit leads this section and sits on the left: the eye lands left-first
    # on a portrait screen, and unlike the Fed path -- already summarised in the
    # status strip and in three front-end table rows -- credit has no numeric
    # stand-in above.
    ui.section("Credit, policy & funding", "")
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for s_, color in ((ig, theme.BLUE), (hy, theme.ORANGE)):
            if s_ and s_.ok:
                d = s_.col * 100
                fig.add_trace(go.Scatter(x=d.index, y=d,
                                         name=s_.label.replace(" OAS", ""),
                                         line=dict(width=1.8, color=color),
                                         hovertemplate="%{y:.0f}bp<extra>"
                                                       f"{s_.label}</extra>"))
        # Log scale, not a second axis: IG near 90bp against HY near 275bp on a
        # shared linear axis flattens IG into a dead straight line. A log axis
        # makes proportional moves in both legible on ONE axis -- a dual axis
        # would invite exactly the false comparison it appears to solve.
        fig.update_layout(title="IG & HY OAS (log scale)",
                          yaxis=dict(title="bp", type="log"))
        ui.chart(fig, height=H, compact=True)
    with c2:
        if bb and ccc and bb.ok and ccc.ok:
            q = ((ccc.col - bb.col).dropna()) * 100
            z = an.zscore(q, 5)
            fig = go.Figure(go.Scatter(x=q.index, y=q, name="CCC−BB",
                                       line=dict(width=1.8, color=theme.RED_RATE),
                                       hovertemplate="%{y:.0f}bp<extra></extra>"))
            fig.update_layout(
                title=f"CCC−BB dispersion · {q.iloc[-1]:.0f}bp"
                      + (f" ({z.verdict_width})" if z else ""),
                yaxis=dict(title="bp"))
            ui.chart(fig, height=H, legend=False, compact=True)

    c1, c2 = st.columns(2)
    with c1:
        if ff.ok:
            d = ff.frame
            fig = go.Figure(go.Scatter(
                x=d.index, y=d["implied_rate"], mode="lines+markers",
                line=dict(width=2, color=theme.VIOLET), marker=dict(size=5),
                name="Implied EFFR",
                hovertemplate="%{x|%b %Y}: %{y:.3f}%<extra></extra>"))
            if effr.ok:
                fig.add_hline(y=effr.latest("percentRate"),
                              line=dict(color=theme.MUTED, width=1, dash="dot"))
            fig.update_layout(title="Fed path — fed funds futures",
                              yaxis=dict(ticksuffix="%"))
            ui.chart(fig, height=H, legend=False, compact=True)
    with c2:
        if sofr_on.ok and iorb and iorb.ok:
            last = sofr_on.frame.index.max()
            d = pd.concat([sofr_on.frame["percentRate"].rename("s"),
                           iorb.col.rename("i")], axis=1).ffill()
            d = d[d.index <= last].dropna()
            sp_ = ((d["s"] - d["i"]) * 100).tail(400)
            fig = go.Figure(go.Scatter(x=sp_.index, y=sp_,
                                       line=dict(width=1.8, color=theme.MAGENTA),
                                       name="SOFR−IORB",
                                       hovertemplate="%{y:+.1f}bp<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1, dash="dot"))
            fig.update_layout(
                title=f"Reserve scarcity — SOFR−IORB · {sp_.iloc[-1]:+.0f}bp",
                yaxis=dict(title="bp"))
            ui.chart(fig, height=H, legend=False, compact=True)

    ui.section("Carry & global linkage", "")
    c1, c2 = st.columns([1.15, 1])
    with c1:
        front = None
        if ust.ok and "3 Mo" in ust.frame.columns:
            front = float(ust.frame["3 Mo"].iloc[-1])
        elif sofr_on.ok:
            front = sofr_on.latest("percentRate")
        if ust.ok and front is not None:
            levels = {k: float(v) for k, v in ust.frame.iloc[-1].items() if pd.notna(v)}
            cr = an.carry_rolldown(treasury.TENORS, levels, front, 0.25)
            cr = cr[cr["years"] >= 1]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=cr["tenor"], y=cr["carry_bp"], name="Carry",
                                 marker=dict(color=theme.BLUE),
                                 hovertemplate="%{y:.1f}bp<extra>carry</extra>"))
            fig.add_trace(go.Bar(x=cr["tenor"], y=cr["roll_bp"], name="Roll",
                                 marker=dict(color=theme.AQUA),
                                 hovertemplate="%{y:.1f}bp<extra>roll</extra>"))
            # Markers, not a line: breakeven runs 2-14bp against carry bars up
            # to 50bp, so as a line it lies flat on the baseline and reads as
            # chart furniture rather than as the number that matters.
            fig.add_trace(go.Scatter(
                x=cr["tenor"], y=cr["breakeven_bp"], name="Breakeven",
                mode="markers+text", marker=dict(size=10, color=theme.ORANGE,
                                                 symbol="diamond",
                                                 line=dict(width=1.5,
                                                           color=theme.SURFACE)),
                text=[f"{v:.0f}" for v in cr["breakeven_bp"]],
                textposition="top center",
                textfont=dict(size=8.5, color=theme.ORANGE),
                hovertemplate="%{y:.1f}bp<extra>breakeven</extra>"))
            fig.update_layout(barmode="relative", yaxis=dict(title="bp"),
                              title=f"3m carry & roll, financed at {front:.2f}%")
            ui.chart(fig, height=H, unified=False, compact=True)
    with c2:
        if jpy is not None and jpy.ok and long_ust and long_ust.ok and jgb.ok:
            dfb = pd.concat([jpy.col.rename("spot"), long_ust.col.rename("ust"),
                             jgb.frame["10Y"].rename("jgb")], axis=1).ffill().dropna()
            dfb["diff"] = (dfb["ust"] - dfb["jgb"]) * 100
            dfb = dfb.tail(756)
            roll = [np.nan if i < 250 else
                    an.beta(dfb["spot"].iloc[i - 250:i + 1],
                            dfb["diff"].iloc[i - 250:i + 1], 250)[0] * 100
                    for i in range(len(dfb))]
            dfb["b"] = roll
            fig = go.Figure(go.Scatter(x=dfb.index, y=dfb["b"], name="beta",
                                       line=dict(width=1.8, color=theme.VIOLET),
                                       hovertemplate="%{y:.1f} yen/100bp<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1, dash="dot"))
            fig.update_layout(
                title=f"USDJPY beta to UST−JGB · {dfb['b'].iloc[-1]:.1f} yen/100bp",
                yaxis=dict(title="yen/100bp"))
            ui.chart(fig, height=H, legend=False, compact=True)

    ui.sources_note([ust, jgb, sofr_fwd, hy, move])
    st.markdown("</div>", unsafe_allow_html=True)


def _slope_row(ust, name: str, lo: str, hi: str):
    """A curve slope as a monitor row. Already in bp, so changes are whole bp."""
    ser = an.spread(ust.frame, hi, lo)
    return monitor.Row(name, ser, float(ser.iloc[-1]), unit="bp", dp=0,
                       mode="rates", chg_unit="pts", chg_dp=0, as_of=ust.as_of)


@st.cache_data(ttl=900, show_spinner=False)
def _usdjpy():
    return market.quote("JPY=X", "USDJPY", period="5y")
