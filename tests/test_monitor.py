import numpy as np
import pandas as pd
import pytest

from ficc import monitor
from ficc.contract import Series, Status


def test_weekly_series_changes_are_calendar_based():
    wk = pd.Series(
        range(20), index=pd.date_range("2025-01-01", periods=20, freq="W-WED"), dtype=float
    )
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
    ser = pd.Series(
        range(252 * 10), index=pd.bdate_range("2014-01-01", periods=252 * 10), dtype=float
    )
    row = monitor.Row("<b>x</b>", ser, float(ser.iloc[-1]))
    html = monitor.render_html([("G", [row, None])])
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert html.count("<polyline") == 1


def test_search_export_and_explicit_change_units():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    hy = monitor.Row("HY OAS", pd.Series([3.0, 3.1], index=dates), 310.0, unit="bp", scale=100)
    fx = monitor.Row("USDJPY", pd.Series([100.0, 101.0], index=dates), 101.0, chg_unit="%")
    groups = [("Credit", [hy]), ("Global", [fx])]
    selected = monitor.filter_groups(groups, "  hy  ")
    frame = monitor.to_frame(selected)
    assert frame.Instrument.tolist() == ["HY OAS"]
    assert frame["1D"].iloc[0] == pytest.approx(10.0)
    assert frame["Change unit"].iloc[0] == "bp"
    assert monitor.to_frame(monitor.filter_groups(groups, group="Global"))["1D"].iloc[
        0
    ] == pytest.approx(1.0)
    assert monitor.to_frame(monitor.filter_groups(groups, "nothing")).empty
    html = monitor.render_html(groups)
    assert "1D change in bp" in html and "1D change in % return" in html


def _move_row(label="Yield", *, last=0.04, count=80, **kwargs):
    changes = np.resize([0.01, -0.02, 0.03, -0.01], count)
    values = 4 + np.r_[0, changes, last].cumsum()
    dates = pd.bdate_range("2026-01-01", periods=len(values))
    series = pd.Series(values, index=dates)
    return monitor.Row(label, series, float(series.iloc[-1]), as_of=dates[-1].date(), **kwargs)


def test_move_rank_compares_each_instrument_with_its_own_history():
    unusual = _move_row("Small unusual move")
    ordinary = _move_row("Large ordinary move", last=0.01)
    ordinary.series *= 100
    ordinary.value *= 100
    ranked = monitor.rank_moves([("Rates", [ordinary, unusual])], as_of=unusual.as_of)
    assert ranked.Instrument.tolist() == ["Small unusual move", "Large ordinary move"]
    assert ranked["Change"].iloc[0] == pytest.approx(4)
    assert ranked["Change unit"].tolist() == ["bp", "bp"]
    assert ranked["Sample count"].tolist() == [80, 80]
    assert ranked["Absolute move percentile"].iloc[0] == pytest.approx(100)
    assert ranked["As of"].iloc[0] == unusual.series.index[-1]
    assert ranked["Previous date"].iloc[0] == unusual.series.index[-2]
    assert (
        len(monitor.rank_moves([("Rates", [ordinary, unusual])], limit=1, as_of=unusual.as_of)) == 1
    )


def test_move_rank_excludes_current_move_and_requires_60_prior_comparisons():
    enough = _move_row(count=60, last=0.005)
    short = _move_row("Short", count=59)
    ranked = monitor.rank_moves([("Rates", [enough, short])], as_of=enough.as_of)
    assert ranked.Instrument.tolist() == ["Yield"]
    assert ranked["Sample count"].iloc[0] == 60
    assert ranked["Absolute move percentile"].iloc[0] == 0


def test_move_rank_excludes_unchanged_administered_rates():
    iorb = _move_row("IORB")
    iorb.series[:] = 4.4
    iorb.value = 4.4
    iorb.inputs = (Series("IORB", "IORB", iorb.series.to_frame(), "FRED"),)
    unchanged = _move_row("Unchanged", last=0)
    moving = _move_row("Moving")
    ranked = monitor.rank_moves([("Rates", [iorb, unchanged, moving])], as_of=moving.as_of)
    assert ranked.Instrument.tolist() == ["Moving"]


@pytest.mark.parametrize("values", [[], [np.nan], [4.0], [np.nan, 4.0]])
def test_move_rank_handles_empty_and_short_finite_history(values):
    dates = pd.bdate_range("2026-01-01", periods=len(values))
    series = pd.Series(values, index=dates, dtype=float)
    row = monitor.Row("Sparse", series, 4.0)
    assert monitor.rank_moves([("Rates", [row])], as_of="2026-01-02").empty


def test_move_rank_preserves_percent_returns_and_bp_series_units():
    spread = _move_row("Slope", unit="bp", chg_unit="pts")
    fx = _move_row("FX", chg_unit="%")
    returns = np.r_[np.resize([0.001, -0.002, 0.003, -0.001], 80), 0.004]
    fx.series = pd.Series(100 * np.r_[1, (1 + returns).cumprod()], index=fx.series.index)
    fx.value = float(fx.series.iloc[-1])
    ranked = monitor.rank_moves([("Global", [spread, fx])], as_of=spread.as_of).set_index(
        "Instrument"
    )
    assert ranked.loc["Slope", "Change"] == pytest.approx(0.04)
    assert ranked.loc["Slope", "Change unit"] == "bp"
    assert ranked.loc["FX", "Change"] == pytest.approx(0.4)
    assert ranked.loc["FX", "Change unit"] == "%"


@pytest.mark.parametrize("status,cadence", [(Status.STALE, 1), (Status.FAILED, 1), (Status.OK, 7)])
def test_move_rank_excludes_unusable_source_inputs(status, cadence):
    row = _move_row()
    row.inputs = (
        Series(
            "x", "Source", row.series.to_frame("value"), "FRED", status=status, cadence_days=cadence
        ),
    )
    assert monitor.rank_moves([("Rates", [row])], as_of=row.as_of).empty


def test_move_rank_checks_dates_for_each_derived_input():
    row = _move_row()
    fresh = Series("a", "A", row.series.to_frame("value"), "FRED")
    old = Series("b", "B", row.series.iloc[:-10].to_frame("value"), "FRED")
    row.inputs = (fresh, old)
    assert monitor.rank_moves([("Rates", [row])], as_of=row.as_of).empty
    row.inputs = (fresh,)
    assert not monitor.rank_moves([("Rates", [row])], as_of=row.as_of).empty
    assert monitor.rank_moves(
        [("Rates", [row])], as_of=pd.Timestamp(row.as_of) + pd.Timedelta(days=5)
    ).empty


def test_move_rank_omits_latest_gap_and_nonfinite_observations():
    gap = _move_row("Gap")
    dates = gap.series.index.to_list()
    dates[-1] = dates[-2] + pd.Timedelta(days=5)
    gap.series.index = pd.DatetimeIndex(dates)
    gap.as_of = dates[-1].date()
    bad = _move_row("Bad")
    bad.series.iloc[-1] = np.inf
    assert monitor.rank_moves([("Rates", [gap, bad])], as_of=gap.as_of).empty


def test_move_rank_omits_current_quality_problems_but_keeps_old_gap_warning():
    jump = _move_row("Jump", last=10)
    flat = _move_row("Flat", last=0)
    flat.series.iloc[-7:] = flat.series.iloc[-7]
    flat.value = float(flat.series.iloc[-1])
    flat.inputs = (Series("flat", "Flat", flat.series.to_frame(), "Yahoo Finance"),)
    healthy = _move_row("Healthy")
    old = pd.Series([3.0, 3.1], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
    healthy.series = pd.concat([old, healthy.series])
    healthy.inputs = (Series("good", "Healthy", healthy.series.to_frame(), "FRED"),)
    ranked = monitor.rank_moves([("Rates", [jump, flat, healthy])], as_of=healthy.as_of)
    assert ranked.Instrument.tolist() == ["Healthy"]
    assert ranked["Sample count"].iloc[0] == 80


def test_move_rank_checks_raw_inputs_after_row_history_has_been_cleaned():
    row = _move_row()
    raw = row.series.to_frame("selected")
    raw.loc[raw.index[-1], "selected"] = np.nan
    row.inputs = (Series("x", "Source", raw, "FRED"),)
    row.check_column = "selected"
    assert monitor.rank_moves([("Rates", [row])], as_of=row.as_of).empty

    source = _move_row(last=10)
    row.inputs = (Series("x", "Source", source.series.to_frame("selected"), "FRED"),)
    assert monitor.rank_moves([("Rates", [row])], as_of=row.as_of).empty


def test_curve_move_checks_ignore_unrelated_missing_tenor():
    from ficc.panels.dashboard import _treasury_groups

    low, high = _move_row(), _move_row(last=0.02)
    frame = pd.DataFrame({"1 Mo": low.series, "2 Yr": low.series, "10 Yr": high.series + 1})
    frame.loc[frame.index[-1], "1 Mo"] = np.nan
    source = Series("ust", "Treasury curve", frame, "US Treasury")
    groups = _treasury_groups(source)
    slope = next(row for _, rows in groups for row in rows if row.label == "2s10s")

    assert [column for _, column in monitor.source_checks(slope)] == ["2 Yr", "10 Yr"]
    assert all("1 Mo" not in issue for issue in monitor.row_issues(slope))
    ranked = monitor.rank_moves(groups, as_of=low.as_of)
    assert "2s10s" in ranked.Instrument.tolist()


def test_curve_move_checks_reject_cancelling_jumps_in_actual_legs():
    from ficc.panels.dashboard import _treasury_groups

    low, high = _move_row(), _move_row(last=0.02)
    frame = pd.DataFrame({"1 Mo": low.series, "2 Yr": low.series, "10 Yr": high.series + 1})
    frame.loc[frame.index[-1], ["2 Yr", "10 Yr"]] += 2.0
    source = Series("ust", "Treasury curve", frame, "US Treasury")
    groups = _treasury_groups(source)
    slope = next(row for _, rows in groups for row in rows if row.label == "2s10s")

    assert any("2 Yr" in issue for issue in monitor.row_issues(slope))
    assert any("10 Yr" in issue for issue in monitor.row_issues(slope))
    ranked = monitor.rank_moves(groups, as_of=low.as_of)
    assert "2s10s" not in ranked.Instrument.tolist()


def test_move_rank_empty_output_has_schema():
    ranked = monitor.rank_moves([], as_of="2026-01-01")
    assert ranked.empty
    assert ranked.columns.tolist() == monitor.MOVE_COLUMNS
