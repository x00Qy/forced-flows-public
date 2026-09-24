# GATE — blinded nuisance-parameter measurement, Phase 2 (F&O ban-list entry)

**Committed before the data it consumes is downloaded and before any estimate exists.**

`b8592ca` recorded that Phase 2's pre-check verdict is superseded: the `1031c76` PASS
(MDE 42.44 bps against a 71.35 bps bar) clustered on the event date only, and under the two-way
(week × stock) estimator that `PREREG_BAN_LIST_ENTRY.md` names as primary, the MDE is 126.64 bps at
the assumed SD of 5% and ρ_stock 0.25 — **1.78× the bar, and 0 of 9 grid cells clear.**

Whether Phase 2 is powered therefore turns on **ρ_stock, ρ_week and the per-event CAR SD**, none of
which has been measured. The design clears only if ρ_stock ≲ 0.03 or SD ≈ 2.8%.

**This document is the gate, not the test.** It measures those three nuisance parameters and nothing
else, decides on them alone whether Phase 2 proceeds, and is fixed before a single price is fetched
so the decision cannot be reverse-engineered from the answer.

---

## 1. Blinding — what the gate script may and may not compute

The gate script `src/gate_ban_list_nuisance.py` **estimates only ρ_stock, ρ_week and the per-event
CAR standard deviation, from mean-removed CARs.**

**It must never compute, print, log, return or persist:**

- the mean CAR, over the full sample or any subset;
- any t-statistic or p-value on the real data;
- per-event CARs, or any sum, quantile or sign count of them from which a mean is recoverable;
- per-year, per-stock or split-half means.

**Enforced structurally, not by care.** The data layer ends at one function that returns residuals
and does not return the mean:

```
    prepare_residuals(...) -> (residuals, stock_labels, week_labels, counts)
```

The grand mean is subtracted inside it and goes out of scope. Nothing downstream ever holds it.
Every published quantity is emitted through a single writer holding an explicit allow-list of keys;
a key not on the list is a hard error, not a warning.

**What blinding is, and what it is not.** The raw bhavcopy on disk obviously contains the answer;
anyone could compute the mean CAR from it in one line. The blinding is **procedural** — its
integrity rests on the gate script being the only thing run against the assembled event set before
`PREREG_BAN_LIST_ENTRY.md` is locked. It is stated this way rather than claimed to be stronger than
it is.

**Why mean-removal costs nothing.** Residual second moments carry no information about the mean, so
removing it loses nothing the gate needs. It induces a small **downward** bias in the pair
covariances, of order ρ·c̄/n ≈ 0.008 at ρ 0.25 — anti-conservative, therefore measured in §2's dry
run rather than waved at, and absorbed by §3's upper bound.

## 2. Estimator — method-of-moments variance components

Model on the kept events, i indexed by stock s(i) and ISO week w(i):

```
    CAR_i = mu + u_s(i) + v_w(i) + e_i
    Var(u) = sig2_s     Var(v) = sig2_w     Var(e) = sig2_e
    rho_stock = sig2_s / sig2      rho_week = sig2_w / sig2      sig2 = sig2_s + sig2_w + sig2_e
```

From residuals r (mean removed), with c_s entries in stock s and m_w in week w:

```
    sig2_hat  = sum_i r_i^2 / (n - 1)
    C_stock   = [ sum_s ( T_s^2 - sum_{i in s} r_i^2 ) ] / sum_s c_s (c_s - 1)      T_s = sum_{i in s} r_i
    C_week    = [ sum_w ( T_w^2 - sum_{i in w} r_i^2 ) ] / sum_w m_w (m_w - 1)      T_w = sum_{i in w} r_i

    rho_stock_hat = C_stock / sig2_hat        rho_week_hat = C_week / sig2_hat
    SD_event_hat  = sqrt(sig2_hat)
```

**Why the two components are separately identified here, and it is a property of the design, not an
assumption.** The 5-trading-day same-stock exclusion (`PREREG_BAN_LIST_ENTRY.md` §2) means two kept
entries of the same stock are never closer than five sessions, and an ISO week holds at most five
sessions. **So no same-stock pair shares a week, and no same-week pair shares a stock.** `C_stock`
therefore estimates sig2_s uncontaminated by sig2_w, and `C_week` estimates sig2_w uncontaminated by
sig2_s. This is asserted against the real event set before either is used: if any same-stock pair is
found in one week, the gate aborts rather than reporting a confounded number.

**Dry run, before the estimator touches real data.** On synthetic panels with **planted** ρ values,
over (ρ_stock, ρ_week) ∈ {0.02, 0.15, 0.25, 0.35} × {0.05, 0.15, 0.25} and SD ∈ {0.02, 0.05}:

- each ρ̂ recovers its planted value within **±0.02**, and SD̂ within **±2%**, averaged over 300 draws;
- the same check at **ρ_stock = 0** must return ρ̂_stock ≈ 0 — the estimator must not manufacture a
  correlation, since a spurious one closes Phase 2;
- §3's upper bound covers the planted truth on at least **90%** of draws, measured, not assumed.

**Any arm failing means the gate does not run.** A nuisance estimator that was never checked against
a known answer is exactly the failure this project keeps finding after the fact.

## 3. Conservatism — bounds, not point estimates

The gate uses the **upper end of a one-sided 90% interval** for ρ_stock and for SD_event, never the
point estimate. Both enter the MDE monotonically upward, so bounding them bounds the MDE.

Intervals come from a **nonparametric cluster bootstrap on residuals**, B = 2,000:

- **ρ_stock and SD_event**: resample **stocks** with replacement, carrying each stock's whole block
  of entries, and recompute. The upper bound is the 90th percentile.
- **ρ_week**: resample **weeks** with replacement, same construction. Reported with its bound for
  completeness; the gate's arithmetic uses the ρ_stock and SD bounds as specified.

Each bootstrap resamples the dimension it is bounding and is used for that dimension only —
resampling stocks destroys the week structure and vice versa, so neither interval is quoted for the
other's parameter.

## 4. The gate

With ρ_stock at its upper bound, ρ_week at its point estimate, SD_event at its upper bound, and the
**real** post-exclusion structure — actual n, actual stock entry counts, actual week assignment of
every kept event, df = min(G_week, G_stock) − 1:

1. **Recalibrate α\*** by the procedure `calibrate_two_way_alpha.py` already carries and which is
   committed at `b8592ca`: zero-effect panels on that structure, the two-way p-value of each, α\* =
   the empirical 1% quantile of the null p-distribution. **N = 20,000 sims**, four times the earlier
   resolution, because α\* is the 1%-quantile order statistic and at 5,000 its cell-to-cell spread
   (0.0052–0.0102) was mostly Monte-Carlo noise. A **fresh** 20,000-sim sample then measures the
   realised size at α\* with a 99% Clopper–Pearson band, as before.
2. **Compute the two-way MDE in bps** at α\*, 80% power:

   ```
   MDE = ( t(1 - alpha*/2, df) + t(0.80, df) ) * SD_two_way * 10,000   bps of notional
   ```

   with `SD_two_way` the simulated mean two-way SE on that structure, cross-checked against the
   closed form `[n + rho_s(sum c_s^2 - n) + rho_w(sum m_w^2 - n)] / n^2` (ARM 7 of
   `calibrate_two_way_alpha.py`), which must agree within 6%. They disagreeing means one of them is
   wrong and the gate aborts.

3. **The decision, and it is arithmetic, not judgement:**

   | | |
   |---|---|
   | **MDE ≤ 71.35 bps** | Phase 2 **PROCEEDS** to locking `PREREG_BAN_LIST_ENTRY.md` |
   | **MDE > 71.35 bps** | Phase 2 **CLOSES as underpowered** |

   71.35 bps is 3 × the 23.7821 bps round-trip delivery floor at ₹1 lakh notional, today's cost,
   regime (a) — unchanged from `PRECHECK_BAN_LIST.md`.

**The gate runs once.** It is not re-run with a different window, a different exclusion rule, a
different bar or a different bootstrap because the first answer was unwelcome. A closed Phase 2 is a
result and is recorded in `TEST_REGISTRY.csv` as one.

## 5. Inputs, fixed here

Applied exactly as `PREREG_BAN_LIST_ENTRY.md` states, before any estimation:

- **Events**: entries only — not in ban on the previous archived trading day, in ban on D. Source
  `data/fo_secban_2015_2026.csv`, 1,781 entries / 141 stocks / 2,893 archived days.
- **Window**: open of D to close of D+4. A single holding-period return, so **no close-to-close
  chaining is involved and §0.2's unadjusted `PREVCLOSE` never enters the CAR.**
- **Benchmark**: NIFTY 500 over the identical interval, open D to close D+4. Beta fixed at 1.
- **Same-stock exclusion**: drop an entry within 5 trading days of that stock's previous *kept*
  entry, forward-greedy (`exclude_overlapping`).
- **Ex-date exclusion**: drop an event whose window contains a corporate-action ex-date on **D+1 to
  D+4** — splits, bonuses, rights, dividends — from NSE's corporate-actions records. **An ex-date on
  D itself is harmless**: entry is at the open of D, which is already the ex-price, so the
  open-to-close-D+4 return is unaffected.
- **Extreme daily returns**: a daily return beyond ±20% inside a **kept** window is logged and
  checked against the corporate-actions record. It is **never excluded on the strength of its
  outcome** — that would be selecting on the dependent variable.

Every exclusion count is reported. Counts are not means and leak nothing.

## 6. What would make this wrong

- **The bootstrap bound is asymptotic in the number of clusters.** At 141 stocks a 90% upper bound is
  itself uncertain; §2's dry run measures its coverage rather than assuming it.
- **ρ̂ is estimated on residuals from a fitted grand mean**, which biases pair covariances **downward**
  by O(ρ·c̄/n). Anti-conservative, small, measured in the dry run, and absorbed by the upper bound.
- **The variance-components model is additive and homoscedastic.** Real CAR variance differs across
  stocks; a single SD understates the tail. Fat tails make cluster-robust over-rejection worse, so
  α\* is if anything optimistic.
- **The gate conditions on the design being right.** If the window, benchmark or event definition is
  wrong, a powered verdict here does not rescue it.
- **A PROCEED verdict is not a result.** It says only that an effect of 71.35 bps would be detectable
  80% of the time. It says nothing about whether one exists.

## 7. Standing rules

Every figure names its script and its run. This document is committed **before** the gate script
exists and before the data is downloaded, and is not edited retroactively — corrections go in a
numbered addendum. The verdict is recorded in `TEST_REGISTRY.csv` whichever way it goes.
