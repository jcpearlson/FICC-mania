"""Cross-asset market health -- the landing page.

The composite is deliberately transparent: five components, fixed weights,
each one shown next to the headline so it can be decomposed on sight. An
opaque risk score a practitioner cannot take apart is not useful to them.

Credit and vol carry the most weight because they are the only components that
tend to move *before* the damage. The financial-conditions indices rank third
despite being the most official, precisely because they publish weekly and lag.
Trend ranks last -- it is the most reflexive and the last thing to break.

The divergence table underneath matters as much as the score, since any
composite averages away exactly the disagreements worth trading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import theme, ui
from ..sources import fred, market, treasury

WEIGHTS = {"credit": 0.25, "vol": 0.25, "funding": 0.20, "growth": 0.15, "trend": 0.15}


@st.cache_data(ttl=900, show_spinner=False)
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


def _components(f, slow, mkt) -> dict[str, float]:
    """Each component signed so that positive always means risk-on."""
    out: dict[str, float] = {}
    hy = f.get("BAMLH0A0HYM2")
    out["credit"] = an.signed_z(hy.col, 5, invert=True) if hy and hy.ok else np.nan

    vix, move = f.get("VIXCLS"), mkt.get("^MOVE")
    vs = [an.signed_z(s.col, 5, invert=True)
          for s in (vix, move) if s and s.ok]
    out["vol"] = float(np.mean(vs)) if vs else np.nan

    fs = [an.signed_z(s.col, 5, invert=True) for s in slow.values() if s and s.ok]
    out["funding"] = float(np.mean(fs)) if fs else np.nan

    cu, au = mkt.get("HG=F"), mkt.get("GC=F")
    if cu and au and cu.ok and au.ok:
        out["growth"] = an.signed_z(an.ratio(cu.col, au.col), 5)
    else:
        out["growth"] = np.nan

    spx = mkt.get("^GSPC")
    if spx and spx.ok:
        d = spx.col.dropna()
        rel = (d / d.rolling(200).mean() - 1).dropna()
        out["trend"] = an.signed_z(rel, 5)
    else:
        out["trend"] = np.nan
    return out


def render() -> None:
    f, slow, mkt = _load()
    comp = _components(f, slow, mkt)

    valid = {k: v for k, v in comp.items() if v == v}
    if valid:
        wsum = sum(WEIGHTS[k] for k in valid)
        score = sum(WEIGHTS[k] * v for k, v in valid.items()) / wsum
    else:
        score = float("nan")
    _, label = an.regime_score({"s": score})

    band = (theme.CRITICAL if score <= -0.5 else theme.SERIOUS if score <= -0.15
            else theme.INK_2 if score < 0.15 else theme.GOOD)

    c1, c2 = st.columns([1, 2.4])
    with c1:
        st.markdown(
            f"""<div class="ficc-card">
              <p class="ficc-tile-label">Cross-asset risk regime</p>
              <p class="ficc-tile-value" style="font-size:40px;color:{band}">{score:+.2f}</p>
              <div style="margin:8px 0 2px 0">
                <span class="ficc-regime" style="background:{band}22;color:{band}">{label}</span>
              </div>
              <div class="ficc-tile-sub">Weighted blend of five components, each
              signed so positive = risk-on. Range roughly −1 to +1.</div>
            </div>""", unsafe_allow_html=True)
    with c2:
        order = ["credit", "vol", "funding", "growth", "trend"]
        vals = [comp.get(k, np.nan) for k in order]
        names = [f"{k.title()} ({WEIGHTS[k]:.0%})" for k in order]
        # Polarity, not status: these take the diverging poles. The reserved
        # status colors stay reserved for freshness and alerts.
        colors = [theme.BLUE if (v == v and v >= 0) else theme.RED_RATE for v in vals]
        fig = go.Figure(go.Bar(
            x=vals, y=names, orientation="h", marker=dict(color=colors),
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>"))
        fig.add_vline(x=0, line=dict(color=theme.AXIS, width=1))
        fig.update_layout(title="Regime components — positive is risk-on",
                          xaxis=dict(title="signed z (capped ±1)", range=[-1.05, 1.05]),
                          yaxis=dict(autorange="reversed"))
        ui.chart(fig, height=210, legend=False, unified=False)

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
               "where the composite averages away the disagreement — the pairs worth a second look")
    pairs = []

    def _add(name: str, a, b, a_lbl: str, b_lbl: str, inv_a=False, inv_b=False, note=""):
        if a is None or b is None or not a.ok or not b.ok:
            return
        za, zb = an.signed_z(a.col, 5, inv_a), an.signed_z(b.col, 5, inv_b)
        if za != za or zb != zb:
            return
        pairs.append({"pair": name, a_lbl: za, b_lbl: zb, "gap": za - zb, "note": note})

    _add("Credit vs equity vol", hy, f.get("VIXCLS"), "a", "b", True, True,
         "HY calm while VIX is bid (or the reverse) is the classic pre-drawdown tell")
    _add("Rate vol vs equity vol", mkt.get("^MOVE"), f.get("VIXCLS"), "a", "b", True, True,
         "MOVE usually moves first in genuine macro events")
    _add("Copper/gold vs 10y", None, None, "a", "b")
    cu, au, ten = mkt.get("HG=F"), mkt.get("GC=F"), f.get("DGS10")
    if cu and au and ten and cu.ok and au.ok and ten.ok:
        za = an.signed_z(an.ratio(cu.col, au.col), 5)
        zb = an.signed_z(ten.col, 5)
        pairs.append({"pair": "Copper/gold vs 10y", "a": za, "b": zb, "gap": za - zb,
                      "note": "growth proxy against the rate market's growth view"})
    _add("Credit vs financial conditions", hy, slow.get("NFCI"), "a", "b", True, True,
         "spreads against the official conditions read")
    _add("Skew vs vol", mkt.get("^SKEW"), f.get("VIXCLS"), "a", "b", True, True,
         "tail hedging demand against spot vol")

    if pairs:
        df = pd.DataFrame([p for p in pairs if "a" in p and p["a"] == p["a"]])
        df = df.reindex(df["gap"].abs().sort_values(ascending=False).index)
        c1, c2 = st.columns([1.15, 1])
        with c1:
            colors = [theme.SERIOUS if abs(v) >= 1.0 else
                      theme.WARNING if abs(v) >= 0.5 else theme.INK_2
                      for v in df["gap"]]
            fig = go.Figure(go.Bar(x=df["gap"], y=df["pair"], orientation="h",
                                   marker=dict(color=colors),
                                   hovertemplate="%{y}: gap %{x:+.2f}<extra></extra>"))
            fig.add_vline(x=0, line=dict(color=theme.AXIS, width=1))
            fig.update_layout(title="Divergence size (signed z gap)",
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
    ui.section("Context", "a single score hides whether you are at −1 improving or +0.5 collapsing")
    c1, c2 = st.columns(2)
    with c1:
        if hy and hy.ok and f.get("VIXCLS") and f["VIXCLS"].ok:
            df = pd.concat([(hy.col * 100).rename("hy"),
                            f["VIXCLS"].col.rename("vix")], axis=1).dropna()
            span = (df.index[-1] - df.index[0]).days / 365.25
            fig = go.Figure(go.Scatter(
                x=df["vix"], y=df["hy"], mode="markers",
                marker=dict(size=5, color=list(range(len(df))),
                            colorscale=theme.SEQ_BLUE, showscale=False),
                hovertemplate="VIX %{x:.1f} · HY %{y:.0f}bp<extra></extra>",
                name=f"{span:.0f}y"))
            fig.add_trace(go.Scatter(
                x=[df["vix"].iloc[-1]], y=[df["hy"].iloc[-1]], mode="markers",
                marker=dict(size=13, color=theme.ORANGE,
                            line=dict(width=2, color=theme.SURFACE)),
                name="today", hovertemplate="today<extra></extra>"))
            fig.update_layout(
                title=f"HY OAS vs VIX — {span:.0f}y, darker = more recent",
                              xaxis=dict(title="VIX"), yaxis=dict(title="HY OAS (bp)"))
            ui.chart(fig, height=300, unified=False)
    with c2:
        rows = []
        for name, s, inv in (("HY OAS", hy, True), ("IG OAS", f.get("BAMLC0A0CM"), True),
                             ("VIX", f.get("VIXCLS"), True), ("MOVE", mkt.get("^MOVE"), True),
                             ("10y UST", f.get("DGS10"), False),
                             ("2s10s", f.get("T10Y2Y"), False),
                             ("NFCI", slow.get("NFCI"), True),
                             ("DXY", mkt.get("DX-Y.NYB"), False)):
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
    ui.sources_note([hy, mkt.get("^MOVE"), slow.get("NFCI")])
