"""Market monitor and compact charts for the dashboard landing page."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import analytics as an
from .. import dashboard_data, monitor, regime, theme, ui
from ..sources import mof, treasury
from . import monitor_view
from . import overview as overview_panel
from . import rates as rates_panel

H = 190  # small-multiple height
H_TALL = 230  # for the curve, which earns a little more


def render(years: list[int]) -> None:
    ui.dense_css()
    st.html(monitor.CSS)

    preview = st.empty()
    if "dashboard_loaded" not in st.session_state:
        with st.spinner("Loading Treasuries…"):
            early_ust = dashboard_data.load_treasury(years)
        early_groups = _treasury_groups(early_ust)
        with preview.container():
            st.caption("Treasury preview · credit, funding and global markets are loading.")
            st.markdown(monitor.render_html(early_groups), unsafe_allow_html=True)
    with st.spinner("Loading credit, funding and global markets…"):
        data = dashboard_data.load(years)
    preview.empty()
    st.session_state.dashboard_loaded = True
    ust, jgb, sofr_fwd, ff = data.ust, data.jgb, data.sofr_fwd, data.ff
    sofr_on, effr, extras = data.sofr_on, data.effr, data.extras
    head, ladder = data.head, data.ladder
    f, slow, mkt = data.f, data.slow, data.mkt
    plumbing, cp, eur, estr = data.plumbing, data.cp, data.eur, data.estr
    move, vix, jpy = data.move, data.vix, data.jpy

    hy, ig = head.get("BAMLH0A0HYM2"), head.get("BAMLC0A0CM")
    bb, ccc = ladder.get("BAMLH0A1HYBB"), ladder.get("BAMLH0A3HYC")
    dispersion = (
        (ccc.col - bb.col).dropna() * 100
        if bb and ccc and bb.ok and ccc.ok
        else pd.Series(dtype=float)
    )
    long_ust = extras.get("DGS10")
    iorb = extras.get("IORB")

    # ------------------------------------------------------ status strip
    result = regime.analyze(f, slow, mkt)
    score, label, band = result.score, result.label, overview_panel.regime_color(result)

    def _d(v, unit="bp"):
        """Level plus its 1-day change -- a level alone cannot say 'selloff'."""
        if v is None or v != v:
            return ""
        c = theme.delta_color(v, mode="rates")
        return f"<span style='font-size:10.5px;color:{c};margin-left:5px'>{v:+.0f}{unit}</span>"

    items = [("Regime", f"{ui.fmt(score, 3, plus=True)} {label}", band)]
    if ust.ok and "10 Yr" in ust.frame:
        items.append(
            (
                "10Y",
                f"{ust.frame['10 Yr'].iloc[-1]:.2f}%" + _d(an.pct_change_bp(ust.frame["10 Yr"], 1)),
                theme.INK,
            )
        )
        sl = an.spread(ust.frame, "10 Yr", "2 Yr")
        if not sl.empty:
            items.append(
                (
                    "2s10s",
                    f"{sl.iloc[-1]:.0f}bp"
                    + _d(float(sl.iloc[-1] - sl.iloc[-2]) if len(sl) > 1 else None),
                    theme.INK,
                )
            )
    if hy and hy.ok:
        items.append(
            ("HY OAS", f"{hy.latest() * 100:.0f}bp" + _d(an.pct_change_bp(hy.col, 1)), theme.INK)
        )
    if not dispersion.empty:
        q = dispersion
        zq = an.zscore(q, 5)
        qc = theme.SERIOUS if zq and (zq.pct >= 90 or zq.pct <= 10) else theme.INK
        items.append(
            (
                "CCC−BB",
                f"{q.iloc[-1]:.0f}bp" + _d(float(q.iloc[-1] - q.iloc[-2]) if len(q) > 1 else None),
                qc,
            )
        )
    if ff.ok and effr.ok:
        pr = (float(ff.frame["implied_rate"].iloc[-1]) - effr.latest("percentRate")) * 100
        items.append(
            (
                f"Priced {ff.frame.index[-1]:%b%y}",
                f"{pr:+.0f}bp",
                theme.RED_RATE if pr > 0 else theme.BLUE_RATE,
            )
        )
    ui.strip(items)
    st.caption(
        f"Regime: {result.coverage:.0%} coverage"
        + (" · partial inputs" if result.coverage < 0.999 else "")
        + (" · mixed signals" if result.mixed else "")
        + ". "
        + result.explanation
    )
    overview_panel.regime_details(result, compact=True)

    # ---------------------------------------------------- monitor table
    R = monitor.row_from
    (_, rates_rows), (_, curve_rows) = _treasury_groups(ust)

    front_rows = [
        R(sofr_on, "SOFR o/n", col="percentRate", mode="rates"),
        R(effr, "EFFR", col="percentRate", mode="rates"),
        R(iorb, "IORB", mode="rates"),
    ]
    funding = rates_panel.funding_spread(sofr_on, iorb)
    if not funding.empty:
        front_rows.append(
            monitor.Row(
                "SOFR − IORB",
                funding,
                float(funding.iloc[-1]),
                unit="bp",
                dp=0,
                mode="risk",
                chg_unit="pts",
                chg_dp=0,
                as_of=funding.index[-1].date(),
            )
        )

    cps = rates_panel.cp_spread(cp)
    if cps is not None and len(cps):
        front_rows.append(
            monitor.Row(
                "CP A2/P2 − AA",
                cps,
                float(cps.iloc[-1]),
                unit="bp",
                dp=0,
                mode="risk",
                chg_unit="pts",
                chg_dp=0,
                as_of=cps.index[-1].date(),
            )
        )
    front_rows.append(
        R(
            plumbing.get("RRPONTSYD"),
            "ON RRP ($bn)",
            mode="rates",
            unit="",
            dp=0,
            chg_unit="pts",
            chg_dp=0,
        )
    )

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
    if not dispersion.empty:
        q = dispersion
        credit_rows.append(
            monitor.Row(
                "CCC − BB dispersion",
                q,
                float(q.iloc[-1]),
                unit="bp",
                dp=0,
                mode="risk",
                chg_unit="pts",
                chg_dp=0,
                as_of=ccc.as_of,
            )
        )
    credit_rows += [
        R(head.get("BAMLEMCBPIOAS"), "EM corp OAS", mode="risk", unit="bp", dp=0, scale=100),
        R(head.get("BAMLHE00EHYIOAS"), "Euro HY OAS", mode="risk", unit="bp", dp=0, scale=100),
    ]

    vol_rows = [
        R(move, "MOVE (rate vol)", mode="risk", unit="", dp=1, chg_unit="pts"),
        R(vix, "VIX", mode="risk", unit="", dp=2, chg_unit="pts"),
        R(slow.get("NFCI"), "Chicago Fed NFCI", mode="risk", unit="", dp=2, chg_unit="pts"),
    ]

    global_rows = []
    if jgb.ok:
        for t in ("2Y", "10Y", "30Y"):
            if t in jgb.frame.columns:
                global_rows.append(R(jgb, f"JGB {t}", col=t, mode="rates"))
    if long_ust and long_ust.ok and jgb.ok and "10Y" in jgb.frame.columns:
        d = an.align_recent({"u": long_ust.col, "j": jgb.frame["10Y"]})
        if d.empty:
            st.caption("UST and JGB have no recent overlapping observations.")
        else:
            spd = (d["u"] - d["j"]) * 100
            global_rows.append(
                monitor.Row(
                    "10y UST − JGB",
                    spd,
                    float(spd.iloc[-1]),
                    unit="bp",
                    dp=0,
                    mode="rates",
                    chg_unit="pts",
                    chg_dp=0,
                    as_of=min(long_ust.as_of, jgb.as_of),
                )
            )
    if eur.ok and "10Y" in eur.frame.columns:
        global_rows.append(R(eur, "EUR AAA 10Y", col="10Y", mode="rates"))
        if long_ust and long_ust.ok:
            d = an.align_recent({"u": long_ust.col, "e": eur.frame["10Y"]})
            if d.empty:
                st.caption("UST and EUR have no recent overlapping observations.")
            else:
                spd = (d["u"] - d["e"]) * 100
                global_rows.append(
                    monitor.Row(
                        "10y UST − EUR AAA",
                        spd,
                        float(spd.iloc[-1]),
                        unit="bp",
                        dp=0,
                        mode="rates",
                        chg_unit="pts",
                        chg_dp=0,
                        as_of=min(long_ust.as_of, eur.as_of),
                    )
                )
    global_rows.append(R(estr, "EUR STR", mode="rates"))
    if jpy is not None and jpy.ok:
        global_rows.append(R(jpy, "USDJPY", mode="perf", unit="", dp=2, chg_unit="%"))
    dxy = mkt.get("DX-Y.NYB")
    if dxy and dxy.ok:
        global_rows.append(R(dxy, "DXY", mode="perf", unit="", dp=2, chg_unit="%"))

    groups = [
        ("US Treasuries", rates_rows),
        ("Curve", curve_rows),
        ("Credit", credit_rows),
        ("Front end & funding", front_rows),
        ("Inflation & term premium", infl_rows),
        ("Volatility & conditions", vol_rows),
        ("Global", global_rows),
    ]
    derived_checks = {
        "SOFR − IORB": ((sofr_on, "percentRate"), (iorb, None)),
        "CP A2/P2 − AA": ((cp.get("RIFSPPNA2P2D90NB"), None), (cp.get("DCPN3M"), None)),
        "CCC − BB dispersion": ((ccc, None), (bb, None)),
        "10y UST − JGB": ((long_ust, None), (jgb, "10Y")),
        "10y UST − EUR AAA": ((long_ust, None), (eur, "10Y")),
    }
    for _, rows in groups:
        for row in rows:
            if row is not None and row.label in derived_checks:
                row.input_checks = tuple(
                    (source, column)
                    for source, column in derived_checks[row.label]
                    if source is not None
                )
                row.inputs = tuple(source for source, _ in row.input_checks)
    ui.quality_summary(
        [
            check
            for _, rows in groups
            for row in rows
            if row is not None
            for check in monitor.source_checks(row)
        ]
        + [
            (s, None)
            for s in (
                f.get("BAMLH0A0HYM2"),
                f.get("VIXCLS"),
                *slow.values(),
                mkt.get("^MOVE"),
                mkt.get("^GSPC"),
                mkt.get("HG=F"),
                mkt.get("GC=F"),
            )
            if s is not None
        ]
    )
    monitor_view.render(groups)
    st.markdown(
        '<div class="ficc-help">'
        f"One convention throughout: <span style='color:{theme.RED_RATE}'>red</span> "
        f"= the number rose, <span style='color:{theme.BLUE_RATE}'>blue</span> = it "
        "fell — for every row, and for the sparkline too. Not good/bad, because "
        "tighter spreads are only good if you are long. Changes are calendar "
        "lookbacks (1W = seven days back). Rates and OAS changes are in bp; FX/DXY "
        "changes are percent returns; other index levels use points. Hover a change "
        "for its unit. 1D is left blank for series that "
        "do not print daily. Range is each series against its trailing three "
        "years, or less where the source serves less; "
        f"<span style='color:{theme.SERIOUS}'>amber</span> marks past the 10th/90th "
        "percentile. 'As of' is the source's observation date, not the pull time. "
        "▲ marks a data warning; inspect the warnings above for details. "
        "Session dates use the provider's trading calendar."
        "</div>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------- the charts
    ui.section("Curves", "US, Japan, and the forward path the market is pricing")
    c1, c2 = ui.columns([1.15, 1])
    with c1:
        fig = go.Figure()
        if ust.ok:
            snap = an.curve_snapshot(ust.frame, treasury.TENORS, offsets=(0,))
            cur = snap[snap.offset == 0]
            fig.add_trace(
                go.Scatter(
                    x=cur["years"],
                    y=cur["yield"],
                    name="UST",
                    mode="lines+markers",
                    line=dict(width=2.2, color=theme.BLUE),
                    marker=dict(size=6),
                    hovertemplate="%{y:.2f}%<extra>UST</extra>",
                )
            )
        if sofr_fwd.ok:
            fw = sofr_fwd.frame
            fig.add_trace(
                go.Scatter(
                    x=fw["years_fwd"],
                    y=fw["implied_rate"],
                    name="SOFR fwd",
                    mode="lines+markers",
                    line=dict(width=2.2, color=theme.ORANGE),
                    marker=dict(size=6),
                    customdata=pd.to_datetime(fw["observed_at"]).dt.strftime("%d %b %Y"),
                    hovertemplate="%{y:.2f}% · quote %{customdata}<extra>SOFR fwd</extra>",
                )
            )
        if jgb.ok:
            jr = jgb.frame.iloc[-1]
            xs = [mof.TENORS[c] for c in jgb.frame.columns if c in mof.TENORS and pd.notna(jr[c])]
            ys = [float(jr[c]) for c in jgb.frame.columns if c in mof.TENORS and pd.notna(jr[c])]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    name="JGB",
                    mode="lines+markers",
                    line=dict(width=2.2, color=theme.AQUA),
                    marker=dict(size=6),
                    hovertemplate="%{y:.2f}%<extra>JGB</extra>",
                )
            )
        fig.update_layout(
            title="Yield curves — US & Japan",
            xaxis=dict(
                type="log",
                tickvals=[0.25, 1, 2, 5, 10, 30],
                ticktext=["3m", "1y", "2y", "5y", "10y", "30y"],
            ),
            yaxis=dict(ticksuffix="%"),
        )
        ui.chart(fig, height=H_TALL, compact=True)
    with c2:
        if ust.ok:
            ch = an.curve_changes(ust.frame, treasury.TENORS, dict(monitor.LOOKBACKS))
            cols = [c for c in ("1D", "1W", "1M", "3M") if c in ch.columns]
            raw = ch[cols].T.values.astype(float)
            relative = st.checkbox(
                "Scale each lookback separately",
                key="heatmap_relative",
                help="Off: equal colours mean equal bp moves across every row. "
                "On: highlight the biggest move within each lookback.",
            )
            limit = max(1.0, float(np.nanmax(np.abs(raw)))) if np.isfinite(raw).any() else 1.0
            plotted = raw.copy()
            if relative:
                for i in range(raw.shape[0]):
                    m = np.nanmax(np.abs(raw[i])) if np.isfinite(raw[i]).any() else 0
                    plotted[i] = raw[i] / m if m else raw[i]
                limit = 1.0
            labels = [
                t.replace("1.5 Month", "6 Wk").replace(" Mo", "m").replace(" Yr", "y")
                for t in ch["tenor"]
            ]
            fig = go.Figure(
                go.Heatmap(
                    z=plotted,
                    x=labels,
                    y=cols,
                    customdata=[[f"{value:+.1f}" for value in row] for row in raw],
                    colorscale=theme.DIVERGING,
                    zmid=0,
                    zmin=-limit,
                    zmax=limit,
                    text=[
                        [
                            ("0" if abs(value) < 0.5 else f"{value:+.0f}")
                            if np.isfinite(value)
                            else "—"
                            for value in row
                        ]
                        for row in raw
                    ],
                    texttemplate="%{text}",
                    textfont=dict(size=10),
                    xgap=1,
                    ygap=1,
                    showscale=False,
                    hovertemplate="%{x} · %{y}: %{customdata} bp<extra></extra>",
                )
            )
            fig.update_layout(
                title="Change by tenor — "
                + ("relative within each row" if relative else "shared bp scale"),
                yaxis=dict(autorange="reversed"),
                xaxis=dict(tickangle=-60),
            )
            ui.chart(fig, height=H_TALL, legend=False, unified=False, compact=True)
            st.caption(
                "Numbers are bp moves. "
                + (
                    "Colour is relative within each row; colours do not compare magnitude across rows."
                    if relative
                    else f"Equal colours mean equal moves across all rows (scale ±{limit:.0f}bp)."
                )
                + " Hover for one decimal place. 1W/1M/3M use calendar lookbacks, as in the monitor."
            )

    # Credit leads this section and sits on the left: the eye lands left-first
    # on a portrait screen, and unlike the Fed path -- already summarised in the
    # status strip and in three front-end table rows -- credit has no numeric
    # stand-in above.
    ui.section("Credit, policy & funding", "")
    c1, c2 = ui.columns(2)
    with c1:
        fig = go.Figure()
        for s_, color in ((ig, theme.BLUE), (hy, theme.ORANGE)):
            if s_ and s_.ok:
                d = s_.col * 100
                fig.add_trace(
                    go.Scatter(
                        x=d.index,
                        y=d,
                        name=s_.label.replace(" OAS", ""),
                        line=dict(width=1.8, color=color),
                        hovertemplate=f"%{{y:.0f}}bp<extra>{s_.label}</extra>",
                    )
                )
        # Log scale, not a second axis: IG near 90bp against HY near 275bp on a
        # shared linear axis flattens IG into a dead straight line. A log axis
        # makes proportional moves in both legible on ONE axis -- a dual axis
        # would invite exactly the false comparison it appears to solve.
        fig.update_layout(title="IG & HY OAS (log scale)", yaxis=dict(title="bp", type="log"))
        ui.chart(fig, height=H, compact=True)
    with c2:
        if not dispersion.empty:
            q = dispersion
            z = an.zscore(q, 5)
            fig = go.Figure(
                go.Scatter(
                    x=q.index,
                    y=q,
                    name="CCC−BB",
                    line=dict(width=1.8, color=theme.RED_RATE),
                    hovertemplate="%{y:.0f}bp<extra></extra>",
                )
            )
            fig.update_layout(
                title=f"CCC−BB dispersion · {q.iloc[-1]:.0f}bp"
                + (f" ({z.verdict_width})" if z else ""),
                yaxis=dict(title="bp"),
            )
            ui.chart(fig, height=H, legend=False, compact=True)

    c1, c2 = ui.columns(2)
    with c1:
        if ff.ok:
            d = ff.frame
            fig = go.Figure(
                go.Scatter(
                    x=d.index,
                    y=d["implied_rate"],
                    mode="lines+markers",
                    line=dict(width=2, color=theme.VIOLET),
                    marker=dict(size=5),
                    name="Implied EFFR",
                    customdata=pd.to_datetime(d["observed_at"]).dt.strftime("%d %b %Y"),
                    hovertemplate="%{x|%b %Y}: %{y:.3f}% · quote %{customdata}<extra></extra>",
                )
            )
            if effr.ok:
                fig.add_hline(
                    y=effr.latest("percentRate"), line=dict(color=theme.MUTED, width=1, dash="dot")
                )
            fig.update_layout(title="Fed path — fed funds futures", yaxis=dict(ticksuffix="%"))
            ui.chart(fig, height=H, legend=False, compact=True)
    with c2:
        if not funding.empty:
            sp_ = funding.tail(400)
            fig = go.Figure(
                go.Scatter(
                    x=sp_.index,
                    y=sp_,
                    line=dict(width=1.8, color=theme.MAGENTA),
                    name="SOFR−IORB",
                    hovertemplate="%{y:+.1f}bp<extra></extra>",
                )
            )
            fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1, dash="dot"))
            fig.update_layout(
                title=f"Reserve scarcity — SOFR−IORB · {sp_.iloc[-1]:+.0f}bp",
                yaxis=dict(title="bp"),
            )
            ui.chart(fig, height=H, legend=False, compact=True)

    ui.section("Carry & global linkage", "")
    c1, c2 = ui.columns([1.15, 1])
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
            fig.add_trace(
                go.Bar(
                    x=cr["tenor"],
                    y=cr["carry_bp"],
                    name="Carry",
                    marker=dict(color=theme.BLUE),
                    hovertemplate="%{y:.1f}bp<extra>carry</extra>",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=cr["tenor"],
                    y=cr["roll_bp"],
                    name="Roll",
                    marker=dict(color=theme.AQUA),
                    hovertemplate="%{y:.1f}bp<extra>roll</extra>",
                )
            )
            # Markers, not a line: breakeven runs 2-14bp against carry bars up
            # to 50bp, so as a line it lies flat on the baseline and reads as
            # chart furniture rather than as the number that matters.
            fig.add_trace(
                go.Scatter(
                    x=cr["tenor"],
                    y=cr["breakeven_bp"],
                    name="Breakeven",
                    mode="markers+text",
                    marker=dict(
                        size=10,
                        color=theme.ORANGE,
                        symbol="diamond",
                        line=dict(width=1.5, color=theme.SURFACE),
                    ),
                    text=[f"{v:.0f}" for v in cr["breakeven_bp"]],
                    textposition="top center",
                    textfont=dict(size=8.5, color=theme.ORANGE),
                    hovertemplate="%{y:.1f}bp<extra>breakeven</extra>",
                )
            )
            fig.update_layout(
                barmode="relative",
                yaxis=dict(title="bp"),
                title=f"3m carry & roll, financed at {front:.2f}%",
            )
            ui.chart(fig, height=H, unified=False, compact=True)
    with c2:
        if (
            jpy is not None
            and jpy.ok
            and long_ust
            and long_ust.ok
            and jgb.ok
            and "10Y" in jgb.frame
        ):
            dfb = an.align_recent({"spot": jpy.col, "ust": long_ust.col, "jgb": jgb.frame["10Y"]})
            if dfb.empty:
                st.caption("USDJPY and rate curves have no recent overlapping observations.")
            else:
                dfb["diff"] = (dfb["ust"] - dfb["jgb"]) * 100
                dfb = dfb.tail(756)
                dfb["b"] = an.rolling_beta(dfb["spot"], dfb["diff"], 250) * 100
                fig = go.Figure(
                    go.Scatter(
                        x=dfb.index,
                        y=dfb["b"],
                        name="beta",
                        line=dict(width=1.8, color=theme.VIOLET),
                        hovertemplate="%{y:.1f} yen/100bp<extra></extra>",
                    )
                )
                fig.add_hline(y=0, line=dict(color=theme.AXIS, width=1, dash="dot"))
                fig.update_layout(
                    title=f"USDJPY beta to UST−JGB · {dfb['b'].iloc[-1]:.1f} yen/100bp",
                    yaxis=dict(title="yen/100bp"),
                )
                ui.chart(fig, height=H, legend=False, compact=True)

    ui.sources_note([ust, jgb, sofr_fwd, hy, move, eur])


def _slope_row(ust, name: str, lo: str, hi: str):
    """A curve slope as a monitor row. Already in bp, so changes are whole bp."""
    ser = an.spread(ust.frame, hi, lo)
    if ser.empty:
        return None
    return monitor.Row(
        name,
        ser,
        float(ser.iloc[-1]),
        unit="bp",
        dp=0,
        mode="rates",
        chg_unit="pts",
        chg_dp=0,
        as_of=ust.as_of,
        inputs=(ust,),
        input_checks=((ust, lo), (ust, hi)),
    )


def _treasury_groups(ust):
    rates_rows, curve_rows = [], []
    if ust.ok:
        if "3 Mo" in ust.frame:
            rates_rows.append(monitor.row_from(ust, "3m bill", col="3 Mo", mode="rates"))
        for tenor in ("2 Yr", "5 Yr", "10 Yr", "30 Yr"):
            if tenor in ust.frame:
                rates_rows.append(
                    monitor.row_from(ust, f"UST {tenor.replace(' Yr', 'Y')}", col=tenor)
                )
        for name, lo, hi in (
            ("2s10s", "2 Yr", "10 Yr"),
            ("5s30s", "5 Yr", "30 Yr"),
            ("3m10y", "3 Mo", "10 Yr"),
        ):
            if lo in ust.frame and hi in ust.frame:
                curve_rows.append(_slope_row(ust, name, lo, hi))
        if {"2 Yr", "5 Yr", "10 Yr"} <= set(ust.frame):
            fly = an.butterfly(ust.frame, "2 Yr", "5 Yr", "10 Yr")
            if not fly.empty:
                curve_rows.append(
                    monitor.Row(
                        "2s5s10s fly",
                        fly,
                        float(fly.iloc[-1]),
                        unit="bp",
                        dp=0,
                        chg_unit="pts",
                        chg_dp=0,
                        as_of=ust.as_of,
                        inputs=(ust,),
                        input_checks=tuple((ust, tenor) for tenor in ("2 Yr", "5 Yr", "10 Yr")),
                    )
                )
    return [("US Treasuries", rates_rows), ("Curve", curve_rows)]
