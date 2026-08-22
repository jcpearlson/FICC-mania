# Backlog & data-source status

Verified 2026-08-21. This file exists so that "we don't show X" is always a
recorded decision with a reason, not an oversight.

---

## 1. Not free — do not proxy without a label

| Item | Status | What we do instead |
|---|---|---|
| **Cross-currency basis** (JPY/EUR 3m) | The basis swap is OTC; `JYBS3`/`EUBS3` are licensed. FX forward points aren't free daily either, so CIP deviation can't be computed. BIS publishes quarterly aggregates only. | **Nothing.** Deliberately absent. `SWPT` (Fed swap lines) is a *consequence* of severe basis widening and would be a **funding-stress proxy, not the basis** — a strategist forgives a missing metric, never a mislabelled one. |
| **CLO tranche spreads / primary AAA discount margins** | Licensed. | JAAA / JBBB total return, labelled a proxy everywhere it appears. |
| **Loan index levels** (Morningstar-LSTA, S&P/UBS) | Licensed. | BKLN total return, labelled. |
| **Swap spreads** | FRED `DSWP10` dead at 2016-10-28; `ICERATES1100USD10Y` 404s. No free swap-rate source found. | Absent. A UST-minus-SR3-implied-OIS construct is possible but is *not* a swap spread and would need that caveat. |
| **HY distress ratio** (share trading >1000bp) | Needs constituent-level data. CCC OAS is a level, not a ratio. | CCC−BB quality spread as the dispersion signal. |
| **CDX IG/HY** | Licensed. | ETF complex + cash spreads. |
| **True equity breadth** (A/D line, % above 200dma) | Needs constituent data. | Not shown. Sector/equal-weight relative performance is the closest free substitute and would need labelling as "leadership", not breadth. |
| **Baltic Dry Index** | `^BDIY` 404s; not free anywhere. | Not shown. `BDRY` ETF is the only free proxy. |
| **Auction tail** | Requires the 1pm when-issued yield, which is not public. `highYield − averageMedianYield` is a **different statistic** and must never be labelled tail. | Use bid-to-cover, indirect share, dealer takedown (all free — see §3). |

## 2. Blocked from this network

| Source | Symptom | Note |
|---|---|---|
| **stooq.com** | SHA-256 proof-of-work JS interstitial on every request, both TLDs, with and without browser UA. | IP/session-scoped — may work from another host. Superseded by yfinance; not worth re-architecting for. |
| **Yahoo raw chart API** | HTTP 429 to `curl`. | **Not actually blocked** — the `yfinance` client negotiates the cookie/crumb handshake and succeeds. Always go through the library. |
| **CME Group** (`/CmeWS/mvc/Settlements/...`) | Connection refused / 000. | Would give official settlement prices *and* open interest. **Best candidate for the `headers.local.json` route** — see README. Currently substituted by Yahoo's SR3/ZQ strip, which lacks volume and OI. |
| **CBOE FX vol** (`^EVZ`, `^JYVIX`, `^BPVIX`) | Resolve via raw curl but return empty through yfinance. | Genuine gap. FRED `EVZCLS` is stale (last obs 2025-03-11). Would complete the vol picture — cheap yen vol plus a stretched USDJPY residual plus crowded short-JPY positioning is the classic pre-unwind setup. |
| Baker Hughes rig count, LME warehouse stocks | 403 | Licensed / bot-blocked. |
| ICI fund flows | 403 even with browser UA | — |
| FINRA fixed income API | 401 | Free but requires credentials. |

## 3. Verified and worth adding next

Ranked. All endpoints confirmed returning data on 2026-08-21.

1. **Treasury auction results** — `https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json`
   (200, 894 KB, 250 records). Gives `bidToCoverRatio`, `indirectBidderAccepted`,
   `primaryDealerAccepted`. The missing "who is absorbing duration" read.
   Latest 29Y6M TIPS: b/c 2.82, 74.3% indirect.
2. **Meeting-dated policy path** — `https://www.federalreserve.gov/json/calendar.json`
   (200, 57 FOMC meetings). Current ZQ strip is *monthly*, which smears a
   mid-month meeting across two policy levels. Proper construction solves
   forward: `F_m = (k/n)·r_before + ((n−k)/n)·r_after`.
3. **ACM term premium** — `https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls`
   (200, 10.1 MB; daily to 2026-08-20, ACMTP10 = 0.816%). Needs `xlrd` for the
   legacy binary `.xls`; the `.csv` URL returns the **same binary blob**, so
   don't "fix" it by swapping the extension. We currently use FRED
   `THREEFYTP10` (Kim-Wright), which is keyless and daily but lags to 08-14.
4. **EDGAR full-text search** — `https://efts.sec.gov/LATEST/search-index?q=...&forms=...`
   with a UA header. Free daily distress velocity: `"chapter 11"` in 8-Ks over
   Jun 1–Aug 20 = 228; `"going concern"` in 10-Qs = 3,393.
5. **CFTC Commitments of Traders** — Socrata, no key. `yw9f-hn96` (TFF, use for
   FX), `72hh-3qpy` (disaggregated, use for commodities). **Default limit is
   1000 — always set `$limit`.** Contract-name literals must match exactly, e.g.
   `COPPER- #1 - COMMODITY EXCHANGE INC.` (no space before the hyphen). Beware
   lookalikes (`MICRO GOLD`, Coinbase gold) that corrupt a series on loose
   matching. Normalise net spec by open interest before z-scoring.
6. **A2/P2 − AA commercial paper spread** — FRED `RIFSPPNA2P2D90NB` − `DCPN3M`
   (≈28bp). Front-end credit stress; leads HY. Align the dates — they publish a
   day apart.
7. **Realised default reads** — FRED `DRBLACBS` (1.34%), `CORBLACBS` (0.59%).
   *Now wired in* on the credit tab's risk-premium chart.
8. **EIA petroleum inventories** — v2 API **requires a free key** (403
   `API_KEY_MISSING`). Keyless paths work: `https://ir.eia.gov/wpsr/psw09.xls`
   (the actual Wednesday release) and `https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls`.
   Build on the keyless `dnav` files; offer the key as opt-in only.
9. **Bill curve** — `type=daily_treasury_bill_rates` (200). `treasury.BILL` is
   already defined; nothing between overnight SOFR and the 1y CMT point today.
10. **Repo operations** — NY Fed `api/rp/all/all/results/last/N.json` (200,
    returns SRF and RRP). SOFR−IORB is already shown as the scarcity gauge.

## 4. Known limitations in what is shipped

- **SR3 convexity.** SOFR futures are daily-margined, so the futures rate
  exceeds the true forward by roughly `½σ²T₁T₂`. Material beyond ~2y and
  **not adjusted for**. The strip is plotted at reference-quarter midpoints,
  which fixes the placement error but not the convexity bias.
- **No volume/open-interest screen** on the futures strips, so a stale far
  contract print flows straight into the headline "bp priced by" figure.
- **ICE BofA history is capped at 3 years** by FRED's keyless endpoint. Window
  labels self-report, so nothing lies, but the credit percentile context is
  a compressed post-2021 sample that makes historically tight spreads look
  mid-range. A free FRED API key would restore full history (untested).
  `BAA10Y` (1986+, unrestricted) is the long-run anchor if needed.
- **Unused analytics.** `analytics.butterfly()` and `analytics.forward_rate()`
  are implemented and not yet surfaced — no 5s30s, no 2s5s10s fly. Note that
  `forward_rate()` expects **zero** rates; feeding it CMT par yields is
  silently wrong.
