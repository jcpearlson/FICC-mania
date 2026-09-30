import numpy as np
import pandas as pd
import pytest

from ficc import analytics as an


def _s(values, start="2024-01-01", freq="B"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq),
                     dtype=float)


def test_zscore_reports_span_actually_used():
    s = _s(np.linspace(1, 2, 252 * 3))
    z = an.zscore(s, window_years=5)
    assert z.window_label == "3y"          # asked for 5y, only 3y exists
    assert z.pct == pytest.approx(100.0)


def test_pct_return_divides_by_earlier_value():
    s = _s([100.0, 110.0])
    assert an.pct_return(s) == pytest.approx(10.0)       # not 110/100-1 vs latest
    assert an.pct_return(_s([100.0])) is None


def test_rolling_beta_matches_refitting_ols():
    rng = np.random.default_rng(0)
    x = _s(rng.normal(size=400).cumsum())
    y = 2.5 * x + _s(rng.normal(scale=0.3, size=400))
    fast = an.rolling_beta(y, x, 250)
    i = 320
    slow = an.beta(y.iloc[i - 250:i + 1], x.iloc[i - 250:i + 1], 250)[0]
    assert fast.iloc[i] == pytest.approx(slow, rel=1e-9)
    assert fast.iloc[:249].isna().all()


def test_duration_limits():
    assert an.duration(5.0, 0) == 0
    assert an.duration(0.0, 10) == 10
    assert 8.0 < an.duration(4.0, 10) < 8.4      # ~8.18 for a 10y par at 4%


def test_carry_rolldown_flat_curve_has_no_roll():
    tenors = {"2 Yr": 2, "5 Yr": 5, "10 Yr": 10}
    levels = {k: 4.0 for k in tenors}
    cr = an.carry_rolldown(tenors, levels, front_rate=4.0)
    assert np.allclose(cr["roll_bp"], 0) and np.allclose(cr["carry_bp"], 0)


def test_excess_over_loss_does_not_double_count_recovery():
    # A 0.6% charge-off rate is already a loss; 3% OAS leaves 2.4% of premium.
    assert an.excess_over_loss(3.0, 0.6) == pytest.approx(2.4)
    assert an.loss_to_default_rate(0.6) == pytest.approx(1.0)


def test_net_liquidity_reconciles_units():
    wed = pd.date_range("2025-01-01", periods=4, freq="W-WED")
    walcl = pd.Series(7_000_000.0, index=wed)                       # $mn
    tga = pd.Series(800_000.0, index=wed)                            # $mn (WTREGEN)
    rrp = pd.Series(200.0, index=pd.bdate_range(wed[0], wed[-1]))    # $bn, daily
    nl = an.net_liquidity(walcl, tga, rrp)
    assert list(nl.index) == list(wed)
    assert nl.iloc[-1] == pytest.approx(7.0 - 0.8 - 0.2)             # $tn


def test_common_base_index_uses_shared_start():
    a = _s([1, 2, 4, 8])
    b = _s([10, 20], start=a.index[2])
    idx = an.common_base_index({"a": a, "b": b})
    assert idx.index[0] == a.index[2]
    assert (idx.iloc[0] == 100).all()


def test_cross_market_alignment_does_not_extend_stopped_sources():
    old = pd.Series([1., 2.], index=pd.to_datetime(['2026-01-01', '2026-01-02']))
    active = pd.Series(range(16), index=pd.date_range('2026-01-01', periods=16), dtype=float)
    aligned = an.align_recent({'old': old, 'active': active})
    assert aligned.index[-1] == pd.Timestamp('2026-01-09')
    assert aligned['old'].iloc[-1] == 2.
    assert an.align_recent({'old': old, 'new': active.loc['2026-01-12':]}).empty
