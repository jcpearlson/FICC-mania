"""Market conditions, their component contributions and cross-market context."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import regime, theme, ui
from ..sources import fred, market

@st.cache_data(ttl=120, show_spinner=False)
def _load():
    f = fred.many({
        "BAMLH0A0HYM2": "HY OAS", "BAMLC0A0CM": "IG OAS", "VIXCLS": "VIX",
        "T10Y2Y": "2s10s", "DGS10": "10y UST",
    })
    slow = {k: fred.get(k, v, cadence_days=7) for k, v in
            {"NFCI": "Chicago Fed NFCI", "STLFSI4": "St. Louis Fed FSI"}.items()}
    mkt = market.basket({"^MOVE": "MOVE", "^GSPC": "S&P 500", "HG=F": "Copper",
                         "GC=F": "Gold", "^VVIX": "VVIX", "^SKEW": "SKEW",
                         "DX-Y.NYB": "DXY"}, period="5y")
    return f, slow, mkt


def regime_color(result):
    if not np.isfinite(result.score):
        return theme.WARNING
    return (theme.CRITICAL if result.score <= -.5 else theme.SERIOUS if result.score <= -.15
            else theme.INK_2 if result.score < .15 else theme.GOOD)


def regime_details(result, *, compact=False):
    """The same auditable explanation is available from both landing pages."""
    with st.expander("How the regime is calculated", expanded=False):
        st.markdown("A **market-conditions heuristic**: positive means stronger risk appetite. "
                    "It describes available observations; its weights and bands have not been "
                    "calibrated to predict returns or recessions.")
        st.markdown("**Intended weights:** credit 25%, volatility 25%, financial conditions 20%, "
                    "copper/gold growth proxy 15%, equity trend 15%. VIX/MOVE and NFCI/STLFSI "
                    "split their component equally. Missing legs lose their own weight; surviving "
                    "weights are shown below. At least 80% coverage, credit and volatility are required.")
        st.markdown("**Scaling:** HY, VIX, MOVE and copper/gold use a trailing, up-to-five-year "
                    "mean and standard deviation, excluding the current print (minimum 252 prior "
                    "prints). Divide the signed z-score by 2 and cap at ±1. "
                    "Financial conditions retain the publishers’ zero anchor: −index/2. "
                    "Trend is distance above/below the 200-day MA divided by twice its trailing "
                    "standard deviation; zero is the MA. These anchors serve different purposes.")
        st.markdown("**Bands:** Risk-off ≤ −0.50; Cautious (−0.50, −0.15]; "
                    "Neutral (−0.15, +0.15); Constructive [+0.15, +0.50); Risk-on ≥ +0.50. "
                    "Daily prints expire after 4 calendar days; weekly prints after 10. "
                    "Future-dated and non-finite inputs are excluded. Historical source revisions "
                    "are not undone, so the history is a reconstruction, not a point-in-time backtest.")
        table = result.audit.copy()
        table["Value"] = table["Value"].map(lambda v: ui.fmt(v, 4))
        for col in ("Score", "Contribution"):
            table[col] = table[col].map(lambda v: ui.fmt(v, 3, plus=True))
        for col in ("Intended weight", "Effective weight"):
            table[col] = table[col].map(lambda v: f"{v:.1%}")
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption("Input units: HY OAS in percent; VIX/MOVE and financial conditions in index "
                   "points; copper/gold is a price ratio; trend distance is a fraction (0.05 = 5%). "
                   "Coverage measures available intended weight, not forecast confidence.")
        st.download_button("Download regime inputs", result.audit.to_csv(index=False),
                           "ficc-regime-inputs.csv", "text/csv", key=f"regime-csv-{compact}")


def regime_history(result):
    ui.section("Regime history", "the same calculation through time, using the available source vintage")
    history = result.history.loc[result.history.index >= result.history.index[-1] - pd.Timedelta(days=730)]
    fig = go.Figure(go.Scatter(x=history.index, y=history.score,
                              line=dict(color=theme.BLUE, width=2), name="Conditions score",
                              connectgaps=False, customdata=history.coverage,
                              hovertemplate="%{x|%d %b %Y}: %{y:+.3f}<br>Coverage %{customdata:.0%}<extra></extra>"))
    fig.add_hrect(y0=-.15, y1=.15, fillcolor=theme.INK_2, opacity=.08, line_width=0)
    for boundary in (-.5, -.15, .15, .5):
        fig.add_hline(y=boundary, line=dict(color=theme.AXIS, dash="dot", width=1))
    fig.update_layout(title="Conditions score · shaded band = Neutral", yaxis=dict(range=[-1.05, 1.05], title="score"))
    ui.chart(fig, height=270, legend=False)
    current = history.score.dropna()
    prior = current.loc[current.index <= history.index[-1] - pd.Timedelta(days=30)]
    if np.isfinite(result.score) and len(prior):
        st.caption(f"30-day score change: {result.score - prior.iloc[-1]:+.3f}. "
                   "Weights can change with source availability; chart gaps mean insufficient coverage.")
    else:
        st.caption("Chart gaps mean insufficient coverage. Daily/weekly observations carry forward "
                   "only within their freshness limits. Weights can change with availability.")


def render() -> None:
    f, slow, mkt = _load()
    ui.quality_summary([(s, None) for s in (*f.values(), *slow.values(), *mkt.values())])
    result = regime.analyze(f, slow, mkt)
    score, label, band = result.score, result.label, regime_color(result)

    c1, c2 = ui.columns([1, 2.4])
    with c1:
        st.markdown(
            f"""<div class="ficc-card">
              <p class="ficc-tile-label">Cross-asset risk regime</p>
              <p class="ficc-tile-value" style="font-size:40px;color:{band}">{ui.fmt(score, 3, plus=True)}</p>
              <div style="margin:8px 0 2px 0">
                <span class="ficc-regime" style="background:{band}22;color:{band}">{label}</span>
              </div>
              <div class="ficc-tile-sub">{result.coverage:.0%} of intended weight available ·
              {"Partial coverage" if result.coverage < .999 else "Full coverage"}.
              {"Mixed signals across components." if result.mixed else ""}</div>
            </div>""", unsafe_allow_html=True)
    with c2:
        order = list(regime.WEIGHTS)
        vals = [result.contributions.get(k, np.nan) for k in order]
        names = [f"{regime.NAMES[k]} ({result.weights[k]:.0%} effective)" for k in order]
        # Polarity, not status: these take the diverging poles. The reserved
        # status colors stay reserved for freshness and alerts.
        colors = [theme.BLUE if (v == v and v >= 0) else theme.RED_RATE for v in vals]
        fig = go.Figure(go.Bar(
            x=vals, y=names, orientation="h", marker=dict(color=colors),
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>"))
        fig.add_vline(x=0, line=dict(color=theme.AXIS, width=1))
        fig.update_layout(title="What contributes to the headline score",
                          xaxis=dict(title="weighted contribution", range=[-.40, .40]),
                          yaxis=dict(autorange="reversed"))
        ui.chart(fig, height=250, legend=False, unified=False)

    st.caption(result.explanation)
    if np.isfinite(score):
        nearest = min((-.5, -.15, .15, .5), key=lambda v: abs(score - v))
        if abs(score - nearest) < .03:
            st.caption(f"Near a band boundary: {abs(score-nearest):.3f} from {nearest:+.2f}. "
                       "A small move can change the label without a large change in conditions.")
    regime_details(result)
    regime_history(result)

    # ---- headline tiles -------------------------------------------------
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    tiles = []
    hy = f.get("BAMLH0A0HYM2")
    if hy and hy.ok:
        tiles.append(ui.tile("HY OAS", hy.latest() * 100, hy, unit="bp", dp=0,
                             delta=an.pct_change_bp(hy.col, 1), mode="risk"))
    ig = f.get("BAMLC0A0CM")
    if ig and ig.ok:
        tiles.append(ui.tile("IG OAS", ig.latest() * 100, ig, unit="bp", dp=0,
                             delta=an.pct_change_bp(ig.col, 1), mode="risk"))
    for key, src, dp, md in (("VIXCLS", f, 2, "risk"), ("^MOVE", mkt, 1, "risk"),
                             ("DX-Y.NYB", mkt, 2, "perf")):
        s = src.get(key)
        if s and s.ok:
            tiles.append(ui.tile(s.label, s.latest(), s, dp=dp,
                                 delta=s.change(), delta_unit="pts", mode=md))
    ten = f.get("DGS10")
    if ten and ten.ok:
        tiles.append(ui.tile("10y UST", ten.latest(), ten, unit="%", mode="rates",
                             delta=an.pct_change_bp(ten.col, 1)))
    ui.tile_row(tiles[:6])

    # ---- divergences ----------------------------------------------------
    ui.section("Divergences",
               "relative positioning differences; these are descriptive, not validated leading signals")
    pairs = []

    def _add(name: str, a, b, inv_a=False, inv_b=False, note=""):
        if a is None or b is None or not a.ok or not b.ok:
            return
        za, zb = an.signed_z(a.col, 5, inv_a), an.signed_z(b.col, 5, inv_b)
        if za != za or zb != zb:
            return
        pairs.append({"pair": name, "gap": za - zb, "note": note})

    _add("Credit vs equity vol", hy, f.get("VIXCLS"), True, True,
         "Positive = HY is calmer relative to its own history than VIX is")
    _add("Rate vol vs equity vol", mkt.get("^MOVE"), f.get("VIXCLS"), True, True,
         "Positive = MOVE is calmer relative to its own history than VIX is")
    cu, au, ten = mkt.get("HG=F"), mkt.get("GC=F"), f.get("DGS10")
    if cu and au and ten and cu.ok and au.ok and ten.ok:
        za = an.signed_z(an.ratio(cu.col, au.col), 5)
        zb = an.signed_z(ten.col, 5)
        pairs.append({"pair": "Copper/gold vs 10y", "gap": za - zb,
                      "note": "Positive = copper/gold is stronger vs history than the 10y yield; yields also reflect inflation and term premium"})
    _add("Credit vs financial conditions", hy, slow.get("NFCI"), True, True,
         "Relative HY vs NFCI positioning; NFCI overlaps with credit and volatility")
    _add("Skew vs vol", mkt.get("^SKEW"), f.get("VIXCLS"), True, True,
         "Positive = SKEW is lower vs history than VIX; different option-market measures")

    if any(p["gap"] == p["gap"] for p in pairs):
        df = pd.DataFrame([p for p in pairs if p["gap"] == p["gap"]])
        df = df.reindex(df["gap"].abs().sort_values(ascending=False).index)
        c1, c2 = ui.columns([1.15, 1])
        with c1:
            colors = [theme.SERIOUS if abs(v) >= 1.0 else
                      theme.WARNING if abs(v) >= 0.5 else theme.INK_2
                      for v in df["gap"]]
            fig = go.Figure(go.Bar(x=df["gap"], y=df["pair"], orientation="h",
                                   marker=dict(color=colors),
                                   hovertemplate="%{y}: gap %{x:+.2f}<extra></extra>"))
            fig.add_vline(x=0, line=dict(color=theme.AXIS, width=1))
            fig.update_layout(title="Relative score gap (each z-score clipped and divided by 2)",
                              xaxis=dict(title="gap"),
                              yaxis=dict(autorange="reversed"))
            ui.chart(fig, height=260, legend=False, unified=False)
        with c2:
            rows = "".join(
                f"<tr><td>{r.pair}</td><td style='text-align:right;color:"
                f"{theme.SERIOUS if abs(r.gap) >= 1 else theme.INK_2}'>{r.gap:+.2f}</td>"
                f"<td style='font-size:11px;color:{theme.MUTED}'>{r.note}</td></tr>"
                for r in df.itertuples())
            st.markdown(
                f'<table class="ficc-tbl"><tr><th>Pair</th><th>Gap</th>'
                f'<th style="text-align:left">Why it matters</th></tr>{rows}</table>',
                unsafe_allow_html=True)

    # ---- regime history --------------------------------------------------
    ui.section("Distribution context", "historical positioning of the underlying markets")
    c1, c2 = ui.columns(2)
    with c1:
        if hy and hy.ok and f.get("VIXCLS") and f["VIXCLS"].ok:
            df = pd.concat([(hy.col * 100).rename("hy"),
                            f["VIXCLS"].col.rename("vix")], axis=1).dropna()
            span = (df.index[-1] - df.index[0]).days / 365.25
            fig = go.Figure(go.Scatter(
                x=df["vix"], y=df["hy"], mode="markers",
                marker=dict(size=5, color=list(range(len(df))),
                            colorscale=theme.SEQ_BLUE, showscale=False),
                customdata=df.index.strftime("%d %b %Y"),
                hovertemplate="%{customdata}: VIX %{x:.1f} · HY %{y:.0f}bp<extra></extra>",
                name=f"{span:.0f}y"))
            fig.add_trace(go.Scatter(
                x=[df["vix"].iloc[-1]], y=[df["hy"].iloc[-1]], mode="markers",
                marker=dict(size=13, color=theme.ORANGE,
                            line=dict(width=2, color=theme.SURFACE)),
                name=f"Latest matched date · {df.index[-1]:%d %b}",
                hovertemplate=f"{df.index[-1]:%d %b %Y}<extra>latest matched observation</extra>"))
            fig.update_layout(
                title=f"HY OAS vs VIX — {span:.0f}y, darker = more recent",
                              xaxis=dict(title="VIX"), yaxis=dict(title="HY OAS (bp)"))
            ui.chart(fig, height=300, unified=False)
    with c2:
        rows = []
        for name, s in (("HY OAS", hy), ("IG OAS", f.get("BAMLC0A0CM")),
                        ("VIX", f.get("VIXCLS")), ("MOVE", mkt.get("^MOVE")),
                        ("10y UST", f.get("DGS10")), ("2s10s", f.get("T10Y2Y")),
                        ("NFCI", slow.get("NFCI")), ("DXY", mkt.get("DX-Y.NYB"))):
            if s and s.ok:
                z = an.zscore(s.col, 5)
                if z:
                    rows.append({"metric": f"{name} ({z.window_label})",
                                 "level": z.value, "pct": z.pct, "z": z.z})
        if rows:
            df = pd.DataFrame(rows)
            fig = go.Figure(go.Bar(
                x=df["pct"], y=df["metric"], orientation="h",
                marker=dict(color=df["pct"], colorscale=theme.SEQ_BLUE,
                            cmin=0, cmax=100),
                hovertemplate="%{y}: %{x:.0f}th percentile<extra></extra>"))
            fig.add_vline(x=50, line=dict(color=theme.AXIS, width=1, dash="dot"))
            fig.update_layout(title="Where each market sits in its own history",
                              xaxis=dict(title="percentile", range=[0, 100]),
                              yaxis=dict(autorange="reversed"))
            ui.chart(fig, height=300, legend=False, unified=False)

    ui.failures_note([*f.values(), *slow.values(), *mkt.values()])
    ui.sources_note([hy, f.get("VIXCLS"), mkt.get("^MOVE"), slow.get("NFCI"),
                     slow.get("STLFSI4"), cu, au, mkt.get("^GSPC")])
