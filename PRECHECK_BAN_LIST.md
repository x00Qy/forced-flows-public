# PRE-CHECK — F&O ban list, forced flows: Phase 2 feasibility

**Written 2026-09-21, committed before `src/precheck_ban_list.py` exists.** Nothing below has been
run. No price data is required: this is a power calculation on the event structure, as Phase 1 was.

## The kill condition, locked here

> **Phase 2 (ban list) closes if the clustered MDE (p<0.01 two-sided, 80% power, t with G−1 df)
> exceeds 3× the delivery floor at ₹1 lakh notional at the middle SD and intra-cluster correlation
> cell, using the sourced count of distinct ban-entry dates as G.**

"Middle" is the (per-event CAR SD = 5%, intra-cluster ρ = 0.2) cell of the grid in §4.

## 1. The mechanism, and why the test is two-sided

When a stock's aggregate F&O open interest crosses 95% of its market-wide position limit, NSE puts
it in a **ban period**: no new positions, only reduction. That is a forced flow — participants who
would otherwise have opened or rolled positions cannot, and some existing positions are unwound
under time pressure rather than on their own schedule.

**The sign of the resulting price move is not settled in advance, and this pre-registration does not
pretend otherwise.** Two mechanisms pull opposite ways. Forced unwinding of crowded longs in the
derivative can drag the cash price down; equally, a ban caps further speculative *short* build-up
and can squeeze prices up. Which dominates is an empirical question, plausibly varying with whether
the pre-ban open interest was net long or net short — which this pre-check does not observe.

**So the test is TWO-SIDED.** Declaring a direction now and testing one-sided would buy power by
assuming the thing in question. The kill condition names two-sided explicitly so it cannot be
loosened later.

## 2. What counts as an event, and what G is

**An event is a stock ENTERING the ban list** — the first day it appears after being absent. It is
**not** every day it remains banned. A stock that sits in the ban list for nine consecutive days is
**one** event, not nine. Counting ban-days would inflate n by roughly the mean ban duration and
would be the same inflated-n error `event_study.py`'s ARM 5 measures.

**G is the number of DISTINCT ban-entry dates.** Several stocks can enter on the same day —
typically when a sector moves together — and those share that day's market shock, so they are one
cluster, not several independent draws.

Unlike index reconstitution, ban entries are **not** confined to a scheduled calendar. They occur
whenever utilisation crosses the threshold, so G could be far larger here than Phase 1's 110. That
is the reason this phase is worth a separate pre-check rather than being closed by analogy.

## 3. The bar

3 × the round-trip delivery-equity floor at **₹1 lakh notional**, from
`yalgo_core.equity_cost_model` at today's rates, printed with its components — identical to Phase 1
so the two phases are comparable. Today's cost, regime (a); nothing here prices a historical trade.

## 4. The estimator and the grid

Reusing Phase 1's power code unchanged — `sd_cluster_mean`, `clustered_mde`, `g_required` and the
planted-effect dry run — rather than rewriting them:

```
sd_cluster = SD_event × sqrt((1 + (m − 1)ρ) / m)
se         = sd_cluster / sqrt(G)
MDE        = (t_{0.995, G−1} + t_{0.80, G−1}) × se
```

`m` is the **mean entries per ban-entry date, measured from the inventory**, not assumed — this
differs from Phase 1, where the per-cluster count could not be sourced.

Window: **5 trading days after entry**, `[+1, +5]`, excluding the entry day itself. The entry day is
excluded because the ban is announced after the close for the following session, so day 0 is
contaminated by whatever drove utilisation across the threshold.

Grid: SD_event ∈ {3%, 5%, 8%} × ρ ∈ {0, 0.2, 0.4}. **The (5%, 0.2) cell decides.** The SD values are
lower than Phase 1's because the window is shorter and the names are F&O-eligible, hence larger and
less volatile than a Midcap 150 addition — but they remain assumptions, not measurements.

## 5. Inventory requirements, and what counts as honest

Source: **NSE's daily securities-in-ban-period files** (`fo_secban`) from the official NSE archives.
Persist every file fetched to disk, as Phase 1 persisted its press-release list — a figure from a
live endpoint is not reproducible unless its input is saved.

Report **per year**: number of ban entries, number of distinct entry dates, and the **mean and max
entries per date**. Where the archive does not reach back, say so per year rather than
interpolating. An incomplete inventory understates G, which understates power — so an UNDERPOWERED
verdict on partial data is conservative, while a POWERED one would need the gap closed first. That
asymmetry is the same one Phase 1 relied on and it is stated here in advance.

## 6. Regression-discontinuity feasibility — inventory only, no power calculation

A ban triggers at a **95% MWPL utilisation threshold**, which is a candidate regression
discontinuity: stocks just above and just below 95% differ only by noise in the running variable.
That is a sharper design than an event study and would be worth its own phase.

**This pre-check does NOT power it, and must not report an MDE for it.** It answers only: can daily
MWPL utilisation be reconstructed from the F&O bhavcopy open interest already on disk plus NSE's
published MWPL figures? The deliverable is a list of which inputs exist, over which date range, and
what is missing — nothing more. Powering an RD design needs the density of the running variable near
the threshold, which requires the reconstruction to exist first.

## 7. What would make this wrong

- **SD and ρ are assumptions**, as in Phase 1. The grid makes the sensitivity visible.
- **Ban entry is defined by appearance in the file**, so a gap in the archive manufactures a spurious
  "entry" when coverage resumes. Missing dates must be reported, not silently bridged.
- **The 5-day window is a choice**, fixed here so it cannot be selected after seeing which window is
  significant.
- **Selection into ban is not random.** Banned stocks are, by construction, ones with extreme
  derivative positioning — so any measured CAR is conditional on that, and is not a statement about
  stocks in general.
- **Entries cluster in sector waves**, which is why ρ is on the grid at all and why clustering by
  entry date is not optional.

## 8. Standing rules

The dry run runs first and gates the inventory, reusing Phase 1's planted-effect check. Every figure
names its script, its run and its n. This document is not edited retroactively; corrections go in a
numbered addendum. A killed pre-check is recorded in `TEST_REGISTRY.csv` with verdict
`PRECHECK_KILLED`, because killed pre-checks count toward the program stopping rule.
