r"""
calibrate_interval_method.py -- choose the interval method for the gate's
nuisance bounds, BY SIMULATED COVERAGE and nothing else.

=== WHY THIS EXISTS ===

GATE_BAN_LIST_NUISANCE.md §3 specified a one-sided 90% upper bound from a
percentile cluster bootstrap, and §2 required its coverage to be MEASURED
rather than assumed. It was measured, on 2026-09-22, and it FAILED: 84.0%
coverage for rho_stock and 86.7% for SD against a required 90%.

Diagnosed before anything was changed, and it is not an implementation bug.
It was first measured on a BALANCED 60x8 panel, where the shortfall split
evenly between a downward bias and an under-stated spread. Re-measured on the
OBSERVED structure -- 141 stocks, one holding 75 entries, 66 holding three or
fewer -- the split is quite different, and the observed structure is the one
that matters:

    rho_s  rho_w    bias      in SD units   boot SD / true SD
     0.15   0.15   -0.00611      -0.15           0.817
     0.25   0.15   -0.00913      -0.15           0.806
     0.35   0.25   -0.01430      -0.19           0.813

THE DOMINANT DEFECT IS SPREAD, NOT CENTRING. The whole-stock bootstrap
under-states the sampling SD of rho_stock_hat by about 19% once the blocks are
as unbalanced as they really are. The bias is real but small, and is closely
predicted by the closed form E[r_i r_j] = C_ij - (R_i + R_j)/n + S/n^2
(predicted -0.0071 at rho_s 0.25 against -0.0091 measured).

That diagnosis is what makes a CALIBRATED PERCENTILE the right family rather
than a fudge: it compensates a scale deficiency, it does not paper over a
mis-centred estimator. Had the failure been mostly bias, the honest fix would
have been de-biasing or BCa -- and BCa is measured here for exactly that
reason, rather than dismissed.

The direction matters and is stated plainly: an under-covering upper bound is
TOO LOW, so it under-states rho_stock and SD, so it makes the MDE look SMALLER
than it is, so it makes Phase 2 look BETTER powered than it is. The original
method was failing in the direction that flatters the design.

=== THE CANDIDATES, AND A NAMING TRAP ===

    whole-stock resampling      the ORIGINAL method: resample stocks with
                                replacement, read the 0.90 percentile. This is
                                the SAME THING as "percentile 0.900" in the
                                table below -- every candidate here resamples
                                whole stocks, because the stock is the cluster.
                                It is listed under both names so nobody reads
                                the table and thinks a candidate was skipped.
    calibrated percentile       same estimator, same draws, one constant
                                changed: the percentile q* found by search.
    BCa                         bias-correction and acceleration, with a
                                delete-one-STOCK jackknife. A different and
                                heavier method.

=== THE SELECTION RULE, FIXED BEFORE THE RUN ===

    Choose the SMALLEST q such that, on BOTH rho_stock and SD_event, every
    grid cell's measured coverage has a ONE-SIDED 95% CLOPPER-PEARSON LOWER
    BOUND of at least 90%, at 500 trials per cell. Then re-validate that q on
    a FRESH seed under the identical criterion. If no q <= 0.999 satisfies it,
    STOP AND REPORT -- do not extend the grid to find one.

WHY A LOWER BOUND AND NOT THE POINT ESTIMATE. The earlier rule -- "worst cell
>= 90%" on a point estimate -- is not the test it appears to be. The worst of
nine noisy estimates is biased DOWNWARD: at 500 trials the binomial SE is
about 1.3pp, so even a method that is EXACTLY 90% everywhere would show a
worst cell near 88% most of the time and be rejected. The mirror failure is
worse: a method truly at 88% can show 90.0% in all nine cells by luck and be
accepted. Requiring a 95% lower bound to clear 90% removes the second failure,
which is the one that would let an under-covering bound into the gate.

At n = 500 this needs roughly 92% observed coverage, not 90%.

  1. Candidates are judged ONLY by simulated coverage on the observed
     structure, across the rho grid. Not by elegance, not by convention.
  2. Ascending q = least adjustment first; the first q that clears wins.
  3. Every candidate is scored on THE SAME panels and THE SAME bootstrap
     draws, so the ranking carries no noise between candidates.
  4. The winner is re-verified on a FRESH seed. A method chosen on a sample
     and validated on that sample has proved nothing.

=== CRASH SAFETY ===

The first attempt lost 18 minutes of completed work to a machine crash because
results were only printed at the end. Each grid cell now:

  * draws from a seed that is a pure function of (phase, rho_s, rho_w), so a
    resumed cell is bit-identical to the one that was lost;
  * is written to results/interval_cov/ as soon as it finishes;
  * is SKIPPED on restart if its file is already there.

Delete that directory to force a clean re-run.

NO REAL DATA IS TOUCHED. Every number here comes from synthetic panels with
planted components. The blind of GATE_BAN_LIST_NUISANCE.md §1 holds: at the
time this runs, no CAR, mean or test statistic has been computed on a real
ban-list event.

=== WHAT WOULD MAKE THIS WRONG ===

  COVERAGE IS MEASURED AT PLANTED GAUSSIAN COMPONENTS. Real CARs have fatter
  tails, which widens the true sampling distribution and would push coverage
  DOWN. A calibrated percentile is a correction fitted to this generating
  model, not a distribution-free guarantee.

  THE CALIBRATION IS A CONSTANT, NOT A THEORY. It repairs the measured
  shortfall at these cells and carries no claim beyond them, which is why the
  gate's "realised values must land inside the grid" rule still applies.

  q* IS READ FROM A BOOTSTRAP OF B DRAWS. A far-tail quantile of too few draws
  is mostly noise, so B here MUST equal the gate's own N_BOOT. It does, and
  ARM 3 fails the run if it ever stops matching. B was raised from 2,000 to
  5,000 precisely because the selected q sits far enough into the tail that
  2,000 draws did not resolve it: at q = 0.997, B = 2,000 reads the 6th
  largest draw, B = 5,000 the 15th.

Run:  python src/calibrate_interval_method.py
      python src/calibrate_interval_method.py --arms    (validation only)
"""
from __future__ import annotations

import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Final

import numpy as np
from scipy import stats as _st  # type: ignore[import-untyped]

from event_study import (N_ENTRIES_OBSERVED, N_WEEKS_OBSERVED,
                         STOCK_ENTRY_COUNTS)
from require_data import guard
from gate_ban_list_nuisance import (N_BOOT, _pair_cov, synth_observed,
                                    variance_components)

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CKPT: Final[Path] = ROOT / "results" / "interval_cov"

RHO_STOCK_GRID: Final[tuple[float, ...]] = (0.15, 0.25, 0.35)
RHO_WEEK_GRID: Final[tuple[float, ...]] = (0.10, 0.15, 0.25)
SD_TRUE: Final[float] = 0.05
TRIALS: Final[int] = 500
B: Final[int] = N_BOOT               # MUST equal the gate's own N_BOOT
TARGET_COV: Final[float] = 0.90
CANDIDATE_Q: Final[tuple[float, ...]] = (
    0.90, 0.95, 0.975, 0.99, 0.992, 0.994, 0.995, 0.996, 0.997, 0.998, 0.999)
BASE_SEED: Final[int] = 20260922

_STOCK_IDX: Final[np.ndarray] = np.repeat(
    np.arange(len(STOCK_ENTRY_COUNTS)),
    np.asarray(STOCK_ENTRY_COUNTS)).astype(np.int64)
_SIZES: Final[np.ndarray] = np.asarray(STOCK_ENTRY_COUNTS, dtype=np.float64)
_NS: Final[int] = len(STOCK_ENTRY_COUNTS)


def cell_seed(phase: int, rho_s: float, rho_w: float) -> int:
    """A seed that is a pure function of (phase, cell). A cell recomputed
    after a crash is then bit-identical to the one that was lost, which is
    what makes resuming honest rather than merely convenient."""
    return (BASE_SEED + phase * 1_000_000
            + int(round(rho_s * 1000)) * 1000 + int(round(rho_w * 1000)))


# =====================================================================
# The bootstrap, in block-summary form.
#
# A whole-stock resample never needs the resampled RESIDUALS -- only each
# drawn block's total, sum of squares and size. Writing it that way turns
# B x 141 array-builds into a handful of vectorised sums and is what makes a
# 500-trial x 2,000-resample cell run in seconds instead of five minutes.
#
# It is an OPTIMISATION, NOT A DIFFERENT METHOD, and ARM 1 proves that by
# feeding the same draws to both and requiring agreement to 1e-12.
# =====================================================================

def _block_stats(resid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(per-stock total, per-stock sum of squares)."""
    t = np.bincount(_STOCK_IDX, weights=resid, minlength=_NS)
    ss = np.bincount(_STOCK_IDX, weights=resid * resid, minlength=_NS)
    return t, ss


def draw_picks(rng: np.random.Generator, b: int) -> np.ndarray:
    """b whole-stock resamples, one row each, stocks drawn with replacement."""
    return np.asarray(rng.integers(0, _NS, size=(b, _NS)), dtype=np.int64)


def boot_from_picks(t: np.ndarray, ss: np.ndarray, picks: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray]:
    """(rho_stock, sd) for each resample, from block summaries alone.

    Each DRAWN block is its own cluster, so a stock drawn twice contributes two
    separate clusters -- the same relabelling the reference loop does."""
    tp = t[picks]
    sp = ss[picks]
    cp = _SIZES[picks]
    n_b = cp.sum(axis=1)
    sum_sq = sp.sum(axis=1)
    num = (tp * tp - sp).sum(axis=1)
    den = (cp * (cp - 1.0)).sum(axis=1)
    s2 = sum_sq / (n_b - 1.0)
    ok = (s2 > 0.0) & (den > 0.0)
    rho = np.where(ok, np.divide(num, np.where(den > 0, den, 1.0)) /
                   np.where(s2 > 0, s2, 1.0), 0.0)
    sd = np.where(s2 > 0.0, np.sqrt(np.maximum(s2, 0.0)), 0.0)
    return np.asarray(rho, dtype=float), np.asarray(sd, dtype=float)


def _boot_ref(resid: np.ndarray, picks: np.ndarray
              ) -> tuple[np.ndarray, np.ndarray]:
    """REFERENCE implementation: materialise each resample and reuse the
    gate's own `_pair_cov`. Slow, and kept only so ARM 1 has something
    independent to check the fast path against."""
    sizes = _SIZES.astype(np.int64)
    blocks = [np.flatnonzero(_STOCK_IDX == s) for s in range(_NS)]
    rho = np.empty(picks.shape[0], dtype=float)
    sd = np.empty(picks.shape[0], dtype=float)
    for b in range(picks.shape[0]):
        pick = picks[b]
        idx = np.concatenate([blocks[p] for p in pick])
        lab = np.repeat(np.arange(_NS, dtype=np.int64), sizes[pick])
        r = resid[idx]
        s2 = float(np.dot(r, r)) / float(r.size - 1)
        sd[b] = math.sqrt(s2) if s2 > 0.0 else 0.0
        rho[b] = (_pair_cov(r, lab, _NS) / s2) if s2 > 0.0 else 0.0
    return rho, sd


def jackknife(t: np.ndarray, ss: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Delete-one-STOCK jackknife of (rho_stock, sd), for BCa's acceleration.
    The deleted unit is the cluster, matching the bootstrap's resampling
    unit."""
    n = float(_SIZES.sum())
    tot_sq = float(ss.sum())
    tot_num = float((t * t - ss).sum())
    tot_den = float((_SIZES * (_SIZES - 1.0)).sum())
    n_j = n - _SIZES
    sq_j = tot_sq - ss
    num_j = tot_num - (t * t - ss)
    den_j = tot_den - _SIZES * (_SIZES - 1.0)
    s2 = sq_j / (n_j - 1.0)
    rho = np.where((s2 > 0) & (den_j > 0),
                   (num_j / np.where(den_j > 0, den_j, 1.0))
                   / np.where(s2 > 0, s2, 1.0), 0.0)
    return (np.asarray(rho, dtype=float),
            np.asarray(np.sqrt(np.maximum(s2, 0.0)), dtype=float))


def cp_lower(k: int, n: int, conf: float = 0.95) -> float:
    """One-sided Clopper-Pearson LOWER bound on a proportion.

    Exact, not normal-approximate: at a coverage of ~0.93 on 500 trials the
    normal approximation is already visibly wrong in the tail, and this number
    decides whether a method enters the gate."""
    if k <= 0:
        return 0.0
    if k >= n:
        return float((1.0 - conf) ** (1.0 / n))
    return float(_st.beta.ppf(1.0 - conf, k, n - k + 1))


def bca_upper(boot: np.ndarray, point: float, jack: np.ndarray,
              level: float) -> float:
    """One-sided BCa upper bound.

        z0    = Phi^-1( #{boot < point} / B )        bias correction
        a     = sum(d^3) / (6 (sum d^2)^1.5),  d = mean(jack) - jack
        q     = Phi( z0 + (z0 + z_level) / (1 - a (z0 + z_level)) )
        bound = quantile(boot, q)

    z0 answers "is the bootstrap distribution centred off the estimate" -- the
    bias half of the diagnosed failure -- and `a` answers "does the
    estimator's variance move with its level"."""
    b = boot.size
    frac = min(max(float((boot < point).mean()), 1.0 / (2 * b)),
               1.0 - 1.0 / (2 * b))
    z0 = float(_st.norm.ppf(frac))
    d = float(np.mean(jack)) - jack
    s2 = float(np.sum(d * d))
    a = (float(np.sum(d ** 3)) / (6.0 * s2 ** 1.5)) if s2 > 0.0 else 0.0
    zl = float(_st.norm.ppf(level))
    denom = 1.0 - a * (z0 + zl)
    if abs(denom) < 1e-12:
        return float(np.quantile(boot, level))
    q = min(max(float(_st.norm.cdf(z0 + (z0 + zl) / denom)), 1.0 / b),
            1.0 - 1.0 / b)
    return float(np.quantile(boot, q))


LABELS: Final[tuple[str, ...]] = tuple(
    [f"percentile {q:.3f}" for q in CANDIDATE_Q] + ["BCa 0.90", "BCa 0.95"])


def coverage_cell(rho_s: float, rho_w: float, phase: int
                  ) -> dict[str, tuple[int, int]]:
    """COUNTS of covering trials for every candidate in one cell, on shared
    panels and shared bootstrap draws.

    Counts, not fractions: the selection rule needs an exact Clopper-Pearson
    bound, and that needs k and n rather than a rounded ratio."""
    rng = np.random.default_rng(cell_seed(phase, rho_s, rho_w))
    hits: dict[str, list[int]] = {k: [0, 0] for k in LABELS}
    for _ in range(TRIALS):
        cars, _stk, week = synth_observed(rng, rho_s, rho_w, SD_TRUE)
        resid = cars - cars.mean()
        pr, _, ps = variance_components(resid, _STOCK_IDX, week)
        t, ss = _block_stats(resid)
        br, bs = boot_from_picks(t, ss, draw_picks(rng, B))
        for q in CANDIDATE_Q:
            k = f"percentile {q:.3f}"
            hits[k][0] += int(float(np.quantile(br, q)) >= rho_s)
            hits[k][1] += int(float(np.quantile(bs, q)) >= SD_TRUE)
        jr, js = jackknife(t, ss)
        for lv in (0.90, 0.95):
            k = f"BCa {lv:.2f}"
            hits[k][0] += int(bca_upper(br, pr, jr, lv) >= rho_s)
            hits[k][1] += int(bca_upper(bs, ps, js, lv) >= SD_TRUE)
    return {k: (v[0], v[1]) for k, v in hits.items()}


def cached_cell(rho_s: float, rho_w: float, phase: int
                ) -> dict[str, tuple[int, int]]:
    """Run a cell, or return the checkpoint if it is already on disk."""
    CKPT.mkdir(parents=True, exist_ok=True)
    p = CKPT / f"p{phase}_rs{int(round(rho_s * 1000))}_rw{int(round(rho_w * 1000))}.json"
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if (raw.get("trials") == TRIALS and raw.get("B") == B
                and raw.get("fmt") == "counts"):
            print(f"    cell rho_s {rho_s:.2f} rho_w {rho_w:.2f}  "
                  f"[resumed from checkpoint]", flush=True)
            return {k: (int(v[0]), int(v[1])) for k, v in raw["cov"].items()}
        print(f"    cell rho_s {rho_s:.2f} rho_w {rho_w:.2f}  checkpoint is "
              f"for different settings, recomputing", flush=True)
    t0 = time.time()
    cov = coverage_cell(rho_s, rho_w, phase)
    p.write_text(json.dumps({
        "phase": phase, "rho_s": rho_s, "rho_w": rho_w, "trials": TRIALS,
        "B": B, "sd_true": SD_TRUE, "seed": cell_seed(phase, rho_s, rho_w),
        "fmt": "counts",
        "cov": {k: list(v) for k, v in cov.items()}}, indent=1),
        encoding="utf-8")
    print(f"    cell rho_s {rho_s:.2f} rho_w {rho_w:.2f} done "
          f"[{time.time() - t0:.0f}s] -> {p.name}", flush=True)
    return cov


# =====================================================================
# VALIDATION ARMS -- before any coverage number is believed
# =====================================================================

def arms() -> bool:
    ok = True
    print("\n  ARMS")
    rng = np.random.default_rng(7)
    cars, _stk, week = synth_observed(rng, 0.25, 0.15, SD_TRUE)
    resid = cars - cars.mean()
    t, ss = _block_stats(resid)

    # ARM 1: the fast bootstrap IS the reference bootstrap
    picks = draw_picks(rng, 300)
    fr, fs = boot_from_picks(t, ss, picks)
    rr, rs_ = _boot_ref(resid, picks)
    d = max(float(np.abs(fr - rr).max()), float(np.abs(fs - rs_).max()))
    a1 = d < 1e-12
    ok &= a1
    print(f"    1  block-summary bootstrap vs materialised reference, same "
          f"300 draws: max |diff| {d:.2e}  " + ("PASS" if a1 else "*** FAIL ***"))

    # ARM 2: the jackknife matches a brute-force delete-one
    jr, js = jackknife(t, ss)
    worst = 0.0
    for s in (0, 1, 70, 140):
        keep = _STOCK_IDX != s
        r2 = resid[keep]
        s2 = float(np.dot(r2, r2)) / float(r2.size - 1)
        ref_rho = _pair_cov(r2, _STOCK_IDX[keep], _NS) / s2
        worst = max(worst, abs(ref_rho - jr[s]), abs(math.sqrt(s2) - js[s]))
    a2 = worst < 1e-12
    ok &= a2
    print(f"    2  delete-one-stock jackknife vs brute force, 4 stocks: "
          f"max |diff| {worst:.2e}  " + ("PASS" if a2 else "*** FAIL ***"))

    # ARM 3: B must equal the gate's N_BOOT, or q* is not transferable
    a3 = B == N_BOOT
    ok &= a3
    print(f"    3  B ({B:,}) equals the gate's N_BOOT ({N_BOOT:,})  "
          + ("PASS" if a3 else "*** FAIL ***"))

    # ARM 4: the seed is a pure function of the cell
    a4 = (cell_seed(0, 0.25, 0.15) == cell_seed(0, 0.25, 0.15)
          and cell_seed(0, 0.25, 0.15) != cell_seed(1, 0.25, 0.15)
          and cell_seed(0, 0.25, 0.15) != cell_seed(0, 0.15, 0.25))
    ok &= a4
    print(f"    4  cell seeds are pure, phase-distinct and cell-distinct  "
          + ("PASS" if a4 else "*** FAIL ***"))

    # ARM 5: a resumed cell reproduces bit-identically
    c1 = coverage_cell(0.25, 0.15, 99)
    c2 = coverage_cell(0.25, 0.15, 99)
    a5 = c1 == c2
    ok &= a5
    print(f"    5  same cell run twice gives identical coverage  "
          + ("PASS" if a5 else "*** FAIL ***"))

    print(f"\n  ARMS: {'ALL PASS' if ok else '*** FAILED ***'}")
    return bool(ok)


def _table(title: str,
           table: dict[str, dict[tuple[float, float], tuple[int, int]]],
           cells: list[tuple[float, float]], ix: int) -> None:
    print(f"\n  COVERAGE OF THE ONE-SIDED 90% UPPER BOUND -- {title}")
    print("    " + f"{'method':<22}"
          + "".join(f"{f'{rs:.2f}/{rw:.2f}':>10}" for rs, rw in cells)
          + f"{'worst':>8}{'CP LB':>8}")
    print("    " + "-" * (22 + 10 * len(cells) + 16))
    for k in LABELS:
        ks = [table[k][c][ix] for c in cells]
        vals = [x / TRIALS for x in ks]
        worst = min(vals)
        lb = min(cp_lower(x, TRIALS) for x in ks)
        name = "percentile 0.900 *" if k == "percentile 0.900" else k
        print("    " + f"{name:<22}"
              + "".join(f"{v:>9.1%} " for v in vals)
              + f"{worst:>7.1%}{lb:>8.1%}"
              + ("  OK" if lb >= TARGET_COV else "  fails"))
    print(f"    CP LB = one-sided 95% Clopper-Pearson lower bound on the WORST "
          f"cell, n={TRIALS}. The rule is CP LB >= {TARGET_COV:.0%}.")
    print("    * = the ORIGINAL method, whole-stock resampling at the nominal "
          "level. Same thing.")


def main() -> int:
    print("=" * 84)
    print("  INTERVAL-METHOD CALIBRATION -- chosen by simulated coverage alone")
    print("=" * 84)
    print(f"\n  structure: {_NS} stocks, {N_ENTRIES_OBSERVED:,} entries "
          f"(observed counts, largest {max(STOCK_ENTRY_COUNTS)}), "
          f"{N_WEEKS_OBSERVED} weeks")
    print(f"  {TRIALS} trials/cell x {B:,} resamples, SD_true {SD_TRUE:.0%}, "
          f"target coverage {TARGET_COV:.0%}")
    print(f"  checkpoints: {CKPT}")
    print(f"  NO REAL DATA IS READ BY THIS SCRIPT.")

    if not arms():
        return 1
    if "--arms" in sys.argv:
        return 0

    cells = [(rs, rw) for rs in RHO_STOCK_GRID for rw in RHO_WEEK_GRID]

    print(f"\n  PHASE 0 -- selection grid")
    table: dict[str, dict[tuple[float, float], tuple[int, int]]] = {
        k: {} for k in LABELS}
    for rs, rw in cells:
        for k, v in cached_cell(rs, rw, 0).items():
            table[k][(rs, rw)] = v

    _table("rho_stock", table, cells, 0)
    _table("SD_event", table, cells, 1)

    print(f"\n  SELECTION -- smallest q whose WORST-CELL 95% CP lower bound "
          f"clears {TARGET_COV:.0%}, on BOTH parameters")
    winner = None
    for k in LABELS:
        lb_r = min(cp_lower(table[k][c][0], TRIALS) for c in cells)
        lb_s = min(cp_lower(table[k][c][1], TRIALS) for c in cells)
        lb = min(lb_r, lb_s)
        eligible = lb >= TARGET_COV
        mark = "ELIGIBLE" if eligible else "rejected"
        if eligible and winner is None:
            winner = k
            mark = "ELIGIBLE  <- smallest, chosen"
        print(f"    {k:<22} CP LB rho {lb_r:>6.1%}  SD {lb_s:>6.1%}  "
              f"-> {lb:>6.1%}   {mark}")
    if winner is None:
        print(f"\n  *** NO CANDIDATE UP TO q = {max(CANDIDATE_Q)} MEETS THE "
              f"RULE. ***")
        print(f"  *** The rule said STOP AND REPORT rather than extend the "
              f"grid, so nothing is chosen. ***")
        return 2

    print(f"\n  PHASE 1 -- FRESH-SEED VERIFICATION (independent streams)")
    fresh: dict[str, dict[tuple[float, float], tuple[int, int]]] = {
        k: {} for k in LABELS}
    for rs, rw in cells:
        for k, v in cached_cell(rs, rw, 1).items():
            fresh[k][(rs, rw)] = v
    _table(f"rho_stock  [FRESH SEED]", fresh, cells, 0)
    _table(f"SD_event   [FRESH SEED]", fresh, cells, 1)

    lb_r = min(cp_lower(fresh[winner][c][0], TRIALS) for c in cells)
    lb_s = min(cp_lower(fresh[winner][c][1], TRIALS) for c in cells)
    worst_r = min(fresh[winner][c][0] for c in cells) / TRIALS
    worst_s = min(fresh[winner][c][1] for c in cells) / TRIALS
    good = min(lb_r, lb_s) >= TARGET_COV
    print(f"\n  '{winner}' ON THE FRESH SEED, same criterion:")
    print(f"    rho_stock  worst cell {worst_r:.1%}   95% CP LB {lb_r:.1%}")
    print(f"    SD_event   worst cell {worst_s:.1%}   95% CP LB {lb_s:.1%}")
    print("    " + ("CONFIRMED" if good else "*** NOT CONFIRMED ***"))
    print("\n" + "=" * 84)
    print(f"  CANDIDATE: {winner}   B = {B:,}   fresh-seed CP LB "
          f"{min(lb_r, lb_s):.1%}" if good else
          f"  {winner} FAILED fresh-seed verification -- nothing is adopted")
    print("  Nothing is adopted by this script. The choice is reported for review.")
    print("=" * 84)
    return 0 if good else 3


if __name__ == "__main__":
    raise SystemExit(guard(main))
