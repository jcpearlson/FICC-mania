# FICC Mania

A practitioner's dashboard for **fixed income, currencies and commodities**, built
entirely on **free, public, keyless data**. No terminal subscription, no vendor
login, no paid API. Every number on the page can be traced to a public endpoint.

```bash
uv run streamlit run app.py
```

That is the whole setup. `uv` resolves the environment on first run. The app
binds to `localhost` only — it has no authentication, so read
[SECURITY.md](SECURITY.md) before exposing it on a network.

> **This is not investment advice, and it is not a financial product.** It is a
> personal research tool that reads public data and does arithmetic on it.
> Figures may be wrong, stale, misattributed, or silently missing — several
> upstream sources have changed or broken during development alone. Nothing
> here is verified against a vendor system, nothing is suitable for trading,
> valuation, reporting, or any regulated purpose, and the software is provided
> without warranty of any kind. Verify independently before you act on
> anything you see here.

---

## What it shows

**Dashboard** — the landing page, and the only one you need for a quick glance.
Terminal density, built for a **portrait monitor**.

It leads with a **monitor table**: ~38 instruments grouped Treasuries → curve
slopes → credit → front end and funding → inflation and term premium → vol →
Global (Japan, euro area, FX), each row carrying level, 1D/1W/1M/3M change, a
position-in-3y-range marker, its percentile, a 3-year sparkline and the
source's observation date. On phones, the compact table prioritizes Last, 1D
and source dates, with all columns available through
an explicit horizontal scroll mode. Data-quality warnings travel with each row. Changes are **calendar** lookbacks (1W is seven days
back, whatever the series' cadence), and 1D is blank for series that do not
print daily. That is a
deliberate trade: six stat tiles occupy the same vertical space as thirty table
rows and carry a fifth of the information, and on a glance page the number of
instruments visible before you scroll *is* the product.

The monitor also has instrument search, group filtering and a CSV export with explicit units.
The tenor heatmap defaults to a shared bp scale; relative row scaling is optional.

The table uses **one directional convention throughout** — red means the number
rose, blue means it fell, for every row and for the sparkline. Not good/bad:
in a grid of thirty mixed instruments a green credit print beside a red rates
print would mean opposite things two lines apart, and "good" depends on which
way you are positioned.

Sparklines are inline SVG (`ficc/sparkline.py`), not chart objects — thirty
Plotly figures would be slow and enormous; thirty inline SVGs are a few
kilobytes and render instantly.

Below the table, eight charts as small multiples two across at ~190px, in
compact mode (smaller type, tighter margins, wrapping captions above a separate legend band).
Once the table has told you *what* moved, a chart only needs to show *shape*:
the curve, the policy path, IG/HY, CCC−BB dispersion, SOFR−IORB, carry and
roll-down, and the USDJPY beta to UST−JGB.

Ordering is the design — the further down something sits, the less often it
changes the answer to "how is fixed income doing right now". The page reuses
the other tabs' cached loaders. Tabs load only when opened, with visible source-group loading feedback.

**Market health** — a five-component cross-asset risk regime score (credit, vol,
financial conditions, growth proxy, equity trend). This is a descriptive heuristic,
not a calibrated forecast. It shows actual weighted contributions, input dates,
coverage, exclusions, effective weights, an exportable calculation table and a
trailing reconstruction. Daily inputs expire after 4 days, weekly after 10; at least
80% intended weight plus credit and volatility are required. Full methodology and
review: [REGIME_REVIEW.md](REGIME_REVIEW.md). Relative-positioning comparisons sit below.

**Rates & curves** — the UST nominal and real curves, the JGB curve, and a genuine
**forward SOFR curve** built from CME SR3 futures, on one chart. Per-tenor change
heatmap, the Fed policy path implied by fed funds futures, overnight funding
(SOFR vs EFFR with its percentile band), the 10y UST−JGB spread, a decomposition
of the 10y into real yield / breakevens / term premium, funding pressure via
SOFR−IORB, and **carry, roll-down and the breakeven selloff** for every tenor.
The curve chart also carries the ECB's euro AAA curve and a month-ago UST
ghost. Below: **liquidity and plumbing** (Fed balance sheet net of TGA and RRP,
reserves, the A2/P2−AA commercial paper spread) and **Treasury auction
demand** (bid-to-cover and bidder shares against each security's own recent
auctions).

**Credit, CLOs & loans** — IG, HY, EM and Euro HY option-adjusted spreads with
percentile context; the full AAA→CCC ratings ladder; the CCC−BB quality spread
as a dispersion signal; CLO and leveraged-loan total-return proxies; bank lending
standards from SLOOS; spread-implied default equivalents under a recovery
assumption; a separate bank-loss comparison; and OAS as a share of yield.

**FX & commodities** — the dollar and the G10/EM complex; USDJPY against
a retrospectively fitted rate relationship with its residual *and rolling beta*; gold against
real yields; copper/gold against 10y yields; energy forward curves with a
contango/backwardation metric; gold/silver; a commodity performance grid; and
**CFTC positioning**, i.e. leveraged-fund net in yen and euro futures as a share of
open interest.

**Sources** — every endpoint, its cadence, an explicit list of what is
deliberately absent and why, and a **data-quality table** that checks every
loaded series for staleness, flatlines (dead symbols), outsized jumps (bad
prints or unit changes), history gaps and short samples.

---

## The two-timestamp rule

The single most important design decision. Every fetcher returns a record
carrying **two** distinct timestamps:

| Field | Meaning |
|---|---|
| `as_of` | the observation date **the source** stamps on the data |
| `fetched_at` | when **this app** pulled it |

Conflating them makes the dashboard lie. FRED's USDJPY series can be six days
stale while treasury.gov has already published today's curve — a tile reading
"updated 4 seconds ago" over a six-day-old print is worse than no timestamp at
all. So each tile badges its **observation date** and turns amber when that date
falls behind the series' expected cadence. Actual successful pull times survive
disk-cache hits and appear in badge tooltips and source notes. The header shows
**Page rendered**. Refresh clears the memory cache while retaining the disk cache;
Clear cache requests fresh data for the open tab. FX dates are labelled as source
sessions; unexplained future dates are flagged. Futures retain each contract’s
quote date, with the oldest date used for freshness and mixed dates flagged.

## Honest history windows

Window labels are **derived from the data actually used**, never hardcoded. This
matters more than it sounds: FRED's keyless endpoint silently truncates the
licensed ICE BofA credit series to **exactly three years**, and ignores `cosd`.
Asking for a 5-year z-score on HY OAS quietly gets you three. Because the label
is computed from the span, a tile physically cannot claim more history than it
has — credit tiles read `3y`, Treasury tiles read `5y`, and the difference is
visible rather than hidden.

## Failure behaviour

One dead source never blanks the page. Every fetch is cache-through with a
stale fallback: if the network call fails and a cached payload exists, the last
known value is served and badged as stale. An HTTP 200 with no usable rows is
treated as a failure too, so it never overwrites a good cache entry. Panels
render whatever succeeded and list what did not at the bottom.

---

## Architecture

```
app.py                  Streamlit shell, tabs, header, refresh
assets/
  make_favicon.py       Draws the browser-tab mark (a yield curve); regenerate
                        with `uv run python assets/make_favicon.py`
ficc/
  contract.py           Series record: as_of vs fetched_at, status, freshness
  http.py               Per-source headers + rate limiting  (see note below)
  cache.py              On-disk TTL cache with stale fallback
  analytics.py          Z-scores, curve maths, carry/roll-down, rolling beta,
                        net liquidity, regime scoring
  quality.py            Per-series data-quality checks (Sources tab)
  theme.py              Design tokens, Plotly template, compact chart mode
  ui.py                 Stat tiles, freshness badges, section chrome, status strip
  monitor.py            The dense monitor table (rows, grouping, one colour rule)
  sparkline.py          Inline SVG sparklines and range bars
  sources/
    fred.py             FRED keyless CSV
    treasury.py         home.treasury.gov nominal / real / bill curves
    nyfed.py            NY Fed markets API (SOFR, EFFR, averages)
    mof.py              MOF Japan JGB curve (English CSV, history to 1974)
    ecb.py              ECB Data Portal: euro AAA curve, EUR STR
    treasurydirect.py   Treasury coupon auction results
    cftc.py             CFTC Traders in Financial Futures positioning
    market.py           yfinance: FX, commodities, ETFs, futures strips
  panels/
    dashboard.py        The portrait glance page (landing tab)
    overview.py  rates.py  credit.py  fxcommods.py
tests/
  fakenet.py            Every source's wire format, synthesised: the whole
                        app runs and renders offline
```

### Tests

```bash
uv run --group dev pytest      # offline source and app regression tests
uv run --group dev ruff check .
```

`tests/fakenet.py` replaces `http.get` and `yfinance.download` with
deterministic synthetic payloads shaped like each real source, so the parsers,
analytics and every tab's render path run in CI without touching an endpoint.

### Colour conventions

Three, used deliberately and never mixed within one component:

- **Stat tiles** carry a `mode`: `perf` (up is good), `risk` (up is bad — spreads
  and vol), or `rates` (up is neither — a yield rising is a selloff, not a
  verdict, so it renders red for higher and blue for lower).
- **The monitor table** uses one directional rule throughout — red rose, blue
  fell — because in a grid of thirty mixed instruments a green credit print
  beside a red rates print would mean opposite things two lines apart.
- **Status colours** (good / warning / serious / critical) are reserved for
  freshness badges and range alerts, never reused as a series colour.

The categorical palette is a validated eight-hue ramp; it clears the lightness
band, chroma floor, adjacent-pair colour-vision separation, normal-vision floor
and 3:1 contrast against this app's dark surface. Do not add a ninth hue — a
ninth series folds into "Other" or becomes a small multiple.

### Per-source HTTP headers are not optional

Two verified facts, both of which look exactly like an outage if you get them
wrong:

- **FRED** fails if you send a browser `User-Agent`.
- **treasury.gov** hangs until timeout if you *don't*.

So headers are configured per source in `ficc/http.py`, never globally, and each
source gets its own session and a minimum interval between calls (hitting FRED
concurrently reproducibly returns empty responses).

**If a source starts refusing us**, copy the request headers from Chrome's
Network tab into `headers.local.json` at the repo root:

```json
{ "cme": { "User-Agent": "...", "Cookie": "...", "Accept": "..." } }
```

They are merged over the defaults at import. The file is gitignored, since
pasted headers usually carry session cookies.

---

## Data sources

| Source | Provides | Freshness |
|---|---|---|
| US Treasury | UST nominal, real and bill curves | Same day, ~15:30 ET |
| FRED (keyless CSV) | ICE BofA OAS, breakevens, term premium, NFCI, IORB, Fed balance sheet / TGA / RRP / reserves, CP rates | T+1 daily; balance sheet weekly |
| NY Fed markets API | SOFR + percentiles + volume, EFFR, SOFR averages | ~08:00 ET, T+1 |
| MOF Japan | JGB curve 1Y–40Y, history to 1974 | T+1 |
| CME futures (via yfinance) | Forward SOFR (SR3), policy path (ZQ), commodity curves | Intraday, 15-min delayed |
| Yahoo Finance | FX, metals, energy, ags, credit/CLO ETFs, VIX/MOVE/SKEW | Intraday, 15-min delayed |
| ECB Data Portal | Euro-area AAA govt spot curve, EUR STR | T+1 |
| TreasuryDirect | Coupon auction results | Same day as auction |
| CFTC (Socrata) | Traders in Financial Futures positioning | Weekly (Fri, for Tue) |

See `BACKLOG.md` for what is blocked, what is licensed, and what is deliberately
left out, and `AUDIT.md` for the most recent source and data-quality audit.

## Data terms — read before you fork or redistribute

**The MIT licence in [LICENSE](LICENSE) covers the source code only.** It is
verbatim MIT and says nothing about data, because the data is not ours to
license — it grants you no rights whatsoever in respect of anything the code
retrieves at runtime. This project ships **no
market data**: there is no vendored dataset, no committed cache, no snapshot in
the git history. Everything is fetched at runtime, on your machine, under your
own relationship with each provider. That distinction is what keeps the repo
redistributable — and it is your responsibility to keep it that way.

| Source | Status | What it means for you |
|---|---|---|
| US Treasury, TreasuryDirect, Federal Reserve (FRED host), NY Fed, CFTC, MOF Japan | US/Japanese government publications, generally free to use | Attribute the source; do not imply endorsement |
| ECB Data Portal | ECB statistics; free reuse provided the source is cited | Cite "Source: ECB" wherever the euro curve or EUR STR is shown or reused |
| **ICE BofA index data via FRED** (`BAML*` series) | **Third-party licensed content**, owned by ICE Data Indices, LLC and redistributed by FRED under its own terms | Personal/research use as served by FRED. **Do not redistribute these series, cache them publicly, or build a commercial product on them** without checking ICE's and FRED's terms |
| **Yahoo Finance via `yfinance`** | **Unofficial.** `yfinance` reads a public web endpoint that Yahoo does not document or support for this purpose, and Yahoo's Terms of Service restrict automated access and redistribution | Personal use at your own risk. It can break or start refusing requests at any time. **Do not build a commercial or redistributed service on it** |

Three practical rules if you run or fork this:

1. **Do not commit the `.cache/` directory.** It is gitignored for a reason —
   committing it would turn "fetches data at runtime" into "redistributes
   licensed data", which is the one thing the structure above is designed to
   avoid.
2. **Be polite to the sources.** `ficc/http.py` enforces a minimum interval
   between calls per source and `ficc/cache.py` caches to disk with TTLs matched
   to each series' publication cadence. This is deliberate — FRED reproducibly
   returns empty responses when hit concurrently. Do not remove the throttling
   or the cache to "make it faster"; you will get the endpoint blocked, for you
   and for everyone.
3. **These endpoints are undocumented and can vanish.** Several changed during
   development: stooq went behind a proof-of-work wall, and FRED silently caps
   the licensed credit series at three years. Expect breakage; treat a missing
   panel as normal rather than as a bug in your setup.
