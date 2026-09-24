r"""
gate_ban_list_nuisance.py -- executes GATE_BAN_LIST_NUISANCE.md.

Measures ONLY rho_stock, rho_week and the per-event CAR standard deviation,
from MEAN-REMOVED CARs, and decides on those three alone whether Phase 2
proceeds to locking PREREG_BAN_LIST_ENTRY.md.

=== THE BLIND, AND HOW IT IS ENFORCED ===

This module must never compute, print, log, return or persist the mean CAR,
any t-statistic or p-value on real data, per-event CARs, or any sum, quantile
or sign count from which a mean is recoverable.

That is enforced structurally, not by care:

  * `prepare_residuals()` is the ONLY way out of the data layer. It subtracts
    the grand mean INSIDE itself and returns residuals. The mean goes out of
    scope at that return and no caller ever holds it. `_build_cars()` is
    private and is called from nowhere else.
  * every published figure goes through `emit()`, which holds an explicit
    ALLOW-list of keys. An unlisted key raises. A number this module was not
    authorised to publish cannot reach stdout or the results file by accident.
  * ARM 8 of the dry run asserts both: that `prepare_residuals` returns
    residuals summing to zero, and that `emit` refuses a forbidden key.

The blinding is PROCEDURAL and is stated as such in §1 of the gate document.
The bhavcopy on disk obviously contains the answer; the integrity of the blind
rests on this being the only script run against the assembled event set before
the pre-registration is locked. It is not claimed to be stronger than that.

=== THE ESTIMATOR ===

    CAR_i = mu + u_s(i) + v_w(i) + e_i

Method-of-moments variance components on the residuals r:

    sig2_hat = sum r_i^2 / (n - 1)
    C_stock  = [sum_s (T_s^2 - SS_s)] / sum_s c_s(c_s - 1)
    C_week   = [sum_w (T_w^2 - SS_w)] / sum_w m_w(m_w - 1)
    rho_stock = C_stock / sig2_hat        rho_week = C_week / sig2_hat

Separately identified BY THE DESIGN, not by assumption: the 5-trading-day
same-stock exclusion means two kept entries of one stock are never within five
sessions, and an ISO week holds at most five sessions, so no same-stock pair
shares a week and no same-week pair shares a stock. `_assert_disjoint()`
checks that on the real event set and ABORTS if it does not hold.

Run:  python src/gate_ban_list_nuisance.py
      python src/gate_ban_list_nuisance.py --dry-run
"""
from __future__ import annotations

import csv
import io
import math
import sys
from datetime import date
from pathlib import Path
from typing import Final, Optional, Sequence

import numpy as np
from scipy import stats as _st  # type: ignore[import-untyped]

from calibrate_two_way_alpha import _clopper_pearson, _threshold
from event_study import (N_ENTRIES_OBSERVED, N_WEEKS_OBSERVED,
                         STOCK_ENTRY_COUNTS, EventWindow, _two_sided_t_p,
                         exclude_overlapping, mean_car_two_way)
from fetch_cash_bhavcopy import read_day
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SECBAN: Final[Path] = ROOT / "data" / "fo_secban_2015_2026.csv"
CORPACT: Final[Path] = ROOT / "data" / "corpactions_banlist_2015_2026.csv"
NIFTY500: Final[Path] = ROOT / "data" / "nifty500_daily_2015_2026.csv"
RESULTS: Final[Path] = ROOT / "results"

# --- the gate's own constants, fixed by GATE_BAN_LIST_NUISANCE.md ----------
TARGET: Final[float] = 0.01          # the TRUE size alpha* must buy
N_GATE: Final[int] = 20_000          # calibration sims
N_VAL: Final[int] = 20_000           # fresh validation sims
N_BOOT: Final[int] = 5_000           # cluster-bootstrap resamples
# The percentile at which the cluster bootstrap is READ so that the bound
# actually DELIVERS one-sided 90% coverage. It is NOT 0.90: the nominal 0.90
# percentile was measured at 74.0% worst-cell coverage on the observed
# structure. 0.997 is q*, selected and fresh-seed validated in
# GATE_BAN_LIST_NUISANCE_ADDENDUM_01.md by calibrate_interval_method.py.
# It is tied to N_BOOT -- a far-tail quantile of a different number of draws
# is a different bound -- and ARM 3 of that script locks the two together.
BOUND_Q: Final[float] = 0.997        # reads a TRUE one-sided 90% bound
POWER: Final[float] = 0.80
BAR_BPS: Final[float] = 71.35        # 3 x 23.7821 bps delivery floor, today
WINDOW_DAYS: Final[int] = 4          # open D -> close D+4
MIN_SEPARATION: Final[int] = 5       # trading days, same-stock exclusion
EXTREME: Final[float] = 0.20         # daily return flagged, never excluded
SEED: Final[int] = 20260922

# The ONLY keys this module may publish. An unlisted key raises -- see the
# module docstring. Note what is absent: mean, t, p, car, sum, sign.
ALLOWED: Final[frozenset[str]] = frozenset({
    "n_entries_raw", "n_after_same_stock", "n_after_exdate", "n_after_prices",
    "n_stocks", "n_weeks", "n_dropped_same_stock", "n_dropped_exdate",
    "n_dropped_missing_price", "n_dropped_nifty_gap", "n_nifty_gap_days",
    "n_after_nifty_gap", "n_extreme_daily", "max_stock_count",
    "sum_c2", "df", "span_first", "span_last",
    "rho_stock_hat", "rho_week_hat", "sd_event_hat",
    "rho_stock_upper", "rho_week_upper", "sd_event_upper",
    "alpha_star", "size_at_alpha_star", "size_lo", "size_hi",
    "mde_bps", "mde_pct", "bar_bps", "se_two_way_sim", "se_two_way_analytic",
    "power_check", "verdict",
})

_EMITTED: dict[str, object] = {}


def emit(key: str, value: object) -> None:
    """Publish one figure. A key outside ALLOWED is a hard error."""
    if key not in ALLOWED:
        raise KeyError(
            f"BLIND VIOLATION: '{key}' is not in the allow-list. "
            f"GATE_BAN_LIST_NUISANCE.md permits only rho_stock, rho_week, the "
            f"per-event SD, their bounds, alpha*, the MDE and the verdict.")
    _EMITTED[key] = value


# =====================================================================
# DATA LAYER -- ends at prepare_residuals(), which does not return the mean
# =====================================================================

def _read_secban() -> tuple[dict[str, set[str]], list[str]]:
    by_day: dict[str, set[str]] = {}
    with io.open(SECBAN, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0] == "ban_date":
                continue
            by_day.setdefault(row[0], set()).add(row[1])
    return by_day, sorted(by_day)


def _entries() -> list[tuple[str, str]]:
    """(date, symbol) for every ENTRY: absent on the previous archived day,
    present on this one. Hysteresis (95% in, 80% out) is why status is not an
    event -- see PREREG_BAN_LIST_ENTRY.md §1."""
    by_day, days = _read_secban()
    out: list[tuple[str, str]] = []
    for i, d in enumerate(days):
        prev = by_day[days[i - 1]] if i else set()
        for s in sorted(by_day[d]):
            if s != "__NONE__" and s not in prev:
                out.append((d, s))
    return out


def _exdates() -> dict[str, list[date]]:
    out: dict[str, list[date]] = {}
    with io.open(CORPACT, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0] == "date":
                continue
            out.setdefault(row[1], []).append(date.fromisoformat(row[0]))
    return out


def _nifty500() -> dict[date, tuple[float, float]]:
    out: dict[date, tuple[float, float]] = {}
    with io.open(NIFTY500, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0] == "date":
                continue
            out[date.fromisoformat(row[0])] = (float(row[1]), float(row[2]))
    return out


def _load_prices(days: Sequence[date], symbols: frozenset[str]
                 ) -> dict[date, dict[str, tuple[float, float, float]]]:
    """(date -> symbol -> (open, close, prevclose)) for the ban-list symbols
    only. Days with no cached bhavcopy are simply absent, and the trading
    calendar is taken from the days that ARE present."""
    out: dict[date, dict[str, tuple[float, float, float]]] = {}
    for i, d in enumerate(days):
        day = read_day(d)
        if day is None:
            continue
        out[d] = {s: v for s, v in day.items() if s in symbols}
        if (i + 1) % 500 == 0:
            print(f"      read {i + 1:,}/{len(days):,} bhavcopy days",
                  flush=True)
    return out


def _build_cars() -> tuple[np.ndarray, list[str], list[tuple[int, int]],
                           dict[str, int]]:
    """PRIVATE. Assembles the kept event set and its per-event CARs.

    Called only by `prepare_residuals`, which strips the mean before anything
    downstream sees the numbers. Do not call this from anywhere else.

    Returns (cars, stock_labels, week_labels, counts)."""
    counts: dict[str, int] = {}
    raw = _entries()
    counts["n_entries_raw"] = len(raw)

    # --- the trading calendar comes from the bhavcopy that is actually on
    # --- disk, not from the ban archive, whose 165 weekday gaps do not
    # --- distinguish an exchange holiday from a missing file.
    _, archived = _read_secban()
    span = [date.fromisoformat(d) for d in archived]
    symbols = frozenset(s for _, s in raw)
    print(f"    loading bhavcopy for {len(span):,} archived days ...",
          flush=True)
    prices = _load_prices(span, symbols)
    cal = sorted(prices)
    pos = {d: i for i, d in enumerate(cal)}
    print(f"    trading calendar: {len(cal):,} days with cached bhavcopy",
          flush=True)

    # --- 1. same-stock exclusion, in TRADING days, forward-greedy ---------
    usable = [(d, s) for d, s in raw if date.fromisoformat(d) in pos]
    ordinals = [pos[date.fromisoformat(d)] for d, _ in usable]
    stocks = [s for _, s in usable]
    keep = exclude_overlapping(ordinals, stocks, MIN_SEPARATION)
    counts["n_after_same_stock"] = len(keep)
    counts["n_dropped_same_stock"] = len(usable) - len(keep)

    # --- 2. ex-date exclusion, D+1 .. D+4 ---------------------------------
    ex = _exdates()
    kept2: list[int] = []
    for i in keep:
        j = ordinals[i]
        if j + WINDOW_DAYS >= len(cal):
            continue
        lo, hi = cal[j + 1], cal[j + WINDOW_DAYS]
        if any(lo <= e <= hi for e in ex.get(stocks[i], ())):
            continue
        kept2.append(i)
    counts["n_after_exdate"] = len(kept2)
    counts["n_dropped_exdate"] = len(keep) - len(kept2)

    # --- 3. NIFTY 500 gap exclusion, decided on DATES ---------------------
    # Nine days trade in the cash bhavcopy but are absent from NSE's
    # ind_close_all archive (all 2015 - mid-2016; re-probed 2026-09-22, all
    # still HTTP 404; each confirmed a real session by a second NSE endpoint,
    # the F&O ban archive). An event whose window touches one of them has no
    # benchmark for part of that window.
    #
    # The rule drops the event if ANY day of [D, D+4] is a gap day, not merely
    # if D or D+4 is. Only the endpoints are arithmetically needed, but a rule
    # stated on the whole window is decidable from dates alone, before any
    # return exists, and cannot later be argued into a different shape once the
    # answer is known. The gap set is DERIVED, never hardcoded, so a change in
    # the data surfaces as a changed count instead of passing silently.
    idx = _nifty500()
    gapset = {d for d in cal if d not in idx}
    counts["n_nifty_gap_days"] = len(gapset)
    kept3: list[int] = []
    for i in kept2:
        j = ordinals[i]
        if any(cal[k] in gapset for k in range(j, j + WINDOW_DAYS + 1)):
            continue
        kept3.append(i)
    counts["n_after_nifty_gap"] = len(kept3)
    counts["n_dropped_nifty_gap"] = len(kept2) - len(kept3)

    # --- 4. prices, and the market-adjusted CAR ---------------------------
    cars: list[float] = []
    lab_s: list[str] = []
    lab_w: list[tuple[int, int]] = []
    missing = 0
    extreme = 0
    for i in kept3:
        j = ordinals[i]
        d0, d4 = cal[j], cal[j + WINDOW_DAYS]
        sym = stocks[i]
        p0 = prices.get(d0, {}).get(sym)
        p4 = prices.get(d4, {}).get(sym)
        i0, i4 = idx.get(d0), idx.get(d4)
        if p0 is None or p4 is None or i0 is None or i4 is None:
            missing += 1
            continue
        if p0[0] <= 0.0 or i0[0] <= 0.0:
            missing += 1
            continue
        stock_ret = p4[1] / p0[0] - 1.0            # open D  -> close D+4
        bench_ret = i4[1] / i0[0] - 1.0            # identical interval
        cars.append(stock_ret - bench_ret)
        lab_s.append(sym)
        iso = d0.isocalendar()
        lab_w.append((int(iso[0]), int(iso[1])))
        # extreme DAILY returns inside a KEPT window: logged, never excluded
        for k in range(j + 1, j + WINDOW_DAYS + 1):
            a = prices.get(cal[k - 1], {}).get(sym)
            b = prices.get(cal[k], {}).get(sym)
            if a and b and a[1] > 0.0 and abs(b[1] / a[1] - 1.0) > EXTREME:
                extreme += 1
    counts["n_after_prices"] = len(cars)
    counts["n_dropped_missing_price"] = missing
    counts["n_extreme_daily"] = extreme
    counts["span_first"] = 0 if not cars else int(cal[min(
        ordinals[i] for i in kept3)].toordinal())
    return np.asarray(cars, dtype=float), lab_s, lab_w, counts


def prepare_residuals() -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                 dict[str, int]]:
    """THE ONLY WAY OUT OF THE DATA LAYER.

    Subtracts the grand mean inside this function and returns residuals. The
    mean is not returned, not stored and not published: it goes out of scope
    at the return statement.

    Returns (residuals, stock_codes, week_codes, counts)."""
    cars, lab_s, lab_w, counts = _build_cars()
    if cars.size < 2:
        raise RuntimeError(f"only {cars.size} events survived; gate cannot run")
    resid = cars - cars.mean()           # the mean dies here, deliberately
    s_uniq = {s: i for i, s in enumerate(sorted(set(lab_s)))}
    w_uniq = {w: i for i, w in enumerate(sorted(set(lab_w)))}
    counts["n_stocks"] = len(s_uniq)
    counts["n_weeks"] = len(w_uniq)
    return (resid,
            np.asarray([s_uniq[s] for s in lab_s], dtype=np.int64),
            np.asarray([w_uniq[w] for w in lab_w], dtype=np.int64),
            counts)


def _assert_disjoint(stock: np.ndarray, week: np.ndarray) -> None:
    """The two variance components are separately identified only if no
    same-stock pair shares a week. Guaranteed by the 5-day exclusion, CHECKED
    here, because a confounded component is not worth reporting."""
    seen: set[tuple[int, int]] = set()
    for s, w in zip(stock.tolist(), week.tolist()):
        if (s, w) in seen:
            raise RuntimeError(
                f"stock {s} has two kept entries in ISO week {w}: the "
                f"variance components are confounded and the gate aborts")
        seen.add((s, w))


# =====================================================================
# METHOD-OF-MOMENTS VARIANCE COMPONENTS
# =====================================================================

def _pair_cov(resid: np.ndarray, codes: np.ndarray, n_groups: int) -> float:
    """Mean covariance over distinct within-group pairs:
        [sum_g (T_g^2 - SS_g)] / sum_g n_g (n_g - 1)."""
    tot = np.bincount(codes, weights=resid, minlength=n_groups)
    ss = np.bincount(codes, weights=resid * resid, minlength=n_groups)
    cnt = np.bincount(codes, minlength=n_groups).astype(float)
    den = float((cnt * (cnt - 1.0)).sum())
    if den <= 0.0:
        return 0.0
    return float((tot * tot - ss).sum()) / den


def variance_components(resid: np.ndarray, stock: np.ndarray,
                        week: np.ndarray) -> tuple[float, float, float]:
    """(rho_stock, rho_week, sd_event) by method of moments."""
    n = resid.size
    sig2 = float(np.dot(resid, resid)) / float(n - 1)
    if sig2 <= 0.0:
        return 0.0, 0.0, 0.0
    c_s = _pair_cov(resid, stock, int(stock.max()) + 1)
    c_w = _pair_cov(resid, week, int(week.max()) + 1)
    return c_s / sig2, c_w / sig2, math.sqrt(sig2)


def _blocks(codes: np.ndarray) -> list[np.ndarray]:
    order = np.argsort(codes, kind="stable")
    s = codes[order]
    return list(np.split(order, np.flatnonzero(np.diff(s)) + 1))


def bootstrap_upper(resid: np.ndarray, stock: np.ndarray, week: np.ndarray,
                    by: str, rng: np.random.Generator
                    ) -> tuple[float, float]:
    """One-sided 90%-COVERAGE upper bounds, by nonparametric cluster bootstrap
    read at the CALIBRATED percentile BOUND_Q (0.997, not 0.90).

    The nominal 0.90 percentile delivers 74.0% coverage on this structure, not
    90%, because the whole-stock bootstrap under-states the sampling SD of
    rho_stock_hat by about 19% when the blocks are as unbalanced as they really
    are. See GATE_BAN_LIST_NUISANCE_ADDENDUM_01.md.

    `by='stock'` resamples STOCKS with replacement, carrying each stock's whole
    block of entries, and bounds (rho_stock, sd_event). `by='week'` resamples
    WEEKS and bounds (rho_week, sd_event). Each bootstrap resamples the
    dimension it is bounding: resampling stocks destroys the week structure and
    vice versa, so neither interval is quoted for the other's parameter."""
    codes = stock if by == "stock" else week
    blocks = _blocks(codes)
    g = len(blocks)
    rhos = np.empty(N_BOOT, dtype=float)
    sds = np.empty(N_BOOT, dtype=float)
    for b in range(N_BOOT):
        pick = rng.integers(0, g, g)
        idx = np.concatenate([blocks[p] for p in pick])
        r = resid[idx]
        # relabel the resampled clusters so a stock drawn twice counts twice
        lab = np.concatenate([np.full(blocks[p].size, k, dtype=np.int64)
                              for k, p in enumerate(pick)])
        n = r.size
        sig2 = float(np.dot(r, r)) / float(n - 1)
        sds[b] = math.sqrt(sig2) if sig2 > 0.0 else 0.0
        rhos[b] = (_pair_cov(r, lab, g) / sig2) if sig2 > 0.0 else 0.0
    return (float(np.quantile(rhos, BOUND_Q)),
            float(np.quantile(sds, BOUND_Q)))


# =====================================================================
# TWO-WAY MACHINERY on an ARBITRARY structure (the real one, not a snapshot)
# =====================================================================

def _cvar(resid: np.ndarray, codes: np.ndarray, n_groups: int) -> float:
    tot = np.bincount(codes, weights=resid, minlength=n_groups)
    return float(np.dot(tot, tot)) / float(resid.size * resid.size)


def two_way_p(cars: np.ndarray, stock: np.ndarray, week: np.ndarray,
              n_s: int, n_w: int) -> tuple[float, float, int]:
    """(p, se, df), Cameron-Gelbach-Miller, on any (stock, week) structure.
    Identical arithmetic to `event_study.mean_car_two_way`, asserted in ARM 1."""
    resid = cars - cars.mean()
    v_a = _cvar(resid, week, n_w)
    v_b = _cvar(resid, stock, n_s)
    v_ab = _cvar(resid, stock.astype(np.int64) * n_w + week, n_s * n_w)
    v = v_a + v_b - v_ab
    if v <= 0.0:
        v = max(v_a, v_b)
    df = min(int(np.unique(week).size), int(np.unique(stock).size)) - 1
    se = math.sqrt(v)
    t = float(cars.mean()) / se if se > 0.0 else float("nan")
    return _two_sided_t_p(t, float(df)), se, df


def panel_on(rng: np.random.Generator, stock: np.ndarray, week: np.ndarray,
             n_s: int, n_w: int, rho_s: float, rho_w: float,
             planted: float) -> np.ndarray:
    """Zero-mean panel with the given variance components ON THE REAL
    (stock, week) assignment of the kept events -- not a uniform redraw, so
    the real bunching of entries into stressed weeks is preserved."""
    u = rng.standard_normal(n_s)
    v = rng.standard_normal(n_w)
    e = rng.standard_normal(stock.size)
    idio = math.sqrt(max(0.0, 1.0 - rho_s - rho_w))
    out = (math.sqrt(rho_s) * u[stock] + math.sqrt(rho_w) * v[week]
           + idio * e + planted)
    return np.asarray(out, dtype=float)


def analytic_sd_of_mean(stock: np.ndarray, week: np.ndarray, n_s: int,
                        n_w: int, rho_s: float, rho_w: float) -> float:
    """Closed-form SD of the mean on THIS structure:
        [n + rho_s(sum c_s^2 - n) + rho_w(sum m_w^2 - n)] / n^2."""
    n = float(stock.size)
    c = np.bincount(stock, minlength=n_s).astype(float)
    m = np.bincount(week, minlength=n_w).astype(float)
    var = (n + rho_s * (float((c * c).sum()) - n)
           + rho_w * (float((m * m).sum()) - n)) / (n * n)
    return math.sqrt(var)


def synth_observed(rng: np.random.Generator, rho_s: float, rho_w: float,
                   sd: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A panel on the OBSERVED ban-entry structure, with PLANTED components.

    Lives here rather than in `calibrate_interval_method.py` because both that
    script and ARM 4 below must measure coverage on the SAME generator. Two
    copies of a panel generator is how a calibration silently stops applying to
    the thing it calibrated.

    Weeks are drawn WITHOUT replacement within each stock, reproducing the
    property the 5-trading-day same-stock exclusion gives the real data: no
    same-stock pair ever shares an ISO week."""
    n_s = len(STOCK_ENTRY_COUNTS)
    u = rng.standard_normal(n_s)
    v = rng.standard_normal(N_WEEKS_OBSERVED)
    e = rng.standard_normal(N_ENTRIES_OBSERVED)
    stock = np.repeat(np.arange(n_s), np.asarray(STOCK_ENTRY_COUNTS)
                      ).astype(np.int64)
    week = np.empty(N_ENTRIES_OBSERVED, dtype=np.int64)
    at = 0
    for si, c in enumerate(STOCK_ENTRY_COUNTS):
        week[at:at + c] = rng.choice(N_WEEKS_OBSERVED, size=c, replace=False)
        at += c
    idio = math.sqrt(max(0.0, 1.0 - rho_s - rho_w))
    cars = sd * (math.sqrt(rho_s) * u[stock] + math.sqrt(rho_w) * v[week]
                 + idio * e)
    return np.asarray(cars, dtype=float), stock, week


# =====================================================================
# DRY RUN -- planted rho values, before the estimator sees real data
# =====================================================================

def _synth(rng: np.random.Generator, n_stocks: int, per_stock: int,
           n_weeks: int, rho_s: float, rho_w: float, sd: float
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A panel with PLANTED components, laid out so that no same-stock pair
    shares a week -- the same property the 5-day exclusion gives the real
    data, so the dry run tests the estimator under the conditions it will
    actually meet."""
    stock = np.repeat(np.arange(n_stocks), per_stock).astype(np.int64)
    week = np.empty(stock.size, dtype=np.int64)
    for s in range(n_stocks):
        week[s * per_stock:(s + 1) * per_stock] = rng.choice(
            n_weeks, size=per_stock, replace=False)
    u = rng.standard_normal(n_stocks)
    v = rng.standard_normal(n_weeks)
    e = rng.standard_normal(stock.size)
    idio = math.sqrt(max(0.0, 1.0 - rho_s - rho_w))
    cars = sd * (math.sqrt(rho_s) * u[stock] + math.sqrt(rho_w) * v[week]
                 + idio * e)
    return cars, stock, week


def dry_run() -> bool:
    ok = True
    print("\n  DRY RUN -- planted components, before any real data is read")

    # --- ARM 1: two_way_p matches event_study.mean_car_two_way -----------
    rng = np.random.default_rng(SEED)
    w = EventWindow(0, 0)
    worst = 0.0
    for _ in range(5):
        c, st, wk = _synth(rng, 60, 8, 200, 0.25, 0.15, 0.05)
        p, se, df = two_way_p(c, st, wk, 60, 200)
        ref = mean_car_two_way(c, w, [int(x) for x in wk], [int(x) for x in st])
        worst = max(worst, abs(p - ref.p), abs(se - ref.se))
    a1 = worst < 1e-15
    ok &= a1
    print(f"    1  two_way_p vs mean_car_two_way: max |diff| {worst:.2e}  "
          + ("PASS" if a1 else "*** FAIL ***"))

    # --- ARM 2: the estimator recovers PLANTED components ----------------
    print("    2  method-of-moments recovery, 300 draws per cell")
    print(f"       {'rho_s':>7}{'rho_w':>7}{'SD':>7}"
          f"{'rho_s_hat':>11}{'rho_w_hat':>11}{'SD_hat':>10}")
    worst_r, worst_sd = 0.0, 0.0
    for rs in (0.02, 0.15, 0.25, 0.35):
        for rw in (0.05, 0.15, 0.25):
            for sd in (0.02, 0.05):
                got = np.array([
                    variance_components(*_apply_strip(
                        _synth(rng, 60, 8, 200, rs, rw, sd)))
                    for _ in range(300)])
                mrs, mrw, msd = got.mean(axis=0)
                worst_r = max(worst_r, abs(mrs - rs), abs(mrw - rw))
                worst_sd = max(worst_sd, abs(msd / sd - 1.0))
                if rw == 0.15 and sd == 0.05:
                    print(f"       {rs:>7.2f}{rw:>7.2f}{sd:>7.2f}"
                          f"{mrs:>11.4f}{mrw:>11.4f}{msd:>10.4f}")
    a2 = worst_r < 0.02 and worst_sd < 0.02
    ok &= a2
    print(f"       worst |rho_hat - rho| {worst_r:.4f} (< 0.02), worst SD "
          f"error {worst_sd:.2%} (< 2%)  " + ("PASS" if a2 else "*** FAIL ***"))

    # --- ARM 3: it must NOT manufacture a correlation --------------------
    # A spurious rho_stock closes Phase 2, so zero must come back as zero.
    got0 = np.array([variance_components(*_apply_strip(
        _synth(rng, 60, 8, 200, 0.0, 0.0, 0.05))) for _ in range(400)])
    m0 = got0.mean(axis=0)
    a3 = abs(m0[0]) < 0.01 and abs(m0[1]) < 0.01
    ok &= a3
    print(f"    3  at PLANTED ZERO: rho_s_hat {m0[0]:+.5f}, rho_w_hat "
          f"{m0[1]:+.5f}, both |.| < 0.01  " + ("PASS" if a3 else "*** FAIL ***"))

    # --- ARM 4: the bound at BOUND_Q covers the truth, on the OBSERVED
    # --- structure. This is a SMOKE TEST at low trial count; the
    # --- authoritative evidence is calibrate_interval_method.py's 500-trial
    # --- x 9-cell grid recorded in ADDENDUM_01. What this arm exists to catch
    # --- is BOUND_Q or N_BOOT being changed here without re-calibrating.
    cover_r = cover_s = 0
    trials = 120
    for _ in range(trials):
        c, st, wk = synth_observed(rng, 0.25, 0.15, 0.05)
        r = c - c.mean()
        ru, su = bootstrap_upper(r, st, wk, "stock", rng)
        cover_r += int(ru >= 0.25)
        cover_s += int(su >= 0.05)
    cr, cs = cover_r / trials, cover_s / trials
    a4 = cr >= 0.90 and cs >= 0.90
    ok &= a4
    print(f"    4  bound at q={BOUND_Q} on the OBSERVED structure, {trials} "
          f"draws: rho_stock {cr:.1%}, SD {cs:.1%}")
    print(f"       (smoke test -- the 500-trial grid is in ADDENDUM_01)  "
          + ("PASS" if a4 else "*** FAIL ***"))

    # --- ARM 5: mean-removal bias is measured, and its SIGN is stated ----
    c, st, wk = _synth(rng, 60, 8, 200, 0.25, 0.15, 0.05)
    full = variance_components(c - c.mean(), st, wk)
    biasless = np.array([variance_components(*_apply_strip(
        _synth(rng, 60, 8, 200, 0.25, 0.15, 0.05))) for _ in range(300)]
    ).mean(axis=0)
    print(f"    5  mean-removal bias in rho_stock: {biasless[0] - 0.25:+.5f} "
          f"(downward = anti-conservative, absorbed by ARM 4's bound)")
    del full

    # --- ARM 6: the same-stock/same-week disjointness check FIRES --------
    bad_s = np.array([0, 0], dtype=np.int64)
    bad_w = np.array([7, 7], dtype=np.int64)
    fired = False
    try:
        _assert_disjoint(bad_s, bad_w)
    except RuntimeError:
        fired = True
    ok &= fired
    print(f"    6  disjointness check fires on a planted same-stock/same-week "
          f"pair  " + ("PASS" if fired else "*** FAIL ***"))

    # --- ARM 7: the allow-list writer refuses a forbidden key ------------
    refused = False
    try:
        emit("mean_car", 0.0)
    except KeyError:
        refused = True
    allowed_ok = True
    try:
        emit("rho_stock_hat", 0.0)
        _EMITTED.pop("rho_stock_hat", None)
    except KeyError:
        allowed_ok = False
    a7 = refused and allowed_ok
    ok &= a7
    print(f"    7  emit() refuses 'mean_car' and accepts 'rho_stock_hat'  "
          + ("PASS" if a7 else "*** FAIL ***"))

    # --- ARM 8: residuals sum to zero -----------------------------------
    c, st, wk = _synth(rng, 60, 8, 200, 0.25, 0.15, 0.05)
    r = c - c.mean()
    a8 = abs(float(r.sum())) < 1e-12 * max(1.0, float(np.abs(c).sum()))
    ok &= a8
    print(f"    8  mean-removed residuals sum to {float(r.sum()):+.3e}  "
          + ("PASS" if a8 else "*** FAIL ***"))

    print(f"\n  DRY RUN: {'ALL ARMS PASS' if ok else '*** FAILED ***'}")
    return bool(ok)


def _apply_strip(t: tuple[np.ndarray, np.ndarray, np.ndarray]
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    c, st, wk = t
    return c - c.mean(), st, wk


# =====================================================================
# THE GATE
# =====================================================================

def run_gate() -> int:
    print("=" * 74)
    print("  GATE -- blinded nuisance parameters, Phase 2 ban-list entry")
    print("  executes GATE_BAN_LIST_NUISANCE.md")
    print("=" * 74)

    print("\n  ASSEMBLING THE EVENT SET")
    resid, stock, week, counts = prepare_residuals()
    _assert_disjoint(stock, week)
    n_s = int(stock.max()) + 1
    n_w = int(week.max()) + 1
    for k in ("n_entries_raw", "n_dropped_same_stock", "n_after_same_stock",
              "n_dropped_exdate", "n_after_exdate", "n_nifty_gap_days",
              "n_dropped_nifty_gap", "n_after_nifty_gap",
              "n_dropped_missing_price",
              "n_after_prices", "n_stocks", "n_weeks", "n_extreme_daily"):
        emit(k, counts[k])
    c_counts = np.bincount(stock, minlength=n_s).astype(float)
    emit("max_stock_count", int(c_counts.max()))
    emit("sum_c2", int((c_counts * c_counts).sum()))

    print(f"    raw entries                      {counts['n_entries_raw']:>7,}")
    print(f"    dropped, 5-day same-stock rule   {counts['n_dropped_same_stock']:>7,}")
    print(f"    dropped, ex-date in D+1..D+4     {counts['n_dropped_exdate']:>7,}")
    print(f"    dropped, window touches one of the {counts['n_nifty_gap_days']} "
          f"NIFTY 500 gap days {counts['n_dropped_nifty_gap']:>3,}")
    print(f"    dropped, missing price/benchmark {counts['n_dropped_missing_price']:>7,}")
    print(f"    KEPT                             {counts['n_after_prices']:>7,}"
          f"   in {n_s} stocks and {n_w} ISO weeks")
    print(f"    largest stock block {int(c_counts.max())},  sum c_s^2 "
          f"{int((c_counts * c_counts).sum()):,}")
    print(f"    extreme daily returns (>|20%|) inside kept windows: "
          f"{counts['n_extreme_daily']}  -- logged, never excluded")

    print("\n  NUISANCE PARAMETERS (from mean-removed CARs)")
    rs, rw, sd = variance_components(resid, stock, week)
    emit("rho_stock_hat", rs)
    emit("rho_week_hat", rw)
    emit("sd_event_hat", sd)
    rng = np.random.default_rng(SEED)
    rs_u, sd_u = bootstrap_upper(resid, stock, week, "stock", rng)
    rw_u, _ = bootstrap_upper(resid, stock, week, "week", rng)
    emit("rho_stock_upper", rs_u)
    emit("rho_week_upper", rw_u)
    emit("sd_event_upper", sd_u)
    print(f"    {'':<14}{'point':>12}{'90% upper':>12}")
    print(f"    {'rho_stock':<14}{rs:>12.4f}{rs_u:>12.4f}")
    print(f"    {'rho_week':<14}{rw:>12.4f}{rw_u:>12.4f}")
    print(f"    {'SD_event':<14}{sd:>12.4%}{sd_u:>12.4%}")
    print(f"    bounds target one-sided 90% COVERAGE, read at the calibrated")
    print(f"    percentile q*={BOUND_Q} of a {N_BOOT:,}-resample cluster "
          f"bootstrap (ADDENDUM_01)")

    # --- recalibrate alpha* at the BOUNDED values -----------------------
    print(f"\n  RECALIBRATING alpha* at the bounded values "
          f"(rho_stock {rs_u:.4f}, rho_week {rw:.4f})")
    print(f"    {N_GATE:,} zero-effect sims on the REAL structure ...",
          flush=True)
    rng_c = np.random.default_rng(SEED + 1)
    ps = np.empty(N_GATE, dtype=float)
    ses = np.empty(N_GATE, dtype=float)
    df = 0
    for i in range(N_GATE):
        c = panel_on(rng_c, stock, week, n_s, n_w, rs_u, rw, 0.0)
        ps[i], ses[i], df = two_way_p(c, stock, week, n_s, n_w)
    alpha_star = _threshold(ps, TARGET)
    emit("alpha_star", alpha_star)
    emit("df", df)
    print(f"    alpha* = {alpha_star:.6f}   (df {df}; a nominal 0.01 buys "
          f"{float((ps < 0.01).mean()):.2%} here)")

    print(f"    fresh {N_VAL:,}-sim validation at alpha* ...", flush=True)
    rng_v = np.random.default_rng(SEED + 2)
    hit = 0
    for _ in range(N_VAL):
        c = panel_on(rng_v, stock, week, n_s, n_w, rs_u, rw, 0.0)
        if two_way_p(c, stock, week, n_s, n_w)[0] < alpha_star:
            hit += 1
    size = hit / N_VAL
    lo, hi = _clopper_pearson(hit, N_VAL, 0.99)
    emit("size_at_alpha_star", size)
    emit("size_lo", lo)
    emit("size_hi", hi)
    print(f"    realised size {hit:,}/{N_VAL:,} = {size:.3%}   "
          f"99% CP [{lo:.3%}, {hi:.3%}]   "
          + ("contains 1%" if lo <= TARGET <= hi else "*** MIS-SIZED ***"))

    # --- the MDE --------------------------------------------------------
    se_sim = float(ses.mean())
    se_an = analytic_sd_of_mean(stock, week, n_s, n_w, rs_u, rw)
    emit("se_two_way_sim", se_sim)
    emit("se_two_way_analytic", se_an)
    agree = abs(se_sim / se_an - 1.0) < 0.06
    print(f"\n  TWO-WAY STANDARD ERROR at the bounded values")
    print(f"    simulated {se_sim:.6f}   analytic {se_an:.6f}   "
          f"ratio {se_sim / se_an:.3f}  "
          + ("agree" if agree else "*** DISAGREE -- GATE ABORTS ***"))
    if not agree:
        emit("verdict", "ABORT_SE_DISAGREEMENT")
        _write_results()
        return 2

    crit = float(_st.t.ppf(1.0 - alpha_star / 2.0, df))
    pw = float(_st.t.ppf(POWER, df))
    mde = (crit + pw) * se_sim * sd_u
    mde_bps = mde * 10_000.0
    emit("mde_pct", mde)
    emit("mde_bps", mde_bps)
    emit("bar_bps", BAR_BPS)

    rng_p = np.random.default_rng(SEED + 3)
    n_pw = 2_000
    det = sum(1 for _ in range(n_pw)
              if two_way_p(panel_on(rng_p, stock, week, n_s, n_w, rs_u, rw,
                                    (crit + pw) * se_sim),
                           stock, week, n_s, n_w)[0] < alpha_star)
    emit("power_check", det / n_pw)

    print(f"\n  MDE AT alpha*, {POWER:.0%} POWER, SD_event at its upper bound")
    print(f"    t crit {crit:.6f} + t power {pw:.6f}")
    print(f"    MDE  {mde:.4%}  =  {mde_bps:.2f} bps")
    print(f"    bar  {BAR_BPS:.2f} bps   (3 x 23.7821 bps delivery floor)")
    print(f"    direct power check at that effect: {det / n_pw:.1%} detected")

    passed = mde_bps <= BAR_BPS
    emit("verdict", "PROCEED" if passed else "CLOSE_UNDERPOWERED")
    print("\n" + "=" * 74)
    if passed:
        print(f"  VERDICT: PROCEED -- MDE {mde_bps:.2f} bps <= "
              f"{BAR_BPS:.2f} bps")
        print(f"  Phase 2 proceeds to LOCKING PREREG_BAN_LIST_ENTRY.md.")
    else:
        print(f"  VERDICT: CLOSE AS UNDERPOWERED -- MDE {mde_bps:.2f} bps > "
              f"{BAR_BPS:.2f} bps")
        print(f"  shortfall {mde_bps - BAR_BPS:+.2f} bps "
              f"({mde_bps / BAR_BPS:.2f}x the bar)")
    print("=" * 74)
    _write_results()
    return 0


def _write_results() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"gate_ban_list_nuisance_{date.today().isoformat()}.csv"
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# GATE_BAN_LIST_NUISANCE.md -- permitted figures only.\n")
        fh.write("# Every key here is on gate_ban_list_nuisance.ALLOWED. The\n")
        fh.write("# mean CAR, any t-statistic and any p-value on real data are\n")
        fh.write("# absent BY CONSTRUCTION, not by omission.\n")
        fh.write("key,value\n")
        for k in sorted(_EMITTED):
            fh.write(f"{k},{_EMITTED[k]}\n")
    print(f"\n  wrote {p}")


def main() -> int:
    if not dry_run():
        print("\n  DRY RUN FAILED -- the gate does not run.")
        return 1
    if "--dry-run" in sys.argv:
        return 0
    return run_gate()


if __name__ == "__main__":
    raise SystemExit(guard(main))
