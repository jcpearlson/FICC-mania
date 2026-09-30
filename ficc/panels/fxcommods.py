"""FX and commodities.

Spot quotes use source session dates. Relationship charts describe fitted
sensitivities and residuals; they do not establish causality or fair value.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import theme, ui
from ..sources import cftc, fred, market, mof

FX = {"DX-Y.NYB": "DXY", "JPY=X": "USDJPY", "EURUSD=X": "EURUSD",
      "GBPUSD=X": "GBPUSD", "AUDUSD=X": "AUDUSD", "CNH=X": "USDCNH",
      "MXN=X": "USDMXN"}
METALS = {"GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper",
          "PL=F": "Platinum", "ALI=F": "Aluminium"}
ENERGY = {"CL=F": "WTI", "BZ=F": "Brent", "NG=F": "Henry Hub",
          "RB=F": "RBOB", "HO=F": "Heating oil"}
AGS = {"ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans"}
VOLS = {"^GVZ": "Gold vol", "^OVX": "Oil vol"}


@st.cache_data(ttl=120, show_spinner=False)
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


@st.cache_data(ttl=3600, show_spinner=False)
def _load_cot():
    return {code: cftc.positioning(code) for code in ("097741", "099741")}


def render() -> None:
    fx, metals, energy, ags, vols, wti_curve, ng_curve, real, ust10, jgb = _load()
    ui.quality_summary([(s, None) for s in (*fx.values(), *metals.values(), *energy.values(),
                        *ags.values(), *vols.values(), real, ust10)]
                       + [(wti_curve, "price"), (ng_curve, "price"), (jgb, "10Y")])

    # ---- tiles ---------------------------------------------------------
    tiles = []
    for sym, dp in (("DX-Y.NYB", 2), ("JPY=X", 2)):
        s = fx.get(sym)
        if s and s.ok:
            tiles.append(ui.tile(FX[sym], s.latest(), s, dp=dp,
                                 delta=an.pct_return(s.col), delta_unit="%"))
    for sym in ("GC=F", "HG=F"):
        s = metals.get(sym)
        if s and s.ok:
            pct = an.pct_return(s.col)
            z = an.zscore(s.col, 3)
            tiles.append(ui.tile(METALS[sym], s.latest(), s, dp=2,
                                 delta=pct, delta_unit="%",
                                 sub=f"{z.window_label} pct {z.pct:.0f}" if z else ""))
    w = energy.get("CL=F")
    if w and w.ok:
        shape = market.curve_shape(wti_curve.frame, 6) if wti_curve.ok else None
        sub = (f"{shape:+.0f}% ann. {'backwardation' if shape > 0 else 'contango'}"
               if shape is not None and shape == shape else "")
        tiles.append(ui.tile("WTI", w.latest(), w, dp=2,
                             delta=an.pct_return(w.col), delta_unit="%", sub=sub))
    ui.tile_row(tiles[:6])

    # ---- USDJPY vs rate differential -----------------------------------
    ui.section("USDJPY and the rate differential",
               "spot vs a fitted relationship, its residual, and rolling sensitivity")
    jpy = fx.get("JPY=X")
    if jpy and jpy.ok and ust10.ok and jgb.ok and "10Y" in jgb.frame.columns:
        df = an.align_recent({"spot": jpy.col, "ust": ust10.col, "jgb": jgb.frame["10Y"]})
        if df.empty:
            st.caption("USDJPY and rate curves have no recent overlapping observations.")
        else:
            df["diff"] = (df["ust"] - df["jgb"]) * 100  # bp
            df = df.tail(756)
            slope, intercept, r2 = an.beta(df["spot"], df["diff"], 250)
            df["fair"] = slope * df["diff"] + intercept
            df["resid"] = df["spot"] - df["fair"]

            # Rolling beta: yen per 100bp of spread.
            df["beta100"] = an.rolling_beta(df["spot"], df["diff"], 250) * 100

            c1, c2, c3 = ui.columns(3)
            with c1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df["spot"], name="USDJPY spot",
                                         line=dict(width=2, color=theme.BLUE),
                                         hovertemplate="%{y:.2f}<extra>spot</extra>"))
                fig.add_trace(go.Scatter(x=df.index, y=df["fair"], name="Fitted rate relationship",
                                         line=dict(width=2, color=theme.ORANGE, dash="dash"),
                                         hovertemplate="%{y:.2f}<extra>fitted</extra>"))
                fig.update_layout(title=f"USDJPY vs fitted relationship · R² {r2:.2f}",
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
                    yaxis=dict(title="yen vs fitted relationship"))
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
                    "The line is fitted on the latest 250 matched observations and drawn "
                    "retrospectively. It is not a tradable fair-value estimate. A lower beta "
                    "shows reduced fitted sensitivity, not its cause.</div>", unsafe_allow_html=True)

    _positioning(_load_cot())

    # ---- FX complex -----------------------------------------------------
    c1, c2 = ui.columns(2)
    with c1:
        fig = go.Figure()
        fx_series = {}
        for sym, label in FX.items():
            s = fx.get(sym)
            if s and s.ok:
                d = s.col.dropna().tail(504)
                if label.endswith("USD"):
                    d = 1.0 / d
                    label = f"{label} (inv.)"
                fx_series[label] = d
        if fx_series:
            indexed = an.common_base_index(fx_series)
            for label, color in zip(indexed.columns, theme.SERIES):
                fig.add_trace(go.Scatter(x=indexed.index, y=indexed[label], name=label,
                                         line=dict(width=2, color=color),
                                         hovertemplate="%{y:.1f}<extra>" + label + "</extra>"))
        fig.update_layout(title="FX complex — shared base = 100, up = USD stronger",
                          yaxis=dict(title="Index"))
        ui.chart(fig, height=300)
    with c2:
        # Gold vs real yields: the relationship, and where it has broken.
        g = metals.get("GC=F")
        if g and g.ok and real.ok:
            df = an.align_recent({"gold": g.col, "real": real.col}).tail(756)
            if df.empty:
                st.caption("Gold and real yields have no recent overlapping observations.")
            else:
                gspan = (df.index[-1] - df.index[0]).days / 365.25
                fig = go.Figure(go.Scatter(
                    x=df["real"], y=df["gold"], mode="markers",
                    marker=dict(size=5, color=list(range(len(df))),
                                colorscale=theme.SEQ_BLUE, showscale=False),
                    name="daily", customdata=df.index.strftime("%d %b %Y"),
                    hovertemplate="%{customdata}: real %{x:.2f}% · gold %{y:,.0f}<extra></extra>"))
                fig.add_trace(go.Scatter(
                    x=[df["real"].iloc[-1]], y=[df["gold"].iloc[-1]], mode="markers",
                    marker=dict(size=13, color=theme.ORANGE,
                                line=dict(width=2, color=theme.SURFACE)),
                    name=f"Latest matched date · {df.index[-1]:%d %b}",
                    hovertemplate=f"{df.index[-1]:%d %b %Y}<extra>latest matched observation</extra>"))
                fig.update_layout(
                    title=f"Gold vs 10y real yield — {gspan:.0f}y, darker = more recent",
                    xaxis=dict(title="10y TIPS real yield (%)", ticksuffix="%"),
                    yaxis=dict(title="Gold ($/oz)"))
                ui.chart(fig, height=300, unified=False)

    # ---- commodity curves & ratios --------------------------------------
    ui.section("Commodity curves & macro ratios",
               "forward curve shape and cross-market relative positioning")
    c1, c2, c3 = ui.columns(3)
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
                    customdata=pd.to_datetime(d["observed_at"]).dt.strftime("%d %b %Y"),
                    hovertemplate="%{x|%b %y}: %{y:.1f} · quote %{customdata}<extra>" + name + "</extra>"))
        fig.update_layout(
            title="Energy forward curves — front contract = 100",
            yaxis=dict(title="Index vs front"), xaxis=dict(title="Delivery month"))
        ui.chart(fig, height=290)
        if wti_curve.ok:
            sh = market.curve_shape(wti_curve.frame, 6)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                f"WTI 6-month slope {sh:+.1f}% annualised — "
                f"{'backwardation' if sh > 0 else 'contango'}."
                "</div>", unsafe_allow_html=True)
    with c2:
        cu, au = metals.get("HG=F"), metals.get("GC=F")
        if cu and au and cu.ok and au.ok and ust10.ok:
            r = an.ratio(cu.col, au.col, "cg").dropna()
            df = an.align_recent({"cg": r, "y10": ust10.col}).tail(756)
            if df.empty:
                st.caption("Copper/gold and yields have no recent overlapping observations.")
            else:
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
                    "Both standardised over the displayed sample. The gap describes relative "
                    "positioning: copper/gold is a noisy growth proxy, while yields also reflect "
                    "inflation, policy and term premium. A gap does not establish mispricing.</div>",
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
    c1, c2 = ui.columns(2)
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


def _positioning(cot: dict) -> None:
    """Leveraged-fund positioning in yen and euro futures, as a share of OI."""
    live = {code: s for code, s in cot.items() if s.ok}
    if not live:
        ui.failures_note(list(cot.values()))
        return
    ui.section("Positioning — CFTC Traders in Financial Futures",
               "leveraged-fund net as % of open interest; a crowded short yen is carry-unwind fuel")
    c1, c2 = ui.columns([1.4, 1])
    with c1:
        fig = go.Figure()
        for s, color in zip(live.values(), (theme.BLUE, theme.ORANGE)):
            d = s.frame["lev_net_pct_oi"].dropna()
            fig.add_trace(go.Scatter(x=d.index, y=d, name=s.label.replace(" futures", ""),
                                     line=dict(width=2, color=color, shape="hv"),
                                     hovertemplate="%{y:+.1f}% of OI<extra>"
                                                   f"{s.label}</extra>"))
        fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1))
        fig.update_layout(title="Leveraged funds, net long (+) / short (−) the foreign currency",
                          yaxis=dict(title="% of open interest", ticksuffix="%"))
        ui.chart(fig, height=280)
    with c2:
        rows = []
        for s in live.values():
            d = s.frame["lev_net_pct_oi"].dropna()
            z = an.zscore(d, 5)
            wk = float(d.iloc[-1] - d.iloc[-2]) if len(d) > 1 else float("nan")
            rows.append(
                f"<tr><td>{ui.esc(s.label)}</td>"
                f"<td style='text-align:right'>{ui.fmt(float(d.iloc[-1]), 1, plus=True)}%</td>"
                f"<td style='text-align:right'>{ui.fmt(wk, 1, plus=True)}</td>"
                f"<td style='text-align:right'>{f'{z.pct:.0f}' if z else '—'}</td>"
                f"<td style='text-align:right'>{f'{s.as_of:%d %b}' if s.as_of else '—'}</td></tr>")
        st.markdown(
            '<table class="ficc-tbl"><tr><th>Contract</th><th>Lev net</th><th>1w chg</th>'
            f'<th>Pctile</th><th>As of</th></tr>{"".join(rows)}</table>',
            unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:6px'>"
            "Positions as of Tuesday, published Friday. Futures on JPY and EUR are "
            "quoted as the foreign currency, so a negative number is short yen "
            "(long USDJPY). Percentile is against the available five-year window.</div>",
            unsafe_allow_html=True)
    ui.sources_note(list(live.values()))
