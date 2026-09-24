# GATE — SIP timing, power before any return is grouped

**Committed before the gate script exists and before any SIP-day return has been computed.**

`PRECHECK_SIP_TIMING.md` (`0c52614`) did not close Phase 3: at maximum concentration the largest
month implies 123.23 bps against a 71.35 bps delivery bar. That verdict rests on two assumptions the
pre-check labelled as load-bearing — the whole month on one date, and a square-root law extrapolated
an order of magnitude beyond its calibrated range.

**This gate asks the question the pre-check could not: is a real SIP-day effect detectable at all?**
It measures only nuisance quantities, on all days, without ever grouping returns by SIP status.

---

## 1. Instrument and bar

**Instrument: NIFTY futures.** The pre-check priced a cash-market delivery round trip because it was
comparing against Phase 2. A flow-timing effect on an index is traded in the index future, so the
bar is the futures cost, not the delivery cost.

From P1's `src/data/spot_cost_model.py` at the rate era in force on 2026-09-22, one lot round trip:

```
    STT, sell side once, 0.05%      5.0000 bps    era effective 2026-04-01
                                                  provenance: zerodha.com/charges,
                                                  fetched 2026-09-07, verified=True
    transaction charge, per leg x2  0.3660 bps
    SEBI fee, per leg x2            0.0200 bps
    stamp duty, buy side once       0.2000 bps
    GST 18% on the above            0.0695 bps
    ------------------------------------------
    statutory round trip            5.6555 bps
```

**BAR = 3 x 5.6555 = 16.9664 bps.**

Every term is a percentage of notional, so the bar is **independent of index level and lot size** —
it does not drift with the 65-share lot or the index close.

**Two things it excludes, stated so the bar is not read as a full cost.** It is **statutory only and
excludes slippage**, exactly as Phase 2's 71.35 bps delivery bar did; P1 carries 2.0 index points of
slippage as a separate term. And P1's `CORRECTED_SPOT_COST` sets **brokerage to 0.0**, so real
₹20-per-order brokerage would add about **0.25 bps**, making the floor ≈5.91 bps and the bar ≈17.7
bps. The gate uses 16.9664 bps, which is the more demanding of the two.

## 2. The SIP date set — THE 10TH, AND NOTHING ELSE

Sourced from published SIP application forms, persisted under `data/sip_forms/` with their URLs in
`data/sip_form_dates.csv`, fetched 2026-09-22 by `src/fetch_sip_forms.py`:

| AMC | dates the form offers | default |
|---|---|---|
| SBI | 1, 5, 10, 15, 20, 25, 30 | **10th** |
| ICICI Prudential | 1, 7, 10, 15, 20, 25 | **10th** |
| Kotak Mahindra | 1, 7, 10, 14, 15, 21, 25, 28 | — |
| Aditya Birla Sun Life | 1, 7, 15, 20, 28 | — |
| HDFC | **every date, 1–31** | — |
| Nippon India | **any date**, free field | **10th** |
| Axis | **any date except 29/30/31** | — |

SBI and ICICI were each extracted from two independent hosts and agreed exactly, which is the check
that the extraction is reading the form rather than inventing a plausible list.

**THE DATE SET IS FIXED HERE AT {10}.** The 10th is the default at three of the five largest AMCs,
and defaults are sticky — an investor who does not choose is the modal investor.

**Why the wider sets were rejected, recorded because the reasoning generalises.** The instinct in
this project is to resolve an unknown in the direction generous to the hypothesis. **Here that
instinct inverts.** A wider date set does not protect against a false kill; it destroys the contrast
the test depends on:

- **Set A**, dates offered by at least three of the four AMCs with restricted lists — {1, 7, 10, 15,
  20, 25} — is six dates a month. With a D→D+2 window each date claims three sessions, so **about 18
  of roughly 21 trading days are "SIP days"** and the comparison group nearly vanishes.
- **Set B**, the union of every enumerated date, is worse still.

Inclusiveness is dilution here, not conservatism, and a test with almost no control group cannot
detect anything however large the effect.

**If the 10th is not a trading day, the event is the NEXT trading day.** Debits are presented on the
10th and settle on the following business day when the 10th is a holiday; moving forward, never
backward, also keeps the rule decidable from the calendar alone with no look-ahead.

## 3. Window — D through D+2

**Open of D to close of D+2, three sessions.** Consistent with Phase 2's convention of entering at
the open.

**The settlement reasoning.** A SIP instruction debits the investor's bank on D. The AMC receives
cleared funds on D or D+1, allots units at the applicable NAV, and places the corresponding market
orders over D and D+1. Indian cash equity settles **T+1**, so an order placed on D+1 settles on D+2
and any price pressure it creates can persist to that close. Three sessions therefore spans the
plausible deployment-and-settlement path. A shorter window risks truncating the effect; a longer one
buys unrelated variance and weakens power, which §5 quantifies rather than asserts.

## 4. Blinding

**The gate script measures only:**

1. the **standard deviation of NIFTY 500 returns over the window length** (open-to-close over three
   sessions), computed on **all days**, every day treated alike as a potential D;
2. the **serial correlation** of that overlapping three-session return series, at lags 1…L, again on
   all days.

**It never computes returns grouped by SIP versus non-SIP day**, never forms the SIP-day mean, the
other-day mean or their difference, and never computes a t-statistic or p-value on the real series.
Enforced the same way the Phase 2 gate was: an allow-list writer where an unlisted key raises.

The blinding is **procedural**, as it was in Phase 2 — the price series on disk obviously contains
the answer. Its integrity rests on this being the only script run against the series before the
pre-registration is locked.

## 5. Sample and power

**Sample: every month in `data/nifty500_daily_2015_2026.csv` falling in 2016–2026** — about 125
months, one event each. **Not** the 27-month AMFI SIP series: the gate needs the return series, which
runs the full period, and restricting to months with published SIP totals would throw away
three-quarters of the power for no gain.

**The estimator the power calculation must match** (STANDING_RULES.md rule 1) is the difference
between the SIP-day window return and the mean of the same month's other-day window returns,
averaged over months, with **standard errors clustered by month**. With one event per month the
month IS the cluster, so G = the number of months.

```
    d_m   = r_SIP,m  -  mean of the other-day window returns in month m
    MDE   = ( t(0.995, G-1) + t(0.80, G-1) ) * SD(d) / sqrt(G)
    SD(d)^2 = s3^2 * ( 1 + VIF / m_other )
```

- `s3` — SD of the three-session return over all days.
- `m_other` — other-day windows per month.
- `VIF = 1 + 2 * sum_k (1 - k/m_other) * rho_k` — the variance inflation of a mean of **overlapping**
  windows. Three-session windows on consecutive days share two days by construction, so rho_1 and
  rho_2 are large and mechanical. Ignoring this would understate the variance and overstate power.

**The covariance between the SIP-day window and the other-day windows is set to zero.** It is
positive in reality, so dropping it **overstates** `SD(d)` and therefore the MDE. Conservative, in
the direction that makes the gate harder to pass, and stated rather than hidden.

**PROCEED only if MDE ≤ 16.9664 bps. Otherwise Phase 3 closes as underpowered**, and that is a
result recorded in `TEST_REGISTRY.csv`.

**A synthetic dry run runs first**, on data with a planted SD and a known autocorrelation structure:
the estimator must recover both, the VIF must match its closed form, and an effect planted at the
computed MDE must be detected about 80% of the time. Any arm failing means the gate does not run.

## 6. Dose-response — DROPPED, and why

The intended pre-registration was: **if the main test is later run, the effect must be larger in the
top tercile of SIP-inflow years than in the bottom.** It is dropped, because the annual figures it
needs are not sourceable.

Searched 2026-09-22 across AMFI's machine-readable publications. **Exactly two fiscal years carry an
FY-tagged SIP figure** — the March-2025 Monthly Note gives an average monthly SIP contribution of
₹24,113 crore for FY 2024-25 and ₹16,602 crore for FY 2023-24. The March-2026 note carries none. The
monthly series itself begins only with the June-2024 note (`PRECHECK_SIP_TIMING.md` §4).

**Two fiscal years cannot form terciles over an eleven-year sample.** Running the check on the
27-month series instead is explicitly refused: it would cover 2024–2026 only, a period over which
SIP inflows barely vary, so the "low dose" tercile would not be low and the test would have no
power to fail. A dose-response test that cannot fail is not evidence.

**Consequence, stated plainly:** if the main test is later run and finds an effect, **there is no
pre-registered dose-response check standing behind it.** That is a real weakening of what a positive
result would mean, and it is recorded here rather than discovered later.

## 7. What would make this wrong

- **The 10th is a guess about where mass sits**, grounded in three defaults but not in debit data. No
  AMC publishes a debit-date histogram. If flow is more evenly spread, the true contrast is smaller
  than any power figure here implies.
- **Three of seven AMCs impose no date restriction**, so "other days" are contaminated by real SIP
  flow. That biases the measured difference **toward zero**, so a null is weaker evidence than it
  looks, while a positive result is not manufactured by it.
- **A detectable move is not a tradable edge.** The gate asks only whether an effect of 16.9664 bps
  could be seen. Direction, persistence and whether it survives slippage are separate questions this
  document does not address.
- **The bar excludes slippage**, and on a three-session futures position slippage is not negligible.
  A design that clears this bar has not been shown to clear a realistic one.

## 8. Standing rules

Per `STANDING_RULES.md` rule 1, the power calculation uses the planned test's own estimator, and its
nuisance inputs are measured blind from real data. Per rule 3 this document is not edited
retroactively; corrections go in a numbered addendum. Per rule 4 the verdict is recorded in
`TEST_REGISTRY.csv` whichever way it goes.
