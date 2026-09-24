# RESULTS — forced-flows

Every phase, its pre-registration, its gate, its verdict, and the one number that decided it.
The append-only ledger this is drawn from is [`TEST_REGISTRY.csv`](TEST_REGISTRY.csv).

**The line is closed.** Phases 1, 2 and 3 closed; 2b not pursued; Phase 4 not started.

---

## The phases

| # | candidate | pre-registration | gate | verdict | the deciding number |
|---|---|---|---|---|---|
| **1** | index reconstitution — buy additions from announcement to effective | `PRECHECK_INDEX_RECON.md` | — closed at the pre-check | `PRECHECK_KILLED` | n = **110** events; clustered MDE above 3× the delivery floor |
| **2** | F&O ban-list entry moves the cash price | `PRECHECK_BAN_LIST.md` → `PREREG_BAN_LIST_ENTRY.md` (**never locked**) | `GATE_BAN_LIST_NUISANCE.md` + Addenda 01, 02 | `GATE_CLOSED_UNDERPOWERED` | MDE **120.42 bps** vs a **71.35 bps** bar — **1.69×** |
| **2b** | ASM/GSM surveillance-list entry | — none written | — | `NOT_PURSUED` | no figure claimed; every binding factor worse than Phase 2 |
| **3** | SIP debits on the 10th move the index over D…D+2 | `PRECHECK_SIP_TIMING.md` | `GATE_SIP_TIMING.md` + Addendum 01 | `GATE_CLOSED_UNDERPOWERED` | MDE **53.20 bps** vs a **16.97 bps** bar — **3.14×** |
| **4** | — | — | — | not started | line closed under the stopping rule |

### Phase 1 — index reconstitution

Buying index additions between announcement and effective date. Closed at the arithmetic
pre-check: **110 events** is too few for the clustered MDE to come under 3× the cash-market
delivery floor. No data beyond the announcement archive was downloaded.

### Phase 2 — F&O ban-list entry

A stock entering the NSE F&O ban list cannot take new derivative positions, which forces
unwinding. **1,781 entries across 141 stocks, 2015–2026**, the entire archive.

The pre-check returned **PRECHECK_PASSED** at 42.44 bps against a 71.35 bps bar — and was wrong
twice over.

**First supersession, and its stated reason was also wrong.** The pre-check clustered on the event
date alone while the pre-registration named a two-way (week × stock) estimator as primary. The
superseding note blamed stock-level clustering: 1,781 entries sit in 141 stocks, one holding 75,
so Σc²ₛ = 53,887 against n = 1,781. That looked decisive. **Measured, ρ_stock came back at
−0.0029** — the stock dimension carried essentially none of the gap. Right conclusion, wrong
mechanism, corrected in `GATE_BAN_LIST_NUISANCE_ADDENDUM_02.md` §7.

**What actually closed it was volatility.** The pre-check assumed a 5% per-event CAR standard
deviation; the realised figure was **7.75%**. Restore only the 5% assumption, holding everything
else at its measured value, and the design clears at 56.77 bps.

```
    kept sample        1,568 events, 140 stocks, 483 ISO weeks
    rho_stock         -0.0029   (90% upper 0.0184)
    rho_week           0.1713   (90% upper 0.3159)
    SD_event           7.750%   (90% upper 9.527%)
    alpha*          0.009178, fresh-sample size 1.070% [0.892%, 1.272%]
    MDE              120.42 bps  vs bar 71.35 bps       CLOSE_UNDERPOWERED
    at point estimates throughout, 88.00 bps -- still fails by 23%
```

The verdict does not rest on the conservatism: strip the bounds entirely and it still fails.

### Phase 2b — ASM/GSM

Not pursued, recorded so the absence is a decision rather than an untried idea. The ban-list gate
closed on volatility and liquidity; ASM/GSM names are less liquid, more volatile and costlier to
trade, so every factor that bound Phase 2 is worse. **No test designed, no data fetched, no figure
claimed.**

### Phase 3 — SIP debit timing

Indian systematic investment plans debit on fixed monthly dates. The **10th** is the default at
three of the five largest asset managers, sourced from their published application forms.

The arithmetic pre-check did **not** close it — at maximum concentration the largest month implies
**123.23 bps** against a 71.35 bps delivery bar. But it recorded two load-bearing caveats: the
whole month deployed on one date, and a square-root impact law extrapolated an order of magnitude
beyond its calibrated range. **Spread over the roughly seven usual debit dates, the same month
gives ≈47 bps.**

The gate then measured what could be detected:

```
    2,643 three-session windows over 129 months, 2016-2026
    SD of the 3-session return   164.3 bps
    rho_1 +0.6143, rho_2 +0.2572   (mechanical -- consecutive windows share two days)
    VIF 2.6223  -- a 20-window monthly mean carries the information of 7.6
    MDE  53.20 bps  vs bar 16.97 bps       CLOSE_UNDERPOWERED
    in TRUE-EFFECT terms 59.12 bps, after 0.900 attenuation from window overlap
```

**The pre-check and the gate converge from opposite directions.** The ≈47 bps that survives
realistic concentration sits **below** the 53.20 bps detection floor. Clearing the bar would need
about **1,268 months — 106 years** of index history.

The pre-registered dose-response check was **dropped**: only two fiscal years carry an FY-tagged
SIP figure in AMFI's machine-readable publications, which cannot form terciles over eleven years.
Running it on the 27-month series was refused — SIP inflows barely vary over 2024–2026, so the low
tercile would not be low and the test could not fail.

---

## The standing rules, and what each was learned from

From [`STANDING_RULES.md`](STANDING_RULES.md). Each was written after something went wrong.

### 1. A pre-check must use the planned test's own estimator, and measure its nuisance parameters

> A pre-check's power calculation must use the planned test's own estimator, and nuisance
> parameters must be measured blind from real data where the data is cheap, before a
> `PRECHECK_PASSED` verdict.

**Learned from Phase 2.** The pre-check passed at 42.44 bps using a date-clustered estimator and an
*assumed* 5% SD, while the pre-registration named a two-way estimator. Measured, the SD was 7.75%
and the MDE 120.42 bps — a fail by 1.69×, on a design already recorded as passed. Both halves of
the rule failed independently, and the data that would have caught it was one afternoon of
throttled downloading.

*"Where the data is cheap" is not an escape hatch: if a public archive and a rate-limited fetcher
would settle it, measure it.*

### 2. Do not assert a mechanism before measuring it

**Learned three times in Phase 2.** The supersession blamed stock clustering; ρ_stock measured
−0.0029. `PREVCLOSE` was expected to repair corporate-action discontinuities; it does not — BHEL's
1:2 bonus and CANBK's split both showed ratio 1.0000, leaving −33.69% and −79.00% artefacts. A
percentile bootstrap was expected to deliver 90% coverage; it delivered 74.0%.

**A conclusion that is right for the wrong reason will mislead the next decision that leans on the
reason rather than the conclusion.**

### 3. Corrections go in a numbered addendum; the original row stands

No pre-registration, gate or registry row is edited retroactively. `TEST_REGISTRY.csv` is appended
to, never rewritten — the superseded `PRECHECK_PASSED` row keeps its place as the record of what
was believed then.

**Learned from the discipline working:** it is the only reason the Phase 2 supersession's *own*
error could be found and corrected in Addendum 02 rather than quietly overwritten.

### 4. A closed phase is a result

Recorded with its verdict and reason at the same evidential standard as one that proceeds.
"Underpowered" is not "awaiting more data" when the sample is the whole archive, and it is not "no
effect" either — it is a statement about detectability. A design **not pursued** is recorded too,
with no figures claimed.

**Learned from Phase 2b**, which would otherwise have looked open forever.

### 5. A figure inherits every condition its script attached to it

> A figure quoted from a script inherits every condition the script attaches to it. Dropping the
> caveat at quote time is a defect.

**Learned from P1, three times over, and it applies here too.** P1's closure reported an audit
column that answered *"which bar is harder"* as though it answered *"which bar fired"*; its paper
carried a different file's row count as the spot bar count. In this line, Phase 3's **53.20 bps**
MDE holds only against a comparison group that overlaps the event window — an overlap that
attenuates a true effect to **0.900** of itself. Quoted bare, the gate reads 10% more sensitive
than it is.

Name the script and run beside the number, and carry the one condition that would change its
meaning if dropped.

---

## Errors caught, and what caught them

Recorded because the apparatus is the output.

| error | direction | what caught it |
|---|---|---|
| Phase 2 pre-check assumed 5% SD; realised 7.75% | flattered the design | the blinded nuisance gate |
| supersession blamed stock clustering; ρ_stock ≈ 0 | right conclusion, wrong mechanism | measuring it |
| `PREVCLOSE` assumed corporate-action adjusted; it is not | would have injected −79% returns | checking two known ex-dates |
| percentile bootstrap assumed 90% coverage; 74.0% | flattered the design | a coverage arm that measured it |
| AMFI corporate-action API returns nothing for renamed tickers | silent — no ex-dates means nothing excluded | 11 of 141 symbols coming back empty |
| SIP parser scavenged month headers from prose; read `5.3%` as a monthly inflow | wrong numbers that looked right | an overlap assertion across AMFI notes |
| overlapping comparison windows absorb 10% of any real effect | flattered the design | planting the effect in daily returns instead of in the difference |

Five of seven ran in the direction that made a design look better than it was.
