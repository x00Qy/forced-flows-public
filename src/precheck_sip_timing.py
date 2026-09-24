r"""
precheck_sip_timing.py -- executes PRECHECK_SIP_TIMING.md.

Arithmetic only. No event study, no test statistic, no price data beyond one
volatility input.

    KILL CONDITION (PRECHECK_SIP_TIMING.md section 1)
    Phase 3 closes if the largest plausible single-date SIP deployment, as a
    share of that date's NSE cash-market turnover, implies an index move below
    3x the delivery floor (71.35 bps) under a stated, generous price-impact
    assumption.

=== THE MODEL, FIXED IN THE PRE-CHECK BEFORE ANY RATIO WAS SEEN ===

    dP/P = Y * sigma * sqrt(Q / V)          square-root law of market impact

Y = 1.5, fifty percent above the Y ~ 1 consensus (Torre 1997 after Loeb 1983;
Torre & Ferrari 1998; Moro et al. 2009; Toth et al. 2011; Bershova & Rakhlin
2013; Zarinelli et al. 2015; Waelbroeck & Gomes 2015). Almgren et al. (2005)
prefer a 3/5 power for temporary impact, which gives a SMALLER move than a
square root below Q/V = 1, so the square root is itself the generous choice.

sigma = the 95th percentile of the rolling 21-session standard deviation of
NIFTY 500 close-to-close returns over the covered months -- not the average.

Q = the WHOLE MONTH's SIP inflow, deployed on ONE date. No public data exists
on how SIP debits distribute across dates, so the unknown is resolved in the
direction generous to the hypothesis. This overstates the move by roughly
sqrt(k) for k real debit dates.

=== THE DATA, AND THE ONE THING IT CANNOT DO ===

AMFI does NOT publish a machine-readable monthly SIP series back to 2016.
Verified 2026-09-22 and recorded in PRECHECK_SIP_TIMING.md section 4: the
monthly report Excel carries SIP columns only in Aug-2026; the pre-2018
monthly report PDFs contain no occurrence of "SIP" at all; the AMFI Monthly
Note PDFs do carry the series but the archive begins June 2024.

So the covered window is about Jan-2024 to Aug-2026, assembled from
OVERLAPPING notes -- each month is reported by up to seven of them. Those
overlaps are not averaged. `sip_series()` ASSERTS that every note reporting a
month agrees on it, and raises on a disagreement, because a silently averaged
disagreement is a wrong number that looks like a right one.

THE ASSUMPTION THIS FORCES: that no month before the window had a larger SIP
inflow than the largest inside it. Not verified here, because the data is not
machine-readable. It matters in ONE direction -- an earlier larger month would
make a kill false -- so the verdict reports how far the largest month is from
the bar in flow terms.

Run:  python src/precheck_sip_timing.py
      python src/precheck_sip_timing.py --dry-run
"""
from __future__ import annotations

import csv
import io
import math
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Final, Optional

import numpy as np
import pypdf
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
NOTE_INDEX: Final[Path] = ROOT / "data" / "amfi_monthly_notes_index.csv"
NOTE_CACHE: Final[Path] = ROOT / "data" / "amfi_notes"
SIP_CSV: Final[Path] = ROOT / "data" / "amfi_sip_monthly.csv"
TURNOVER_CSV: Final[Path] = ROOT / "data" / "nse_cash_turnover_daily.csv"
NIFTY500: Final[Path] = ROOT / "data" / "nifty500_daily_2015_2026.csv"
BHAV: Final[Path] = ROOT / "data" / "bhavcopy"
RESULTS: Final[Path] = ROOT / "results"

# --- pre-registered constants; changing one invalidates the pre-check ------
Y_GENEROUS: Final[float] = 1.5       # 1.5x the Y ~ 1 consensus
Y_CONSENSUS: Final[float] = 1.0
SIGMA_PCTILE: Final[float] = 95.0    # of rolling 21-session SD
SIGMA_WINDOW: Final[int] = 21
BAR_BPS: Final[float] = 71.35        # 3 x 23.7821 bps delivery floor
CRORE: Final[float] = 1e7

HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Referer": "https://www.amfiindia.com/",
}
PAUSE: Final[float] = 1.0
MONTHS: Final[dict[str, int]] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


# =====================================================================
# AMFI Monthly Note -> monthly SIP contribution
# =====================================================================

def _norm_month(tok: str) -> Optional[str]:
    """'Apr 25', 'Apr-2026', 'April2025' -> '2025-04'. Two-digit years are
    2000-relative, which is safe for a series that starts in 2024."""
    m = re.match(r"([A-Za-z]{3,9})[\s\-\u2019\u2018']*((?:19|20)?\d{2})$",
                 tok.strip())
    if not m:
        return None
    mon = MONTHS.get(m.group(1)[:3].lower())
    if mon is None:
        return None
    yr = int(m.group(2))
    if yr < 100:
        yr += 2000
    if not (2000 <= yr <= 2100):
        return None
    return f"{yr:04d}-{mon:02d}"


# A month token as AMFI writes it, across every template seen: 'Apr 25',
# 'Jun 2024', 'Apr-2026' and -- the one that silently broke the parser the
# first time -- 'Jun\u201925' with a CURLY apostrophe.
MONTH_TOK: Final[str] = r"[A-Za-z]{3,9}\s*[\u2019\u2018'\-]?\s*(?:19|20)?\d{2}\b"


def _months_from_line(raw: str) -> list[str]:
    return [t for t in (_norm_month(x) for x in re.findall(MONTH_TOK, raw)) if t]


def _months_for(lines: list[str], i: int, n: int) -> list[str]:
    """The n month headers belonging to the value row at line `i`.

    TWO LAYOUTS, AND ONE TRAP.

      single-line  'SIP stats Apr 25  Mar 25 ...'  or
                   'Contribution Jun\u201925  May \u201925  Apr \u201925 ...'
      wrapped      'Contribution Aug-' / '2026' / 'Jul-' / '2026' / ...

    THE TRAP: the prose above these tables is full of month names -- "reaching
    8.64 crore in June 2025 from 8.56 crore in May 2025" -- so a walk that
    ACCUMULATES tokens across lines will happily build a month list out of
    narrative text and silently mis-align every value. That is exactly what
    happened, and the overlap assertion in `sip_series()` is what caught it.

    So months are taken from ONE line: the first line above the value row
    carrying at least n month tokens. Only if no such line exists is the
    wrapped layout assembled, and that walk stops the moment the year/'Mon-'
    pattern breaks rather than skipping over prose to find more."""
    for j in range(i - 1, max(-1, i - 12), -1):
        raw = lines[j].strip()
        if not raw:
            continue
        toks = _months_from_line(raw)
        if len(toks) >= n:
            return toks[:n]
    months: list[str] = []
    j = i - 1
    while j > 0 and len(months) < n:
        raw = lines[j].strip()
        if not raw:
            j -= 1
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", raw):
            mm = re.search(r"([A-Za-z]{3,9})[\-\u2019\u2018']?\s*$",
                           lines[j - 1].strip())
            if mm:
                nn = _norm_month(mm.group(1) + " " + raw)
                if nn:
                    months = [nn] + months
                    j -= 2
                    continue
        if months:
            break
        j -= 1
    return months[:n] if len(months) >= n else []


def parse_sip_table(text: str) -> dict[str, float]:
    """month 'YYYY-MM' -> SIP contribution in Rs crore, from one note.

    Two layouts occur and both are handled, because AMFI changed the template:

      single-line   'SIP stats Apr 25  Mar 25 ...'
                    'SIP monthly contributions (in crore) 26,632 25,926 ...'

      wrapped       'Contribution Aug-' / '2026' / 'Jul-' / '2026' / ...
                    'SIP monthly contribution (crore) 32,297 31,961 ...'

    The VALUE row is one line in every template seen. Month resolution is
    delegated to `_months_for`, which is where the layout handling and the
    prose trap live. Returns {} when the note carries no contribution row at
    all, which some 2024 notes do not -- that is reported, never guessed."""
    lines = text.split("\n")
    out: dict[str, float] = {}
    for i, line in enumerate(lines):
        # THE VALUE ROW MUST BE A TABLE ROW, NOT A SENTENCE. These notes are
        # full of prose that opens with the same words:
        #   "SIP monthly contributions cross Rs 0.3 lakh crore mark"
        #   "SIP monthly contributions registered ... inflows of Rs 31,002
        #    crore in December, marking a significant 5.3% on-month rise"
        # A loose search matched all of them and harvested 5.3 as a month's
        # SIP inflow. So the line must BEGIN with the label and carry a
        # parenthesised crore unit -- '(crore)' or '(in crore)' -- which every
        # observed table row has and no observed sentence does. Values are
        # taken only from after that closing parenthesis.
        #
        # A future template without the parenthesised unit would make this
        # note parse to {} and be REPORTED as carrying no contribution row.
        # That is the safe direction: it under-collects rather than
        # mis-collects.
        m_row = re.match(
            r"\s*SIP\s+monthly\s+contributions?\s*\(([^)]*crore[^)]*)\)",
            line, re.I)
        if not m_row:
            continue
        vals = [float(v.replace(",", ""))
                for v in re.findall(r"\d[\d,]*(?:\.\d+)?",
                                    line[m_row.end():])]
        if len(vals) < 3:
            continue
        months = _months_for(lines, i, len(vals))
        if not months:
            continue
        for mth, v in zip(months[:len(vals)], vals):
            out[mth] = v
    return out


def fetch_note(month: str, url: str) -> Optional[str]:
    NOTE_CACHE.mkdir(parents=True, exist_ok=True)
    path = NOTE_CACHE / f"{month}.pdf"
    if not path.exists():
        time.sleep(PAUSE)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            path.write_bytes(bytes(urllib.request.urlopen(
                req, timeout=60, context=_ctx()).read()))
        except Exception:
            return None
    try:
        rd = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
        return "\n".join(str(p.extract_text() or "") for p in rd.pages)
    except Exception:
        return None


def sip_series() -> tuple[dict[str, float], dict[str, list[str]], list[str]]:
    """(month -> Rs crore, month -> reporting notes, notes with no table).

    ASSERTS agreement across overlapping notes. A month reported differently
    by two notes raises rather than being averaged."""
    index: list[tuple[str, str]] = []
    with io.open(NOTE_INDEX, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if row and not row[0].startswith("#") and row[0] != "note_month":
                index.append((row[0], row[1]))
    series: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    empty: list[str] = []
    for note_month, url in sorted(index):
        text = fetch_note(note_month, url)
        if text is None:
            empty.append(note_month + " (fetch/parse failed)")
            continue
        table = parse_sip_table(text)
        if not table:
            empty.append(note_month + " (no contribution row)")
            continue
        for mth, v in table.items():
            if mth in series and abs(series[mth] - v) > 0.5:
                raise RuntimeError(
                    f"AMFI notes disagree on {mth}: {series[mth]:,.0f} "
                    f"(from {sources[mth]}) vs {v:,.0f} (from {note_month}). "
                    f"Not averaged -- a disagreement is an error.")
            series[mth] = v
            sources.setdefault(mth, []).append(note_month)
    return series, sources, empty


# =====================================================================
# NSE cash-market turnover, from the bhavcopy already on disk
# =====================================================================

def _day_turnover(path: Path, legacy: bool) -> Optional[float]:
    try:
        z = zipfile.ZipFile(path)
        lines = z.read(z.namelist()[0]).decode("utf-8", "replace").splitlines()
    except Exception:
        return None
    if not lines:
        return None
    head = [h.strip().upper() if legacy else h.strip()
            for h in lines[0].split(",")]
    col = "TOTTRDVAL" if legacy else "TtlTrfVal"
    if col not in head:
        return None
    i = head.index(col)
    tot = 0.0
    for line in lines[1:]:
        p = line.split(",")
        if len(p) > i:
            try:
                tot += float(p[i])
            except ValueError:
                pass
    return tot


def build_turnover() -> dict[date, float]:
    """Daily NSE cash-market turnover in rupees, summed over EVERY row and
    EVERY series of NSE's own bhavcopy. Cached to CSV after the first build."""
    if TURNOVER_CSV.exists():
        out: dict[date, float] = {}
        with io.open(TURNOVER_CSV, encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if row and not row[0].startswith("#") and row[0] != "date":
                    out[date.fromisoformat(row[0])] = float(row[1])
        return out
    rows: list[tuple[date, float]] = []
    for tag, legacy in (("legacy", True), ("udiff", False)):
        d = BHAV / tag
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.zip")):
            t = _day_turnover(f, legacy)
            if t and t > 0:
                rows.append((date.fromisoformat(f.stem), t))
    best: dict[date, float] = {}
    for d0, t in rows:              # legacy first, so it wins on overlap days
        best.setdefault(d0, t)
    TURNOVER_CSV.write_text(
        "# NSE cash-market daily turnover, summed over every row and every\n"
        "# series of NSE's own daily bhavcopy (TOTTRDVAL / TtlTrfVal), from\n"
        "# the archive fetched by src/fetch_cash_bhavcopy.py.\n"
        "# Where both formats exist the LEGACY file is used, and the two were\n"
        "# verified identical on their 2024 overlap (commit dcad806).\n"
        f"# built    {date.today().isoformat()}   {len(best):,} trading days\n"
        "date,turnover_rupees\n"
        + "".join(f"{d0.isoformat()},{v:.2f}\n" for d0, v in sorted(best.items())),
        encoding="utf-8")
    return best


def sigma_generous(months: list[str]) -> tuple[float, float]:
    """(generous sigma, median rolling sigma) of NIFTY 500 daily returns.

    The generous figure is the SIGMA_PCTILE-th percentile of the rolling
    SIGMA_WINDOW-session standard deviation over the covered months: every
    deployment is assumed to land in a market as volatile as its worst 5%."""
    days: list[tuple[date, float]] = []
    with io.open(NIFTY500, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if row and not row[0].startswith("#") and row[0] != "date":
                days.append((date.fromisoformat(row[0]), float(row[2])))
    days.sort()
    lo = min(months)
    hi = max(months)
    closes = np.array([c for d0, c in days
                       if lo <= f"{d0.year:04d}-{d0.month:02d}" <= hi])
    rets = closes[1:] / closes[:-1] - 1.0
    roll = np.array([rets[i:i + SIGMA_WINDOW].std(ddof=1)
                     for i in range(rets.size - SIGMA_WINDOW + 1)])
    return (float(np.percentile(roll, SIGMA_PCTILE)), float(np.median(roll)))


# =====================================================================
# The arithmetic
# =====================================================================

def implied_move_bps(q: float, v: float, sigma: float, y: float) -> float:
    """Y * sigma * sqrt(Q/V), in basis points of the index."""
    if v <= 0.0:
        return float("nan")
    return y * sigma * math.sqrt(q / v) * 10_000.0


def breakeven_y(q: float, v: float, sigma: float, bar_bps: float) -> float:
    """The Y at which the implied move would exactly reach `bar_bps`.
    Linear in Y, so this is exact, not a search."""
    base = implied_move_bps(q, v, sigma, 1.0)
    return float("inf") if base <= 0.0 else bar_bps / base


# =====================================================================
# DRY RUN -- known answers, before any real figure is produced
# =====================================================================

def dry_run() -> bool:
    ok = True
    print("\n  DRY RUN -- arithmetic and parsing against known answers")

    # ARM 1: the impact formula
    got = implied_move_bps(0.25, 1.0, 0.01, 1.5)
    want = 1.5 * 0.01 * 0.5 * 10_000.0          # sqrt(0.25) = 0.5 -> 75 bps
    a1 = abs(got - want) < 1e-9
    ok &= a1
    print(f"    1  Y=1.5, sigma=1%, Q/V=0.25 -> {got:.4f} bps, want "
          f"{want:.4f}  " + ("PASS" if a1 else "*** FAIL ***"))

    # ARM 2: break-even Y is exact
    be = breakeven_y(0.25, 1.0, 0.01, 71.35)
    a2 = abs(be - 71.35 / (0.01 * 0.5 * 10_000.0)) < 1e-12
    ok &= a2
    print(f"    2  break-even Y for a 71.35 bps bar at that cell: {be:.6f}  "
          + ("PASS" if a2 else "*** FAIL ***"))
    chk = implied_move_bps(0.25, 1.0, 0.01, be)
    a2b = abs(chk - 71.35) < 1e-9
    ok &= a2b
    print(f"       and plugging it back gives {chk:.4f} bps  "
          + ("PASS" if a2b else "*** FAIL ***"))

    # ARM 3: the single-line note layout
    single = ("SIP trends\n"
              "SIP stats Apr 25  Mar 25 Feb 25 Jan 25 Dec 24 Nov 24\n"
              "No. of Contributing SIP accounts (in crore) 8.38 8.11 8.26 "
              "8.35 8.27 7.97\n"
              "SIP monthly contributions (in crore) 26,632 25,926 25,999 "
              "26,400 26,459 25,320\n")
    g3 = parse_sip_table(single)
    w3 = {"2025-04": 26632.0, "2025-03": 25926.0, "2025-02": 25999.0,
          "2025-01": 26400.0, "2024-12": 26459.0, "2024-11": 25320.0}
    a3 = g3 == w3
    ok &= a3
    print(f"    3  single-line layout parses {len(g3)}/6 months correctly  "
          + ("PASS" if a3 else f"*** FAIL *** got {g3}"))

    # ARM 4: the wrapped layout
    wrapped = ("SIP trend\nContribution Aug-\n2026 \nJul-\n2026 \nJun-\n2026 \n"
               "May-\n2026 \nApr-\n2026 \nMar-\n2026 \nFeb-\n2026 \n"
               "Number of contributing SIP accounts (crore) 10.02 9.90 9.78 "
               "9.64 9.65 9.72 9.44\n"
               "SIP monthly contribution (crore) 32,297 31,961 31,781 30,954 "
               "31,115 32,087 29,845\n")
    g4 = parse_sip_table(wrapped)
    a4 = (g4.get("2026-08") == 32297.0 and g4.get("2026-02") == 29845.0
          and len(g4) == 7)
    ok &= a4
    print(f"    4  wrapped layout parses {len(g4)}/7 months, Aug-2026 "
          f"{g4.get('2026-08')}  " + ("PASS" if a4 else f"*** FAIL *** {g4}"))

    # ARM 5: a note with NO contribution row yields nothing, never a guess
    none_row = ("SIP stats Jun 2024 May 2024 Apr 2024\n"
                "SIP assets 12.44 11.53 11.26\n"
                "SIP accounts 8.99 8.76 8.70\n")
    g5 = parse_sip_table(none_row)
    a5 = g5 == {}
    ok &= a5
    print(f"    5  note without a contribution row returns {{}}, not a guess  "
          + ("PASS" if a5 else f"*** FAIL *** {g5}"))

    # ARM 5b: the CURLY-APOSTROPHE header, which the first parser missed
    curly = ("Record-high SIP contribution in June\n"
             "SIP trend\n"
             "Contribution Jun\u201925  May \u201925  Apr \u201925  "
             "Mar \u201925 Feb \u201925 Jan \u201925\n"
             "No. of contributing SIP accounts (crore) 8.64 8.56 8.38 8.11 "
             "8.26 8.35\n"
             "SIP monthly contribution (crore) 27,269 26,688 26,632 25,926 "
             "25,999 26,400\n")
    g5b = parse_sip_table(curly)
    w5b = {"2025-06": 27269.0, "2025-05": 26688.0, "2025-04": 26632.0,
           "2025-03": 25926.0, "2025-02": 25999.0, "2025-01": 26400.0}
    a5b = g5b == w5b
    ok &= a5b
    print(f"    5b curly-apostrophe header (Jun\u201925) parses {len(g5b)}/6 "
          f"correctly  " + ("PASS" if a5b else f"*** FAIL *** {g5b}"))

    # ARM 5c: PROSE ABOVE THE TABLE MUST NOT CONTAMINATE THE MONTHS.
    # This is the bug the overlap assertion caught on real data: narrative
    # text says "reaching 8.64 crore in June 2025 from 8.56 crore in May
    # 2025", and a parser that accumulates tokens across lines builds its
    # month list out of that and mis-aligns every value.
    prosey = ("The number of contributing SIP accounts reached 8.64 crore in "
              "June 2025 from 8.56 crore in May 2025.\n"
              "Record-high SIP contribution in June\n"
              "SIP trend\n"
              "Contribution Jun\u201925  May \u201925  Apr \u201925  "
              "Mar \u201925 Feb \u201925 Jan \u201925\n"
              "No. of contributing SIP accounts (crore) 8.64 8.56 8.38 8.11 "
              "8.26 8.35\n"
              "SIP monthly contribution (crore) 27,269 26,688 26,632 25,926 "
              "25,999 26,400\n")
    g5c = parse_sip_table(prosey)
    a5c = g5c == w5b
    ok &= a5c
    print(f"    5c the same table under month-bearing PROSE still parses to "
          f"the header, not the prose  "
          + ("PASS" if a5c else f"*** FAIL *** {g5c}"))

    # ARM 5d: PROSE THAT OPENS WITH THE LABEL MUST BE IGNORED.
    # Real text from the Dec-2025 note, where a loose match harvested the
    # "5.3%" on-month change as a month's SIP inflow. The overlap assertion
    # caught it; this arm keeps it caught.
    dec = ("SIP monthly contributions cross Rs 0.3 lakh crore mark\n"
           "SIP monthly contributions registered highest ever inflows of Rs "
           "31,002 crore in December, marking a significant 5.3%\n"
           "on-month rise, and a 17.2% on -year growth.\n"
           "SIP monthly contributions at peak\n"
           "SIP trend\n"
           "Contribution Dec 2025  Nov 2025  Oct 2025  Sep 2025  Aug 2025  "
           "Jul 2025\n"
           "No. of contributing SIP accounts (crore) 9.79 9.43 9.45 9.25 "
           "8.99 9.11\n"
           "SIP monthly contribution (crore) 31,002 29,445 29,529 29,361 "
           "28,265 28,464\n"
           "SIP monthly contributions have touched an all-time high of over "
           "31,000 crore.\n")
    g5d = parse_sip_table(dec)
    w5d = {"2025-12": 31002.0, "2025-11": 29445.0, "2025-10": 29529.0,
           "2025-09": 29361.0, "2025-08": 28265.0, "2025-07": 28464.0}
    a5d = g5d == w5d
    ok &= a5d
    print(f"    5d four PROSE lines opening with the same label are ignored; "
          f"only the table row parses  "
          + ("PASS" if a5d else f"*** FAIL *** {g5d}"))

    # ARM 6: sigma percentile on a series with a known answer
    rng = np.random.default_rng(3)
    fake = rng.normal(0.0, 0.01, 4000)
    roll = np.array([fake[i:i + SIGMA_WINDOW].std(ddof=1)
                     for i in range(fake.size - SIGMA_WINDOW + 1)])
    p95 = float(np.percentile(roll, 95.0))
    med = float(np.median(roll))
    a6 = p95 > med and abs(med - 0.01) < 0.002
    ok &= a6
    print(f"    6  rolling-{SIGMA_WINDOW} sigma on N(0,1%): median {med:.5f}, "
          f"p95 {p95:.5f}, p95 > median  " + ("PASS" if a6 else "*** FAIL ***"))

    # ARM 7: max concentration really is the generous end
    #        spreading one month over k dates divides the move by sqrt(k)
    one = implied_move_bps(1.0, 100.0, 0.01, 1.5)
    four = implied_move_bps(0.25, 100.0, 0.01, 1.5)
    a7 = abs(one / four - 2.0) < 1e-9
    ok &= a7
    print(f"    7  splitting a month over 4 dates cuts the move by exactly "
          f"2.000x ({one:.3f} -> {four:.3f})  "
          + ("PASS" if a7 else "*** FAIL ***"))

    print(f"\n  DRY RUN: {'ALL ARMS PASS' if ok else '*** FAILED ***'}")
    return bool(ok)


def main() -> int:
    print("=" * 78)
    print("  PRE-CHECK -- SIP flow timing, arithmetic only")
    print("  executes PRECHECK_SIP_TIMING.md")
    print("=" * 78)
    if not dry_run():
        print("\n  DRY RUN FAILED -- the pre-check does not run.")
        return 1
    if "--dry-run" in sys.argv:
        return 0

    print("\n  SIP SERIES from AMFI Monthly Notes")
    series, sources, empty = sip_series()
    months = sorted(series)
    print(f"    {len(months)} months recovered: {months[0]} -> {months[-1]}")
    multi = [m for m in months if len(sources[m]) > 1]
    print(f"    {len(multi)} of them reported by more than one note; every "
          f"overlap AGREES (a disagreement raises)")
    print(f"    max overlap: {max(len(sources[m]) for m in months)} notes on "
          f"one month")
    if empty:
        print(f"    {len(empty)} notes carried no contribution row: "
              f"{', '.join(empty[:6])}" + (" ..." if len(empty) > 6 else ""))
    SIP_CSV.write_text(
        "# AMFI monthly SIP contribution, Rs crore.\n"
        "# source   AMFI Monthly Note PDFs, index in "
        "data/amfi_monthly_notes_index.csv\n"
        f"# built    {date.today().isoformat()}\n"
        "# NOTE     AMFI's machine-readable SIP archive begins with the "
        "June-2024 note.\n"
        "#          This is NOT a series since 2016 -- see "
        "PRECHECK_SIP_TIMING.md section 4.\n"
        "# overlaps Every month reported by more than one note was checked "
        "for agreement.\n"
        "month,sip_crore,reporting_notes\n"
        + "".join(f"{m},{series[m]:.0f},{' '.join(sources[m])}\n"
                 for m in months), encoding="utf-8")

    print("\n  NSE CASH-MARKET TURNOVER")
    turn = build_turnover()
    print(f"    {len(turn):,} trading days on disk")

    sig, sig_med = sigma_generous(months)
    print(f"\n  NIFTY 500 VOLATILITY over {months[0]} -> {months[-1]}")
    print(f"    median rolling-{SIGMA_WINDOW} daily sigma {sig_med:.5f} "
          f"({sig_med * 100:.3f}%)")
    print(f"    GENEROUS sigma, {SIGMA_PCTILE:.0f}th percentile "
          f"{sig:.5f} ({sig * 100:.3f}%)")

    print(f"\n  PER MONTH -- whole month deployed on ONE date, Y = "
          f"{Y_GENEROUS}, sigma = {sig * 100:.3f}%")
    print(f"    {'month':<9}{'SIP Rs cr':>12}{'mean daily turnover Rs cr':>28}"
          f"{'Q/V':>9}{'move bps':>10}")
    rows: list[tuple[str, float, float, float, float]] = []
    for m in months:
        yr, mo = int(m[:4]), int(m[5:])
        vals = [v for d0, v in turn.items() if d0.year == yr and d0.month == mo]
        if not vals:
            print(f"    {m:<9}{series[m]:>12,.0f}{'no turnover data':>28}")
            continue
        v = float(np.mean(vals))
        q = series[m] * CRORE
        bps = implied_move_bps(q, v, sig, Y_GENEROUS)
        rows.append((m, series[m], v, q / v, bps))
    for m, cr, v, ratio, bps in rows:
        print(f"    {m:<9}{cr:>12,.0f}{v / CRORE:>28,.0f}{ratio:>9.3f}"
              f"{bps:>10.2f}")

    biggest = max(rows, key=lambda r: r[4])
    med_bps = float(np.median([r[4] for r in rows]))
    med_ratio = float(np.median([r[3] for r in rows]))
    over = [r for r in rows if r[4] >= BAR_BPS]

    print(f"\n  SUMMARY  ({len(rows)} months)")
    print(f"    LARGEST implied move   {biggest[0]}   SIP Rs "
          f"{biggest[1]:,.0f} cr, Q/V {biggest[3]:.3f}, "
          f"{biggest[4]:.2f} bps")
    print(f"    MEDIAN month           Q/V {med_ratio:.3f}, {med_bps:.2f} bps"
          f"   (over the covered window only, NOT since 2016)")
    print(f"    months at or above the {BAR_BPS:.2f} bps bar: {len(over)}")
    print(f"    at the consensus Y = {Y_CONSENSUS}: largest month "
          f"{implied_move_bps(biggest[1] * CRORE, biggest[2], sig, Y_CONSENSUS):.2f}"
          f" bps")
    be = breakeven_y(biggest[1] * CRORE, biggest[2], sig, BAR_BPS)
    print(f"    BREAK-EVEN Y for the largest month: {be:.3f}   "
          f"({be / Y_CONSENSUS:.2f}x the consensus, "
          f"{be / Y_GENEROUS:.2f}x the generous Y used here)")
    # Impact goes as sqrt(Q), so the flow ratio that moves the implied move
    # onto the bar is (bar/move)^2. Phrased by DIRECTION, because "0.34x" is
    # meaningless without saying which way.
    need = (BAR_BPS / biggest[4]) ** 2
    if biggest[4] >= BAR_BPS:
        print(f"    HEADROOM: the largest month's flow could fall to "
              f"{need:.2f}x of itself (Rs {biggest[1] * need:,.0f} cr)")
        print(f"    before the implied move drops to the bar, holding "
              f"turnover, sigma and Y fixed.")
    else:
        print(f"    the largest month's flow would have to RISE to "
              f"{need:.2f}x (Rs {biggest[1] * need:,.0f} cr) to reach the "
              f"bar,")
        print(f"    holding turnover, sigma and Y fixed.")

    # The single most important caveat, printed with the verdict rather than
    # left in the document: Q/V here is FAR outside the range the square-root
    # law was estimated on.
    print(f"\n    RANGE WARNING: the square-root law is calibrated on "
          f"single-name metaorders of a")
    print(f"    few percent of daily volume. The Q/V values above run "
          f"{min(r[3] for r in rows):.3f} to {max(r[3] for r in rows):.3f},")
    print(f"    an order of magnitude beyond that. Every figure here is "
          f"EXTRAPOLATION, not measurement.")

    passed = biggest[4] >= BAR_BPS
    print("\n" + "=" * 78)
    if passed:
        print(f"  VERDICT: DOES NOT CLOSE -- largest implied move "
              f"{biggest[4]:.2f} bps >= {BAR_BPS:.2f} bps")
    else:
        print(f"  VERDICT: PHASE 3 CLOSES -- largest implied move "
              f"{biggest[4]:.2f} bps < {BAR_BPS:.2f} bps")
        print(f"  shortfall {BAR_BPS - biggest[4]:.2f} bps "
              f"({biggest[4] / BAR_BPS:.3f}x the bar)")
    print("=" * 78)

    RESULTS.mkdir(parents=True, exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
