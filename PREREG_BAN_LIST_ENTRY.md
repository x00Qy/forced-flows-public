> **NEVER LOCKED: Phase 2 closed at the nuisance gate (see Addendum 02). Kept as a reusable design.**

# PRE-REGISTRATION — F&O ban-list entry, cash-market CAR

**DRAFT, uncommitted.** Written 2026-09-21 after the Phase 2 pre-check found the design powered
(`99f3afb`, MDE 0.4244% against a 0.7135% bar) and after the dry run in `src/event_study.py` passed
all six arms. No price data has been downloaded in bulk and no test has been run.

**Two verification results below change the design and are stated before the specification, not
after it.**

---

## 0. Two things verified first, because the design depends on them

### 0.1 The ban list is known before the open of D — so entry at the open of D is not look-ahead

NSE Clearing, *Risk Management → Equity Derivatives → Position Limits*, section **"Market Wide
Position Limits (for Derivative Contracts on Underlying Stocks)"**, verbatim:

> "At the end of each day the Exchange disseminates the aggregate open interest across all
> Exchanges in the futures and options on individual scrips along with the market wide position
> limit for that scrip and tests whether the aggregate open interest for any scrip exceeds 95% of
> the market wide position limit for that scrip. If yes, the Exchange takes note of open positions
> of all client/ TMs as at the end of that day in that scrip, and **from next day onwards** the
> client/ TMs should trade only to decrease their positions through offsetting positions till the
> normal trading in the scrip is resumed."

> "The normal trading in the scrip is resumed only after the aggregate open interest across
> Exchanges comes down to **80% or below** of the market wide position limit."

and the file's own section heading on the same page:

> **"Security in ban period for the next trade date - F&O segment"** — "Download the file for
> Security in ban period for **the next trade date** (.csv)"

**So the test is run at the close of D−1 and the file published that evening names the securities
banned for trade date D.** `fo_secban_DDMMYYYY.csv` is stamped with the trade date it *applies to*,
not the date it was produced. Corroborated directly: at 01:35 IST on 2026-09-22 — 7h 40m before the
09:15 open — the live endpoint already returned *"Securities in Ban For Trade Date 22-SEP-2026"*.

**Consequence, and it is the one this hinged on: entry at the OPEN of D is available to a
participant who reads the file the previous evening. It is not look-ahead.** Had the file only
appeared on the morning of D, the entry would have had to move to the close of D and the whole
window would shift.

This also fixes the 95%/80% hysteresis from an official source, which is why §1 defines an event as
an entry and never as ban status.

### 0.2 `PREVCLOSE` is NOT corporate-action adjusted — the premise this was checked against is false

The check was expected to show that `CLOSE / PREVCLOSE` chaining repairs the discontinuity that raw
`CLOSE` has at an ex-date. **It does not. Both are equally broken**, because NSE's bhavcopy
`PREVCLOSE` is the raw prior-session close, unrestated.

**BHEL, Bonus 1:2, ex-date 2017-09-28** (ex-date from NSE's own corporate-actions API; 5 days of
legacy bhavcopy fetched):

```
  date             OPEN    CLOSE  PREVCLOSE   raw ret  chained ret
  2017-09-27     129.40   124.65     127.75   -2.43%      -2.43%
  2017-09-28      82.80    82.65     124.65  -33.69%     -33.69%   <= EX-DATE
  2017-09-29      84.00    83.95      82.65    1.57%       1.57%

  prior CLOSE 124.65 -> ex-date PREVCLOSE 124.65   ratio 1.0000   (2/3 = 0.6667)
```

`PREVCLOSE` on the ex-date is **124.65**, identical to the prior raw close, not the 83.10 a 1:2
bonus implies. Chaining reproduces the same spurious **−33.69%**.

The modern format behaves identically. **CANBK, face-value split, ex-date 2024-05-15**, UDiFF
`PrvsClsgPric`:

```
  2024-05-14     555.40   566.55        549.35    3.13%
  2024-05-15     116.25   119.00        566.55  -79.00%  <= EX
     prior CLOSE 566.55 vs ex-date PrvsClsgPric 566.55  ratio 1.0000
```

**Consequences, binding on this design:**

1. An **explicit corporate-action adjustment is mandatory**, in both bhavcopy eras. Ex-dates and
   ratios come from NSE's corporate-actions API per symbol over 2015–2026, persisted to disk like
   every other input.
2. **A gate before any test runs:** the adjustment must reproduce continuity on these two exact
   cases — BHEL 2017-09-28 and CANBK 2024-05-15 — or the run is void. A silent failure here injects
   a −33% or −79% "abnormal return" into whichever event window contains it.
3. **Belt and braces:** any event whose window [D, D+4] contains an ex-date for that stock is
   **dropped**, and the count dropped is reported. Adjustment and exclusion are independent
   defences and both are pre-registered, because a single defence against a −79% artefact is thin.

---

## 1. Event definition

An event is a stock **entering** the ban list: **not in ban on the previous archived trading day,
in ban on D**. A stock banned for nine consecutive sessions is one event.

Forced by §0.1's hysteresis: entry at 95%, exit at 80%, so ban *status* is not a function of
same-day utilisation and only *entry* is an event. Measured: 3.23 stocks sit in ban on a typical day
against 0.62 new entries, a 5.24× ratio — counting ban-days would inflate n by the mean ban
duration.

Source: `data/fo_secban_2015_2026.csv`, 2,893 archived trading days 2015-01-01 → 2026-09-21,
**1,781 entries across 141 stocks and 1,203 distinct entry dates**.

## 2. Design

| | |
|---|---|
| **Entry** | the **open of D**, the first banned session — available per §0.1 |
| **Exit** | the **close of D+4** |
| **Window** | open D → close D+4, five sessions |
| **Return** | corporate-action-adjusted, per §0.2 |
| **Benchmark** | **NIFTY 500**, same interval, open D → close D+4 |
| **Abnormal return** | stock return − benchmark return over the identical interval |
| **Same-stock exclusion** | drop an entry within **5 trading days** of that stock's previous *kept* entry |
| **Benchmark-gap exclusion** | drop an entry whose window [D, D+4] contains a day with no NIFTY 500 record |
| **Primary SE** | **two-way clustered, week × stock** (Cameron–Gelbach–Miller) |
| **Sensitivities** | date-clustered, and naive — reported, never primary |
| **Test** | **two-sided, p < 0.01** |

**Why NIFTY 500 and not NIFTY 50.** Ban-list names are mid- and small-cap heavy — INDIACEM,
BALRAMCHIN, IBREALEST, RBLBANK. NIFTY 50 would leave a systematic size tilt in the "abnormal"
return. NIFTY 500 spans the cap range the sample actually occupies. Beta is fixed at 1; §7 records
what that costs.

**Why the benchmark is measured open-to-close over the same interval**, not close-to-close: the
position is entered at the open of D, so the benchmark must be too, or the first few hours of market
move land in the abnormal return.

**Why the same-stock exclusion.** A [+1,+5]-style window overlaps itself when a stock re-enters
within five sessions, and overlapping windows share returns, making the two CARs mechanically
correlated. Measured: **175 of 1,781 entries (9.8%)** fall within 5 trading days of the same stock's
previous entry; a third of consecutive same-stock pairs are within 10 sessions. The rule is
forward-greedy — the earlier event is kept, the later dropped — so it never depends on anything
after the event it is applied to.

**Why the benchmark-gap exclusion, and why it is stated on dates.** Nine days trade in the cash
bhavcopy but are absent from NSE's `ind_close_all` archive — 2015-02-02, 2015-03-12, 2015-03-13,
2015-05-19, 2015-07-08, 2015-09-04, 2015-10-16, 2015-12-01 and 2016-06-20. Re-probed 2026-09-22, all
nine still return HTTP 404, so this is a permanent hole in NSE's index archive and not a fetch
failure; each was a real session, confirmed independently by the F&O ban archive holding a file for
the same date. **12 of 1,781 entries (0.67%)** have a window touching one. Only an endpoint gap is
arithmetically fatal — 6 of the 12 — but the rule drops all events whose window touches a gap day,
because a rule stated on the whole window is decidable from dates alone, before any return exists,
and cannot be argued into a different shape once the answer is known. The count is reported.

**Why two-way clustering is primary.** Date clustering handles names entering together. It does not
handle **the same stock entering repeatedly**, and **the top ten names carry 28.6% of all entries**.
Two SAIL entries months apart are not independent draws however far apart their dates are. Measured
in the dry run, under zero effect on the real structure (141 stocks, observed counts, 499 weeks,
ρ_stock 0.25, ρ_week 0.15):

```
       two-way      20/1,000 =   2.00%
       date-only   253/1,000 =  25.30%
       naive       369/1,000 =  36.90%
```

**A date-only reading would reject a true null a quarter of the time.** That is why it is a
sensitivity and not the headline.

## 3. The size distortion, stated in advance

**The nominal p < 0.01 bar buys about 2% actual size on this structure, not 1%** — measured above.
With *balanced* clusters at the same G = 141 the size is ~1.25%, so the excess is the **observed
imbalance**: one stock carries 75 of 1,781 entries. Cluster-robust inference is known to over-reject
with few and unbalanced clusters.

This is recorded here rather than discovered afterwards. **It is a live decision, not a resolved
one** — the bar stays at p < 0.01 as specified, and a result landing just inside it must be read as
roughly 2%-level evidence, not 1%. Tightening the nominal bar to ~0.005 to recover a true 1%, or
pre-registering a wild cluster bootstrap as a gate, are the two alternatives; neither is adopted
here without a decision.

## 4. Viability rule — and why only a positive effect is tradable

The effect is **tradable only if it is positive**, and this is a property of the instrument, not a
preference:

- A **positive** CAR is capturable by **buying at the open of D and selling at the close of D+4** in
  the cash market, which is what `yalgo_core.equity_cost_model` prices.
- A **negative** CAR would require **shorting**. Indian cash-market intraday shorts cannot be carried
  overnight, and a five-session short needs stock borrow through SLB, which for a name in F&O ban is
  precisely when borrow is scarce and expensive. **The F&O route is closed by construction** — the
  ban forbids new positions in exactly that stock's derivatives. So a negative result is a finding
  about the world, and not one this design can trade.

**The test remains two-sided** (§2), because the direction is not settled in advance and a one-sided
test would buy power by assuming the answer. Two-sidedness governs *significance*; tradability
governs *what a significant result is worth*. They are separate and are kept separate.

**Viability requires all three:**

1. mean CAR **positive**;
2. **significant** at two-sided p < 0.01 on two-way clustered errors, read against §3;
3. point estimate **≥ 3 × the delivery floor at ₹1 lakh notional** — currently **0.7135%**
   (23.7821 bps round trip × 3), today's cost, regime (a).

Failing any one is a close. Clearing 2 but not 3 is a real effect that is not worth trading, and is
reported that way.

## 5. Pre-registered robustness

- **Split-half sign consistency.** First and second halves of the sample by entry date must agree in
  sign. Disagreement is a close regardless of the pooled p-value — the characteristic shape of a
  spurious result, and the rule that killed five P1 candidates.
- **Realised-MDE null rule.** If the result is not significant, the **realised** MDE is computed from
  the achieved SE and n, and reported beside the point estimate. A non-significant result whose
  realised MDE exceeds the 3× bar is recorded as **"not tested at an effect size that matters"**, not
  as "no effect" — the reclassification P1's closure audit had to apply after the fact to two of
  seventeen strategies.
- **A non-significant result is DEAD, not "needs more data."**

## 6. Descriptive, carrying no p-value and not promotable

Reported alongside, never as the headline: the result with the **top 10 stocks removed** (those ten
carry 28.6% of entries); per-year mean CAR; the count of events dropped by the same-stock rule, by
the ex-date rule and by the benchmark-gap rule; and the two sensitivity SEs from §2.

## 7. What would make this wrong

- **Beta is fixed at 1.** Part of a high-beta name's "abnormal" return is market exposure. A
  pre-event estimation window would add its own error; the restriction is real and is stated.
- **Selection into ban is not random.** Banned names have extreme derivative positioning by
  construction, so any CAR is conditional on that and is not a statement about stocks generally.
- **The open of D is a stated entry, not a measured fill.** No slippage is modelled; the cost model
  covers statutory charges and DP, not the spread on a stressed small-cap open.
- **165 weekdays are absent from the archive** and the endpoint does not distinguish holiday from
  gap. One entry follows a gap of >4 days and is reported, not removed.
- **The pre-check's SD assumption was 5%**, unmeasured. Realised SD is reported and, if it lands far
  from 5%, the achieved power is restated.

## 8. Standing rules

Every figure names its script, its run and its n. This document is committed **before** the analysis
script exists, and is not edited retroactively — corrections go in a numbered addendum. The result
is recorded in `TEST_REGISTRY.csv` whichever way it goes.
