"""Render and exercise the app offline, including lazy tab navigation."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["Dashboard", "Market health", "Rates & curves", "Credit, CLOs & loans",
         "FX & commodities", "Sources"]


def test_every_tab_renders_without_exceptions(fake_net):
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    htmls, specs = [], []
    for page in PAGES:
        at.selectbox[0].select(page).run()
        assert not at.exception, [e.message for e in at.exception]
        htmls.extend(m.value for m in at.markdown)
        specs.extend(c.proto.spec for c in at.get("plotly_chart"))
    html = " ".join(htmls)
    for removed in ("Rate dur", "Spread dur", "Duration methods & source dates"):
        assert removed not in html
    for needle in ("2s5s10s fly", "EUR AAA 10Y", "CP A2/P2", "plumbing",
                   "Treasury auctions", "Positioning", "Data quality"):
        assert needle in html, needle
    for title in ("Net liquidity", "CP quality spread", "Primary dealer take-down",
                  "Leveraged funds", "EUR AAA spot", "UST 1m ago"):
        assert title in " ".join(specs), title


def test_initial_page_is_lazy_and_refresh_preserves_pull_time(fake_net, tmp_path):
    from ficc import cache
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception
    assert "Positioning" not in " ".join(m.value for m in at.markdown)
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.pkl")}
    at.button[0].click().run()
    assert not at.exception
    assert before == {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.pkl")}
    at.button[1].click().run()
    assert not at.exception
    assert any(p.stat().st_mtime_ns != before.get(p.name) for p in tmp_path.glob("*.pkl"))
    assert cache.CACHE_DIR == tmp_path
    assert "Page rendered" in " ".join(m.value for m in at.markdown)
    at.checkbox[0].check().run()
    assert not at.exception
    assert 'mon mon-full' in " ".join(m.value for m in at.markdown)
    at.checkbox[0].uncheck().run()
    assert 'mon mon-compact' in " ".join(m.value for m in at.markdown)
    at.selectbox[0].select("Sources").run()
    assert not at.exception
    assert at.session_state["page"] == "Sources"
    assert "Data quality" in " ".join(m.value for m in at.markdown)


def test_monitor_filter_and_heatmap_scale_controls(fake_net):
    import json
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.text_input[0].input('HY').run()
    assert not at.exception
    tables = [m.value for m in at.markdown if '<table class="mon' in m.value]
    assert len(tables) == 1 and 'HY OAS' in tables[0] and 'UST 10Y' not in tables[0]
    at.text_input[0].input('no-such-instrument').run()
    assert any('No instruments match' in i.value for i in at.info)
    at.text_input[0].input('').run()
    at.selectbox[1].select('Credit').run()
    tables = [m.value for m in at.markdown if '<table class="mon' in m.value]
    assert 'HY OAS' in tables[0] and 'UST 10Y' not in tables[0]
    def heatmap():
        return next(json.loads(c.proto.spec) for c in at.get('plotly_chart')
                    if json.loads(c.proto.spec)['data'][0]['type'] == 'heatmap')
    assert 'shared bp scale' in heatmap()['layout']['meta']['caption']
    at.checkbox[1].check().run()
    assert 'relative within each row' in heatmap()['layout']['meta']['caption']
    at.selectbox[0].select('Market health').run()
    assert not at.exception
    assert 'How the regime is calculated' in [e.label for e in at.expander]
    assert any('Regime history' in m.value for m in at.markdown)


def test_disjoint_cross_market_histories_render_without_comparisons(fake_net, monkeypatch):
    from ficc.sources import mof
    original = mof.curve
    def disjoint():
        result = original()
        result.frame.index -= pd.Timedelta(days=50000)
        result.as_of = result.frame.index[-1].date()
        return result
    import pandas as pd
    st.cache_data.clear()
    monkeypatch.setattr(mof, 'curve', disjoint)
    at = AppTest.from_file(APP, default_timeout=180).run()
    for page in ('Dashboard', 'Rates & curves', 'FX & commodities'):
        at.selectbox[0].select(page).run()
        assert not at.exception, [e.message for e in at.exception]
        assert any('no recent overlapping observations' in c.value for c in at.caption)


def test_refresh_preserves_selected_analysis_page(fake_net):
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.selectbox[0].select('Market health').run()
    assert at.session_state['page'] == 'Market health'
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state['page'] == 'Market health'
    assert any('Regime history' in m.value for m in at.markdown)
    at.button[1].click().run()
    assert not at.exception
    assert at.session_state['page'] == 'Market health'
