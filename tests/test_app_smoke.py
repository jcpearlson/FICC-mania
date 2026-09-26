"""Render the whole app offline against the fake network."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_every_tab_renders_without_exceptions(fake_net):
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    for needle in ("2s5s10s fly", "EUR AAA 10Y", "CP A2/P2", "plumbing",
                   "Treasury auctions", "Positioning", "Data quality"):
        assert needle in html or any(needle in str(c) for c in at.main), needle


def test_new_charts_are_drawn(fake_net):
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=180).run()
    specs = " ".join(c.proto.spec for c in at.get("plotly_chart"))
    for title in ("Net liquidity", "CP quality spread", "Primary dealer take-down",
                  "Leveraged funds", "EUR AAA spot", "UST 1m ago"):
        assert title in specs, title
