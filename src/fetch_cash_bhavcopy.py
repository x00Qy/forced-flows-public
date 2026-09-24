r"""
fetch_cash_bhavcopy.py -- download and persist NSE's daily CASH-market
bhavcopy, in BOTH published formats. Fetch-and-cache only: it derives nothing
and decides nothing.

SOURCES, and the cutover between them is MEASURED, not assumed:

    LEGACY  https://nsearchives.nseindia.com/content/historical/EQUITIES/
            YYYY/MON/cmDDMONYYYYbhav.csv.zip
            columns SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,...

    UDiFF   https://nsearchives.nseindia.com/content/cm/
            BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
            columns TradDt,...,TckrSymb,SctySrs,...,OpnPric,HghPric,LwPric,
                    ClsPric,...

    Probed 2026-09-22: legacy present on 2024-07-01, absent (404) on
    2024-07-08; UDiFF present on both. The two formats OVERLAP, so
    `consolidate_bhavcopy.py` cross-checks them on the overlap rather than
    trusting that they agree.

THE SLIM EXTRACT. Only the ban-list stocks matter, so each day is reduced to
(date, symbol, open, close) for the symbols in SYMBOLS_FILE and appended to one
consolidated file. The raw zips are kept on disk and gitignored: a figure from
a live endpoint is not reproducible unless its input is on disk, but 2,893
zips do not belong in git.

POLITENESS. THREE workers and a 0.35s per-request pause, the same as
`fetch_secban.py`. These are 65-170 KB files, not 100-byte ones, so this run is
slower in wall-clock terms and MUST NOT be sped up -- NSE blocks IPs that pull
too fast and a block would cost far more than the time saved. The cache makes
the run resumable.

WHAT THIS DOES NOT DO. It does not adjust for corporate actions, does not
compute returns, and does not know what an event is. `PREVCLOSE` is captured
as published and is NOT corporate-action adjusted (verified on BHEL 2017-09-28
and CANBK 2024-05-15); nothing downstream chains on it.

Run:  python src/fetch_cash_bhavcopy.py [START] [END]
"""
from __future__ import annotations

import io
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Optional
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
OUT: Final[Path] = ROOT / "data" / "bhavcopy"
HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
MON: Final[tuple[str, ...]] = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL",
                               "AUG", "SEP", "OCT", "NOV", "DEC")
WORKERS: Final[int] = 3
PAUSE: Final[float] = 0.35
MISSING: Final[str] = "__404__"


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def legacy_url(d: date) -> str:
    m = MON[d.month - 1]
    return ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
            f"{d.year}/{m}/cm{d.strftime('%d')}{m}{d.year}bhav.csv.zip")


def udiff_url(d: date) -> str:
    return ("https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    return bytes(urllib.request.urlopen(req, timeout=40, context=_ctx()).read())


def fetch_one(d: date) -> tuple[date, str]:
    """Cache both formats for one day. Returns (date, status) where status is
    one of 'both', 'legacy', 'udiff', 'none'. A cached 404 marker is honoured,
    so a re-run does not re-probe every holiday."""
    got: list[str] = []
    for tag, fn in (("legacy", legacy_url), ("udiff", udiff_url)):
        # Era guards, MEASURED on 2026-09-22 rather than guessed: UDiFF 404s on
        # 2015-01-02, 2020-01-02, 2023-01-02 and 2023-07-03 but is present from
        # 2024-01-02; legacy is present on 2024-07-01 and 404s from 2024-07-08.
        # The guards keep a 2024 OVERLAP in which both are fetched, which is
        # what lets the two formats be cross-checked instead of assumed equal.
        # Without them this run would spend ~2,400 pointless 404 probes.
        if tag == "udiff" and d < date(2024, 1, 1):
            continue
        if tag == "legacy" and d > date(2024, 12, 31):
            continue
        path = OUT / tag / f"{d.isoformat()}.zip"
        mark = OUT / tag / f"{d.isoformat()}.404"
        if path.exists():
            got.append(tag)
            continue
        if mark.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        time.sleep(PAUSE)
        try:
            body = _get(fn(d))
            zipfile.ZipFile(io.BytesIO(body)).namelist()   # reject truncation
            path.write_bytes(body)
            got.append(tag)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                mark.write_text(MISSING, encoding="utf-8")
            # any other HTTP code: do NOT cache, so a re-run retries
        except Exception:
            pass                                            # transient; retry
    if len(got) == 2:
        return d, "both"
    if got:
        return d, got[0]
    return d, "none"


def read_day(d: date) -> Optional[dict[str, tuple[float, float, float]]]:
    """(symbol -> (open, close, prevclose)) for EQ-series equities on day `d`,
    preferring the LEGACY file where both exist so the long era is read one
    way. Returns None if neither format is cached."""
    lp = OUT / "legacy" / f"{d.isoformat()}.zip"
    up = OUT / "udiff" / f"{d.isoformat()}.zip"
    if lp.exists():
        return _parse_legacy(lp)
    if up.exists():
        return _parse_udiff(up)
    return None


def _text(path: Path) -> str:
    z = zipfile.ZipFile(path)
    return z.read(z.namelist()[0]).decode("utf-8", "replace")


def _parse_legacy(path: Path) -> dict[str, tuple[float, float, float]]:
    out: dict[str, tuple[float, float, float]] = {}
    lines = _text(path).splitlines()
    head = [h.strip().upper() for h in lines[0].split(",")]
    ix = {k: head.index(k) for k in
          ("SYMBOL", "SERIES", "OPEN", "CLOSE", "PREVCLOSE")}
    for line in lines[1:]:
        p = [x.strip() for x in line.split(",")]
        if len(p) <= max(ix.values()) or p[ix["SERIES"]] != "EQ":
            continue
        try:
            out[p[ix["SYMBOL"]]] = (float(p[ix["OPEN"]]), float(p[ix["CLOSE"]]),
                                    float(p[ix["PREVCLOSE"]]))
        except ValueError:
            continue
    return out


def _parse_udiff(path: Path) -> dict[str, tuple[float, float, float]]:
    out: dict[str, tuple[float, float, float]] = {}
    lines = _text(path).splitlines()
    head = [h.strip() for h in lines[0].split(",")]
    ix = {k: head.index(k) for k in
          ("TckrSymb", "SctySrs", "OpnPric", "ClsPric", "PrvsClsgPric")}
    for line in lines[1:]:
        p = [x.strip() for x in line.split(",")]
        if len(p) <= max(ix.values()) or p[ix["SctySrs"]] != "EQ":
            continue
        try:
            out[p[ix["TckrSymb"]]] = (float(p[ix["OpnPric"]]),
                                      float(p[ix["ClsPric"]]),
                                      float(p[ix["PrvsClsgPric"]]))
        except ValueError:
            continue
    return out


def main() -> int:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2015, 1, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 9, 21)
    OUT.mkdir(parents=True, exist_ok=True)

    days: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    print(f"fetch_cash_bhavcopy: {len(days):,} weekdays {start} -> {end}",
          flush=True)
    print(f"  cache {OUT}   {WORKERS} workers, {PAUSE}s pause", flush=True)
    tally = {"both": 0, "legacy": 0, "udiff": 0, "none": 0}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (_, status) in enumerate(pool.map(fetch_one, days), 1):
            tally[status] += 1
            if i % 200 == 0:
                print(f"  {i:,}/{len(days):,}  " +
                      "  ".join(f"{k} {v:,}" for k, v in tally.items()),
                      flush=True)
    print("DONE  " + "  ".join(f"{k} {v:,}" for k, v in tally.items()),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
