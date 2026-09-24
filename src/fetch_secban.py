r"""
fetch_secban.py -- download and persist NSE's daily securities-in-ban-period
files. Fetch-and-cache only: it derives nothing and decides nothing.

SOURCE
    https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv
    One file per trading day. A 404 means no file for that date -- a weekend,
    an exchange holiday, or a genuine archive gap -- and the three are NOT
    distinguishable from the endpoint alone. `precheck_ban_list.py` reports the
    resulting coverage per year rather than assuming which it was.

WHY PERSIST. A figure from a live endpoint is not reproducible unless its input
is on disk, the same rule that put data/daily_closes_nifty_banknifty.csv into
P1 and data/nse_index_recon_announcements_2026-09-21.csv into Phase 1. Every
file fetched is written under data/fo_secban/ and never re-fetched.

POLITENESS. THREE workers and a 0.35s per-request pause, deliberately slow.
These are ~100-byte files on a public archive, but NSE blocks IPs that pull too
fast and a block would cost far more than the time saved. Do not raise these to
"just finish it sooner" -- the cache makes the run resumable, so a slow run that
completes beats a fast one that gets the address blocked.

=== NOT FETCHED YET: the MWPL utilisation series, and why ===

NSE publishes the regression-discontinuity running variable DIRECTLY, daily,
per stock. It does not need reconstructing from bhavcopy open interest:

    https://nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_DDMMYYYY.zip
    columns: Date, ISIN, Scrip Name, NSE Symbol, MWPL, Open Interest,
             Future Equivalent Open Interest, Limit for Next Day
    ~210 stocks per day; confirmed present back to at least 2014-09.
    utilisation = Future Equivalent Open Interest / MWPL
    "Limit for Next Day" reads "No Fresh Positions" for a banned name.

DELIBERATELY NOT FETCHED until the Phase 2 power grid is known. Pulling a
second multi-year daily archive to support a design that may be closed by the
same arithmetic would be work done in the wrong order.

THE CONSTRAINT THAT DESIGN MUST RESPECT, recorded here so it is not lost:
BAN STATUS IS HYSTERETIC. Entry is at 95% utilisation, exit at 80%, so a stock
stays banned while utilisation falls through the gap -- BANDHANBNK sat at 82.7%
on 2026-09-18 and was still banned. Ban STATUS is therefore not a function of
same-day utilisation, and an RD on the 95% threshold must be an RD on ENTRY
EVENTS, never on status. The same hysteresis is why this fetcher's consumer
defines an event as "not in ban on t-1, in ban on t" rather than "in ban on t".

Run:  python src/fetch_secban.py [START_YYYY-MM-DD] [END_YYYY-MM-DD]
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

BASE: Final[str] = ("https://nsearchives.nseindia.com/archives/fo/sec_ban/"
                    "fo_secban_%s.csv")
HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
OUT: Final[Path] = Path(__file__).resolve().parent.parent / "data" / "fo_secban"
WORKERS: Final[int] = 3
PAUSE: Final[float] = 0.35
MISSING: Final[str] = "__404__"


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch_one(d: date) -> tuple[date, Optional[str]]:
    """Returns (date, text) or (date, None) on 404. Cached files are not
    re-fetched; a cached MISSING marker is honoured too, so a re-run does not
    re-probe every weekend."""
    path = OUT / f"fo_secban_{d.strftime('%d%m%Y')}.csv"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return d, (None if text.startswith(MISSING) else text)
    time.sleep(PAUSE)
    url = BASE % d.strftime("%d%m%Y")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        body = urllib.request.urlopen(req, timeout=25, context=_ctx()).read()
        text = body.decode("utf-8", "replace")
        path.write_text(text, encoding="utf-8")
        return d, text
    except urllib.error.HTTPError as e:
        if e.code == 404:
            path.write_text(MISSING, encoding="utf-8")
            return d, None
        raise
    except Exception:
        # transient: do NOT cache, so a re-run retries it
        return d, None


def main() -> int:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2015, 1, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 9, 21)
    OUT.mkdir(parents=True, exist_ok=True)

    days: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:            # weekdays only; holidays still 404
            days.append(d)
        d += timedelta(days=1)

    print(f"fetch_secban: {len(days):,} weekdays {start} -> {end}, "
          f"cache {OUT}", flush=True)
    got = 0
    miss = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (day, text) in enumerate(pool.map(fetch_one, days), 1):
            if text is None:
                miss += 1
            else:
                got += 1
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}  present {got:,}  absent {miss:,}",
                      flush=True)
    print(f"DONE  present {got:,}  absent {miss:,}  of {len(days):,} weekdays",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
