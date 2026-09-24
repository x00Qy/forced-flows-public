r"""
consolidate_secban.py -- fold the per-day fo_secban cache into one committed
file of (date, symbol) rows.

WHY. The 3,058 per-day files are the raw fetch artifact and stay on disk,
gitignored: committing 3,058 ~100-byte files would bloat the repository and
none of them is individually interesting. The consolidated file IS the
committed input -- one artifact, readable, diffable, and carrying its own
provenance header so a figure derived from it can name its source.

The header is CSV comment lines (#) so the file stays machine-readable and
`precheck_ban_list.py` can skip them without a special parser.

Run:  python src/consolidate_secban.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CACHE: Final[Path] = ROOT / "data" / "fo_secban"
OUT: Final[Path] = ROOT / "data" / "fo_secban_2015_2026.csv"
MISSING_MARKER: Final[str] = "__404__"
NONE_SENTINEL: Final[str] = "__NONE__"
SOURCE_PATTERN: Final[str] = (
    "https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv")
FETCHED: Final[str] = "2026-09-21"


def main() -> int:
    if not CACHE.exists():
        raise FileNotFoundError(f"{CACHE} missing; run src/fetch_secban.py first")
    rows: list[tuple[date, str]] = []
    with_data = 0
    absent = 0
    empty = 0
    for path in sorted(CACHE.glob("fo_secban_*.csv")):
        stem = path.stem.replace("fo_secban_", "")
        d = date(int(stem[4:8]), int(stem[2:4]), int(stem[0:2]))
        text = path.read_text(encoding="utf-8")
        if text.startswith(MISSING_MARKER):
            absent += 1
            continue
        with_data += 1
        n_before = len(rows)
        for line in text.splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                sym = parts[1].strip().upper()
                if sym:
                    rows.append((d, sym))
        if len(rows) == n_before:
            empty += 1
            # A day that was archived with NOBODY in ban is a real trading day
            # and must survive into the consolidated file: entry detection
            # compares against the previous ARCHIVED day, and an archived-empty
            # day is not the same as an absent one. Without this sentinel the
            # committed file could not reproduce the cache-based run.
            rows.append((d, NONE_SENTINEL))
    rows.sort()

    days = sorted({d for d, _ in rows})
    lines = [
        "# NSE securities-in-ban-period, consolidated from the daily archive.",
        f"# source   {SOURCE_PATTERN}",
        f"# fetched  {FETCHED}",
        f"# produced {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        " by src/consolidate_secban.py",
        f"# span     {days[0].isoformat()} -> {days[-1].isoformat()}",
        f"# files    {with_data:,} archived trading days with a file,"
        f" {absent:,} weekdays absent (exchange holidays or archive gaps --"
        " the endpoint does not distinguish them)",
        f"#          {empty:,} of the archived days had a file but nobody in ban,"
        " which is a real trading day and NOT the same as an absent file",
        "# rows     one row per (trading day, stock in ban on that day). A stock"
        " banned for nine days appears nine times.",
        "#          A day with symbol __NONE__ was archived with nobody in ban --"
        " a real trading day, kept so the archived calendar survives.",
        "#          an EVENT is an ENTRY (absent on the previous archived day,"
        " present on this one), derived by the consumer.",
        "ban_date,symbol",
    ]
    lines.extend(f"{d.isoformat()},{s}" for d, s in rows)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"  {len(rows):,} (date, symbol) rows over {len(days):,} trading days")
    print(f"  {with_data:,} files with data, {absent:,} absent, {empty:,} empty-but-present")
    print(f"  span {days[0].isoformat()} -> {days[-1].isoformat()}")
    print(f"  distinct symbols {len({s for _, s in rows if s != NONE_SENTINEL}):,}")
    print(f"  __NONE__ sentinel rows (archived, nobody banned) {empty:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
