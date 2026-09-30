import datetime as dt

import pandas as pd
import pytest

from ficc import cache, quality
from ficc.contract import Series, Status, failed, status_from, worst_status


@pytest.fixture
def tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def test_empty_payload_never_overwrites_good_cache(tmp_cache):
    good = pd.DataFrame({"v": [1.0]})
    cache.through("t", "k", 0, lambda: good)
    frame, meta = cache.through("t", "k", 0, lambda: pd.DataFrame())
    assert meta.startswith("stale") and frame.equals(good)


def test_empty_payload_with_no_fallback_raises(tmp_cache):
    with pytest.raises(cache.EmptyPayload):
        cache.through("t", "fresh", 0, lambda: pd.DataFrame({"v": [None]}))


def test_status_mapping():
    assert status_from("live") is Status.OK
    assert status_from("cached") is Status.CACHED
    assert status_from("stale:30") is Status.STALE
    assert worst_status(["live", "stale:1", "cached"]) is Status.STALE


def _daily(values, end=None):
    end = end or pd.Timestamp.today().normalize()
    return pd.DataFrame({"v": values}, index=pd.bdate_range(end=end, periods=len(values)))


def test_quality_flags_flatline_on_market_prices_only():
    flat = _daily([1.0] * 300)
    assert any("flat" in f for f in quality.assess(Series("x", "x", flat, "Yahoo Finance")).flags)
    assert not any("flat" in f for f in quality.assess(Series("x", "x", flat, "FRED")).flags)


def test_quality_flags_jump_and_gap():
    vals = [float(i % 5) * 0.01 for i in range(300)] + [50.0]
    r = quality.assess(Series("x", "x", _daily(vals), "FRED"))
    assert any("robust" in f for f in r.flags)
    gappy = pd.concat([_daily([1.0, 2.0] * 100, end=pd.Timestamp.today() - pd.Timedelta(days=90)),
                       _daily([3.0, 4.0] * 10)])
    assert any("gap" in f for f in quality.assess(Series("g", "g", gappy, "FRED")).flags)


def test_quality_failed_series():
    r = quality.assess(failed("k", "lbl", "SRC", "boom"))
    assert r.worst == "failed" and r.flags == ["boom"]


def test_future_dates_preserved_and_flagged():
    fwd = pd.DataFrame({"v": [1.0]}, index=[pd.Timestamp.today() + pd.Timedelta(days=3)])
    s = Series("iorb", "IORB", fwd, "FRED", as_of=(dt.date.today() + dt.timedelta(days=3)))
    assert s.lag_days() == -3
    assert any("future" in f for f in quality.assess(s).flags)
    from ficc.ui import badge_html
    assert "future date" in badge_html(s) and "today" not in badge_html(s)


def test_next_day_fx_is_explicit_session():
    from ficc.ui import badge_html
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    s = Series("fx", "FX", _daily([1, 2]), "Yahoo Finance", as_of=tomorrow,
               date_basis="session")
    assert "source session" in badge_html(s) and "today" not in badge_html(s)
    assert not any("future" in f for f in quality.assess(s).flags)


def test_cached_and_stale_payloads_keep_actual_pull_time(tmp_cache):
    frame, _ = cache.through("t", "k", 999, lambda: _daily([1, 2]))
    pulled = frame.attrs[cache.FETCHED_AT]
    cached, meta = cache.through("t", "k", 999, lambda: pytest.fail("network on cache hit"))
    assert meta == "cached" and cached.attrs[cache.FETCHED_AT] == pulled
    stale, meta = cache.through("t", "k", 0, lambda: pd.DataFrame())
    assert meta.startswith("stale")
    assert Series("k", "K", stale, "T").fetched_at == pulled


def test_legacy_cache_uses_write_time(tmp_cache):
    import os
    import pickle
    path = cache._path("t", "legacy")
    path.write_bytes(pickle.dumps(_daily([1, 2])))
    stamp = 1700000000
    os.utime(path, (stamp, stamp))
    frame, _, _ = cache.load("t", "legacy", 999)
    assert frame.attrs[cache.FETCHED_AT].timestamp() == stamp
