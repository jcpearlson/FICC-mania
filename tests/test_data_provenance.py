"""Regression coverage for source units, quote dates and dashboard warnings."""
import pandas as pd
import pytest

from ficc import analytics as an, cache, monitor, quality
from ficc.contract import Series, Status, failed
from ficc.sources import fred, market


def test_liquidity_source_units_end_to_end(fake_net):
    bs, tga, rrp = (fred.get(key) for key in ('WALCL', 'WTREGEN', 'RRPONTSYD'))
    result = an.net_liquidity(bs.col, tga.col, rrp.col)
    at = result.index[-1]
    assert result.iloc[-1] == pytest.approx(bs.col.asof(at)/1e6 - tga.col.asof(at)/1e6 - rrp.col.asof(at)/1e3)
    assert 3 < result.iloc[-1] < 8


def test_futures_old_mixed_quotes_warn(fake_net, monkeypatch):
    import yfinance
    def download(*a, **kw):
        frame = fake_net.fake_download(*a, **kw)
        frame.index -= pd.Timedelta(days=10)
        symbol = frame['Close'].columns[0]
        frame.loc[frame.index[-1], ('Close', symbol)] = float('nan')
        return frame
    monkeypatch.setattr(yfinance, 'download', download)
    strip = market.futures_strip('SR3', 4)
    assert strip.ok and strip.lag_days() >= 10
    assert strip.as_of == pd.Timestamp(strip.frame.observed_at.min()).date()
    flags = quality.assess(strip, 'implied_rate').flags
    assert any('mixed quote' in f for f in flags) and any('stale' in f for f in flags)
    assert not any('gap' in f or 'short' in f for f in flags)


def test_commodity_nested_fallback_preserves_status_and_pull(fake_net, monkeypatch):
    good = market.commodity_curve('CL', 4)
    monkeypatch.setattr(cache, 'TTL_INTRADAY', 0)
    monkeypatch.setattr(cache, 'TTL_DAILY', 0)
    import yfinance
    monkeypatch.setattr(yfinance, 'download', lambda *a, **kw: pd.DataFrame())
    stale = market.commodity_curve('CL', 4)
    assert stale.ok and stale.status is Status.STALE
    assert stale.fetched_at == good.fetched_at and stale.as_of == good.as_of


def test_monitor_retains_failed_and_derived_warnings():
    down = failed('x', 'Credit source', 'FRED', 'network down')
    row = monitor.row_from(down, 'IG OAS')
    derived = monitor.Row('Derived', None, None, inputs=(down,))
    old = Series('d', 'Old rate', pd.DataFrame({'v': [6.0]},
                 index=[pd.Timestamp.today()-pd.Timedelta(days=12)]), 'FRED')
    derived.inputs = (down, old)
    html = monitor.render_html([('G', [row, derived])])
    assert html.count('Data warning') == 2 and 'network down' in html
    assert 'Old rate' in html and 'stale' in html
    assert 'FRED: no successful data pull' in html


def test_wide_curve_warning_names_the_checked_tenor():
    s = Series('curve', 'JGB par curve',
               pd.DataFrame({'10Y': [2., 3.]}, index=pd.to_datetime(['2026-01-01', '2026-09-01'])),
               'MOF')
    report = quality.assess(s, '10Y')
    assert report.label == 'JGB par curve · 10Y'
