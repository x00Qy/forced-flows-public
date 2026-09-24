r"""
precheck_ban_list.py -- Phase 2 feasibility, implementing PRECHECK_BAN_LIST.md
as locked. FEASIBILITY ONLY: no price data, no returns, no event study is run.

KILL CONDITION, from the pre-registration committed before this file existed:

    Phase 2 (ban list) closes if the clustered MDE (p<0.01 two-sided, 80% power,
    t with G-1 df) exceeds 3x the delivery floor at Rs 1 lakh notional at the
    middle SD and intra-cluster correlation cell -- (SD 5%, rho 0.2) -- using
    the sourced count of distinct ban-entry dates as G.

TWO-SIDED, per the pre-registration. The sign of the post-ban move is not
settled in advance, and declaring one now would buy power by assuming the thing
in question.

=== AN EVENT IS AN ENTRY, NOT A BAN-DAY ===

    entry(s, t)  <=>  s NOT in ban on the previous ARCHIVED trading day
                      AND s in ban on t

A stock banned for nine consecutive days is ONE event. Counting ban-days would
inflate n by roughly the mean ban duration.

This definition is forced by the hysteresis in the rule itself: entry is at 95%
MWPL utilisation but exit only at 80%, so a stock stays banned while
utilisation falls through the gap -- BANDHANBNK sat at 82.7% on 2026-09-18 and
was still banned. Ban STATUS is therefore not a function of same-day
utilisation; only ENTRY is an event. The output reports both counts side by
side so the size of that distinction is visible rather than asserted.

=== THE ESTIMATOR IS PHASE 1'S, IMPORTED ===

sd_cluster_mean, clustered_mde, g_required and the planted-effect dry run are
imported from precheck_index_recon.py, not reimplemented. A second copy of a
power formula is the defect class this program keeps naming. The dry run is
parameterised, so it runs here at PHASE 2's cell and G rather than Phase 1's.

What differs from Phase 1: m -- the mean entries per entry date -- is MEASURED
from the inventory here, where Phase 1 could only assume it.

=== WHAT WOULD MAKE THIS WRONG ===

  SD AND RHO ARE ASSUMPTIONS. The grid shows the sensitivity.
  A GAP IN THE ARCHIVE MANUFACTURES SPURIOUS ENTRIES. If day t-1 is missing,
  every name banned on t looks new. Gaps are counted and reported, and entries
  adjacent to a gap are reported separately so their contribution is visible.
  SELECTION INTO BAN IS NOT RANDOM. Banned names have extreme derivative
  positioning by construction, so any CAR is conditional on that.
  THE 5-DAY WINDOW IS A CHOICE, fixed in the pre-registration.

Run:  python src/precheck_ban_list.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

from precheck_index_recon import (
    ALPHA, COVERAGE, NOTIONAL_RUPEES, clustered_mde, dry_run, g_required, rule,
)
from require_data import guard
from require_yalgo_core import round_trip_cost_bps

SCRIPT: Final[str] = "precheck_ban_list.py"
RUN_TS: Final[str] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# --- locked by PRECHECK_BAN_LIST.md ----------------------------------
SD_GRID: Final[tuple[float, ...]] = (0.03, 0.05, 0.08)
RHO_GRID: Final[tuple[float, ...]] = (0.0, 0.2, 0.4)
DECISIVE: Final[tuple[float, float]] = (0.05, 0.2)
WINDOW: Final[str] = "[+1,+5]"

CONSOLIDATED: Final[Path] = (Path(__file__).resolve().parent.parent
                             / "data" / "fo_secban_2015_2026.csv")
NONE_SENTINEL: Final[str] = "__NONE__"
SOURCE: Final[str] = ("NSE archives, fo_secban daily files, "
                      "nsearchives.nseindia.com/archives/fo/sec_ban/")


def stamp(n_label: str) -> str:
    return f"[{SCRIPT} | run {RUN_TS} | {n_label}]"


@dataclass(frozen=True)
class Day:
    d: date
    names: frozenset[str]


@dataclass(frozen=True)
class BanInventory:
    days: tuple[Day, ...]                       # archived trading days, in order
    absent: int                                 # weekdays with no file (404)
    entries: tuple[tuple[date, str], ...]       # (entry date, symbol)
    after_gap: int                              # entries whose t-1 was >4 days back
    per_year: tuple[tuple[int, int, int, float, int], ...]
    # (year, entries, distinct entry dates, mean entries/date, max entries/date)


def load_inventory() -> BanInventory:
    """Read the COMMITTED consolidated file, not the gitignored per-day cache.

    The cache is the raw fetch artifact and stays local; this script must run
    from what is in the repository, or a figure could not be reproduced by
    anyone who clones it. A `__NONE__` symbol marks a day that was archived
    with nobody in ban -- a real trading day, and not the same as an absent
    one, which is why the calendar survives consolidation."""
    if not CONSOLIDATED.exists():
        raise FileNotFoundError(
            f"{CONSOLIDATED} is missing. Run src/fetch_secban.py then "
            f"src/consolidate_secban.py; this script does not fetch and will "
            f"not synthesise an inventory."
        )
    by_day: dict[date, set[str]] = {}
    absent = 0
    for line in CONSOLIDATED.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("ban_date"):
            continue
        ds, _, sym = line.partition(",")
        if not ds:
            continue
        d = date.fromisoformat(ds)
        bucket = by_day.setdefault(d, set())
        if sym != NONE_SENTINEL:
            bucket.add(sym)
    days = [Day(d, frozenset(names)) for d, names in sorted(by_day.items())]

    entries: list[tuple[date, str]] = []
    after_gap = 0
    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        gap = (cur.d - prev.d).days > 4          # > a long weekend
        new = cur.names - prev.names
        for sym in sorted(new):
            entries.append((cur.d, sym))
            if gap:
                after_gap += 1

    by_year: dict[int, list[tuple[date, str]]] = {}
    for d, s in entries:
        by_year.setdefault(d.year, []).append((d, s))
    per_year: list[tuple[int, int, int, float, int]] = []
    for y in sorted(by_year):
        rows = by_year[y]
        dates: dict[date, int] = {}
        for d, _ in rows:
            dates[d] = dates.get(d, 0) + 1
        counts = list(dates.values())
        per_year.append((y, len(rows), len(dates),
                         sum(counts) / len(counts), max(counts)))
    return BanInventory(tuple(days), absent, tuple(entries), after_gap,
                        tuple(per_year))


def main() -> int:
    rule(f"{SCRIPT} -- PHASE 2 FEASIBILITY (F&O ban list, forced flows)")
    print(f"  run {RUN_TS}")
    print("  implements PRECHECK_BAN_LIST.md as locked. Feasibility only:")
    print("  no price data, no returns, no event study is run here.")

    # --- the bar (identical to Phase 1, so the phases are comparable) --
    rule("PART B, STEP 1 -- THE BAR")
    items = round_trip_cost_bps(NOTIONAL_RUPEES, date.today())
    bar = COVERAGE * items["total"] / 10_000.0
    print(f"\n  {stamp('n=1 notional, 1 valuation date')}")
    print(f"    delivery round-trip floor at Rs {NOTIONAL_RUPEES:,.0f}: "
          f"{items['total']:.4f} bps")
    print(f"    BAR = {COVERAGE:.0f}x floor = {COVERAGE * items['total']:.4f} bps "
          f"= {bar * 100:.4f}%  (same bar as Phase 1)")

    # --- inventory ----------------------------------------------------
    rule("PART B, STEP 2 -- BAN-LIST INVENTORY")
    inv = load_inventory()
    if not inv.days:
        print("\n  no archived days found -- run src/fetch_secban.py first")
        return 1
    g = len({d for d, _ in inv.entries})
    m = len(inv.entries) / g if g else 0.0
    in_ban = [len(x.names) for x in inv.days]
    mean_in_ban = sum(in_ban) / len(in_ban)
    entries_by_date: dict[date, int] = {}
    for d, _ in inv.entries:
        entries_by_date[d] = entries_by_date.get(d, 0) + 1

    print(f"\n  {stamp(f'n={len(inv.days):,} archived trading days, {len(inv.entries):,} entries')}")
    print(f"    source: {SOURCE}")
    print(f"    committed input: {CONSOLIDATED.name} "
          f"({len(inv.days):,} archived trading days)")
    print(f"    raw per-day cache kept on disk at data/fo_secban/, gitignored")
    print(f"    archived span: {inv.days[0].d.isoformat()} -> {inv.days[-1].d.isoformat()}")
    print(f"\n    AN EVENT IS AN ENTRY, NOT A BAN-DAY:")
    print(f"      stocks in ban on a typical day (mean over days) : {mean_in_ban:>8.2f}")
    print(f"      NEW ENTRIES per day (mean over days)            : "
          f"{len(inv.entries) / len(inv.days):>8.2f}")
    print(f"      ratio                                           : "
          f"{mean_in_ban / (len(inv.entries) / len(inv.days)):>8.2f}x")
    print(f"      -- counting ban-days rather than entries would inflate n by")
    print(f"         about that factor, which is the mean ban duration.")
    print(f"\n    {'year':>6}{'entries':>9}{'entry dates':>13}{'mean/date':>11}{'max/date':>10}")
    for y, ent, dts, mean_d, max_d in inv.per_year:
        print(f"    {y:>6}{ent:>9,}{dts:>13,}{mean_d:>11.2f}{max_d:>10}")
    print(f"    {'TOTAL':>6}{len(inv.entries):>9,}{g:>13,}{m:>11.2f}"
          f"{max(entries_by_date.values()):>10}")
    print(f"\n    G = {g:,} distinct entry dates.  m = {m:.2f} entries per date, MEASURED.")
    print(f"    The first archived day cannot yield entries (no t-1) and is excluded.")
    print(f"    {inv.after_gap:,} entries follow an archive gap of >4 days, where a missing")
    print(f"    t-1 can manufacture a spurious entry. Reported, not removed.")

    if not dry_run(bar, sd=DECISIVE[0], rho=DECISIVE[1], m_events=max(1, round(m)),
                   g_values=(max(3, g // 4), max(3, g // 2), max(3, g))):
        rule("STOPPED -- the dry run failed; no verdict is printed")
        return 1

    # --- the grid -----------------------------------------------------
    rule("PART B, STEP 3 -- CLUSTERED MDE GRID (entries only, window "
         + WINDOW + ")")
    print(f"\n  {stamp(f'n=G {g:,} entry dates, m {m:.2f} entries/date (measured)')}")
    print(f"  bar = {bar * 100:.4f}%.  (*) marks the decisive cell "
          f"(SD {DECISIVE[0]:.0%}, rho {DECISIVE[1]})")
    print(f"\n    {'SD':>6} |" + "".join(f"{'rho=' + format(r, '.1f'):>16}" for r in RHO_GRID))
    print(f"    {'-' * 6}-+" + "-" * (16 * len(RHO_GRID)))
    for sd in SD_GRID:
        cells = []
        for rho in RHO_GRID:
            mde = clustered_mde(sd, m, rho, g)
            mark = "*" if (sd, rho) == DECISIVE else " "
            cells.append(f"{mde * 100:>13.3f}%{mark}")
        print(f"    {sd:>6.0%} |" + "".join(cells))

    # --- verdict ------------------------------------------------------
    rule("PART B, STEP 4 -- THE KILL CONDITION")
    sd_d, rho_d = DECISIVE
    mde_d = clustered_mde(sd_d, m, rho_d, g)
    powered = mde_d <= bar
    print(f"\n  {stamp(f'n=G {g:,}, m {m:.2f}, decisive cell SD {sd_d:.0%} rho {rho_d}')}")
    print("  Locked in PRECHECK_BAN_LIST.md before this script existed:")
    print()
    print("    \"Phase 2 (ban list) closes if the clustered MDE (p<0.01 two-sided,")
    print("     80% power, t with G-1 df) exceeds 3x the delivery floor at Rs 1 lakh")
    print("     notional at the middle SD and intra-cluster correlation cell, using")
    print("     the sourced count of distinct ban-entry dates as G.\"")
    print()
    print(f"    MDE at the decisive cell   {mde_d * 100:>9.4f}%")
    print(f"    bar                        {bar * 100:>9.4f}%")
    print(f"    ratio                      {mde_d / bar:>9.2f}x")
    need = g_required(sd_d, m, rho_d, bar)
    print(f"    entry dates needed to reach the bar: "
          f"{need if need else '>10,000'}   available: {g:,}")
    print()
    if powered:
        print("    THE KILL CONDITION DOES NOT FIRE. Phase 2 is POWERED at the decisive")
        print("    cell: a test on these events could resolve an effect the size that")
        print("    would matter. That is NOT a result -- no effect has been measured and")
        print("    none is claimed. It means a pre-registration for the test itself is")
        print("    the next step, with its own hypothesis, window and bar.")
    else:
        print("    Every reading at the decisive cell is UNDERPOWERED.")
        print("    THE KILL CONDITION IS MET. PHASE 2 CLOSES.")
    clearing = [(sd, rho) for sd in SD_GRID for rho in RHO_GRID
             if clustered_mde(sd, m, rho, g) <= bar]
    print(f"\n    Cells clearing the bar: {clearing if clearing else 'none'}")

    rule("END")
    print(f"  {stamp(f'n={len(inv.entries):,} entries, G={g:,}, {len(inv.days):,} archived days')}")
    print("  wrote nothing. No price data was loaded and no event study was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
