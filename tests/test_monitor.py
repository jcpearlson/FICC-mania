import pandas as pd
import pytest

from ficc import monitor


def test_weekly_series_changes_are_calendar_based():
    wk = pd.Series(range(20), index=pd.date_range("2025-01-01", periods=20, freq="W-WED"),
                   dtype=float)
    # 1D is blank: the previous print is a week old.
    assert monitor._change(wk, None, "pts") is None
    # 1W is one print back, not five.
    assert monitor._change(wk, pd.DateOffset(weeks=1), "pts") == pytest.approx(1.0)
    assert monitor._change(wk, pd.DateOffset(months=1), "pts") == pytest.approx(5.0)


def test_daily_change_and_bp_units():
    d = pd.Series([4.00, 4.05], index=pd.to_datetime(["2025-03-06", "2025-03-07"]))
    assert monitor._change(d, None, "bp") == pytest.approx(5.0)


def test_insufficient_history_is_blank():
    d = pd.Series([1.0, 2.0], index=pd.bdate_range("2025-03-03", periods=2))
    assert monitor._change(d, pd.DateOffset(months=3), "pts") is None


def test_render_escapes_labels_and_trims_spark():
    ser = pd.Series(range(252 * 10), index=pd.bdate_range("2014-01-01", periods=252 * 10),
                    dtype=float)
    row = monitor.Row("<b>x</b>", ser, float(ser.iloc[-1]))
    html = monitor.render_html([("G", [row, None])])
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert html.count("<polyline") == 1


def test_search_export_and_explicit_change_units():
    dates = pd.to_datetime(['2026-01-01', '2026-01-02'])
    hy = monitor.Row('HY OAS', pd.Series([3., 3.1], index=dates), 310., unit='bp', scale=100)
    fx = monitor.Row('USDJPY', pd.Series([100., 101.], index=dates), 101., chg_unit='%')
    groups = [('Credit', [hy]), ('Global', [fx])]
    selected = monitor.filter_groups(groups, '  hy  ')
    frame = monitor.to_frame(selected)
    assert frame.Instrument.tolist() == ['HY OAS']
    assert frame['1D'].iloc[0] == pytest.approx(10.)
    assert frame['Change unit'].iloc[0] == 'bp'
    assert monitor.to_frame(monitor.filter_groups(groups, group='Global'))['1D'].iloc[0] == pytest.approx(1.)
    assert monitor.to_frame(monitor.filter_groups(groups, 'nothing')).empty
    html = monitor.render_html(groups)
    assert '1D change in bp' in html and '1D change in % return' in html
