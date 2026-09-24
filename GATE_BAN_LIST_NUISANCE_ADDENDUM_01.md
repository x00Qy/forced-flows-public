# ADDENDUM 01 to GATE_BAN_LIST_NUISANCE.md — the interval method, and a benchmark gap

**Written 2026-09-22, before the gate ran on real data.** `GATE_BAN_LIST_NUISANCE.md` §7 forbids
editing that document retroactively; this records two changes to it.

**No real-event return had been computed when every number below was produced.** The coverage work
is entirely synthetic. The only real-data quantities here are counts of dates. The blind of §1 holds.

---

## 1. What failed

§3 specified a one-sided 90% upper bound from a percentile cluster bootstrap. §2 required its
coverage to be **measured, not assumed**. It was measured, and it failed:

```
    rho_stock  84.0%      SD_event  86.7%      required 90%
```

**The direction is the one that matters.** An under-covering upper bound is *too low*, so it
under-states ρ_stock and SD, so it makes the MDE look smaller, so it makes Phase 2 look **better
powered than it is**. It was failing in the direction that flatters the design.

## 2. Diagnosis — spread, not centring

First measured on a balanced 60×8 panel, where the shortfall split evenly between bias and spread.
Re-measured on the **observed** structure — 141 stocks, one holding 75 entries, 66 holding three or
fewer — the split is quite different, and the observed structure is the one that governs:

```
    rho_s  rho_w      bias     in SD units    boot SD / true SD
     0.15   0.15   -0.00611       -0.15             0.817
     0.25   0.15   -0.00913       -0.15             0.806
     0.35   0.25   -0.01430       -0.19             0.813
```

**The whole-stock bootstrap under-states the sampling SD of ρ̂_stock by about 19%** once the blocks
are as unbalanced as they really are. The bias is real but secondary, and is closely predicted by
the closed form `E[r_i r_j] = C_ij − (R_i + R_j)/n + S/n²` (−0.0071 predicted against −0.0091
measured at ρ_s 0.25).

**This is why BCa is worse, not better.** BCa corrects *centring* — a bias-correction term z₀ and an
acceleration term from a delete-one-stock jackknife. Centring was never the main defect. Measured:
BCa at 0.90 reaches 77.2% worst-cell coverage against the plain percentile's 74.0%, and at 0.95
reaches 83.6%. Both fail. A method that targets the wrong defect does not stop failing by being
more sophisticated.

## 3. The replacement, and the rule that chose it

**B raised from 2,000 to 5,000** in `gate_ban_list_nuisance.N_BOOT`. The selected percentile sits far
enough into the tail that 2,000 draws did not resolve it: at q = 0.997, B = 2,000 reads the 6th
largest draw and B = 5,000 the 15th. The calibration is **tied to B** — a far-tail quantile of a
different number of draws is a different bound — and ARM 3 of `calibrate_interval_method.py` fails
the run if the two ever stop matching.

**Selection rule, fixed before the run:**

> Choose the smallest q such that, on **both** ρ_stock and SD_event, every grid cell's measured
> coverage has a **one-sided 95% Clopper–Pearson lower bound of at least 90%**, at 500 trials per
> cell. Re-validate that q on a fresh seed under the identical criterion. **If no q ≤ 0.999
> satisfies it, stop and report** — do not extend the grid to find one.

The lower bound, not the point estimate, because "worst cell ≥ 90%" on nine noisy estimates is not
the test it looks like. At 500 trials the binomial SE is ~1.3pp, so a method truly at 88% can show
≥90% in all nine cells by luck and be accepted. That is the failure that would let an under-covering
bound into the gate, and the CP bound removes it. At n = 500 it requires roughly **92%** observed,
not 90%.

Candidates were scored on **the same panels and the same bootstrap draws**, so no ranking difference
is Monte-Carlo noise between them.

## 4. The chosen method — percentile q\* = 0.997

Selection grid, 9 cells over ρ_stock ∈ {0.15, 0.25, 0.35} × ρ_week ∈ {0.10, 0.15, 0.25}, 500 trials
× 5,000 resamples per cell, worst cell and its 95% CP lower bound:

```
                          rho_stock              SD_event
    method             worst    CP LB        worst    CP LB
    percentile 0.900   74.0%    70.6%        80.6%    77.5%   fails   <- the original
    percentile 0.950   80.6%    77.5%        88.2%    85.6%   fails
    percentile 0.975   87.0%    84.3%        91.8%    89.5%   fails
    percentile 0.990   90.2%    87.7%        94.8%    92.9%   fails
    percentile 0.992   90.8%    88.4%        95.0%    93.1%   fails
    percentile 0.994   91.0%    88.6%        96.0%    94.2%   fails
    percentile 0.995   91.6%    89.3%        96.0%    94.2%   fails
    percentile 0.996   92.2%    89.9%        96.2%    94.5%   fails
    percentile 0.997   92.8%    90.6%        96.8%    95.2%   OK   <- smallest, chosen
    percentile 0.998   94.0%    91.9%        97.2%    95.7%   OK
    percentile 0.999   94.8%    92.9%        98.0%    96.6%   OK
    BCa 0.90           77.2%    73.9%        83.4%    80.4%   fails
    BCa 0.95           83.6%    80.6%        89.6%    87.1%   fails
```

**Fresh seed, independent streams, identical criterion:**

```
    rho_stock   worst cell 93.6%   95% CP LB 91.5%
    SD_event    worst cell 96.2%   95% CP LB 94.5%      CONFIRMED
```

`GATE_BAN_LIST_NUISANCE.md` §3's "upper end of a one-sided 90% interval" is unchanged as an
*intent*. What changed is the percentile at which the bootstrap is read to deliver it: **0.997, not
0.90**. `BOUND_Q` in the gate script is now 0.997.

Run: `src/calibrate_interval_method.py`, output `results/calibrate_interval_method_2026-09-22.txt`,
per-cell checkpoints in `results/interval_cov/`.

## 5. The NIFTY 500 benchmark gap

Nine days trade in the cash bhavcopy but are absent from NSE's `ind_close_all` archive:

```
    2015-02-02  2015-03-12  2015-03-13  2015-05-19  2015-07-08
    2015-09-04  2015-10-16  2015-12-01  2016-06-20
```

Re-probed 2026-09-22: **all nine still return HTTP 404**, so this is a permanent hole in NSE's index
archive, not a fetch failure. Each was a **real trading session**, confirmed independently — NSE's
F&O ban archive holds a file for every one of the nine dates.

**Rule, added to §5 of the gate document and to `PREREG_BAN_LIST_ENTRY.md` §2 identically:** drop any
event whose window [D, D+4] contains one of these days. **12 of 1,781 entries (0.67%)**, decided on
dates alone.

Only 6 of the 12 are arithmetically fatal — those whose D or D+4 is a gap day, since the CAR needs
only the benchmark open on D and close on D+4. The rule still drops all 12, because a rule stated on
the whole window is decidable before any return exists and cannot be argued into a different shape
once the answer is known. The gap set is **derived** in the gate script, never hardcoded, so a change
in the data surfaces as a changed count rather than passing silently.

## 6. What this does not fix

- **Coverage is measured at planted Gaussian components.** Real CARs have fatter tails, which widens
  the true sampling distribution and pushes coverage **down**. q\* is a correction fitted to this
  generating model, not a distribution-free guarantee.
- **q\* = 0.997 is a large adjustment**, and it is an admission: the whole-stock bootstrap is a poor
  variance estimator for ρ̂_stock on a panel this unbalanced. It is repaired, not rehabilitated.
- **The calibration is a constant, not a theory.** It holds at these cells and carries no claim
  beyond them, which is why §4's rule — realised values must land inside the grid, or the result is
  reported as possibly mis-sized — still applies and is unchanged.
- **A separate inconsistency, flagged and NOT fixed here:** `PREREG_BAN_LIST_ENTRY.md` §0.2 still
  mandates an explicit corporate-action price adjustment plus a reproduction gate, while the gate
  document handles corporate actions by **exclusion only**. The two documents disagree. That is a
  substantive design question, not a clerical one, and it is left for decision rather than resolved
  by an addendum written for another purpose.
