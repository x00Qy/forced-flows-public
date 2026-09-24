r"""
fetch_index_close.py -- download and persist NSE's daily all-indices close
file, and extract the NIFTY 500 open and close. Fetch-and-cache only.

SOURCE
    https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv
    columns: Index Name, Index Date, Open Index Value, High, Low,
             Closing Index Value, Points Change, Change(%), Volume, ...
    One row per index per trading day; ~47 indices in 2015, ~130 by 2026.

=== THE RENAME, AND THE DECOY THAT SITS NEXT TO IT ===

NSE rebranded the CNX series as NIFTY in late 2015. Probed 2026-09-22:

    2015-11-05   "CNX 500"     open 6734.80   close 6661.70
    2015-11-09   "Nifty 500"   open 6516.20   close 6641.40

so a fetcher keyed on "Nifty 500" alone silently loses ten months of 2015, and
one keyed on a `"500" in name` substring silently picks up **"CNX 500 Shariah"
/ "Nifty500 Shariah"**, a DIFFERENT index that sits in the same file. Both
failures are silent -- a benchmark series with a hole or a wrong index in it
still produces abnormal returns, just wrong ones.

So the match is an EXACT membership test against `NIFTY500_NAMES` and nothing
else, and `main()` asserts that exactly one row matches per day. A day where
zero or two rows match is an error, not a warning.

The rename is a rename: it is the same index and the level is continuous
across it, which `main()` checks rather than assumes.

POLITENESS. Three workers, 0.35s pause, as `fetch_secban.py`.

Run:  python src/fetch_index_close.py [START] [END]
"""
from __future__ import annotations

import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Optional
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CACHE: Final[Path] = ROOT / "data" / "index_close"
OUT_CSV: Final[Path] = ROOT / "data" / "nifty500_daily_2015_2026.csv"
HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
# EXACT names, both eras. Not a substring test -- see the module docstring.
NIFTY500_NAMES: Final[frozenset[str]] = frozenset({"CNX 500", "Nifty 500"})
WORKERS: Final[int] = 3
PAUSE: Final[float] = 0.35
MISSING: Final[str] = "__404__"


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def url_for(d: date) -> str:
    return ("https://nsearchives.nseindia.com/content/indices/"
            f"ind_close_all_{d.strftime('%d%m%Y')}.csv")


def fetch_one(d: date) -> tuple[date, Optional[str]]:
    path = CACHE / f"{d.isoformat()}.csv"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return d, (None if text.startswith(MISSING) else text)
    CACHE.mkdir(parents=True, exist_ok=True)
    time.sleep(PAUSE)
    try:
        req = urllib.request.Request(url_for(d), headers=HEADERS)
        text = urllib.request.urlopen(
            req, timeout=40, context=_ctx()).read().decode("utf-8", "replace")
        path.write_text(text, encoding="utf-8")
        return d, text
    except urllib.error.HTTPError as e:
        if e.code == 404:
            path.write_text(MISSING, encoding="utf-8")
        return d, None
    except Exception:
        return d, None                       # transient: do NOT cache


def _split_csv(line: str) -> list[str]:
    """Index names contain commas inside double quotes in some years."""
    out: list[str] = []
    cur: list[str] = []
    q = False
    for ch in line:
        if ch == '"':
            q = not q
        elif ch == "," and not q:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return out


def nifty500_row(text: str) -> Optional[tuple[float, float]]:
    """(open, close) for NIFTY 500 on this day.

    Raises if the file holds MORE than one matching row -- an ambiguous
    benchmark must stop the run, not pick one."""
    hits: list[tuple[float, float]] = []
    lines = text.splitlines()
    if not lines:
        return None
    head = [h.strip() for h in _split_csv(lines[0])]
    try:
        i_name = head.index("Index Name")
        i_open = head.index("Open Index Value")
        i_close = head.index("Closing Index Value")
    except ValueError:
        return None
    for line in lines[1:]:
        p = _split_csv(line)
        if len(p) <= max(i_name, i_open, i_close):
            continue
        if p[i_name] not in NIFTY500_NAMES:
            continue
        try:
            hits.append((float(p[i_open]), float(p[i_close])))
        except ValueError:
            continue
    if len(hits) > 1:
        raise ValueError(f"{len(hits)} rows matched NIFTY500_NAMES")
    return hits[0] if hits else None


def main() -> int:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2015, 1, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 9, 21)

    days: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    print(f"fetch_index_close: {len(days):,} weekdays {start} -> {end}",
          flush=True)
    rows: list[tuple[date, float, float]] = []
    absent = 0
    no_row = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (day, text) in enumerate(pool.map(fetch_one, days), 1):
            if text is None:
                absent += 1
            else:
                r = nifty500_row(text)
                if r is None:
                    no_row += 1
                else:
                    rows.append((day, r[0], r[1]))
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}  rows {len(rows):,}  "
                      f"absent {absent:,}  no-NIFTY500-row {no_row:,}",
                      flush=True)

    rows.sort()
    OUT_CSV.write_text(
        "# NIFTY 500 daily open and close, from NSE's all-indices close file.\n"
        "# source   https://nsearchives.nseindia.com/content/indices/"
        "ind_close_all_DDMMYYYY.csv\n"
        f"# fetched  {date.today().isoformat()}\n"
        "# names    matched EXACTLY against {'CNX 500', 'Nifty 500'} -- the\n"
        "#          CNX->NIFTY rename is late 2015, and 'CNX 500 Shariah' /\n"
        "#          'Nifty500 Shariah' sit in the same file and are NOT this\n"
        "#          index. A substring match on '500' would take them.\n"
        f"# rows     {len(rows):,} trading days; {absent:,} weekdays absent, "
        f"{no_row:,} present without a NIFTY 500 row\n"
        "date,open,close\n"
        + "".join(f"{d.isoformat()},{o},{c}\n" for d, o, c in rows),
        encoding="utf-8")

    print(f"DONE  {len(rows):,} days -> {OUT_CSV}", flush=True)
    print(f"      {absent:,} weekdays absent, {no_row:,} present with no "
          f"NIFTY 500 row", flush=True)

    # --- the rename is a RENAME: check continuity rather than assume it ----
    big = [(rows[i - 1][0], rows[i][0],
            rows[i][2] / rows[i - 1][2] - 1.0)
           for i in range(1, len(rows))
           if abs(rows[i][2] / rows[i - 1][2] - 1.0) > 0.08]
    print(f"      close-to-close moves beyond +/-8%: {len(big)}")
    for a, b, move in big[:10]:
        print(f"        {a} -> {b}  {move:+.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
