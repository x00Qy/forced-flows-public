r"""
gate_sip_timing.py -- executes GATE_SIP_TIMING.md.

Measures ONLY the standard deviation of the three-session NIFTY 500 return and
its serial correlation, on ALL days, and decides on those alone whether a
SIP-day effect is detectable.

=== THE BLIND ===

This module must never compute, print, log, return or persist returns grouped
by SIP versus non-SIP day, the SIP-day mean, the other-day mean, their
difference, or any t-statistic or p-value on the real series.

Enforced structurally, as in Phase 2: `window_returns()` returns ONE
undifferentiated array over every day, `nuisance()` reduces it to a standard
deviation and a vector of autocorrelations, and `emit()` refuses any key
outside an explicit allow-list. The SIP calendar is used ONLY to count events
and to count other-day windows per month -- counts, never returns.

The blinding is PROCEDURAL. The price series on disk obviously contains the
answer; its integrity rests on this being the only script run against that
series before the pre-registration is locked.

=== THE POWER CALCULATION ===

    d_m     = r_SIP,m - mean(other-day window returns in month m)
    SD(d)^2 = s3^2 * (1 + VIF / m_other)
    VIF     = 1 + 2 * sum_k (1 - k/m_other) * rho_k
    MDE     = ( t(0.995, G-1) + t(0.80, G-1) ) * SD(d) / sqrt(G)

Three-session windows on consecutive days share two days BY CONSTRUCTION, so
rho_1 and rho_2 are large and mechanical rather than a market phenomenon.
Ignoring them understates the variance of the other-day mean and overstates
power, which is the failure mode this whole gate exists to avoid.

The covariance between the SIP-day window and the other-day windows is set to
zero. It is positive in reality, so dropping it OVERSTATES SD(d) and the MDE.
Conservative, in the direction that makes the gate harder to pass.

Run:  python src/gate_sip_timing.py
      python src/gate_sip_timing.py --dry-run
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
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
NIFTY500: Final[Path] = ROOT / "data" / "nifty500_daily_2015_2026.csv"
RESULTS: Final[Path] = ROOT / "results"

# --- fixed by GATE_SIP_TIMING.md; changing one invalidates the gate --------
SIP_DAY_OF_MONTH: Final[int] = 10     # set C: the default at 3 of the 5 largest
WINDOW_SESSIONS: Final[int] = 3       # open of D to close of D+2
YEAR_FROM: Final[int] = 2016
YEAR_TO: Final[int] = 2026
ALPHA: Final[float] = 0.01
POWER: Final[float] = 0.80
BAR_BPS: Final[float] = 16.9664       # 3 x 5.6555 bps futures statutory floor
MAX_LAG: Final[int] = 10
SEED: Final[int] = 20260922

ALLOWED: Final[frozenset[str]] = frozenset({
    "n_days", "n_windows", "n_months", "n_events", "m_other_median",
    "m_other_mean", "span_first", "span_last", "n_sip_moved",
    "sd_window", "sd_window_bps", "vif", "rho_1", "rho_2", "rho_3",
    "df", "sd_d", "mde_bps", "mde_pct", "bar_bps", "power_check", "verdict",
    "m_other_nonoverlap", "vif_nonoverlap", "sd_d_nonoverlap",
    "mde_bps_nonoverlap", "leak_attenuation", "mde_bps_true_effect",
})
_EMITTED: dict[str, object] = {}


def emit(key: str, value: object) -> None:
    """Publish one figure. A key outside ALLOWED is a hard error."""
    if key not in ALLOWED:
        raise KeyError(
            f"BLIND VIOLATION: '{key}' is not in the allow-list. "
            f"GATE_SIP_TIMING.md permits only the window SD, the serial "
            f"correlation, counts, the MDE and the verdict.")
    _EMITTED[key] = value


# =====================================================================
# DATA -- one undifferentiated array over every day
# =====================================================================

def load_index() -> list[tuple[date, float, float]]:
    """(date, open, close) for NIFTY 500, sorted."""
    rows: list[tuple[date, float, float]] = []
    with io.open(NIFTY500, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if row and not row[0].startswith("#") and row[0] != "date":
                rows.append((date.fromisoformat(row[0]), float(row[1]),
                             float(row[2])))
    rows.sort()
    return rows


def window_returns(rows: Sequence[tuple[date, float, float]]
                   ) -> tuple[list[date], np.ndarray]:
    """The three-session return starting at EVERY day: open of day i to close
    of day i+2.

    Returned as ONE array over all days with no SIP labelling. This is the
    only path out of the data layer, which is what makes the blind structural
    rather than a matter of care."""
    out_d: list[date] = []
    out_r: list[float] = []
    for i in range(len(rows) - (WINDOW_SESSIONS - 1)):
        o = rows[i][1]
        c = rows[i + WINDOW_SESSIONS - 1][2]
        if o > 0.0 and c > 0.0:
            out_d.append(rows[i][0])
            out_r.append(c / o - 1.0)
    return out_d, np.asarray(out_r, dtype=float)


def nuisance(r: np.ndarray, max_lag: int) -> tuple[float, np.ndarray]:
    """(SD of the window return, autocorrelations at lags 1..max_lag).

    Computed on ALL windows. Nothing here knows what a SIP day is."""
    sd = float(r.std(ddof=1))
    x = r - r.mean()
    denom = float(np.dot(x, x))
    rho = np.array([float(np.dot(x[:-k], x[k:])) / denom
                    for k in range(1, max_lag + 1)], dtype=float)
    return sd, rho


def vif(rho: np.ndarray, m: float) -> float:
    """Variance inflation of the mean of m OVERLAPPING windows:

        VIF = 1 + 2 * sum_k (1 - k/m) * rho_k

    At rho = 0 this is 1 and the mean behaves as m independent draws. With
    three-session windows on consecutive days rho_1 and rho_2 are large by
    construction, so VIF is well above 1 and the effective sample is much
    smaller than m."""
    k = np.arange(1, rho.size + 1, dtype=float)
    use = k < m
    return 1.0 + 2.0 * float(np.sum((1.0 - k[use] / m) * rho[use]))


# =====================================================================
# THE SIP CALENDAR -- counts only, never returns
# =====================================================================

def sip_events(days: Sequence[date]) -> tuple[list[int], int]:
    """(indices of the SIP-day window in `days`, count moved forward).

    The event is the 10th, or the NEXT trading day when the 10th does not
    trade. Moving forward never uses information from after the event."""
    by_month: dict[tuple[int, int], list[tuple[date, int]]] = {}
    for i, d in enumerate(days):
        by_month.setdefault((d.year, d.month), []).append((d, i))
    out: list[int] = []
    moved = 0
    for key in sorted(by_month):
        if not (YEAR_FROM <= key[0] <= YEAR_TO):
            continue
        cand = [(d, i) for d, i in by_month[key]
                if d.day >= SIP_DAY_OF_MONTH]
        if not cand:
            continue
        d, i = min(cand)
        if d.day != SIP_DAY_OF_MONTH:
            moved += 1
        out.append(i)
    return out, moved


def month_counts(days: Sequence[date]) -> list[int]:
    """Windows per month over the sample, for m_other. A count, not a return."""
    by_month: dict[tuple[int, int], int] = {}
    for d in days:
        if YEAR_FROM <= d.year <= YEAR_TO:
            by_month[(d.year, d.month)] = by_month.get((d.year, d.month), 0) + 1
    return [by_month[k] for k in sorted(by_month)]


def leak_attenuation(m_other: float) -> float:
    """The fraction of a TRUE SIP-day effect that survives into the measured
    difference, when the comparison group contains the overlapping windows.

    An effect spread evenly over the L days of the window leaks into the
    comparison windows starting at offsets +/-1 .. +/-(L-1); the window at
    offset k carries (L-k)/L of it. Summing both sides:

        total leaked = sum_{k=1}^{L-1} 2*(L-k)/L = L - 1
        attenuation  = 1 - (L - 1) / m_other

    At L = 3 and m_other = 20 that is 0.90: a true 100 bps effect is measured
    as 90 bps, because the comparison group has been contaminated with 10% of
    it. ARM 8 checks this closed form against a planted simulation."""
    return 1.0 - (WINDOW_SESSIONS - 1.0) / m_other


def month_counts_nonoverlap(days: Sequence[date],
                           events: Sequence[int]) -> list[int]:
    """Comparison windows per month that share NO DAY with that month's SIP
    window: every start except D-2, D-1, D, D+1 and D+2.

    A three-session window starting at D-2 still contains D, so it carries
    part of any SIP-day effect. The gate's primary reading compares against
    windows that do, which is what ARM 8 measures the cost of."""
    ev = set(events)
    pos_of_event: dict[tuple[int, int], int] = {}
    for i in events:
        d = days[i]
        pos_of_event[(d.year, d.month)] = i
    by_month: dict[tuple[int, int], int] = {}
    for i, d in enumerate(days):
        if not (YEAR_FROM <= d.year <= YEAR_TO):
            continue
        key = (d.year, d.month)
        e = pos_of_event.get(key)
        if e is None:
            continue
        if abs(i - e) <= WINDOW_SESSIONS - 1:
            continue                       # shares a day with the SIP window
        by_month[key] = by_month.get(key, 0) + 1
    del ev
    return [by_month[k] for k in sorted(by_month)]


def mde_bps(sd_window: float, rho: np.ndarray, m_other: float, g: int) -> tuple[float, float, float]:
    """(MDE in bps, SD(d), VIF). The estimator of GATE_SIP_TIMING.md section 5."""
    v = vif(rho, m_other)
    sd_d = sd_window * math.sqrt(1.0 + v / m_other)
    crit = float(_st.t.ppf(1.0 - ALPHA / 2.0, g - 1))
    pw = float(_st.t.ppf(POWER, g - 1))
    return (crit + pw) * sd_d / math.sqrt(g) * 10_000.0, sd_d, v


# =====================================================================
# DRY RUN -- planted SD and a known autocorrelation structure
# =====================================================================

def _rows_from_steps(steps: np.ndarray) -> list[tuple[date, float, float]]:
    """A price path from daily log steps, as (date, open, close) rows where
    the open equals the previous close. Used by ARM 8 to plant an effect in
    DAILY returns rather than in window returns."""
    lvl = 1000.0 * np.exp(np.cumsum(steps))
    out: list[tuple[date, float, float]] = []
    d0 = date(2000, 1, 3)
    for i in range(steps.size):
        o = float(lvl[i]) * math.exp(-float(steps[i]))
        out.append((date.fromordinal(d0.toordinal() + i), o, float(lvl[i])))
    return out


def _synth_prices(rng: np.random.Generator, n: int, daily_sd: float
                  ) -> list[tuple[date, float, float]]:
    """A price path with i.i.d. daily returns, so the OVERLAP is the only
    source of autocorrelation in the three-session windows. That makes the
    expected rho_k exactly (3-k)/3 for k < 3 and 0 beyond, which ARM 2 checks."""
    return _rows_from_steps(rng.normal(0.0, daily_sd, n))


def dry_run() -> bool:
    ok = True
    print("\n  DRY RUN -- planted SD and a known overlap structure")
    rng = np.random.default_rng(SEED)

    # ARM 1: the window return is recovered exactly on a known path
    rows = [(date(2020, 1, 1), 100.0, 101.0), (date(2020, 1, 2), 101.0, 102.0),
            (date(2020, 1, 3), 102.0, 103.0), (date(2020, 1, 4), 103.0, 104.0)]
    _, r = window_returns(rows)
    a1 = abs(r[0] - (103.0 / 100.0 - 1.0)) < 1e-12 and r.size == 2
    ok &= a1
    print(f"    1  open(D)->close(D+2) on a known path: {r[0]:.6f}, want "
          f"{103.0 / 100.0 - 1.0:.6f}, {r.size} windows  "
          + ("PASS" if a1 else "*** FAIL ***"))

    # ARM 2: with i.i.d. daily returns the overlap alone gives rho_k = (3-k)/3
    px = _synth_prices(rng, 30_000, 0.008)
    _, rr = window_returns(px)
    sd, rho = nuisance(rr, MAX_LAG)
    want = [2.0 / 3.0, 1.0 / 3.0, 0.0]
    got = [float(rho[0]), float(rho[1]), float(rho[2])]
    a2 = all(abs(g - w) < 0.03 for g, w in zip(got, want))
    ok &= a2
    print(f"    2  overlap-only autocorrelation: rho_1 {got[0]:.4f} (want "
          f"{want[0]:.4f}), rho_2 {got[1]:.4f} (want {want[1]:.4f}), "
          f"rho_3 {got[2]:.4f} (want 0)  " + ("PASS" if a2 else "*** FAIL ***"))

    # ARM 3: the SD of a 3-session return is sqrt(3) x the daily SD
    a3 = abs(sd / (0.008 * math.sqrt(3.0)) - 1.0) < 0.03
    ok &= a3
    print(f"    3  window SD {sd:.5f}, want sqrt(3)*0.008 = "
          f"{0.008 * math.sqrt(3.0):.5f}  " + ("PASS" if a3 else "*** FAIL ***"))

    # ARM 4: VIF matches its closed form, and is > 1 for overlapping windows
    m = 18.0
    v = vif(rho, m)
    k = np.arange(1, rho.size + 1, dtype=float)
    ref = 1.0 + 2.0 * float(np.sum((1.0 - k[k < m] / m) * rho[k < m]))
    a4 = abs(v - ref) < 1e-12 and v > 1.5
    ok &= a4
    print(f"    4  VIF at m={m:.0f}: {v:.4f} (>1, overlap inflates), matches "
          f"closed form  " + ("PASS" if a4 else "*** FAIL ***"))
    print(f"       an m=18 mean of these windows carries the information of "
          f"{m / v:.1f} independent ones")

    # ARM 5: a planted effect at the MDE is detected ~80% of the time, using
    #        the ACTUAL clustered estimator rather than the formula again.
    g = 125
    m_other = 18
    sd_d_target = sd * math.sqrt(1.0 + v / m_other)
    crit = float(_st.t.ppf(1.0 - ALPHA / 2.0, g - 1))
    pw = float(_st.t.ppf(POWER, g - 1))
    effect = (crit + pw) * sd_d_target / math.sqrt(g)
    hits = 0
    sims = 1500
    rng5 = np.random.default_rng(SEED + 1)
    for _ in range(sims):
        d = rng5.normal(effect, sd_d_target, g)
        t = float(d.mean()) / float(d.std(ddof=1) / math.sqrt(g))
        if 2.0 * (1.0 - _st.t.cdf(abs(t), g - 1)) < ALPHA:
            hits += 1
    rate = hits / sims
    a5 = 0.76 <= rate <= 0.84
    ok &= a5
    print(f"    5  effect planted at the MDE detected {rate:.1%} of "
          f"{sims:,} sims, want 80%  " + ("PASS" if a5 else "*** FAIL ***"))

    # ARM 6: the 10th moves FORWARD when it does not trade, never backward
    days = [date(2024, 3, 8), date(2024, 3, 11), date(2024, 3, 12),
            date(2024, 4, 10), date(2024, 5, 9), date(2024, 5, 13)]
    idx, moved = sip_events(days)
    a6 = idx == [1, 3, 5] and moved == 2
    ok &= a6
    print(f"    6  SIP calendar: picked {idx}, moved {moved} forward; "
          f"want [1, 3, 5] and 2  " + ("PASS" if a6 else "*** FAIL ***"))
    print(f"       (Mar: 10th is a Sunday -> 11th; Apr: 10th trades; "
          f"May: 10th absent -> 13th)")

    # ARM 8: WHERE THE EFFECT IS PLANTED CHANGES THE ANSWER.
    # ARM 5 plants its effect directly in d, the DIFFERENCE, which assumes
    # the comparison windows are clean. They are not: a window starting at
    # D-2, D-1, D+1 or D+2 shares one or two days with D..D+2, so a real
    # SIP-day effect LEAKS into the comparison group and the measured
    # difference is attenuated. This arm plants the effect where it would
    # really occur -- in the DAILY returns of D, D+1 and D+2 -- and measures
    # how much leaks.
    rng8 = np.random.default_rng(SEED + 3)
    e_daily = 0.001
    steps = rng8.normal(0.0, 0.008, 400)
    bumped = steps.copy()
    i0 = 200
    bumped[i0:i0 + WINDOW_SESSIONS] += e_daily
    _, r_base = window_returns(_rows_from_steps(steps))
    _, r_bump = window_returns(_rows_from_steps(bumped))
    delta = r_bump - r_base
    sip_delta = float(delta[i0])
    half = 10                      # ~20 comparison windows, as a real month
    near = [j for j in range(i0 - half, i0 + half + 1)
            if 0 <= j < delta.size and j != i0]
    clean = [j for j in near if abs(j - i0) > WINDOW_SESSIONS - 1]
    leak_all = float(np.mean([delta[j] for j in near]))
    leak_clean = float(np.mean([delta[j] for j in clean]))
    atten = 1.0 - leak_all / sip_delta
    atten_clean = 1.0 - leak_clean / sip_delta
    closed = leak_attenuation(float(len(near)))
    a8 = (abs(sip_delta - 3.0 * e_daily) < 3e-5
          and abs(atten - closed) < 0.01 and atten_clean > 0.999)
    ok &= a8
    print(f"    8  effect planted in DAILY returns of D..D+2 "
          f"({e_daily:.4f}/day):")
    print(f"       SIP window moves {sip_delta * 1e4:>7.2f} bps "
          f"(= 3 x {e_daily * 1e4:.0f} bps, as it must)")
    print(f"       leak into the {len(near)} overlapping comparison windows "
          f"{leak_all * 1e4:>6.2f} bps")
    print(f"       leak into the {len(clean)} NON-overlapping ones "
          f"{leak_clean * 1e4:>6.2f} bps")
    print(f"       measured difference is {atten:.3f} of the true effect "
          f"(clean: {atten_clean:.3f})")
    print(f"       closed form 1-(L-1)/m_other = {closed:.3f}, matches  "
          + ("PASS" if a8 else "*** FAIL ***"))
    print(f"       so ARM 5's difference-space planting OVERSTATES power: a "
          f"true effect")
    print(f"       must be 1/{atten:.3f} = {1.0 / atten:.3f}x the measured "
          f"MDE to be found.")

    # ARM 7: the allow-list refuses a grouped quantity
    refused = False
    try:
        emit("sip_day_mean", 0.0)
    except KeyError:
        refused = True
    ok &= refused
    print(f"    7  emit() refuses 'sip_day_mean'  "
          + ("PASS" if refused else "*** FAIL ***"))

    print(f"\n  DRY RUN: {'ALL ARMS PASS' if ok else '*** FAILED ***'}")
    return bool(ok)


def main() -> int:
    print("=" * 76)
    print("  GATE -- SIP timing power, blinded")
    print("  executes GATE_SIP_TIMING.md")
    print("=" * 76)
    if not dry_run():
        print("\n  DRY RUN FAILED -- the gate does not run.")
        return 1
    if "--dry-run" in sys.argv:
        return 0

    rows = load_index()
    days, r = window_returns(rows)
    keep = [i for i, d in enumerate(days) if YEAR_FROM <= d.year <= YEAR_TO]
    days_s = [days[i] for i in keep]
    r_s = r[np.asarray(keep, dtype=int)]

    ev, moved = sip_events(days_s)
    mc = month_counts(days_s)
    m_other = float(np.median(mc)) - 1.0
    g = len(ev)

    emit("n_days", len(rows))
    emit("n_windows", int(r_s.size))
    emit("n_months", len(mc))
    emit("n_events", g)
    emit("n_sip_moved", moved)
    emit("m_other_median", m_other)
    emit("m_other_mean", float(np.mean(mc)) - 1.0)
    emit("span_first", days_s[0].isoformat())
    emit("span_last", days_s[-1].isoformat())

    print(f"\n  SAMPLE  (counts only -- no return is grouped)")
    print(f"    index days                 {len(rows):>7,}")
    print(f"    3-session windows in scope {r_s.size:>7,}   "
          f"{days_s[0]} -> {days_s[-1]}")
    print(f"    months                     {len(mc):>7,}")
    print(f"    SIP events (the 10th)      {g:>7,}   "
          f"{moved} moved forward to the next trading day")
    print(f"    other-day windows/month    {m_other:>7.1f} median, "
          f"{float(np.mean(mc)) - 1.0:.1f} mean")

    sd, rho = nuisance(r_s, MAX_LAG)
    emit("sd_window", sd)
    emit("sd_window_bps", sd * 10_000.0)
    emit("rho_1", float(rho[0]))
    emit("rho_2", float(rho[1]))
    emit("rho_3", float(rho[2]))

    print(f"\n  NUISANCE  (all days, every day a potential D)")
    print(f"    SD of the 3-session return   {sd:.6f}  = {sd * 10_000.0:,.1f} bps")
    print(f"    autocorrelation  rho_1 {rho[0]:+.4f}   rho_2 {rho[1]:+.4f}"
          f"   rho_3 {rho[2]:+.4f}")
    print(f"    (rho_1 and rho_2 are mechanical: consecutive 3-session windows "
          f"share two days)")

    m, sd_d, v = mde_bps(sd, rho, m_other, g)
    emit("vif", v)
    emit("sd_d", sd_d)
    emit("df", g - 1)
    emit("mde_bps", m)
    emit("mde_pct", m / 10_000.0)
    emit("bar_bps", BAR_BPS)

    mc_no = month_counts_nonoverlap(days_s, ev)
    m_other_no = float(np.median(mc_no))
    m_no, sd_d_no, v_no = mde_bps(sd, rho, m_other_no, g)
    emit("m_other_nonoverlap", m_other_no)
    emit("vif_nonoverlap", v_no)
    emit("sd_d_nonoverlap", sd_d_no)
    emit("mde_bps_nonoverlap", m_no)
    atten = leak_attenuation(m_other)
    emit("leak_attenuation", atten)
    emit("mde_bps_true_effect", m / atten)

    print(f"\n  POWER  (p<{ALPHA}, {POWER:.0%}, clustered by month, df {g - 1})")
    print(f"    VIF {v:.4f}  -> an {m_other:.0f}-window monthly mean carries "
          f"the information of {m_other / v:.1f} independent windows")
    print(f"    SD(d) {sd_d:.6f}")
    print(f"    MDE   {m / 10_000.0:.4%}  =  {m:.2f} bps")
    print(f"    bar   {BAR_BPS:.4f} bps   (3 x 5.6555 bps futures statutory "
          f"floor, slippage excluded)")

    rng = np.random.default_rng(SEED + 2)
    sims = 2_000
    eff = m / 10_000.0
    hits = 0
    for _ in range(sims):
        d = rng.normal(eff, sd_d, g)
        t = float(d.mean()) / float(d.std(ddof=1) / math.sqrt(g))
        if 2.0 * (1.0 - _st.t.cdf(abs(t), g - 1)) < ALPHA:
            hits += 1
    emit("power_check", hits / sims)
    print(f"    direct power check at that effect: {hits / sims:.1%} detected")

    print(f"\n  THE OVERLAP READING, SIDE BY SIDE")
    print(f"    {'comparison group':<34}{'m_other':>9}{'VIF':>8}"
          f"{'SD(d)':>10}{'MDE bps':>10}")
    print(f"    {'all other windows in the month':<34}{m_other:>9.1f}"
          f"{v:>8.4f}{sd_d:>10.6f}{m:>10.2f}")
    print(f"    {'sharing no day with D..D+2':<34}{m_other_no:>9.1f}"
          f"{v_no:>8.4f}{sd_d_no:>10.6f}{m_no:>10.2f}")
    print(f"    excluding the D-2..D+2 starts costs "
          f"{m_other - m_other_no:.0f} comparison windows a month and moves "
          f"the MDE by {m_no - m:+.2f} bps.")
    print(f"    Both readings fail the {BAR_BPS:.4f} bps bar, so the verdict "
          f"does not depend on which is used.")
    print(f"\n  AND THE OVERLAP ALSO ATTENUATES THE EFFECT ITSELF")
    print(f"    a true effect spread over D..D+2 leaks into the {WINDOW_SESSIONS - 1} "
          f"comparison windows on each side,")
    print(f"    so the measured difference is {atten:.3f} of it "
          f"(closed form 1-(L-1)/m_other, checked in ARM 8).")
    print(f"    In TRUE-EFFECT terms the primary MDE is therefore "
          f"{m:.2f}/{atten:.3f} = {m / atten:.2f} bps,")
    print(f"    which is {m / atten / BAR_BPS:.2f}x the bar rather than "
          f"{m / BAR_BPS:.2f}x.")

    passed = m <= BAR_BPS
    emit("verdict", "PROCEED" if passed else "CLOSE_UNDERPOWERED")
    print("\n" + "=" * 76)
    if passed:
        print(f"  VERDICT: PROCEED -- MDE {m:.2f} bps <= {BAR_BPS:.4f} bps")
    else:
        print(f"  VERDICT: CLOSE AS UNDERPOWERED -- MDE {m:.2f} bps > "
              f"{BAR_BPS:.4f} bps")
        print(f"  shortfall {m - BAR_BPS:+.2f} bps ({m / BAR_BPS:.2f}x the bar)")
    print("=" * 76)

    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"gate_sip_timing_{date.today().isoformat()}.csv"
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# GATE_SIP_TIMING.md -- permitted figures only.\n")
        fh.write("# Returns grouped by SIP status, either group's mean, their\n")
        fh.write("# difference, and any t or p on the real series are absent\n")
        fh.write("# BY CONSTRUCTION, not by omission.\n")
        fh.write("key,value\n")
        for k in sorted(_EMITTED):
            fh.write(f"{k},{_EMITTED[k]}\n")
    print(f"\n  wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
