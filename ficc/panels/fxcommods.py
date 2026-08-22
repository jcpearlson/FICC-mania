"""FX and commodities.

Two things drive the layout. First, FX spot comes from Yahoo, never from
FRED's DEX* series -- those run about five business days behind the H.10
release, so pairing them with a T+1 rate series on one chart manufactures
divergence that isn't there. Second, the USDJPY block is three stacked panels
rather than one: spot against its rate-implied fair value, the residual, and
the *rolling beta*. A collapsing beta -- the spread no longer driving spot --
is a better warning than a large residual, because it means the usual
relationship has stopped working.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import theme, ui
from ..sources import fred, market, mof

FX = {"DX-Y.NYB": "DXY", "JPY=X": "USDJPY", "EURUSD=X": "EURUSD",
      "GBPUSD=X": "GBPUSD", "AUDUSD=X": "AUDUSD", "CNH=X": "USDCNH",
      "MXN=X": "USDMXN"}
METALS = {"GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper",
          "PL=F": "Platinum", "ALI=F": "Aluminium"}
ENERGY = {"CL=F": "WTI", "BZ=F": "Brent", "NG=F": "Henry Hub",
          "RB=F": "RBOB", "HO=F": "Heating oil"}
AGS = {"ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans"}
VOLS = {"^GVZ": "Gold vol", "^OVX": "Oil vol"}


@st.cache_data(ttl=900, show_spinner=False)
def _load():
    fx = market.basket(FX, period="3y")
    metals = market.basket(METALS, period="3y")
    energy = market.basket(ENERGY, period="2y")
    ags = market.basket(AGS, period="2y")
    vols = market.basket(VOLS, period="2y")
    wti_curve = market.commodity_curve("CL", 9, "WTI")
    ng_curve = market.commodity_curve("NG", 9, "Henry Hub")
    real = fred.get("DFII10", "10y TIPS real yield")
    ust10 = fred.get("DGS10", "10y UST")
    jgb = mof.curve()
    return fx, metals, energy, ags, vols, wti_curve, ng_curve, real, ust10, jgb


def render() -> None:
    fx, metals, energy, ags, vols, wti_curve, ng_curve, real, ust10, jgb = _load()

    # ---- tiles ---------------------------------------------------------
    tiles = []
    for sym, dp in (("DX-Y.NYB", 2), ("JPY=X", 2)):
        s = fx.get(sym)
        if s and s.ok:
            chg = s.change()
            pct = (chg / s.latest() * 100) if chg and s.latest() else None
            tiles.append(ui.tile(FX[sym], s.latest(), s, dp=dp,
                                 delta=pct, delta_unit="%"))
    for sym in ("GC=F", "HG=F"):
        s = metals.get(sym)
        if s and s.ok:
            chg = s.change()
            pct = (chg / s.latest() * 100) if chg and s.latest() else None
            z = an.zscore(s.col, 3)
            tiles.append(ui.tile(METALS[sym], s.latest(), s, dp=2,
                                 delta=pct, delta_unit="%",
                                 sub=f"{z.window_label} pct {z.pct:.0f}" if z else ""))
    w = energy.get("CL=F")
    if w and w.ok:
        shape = market.curve_shape(wti_curve.frame, 6) if wti_curve.ok else None
        sub = (f"{shape:+.0f}% ann. "
               f"{'backwardation' if shape and shape > 0 else 'contango'}") if shape else ""
        chg = w.change()
        tiles.append(ui.tile("WTI", w.latest(), w, dp=2,
                             delta=(chg / w.latest() * 100) if chg else None,
                             delta_unit="%", sub=sub))
    ui.tile_row(tiles[:6])

    # ---- USDJPY vs rate differential -----------------------------------
    ui.section("USDJPY and the rate differential",
               "spot vs fair value, the residual, and whether the relationship still holds")
    jpy = fx.get("JPY=X")
    if jpy and jpy.ok and ust10.ok and jgb.ok and "10Y" in jgb.frame.columns:
        df = pd.concat([
            jpy.col.rename("spot"),
            ust10.col.rename("ust"),
            jgb.frame["10Y"].rename("jgb"),
        ], axis=1).ffill().dropna()
        df["diff"] = (df["ust"] - df["jgb"]) * 100  # bp
        df = df.tail(756)
        slope, intercept, r2 = an.beta(df["spot"], df["diff"], 250)
        df["fair"] = slope * df["diff"] + intercept
        df["resid"] = df["spot"] - df["fair"]

        # Rolling beta: yen per 100bp of spread.
        roll = []
        for i in range(len(df)):
            if i < 250:
                roll.append(float("nan"))
            else:
                b, _, _ = an.beta(df["spot"].iloc[i - 250:i + 1],
                                  df["diff"].iloc[i - 250:i + 1], 250)
                roll.append(b * 100)
        df["beta100"] = roll

        c1, c2, c3 = st.columns(3)
        with c1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.index, y=df["spot"], name="USDJPY spot",
                                     line=dict(width=2, color=theme.BLUE),
                                     hovertemplate="%{y:.2f}<extra>spot</extra>"))
            fig.add_trace(go.Scatter(x=df.index, y=df["fair"], name="Rate-implied fair value",
                                     line=dict(width=2, color=theme.ORANGE, dash="dash"),
                                     hovertemplate="%{y:.2f}<extra>fair</extra>"))
            fig.update_layout(title=f"USDJPY vs fair value · R² {r2:.2f}",
                              yaxis=dict(title="USDJPY"))
            ui.chart(fig, height=280)
        with c2:
            rz = an.zscore(df["resid"], 2)
            colors = [theme.CRITICAL if v > 0 else theme.BLUE for v in df["resid"]]
            fig = go.Figure(go.Bar(x=df.index, y=df["resid"], marker=dict(color=colors),
                                   hovertemplate="%{y:+.2f} yen<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1))
            fig.update_layout(
                title=f"Residual · {df['resid'].iloc[-1]:+.2f} yen"
                      + (f" ({rz.z:+.1f}σ)" if rz else ""),
                yaxis=dict(title="yen vs fair value"))
            ui.chart(fig, height=280, legend=False, unified=False)
        with c3:
            fig = go.Figure(go.Scatter(
                x=df.index, y=df["beta100"], line=dict(width=2, color=theme.VIOLET),
                name="beta", hovertemplate="%{y:.1f} yen/100bp<extra></extra>"))
            fig.update_layout(
                title=f"Rolling beta · {df['beta100'].iloc[-1]:.1f} yen per 100bp",
                yaxis=dict(title="yen per 100bp"))
            ui.chart(fig, height=280, legend=False)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "A collapsing beta means the rate spread has stopped driving spot — "
                "intervention, a BoJ shift, or flow dominance. That is a louder "
                "warning than a large residual.</div>", unsafe_allow_html=True)

    # ---- FX complex -----------------------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for (sym, label), color in zip(FX.items(), theme.SERIES):
            s = fx.get(sym)
            if s and s.ok:
                d = s.col.dropna().tail(504)
                fig.add_trace(go.Scatter(x=d.index, y=d / d.iloc[0] * 100, name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}<extra>"
                                                       f"{label}</extra>"))
        fig.update_layout(title="FX complex — indexed to 100 (up = USD stronger for USDJPY/CNH/MXN)",
                          yaxis=dict(title="Index"))
        ui.chart(fig, height=300)
    with c2:
        # Gold vs real yields: the relationship, and where it has broken.
        g = metals.get("GC=F")
        if g and g.ok and real.ok:
            df = pd.concat([g.col.rename("gold"), real.col.rename("real")],
                           axis=1).ffill().dropna().tail(756)
            gspan = (df.index[-1] - df.index[0]).days / 365.25
            fig = go.Figure(go.Scatter(
                x=df["real"], y=df["gold"], mode="markers",
                marker=dict(size=5, color=list(range(len(df))),
                            colorscale=theme.SEQ_BLUE, showscale=False),
                name="daily", hovertemplate="real %{x:.2f}% · gold %{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[df["real"].iloc[-1]], y=[df["gold"].iloc[-1]], mode="markers",
                marker=dict(size=13, color=theme.ORANGE,
                            line=dict(width=2, color=theme.SURFACE)),
                name="today", hovertemplate="today<extra></extra>"))
            fig.update_layout(
                title=f"Gold vs 10y real yield — {gspan:.0f}y, darker = more recent",
                xaxis=dict(title="10y TIPS real yield (%)", ticksuffix="%"),
                yaxis=dict(title="Gold ($/oz)"))
            ui.chart(fig, height=300, unified=False)

    # ---- commodity curves & ratios --------------------------------------
    ui.section("Commodity curves & macro ratios",
               "curve shape leads price; the copper/gold-vs-yields gap is the growth signal")
    c1, c2, c3 = st.columns(3)
    with c1:
        fig = go.Figure()
        for cur, name, color in ((wti_curve, "WTI", theme.BLUE),
                                 (ng_curve, "Henry Hub", theme.ORANGE)):
            if cur.ok:
                d = cur.frame
                base = float(d["price"].iloc[0])
                fig.add_trace(go.Scatter(
                    x=d.index, y=d["price"] / base * 100, name=name,
                    mode="lines+markers", line=dict(width=2.4, color=color),
                    marker=dict(size=8),
                    hovertemplate="%{x|%b %y}: %{y:.1f}<extra>" + name + "</extra>"))
        fig.update_layout(
            title="Energy forward curves — front contract = 100",
            yaxis=dict(title="Index vs front"), xaxis=dict(title="Delivery month"))
        ui.chart(fig, height=290)
        if wti_curve.ok:
            sh = market.curve_shape(wti_curve.frame, 6)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                f"WTI 6-month slope {sh:+.1f}% annualised — "
                f"{'backwardation, physically tight' if sh > 0 else 'contango, well supplied'}."
                "</div>", unsafe_allow_html=True)
    with c2:
        cu, au = metals.get("HG=F"), metals.get("GC=F")
        if cu and au and cu.ok and au.ok and ust10.ok:
            r = an.ratio(cu.col, au.col, "cg").dropna()
            df = pd.concat([r, ust10.col.rename("y10")], axis=1).ffill().dropna().tail(756)
            cspan = (df.index[-1] - df.index[0]).days / 365.25
            zc = (df["cg"] - df["cg"].mean()) / df["cg"].std()
            zy = (df["y10"] - df["y10"].mean()) / df["y10"].std()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.index, y=zc, name="Copper/gold (z)",
                                     line=dict(width=2, color=theme.ORANGE),
                                     hovertemplate="%{y:+.2f}σ<extra>Cu/Au</extra>"))
            fig.add_trace(go.Scatter(x=df.index, y=zy, name="10y UST (z)",
                                     line=dict(width=2, color=theme.BLUE),
                                     hovertemplate="%{y:+.2f}σ<extra>10y</extra>"))
            gap = float(zc.iloc[-1] - zy.iloc[-1])
            fig.update_layout(
                title=f"Copper/gold vs 10y — divergence {gap:+.2f}σ",
                yaxis=dict(title=f"z-score ({cspan:.0f}y)", ticksuffix="σ"))
            ui.chart(fig, height=290)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "Both standardised onto one axis. The <em>gap</em> is the signal: "
                "copper/gold is a growth proxy, so a wide divergence from yields "
                "means one of the two is mispricing growth.</div>",
                unsafe_allow_html=True)
    with c3:
        au, ag = metals.get("GC=F"), metals.get("SI=F")
        if au and ag and au.ok and ag.ok:
            r = an.ratio(au.col, ag.col, "gs").dropna().tail(756)
            z = an.zscore(r, 3)
            fig = go.Figure(go.Scatter(x=r.index, y=r, line=dict(width=2, color=theme.YELLOW),
                                       name="Gold/silver",
                                       hovertemplate="%{y:.1f}<extra></extra>"))
            fig.update_layout(
                title=f"Gold/silver ratio · {r.iloc[-1]:.1f}"
                      + (f" ({z.verdict_width}, {z.window_label})" if z else ""),
                yaxis=dict(title="ratio"))
            ui.chart(fig, height=290, legend=False)

    # ---- complex performance -------------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        allc = {**metals, **energy, **ags}
        rows = []
        for sym, s in allc.items():
            if s and s.ok:
                d = s.col.dropna()
                lbl = {**METALS, **ENERGY, **AGS}.get(sym, sym)
                for name, off in (("1d", 1), ("1w", 5), ("1m", 21), ("3m", 63)):
                    if len(d) > off:
                        rows.append({"asset": lbl, "period": name,
                                     "chg": (float(d.iloc[-1]) / float(d.iloc[-1 - off]) - 1) * 100})
        if rows:
            piv = pd.DataFrame(rows).pivot(index="asset", columns="period", values="chg")
            piv = piv[[c for c in ("1d", "1w", "1m", "3m") if c in piv.columns]]
            fig = go.Figure(go.Heatmap(
                z=piv.values, x=piv.columns, y=piv.index,
                colorscale=theme.DIVERGING, zmid=0, xgap=2, ygap=2,
                colorbar=dict(title=dict(text="%", side="right"), thickness=10,
                              len=.85, outlinewidth=0,
                              tickfont=dict(color=theme.MUTED, size=10)),
                hovertemplate="%{y} · %{x}: %{z:+.2f}%<extra></extra>"))
            fig.update_layout(title="Commodity performance (%)")
            ui.chart(fig, height=330, legend=False, unified=False)
    with c2:
        fig = go.Figure()
        for (sym, label), color in zip(VOLS.items(), (theme.YELLOW, theme.ORANGE)):
            s = vols.get(sym)
            if s and s.ok:
                d = s.col.dropna().tail(504)
                fig.add_trace(go.Scatter(x=d.index, y=d, name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}<extra>"
                                                       f"{label}</extra>"))
        fig.update_layout(title="Commodity implied vol", yaxis=dict(title="Index"))
        ui.chart(fig, height=330)
        st.markdown(
            f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
            "CBOE FX vol indices (EVZ, JYVIX, BPVIX) are not retrievable through "
            "this data path — see BACKLOG.md.</div>", unsafe_allow_html=True)

    ui.failures_note([*fx.values(), *metals.values(), *energy.values(), *vols.values()])
    ui.sources_note([*metals.values(), real, jgb])
