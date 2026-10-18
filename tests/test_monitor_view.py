"""Exercise saved watchlists through the dashboard's controls and exports."""

from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ficc import workspace
from ficc.workspace import Watchlist, WatchlistError

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _table(app):
    return next(m.value for m in app.markdown if '<table class="mon' in m.value)


def test_saved_order_default_view_export_navigation_and_cache_clear(fake_net, monkeypatch):
    downloads = []
    download_button = st.download_button

    def capture_download(label, data, *args, **kwargs):
        if kwargs.get("key") == "monitor_csv":
            downloads.append(data)
        return download_button(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture_download)
    st.cache_data.clear()
    app = AppTest.from_file(APP, default_timeout=180).run()
    labels = ["HY OAS", "UST 10Y"]
    app.multiselect(key="watchlist_labels").set_value(labels)
    app.checkbox(key="watchlist_default").check()
    app.button(key="save_watchlist").click().run()
    assert not app.exception
    assert workspace.load_watchlist() == Watchlist(tuple(labels), "My watchlist")
    saved_file = workspace.WATCHLIST_PATH.read_bytes()

    app = AppTest.from_file(APP, default_timeout=180).run()
    assert not app.exception
    assert app.radio(key="monitor_view").value == "My watchlist"
    assert app.multiselect(key="watchlist_labels").value == labels
    table = _table(app)
    assert table.index("HY OAS") < table.index("UST 10Y")
    assert "UST 2Y" not in table
    assert pd.read_csv(StringIO(downloads[-1]))["Instrument"].tolist() == labels

    app.selectbox(key="page_picker").select("Market health").run()
    app.selectbox(key="page_picker").select("Dashboard").run()
    assert not app.exception
    assert app.radio(key="monitor_view").value == "My watchlist"
    assert app.multiselect(key="watchlist_labels").value == labels
    next(button for button in app.button if button.label == "Clear cache").click().run()
    assert not app.exception
    assert workspace.WATCHLIST_PATH.read_bytes() == saved_file
    assert "UST 2Y" not in _table(app)
    assert pd.read_csv(StringIO(downloads[-1]))["Instrument"].tolist() == labels


def test_failed_save_keeps_saved_instruments_effective(fake_net, monkeypatch):
    saved = Watchlist(("UST 2Y",), "My watchlist")
    workspace.save_watchlist(saved)
    saved_file = workspace.WATCHLIST_PATH.read_bytes()

    def cannot_save(value):
        raise WatchlistError("Preferences directory is read-only.")

    monkeypatch.setattr(workspace, "save_watchlist", cannot_save)
    st.cache_data.clear()
    app = AppTest.from_file(APP, default_timeout=180).run()
    app.multiselect(key="watchlist_labels").set_value(["UST 10Y"])
    app.checkbox(key="watchlist_default").uncheck()
    app.button(key="save_watchlist").click().run()
    assert not app.exception
    assert any("read-only" in error.value for error in app.error)
    assert app.radio(key="monitor_view").value == "My watchlist"
    table = _table(app)
    assert "UST 2Y" in table and "UST 10Y" not in table
    assert workspace.load_watchlist() == saved
    assert workspace.WATCHLIST_PATH.read_bytes() == saved_file


def test_corrupt_file_recovery_and_unavailable_saved_instruments(fake_net):
    workspace.WATCHLIST_PATH.write_bytes(b"{broken")
    st.cache_data.clear()
    app = AppTest.from_file(APP, default_timeout=180).run()
    assert not app.exception
    assert any("not valid" in warning.value for warning in app.warning)
    app.text_input(key="monitor_query").input("UST").run()
    assert any("not valid" in warning.value for warning in app.warning)
    assert workspace.WATCHLIST_PATH.read_bytes() == b"{broken"

    app.multiselect(key="watchlist_labels").set_value(["UST 10Y"])
    app.button(key="save_watchlist").click().run()
    app.text_input(key="monitor_query").input("").run()
    assert not app.exception
    assert not any("not valid" in warning.value for warning in app.warning)
    assert workspace.load_watchlist().labels == ("UST 10Y",)

    unavailable = Watchlist(("Retired instrument",), "My watchlist")
    workspace.save_watchlist(unavailable)
    app = AppTest.from_file(APP, default_timeout=180).run()
    assert not app.exception
    assert app.multiselect(key="watchlist_labels").value == ["Retired instrument"]
    assert any("Retired instrument" in caption.value for caption in app.caption)
    assert any("unavailable" in info.value.lower() for info in app.info)
    app.button(key="save_watchlist").click().run()
    assert not app.exception
    assert workspace.load_watchlist() == unavailable
