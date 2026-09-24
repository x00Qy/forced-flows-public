# PRE-CHECK — index reconstitution, forced flows: Phase 1 feasibility

**Written 2026-09-21, committed before `src/precheck_index_recon.py` exists.** Nothing below has
been run. No price data has been touched, and none is required: this is a power calculation, not a
measurement.

## The kill condition, locked here

> **Phase 1 closes if no index set, individually or pooled, has a clustered MDE (p<0.01 two-sided,
> 80% power, t with G−1 df) at or below 3× the delivery floor at ₹1 lakh notional, under the middle
> SD and intra-cluster correlation assumptions.**

"Middle" is the (per-event CAR SD = 8%, intra-cluster ρ = 0.2) cell of the grid in §4. The other
eight cells are reported so the sensitivity is visible; they do not enter the verdict.

## 1. What is being asked, and why it is a power question first

The hypothesis Phase 1 would test is that stocks **added** to an index earn abnormal returns around
the announcement, because index funds are forced to buy them. That hypothesis is old and much
studied; what is not settled is whether a retail participant in this market could act on it after
costs.

Before running it, one thing can be checked for the price of arithmetic: **whether a test of it
could detect an effect the size that would matter.** If the smallest detectable effect is larger
than the effect that would be worth trading, the test cannot produce an informative answer either
way, and running it would generate a NO_ALPHA verdict that means "not tested at an effect size that
matters" — the reclassification P1's own closure audit had to apply to two of its seventeen
strategies after the fact. Doing it before is cheaper.

## 2. Why the clustering is the whole problem

Index reconstitution is **not** a stream of independent events. NIFTY indices reconstitute on a
**semi-annual schedule**, and every stock entering at a given review is announced on the **same
day** and takes effect on the **same day**. Ad-hoc changes (mergers, demergers, delistings) add a
few more dates.

So the number of independent observations is not the number of stocks added. It is the number of
**distinct announcement dates**, G. Fifty additions across ten years might be five or six stocks on
each of roughly twenty dates. Treating them as fifty independent draws is the inflated-n error that
`event_study.py`'s ARM 5 measures directly: at ρ = 0.3 with five events per date it turns a nominal
1% false-positive rate into 8.3%.

**Every figure in this pre-check is therefore computed on G, not on the event count**, and both are
reported side by side so the difference is never hidden.

## 3. The bar

3 × the round-trip delivery-equity floor at **₹1 lakh notional**, from
`yalgo_core.equity_cost_model` at today's rates, printed with its components.

The notional matters and is stated rather than defaulted: DP charges are a fixed rupee amount per
scrip per sell, so the floor in bps falls as position size rises. ₹1 lakh is a retail position size;
a larger one would face a lower bar, and that is a different claim.

The floor is **today's cost (regime a)**, consistent with
`PAPER_no_alpha_at_retail_cost_v2.md`. Nothing here prices a historical trade.

## 4. The estimator and the grid

For each index set, additions only:

```
SD of a cluster mean   sd_cluster = SD_event × sqrt((1 + (m − 1)ρ) / m)
standard error         se         = sd_cluster / sqrt(G)
MDE                    MDE        = (t_{0.995, G−1} + t_{0.80, G−1}) × se
```

`m` is the mean events per cluster from the inventory; `G` is the count of distinct announcement
dates. **t with G−1 degrees of freedom, not z** — G is small enough that the difference is
material, and using z would understate the MDE, which is the direction that flatters feasibility.

Grid: SD_event ∈ {5%, 8%, 12%} × ρ ∈ {0, 0.2, 0.4}. Nine cells per index set, four index sets
(NIFTY 50, NIFTY Next 50, NIFTY Midcap 150, and all three pooled). **The (8%, 0.2) cell decides.**

Those SD values bracket what short-window CAR dispersion looks like for Indian mid- and large-cap
single names; they are assumptions, stated as such, not measurements from this data. ρ = 0.2 is a
middle assumption between independence and the 0.3 used in ARM 5.

**Pooling across indices does not multiply G by three.** The three indices are reviewed on
overlapping calendars, so pooled G is the count of distinct dates across all of them, which is
smaller than the sum. The script computes it from the inventory rather than adding.

## 5. Verdict, per index set

**POWERED** if the (8%, 0.2) MDE ≤ 3× floor — the test could see an effect the size that would
matter. **UNDERPOWERED** otherwise. The kill condition fires only if **all four** are UNDERPOWERED.

A single POWERED set does not open Phase 1 on its own; it means the kill condition does not fire and
a pre-registration for that set would be written next, with its own hypothesis and bar.

## 6. What would make this wrong

- **The SD assumptions are assumptions.** They are not measured here, because measuring them needs
  the price data this pre-check exists to avoid loading. If the real CAR SD is far below 5%, the
  grid's low cell is the relevant one and the verdict could change. The grid exists so that is
  visible rather than buried in a point estimate.
- **ρ is assumed too**, and it interacts with m. A cell with m = 1 is unaffected by ρ entirely.
- **Additions only.** Deletions are a different hypothesis with a different sign and are inventoried
  but not powered here.
- **Announcement date, not effective date.** If the tradeable window is the effective-date flow
  rather than the announcement, G is the count of distinct *effective* dates instead, which for a
  scheduled review is the same small number. The choice is recorded so it cannot be switched after
  seeing a result.
- **The inventory may be incomplete.** Where announcement history cannot be sourced from
  niftyindices.com, the script says so per index and per year and does not fill the gap with an
  estimate. An incomplete inventory understates G, which understates power — so an UNDERPOWERED
  verdict on incomplete data is conservative, while a POWERED one would need the gap closed first.

## 7. Standing rules

The synthetic dry run runs first and gates the real inventory: an effect planted at the computed MDE
must be detected by the clustered test about 80% of the time, reusing `event_study.py`'s ARM 5
clustering structure. Every figure names its script, its run and its n. This document is not edited
retroactively; corrections go in a numbered addendum.
