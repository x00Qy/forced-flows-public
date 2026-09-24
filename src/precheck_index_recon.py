r"""
precheck_index_recon.py -- Phase 1 feasibility, implementing PRECHECK_INDEX_RECON.md
as locked. FEASIBILITY ONLY: no price data, no returns, no event study is run.

KILL CONDITION, from the pre-registration committed before this file existed:

    Phase 1 closes if no index set, individually or pooled, has a clustered MDE
    (p<0.01 two-sided, 80% power, t with G-1 df) at or below 3x the delivery
    floor at Rs 1 lakh notional, under the middle SD and intra-cluster
    correlation assumptions -- the (SD 8%, rho 0.2) cell.

WHY THIS IS ARITHMETIC. Nothing here measures an effect. It asks only whether a
test COULD detect one the size that would matter, which is answerable from the
event count, the clustering structure and the cost floor alone.

=== THE INVENTORY, AND EXACTLY WHAT IS AND IS NOT SOURCED ===

SOURCED, from niftyindices.com press-release archive, fetched 2026-09-21, and
PERSISTED to data/nse_index_recon_announcements_2026-09-21.csv. Every inventory
figure below is DERIVED from that file at run time and checked against what was
recorded at the fetch; a mismatch stops the run.
  243 equity constituent-change announcements, 2017-03-07 to 2026-09-15.
  124 of them NAME a different index in the title (Nifty SME Emerge, Nifty IPO,
      India FPI 150, Smallcap 500, ESG, CPSE, Shariah) and cannot touch the
      three indices in scope, so they are excluded.
  119 remaining releases fall on 110 DISTINCT ANNOUNCEMENT DATES. Those 110 are
      the pool from which NIFTY 50, NIFTY Next 50 and NIFTY Midcap 150 dates
      are drawn.

NOT SOURCED, and not guessed:
  WHICH of the three indices each announcement touches, and HOW MANY stocks it
  adds. Those live in the body of 243 individual PDFs, and parsing them is a
  data-engineering task that was not done here. So there is no per-index event
  count and no measured events-per-cluster.

  Pre-2017 history is also absent: the archive reaches back to 1998, but the
  title conventions before 2017-03 do not match the extraction rule above, so
  nothing is claimed for those years.

HOW THE GAP IS HANDLED, and why it does not weaken the verdict. G enters the
MDE as 1/sqrt(G), so OVERSTATING G overstates power. This script therefore uses
110 -- every candidate date -- as a GENEROUS UPPER BOUND for every index set,
including each index individually. No individual index can have more than 110,
and the pooled set cannot either, because pooled dates are a subset of the same
110 and not the sum of three disjoint calendars. If the verdict is UNDERPOWERED
at that bound it is UNDERPOWERED at the true G, whatever the split turns out to
be. A POWERED result at the bound would NOT be conclusive and would require the
PDFs parsed first; the output says so.

=== WHAT WOULD MAKE THIS WRONG ===

  THE SD AND RHO VALUES ARE ASSUMPTIONS, not measurements -- measuring them
  needs the price data this pre-check exists to avoid loading. The grid exists
  so the sensitivity is visible instead of hidden in a point estimate.
  EVENTS PER CLUSTER is assumed too, for the same reason.
  THE EXTRACTION RULE IS A TITLE REGEX. An announcement whose title does not
  match "replacement"/"constituent change" is missed, and one that names no
  index is kept even if it touched none of the three. The first understates G,
  the second overstates it; the second is the generous direction and is the one
  retained deliberately.

Run:  python src/precheck_index_recon.py
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

import numpy as np
from scipy import stats as _st  # type: ignore[import-untyped]

from event_study import EventWindow, car_per_event, market_adjusted_ar, mean_car
from require_data import guard
from require_yalgo_core import round_trip_cost_bps

SCRIPT: Final[str] = "precheck_index_recon.py"
RUN_TS: Final[str] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# --- locked by PRECHECK_INDEX_RECON.md -------------------------------
ALPHA: Final[float] = 0.01
POWER: Final[float] = 0.80
COVERAGE: Final[float] = 3.0
NOTIONAL_RUPEES: Final[float] = 100_000.0        # Rs 1 lakh, stated not defaulted
SD_GRID: Final[tuple[float, ...]] = (0.05, 0.08, 0.12)
RHO_GRID: Final[tuple[float, ...]] = (0.0, 0.2, 0.4)
DECISIVE: Final[tuple[float, float]] = (0.08, 0.2)
EVENTS_PER_CLUSTER: Final[float] = 5.0           # assumed; see the docstring

# --- the sourced inventory -------------------------------------------
# niftyindices.com press-release archive, fetched 2026-09-21 by DOM extraction
# over /Press_Release/ind_prsDDMMYYYY.pdf links. Title rule, verbatim:
#   keep   /replacement|change in (the )?index constituent|constituent change/i
#   drop   /fixed income|g-sec|gsec|bond|sdl|money market|t-bill|cd index|
#           cp index|launch/i
#   drop   /sme emerge|nifty ipo|fpi 150|smallcap 500|esg indices|cpse|
#           shariah|india fpi/i   (names a different index)
INVENTORY_SOURCE: Final[str] = ("niftyindices.com press-release archive, "
                                "DOM extraction, fetched 2026-09-21")
INVENTORY_FILE: Final[str] = "data/nse_index_recon_announcements_2026-09-21.csv"

# EXPECTED values, recorded at the fetch. The inventory is DERIVED from the
# persisted file on every run and checked against these; a mismatch means the
# file moved under the figures and the run stops rather than quietly reporting
# different numbers under the same pre-registration.
EXPECT_TOTAL: Final[int] = 243
EXPECT_OTHER: Final[int] = 124
EXPECT_CANDIDATES: Final[int] = 119
EXPECT_DATES: Final[int] = 110


@dataclass(frozen=True)
class Inventory:
    total: int
    named_other: int
    candidates: int
    distinct_dates: int
    span: tuple[str, str]
    per_year: tuple[tuple[int, int, int], ...]


def load_inventory(path: Path) -> Inventory:
    """Derive every inventory figure from the persisted CSV.

    The file is the sourced artifact; nothing here is hardcoded except the
    expectations it is checked against. A figure from a live page is not
    reproducible unless its input is on disk -- the same rule that put
    data/daily_closes_nifty_banknifty.csv into P1."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. It is the sourced inventory and this script "
            f"will not synthesise one. Re-run the documented DOM extraction "
            f"against {INVENTORY_SOURCE} to regenerate it."
        )
    rows: list[tuple[str, int]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for rec in csv.DictReader(fh):
            rows.append((rec["announcement_date"], int(rec["candidate"])))
    cand = [d for d, c in rows if c == 1]
    by_year: dict[int, list[str]] = {}
    for d in cand:
        by_year.setdefault(int(d[:4]), []).append(d)
    per_year = tuple(sorted(
        (y, len(ds), len(set(ds))) for y, ds in by_year.items()))
    return Inventory(
        total=len(rows),
        named_other=sum(1 for _, c in rows if c == 0),
        candidates=len(cand),
        distinct_dates=len(set(cand)),
        span=(min(cand), max(cand)),
        per_year=per_year,
    )


INDEX_SETS: Final[tuple[str, ...]] = (
    "NIFTY 50", "NIFTY Next 50", "NIFTY Midcap 150", "ALL THREE POOLED")

N_SIMS: Final[int] = 1000
DRY_SEED: Final[int] = 20260921


def stamp(n_label: str) -> str:
    return f"[{SCRIPT} | run {RUN_TS} | {n_label}]"


def rule(title: str) -> None:
    print(f"\n{'=' * 104}")
    print(title)
    print("=" * 104)


def sd_cluster_mean(sd_event: float, m: float, rho: float) -> float:
    """SD of a cluster mean of m correlated events: sd * sqrt((1+(m-1)rho)/m).

    At rho=0 this is the independent sd/sqrt(m); at rho=1 it is sd, because m
    perfectly correlated events carry the information of one."""
    return sd_event * float(np.sqrt((1.0 + (m - 1.0) * rho) / m))


def clustered_mde(sd_event: float, m: float, rho: float, g: int) -> float:
    """MDE at ALPHA two-sided and POWER, on G clusters, t with G-1 df."""
    df = g - 1
    crit = float(_st.t.ppf(1.0 - ALPHA / 2.0, df))
    pw = float(_st.t.ppf(POWER, df))
    return (crit + pw) * sd_cluster_mean(sd_event, m, rho) / float(np.sqrt(g))


def g_required(sd_event: float, m: float, rho: float, bar: float) -> int:
    """Smallest G whose MDE clears `bar`. Returns 0 if none up to 10,000."""
    for g in range(3, 10_001):
        if clustered_mde(sd_event, m, rho, g) <= bar:
            return g
    return 0


# =====================================================================
# DRY RUN -- reuses event_study.py's ARM 5 clustering structure
# =====================================================================

def _clustered_panel(rng: np.random.Generator, n_dates: int, per_date: int,
                     T: int, sd_event: float, rho: float, planted: float,
                     event_index: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Same construction as event_study.py ARM 5, with an effect planted on the
    event day. AR_ijt = sqrt(rho)*u_jt + sqrt(1-rho)*e_ijt, so intra-cluster
    correlation is rho and the date shock survives market adjustment."""
    n = n_dates * per_date
    market = rng.normal(0.0, 0.01, (n, T))
    common = rng.normal(0.0, sd_event, (n_dates, T))
    idio = rng.normal(0.0, sd_event, (n, T))
    ar = np.empty((n, T), dtype=float)
    labels: list[str] = []
    row = 0
    for j in range(n_dates):
        for _ in range(per_date):
            ar[row] = float(np.sqrt(rho)) * common[j] + float(np.sqrt(1.0 - rho)) * idio[row]
            labels.append(f"d{j}")
            row += 1
    ar[:, event_index] += planted
    return market + ar, market, labels


def dry_run(bar: float, sd: float = DECISIVE[0], rho: float = DECISIVE[1],
            m_events: int = int(EVENTS_PER_CLUSTER),
            g_values: tuple[int, ...] = (30, 60, 110)) -> bool:
    """Planted-effect check on the shared MDE formula.

    Parameterised so a later phase calls it at ITS cell and G values instead
    of writing a second copy. The defaults are Phase 1's, so calling it with
    no arguments reproduces Phase 1's output unchanged."""
    rule("PART A -- DRY RUN. The MDE formula is checked by simulation before any\n"
         "inventory figure is read: an effect planted AT the computed MDE must be\n"
         "detected by the clustered test about 80% of the time, by definition of MDE.")
    ok = True
    m = m_events
    print(f"\n  {stamp(f'n={N_SIMS:,} simulations per row')}")
    print(f"    {'G':>5}{'m':>4}{'SD':>7}{'rho':>6}{'MDE':>10}{'detected':>11}"
          f"{'expected':>10}  status")
    for g in g_values:
        mde = clustered_mde(sd, m, rho, g)
        rng = np.random.default_rng(DRY_SEED + g)
        w = EventWindow(0, 0)
        hits = 0
        for _ in range(N_SIMS):
            stock, market, labels = _clustered_panel(rng, g, m, 5, sd, rho, mde, 2)
            res = mean_car(car_per_event(market_adjusted_ar(stock, market), w, 2),
                           w, event_dates=labels)
            if res.p < ALPHA:
                hits += 1
        rate = hits / N_SIMS
        # 99% binomial band on 1,000 draws at p=0.80
        se = float(np.sqrt(POWER * (1 - POWER) / N_SIMS))
        lo, hi = POWER - 2.576 * se, POWER + 2.576 * se
        good = lo <= rate <= hi
        ok &= good
        print(f"    {g:>5}{m:>4}{sd:>7.2f}{rho:>6.1f}{mde:>10.5f}{rate:>10.1%}"
              f"{POWER:>10.0%}  {'PASS' if good else '*** FAIL ***'} "
              f"band [{lo:.1%},{hi:.1%}]")

    # the formula's own internals, hand-checkable
    exact = sd_cluster_mean(0.08, 5.0, 0.0) - 0.08 / float(np.sqrt(5.0))
    ind_ok = abs(exact) < 1e-12
    ok &= ind_ok
    print(f"\n    rho=0 reduces to sd/sqrt(m): residual {exact:.2e}  "
          f"{'PASS' if ind_ok else '*** FAIL ***'}")
    one = abs(sd_cluster_mean(0.08, 5.0, 1.0) - 0.08) < 1e-12
    ok &= one
    print(f"    rho=1 reduces to sd (m events carry one event's information)  "
          f"{'PASS' if one else '*** FAIL ***'}")
    print(f"\n  PART A: {'ALL CHECKS PASS' if ok else '*** FAILED ***'}")
    return ok


# =====================================================================
# PART B
# =====================================================================

@dataclass(frozen=True)
class Verdict:
    name: str
    g: int
    mde: float
    powered: bool


def main() -> int:
    rule(f"{SCRIPT} -- PHASE 1 FEASIBILITY (index reconstitution, forced flows)")
    print(f"  run {RUN_TS}")
    print("  implements PRECHECK_INDEX_RECON.md as locked. Feasibility only:")
    print("  no price data, no returns, no event study is run here.")

    # --- the bar -----------------------------------------------------
    rule("PART B, STEP 1 -- THE BAR")
    items = round_trip_cost_bps(NOTIONAL_RUPEES, date.today())
    bar = COVERAGE * items["total"] / 10_000.0
    print(f"\n  {stamp('n=1 notional, 1 valuation date')}")
    print(f"    delivery round-trip floor at Rs {NOTIONAL_RUPEES:,.0f} notional, today's rates:")
    for k in ("stt", "stamp", "dp", "transaction", "sebi", "ipft", "gst", "brokerage"):
        print(f"      {k:<12}{items[k]:>9.4f} bps")
    print(f"      {'TOTAL':<12}{items['total']:>9.4f} bps")
    print(f"    BAR = {COVERAGE:.0f}x floor = {COVERAGE * items['total']:.4f} bps "
          f"= {bar:.6f} in return units ({bar * 100:.4f}%)")
    print("    Rs 1 lakh is stated, not defaulted: DP is fixed rupees per sell, so")
    print("    the bps floor falls as position size rises and the bar moves with it.")

    if not dry_run(bar):
        rule("STOPPED -- the dry run failed; no inventory figure is read")
        return 1

    # --- the inventory -----------------------------------------------
    rule("PART B, STEP 2 -- EVENT INVENTORY")
    root = Path(__file__).resolve().parent.parent
    inv = load_inventory(root / INVENTORY_FILE)
    got = (inv.total, inv.named_other, inv.candidates, inv.distinct_dates)
    want = (EXPECT_TOTAL, EXPECT_OTHER, EXPECT_CANDIDATES, EXPECT_DATES)
    print(f"\n  {stamp(f'n={inv.total} equity announcements, {inv.span[0]} -> {inv.span[1]}')}")
    print(f"    source: {INVENTORY_SOURCE}")
    print(f"    persisted at: {INVENTORY_FILE}")
    if got != want:
        print(f"\n    *** INVENTORY MISMATCH. Derived {got}, recorded {want}.")
        print("    *** The persisted file has changed since the figures were recorded.")
        print("    *** Refusing to report a verdict under the same pre-registration.")
        return 1
    print(f"    derived from the file and matching what was recorded at fetch: "
          f"total {inv.total}, other-index {inv.named_other},")
    print(f"    candidates {inv.candidates}, distinct dates {inv.distinct_dates}")
    print(f"\n    {'year':>6}{'releases':>10}{'distinct dates':>16}")
    for y, rel, dts in inv.per_year:
        note = "  (partial year)" if y == 2026 else ""
        print(f"    {y:>6}{rel:>10}{dts:>16}{note}")
    print(f"    {'TOTAL':>6}{sum(r for _, r, _ in inv.per_year):>10}"
          f"{inv.distinct_dates:>16}")
    print("\n    *** NOT SOURCED, AND NOT GUESSED: which of the three indices each")
    print("    announcement touches, and how many stocks it adds. That is in the body")
    print(f"    of {inv.total} PDFs and was not parsed. Pre-2017 history is absent too --")
    print("    the archive reaches to 1998 but earlier title conventions do not match")
    print("    the extraction rule, so nothing is claimed for those years.")
    print(f"\n    G enters the MDE as 1/sqrt(G), so OVERSTATING G overstates power.")
    print(f"    Every index set below is therefore evaluated at G = {inv.distinct_dates}, every")
    print("    candidate date -- a GENEROUS UPPER BOUND. No single index can exceed it,")
    print("    and the pooled set cannot either: pooled dates are a subset of the same")
    print("    110, not the sum of three disjoint calendars.")

    # --- the grid ----------------------------------------------------
    rule("PART B, STEP 3 -- CLUSTERED MDE GRID (additions only)")
    g = inv.distinct_dates
    print(f"\n  {stamp(f'n=G {g} clusters, m {EVENTS_PER_CLUSTER:.0f} events/cluster assumed')}")
    print(f"  MDE = (t_.995,G-1 + t_.80,G-1) x SD x sqrt((1+(m-1)rho)/m) / sqrt(G)")
    print(f"  bar = {bar * 100:.4f}%.  (*) marks the decisive cell "
          f"(SD {DECISIVE[0]:.0%}, rho {DECISIVE[1]})")
    print(f"\n    {'SD':>6} |" + "".join(f"{'rho=' + format(r, '.1f'):>16}" for r in RHO_GRID))
    print(f"    {'-' * 6}-+" + "-" * (16 * len(RHO_GRID)))
    for sd in SD_GRID:
        cells = []
        for rho in RHO_GRID:
            mde = clustered_mde(sd, EVENTS_PER_CLUSTER, rho, g)
            mark = "*" if (sd, rho) == DECISIVE else " "
            cells.append(f"{mde * 100:>13.3f}%{mark}")
        print(f"    {sd:>6.0%} |" + "".join(cells))
    print(f"\n    every cell is an MDE in per-event CAR; POWERED needs MDE <= "
          f"{bar * 100:.4f}%")

    # --- verdicts ----------------------------------------------------
    rule("PART B, STEP 4 -- VERDICT PER INDEX SET")
    sd_d, rho_d = DECISIVE
    mde_d = clustered_mde(sd_d, EVENTS_PER_CLUSTER, rho_d, g)
    verdicts = [Verdict(name, g, mde_d, mde_d <= bar) for name in INDEX_SETS]
    print(f"\n  {stamp(f'n={len(verdicts)} index sets, G={g} (upper bound), decisive cell SD {sd_d:.0%} rho {rho_d}')}")
    print(f"    {'index set':<22}{'G (bound)':>11}{'MDE':>10}{'bar':>10}{'short by':>10}  verdict")
    for v in verdicts:
        print(f"    {v.name:<22}{v.g:>11}{v.mde * 100:>9.3f}%{bar * 100:>9.3f}%"
              f"{v.mde / bar:>9.2f}x  {'POWERED' if v.powered else 'UNDERPOWERED'}")

    need = g_required(sd_d, EVENTS_PER_CLUSTER, rho_d, bar)
    recent = inv.per_year[-2][2]
    print(f"\n    distinct announcement dates needed to reach the bar: "
          f"{need if need else '>10,000'}")
    print(f"    available (generous bound): {g}.  At the 2025 rate of {recent} dates/year")
    print(f"    that is roughly {(need - g) / recent:.0f} more years of announcements.")

    # --- kill condition ----------------------------------------------
    rule("PART B, STEP 5 -- THE KILL CONDITION")
    any_powered = any(v.powered for v in verdicts)
    print(f"\n  {stamp(f'n={len(verdicts)} index sets')}")
    print("  Locked in PRECHECK_INDEX_RECON.md before this script existed:")
    print()
    print("    \"Phase 1 closes if no index set, individually or pooled, has a clustered")
    print("     MDE (p<0.01 two-sided, 80% power, t with G-1 df) at or below 3x the")
    print("     delivery floor at Rs 1 lakh notional, under the middle SD and")
    print("     intra-cluster correlation assumptions.\"")
    print()
    if any_powered:
        print("    KILL CONDITION NOT MET -- at least one index set is POWERED at the")
        print("    decisive cell. NOTE: that result rests on a GENEROUS upper-bound G and")
        print("    is NOT conclusive. The per-index PDF split must be parsed before any")
        print("    pre-registration is written on it.")
    else:
        print("    Every index set is UNDERPOWERED at the decisive cell, and the G used is")
        print("    a generous upper bound -- the true G is smaller, so the true MDE is")
        print("    larger. THE KILL CONDITION IS MET. PHASE 1 CLOSES.")
        print()
        print("    The binding constraint is the number of independent ANNOUNCEMENT DATES,")
        print("    not the number of stocks. Index reconstitution concentrates every")
        print("    addition onto a handful of dates a year, so adding stocks to the sample")
        print("    buys almost no power once they share a date.")
    print("\n    Reported but NOT entering the verdict: the other eight grid cells.")
    powered_cells = [(sd, rho) for sd in SD_GRID for rho in RHO_GRID
                     if clustered_mde(sd, EVENTS_PER_CLUSTER, rho, g) <= bar]
    print(f"    Cells clearing the bar at G={g}: "
          f"{powered_cells if powered_cells else 'none'}")

    rule("END")
    print(f"  {stamp(f'n={inv.total} announcements, G={g}, {len(verdicts)} index sets')}")
    print("  wrote nothing. No price data was loaded and no event study was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
