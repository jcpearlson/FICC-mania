"""Dashboard loads share inputs and preserve the adapters' failure contracts."""

import os
import time
from collections import Counter
from threading import Barrier

import pandas as pd
import pytest

from ficc import dashboard_data, http, regime
from ficc.contract import Status


@pytest.fixture(autouse=True)
def clear_dashboard_cache():
    dashboard_data.load.clear()
    dashboard_data.load_treasury.clear()
    yield
    dashboard_data.load.clear()
    dashboard_data.load_treasury.clear()


def test_load_fetches_only_dashboard_inputs_once(fake_net, monkeypatch):
    import yfinance

    requests = []
    downloads = []

    def get(source, url, **kwargs):
        requests.append((source, url))
        return fake_net.fake_get(source, url, **kwargs)

    def download(symbols, **kwargs):
        downloads.append((set(symbols), kwargs["period"]))
        return fake_net.fake_download(symbols, **kwargs)

    monkeypatch.setattr(http, "get", get)
    monkeypatch.setattr(yfinance, "download", download)
    year = pd.Timestamp.today().year
    treasury = dashboard_data.load_treasury([year])
    treasury_requests = sum(source == "treasury" for source, _ in requests)
    data = dashboard_data.load([year])

    expected_fred = {
        "DFII10",
        "T10YIE",
        "T5YIFR",
        "THREEFYTP10",
        "IORB",
        "DGS10",
        "BAMLC0A0CM",
        "BAMLH0A0HYM2",
        "BAMLEMCBPIOAS",
        "BAMLHE00EHYIOAS",
        "BAMLC0A4CBBB",
        "BAMLH0A1HYBB",
        "BAMLH0A3HYC",
        "NFCI",
        "STLFSI4",
        "RIFSPPNA2P2D90NB",
        "DCPN3M",
        "VIXCLS",
        "RRPONTSYD",
    }
    counts = Counter(url.rsplit("=", 1)[-1] for source, url in requests if source == "fred")
    assert counts == Counter(dict.fromkeys(expected_fred, 1))
    assert sum(source == "treasury" for source, _ in requests) == treasury_requests
    assert all(source != "treasurydirect" for source, _ in requests)
    assert len(downloads) == 3
    assert ({"^MOVE", "^GSPC", "HG=F", "GC=F", "DX-Y.NYB", "JPY=X"}, "5y") in downloads
    assert data.ust.frame.equals(treasury.frame)
    assert data.f["BAMLH0A0HYM2"] is data.head["BAMLH0A0HYM2"]
    assert data.move is data.mkt["^MOVE"]
    assert data.jpy.ok and data.eur.ok and data.effr.ok
    assert set(data.ladder) == {"BAMLC0A4CBBB", "BAMLH0A1HYBB", "BAMLH0A3HYC"}
    assert set(data.plumbing) == {"RRPONTSYD"}
    assert all(series.cadence_days == 7 for series in data.slow.values())
    assert regime.analyze(data.f, data.slow, data.mkt).coverage == pytest.approx(1)


def test_provider_failure_does_not_discard_other_markets(fake_net, monkeypatch):
    def get(source, url, **kwargs):
        if source == "fred":
            raise ConnectionError("FRED unavailable")
        return fake_net.fake_get(source, url, **kwargs)

    monkeypatch.setattr(http, "get", get)
    data = dashboard_data.load([pd.Timestamp.today().year])
    assert all(series.status is Status.FAILED for series in data.head.values())
    assert data.vix.status is Status.FAILED
    assert data.ust.ok and data.jgb.ok and data.sofr_on.ok and data.move.ok and data.eur.ok


def test_expired_disk_cache_survives_network_outage(fake_net, monkeypatch, tmp_path):
    import yfinance

    data = dashboard_data.load([pd.Timestamp.today().year])
    expired = time.time() - 2 * 86400
    for path in tmp_path.glob("*.pkl"):
        os.utime(path, (expired, expired))
    dashboard_data.load.clear()
    dashboard_data.load_treasury.clear()

    def offline(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(http, "get", offline)
    monkeypatch.setattr(yfinance, "download", offline)
    fallback = dashboard_data.load([pd.Timestamp.today().year])
    for fresh, cached in (
        (data.ust, fallback.ust),
        (data.jgb, fallback.jgb),
        (data.vix, fallback.vix),
        (data.sofr_fwd, fallback.sofr_fwd),
        (data.jpy, fallback.jpy),
        (data.eur, fallback.eur),
        (data.effr, fallback.effr),
    ):
        assert cached.ok and cached.status is Status.STALE
        assert cached.frame.equals(fresh.frame)
        assert cached.fetched_at == fresh.fetched_at


def test_independent_providers_run_concurrently(fake_net, monkeypatch):
    barrier = Barrier(4, timeout=10)

    def synchronized(fn):
        def call(*args, **kwargs):
            barrier.wait()
            return fn(*args, **kwargs)

        return call

    monkeypatch.setattr(dashboard_data, "_load_fred", synchronized(dashboard_data._load_fred))
    monkeypatch.setattr(dashboard_data, "_load_market", synchronized(dashboard_data._load_market))
    monkeypatch.setattr(dashboard_data.mof, "curve", synchronized(dashboard_data.mof.curve))
    monkeypatch.setattr(dashboard_data, "_load_funding", synchronized(dashboard_data._load_funding))
    data = dashboard_data.load([pd.Timestamp.today().year])
    assert data.ust.ok and data.jgb.ok and data.move.ok and data.vix.ok
