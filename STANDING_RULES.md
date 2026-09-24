# STANDING RULES — forced-flows

Rules that outlive any one phase. Each was written after something went wrong, and each names what
went wrong, so it can be argued with rather than merely obeyed.

---

## 1. A pre-check must use the planned test's own estimator, and measure its nuisance parameters

> **A pre-check's power calculation must use the planned test's own estimator, and nuisance
> parameters must be measured blind from real data where the data is cheap, before a
> `PRECHECK_PASSED` verdict.**

**Why.** Phase 2's pre-check returned `PRECHECK_PASSED` at `1031c76` with an MDE of 42.44 bps
against a 71.35 bps bar. It computed that number with a **date-clustered** estimator and an
**assumed** 5% per-event SD, while the pre-registration named a **two-way week × stock** estimator
as primary. When the gate finally measured both on real data, the realised SD was **7.75%** and the
MDE was **120.42 bps** — a fail by 1.69×, on a design already recorded as passed.

Both halves of the rule are load-bearing, and Phase 2 failed each in turn:

- **The estimator.** A power figure computed with an estimator the test will not use is not a power
  figure for that test. Date-clustering treated 1,781 entries as ~1,203 near-independent draws;
  the planned estimator does not.
- **The nuisance parameters.** The volatility assumption was never checked, and it was the thing
  that actually closed the phase. The data that would have checked it cost one afternoon of
  throttled downloading — cheap, by any standard, against a phase that ran to two documents, two
  addenda and six scripts before the assumption was tested.

**"Where the data is cheap" is the operative qualifier**, and it is not an escape hatch. It means:
if measuring a nuisance parameter needs data you would have to buy, negotiate for, or spend weeks
assembling, an assumption is legitimate provided the pre-check states it, grids it, and says which
cells clear. If the data is a public archive and a rate-limited fetcher, **measure it**.

**And measure it blind.** Phase 2's gate estimated ρ_stock, ρ_week and SD from mean-removed CARs
behind an allow-list writer that made the mean, the t-statistic and the p-value unreachable by
construction. That is what let the power question be settled honestly after the data was in hand,
instead of becoming a negotiation with a result already glimpsed.

## 2. Do not assert a mechanism before measuring it

**Why.** Twice in Phase 2 a cause was named before it was measured, and both times the conclusion
survived while the mechanism did not.

The pre-check was superseded on the stated grounds that "power depends on unmeasured ρ_stock", with
the stock dimension named as the culprit — Σc_s² = 53,887 against n = 1,781 looked decisive.
Measured, **ρ_stock came back at −0.0029**: the stock dimension carried essentially none of the gap.
The supersession was right; its reasoning was wrong. See `GATE_BAN_LIST_NUISANCE_ADDENDUM_02.md` §7.

Earlier in the same phase, `PREVCLOSE` was expected to repair the corporate-action discontinuity it
demonstrably does not repair, and a percentile bootstrap was expected to deliver 90% coverage when
it delivers 74%. In both cases the check was run, and in both cases the expectation was refuted.

**A conclusion that is right for the wrong reason will mislead the next decision that leans on the
reason rather than the conclusion.** Where a mechanism is cheap to measure, measure it; where it is
not, label it as a conjecture in the document that uses it.

## 3. Corrections go in a numbered addendum; the original row stands

A pre-registration, gate or registry row is **never edited retroactively**. New information goes in
the next numbered addendum, and the original stands as the record of what was believed at the time.
`TEST_REGISTRY.csv` is **appended to, never rewritten** — a superseded verdict keeps its row.

## 4. A closed phase is a result

A phase that closes is recorded in `TEST_REGISTRY.csv` with its verdict and its reason, at the same
standard of evidence as one that proceeds. "Underpowered" is not "awaiting more data" when the
sample is already the whole archive, and it is not "no effect" either — it is a statement about
detectability, and it is written as one.

A design that is **not pursued** is also recorded, with the reason and with no figures claimed
(Phase 2b, ASM/GSM). An untried idea that leaves no trace looks open forever.

## 5. A figure inherits every condition its script attached to it

> **A figure quoted from a script inherits every condition the script attaches to it. Dropping the
> caveat at quote time is a defect.**

**Why.** A script that prints `MDE 53.20 bps` prints it *under* a stated estimator, a stated
window, a stated comparison group and a stated set of assumptions. The number is not portable away
from them. Quoting it bare is not shorthand — it is a different claim.

Three instances, all found late:

- P1's closure said *"13 of 17 were decided by the `sharpe_like` gate"*. The 13 came from an audit
  column reporting **which bar is harder**, not **which bar fired**. Carried across a sentence
  boundary, one question's answer became another's. The engine's verdict function contains no
  p-value at all, so the count for the question actually asked was **17 of 17**.
- P1's paper carried `~2.8M bars` for the 1-minute spot series. That is the row count of a
  **different file** — the 2019–2023 F&O bhavcopy, at exactly 2,862,008 rows — quoted into a row it
  did not describe. The arithmetic gave it away: ~375 minutes a session over that span is ~1.09M.
- Phase 3's gate MDE of **53.20 bps** holds only "against a comparison group that overlaps the
  event window", and that overlap attenuates a true effect to 0.900 of itself. Quoted bare, the
  gate looks 10% more sensitive than it is.

**How to apply it.** When a figure moves from a run into prose, its conditions move with it or the
figure does not go. In practice: name the script and the run beside the number, and carry the one
condition that would change its meaning if dropped. Where one number has two meanings in a
document — `6.16` as both a cost floor and a best edge, `15.52` as both a breakeven bar and a
futures-comparison floor — **label both**, because a reader greping for it finds both.

**This rule is numbered 5 rather than inserted earlier deliberately.** Rules 1–4 are referenced by
number from `GATE_SIP_TIMING.md` and `RESULTS.md`, both committed; renumbering them would silently
repoint those citations, which is the same defect class this rule describes.
