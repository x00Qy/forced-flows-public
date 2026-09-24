# PRE-CHECK — SIP flow timing, arithmetic only

**Committed before the script exists and before any ratio or implied move has been computed.**

Phase 3 asks whether the monthly cycle of SIP (Systematic Investment Plan) debits is large enough,
concentrated enough, to move the Indian equity market by an amount a retail participant could trade.
This is an **arithmetic pre-check**: no price data beyond a volatility input, no event study, no
test statistic. It exists to find out whether the question is worth a study at all.

---

## 1. THE KILL CONDITION

> **Phase 3 closes if the largest plausible single-date SIP deployment, as a share of that date's NSE
> cash-market turnover, implies an index move below 3× the delivery floor (71.35 bps) under a stated,
> generous price-impact assumption.**

71.35 bps is 3 × the 23.7821 bps round-trip delivery floor at ₹1 lakh notional, today's cost,
regime (a) — the same bar Phases 1 and 2 used, unchanged.

## 2. THE IMPACT MODEL, FIXED BEFORE ANY RATIO IS SEEN

```
    dP/P  =  Y * sigma * sqrt(Q / V)
```

- **Q** — rupees of SIP deployed on the single date.
- **V** — that date's NSE cash-market turnover in rupees.
- **sigma** — daily volatility of the index.
- **Y** — a dimensionless constant of order 1.

This is the **square-root law of market impact**, proposed by Torre (1997) on regularities in Loeb
(1983) and confirmed across equities, futures and options by Torre & Ferrari (1998), Moro et al.
(2009), Tóth et al. (2011), Bershova & Rakhlin (2013), Zarinelli et al. (2015) and Waelbroeck &
Gomes (2015). **The consensus estimate is Y ≈ 1.** Almgren et al. (2005) is the main dissent,
preferring a 3/5 power for temporary impact; a 3/5 power gives a *smaller* move than a square root at
Q/V < 1, so adopting the square root is already the generous choice.

**Y is set to 1.5 — 50% above the consensus — and that is pre-registered here, before the ratio is
known.** Choosing Y after seeing Q/V is precisely the manoeuvre this document exists to prevent.

**sigma is set generously too:** the **95th percentile of the rolling 21-session standard deviation
of NIFTY 500 close-to-close returns**, over the same months as the flow data, rather than the
full-sample average. Impact is proportional to sigma, so this assumes every SIP deployment lands in a
market as volatile as its worst 5% of months.

**Reported alongside the verdict:** the move at the consensus Y = 1.0, and the **break-even Y** —
the coefficient at which the implied move would exactly reach 71.35 bps. A pre-check whose verdict
turns on a coefficient must say how far that coefficient would have to move.

## 3. CONCENTRATION — the whole month on one date

**No public data exists on how SIP debits are distributed across dates of the month.** Searched
2026-09-22: AMFI publishes monthly aggregates only; NPCI publishes NACH volumes without a
mutual-fund SIP breakdown by date; no AMC discloses a debit-date histogram.

Per the rule that an unknown is resolved in the direction generous to the hypothesis, **the whole
month's SIP inflow is assumed to be deployed on a single trading date.** This is known to be false —
debits cluster on the 1st, 5th, 7th, 10th, 15th, 20th and 25th, and funds hold cash buffers and
deploy over days — and it is false in the direction that **overstates** the implied move, by roughly
sqrt(k) for k debit dates. If the design fails under this assumption it fails under every weaker one.

**Two further generosities, stated so they are not mistaken for estimates:**

1. **All SIP inflow is treated as equity deployment.** SIP money also flows to debt, hybrid and
   index-fund-of-fund schemes that never touch the NSE cash market.
2. **Deployment is treated as same-day.** In practice T+1 allotment and staged deployment spread it.

## 4. SOURCES, AND WHAT IS ACTUALLY AVAILABLE

**NSE cash-market turnover — daily, 2015-01-01 → 2026-09-21, already on disk.** Summed across every
row and every series of NSE's own daily bhavcopy (`TOTTRDVAL` in the legacy format, `TtlTrfVal` in
UDiFF), the 2,893 trading days fetched by `src/fetch_cash_bhavcopy.py`. The two formats were
cross-checked on their 2024 overlap and agree on all 1,914 EQ symbols with zero disagreements
(commit `dcad806`). Sample: ₹38,255 crore on 2017-09-28, ₹115,863 crore on 2025-06-10.

**NIFTY 500 daily closes — `data/nifty500_daily_2015_2026.csv`, 2,884 days**, from NSE's
`ind_close_all` archive, exact-name matched across the CNX→NIFTY rename (commit `dcad806`).

**AMFI monthly SIP contribution — and this does NOT reach back to 2016.** Verified 2026-09-22:

| source | carries monthly SIP? | evidence |
|---|---|---|
| AMFI monthly report (MCR) `.xls` | **only Aug-2026** | Apr/May/Jul-2026 and Apr/Oct for 2018–2025 all have 11 columns and no SIP field; Aug-2026 has it at column 11 |
| AMFI monthly report PDF, pre-2018 | **no** | Mar-2017, Feb-2018, Mar-2018, Apr-2018 extract 17k–23k characters of text containing **no occurrence of "SIP"** |
| **AMFI Monthly Note PDF** | **yes, 6–7 months per note** | text-extractable; `SIP monthly contribution (crore)` row |
| AMFI Monthly Note archive depth | **June 2024 onwards** | 27 notes listed |

**So the usable series is roughly Jan-2024 → Aug-2026, about 32 months**, assembled from overlapping
Monthly Notes. Each month appears in up to six notes, and **the script must assert that every
overlapping report of a month agrees**; a disagreement is an error, not something to average away.
Known anchors: **Aug-2026 ₹32,297 crore**, Apr-2025 ₹26,632 crore.

**THE ASSUMPTION THIS FORCES, STATED PLAINLY.** The kill condition turns on the *largest* month. It
is assumed that no month before Jan-2024 had a larger SIP inflow than the largest in the covered
window. This is consistent with every published account of Indian SIP growth, but **it is an
assumption, not something this pre-check verifies**, because the data to verify it is not
machine-readable from AMFI's archive. It matters in one direction only: if some earlier month were
larger, the true maximum would be larger and a kill could be false. The verdict therefore reports
**by how much** the largest month would have to grow to reach the bar, so the margin is legible.

The **median** is reported over the covered window and is labelled as such. It is not a median since
2016 and must not be quoted as one.

## 5. WHAT IS COMPUTED

Per month over the covered window: SIP inflow Q (rupees), the mean daily NSE cash turnover V of that
month, the ratio Q/V at maximum concentration, and the implied move `Y·σ·sqrt(Q/V)` in bps.

Reported: **the largest month and its implied move**, the **median month**, the move at Y = 1.0, the
**break-even Y**, and the verdict against §1.

## 6. WHAT WOULD MAKE THIS WRONG

- **The square-root law is calibrated on single-name metaorders**, not on a market-wide flow spread
  across hundreds of names. Applying it to aggregate flow against aggregate turnover is a stretch,
  and it is a stretch in the generous direction: a diversified flow moves any one name less.
- **Q/V may exceed the law's calibrated range.** The square-root law is estimated for metaorders of a
  few percent of daily volume. At maximum concentration this ratio may be far larger, where the law
  is extrapolation, not measurement.
- **Turnover is endogenous.** A day with large SIP deployment may have higher turnover, which would
  lower Q/V and the implied move.
- **A move is not a tradable edge.** Even a move above the bar would have to be predictable in
  direction and timing, which this pre-check does not address and which a later phase would have to
  pre-register separately.
- **Only the maximum is decisive.** A median far below the bar with a maximum above it would mean a
  rare-event strategy, and the count of qualifying months is reported for that reason.

## 7. STANDING RULES

Per `STANDING_RULES.md` rule 1, this pre-check states its estimator and its assumptions before any
figure is computed, and measures its inputs from real data where that data is cheap — turnover and
volatility are measured, concentration and Y are assumptions and are labelled as such. Every figure
names its script and its run. This document is not edited retroactively; corrections go in a numbered
addendum. The verdict is recorded in `TEST_REGISTRY.csv` whichever way it goes.
