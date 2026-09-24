# ADDENDUM 02 to GATE_BAN_LIST_NUISANCE.md — the gate ran; Phase 2 closes

**Run 2026-09-22, `src/gate_ban_list_nuisance.py`, output
`results/gate_ban_list_nuisance_2026-09-22.csv` and `results/gate_run_2026-09-22.txt`.**
The gate ran **once**, as §4 requires. It was not re-run with a different window, exclusion rule,
bar or bootstrap.

**VERDICT: `CLOSE_UNDERPOWERED`. Two-way MDE 120.42 bps against a 71.35 bps bar — 1.69×.**

---

## 1. The sample

```
    raw entries                                          1,781
    dropped, 5-day same-stock rule                         156
    dropped, ex-date in D+1..D+4                            45
    dropped, window touches one of the 9 NIFTY 500 gaps      12
    dropped, missing price/benchmark                         0
    KEPT                                                 1,568    140 stocks, 483 ISO weeks
    largest stock block 64,   sum c_s^2 40,454
    extreme daily returns >|20%| inside kept windows: 18 -- logged, never excluded
```

The benchmark-gap rule dropped exactly the 12 events predicted from dates in Addendum 01 §5. Not a
single event was lost to a missing price, so the 2,893-day bhavcopy and the 2,884-day NIFTY 500
series cover the design completely once the nine gap days are excluded.

## 2. Nuisance parameters, from mean-removed CARs

```
                         point     90% upper
    rho_stock          -0.0029        0.0184
    rho_week            0.1713        0.3159
    SD_event           7.7500%        9.5274%
```

Bounds read at the calibrated percentile q\* = 0.997 of a 5,000-resample whole-stock cluster
bootstrap (Addendum 01 §4).

**ρ_stock is indistinguishable from zero.** ARM 3 of the dry run establishes the estimator returns
≈0 at planted zero (−0.00045 over 400 draws), so −0.0029 is a reading, not an artefact of the
estimator. Repeat ban entries by the same stock are all but independent once week effects are
removed.

## 3. α\* and its validation

```
    alpha* = 0.009178        df 139        a nominal 0.01 buys 1.08% here
    fresh 20,000-sim validation at alpha*:
        214/20,000 = 1.070%     99% Clopper-Pearson [0.892%, 1.272%]     contains 1%
    two-way SE:  simulated 0.036252   analytic 0.036755   ratio 0.986   agree (<6%)
```

α\* was recalibrated **in place**, on the real post-exclusion structure at the bounded values, not
carried over from the grid. Its fresh-sample validation holds, so this part of the arithmetic is
sound regardless of §5 below.

## 4. The MDE and the verdict

```
    t crit 2.642348 + t power 0.844215
    MDE   1.2042%  =  120.42 bps
    bar                71.35 bps      (3 x 23.7821 bps delivery floor, today, regime (a))
    direct power check at that effect: 80.3% detected, expected 80%

    VERDICT: CLOSE AS UNDERPOWERED      shortfall +49.07 bps      1.69x the bar
```

## 5. The out-of-grid rule FIRED, and it is reported rather than waived

§4 of the gate document requires that realised correlations fall inside
ρ_stock ∈ {0.15, 0.25, 0.35} × ρ_week ∈ {0.10, 0.15, 0.25}, **or the result is reported as possibly
mis-sized.**

**ρ_week (0.1713) is inside. ρ_stock (−0.0029, upper bound 0.0184) is far outside — below the grid
floor of 0.15.** So q\* = 0.997 was selected and validated at correlations this data does not have,
and the ρ_stock and SD_event bounds therefore carry **unverified coverage at the realised values**.
This is stated because the rule said to state it, not because it was discovered afterwards.

**It does not change the verdict, and that is checked rather than asserted.** Holding α\* fixed and
recomputing the MDE from the closed form on the real structure:

```
    variant                             SD_mean    MDE bps   x bar   verdict
    bounds (the gate's own inputs)      0.03676     122.12    1.71    fails
    point estimates throughout          0.03257      88.00    1.23    fails
    point rho, ORIGINAL assumed SD 5%   0.03257      56.77    0.80    CLEARS
    rho_week = 0 too, SD 5%             0.02525      44.02    0.62    CLEARS
```

(The 122.12 in the first row is the closed form; the gate's own 120.42 uses the simulated SE. The
0.986 ratio in §3 is the difference.)

**Strip the bounds entirely and use point estimates and the design still fails by 23%.** The kill
rests on the point estimates, not on the possibly-mis-calibrated bound.

## 6. Diagnosis — volatility, not clustering

The last two rows of that table locate the cause exactly. **Hold everything else at its realised
value and restore only the assumed SD of 5%, and the design clears at 56.77 bps.**

```
    SD_event that would clear, holding the rest at realised values : 5.567%
    realised SD_event (point)                                      : 7.750%
```

The Phase 2 pre-check assumed a 5% per-event CAR standard deviation. The realised figure is
**7.75%, 55% larger**. A five-session window on a stock in F&O ban — extreme derivative positioning
by construction, mid- and small-cap heavy — is far more volatile than the assumption allowed. Two of
the three nuisance parameters came back benign; the one that was never in doubt is what closed it.

## 7. Correction to the `PRECHECK_SUPERSEDED` row's stated reason

The registry row of 2026-09-22 superseding `1031c76` states the cause as:

> "1031c76 pass used date-only clustering; under the primary two-way estimator power depends on
> unmeasured rho_stock"

**That attribution is wrong, and this is the correction.** ρ_stock is −0.0029. Stock-level
clustering is essentially absent from this sample and was never the binding constraint. The
superseding reasoning ran: two-way clustering is primary → the stock dimension inflates the variance
→ the pre-check's 42.44 bps is wrong. The conclusion was right, the mechanism was not.

What actually breaks `1031c76` is that **its power calculation used a different estimator from the
planned test and an unmeasured volatility assumption.** Of the 3.0× gap between 42.44 bps and the
realised figure, the week dimension and the SD together carry it; the stock dimension carries
essentially none. The row itself is left standing, uncorrected in place, per §7 of the gate
document — the correction lives here, where the evidence is.

This is the second time in this phase that a mechanism was asserted before it was measured. The
standing rule added to `STANDING_RULES.md` is the response.

## 8. The blind held

**No mean CAR, no t-statistic and no p-value on real events was computed at any point.**

`results/gate_ban_list_nuisance_2026-09-22.csv` contains 34 keys, every one drawn from
`gate_ban_list_nuisance.ALLOWED`. The mean, any t and any p are absent **by construction, not by
omission**: `prepare_residuals()` subtracts the grand mean inside itself and does not return it,
`_build_cars()` is private and called from nowhere else, and `emit()` raises on any key outside the
allow-list — ARM 7 asserts it refuses `mean_car` and accepts `rho_stock_hat`.

The blinding was and remains **procedural**: the bhavcopy on disk obviously contains the answer, and
the integrity of the blind rested on this being the only script run against the assembled event set.
It was. The one further computation performed — §5's robustness table — consumes only ρ and SD,
which are permitted quantities, and is labelled as a sensitivity rather than a second gate run.

## 9. What is closed, and what is not

**Phase 2 (F&O ban-list entry) is CLOSED as underpowered.** Recorded in `TEST_REGISTRY.csv` as
`GATE_CLOSED_UNDERPOWERED`. A closed phase is a result, not a pause: the design is not "awaiting more
data", because the sample is the entire archive from 2015 to 2026.

**This says nothing about whether the effect exists.** It says an effect of 71.35 bps would not be
detectable 80% of the time at a correctly sized 1% test on this sample. Whether ban entry moves the
cash price is untested and remains so.

`PREREG_BAN_LIST_ENTRY.md` is committed **never locked**, kept as a reusable design. Its §0.2
disagreement with this document over corporate actions — price adjustment plus a reproduction gate
there, exclusion only here — is **left unresolved and is now moot**, since no test will run under it.
It is flagged rather than quietly tidied, so that anyone reusing the design meets the open question
instead of inheriting a silent choice.
