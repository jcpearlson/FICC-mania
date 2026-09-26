# Audit — data sources, data quality, code and visualisation

Audited 2026-09-26. This is the record of what was checked, what was wrong, what
changed, and what is still open. The companion files are `BACKLOG.md` (source
status and next candidates) and the test suite under `tests/`.

**One limitation to know first.** This audit ran from a sandbox with no network
route to any data host (FRED, treasury.gov, NY Fed, MOF, Yahoo, ECB, CFTC and
TreasuryDirect all refused the connection). So every finding below comes from
reading the code and from tests against **synthetic payloads in each source's
real wire format** (`tests/fakenet.py`), not from live data. The three new
adapters follow the published formats of their APIs but **have not yet been run
against the live endpoints**. Run `uv run streamlit run app.py` once on a
connected machine and check the Sources → Data quality table.

---

## 1. Data sources — evaluation

| Source | Verdict | Notes |
|---|---|---|
| **US Treasury** (home.treasury.gov CSV) | Keep — primary | Official, same-day. Undocumented CSV path, and it needs a browser UA. The year-by-year pull caps history at about 3y, which is why DGS10 (FRED) anchors the long spreads. |
| **FRED keyless CSV** | Keep — workhorse | Stable and keyless. Two caveats: ICE BofA `BAML*` series are capped at 3y and licensed (see README Data terms), and administered rates (IORB) carry **forward-dated rows**, now clipped (§2). |
| **NY Fed markets API** | Keep | Documented and stable. It is the best free source for SOFR percentiles and volume. |
| **MOF Japan** | Keep | Official, with history to 1974. The English CSV avoids Shift-JIS and Reiwa dates. |
| **Yahoo via yfinance** | Keep, **highest risk** | Unofficial, and its terms restrict automated use. It is also the most likely source to fail silently: a dead symbol returns its last print, and some tickers come back empty with HTTP 200. The new data-quality checks target both failure modes. Where possible, prefer official sources over Yahoo. |
| **ECB Data Portal** (new) | Added | Official, keyless, free reuse with attribution. It fills the euro gap: a fitted AAA government curve (the Bund stand-in) and EUR STR. |
| **TreasuryDirect auctions** (new) | Added | Official and keyless. This was the #1 "next" item in the backlog. |
| **CFTC COT / Socrata** (new) | Added | Official and keyless. JPY and EUR leveraged-fund positioning (backlog #5). |
| **FRED plumbing series** (new use of an existing source) | Added | WALCL, WTREGEN, RRPONTSYD and WRESBAL give net liquidity and reserves. RIFSPPNA2P2D90NB − DCPN3M gives the CP quality spread (backlog #6). |

### Further free sources worth adding (not built here)

Ranked by value to this dashboard. All are keyless and public:

1. **ACM term premium** (NY Fed `.xls`, needs `xlrd`). It is fresher than
   Kim-Wright `THREEFYTP10`, which lags by about a week.
2. **Fed FOMC calendar** (`federalreserve.gov/json/calendar.json`). It enables a
   meeting-dated policy path instead of the monthly ZQ smear.
3. **Treasury Fiscal Data API** (`api.fiscaldata.treasury.gov`). It gives the
   daily TGA from the Daily Treasury Statement, which is fresher than weekly
   `WTREGEN`, plus debt outstanding and average interest cost.
4. **NY Fed repo operations** (`markets.newyorkfed.org/api/rp/...`). These are
   standing repo facility (SRF) usage figures, the stress valve that SOFR−IORB
   only hints at.
5. **Bank of Canada Valet** and **Bank of England IADB**. These give CAD and GBP
   curves to round out the Global block. Valet is a clean JSON API; IADB
   sometimes blocks scripts.
6. **EIA keyless `dnav` xls**. Weekly crude and product inventories, to pair
   with the WTI curve shape.
7. **SEC EDGAR full-text search**. A distress-velocity count ("chapter 11" in
   8-Ks) as a free leading default signal.

---

## 2. Data-quality findings (fixed)

| # | Finding | Impact | Fix |
|---|---|---|---|
| 1 | **Monitor lookbacks counted observations, not time.** "1W" meant 5 rows back. | The NFCI row (weekly) showed a **5-week** change under 1W, 21 weeks under 1M, and a 1-week change under "1D". Cross-market spreads ffilled over two holiday calendars were subtly off too. | Lookbacks are now calendar offsets. 1D is blank when the previous print is more than 4 days old. |
| 2 | **Sparklines labelled "3y" drew full history.** | JGB rows and UST−JGB drew **52 years** of history under a "3y" header, and the up/down colour reflected 1974 → today. | The sparkline is trimmed to the stated window, and the column header is derived from that window. |
| 3 | **"Range in own history" header, 3y window.** | The percentile was computed over 3y, but the header claimed full history. | The header now reads "Position in 3y range". |
| 4 | **Empty payloads were cached.** FRED under load and yfinance for a bad symbol can return HTTP 200 with no rows. | The empty frame **overwrote the last good cache entry** and was served for a full TTL, which defeats the stale fallback. | `cache.through` rejects empty or all-NaN frames and falls back to the stale payload. |
| 5 | **Forward-dated FRED rows.** IORB is published with a future effective date on announcement day. | The monitor's IORB row could show tomorrow's rate as today's. | `fred.get` drops observations dated after today. |
| 6 | **Risk-premium maths double-counted recovery.** The bank charge-off rate (already a *loss*) was multiplied by (1−R) as if it were a default rate. | Expected loss was understated by 40% and the "genuine risk premium" was overstated. The chart compared a default rate with a loss rate on one axis. | Premium is now OAS − loss. The chart grosses charge-offs up to a default-rate equivalent, and the caption notes that bank C&I losses are only a loose proxy for HY. |
| 7 | **% change divided by the new value**, not the old (FX, metals and WTI tiles). | Small but systematic error, and a zero change rendered as no delta. | `analytics.pct_return`. |
| 8 | **Two-leg spreads stamped with one leg's date.** | UST−JGB carried the UST as-of even when the JGB leg was older. | They now carry the older of the two dates. |
| 9 | **No systematic quality checks** beyond freshness. | Flatlined Yahoo symbols, unit or bad-print jumps, history gaps and short samples went unnoticed. | New `ficc/quality.py`, surfaced as a per-series table on the Sources tab. |

## 3. Code-quality findings (fixed)

- **No tests at all.** There are now 31: analytics, monitor, cache/contract/quality,
  every source parser, and two full-app smoke renders (Streamlit `AppTest`)
  against the fake network. The smoke test caught a crash in this very change
  set before it shipped.
- **Duplicated regime maths** (overview and dashboard each computed the
  composite and its colour band). This is now `overview.composite()`.
- **O(n) Python loop of `np.polyfit`** for the rolling USDJPY beta, run twice
  per render. It is replaced by a vectorised `analytics.rolling_beta`, which is
  tested to match the loop to 1e-9.
- **Repeated status plumbing** (`STALE if meta.startswith("stale")…` in six
  places). This is now `contract.status_from` / `worst_status`. Within-TTL Yahoo
  hits are also badged "cached" consistently with FRED.
- **No retry on transient HTTP errors.** `http.get` now makes one backed-off
  retry on connection errors, timeouts, 429 and 5xx. 4xx responses are still
  final.
- Dead code was removed (a no-op `_add(...None...)` call, an unused `ok` flag,
  unused loop variables and an unused `Row.note`). Stale text about the dropped
  CLOA/CLOZ ETFs was corrected.
- **Tooling:** `pytest` + `ruff` dev group in `pyproject.toml`, and a CI
  workflow.

## 4. Visualisation changes

- **FX complex chart**: EURUSD, GBPUSD and AUDUSD are inverted, so every line
  rises when the dollar strengthens. Before, half the lines read backwards.
- **Rates curve chart**: adds a faint *1-month-ago* UST curve (how the curve
  moved, not just where it is) and the **EUR AAA** curve. The caption explains
  the spot-versus-par difference.
- **Monitor**: new rows for the 2s5s10s fly (the backlog's unused
  `butterfly()`), CP A2/P2−AA, ON RRP, EUR AAA 10Y, 10y UST−EUR and EUR STR.
  Rounded-zero changes show a plain "0" with no colour instead of a blue "-0".
- **New sections**: *Liquidity & plumbing* (net liquidity, reserves vs RRP,
  CP spread), *Treasury auctions* (a table judged against each security's own
  last six auctions, plus dealer take-down), and *Positioning* (CFTC leveraged
  funds, % of OI, with a percentile).
- **Sources tab**: lists the new sources, adds the data-quality table, and
  shows NaN-safe regime formatting.

## 5. Still open

- **Verify the three new adapters live** (ECB, TreasuryDirect, CFTC). Field
  names follow the documented APIs. If one differs, the adapter fails loudly as
  "unavailable", never as wrong numbers, because the parsers check their schema.
- The SR3 convexity bias is still not adjusted (see BACKLOG §4).
- ICE BofA history is still capped at 3y. `BAA10Y` would give a long-run credit
  anchor.
- Each panel's `_load()` returns a positional tuple. This works, but a small
  dataclass per panel would make cross-panel reuse (the dashboard) less fragile.
