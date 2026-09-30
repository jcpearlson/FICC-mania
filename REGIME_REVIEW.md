# Regime and dashboard review

Reviewed 29 September 2026. Changes are implemented in `ficc/regime.py`, the
Market health and Dashboard panels, and the associated analytics and tests.

## Assessment and decision

Keep a small, transparent **market-conditions heuristic**. The original score
was useful as a compact summary, but its label had more authority than the
implementation supported. It was not an estimated probability, a recession
classifier, a monetary-policy regime, or a validated return forecast.

Do not tune weights or band thresholds to produce a preferred answer today.
Keep the existing intended weights and bands for continuity, fix the economic
anchors and availability rules, and show enough detail to audit every result.
Streamlit remains adequate for this workflow; changing the frontend would not
resolve these model defects.

## What the original model did

1. HY OAS, inverted trailing level z-score: 25%.
2. Average inverted z-scores of VIX and MOVE: 25%.
3. Average inverted z-scores of NFCI and STLFSI4, labelled “funding”: 20%.
4. Copper/gold ratio trailing z-score: 15%.
5. S&P 500 distance from its 200-day moving average, then z-scored around
   the distance's trailing mean: 15%.

Each z-score was clipped at ±2 and divided by 2. References requested five
years but used whatever the source supplied, with a minimum of just 30 prints.
The current observation was included in the reference distribution. Valid
components were weighted and remaining weights silently renormalized after a
missing component; within a component a missing leg gave its full share to the
surviving leg. Stale cached observations were accepted as long as the source's
frame was nonempty. No minimum coverage or required core input existed.

Labels were assigned from a weighted mean on approximately −1 to +1:

| Interval | Label |
|---|---|
| score ≤ −0.50 | Risk-off |
| −0.50 < score ≤ −0.15 | Cautious |
| −0.15 < score < +0.15 | Neutral |
| +0.15 ≤ score < +0.50 | Constructive |
| score ≥ +0.50 | Risk-on |

Those bands and weights were design choices, with no calibration evidence in
the repository. Comments asserting that credit/vol lead market damage and
that specific divergences predict drawdowns were unsupported by local tests.

## Findings and implemented corrections

| Finding | Why it matters | Implemented behavior |
|---|---|---|
| Freshness warnings did not change the score | Old weekly data could dominate a current label | Daily inputs expire after cadence + 3 calendar days (4); weekly after 10. Dates are checked against the latest finite print, not solely metadata. |
| Silent composition changes | A confident-looking label could come from only one market | Coverage measures available **intended weight**. At least 80%, credit and volatility are required. Otherwise the result is “Insufficient data.” |
| One missing sub-input inherited its partner's share | A failed MOVE feed could double VIX's influence | VIX/MOVE each retain an intended 12.5%; NFCI/STLFSI4 each 10%. Missing legs lose their own weight; all effective weights are displayed. |
| Trend could be negative above the moving average | “Less above average than usual” was confused with below-trend | Trend is distance from the 200-day MA divided by twice the trailing distance SD, capped at ±1. Its sign is anchored at the MA. |
| Official indices were re-centered on a recent sample | A negative NFCI could appear restrictive simply because it was less negative than a recent average | Financial conditions use −native index / 2, capped at ±1. Zero retains the publisher's historical-normal interpretation. |
| 30-print minimum and zero variance returned a neutral-looking component | Statistical failure looked like economic neutrality | Relative scores require 252 prior finite observations and nonzero SD. Otherwise that input is unavailable. Native condition indices are already standardized by their publishers and do not need this second reference sample. |
| Current print changed its own comparison benchmark | Large shocks partly normalized themselves away | A time-based trailing window of up to 1,826 days excludes the current observation. |
| NaN or infinity could contaminate a whole blend | One bad leg could discard valid data or create a false label | Nonfinite observations are removed; unavailable sub-inputs contribute no weight. Future-dated inputs are excluded. |
| Unweighted bars were mistaken for contributions | A component's visual size did not match its influence on the headline | Bars show the actual weighted contributions; they sum to the published score. |
| “Neutral” hid disagreement and proximity to a cutoff | A small net average did not imply all markets were neutral | Separate mixed-signal indication for components on opposite sides of ±0.25; near-boundary note within 0.03 of a threshold; three decimal places on the score. |
| No regime history existed despite a “regime history” code comment | Direction and coverage changes were invisible | Two-year score reconstruction, neutral band, threshold lines, hover coverage, 30-calendar-day change and visible gaps for inadequate coverage. |
| No reproduction path | User could not inspect dates, exclusions or formulas | Expandable methods, raw values with units explained, reference span/print count, source/pull times, nominal/effective weights and downloadable calculation table on both pages. |

Positive is supportive of risk appetite throughout, but the anchors are
explicitly different: credit/vol/growth describe **recent relative positioning**;
financial conditions preserve **publisher normal**; trend preserves **price vs MA**.
The capped scale is a presentation scale, not an empirical probability.

The publishers support the financial-condition sign conventions:
[Chicago Fed NFCI methodology](https://www.chicagofed.org/research/data/nfci/background)
and [St. Louis Fed explanation of financial stress indices](https://www.stlouisfed.org/publications/page-one-economics/2020/09/15/measuring-financial-and-economic-risk-with-fred).
This app's division by 2 and component weights are our heuristic choices.

## Does Neutral make sense for this snapshot?

Yes, as the output of this descriptive heuristic. The inspected source cache
was pulled around 20:26 EDT on 29 September. The original score was
**+0.138532**, correctly classified as Neutral, just below +0.15. “Neutral” was
not an arithmetic bug.

The revised result on the same observations is **+0.104332, Neutral, 80%
coverage, mixed signals**. Both weekly indices last observed 18 September,
11 calendar days earlier, and are excluded. They are not treated as zero.

| Component | Original contribution | Revised effective weight | Revised component score | Revised contribution |
|---|---:|---:|---:|---:|
| Credit | +0.0258 | 31.25% | +0.1033 | +0.0323 |
| Volatility | +0.0223 | 31.25% | +0.0894 | +0.0279 |
| Financial conditions | +0.1230 | 0% | unavailable | unavailable |
| Growth proxy | −0.0437 | 18.75% | −0.2914 | −0.0546 |
| Equity trend | +0.0111 | 18.75% | +0.5266 | +0.0987 |
| **Total** | **+0.1385** | **100% of available weight** | | **+0.1043** |

VIX is individually supportive (+0.2868); MOVE is restrictive (−0.1080),
so even the volatility average hides disagreement. Equity trend is supportive
because SPX is 6.34% above its 200-day MA. Copper/gold is weaker than its own
reference sample. The aggregate remains inside the neutral interval because
these readings offset one another.

This is a dated snapshot, not an assertion that markets must be neutral now.
The live calculation can change when newer observations arrive.

## Remaining model limits and how they are handled

- **No demonstrated predictive skill.** Unit tests establish arithmetic,
  polarity, coverage and causal trailing calculations, not investment value.
  The UI now describes the result as a heuristic and removes trading/leading
  claims. A predictive model would need a defined target, release/vintage data,
  walk-forward evaluation and benchmarks before changing this claim.
- **Correlated inputs.** HY, VIX/MOVE and official financial-condition indices
  overlap. Five components are not five independent votes. We retain fixed
  intended weights and disclose this instead of fitting unstable weights to
  the short available sample.
- **Unequal reference histories.** The current FRED credit sample has about
  three years; other daily inputs have about five. The table shows actual
  reference spans. Tight relative to three years is not tight relative to a
  full multi-cycle history. No unsupported long-run inference is made.
- **No macro-regime identification.** The model does not directly classify
  inflation/growth combinations, real yields, curve shape, liquidity or policy.
  Those remain separate dashboard readings. Adding them blindly would make
  the same label harder to interpret.
- **Growth proxy is noisy.** Copper/gold depends on commodity-specific supply,
  gold demand, rates, currency and continuous futures rolls. It is not a GDP
  forecast, and quoted futures are not a constant-contract cash-price series.
- **Reconstruction is not a backtest.** Past calculations use preceding
  observations, but the currently available vintage can contain revisions;
  weekly observation dates are not release timestamps. The app says so.
- **Availability changes can move the score.** Renormalization is explicit,
  with coverage and effective weights shown. A history change may reflect an
  expiry as well as economics; the chart caption explains this.
- **No false confidence statistic.** Coverage is data availability, not a
  confidence percentage. “Mixed” and “near boundary” are deterministic
  descriptive flags, not statistically estimated uncertainty.

## Whole-dashboard critique and completed fixes

| Issue found while using/reviewing the dashboard | Fix |
|---|---|
| Refresh/Clear cache could discard the selected analysis page | Remove the unnecessary second rerun and persist navigation separately from widget state, synchronizing desktop tabs and the phone selector. |
| Signed numeric hover formats printed full floating-point values in the installed renderer | Normalize hover format specifiers to supported precision; negative signs remain, and preformatted custom data stays intact. |
| Dense table lacked a quick way to isolate an instrument or reuse values | Search, group filter, clear no-results message and filtered CSV export with level/change units, dates and warnings. Charts remain the full dashboard context. |
| Wide-curve warnings repeated the same label without naming the tenor; the dashboard warning summary omitted some regime-only sources | Warning labels include the checked column/tenor and the summary includes every regime input. |
| Bare change numbers made bp vs percent vs points ambiguous | Per-cell unit tooltips, explicit explanatory text and unit columns in CSV. |
| Row-normalized heatmap made equal colours represent very different moves | Default shared bp scale, cell values, precise hover and optional explicitly labelled relative scaling. Trading-observation lookbacks are stated. |
| FX lines started at different dates | FX complex now uses one common starting date and shared base, retaining inverted pairs so up consistently means stronger USD. |
| Cross-market comparisons extended missing series indefinitely | Seven-calendar-day carry limit for UST/JGB/EUR, USDJPY/rates, gold/real-yields and copper/gold/yields. Disjoint histories produce an explanation instead of a fabricated comparison or exception. |
| “Fair value” and causal explanations overstated a levels regression | FX line is labelled a retrospectively fitted relationship; R², residual and beta remain descriptive. |
| Scatter highlight said “today” with older matched observations | Highlight and hover show actual matched date; historical dots also show dates. |
| Divergence captions asserted leading/trading value | Captions explain gap direction and descriptive relative positioning. They no longer claim a tested lead or mispricing. |
| HY OAS minus losses on a different bank borrower pool looked like a measured risk premium | Remove the premium claim/subtraction from the UI. Label OAS/(1−recovery) a default equivalent that allocates all spread to loss; bank C&I losses are a separate-pool comparison. |
| Spread/yield ratio was presented as a duration decomposition | Label the actual ratio and explain it is not expected-return decomposition or rate sensitivity. |
| Lending survey and SOFR−IORB captions overstated what they establish | Describe reported tightening and possible funding pressure, with no fixed forecast horizon or single-cause claim. |

The existing mobile selector, responsive chart grids, compact/full monitor,
source dates, quality warnings and lazy tabs remain. Duration/spread-duration
columns and feeds stay removed as requested. `APP_FEEDBACK.md` stays removed.

## Verification

Regression tests cover exact contribution sums, economic anchors, stale weekly
exclusion, missing sub-input weights, absent core inputs, future/nonfinite inputs,
short/constant histories, all-missing inputs, clipping, threshold boundaries,
trailing-history causality and bounded carry. Additional tests exercise monitor
search/export, scale switching and disjoint cross-market data in the app.
Every page is smoke-tested offline against source-shaped fixtures. Live browser
checks cover navigation, methods, warning details, filters, hover interactions,
scale switching and desktop/phone layout. Lint and whitespace checks are run
alongside the full test suite.

Final validation: **62 tests passed**; Ruff and `git diff --check` passed. The
live browser verified all six pages, search/export controls, both heatmap modes,
methods, corrected hover precision, refresh navigation and a 390px phone layout
without page overflow. Duration fields and `APP_FEEDBACK.md` remain absent.
