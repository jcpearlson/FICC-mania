"""Rates: the three curves, the policy path, and the money-market front end.

A note on the combined curve chart, because it merges two different objects:
the UST and JGB lines are *par yield curves* (x = maturity), while the SOFR
line is a *futures-implied forward path* (x = time forward). Practitioners read
them together constantly -- that comparison is the point -- but the x-axis
means something slightly different for the third line, so the chart says so
rather than quietly pretending they're the same construct.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import theme, ui
from ..sources import ecb, fred, market, mof, nyfed, treasury, treasurydirect

# Fed balance sheet plumbing. Units differ at source and are reconciled in
# analytics.net_liquidity -- WALCL is $mn, the rest $bn.
PLUMBING = {
    "WALCL": ("Fed total assets ($mn)", 7),
    "WTREGEN": ("Treasury General Account ($bn)", 7),
    "RRPONTSYD": ("ON RRP take-up ($bn)", 1),
    "WRESBAL": ("Reserve balances ($bn)", 7),
}
# Front-end credit: lower-tier (A2/P2) minus AA non-financial 90-day CP.
CP = {"RIFSPPNA2P2D90NB": "A2/P2 nonfinancial CP 90d",
      "DCPN3M": "AA nonfinancial CP 90d"}


@st.cache_data(ttl=900, show_spinner=False)
def _load(years: list[int]):
    ust = treasury.curve(years)
    jgb = mof.curve()
    sofr_fwd = market.futures_strip("SR3", 16, True, "SOFR futures forward path")
    ff = market.futures_strip("ZQ", 15, False, "Fed funds futures path")
    sofr_on = nyfed.reference_rate("sofr")
    effr = nyfed.reference_rate("effr", "unsecured")
    sofr_avg = nyfed.sofr_averages()
    extras = fred.many({
        "DFII10": "10y TIPS real yield",
        "T10YIE": "10y breakeven",
        "T5YIFR": "5y5y fwd inflation",
        "THREEFYTP10": "10y term premium (Kim-Wright)",
        "IORB": "Interest on reserve balances",
        "DGS10": "10y UST (long history)",
    })
    real = treasury.curve(years, treasury.REAL, "UST real curve")
    move = market.quote("^MOVE", "MOVE (rate vol)", period="2y")
    return (ust, jgb, sofr_fwd, ff, sofr_on, effr, sofr_avg, extras, move, real)


@st.cache_data(ttl=900, show_spinner=False)
def _load_extra():
    """Newer sources, loaded apart from `_load` so its tuple stays stable."""
    plumbing = {k: fred.get(k, lbl, cadence_days=cad) for k, (lbl, cad) in PLUMBING.items()}
    cp = fred.many(CP)
    eur = ecb.curve()
    estr = ecb.estr()
    auctions = treasurydirect.auctions()
    return plumbing, cp, eur, estr, auctions


def cp_spread(cp: dict) -> pd.Series | None:
    """A2/P2 minus AA 90-day CP in bp, on dates both published.

    The two series are released a day apart; an inner join keeps a spread
    from ever pairing today's A2/P2 with yesterday's AA.
    """
    a, b = cp.get("RIFSPPNA2P2D90NB"), cp.get("DCPN3M")
    if not (a and b and a.ok and b.ok):
        return None
    d = pd.concat([a.col.rename("a"), b.col.rename("b")], axis=1, join="inner").dropna()
    return ((d["a"] - d["b"]) * 100).rename("cp_spread") if len(d) else None


def render(years: list[int]) -> None:
    (ust, jgb, sofr_fwd, ff, sofr_on, effr, sofr_avg,
     extras, move, real) = _load(years)
    plumbing, cp, eur, estr, auctions = _load_extra()

    # ---- headline tiles ------------------------------------------------
    tiles = []
    if ust.ok:
        f = ust.frame
        for tenor, dp in (("2 Yr", 2), ("10 Yr", 2), ("30 Yr", 2)):
            if tenor in f.columns:
                tiles.append(ui.tile(
                    f"UST {tenor.replace(' Yr','Y')}", float(f[tenor].iloc[-1]), ust,
                    unit="%", dp=dp, mode="rates",
                    delta=an.pct_change_bp(f[tenor], 1)))
        s = an.spread(f, "10 Yr", "2 Yr")
        z = an.zscore(s, 5)
        tiles.append(ui.tile("2s10s slope", float(s.iloc[-1]), ust, unit="bp", dp=0,
                             mode="rates",
                             delta=float(s.iloc[-1] - s.iloc[-2]) if len(s) > 1 else None,
                             sub=f"{z.window_label} pct {z.pct:.0f} · {z.verdict_width}"
                                 if z else ""))
    if jgb.ok and "10Y" in jgb.frame.columns:
        tiles.append(ui.tile("JGB 10Y", float(jgb.frame["10Y"].iloc[-1]), jgb, unit="%",
                             mode="rates",
                             delta=an.pct_change_bp(jgb.frame["10Y"], 1)))
    if move.ok:
        tiles.append(ui.tile("MOVE", move.latest(), move, dp=1,
                             delta=move.change(), delta_unit="pts", invert=True))
    ui.tile_row(tiles[:6])

    # ---- the three curves ---------------------------------------------
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.35, 1])

    with c1:
        fig = go.Figure()
        if ust.ok:
            snap = an.curve_snapshot(ust.frame, treasury.TENORS, offsets=(0, 21))
            ago = snap[snap.offset == 21]
            if len(ago):
                # A faint month-ago curve turns "the curve" into "how the curve
                # moved", which is the question a level alone cannot answer.
                fig.add_trace(go.Scatter(
                    x=ago["years"], y=ago["yield"], name="UST 1m ago",
                    mode="lines", line=dict(width=1.4, color=theme.BLUE, dash="dot"),
                    opacity=0.55, hovertemplate="%{y:.2f}%<extra>UST 1m ago</extra>"))
            cur = snap[snap.offset == 0]
            fig.add_trace(go.Scatter(
                x=cur["years"], y=cur["yield"], name="UST par curve",
                mode="lines+markers", line=dict(width=2.4, color=theme.BLUE),
                marker=dict(size=7), hovertemplate="%{y:.2f}%<extra>UST</extra>"))
        if sofr_fwd.ok:
            fwd = sofr_fwd.frame.copy()
            fig.add_trace(go.Scatter(
                x=fwd["years_fwd"], y=fwd["implied_rate"], name="SOFR forward (futures)",
                mode="lines+markers", line=dict(width=2.4, color=theme.ORANGE),
                marker=dict(size=7), hovertemplate="%{y:.2f}%<extra>SOFR fwd</extra>"))
        if jgb.ok:
            jr = jgb.frame.iloc[-1]
            xs = [mof.TENORS[c] for c in jgb.frame.columns if c in mof.TENORS
                  and pd.notna(jr[c])]
            ys = [float(jr[c]) for c in jgb.frame.columns if c in mof.TENORS
                  and pd.notna(jr[c])]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, name="JGB par curve", mode="lines+markers",
                line=dict(width=2.4, color=theme.AQUA), marker=dict(size=7),
                hovertemplate="%{y:.2f}%<extra>JGB</extra>"))
        if real.ok:
            rr = real.frame.iloc[-1]
            rmap = {"5 YR": 5, "7 YR": 7, "10 YR": 10, "20 YR": 20, "30 YR": 30}
            xs = [v for k, v in rmap.items() if k in real.frame.columns and pd.notna(rr[k])]
            ys = [float(rr[k]) for k in rmap if k in real.frame.columns and pd.notna(rr[k])]
            if xs:
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, name="UST real (TIPS)", mode="lines+markers",
                    line=dict(width=2, color=theme.VIOLET, dash="dash"),
                    marker=dict(size=6),
                    hovertemplate="%{y:.2f}%<extra>UST real</extra>"))
        if eur.ok:
            er = eur.frame.iloc[-1]
            pts = [(ecb.TENORS[c], float(er[c])) for c in eur.frame.columns
                   if c in ecb.TENORS and pd.notna(er[c])]
            if pts:
                fig.add_trace(go.Scatter(
                    x=[p[0] for p in pts], y=[p[1] for p in pts],
                    name="EUR AAA spot (ECB)", mode="lines+markers",
                    line=dict(width=2, color=theme.YELLOW), marker=dict(size=6),
                    hovertemplate="%{y:.2f}%<extra>EUR AAA</extra>"))
        fig.update_layout(
            title="Curves — UST nominal & real, SOFR forward, JGB, EUR AAA",
            xaxis=dict(title="Years", type="log",
                       tickvals=[0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30],
                       ticktext=["3m", "6m", "1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y"]),
            yaxis=dict(title="Yield / implied rate (%)", ticksuffix="%"),
        )
        ui.chart(fig, height=340)
        st.markdown(
            f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
            "x-axis is maturity for the par curves and time-forward for the SOFR "
            "strip, each futures point placed at the midpoint of the quarter it "
            "settles on. A par yield is an <em>average</em> of forwards to that "
            "maturity, so in an upward-sloping market the forward strip sits above "
            "the par curve by construction — that gap is geometry, not value. "
            "The EUR line is the ECB's fitted AAA <em>spot</em> curve, not par; the "
            "difference is a few bp and does not change the shape."
            "</div>", unsafe_allow_html=True)

    with c2:
        # Per-tenor change grid -- the "what moved overnight" read.
        if ust.ok:
            ch = an.curve_changes(ust.frame, treasury.TENORS,
                                  {"1d": 1, "1w": 5, "1m": 21, "3m": 63})
            cols = [c for c in ("1d", "1w", "1m", "3m") if c in ch.columns]
            fig = go.Figure(go.Heatmap(
                z=ch[cols].T.values, x=ch["tenor"], y=cols,
                colorscale=theme.DIVERGING, zmid=0,
                xgap=2, ygap=2,
                colorbar=dict(title=dict(text="bp", side="right"), thickness=10,
                              len=.85, outlinewidth=0,
                              tickfont=dict(color=theme.MUTED, size=10)),
                hovertemplate="%{x} · %{y}: %{z:+.1f} bp<extra></extra>"))
            fig.update_layout(title="UST change by tenor (bp)",
                              yaxis=dict(autorange="reversed"),
                              xaxis=dict(tickangle=-45))
            ui.chart(fig, height=340, legend=False, unified=False)

    # ---- policy path + front end ---------------------------------------
    c1, c2, c3 = st.columns(3)
    with c1:
        if ff.ok:
            d = ff.frame
            fig = go.Figure(go.Scatter(
                x=d.index, y=d["implied_rate"], mode="lines+markers",
                line=dict(width=2.4, color=theme.VIOLET), marker=dict(size=8),
                name="Implied EFFR",
                hovertemplate="%{x|%b %Y}: %{y:.3f}%<extra></extra>"))
            if effr.ok:
                cur = effr.latest("percentRate")
                fig.add_hline(y=cur, line=dict(color=theme.MUTED, width=1, dash="dot"),
                              annotation_text=f"EFFR now {cur:.2f}%",
                              annotation_font=dict(size=10, color=theme.MUTED))
                total = (float(d["implied_rate"].iloc[-1]) - cur) * 100
                fig.add_annotation(
                    x=0.02, y=0.96, xref="paper", yref="paper", showarrow=False,
                    text=f"<b>{total:+.0f} bp</b> priced by {d.index[-1]:%b %Y}",
                    font=dict(size=11, color=theme.INK), align="left")
            fig.update_layout(title="Fed policy path — fed funds futures",
                              yaxis=dict(title="Implied EFFR (%)", ticksuffix="%"))
            ui.chart(fig, height=290, legend=False)
    with c2:
        if sofr_on.ok:
            d = sofr_on.frame.tail(180)
            fig = go.Figure()
            if {"percentPercentile1", "percentPercentile99"} <= set(d.columns):
                fig.add_trace(go.Scatter(
                    x=list(d.index) + list(d.index[::-1]),
                    y=list(d["percentPercentile99"]) + list(d["percentPercentile1"][::-1]),
                    fill="toself", fillcolor="rgba(57,135,229,0.13)",
                    line=dict(width=0), name="1st–99th pctile", hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=d.index, y=d["percentRate"], name="SOFR",
                line=dict(width=2, color=theme.BLUE),
                hovertemplate="%{y:.2f}%<extra>SOFR</extra>"))
            if effr.ok:
                e = effr.frame.tail(180)
                fig.add_trace(go.Scatter(
                    x=e.index, y=e["percentRate"], name="EFFR",
                    line=dict(width=2, color=theme.ORANGE),
                    hovertemplate="%{y:.2f}%<extra>EFFR</extra>"))
            fig.update_layout(title="Overnight funding — SOFR vs EFFR",
                              yaxis=dict(title="%", ticksuffix="%"))
            ui.chart(fig, height=290)
    with c3:
        # DGS10 rather than the treasury.gov curve: the CSV endpoint only serves
        # a few years at a time, which would cap the spread's history at ~3y and
        # make the percentile verdict nearly meaningless.
        long_ust = extras.get("DGS10")
        if (long_ust and long_ust.ok) and jgb.ok:
            u = long_ust.col.dropna()
            j = jgb.frame["10Y"].dropna()
            df = pd.concat([u.rename("ust"), j.rename("jgb")], axis=1).ffill().dropna()
            # Score against the full common history, then truncate for display.
            # Scoring a series that has already been cut to two years makes the
            # window equal the sample, so the verdict can never say anything.
            sp_full = (df["ust"] - df["jgb"]) * 100
            z = an.zscore(sp_full, 10)
            sp = sp_full[sp_full.index >= sp_full.index[-1] - pd.Timedelta(days=730)]
            fig = go.Figure(go.Scatter(
                x=sp.index, y=sp, line=dict(width=2, color=theme.MAGENTA),
                name="10y UST − JGB",
                hovertemplate="%{y:.0f} bp<extra></extra>"))
            fig.update_layout(
                title=f"10y UST − JGB spread · {sp.iloc[-1]:.0f} bp"
                      + (f" ({z.verdict_width}, {z.window_label})" if z else ""),
                yaxis=dict(title="bp"))
            ui.chart(fig, height=290, legend=False)

    # ---- carry, roll-down and the breakeven -----------------------------
    ui.section("Carry & roll-down",
               "what the curve pays you to own it, and how big a selloff wipes that out")
    c1, c2 = st.columns([1.25, 1])
    # Finance a 3-month hold at the 3-month rate, not at overnight. Using the
    # overnight rate understates the cost of carry by the whole front-end slope
    # (~25bp today), which flows into carry and breakeven for every tenor.
    front, front_label = None, ""
    if ust.ok and "3 Mo" in ust.frame.columns:
        front = float(ust.frame["3 Mo"].iloc[-1])
        front_label = "3m bill"
    elif sofr_on.ok:
        front = sofr_on.latest("percentRate")
        front_label = "overnight SOFR"
    if ust.ok and front is not None:
        levels = {k: float(v) for k, v in ust.frame.iloc[-1].items() if pd.notna(v)}
        cr = an.carry_rolldown(treasury.TENORS, levels, front, horizon_years=0.25)
        cr = cr[cr["years"] >= 1]
        with c1:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=cr["tenor"], y=cr["carry_bp"], name="Carry",
                                 marker=dict(color=theme.BLUE),
                                 hovertemplate="%{y:.1f} bp<extra>carry</extra>"))
            fig.add_trace(go.Bar(x=cr["tenor"], y=cr["roll_bp"], name="Roll-down",
                                 marker=dict(color=theme.AQUA),
                                 hovertemplate="%{y:.1f} bp<extra>roll</extra>"))
            fig.add_trace(go.Scatter(
                x=cr["tenor"], y=cr["breakeven_bp"], name="Breakeven selloff",
                mode="lines+markers", line=dict(width=2, color=theme.ORANGE),
                marker=dict(size=8),
                hovertemplate="%{y:.1f} bp<extra>breakeven</extra>"))
            fig.update_layout(barmode="relative",
                              title="3-month horizon — carry, roll-down and breakeven (bp)",
                              yaxis=dict(title="bp"))
            ui.chart(fig, height=300, unified=False)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                f"Financed at {front:.2f}% ({front_label}). Breakeven is the yield "
                "rise over three months that exactly cancels carry plus "
                "roll-down — the number that turns the curve picture into a "
                "trade.</div>",
                unsafe_allow_html=True)
        with c2:
            best = cr.loc[cr["breakeven_bp"].idxmax()] if len(cr) else None
            rows = "".join(
                f"<tr><td>{r.tenor}</td><td style='text-align:right'>{r.yield_now:.2f}%</td>"
                f"<td style='text-align:right'>{r.carry_bp:+.1f}</td>"
                f"<td style='text-align:right'>{r.roll_bp:+.1f}</td>"
                f"<td style='text-align:right;color:{theme.INK}'>{r.total_bp:+.1f}</td>"
                f"<td style='text-align:right'>{r.breakeven_bp:+.1f}</td></tr>"
                for r in cr.itertuples())
            st.markdown(
                '<table class="ficc-tbl"><tr><th>Tenor</th><th>Yield</th><th>Carry</th>'
                f'<th>Roll</th><th>Total</th><th>Breakeven</th></tr>{rows}</table>',
                unsafe_allow_html=True)
            if best is not None:
                st.markdown(
                    f"<div style='font-size:11.5px;color:{theme.INK_2};margin-top:8px'>"
                    f"Best cushion: <b style='color:{theme.INK}'>{best.tenor}</b> — earns "
                    f"{best.total_bp:.0f}bp over three months, so it takes a "
                    f"{best.breakeven_bp:.0f}bp selloff to break even.</div>",
                    unsafe_allow_html=True)

    # ---- inflation, term premium & reserve scarcity ---------------------
    c1, c2 = st.columns(2)
    with c1:
        be = [extras.get(k) for k in ("T10YIE", "T5YIFR", "DFII10", "THREEFYTP10")]
        if any(s and s.ok for s in be):
            fig = go.Figure()
            for s_, color in zip(be, (theme.BLUE, theme.ORANGE, theme.AQUA, theme.YELLOW)):
                if s_ and s_.ok:
                    d = s_.col.tail(1250)
                    fig.add_trace(go.Scatter(x=d.index, y=d, name=s_.label,
                                             line=dict(width=2, color=color),
                                             hovertemplate="%{y:.2f}%<extra>"
                                                           f"{s_.label}</extra>"))
            fig.update_layout(
                title="Decomposing the 10y — real yield, breakevens, term premium",
                yaxis=dict(title="%", ticksuffix="%"))
            ui.chart(fig, height=290)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "Term premium answers the first question on any selloff: is this "
                "repricing of the policy path, or of risk?</div>",
                unsafe_allow_html=True)
    with c2:
        iorb = extras.get("IORB")
        if sofr_on.ok and iorb and iorb.ok:
            # IORB carries a forward-dated effective date (an administered rate
            # is announced before it applies). Joining naively extends the index
            # past today and forward-fills SOFR across days that have not
            # happened, putting a phantom point in the chart title. Clip to the
            # last date SOFR has actually observed.
            last_obs = sofr_on.frame.index.max()
            df = pd.concat([sofr_on.frame["percentRate"].rename("sofr"),
                            iorb.col.rename("iorb")], axis=1).ffill()
            df = df[df.index <= last_obs].dropna()
            sp = ((df["sofr"] - df["iorb"]) * 100).tail(500)
            fig = go.Figure(go.Scatter(
                x=sp.index, y=sp, line=dict(width=2, color=theme.MAGENTA),
                name="SOFR − IORB",
                hovertemplate="%{y:+.1f} bp<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1, dash="dot"))
            fig.update_layout(
                title=f"Reserve scarcity — SOFR minus IORB · {sp.iloc[-1]:+.0f} bp",
                yaxis=dict(title="bp"))
            ui.chart(fig, height=290, legend=False)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "The cleanest single gauge of reserve scarcity. Persistently positive "
                "means cash is getting scarce relative to collateral.</div>",
                unsafe_allow_html=True)

    _plumbing(plumbing, cp)
    _auctions(auctions)

    ui.failures_note([ust, jgb, sofr_fwd, ff, sofr_on, effr, move, real,
                      *extras.values(), *plumbing.values(), *cp.values(),
                      eur, estr, auctions])
    ui.sources_note([ust, jgb, sofr_fwd, sofr_on, real, eur, auctions])


def _plumbing(plumbing: dict, cp: dict) -> None:
    """Liquidity: how much central-bank cash is in the system, and front-end credit."""
    ui.section("Liquidity & plumbing",
               "Fed balance sheet net of TGA and RRP, reserves, and front-end credit stress")
    c1, c2, c3 = st.columns(3)
    w, t, r = (plumbing.get(k) for k in ("WALCL", "WTREGEN", "RRPONTSYD"))
    with c1:
        if all(s_ and s_.ok for s_ in (w, t, r)):
            nl = an.net_liquidity(w.col, t.col, r.col).tail(260)
            if len(nl):
                chg = float(nl.iloc[-1] - nl.iloc[-5]) * 1e3 if len(nl) > 4 else None
                fig = go.Figure(go.Scatter(
                    x=nl.index, y=nl, name="Net liquidity",
                    line=dict(width=2, color=theme.BLUE, shape="hv"),
                    hovertemplate="$%{y:.2f}tn<extra></extra>"))
                fig.update_layout(
                    title=f"Net liquidity · ${nl.iloc[-1]:.2f}tn"
                          + (f" ({chg:+,.0f}bn over 4w)" if chg is not None else ""),
                    yaxis=dict(title="$ trillions", tickprefix="$"))
                ui.chart(fig, height=280, legend=False)
                st.markdown(
                    f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                    "Fed total assets − Treasury General Account − ON RRP, weekly. "
                    "A market shorthand, not an identity: it tracks risk assets loosely "
                    "and breaks whenever balance-sheet composition changes.</div>",
                    unsafe_allow_html=True)
    with c2:
        res, rrp = plumbing.get("WRESBAL"), r
        fig = go.Figure()
        for s_, name, color in ((res, "Reserves", theme.AQUA),
                                (rrp, "ON RRP", theme.ORANGE)):
            if s_ and s_.ok:
                d = (s_.col / 1e3).tail(1100)
                fig.add_trace(go.Scatter(x=d.index, y=d, name=name,
                                         line=dict(width=2, color=color),
                                         hovertemplate="$%{y:.2f}tn<extra>"
                                                       f"{name}</extra>"))
        if fig.data:
            fig.update_layout(title="Reserves vs ON RRP — where the cash sits",
                              yaxis=dict(title="$ trillions", tickprefix="$"))
            ui.chart(fig, height=280)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "Once RRP is drained, further QT comes straight out of reserves — "
                "watch this alongside SOFR−IORB above.</div>", unsafe_allow_html=True)
    with c3:
        sp = cp_spread(cp)
        if sp is not None:
            sp = sp.tail(750)
            z = an.zscore(sp, 3)
            fig = go.Figure(go.Scatter(x=sp.index, y=sp, name="A2/P2 − AA",
                                       line=dict(width=2, color=theme.MAGENTA),
                                       hovertemplate="%{y:.0f} bp<extra></extra>"))
            fig.update_layout(
                title=f"CP quality spread · {sp.iloc[-1]:.0f} bp"
                      + (f" ({z.verdict_width}, {z.window_label})" if z else ""),
                yaxis=dict(title="bp"))
            ui.chart(fig, height=280, legend=False)
            st.markdown(
                f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:-6px'>"
                "90-day A2/P2 minus AA non-financial commercial paper. Front-end "
                "credit stress; it has historically moved ahead of HY.</div>",
                unsafe_allow_html=True)


def _auctions(auctions) -> None:
    """Coupon auction demand, each result judged against its own recent history."""
    ui.section("Treasury auctions",
               "coupon auction demand vs each security's own last six — the 'who is absorbing duration' read")
    if not auctions.ok:
        return
    f = treasurydirect.with_context(auctions.frame)
    recent = f.tail(12).iloc[::-1]

    def _cell(v, dp=2, good_up=True, suffix=""):
        if v != v:
            return "<td style='text-align:right'>—</td>"
        c = theme.delta_color(v, mode="perf" if good_up else "risk")
        return (f"<td style='text-align:right;color:{c}'>{v:+.{dp}f}{suffix}</td>")

    rows = "".join(
        f"<tr><td>{r.Index:%d %b}</td><td>{ui.esc(r.term)} {ui.esc(r.type)}"
        f"{' (r)' if r.reopening else ''}</td>"
        f"<td style='text-align:right'>{ui.fmt(r.high_yield, 3)}</td>"
        f"<td style='text-align:right'>{ui.fmt(r.btc, 2)}</td>"
        + _cell(r.btc_vs_avg, 2)
        + f"<td style='text-align:right'>{ui.fmt(r.indirect_pct, 1)}%</td>"
        + _cell(r.indirect_pct_vs_avg, 1, suffix="pp")
        + f"<td style='text-align:right'>{ui.fmt(r.dealer_pct, 1)}%</td>"
        + _cell(r.dealer_pct_vs_avg, 1, good_up=False, suffix="pp")
        + "</tr>"
        for r in recent.itertuples())
    c1, c2 = st.columns([1.35, 1])
    with c1:
        st.markdown(
            '<table class="ficc-tbl"><tr><th>Date</th><th style="text-align:left">Security</th>'
            '<th>High yld</th><th>B/C</th><th>vs avg</th><th>Indirect</th><th>vs avg</th>'
            f'<th>Dealer</th><th>vs avg</th></tr>{rows}</table>',
            unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:10.5px;color:{theme.MUTED};margin-top:6px'>"
            "Shares are of the competitive award. 'vs avg' compares with the same "
            "security's previous six auctions; green is stronger demand. No tail is "
            "shown: it needs the 1pm when-issued yield, which is not public.</div>",
            unsafe_allow_html=True)
    with c2:
        fig = go.Figure()
        for term, color in zip(("2-Year", "10-Year", "30-Year"),
                               (theme.BLUE, theme.ORANGE, theme.AQUA)):
            d = f[(f["term"].str.startswith(term)) & (f["type"] != "TIPS")].tail(24)
            if len(d):
                fig.add_trace(go.Scatter(
                    x=d.index, y=d["dealer_pct"], name=term.replace("-Year", "y"),
                    mode="lines+markers", line=dict(width=2, color=color),
                    marker=dict(size=6),
                    hovertemplate="%{x|%d %b %Y}: %{y:.1f}%<extra>"
                                  f"{term}</extra>"))
        if fig.data:
            fig.update_layout(title="Primary dealer take-down — share of competitive award",
                              yaxis=dict(title="%", ticksuffix="%"))
            ui.chart(fig, height=300, unified=False)
