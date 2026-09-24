# ADDENDUM 01 to GATE_SIP_TIMING.md — the gate ran; Phase 3 closes

**Run 2026-09-22, `src/gate_sip_timing.py`, outputs `results/gate_sip_timing_2026-09-22.csv` and
`results/gate_sip_timing_run_2026-09-22.txt`.**

**VERDICT: `CLOSE_UNDERPOWERED`. MDE 53.20 bps against a 16.9664 bps bar — 3.14×.**

---

## 1. The result

```
    SAMPLE (counts only -- no return grouped by SIP status)
      index days                   2,884
      3-session windows in scope   2,643    2016-01-01 -> 2026-09-17
      months / SIP events            129
      other-day windows per month   20.0 median, 19.5 mean

    NUISANCE (all days, every day a potential D)
      SD of the 3-session return   0.016425  = 164.3 bps
      rho_1 +0.6143   rho_2 +0.2572   rho_3 +0.0222

    POWER (p<0.01, 80%, clustered by month, df 128)
      VIF 2.6223   SD(d) 0.017469
      MDE  0.5320% = 53.20 bps        bar 16.9664 bps
      direct power check at that effect: 80.3% detected
```

**The gap is not a sample-size problem.** MDE scales as 1/√G, so clearing the bar at this volatility
would need **1,268 months — about 106 years** of index history. Equivalently SD(d) would have to
fall to 0.32× its measured value. Phase 3 is not "awaiting more data"; the data is the whole period.

## 2. The overlap flaw, measured twice

`GATE_SIP_TIMING.md` §5 compared the SIP window against **all** other windows in the month. Those
include the windows starting at D−2, D−1, D+1 and D+2, each of which shares one or two days with
D…D+2. That is a flaw with two separate consequences, and both were measured rather than argued.

**(a) Variance — it barely matters.** Restricting the comparison group to windows sharing **no day**
with D…D+2:

```
    comparison group                    m_other     VIF     SD(d)   MDE bps
    all other windows in the month         20.0  2.6223  0.017469     53.20
    sharing no day with D..D+2             16.0  2.5926  0.017706     53.93
```

Excluding the four contaminated starts costs four comparison windows a month and moves the MDE by
**+0.72 bps**. **Both readings fail the bar by more than 3×, so the verdict does not depend on which
is used.**

**(b) Attenuation — it matters more, and the original dry run hid it.** ARM 5 planted its effect
directly in `d`, the **difference**, which assumes a clean comparison group by construction. ARM 8
now plants the effect where it would really arise — in the **daily returns of D, D+1 and D+2** — and
measures what leaks:

```
    effect planted in DAILY returns of D..D+2 (10 bps/day):
      SIP window moves                             30.09 bps   (= 3 x 10, as it must)
      leak into the 20 overlapping comparison windows  3.02 bps
      leak into the 16 NON-overlapping ones            0.00 bps
      measured difference is 0.900 of the true effect  (clean: 1.000)
      closed form 1 - (L-1)/m_other = 0.900, matches
```

An effect spread over the window's L days leaks into the comparison windows at offsets
±1…±(L−1), the one at offset k carrying (L−k)/L of it, so the total leaked is L−1 and the
attenuation is **1 − (L−1)/m_other**. The simulation and the closed form agree to three decimals.

**So the primary MDE understates what a true effect must be. In true-effect terms it is
53.20 / 0.900 = 59.12 bps — 3.48× the bar, not 3.14×.** The flaw ran in the direction that
flattered the design, which is the direction this project keeps finding.

## 3. The pre-check and the gate agree, and that is the substantive finding

`PRECHECK_SIP_TIMING.md` did not close Phase 3, putting the largest month's implied move at 123.23
bps — but **only under whole-month-on-one-date concentration**, and it recorded that spreading across
the roughly seven usual debit dates gives **≈47 bps**, since impact scales as 1/√k.

**That 47 bps sits below this gate's 53.20 bps detection floor, and well below the 59.12 bps
true-effect floor.** The two phases converge from opposite directions: the effect size that survives
realistic concentration is smaller than the smallest effect this sample could detect. The pre-check's
"not closed" was never evidence of an edge, and the gate says the question cannot be settled either
way on eleven years of Indian index data.

## 4. Dose-response — dropped, and the cost of dropping it

`GATE_SIP_TIMING.md` §6 dropped the pre-registered tercile check. **Exactly two fiscal years carry an
FY-tagged SIP figure** in AMFI's machine-readable publications — FY 2024-25 at ₹24,113 crore average
monthly and FY 2023-24 at ₹16,602 crore, both from the March-2025 Monthly Note; the March-2026 note
carries none, and the monthly series begins only with the June-2024 note.

Two fiscal years cannot form terciles over an eleven-year sample, and running the check on the
27-month series was refused: over 2024–2026 SIP inflows barely vary, so the low tercile would not be
low and the test could not fail. **A dose-response test that cannot fail is not evidence.**

## 5. Forty-two of 129 events moved forward

The 10th is not a trading day in **42 of the 129 months** — weekends and exchange holidays — and the
rule moves the event to the next trading day. The rule is decidable from the calendar and never looks
ahead, so it introduces no bias. But a third of the sample sitting on the 11th, 12th or 13th weakens
the premise the date set rests on: that debits concentrate on a single calendar date. Combined with
§7 of the gate document — three of seven large AMCs impose no date restriction at all — the
comparison group is contaminated with real SIP flow from both directions.

## 6. The blind held

**No return grouped by SIP status, neither group's mean, no difference between them and no t or p on
the real series was computed at any point.** The results file carries 26 keys, every one on
`gate_sip_timing.ALLOWED`; an audit confirmed none fell outside it. `window_returns()` returns one
undifferentiated array over every day, `nuisance()` reduces it to a standard deviation and a vector
of autocorrelations, and the SIP calendar is used only to **count** events and comparison windows.
ARM 7 asserts `emit()` refuses `sip_day_mean`.

The blinding was and remains **procedural**: the price series on disk contains the answer, and the
integrity of the blind rested on this being the only script run against it. It was. Every figure in
§2, including the attenuation, comes from synthetic data or from the window geometry.

## 7. What is closed

**Phase 3 (SIP flow timing) is CLOSED as underpowered**, recorded in `TEST_REGISTRY.csv` as
`GATE_CLOSED_UNDERPOWERED`.

**This does not say the effect is absent.** It says an effect of 16.9664 bps — three times the NIFTY
futures statutory floor — would not be detectable 80% of the time at a 1% test on 129 months. Whether
SIP debits move the index on the 10th is untested and remains so.

And the bar it failed is a **lenient** one: statutory only, slippage excluded, brokerage zeroed. A
design that cannot clear that has no prospect against a realistic cost.
