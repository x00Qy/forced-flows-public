r"""
calibrate_two_way_alpha.py -- find the NOMINAL two-way p-threshold that buys a
TRUE 1% rejection rate on the observed ban-entry structure.

=== WHY THIS EXISTS ===

ARM 6b of `event_study.py` measured that a nominal p < 0.01 on the two-way
(week x stock) clustered estimator rejects a true null about 2% of the time on
the REAL structure -- 141 stocks with the observed entry counts, 1,781 entries,
499 weeks. Cluster-robust inference over-rejects when clusters are few and
unbalanced, and one stock here carries 75 of 1,781 entries.

Recording that distortion in the pre-registration is not the same as removing
it. This script removes it: it finds alpha* such that the REALISED size is 1%,
and it does so over a GRID of residual correlations, not at one guessed cell,
because the true correlations are unknown until the real test runs.

=== THE CALIBRATION ===

  1. For each (rho_stock, rho_week) on a 3x3 grid, simulate N_CAL zero-effect
     panels on the observed structure and collect the two-way p-value of each.
  2. The nominal threshold giving a TARGET (1.0%) rejection rate in that cell
     is the k-th smallest p-value, k = round(TARGET * N_CAL). That is the
     empirical TARGET-quantile of the null p-distribution.
  3. alpha* = the SMALLEST such threshold over the grid -- the most demanding
     cell wins, so the bar is conservative anywhere inside the grid.
  4. A FRESH sample at the middle cell then measures the realised size at
     alpha*, with a 99% Clopper-Pearson band. Re-using the calibration sample
     would report the quantile back to itself and prove nothing.

=== WHAT WOULD MAKE THIS WRONG ===

  THE GRID IS AN ASSUMPTION. alpha* is calibrated to be valid INSIDE
  rho_stock in {0.15, 0.25, 0.35} x rho_week in {0.10, 0.15, 0.25}. If the
  realised residual correlations of the real data fall outside it, alpha* is
  not known to deliver 1% and the result must be reported as possibly
  mis-sized. That rule is pre-registered, not left to judgement afterwards.

  NORMALITY. The panel is Gaussian. Real CARs have fat tails, which typically
  makes cluster-robust over-rejection WORSE, so alpha* is if anything
  optimistic. It is not a bootstrap and does not claim to be one.

  THE WEEK ASSIGNMENT IS RANDOM, drawn uniformly over the 499 observed weeks
  rather than taken from the real entry dates. Real entries bunch (many names
  enter together in a stressed week), which again would worsen, not improve,
  the distortion.

  alpha* IS A NOMINAL NUMBER FOR ONE ESTIMATOR on one structure. It is not a
  p-value correction of general validity and must not be carried to any other
  test.

Run:  python src/calibrate_two_way_alpha.py            (dry run + calibration)
      python src/calibrate_two_way_alpha.py --dry-run  (validation arms only)
"""
from __future__ import annotations

import math
import sys
import time
from typing import Final

import numpy as np
from scipy import stats as _st  # type: ignore[import-untyped]

from require_data import guard
from event_study import (STOCK_ENTRY_COUNTS, N_ENTRIES_OBSERVED,
                         N_STOCKS_OBSERVED, N_WEEKS_OBSERVED, EventWindow,
                         _ban_like_panel, _cluster_var, _t_ppf,
                         _two_sided_t_p, mean_car_two_way)

# ---------------------------------------------------------------------
# Calibration constants -- fixed here, before any number is produced.
# ---------------------------------------------------------------------
TARGET: Final[float] = 0.01          # the TRUE size we want alpha* to buy
N_CAL: Final[int] = 5_000            # sims per grid cell
N_VAL: Final[int] = 5_000            # fresh sims for the validation
RHO_STOCK_GRID: Final[tuple[float, ...]] = (0.15, 0.25, 0.35)
RHO_WEEK_GRID: Final[tuple[float, ...]] = (0.10, 0.15, 0.25)
MIDDLE: Final[tuple[float, float]] = (0.25, 0.15)
CAL_SEED: Final[int] = 20260922
VAL_SEED: Final[int] = 20260922_999  # a DIFFERENT stream, not a continuation

# The Phase 2 viability bar and SD assumption, carried over unchanged from
# PRECHECK_BAN_LIST.md so the power statement is comparable to the pre-check's.
SD_EVENT: Final[float] = 0.05        # 5% per-event SD of CAR, the middle cell
BAR_BPS: Final[float] = 71.35        # 3 x 23.7821 bps delivery floor, today
POWER: Final[float] = 0.80

_STOCK_IDX: Final[np.ndarray] = np.repeat(
    np.arange(len(STOCK_ENTRY_COUNTS)), np.asarray(STOCK_ENTRY_COUNTS))


# =====================================================================
# Vectorised twins of the event_study.py primitives.
#
# These exist ONLY for speed -- 50,000 panels through the pure-Python dict
# loop is hours, not minutes. ARMs 1 and 2 check the fast variance and the
# fast p-value against `_cluster_var` and `mean_car_two_way` to 1e-15, ARM 3
# checks the fast panel's covariance structure, and ARM 4 runs the fast twin
# and `_ban_like_panel` through the SAME estimator and compares the measured
# size. A faster twin that was never checked against the original is how a
# silent estimator swap happens.
# =====================================================================

def _cluster_var_fast(resid: np.ndarray, codes: np.ndarray, n_groups: int
                      ) -> float:
    """(1/n^2) * sum_g (sum_{i in g} e_i)^2, with integer group codes."""
    tot = np.bincount(codes, weights=resid, minlength=n_groups)
    return float(np.dot(tot, tot)) / float(resid.size * resid.size)


def _two_way_p_fast(cars: np.ndarray, stock: np.ndarray, week: np.ndarray
                    ) -> tuple[float, float, int]:
    """(p, se, df) of the mean, two-way clustered, Cameron-Gelbach-Miller.

    Identical arithmetic to `mean_car_two_way`, including the non-positive
    variance fallback and df = min(G_A, G_B) - 1."""
    n = cars.size
    resid = cars - cars.mean()
    cell = stock.astype(np.int64) * N_WEEKS_OBSERVED + week
    v_a = _cluster_var_fast(resid, week, N_WEEKS_OBSERVED)
    v_b = _cluster_var_fast(resid, stock, N_STOCKS_OBSERVED)
    v_ab = _cluster_var_fast(resid, cell, N_STOCKS_OBSERVED * N_WEEKS_OBSERVED)
    v = v_a + v_b - v_ab
    if v <= 0.0:
        v = max(v_a, v_b)
    g_a = int(np.unique(week).size)
    g_b = int(np.unique(stock).size)
    df = min(g_a, g_b) - 1
    se = math.sqrt(v)
    t = float(cars.mean()) / se if se > 0.0 else float("nan")
    return _two_sided_t_p(t, float(df)), se, df


def analytic_sd_of_mean(rho_stock: float, rho_week: float) -> float:
    """TRUE SD of the mean CAR under the panel's own generating model.

        Var(mean) = [ n + rho_s * (sum_s c_s^2 - n) + rho_w * (sum_w m_w^2 - n) ]
                    / n^2

    Every same-stock pair contributes rho_stock to the double sum and every
    same-week pair rho_week; the n diagonal terms contribute the unit marginal
    variance. `sum_w m_w^2` is the expectation for n entries drawn uniformly
    over W weeks, which is what `_fast_panel` actually draws.

    This is the number the two-way estimator is TRYING to estimate, so ARM 7
    can say whether the simulated standard error is RIGHT rather than merely
    self-consistent."""
    c = np.asarray(STOCK_ENTRY_COUNTS, dtype=float)
    n = float(N_ENTRIES_OBSERVED)
    w = float(N_WEEKS_OBSERVED)
    sum_c2 = float((c * c).sum())
    lam = n / w
    sum_m2 = w * (lam + lam * lam * (1.0 - 1.0 / w))
    var = (n + rho_stock * (sum_c2 - n) + rho_week * (sum_m2 - n)) / (n * n)
    return math.sqrt(var)


def _fast_panel(rng: np.random.Generator, rho_stock: float, rho_week: float,
                planted: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised twin of `_ban_like_panel`. Same construction, same marginal
    variance of 1, same observed stock counts; the week of each entry is drawn
    uniformly over the 499 observed weeks exactly as in the original."""
    u = rng.standard_normal(len(STOCK_ENTRY_COUNTS))
    v = rng.standard_normal(N_WEEKS_OBSERVED)
    week = rng.integers(0, N_WEEKS_OBSERVED, N_ENTRIES_OBSERVED)
    e = rng.standard_normal(N_ENTRIES_OBSERVED)
    idio = math.sqrt(max(0.0, 1.0 - rho_stock - rho_week))
    cars = (math.sqrt(rho_stock) * u[_STOCK_IDX]
            + math.sqrt(rho_week) * v[week]
            + idio * e + planted)
    return cars, _STOCK_IDX, week


# =====================================================================
# DRY RUN -- the twins, and the threshold rule, on data with a known answer
# =====================================================================

def dry_run() -> bool:
    """Validation arms. Nothing downstream runs unless every arm passes."""
    ok = True
    print("\n  DRY RUN -- validating the fast twins and the threshold rule")

    # --- ARM 1: the fast cluster variance vs the original ---------------
    rng = np.random.default_rng(1)
    for trial in range(5):
        r = rng.normal(0.0, 1.0, 400)
        codes = rng.integers(0, 17, 400)
        a = _cluster_var(r, [int(c) for c in codes])
        b = _cluster_var_fast(r, codes, 17)
        d = abs(a - b)
        if d > 1e-18:
            ok = False
        if trial == 0:
            print(f"    1  fast cluster variance vs _cluster_var")
            print(f"       original {a:.18f}")
            print(f"       fast     {b:.18f}")
    print(f"       5 trials, agree to 1e-18 -- the only difference possible is")
    print(f"       floating-point reassociation, not a different estimator  "
          f"{'PASS' if ok else '*** FAIL ***'}")

    # --- ARM 2: the fast p-value is EXACT against mean_car_two_way -------
    rng2 = np.random.default_rng(2)
    w = EventWindow(0, 0)
    worst = 0.0
    for _ in range(5):
        cars, st, wk = _fast_panel(rng2, 0.25, 0.15, 0.0)
        p_fast, se_fast, df_fast = _two_way_p_fast(cars, st, wk)
        ref = mean_car_two_way(cars, w, [int(x) for x in wk],
                               [int(x) for x in st])
        worst = max(worst, abs(p_fast - ref.p), abs(se_fast - ref.se))
    a2 = worst < 1e-15
    ok &= a2
    print(f"    2  fast two-way p/se vs mean_car_two_way, 5 panels: "
          f"max |diff| {worst:.2e}  {'PASS' if a2 else '*** FAIL ***'}")

    # --- ARM 3: the fast panel has the structure it claims ---------------
    # The twin draws in a different ORDER from `_ban_like_panel`, so it cannot
    # be bit-identical. What must match is the covariance structure, which is
    # what the estimator actually sees.
    rng3 = np.random.default_rng(3)
    rs, rw = 0.25, 0.15
    got_var: list[float] = []
    got_stock: list[float] = []
    got_week: list[float] = []
    for _ in range(300):
        cars, st, wk = _fast_panel(rng3, rs, rw, 0.0)
        got_var.append(float(cars.var()))
        # within-stock covariance, over pairs in the same stock
        for lab, arr in (("stock", st), ("week", wk)):
            order = np.argsort(arr, kind="stable")
            s = arr[order]
            c = cars[order]
            bnd = np.flatnonzero(np.diff(s)) + 1
            cov, cnt = 0.0, 0
            for grp in np.split(c, bnd):
                if grp.size >= 2:
                    tot = grp.sum()
                    cov += float(tot * tot - np.dot(grp, grp))
                    cnt += grp.size * (grp.size - 1)
            if cnt:
                (got_stock if lab == "stock" else got_week).append(cov / cnt)
    mv, ms, mw = (float(np.mean(got_var)), float(np.mean(got_stock)),
                  float(np.mean(got_week)))
    a3 = abs(mv - 1.0) < 0.02 and abs(ms - rs) < 0.02 and abs(mw - rw) < 0.02
    ok &= a3
    print(f"    3  fast panel structure over 300 draws "
          f"{'PASS' if a3 else '*** FAIL ***'}")
    print(f"       marginal variance        {mv:.4f}  want 1.0000")
    print(f"       within-stock covariance  {ms:.4f}  want {rs:.4f}")
    print(f"       within-week  covariance  {mw:.4f}  want {rw:.4f}")

    # --- ARM 4: the twin and the ORIGINAL agree on the measured size -----
    # Distributional equivalence where it counts: the two generators are run
    # through the SAME estimator and must give the same rejection rate.
    rng4a = np.random.default_rng(4)
    rng4b = np.random.default_rng(5)
    n4 = 400
    rej_fast = sum(1 for _ in range(n4)
                   if _two_way_p_fast(*_fast_panel(rng4a, rs, rw, 0.0))[0] < 0.01)
    rej_slow = 0
    for _ in range(n4):
        c, stl, wkl = _ban_like_panel(rng4b, rs, rw, 0.0)
        if mean_car_two_way(c, w, wkl, stl).p < 0.01:
            rej_slow += 1
    diff = abs(rej_fast - rej_slow) / n4
    a4 = diff < 0.025           # 2 x the ~1.1pp binomial SE of the difference
    ok &= a4
    print(f"    4  size at nominal 1%, {n4} sims each, same estimator")
    print(f"       fast twin  {rej_fast:>3}/{n4} = {rej_fast / n4:.2%}")
    print(f"       original   {rej_slow:>3}/{n4} = {rej_slow / n4:.2%}")
    print(f"       |difference| {diff:.2%} within Monte-Carlo noise  "
          f"{'PASS' if a4 else '*** FAIL ***'}")

    # --- ARM 5: the threshold rule recovers a KNOWN answer ---------------
    # Under a correctly sized test the null p-values are Uniform(0,1), so the
    # 1% quantile must come back at ~0.01 and the rule must not invent a
    # correction where none is needed.
    rng5 = np.random.default_rng(6)
    uni = rng5.random(N_CAL)
    thr = _threshold(uni, TARGET)
    a5 = abs(thr - TARGET) < 0.004
    ok &= a5
    print(f"    5  threshold rule on Uniform(0,1) p-values: {thr:.6f}, "
          f"want ~{TARGET}  {'PASS' if a5 else '*** FAIL ***'}")

    # --- ARM 6: and it TIGHTENS when the p-values are over-dispersed -----
    # p = U^2 rejects at 10% at a nominal 1%; the rule must return ~0.0001.
    thr2 = _threshold(rng5.random(N_CAL) ** 2, TARGET)
    a6 = thr2 < 0.0005
    ok &= a6
    print(f"    6  threshold rule on over-rejecting p=U^2: {thr2:.8f}, "
          f"want ~{TARGET ** 2:.6f}  {'PASS' if a6 else '*** FAIL ***'}")

    # --- ARM 7: the SIMULATED standard error against the ANALYTIC truth --
    # The whole power verdict rests on the size of the two-way SE, so it is
    # checked against a closed form rather than trusted because it came out of
    # a simulation. A ratio below 1 means the estimator UNDER-states the true
    # variance -- the same over-rejection ARM 6b of event_study.py found, seen
    # from the other side -- and it means the MDE below is if anything
    # optimistic, never pessimistic.
    print("    7  simulated two-way SE vs the analytic true SD of the mean")
    print(f"       {'rho_s':>7}{'rho_w':>7}{'analytic':>11}{'simulated':>11}"
          f"{'ratio':>8}")
    rng7 = np.random.default_rng(7)
    worst7 = 0.0
    down = True
    for rs_, rw_ in ((0.15, 0.10), (0.25, 0.15), (0.35, 0.25)):
        ses = [_two_way_p_fast(*_fast_panel(rng7, rs_, rw_, 0.0))[1]
               for _ in range(400)]
        got = float(np.mean(ses))
        want = analytic_sd_of_mean(rs_, rw_)
        print(f"       {rs_:>7.2f}{rw_:>7.2f}{want:>11.6f}{got:>11.6f}"
              f"{got / want:>8.3f}")
        worst7 = max(worst7, abs(got / want - 1.0))
        down &= got < want
    a7 = worst7 < 0.06 and down
    ok &= a7
    print(f"       max deviation {worst7:.1%}, and every cell is DOWNWARD: the")
    print("       estimator under-states, so the MDE below is optimistic  "
          + ("PASS" if a7 else "*** FAIL ***"))

    print(f"\n  DRY RUN: {'ALL ARMS PASS' if ok else '*** FAILED ***'}")
    return ok


# =====================================================================
# The calibration itself
# =====================================================================

def _threshold(pvals: np.ndarray, target: float) -> float:
    """The nominal p-threshold whose rejection rate is `target`: the k-th
    smallest null p-value, k = round(target * N). Rejecting at p < that value
    fires on k-1 of N draws, at that value on k of N."""
    k = max(1, int(round(target * pvals.size)))
    return float(np.partition(np.asarray(pvals, dtype=float), k - 1)[k - 1])


def _clopper_pearson(k: int, n: int, conf: float) -> tuple[float, float]:
    """Exact binomial interval -- no normal approximation at a 1% rate."""
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(_st.beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(_st.beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return lo, hi


def _null_pvals(rho_stock: float, rho_week: float, n_sims: int, seed: int
                ) -> tuple[np.ndarray, np.ndarray, int]:
    """(p-values, standard errors, df) over `n_sims` ZERO-effect panels."""
    rng = np.random.default_rng(seed)
    ps = np.empty(n_sims, dtype=float)
    ses = np.empty(n_sims, dtype=float)
    df = 0
    for i in range(n_sims):
        p, se, df = _two_way_p_fast(*_fast_panel(rng, rho_stock, rho_week, 0.0))
        ps[i] = p
        ses[i] = se
    return ps, ses, df


def calibrate() -> float:
    """Print the grid and return alpha*."""
    print("\n" + "=" * 72)
    print("  STEP 1 -- CALIBRATION GRID")
    print("=" * 72)
    print(f"\n  {N_CAL:,} zero-effect sims per cell, on the OBSERVED structure:")
    print(f"  {N_STOCKS_OBSERVED} stocks / {N_ENTRIES_OBSERVED:,} entries / "
          f"{N_WEEKS_OBSERVED} weeks, one stock carrying "
          f"{max(STOCK_ENTRY_COUNTS)} entries.")
    print(f"  Reported per cell: the size a NOMINAL p<0.01 actually buys, and")
    print(f"  the nominal threshold that would buy a true {TARGET:.1%}.\n")

    hdr = f"    {'rho_stock':>9} {'rho_week':>9} {'size@0.01':>11} {'threshold@1%':>14} {'mean SE':>10} {'df':>5}"
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))

    cells: dict[tuple[float, float], tuple[float, float, float, int]] = {}
    seed = CAL_SEED
    for rs in RHO_STOCK_GRID:
        for rw in RHO_WEEK_GRID:
            t0 = time.time()
            ps, ses, df = _null_pvals(rs, rw, N_CAL, seed)
            seed += 1
            size01 = float((ps < 0.01).mean())
            thr = _threshold(ps, TARGET)
            mse = float(ses.mean())
            cells[(rs, rw)] = (size01, thr, mse, df)
            star = " <- middle" if (rs, rw) == MIDDLE else ""
            print(f"    {rs:>9.2f} {rw:>9.2f} {size01:>11.2%} {thr:>14.6f} "
                  f"{mse:>10.6f} {df:>5}{star}   [{time.time() - t0:.0f}s]")

    alpha_star = min(v[1] for v in cells.values())
    worst = [k for k, v in cells.items() if v[1] == alpha_star][0]
    print(f"\n  Smallest threshold over the grid -> "
          f"ALPHA* = {alpha_star:.6f}")
    print(f"  taken at the most demanding cell rho_stock={worst[0]}, "
          f"rho_week={worst[1]}.")
    print(f"  Monte-Carlo resolution: the threshold is the "
          f"{max(1, int(round(TARGET * N_CAL)))}-th of {N_CAL:,} order")
    print(f"  statistics, so it carries real sampling error; it is NOT quoted "
          f"to more than 4 s.f.")
    return alpha_star


def validate(alpha_star: float) -> float:
    """Fresh-sample size at alpha*, at the middle cell. Returns the mean SE."""
    print("\n" + "=" * 72)
    print("  STEP 1b -- FRESH-SAMPLE VALIDATION")
    print("=" * 72)
    rs, rw = MIDDLE
    print(f"\n  {N_VAL:,} NEW zero-effect sims at the middle cell "
          f"(rho_stock {rs}, rho_week {rw}),")
    print(f"  independent stream (seed {VAL_SEED}), tested at "
          f"alpha* = {alpha_star:.6f}.\n")
    ps, ses, df = _null_pvals(rs, rw, N_VAL, VAL_SEED)
    k = int((ps < alpha_star).sum())
    rate = k / N_VAL
    lo, hi = _clopper_pearson(k, N_VAL, 0.99)
    covers = lo <= TARGET <= hi
    k01 = int((ps < 0.01).sum())
    print(f"    realised size at alpha*   {k:>4}/{N_VAL:,} = {rate:.2%}")
    print(f"    99% Clopper-Pearson band  [{lo:.2%}, {hi:.2%}]")
    print(f"    contains the {TARGET:.0%} target   "
          f"{'YES' if covers else 'NO -- alpha* DOES NOT DELIVER 1%'}")
    print(f"\n    for contrast, same sample at the nominal 0.01: "
          f"{k01:>4}/{N_VAL:,} = {k01 / N_VAL:.2%}")
    return float(ses.mean())


def power_at(alpha_star: float, mean_se_unit: float, df: int) -> None:
    """STEP 2 -- the two-way MDE at alpha*, in bps, against the Phase 2 bar."""
    print("\n" + "=" * 72)
    print("  STEP 2 -- POWER AT ALPHA*")
    print("=" * 72)
    crit = float(_st.t.ppf(1.0 - alpha_star / 2.0, df))
    crit_own = _t_ppf(1.0 - alpha_star / 2.0, float(df))
    pw = float(_st.t.ppf(POWER, df))
    print(f"\n  df = min(G_week, G_stock) - 1 = {df}")
    print(f"  t crit at alpha*={alpha_star:.6f} two-sided : {crit:.6f}"
          f"   (module's own _t_ppf: {crit_own:.6f})")
    print(f"  t at {POWER:.0%} power                        : {pw:.6f}")

    for label, a in (("nominal 0.01", 0.01), ("alpha*", alpha_star)):
        c = float(_st.t.ppf(1.0 - a / 2.0, df))
        mde_unit = (c + pw) * mean_se_unit
        mde_bps = mde_unit * SD_EVENT * 10_000.0
        clears = mde_bps <= BAR_BPS
        print(f"\n  at {label:<13} (a={a:.6f})")
        print(f"    mean two-way SE, unit SD   {mean_se_unit:.6f}")
        print(f"    MDE at SD_event {SD_EVENT:.0%}          "
              f"{mde_unit * SD_EVENT * 100:.4f}%  = {mde_bps:.2f} bps")
        print(f"    against the 3x delivery bar  {BAR_BPS:.2f} bps          "
              f"{'CLEARS' if clears else '*** DOES NOT CLEAR ***'}")
        print(f"    headroom                     "
              f"{BAR_BPS - mde_bps:+.2f} bps "
              f"({mde_bps / BAR_BPS:.3f}x the bar)")

    print(f"\n  MDE ACROSS THE WHOLE GRID at alpha*, SD_event {SD_EVENT:.0%}, "
          f"against the {BAR_BPS:.2f} bps bar:")
    crit_a = float(_st.t.ppf(1.0 - alpha_star / 2.0, df))
    n_clear = 0
    print(f"    {'rho_s':>7}{'rho_w':>7}{'MDE bps':>11}{'x bar':>8}   verdict")
    for rs_ in RHO_STOCK_GRID:
        for rw_ in RHO_WEEK_GRID:
            m_bps = ((crit_a + pw) * analytic_sd_of_mean(rs_, rw_)
                     * SD_EVENT * 10_000.0)
            good = m_bps <= BAR_BPS
            n_clear += int(good)
            print(f"    {rs_:>7.2f}{rw_:>7.2f}{m_bps:>11.2f}"
                  f"{m_bps / BAR_BPS:>8.2f}   "
                  + ("CLEARS" if good else "*** FAILS ***"))
    print(f"\n    {n_clear} of {len(RHO_STOCK_GRID) * len(RHO_WEEK_GRID)} grid "
          f"cells clear the bar.")

    print("\n  BREAK-EVEN -- stated so the gap is legible, NOT adopted:")
    need_se = BAR_BPS / 10_000.0 / SD_EVENT / (crit_a + pw)
    print(f"    required two-way SE at unit SD   {need_se:.6f}")
    print(f"    realised at the middle cell      {mean_se_unit:.6f}"
          f"   ({mean_se_unit / need_se:.2f}x too large)")
    for rs_ in (0.0, 0.01, 0.02, 0.05, 0.10, 0.15):
        m_bps = ((crit_a + pw) * analytic_sd_of_mean(rs_, 0.15)
                 * SD_EVENT * 10_000.0)
        print(f"      rho_stock {rs_:<5} (rho_week 0.15) -> MDE {m_bps:>7.2f} "
              f"bps   " + ("clears" if m_bps <= BAR_BPS else "fails"))
    sd_need = BAR_BPS / 10_000.0 / ((crit_a + pw) * mean_se_unit)
    print(f"    SD_event that would clear at the middle cell: {sd_need:.3%}"
          f"   (the pre-check assumed {SD_EVENT:.0%})")
    print("\n  WHY THIS DIFFERS FROM THE PHASE 2 PRE-CHECK'S 42.44 bps.")
    print("  That figure clusters on the DATE only (G = 1,203 entry dates,")
    print("  m = 1.48, rho = 0.2), which treats the 1,781 entries as ~1,203")
    print("  near-independent draws. Clustering on the STOCK as well does not:")
    print("  1,781 entries sit in 141 stocks, one holding 75, so")
    print("  sum_s c_s^2 = 53,887 against n = 1,781. That ratio -- not the")
    mde_nom = (float(_st.t.ppf(0.995, df)) + pw) * mean_se_unit
    mde_cal = (crit_a + pw) * mean_se_unit
    print("  threshold calibration -- is what moves the MDE. Moving from the")
    print(f"  nominal 0.01 to alpha* costs {mde_cal / mde_nom - 1.0:.1%} of the "
          f"MDE; adding the stock")
    print(f"  dimension costs {mde_cal * SD_EVENT * 10_000.0 / 42.44:.1f}x.")

    # A direct check: plant the alpha* MDE and measure the detection rate.
    print(f"\n  Direct power check -- plant the alpha* MDE, measure detection:")
    rs, rw = MIDDLE
    c = float(_st.t.ppf(1.0 - alpha_star / 2.0, df))
    mde_unit = (c + pw) * mean_se_unit
    rng = np.random.default_rng(VAL_SEED + 1)
    n = 2_000
    hits = sum(1 for _ in range(n)
               if _two_way_p_fast(*_fast_panel(rng, rs, rw, mde_unit))[0]
               < alpha_star)
    lo, hi = _clopper_pearson(hits, n, 0.99)
    print(f"    {hits}/{n:,} = {hits / n:.1%} detected at alpha*, "
          f"expected {POWER:.0%}")
    print(f"    99% band [{lo:.1%}, {hi:.1%}]  "
          f"{'consistent' if lo <= POWER <= hi else 'NOT consistent with 80%'}")


def main() -> int:
    print("=" * 72)
    print("  TWO-WAY CLUSTERED THRESHOLD CALIBRATION -- Phase 2, ban-list entry")
    print("=" * 72)
    if not dry_run():
        print("\n  DRY RUN FAILED -- calibration not run.")
        return 1
    if "--dry-run" in sys.argv:
        return 0
    alpha_star = calibrate()
    mean_se = validate(alpha_star)
    _, _, df = _null_pvals(MIDDLE[0], MIDDLE[1], 1, VAL_SEED)
    power_at(alpha_star, mean_se, df)
    print("\n" + "=" * 72)
    print(f"  ALPHA* = {alpha_star:.6f}   (nominal two-way p-threshold)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
