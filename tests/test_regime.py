"""Economic polarity, coverage failures and time-series causality of the heuristic."""
import numpy as np
import pandas as pd
import pytest

from ficc import analytics as an, regime
from ficc.contract import Series, failed


@pytest.fixture
def inputs():
    dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=900)
    x = np.arange(len(dates))
    def source(key, values, cadence=1):
        return Series(key, key, pd.DataFrame({'v': values}, index=dates), 'Test', cadence_days=cadence)
    f = {'BAMLH0A0HYM2': source('HY', 4 + np.sin(x/45)),
         'VIXCLS': source('VIX', 20 + 5*np.cos(x/30))}
    slow = {k: source(k, -.5 + .1*np.sin(x/90), 7) for k in ('NFCI', 'STLFSI4')}
    mkt = {'^MOVE': source('MOVE', 100 + 10*np.sin(x/30)),
           '^GSPC': source('SPX', 1000 + x + 20*np.sin(x/25)),
           'HG=F': source('Copper', 4 + .5*np.cos(x/30)),
           'GC=F': source('Gold', 1500 + 100*np.sin(x/40))}
    return f, slow, mkt


def test_complete_result_is_exact_sum_of_shown_contributions(inputs):
    r = regime.analyze(*inputs)
    assert r.coverage == pytest.approx(1)
    assert r.score == pytest.approx(sum(r.contributions.values()))
    assert r.score == pytest.approx(r.audit.Contribution.sum())
    assert r.score == pytest.approx(r.history.score.iloc[-1])
    assert r.audit['Effective weight'].sum() == pytest.approx(1)


def test_economic_anchors_preserve_trend_and_conditions_sign(inputs):
    f, slow, mkt = inputs
    for s in slow.values():
        s.frame['v'] = -.5
    r = regime.analyze(f, slow, mkt)
    assert r.components['conditions'] == pytest.approx(.25)
    assert r.components['trend'] > 0  # Price above its MA stays constructive.
    for s in slow.values():
        s.frame['v'] = .5
    assert regime.analyze(f, slow, mkt).components['conditions'] == pytest.approx(-.25)


def test_stale_weekly_component_is_excluded_and_partial_is_visible(inputs):
    f, slow, mkt = inputs
    for s in slow.values():
        s.frame.index -= pd.Timedelta(days=12)
        s.as_of = s.frame.index[-1].date()
    r = regime.analyze(f, slow, mkt)
    assert r.coverage == pytest.approx(.8)
    assert 'conditions' not in r.components and np.isfinite(r.score)
    assert (r.audit.loc[r.audit.Component == 'Financial conditions', 'Status'] == 'Stale observation').all()
    assert r.weights['credit'] == pytest.approx(.25/.8)


def test_missing_subleg_loses_only_its_intended_weight(inputs):
    f, slow, mkt = inputs
    mkt['^MOVE'] = failed('MOVE', 'MOVE', 'Test', 'down')
    r = regime.analyze(f, slow, mkt)
    assert r.coverage == pytest.approx(.875)
    assert r.weights['vol'] == pytest.approx(.125/.875)
    assert 'Missing source' in r.audit.Status.values


def test_absent_critical_input_cannot_masquerade_as_neutral(inputs):
    f, slow, mkt = inputs
    f['BAMLH0A0HYM2'] = failed('HY', 'HY', 'Test', 'down')
    r = regime.analyze(f, slow, mkt)
    assert r.label == 'Insufficient data' and np.isnan(r.score)
    assert r.history.score.iloc[-1] != r.history.score.iloc[-1]


def test_future_and_nonfinite_inputs_do_not_count(inputs):
    f, slow, mkt = inputs
    f['BAMLH0A0HYM2'].as_of = (pd.Timestamp.now() + pd.Timedelta(days=3)).date()
    r = regime.analyze(f, slow, mkt)
    assert r.label == 'Insufficient data'
    assert 'Future observation date' in r.audit.Status.values
    f['BAMLH0A0HYM2'].as_of = pd.Timestamp.now().date()
    f['BAMLH0A0HYM2'].frame['v'] = np.inf
    assert regime.analyze(f, slow, mkt).label == 'Insufficient data'


def test_short_or_constant_history_is_not_a_neutral_signal(inputs):
    f, slow, mkt = inputs
    f['BAMLH0A0HYM2'].frame['v'] = 3.
    r = regime.analyze(f, slow, mkt)
    assert r.label == 'Insufficient data'
    assert 'Insufficient history or zero variance' in r.audit.Status.values
    f['BAMLH0A0HYM2'].frame = f['BAMLH0A0HYM2'].frame.tail(50)
    assert regime.analyze(f, slow, mkt).label == 'Insufficient data'


def test_normalization_is_causal_and_capped():
    dates = pd.bdate_range('2020-01-01', periods=800)
    s = pd.Series(np.sin(np.arange(800)/30), index=dates)
    old = regime.normalized(s.iloc[:600])
    s.iloc[600:] += 100
    full = regime.normalized(s)
    pd.testing.assert_series_equal(old, full.iloc[:600])
    assert full.iloc[600] == 1
    assert regime.normalized(s, invert=True).iloc[600] == -1
    assert full.iloc[:252].isna().all()


def test_score_history_is_causal_across_future_price_changes(inputs):
    f, slow, mkt = inputs
    cut = mkt['^GSPC'].frame.index[-80]
    before = regime.analyze(f, slow, mkt, as_of=cut).history
    for s in (*f.values(), *slow.values(), *mkt.values()):
        # Retain metadata at today's date: compare historical rows only.
        s.frame.loc[s.frame.index > cut, 'v'] *= 2
    after = regime.analyze(f, slow, mkt).history
    pd.testing.assert_frame_equal(before, after.loc[before.index])


def test_bounded_carry_expires_and_never_backfills():
    s = pd.Series([.4], index=pd.to_datetime(['2026-01-06']))
    grid = pd.date_range('2026-01-01', '2026-01-15')
    out = regime._carry(s, grid, 4)
    assert out.loc['2026-01-05'] != out.loc['2026-01-05']
    assert out.loc['2026-01-10'] == .4
    assert np.isnan(out.loc['2026-01-11'])


@pytest.mark.parametrize('score,label', [(-.5,'Risk-off'),(-.15,'Cautious'),(0,'Neutral'),
                                         (.149,'Neutral'),(.15,'Constructive'),(.5,'Risk-on')])
def test_fixed_band_boundaries(score, label):
    assert an.regime_score({'s': score}) == (score, label)


def test_all_inputs_missing_returns_insufficient_data():
    r = regime.analyze({}, {}, {})
    assert r.coverage == 0 and r.label == 'Insufficient data'
    assert len(r.audit) == 7 and r.audit.Status.eq('Missing source').all()
