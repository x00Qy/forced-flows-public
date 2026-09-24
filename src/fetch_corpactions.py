r"""
fetch_corpactions.py -- download and persist NSE's corporate-action records for
the ban-list stocks, and classify each ex-date. Fetch-and-cache only.

SOURCE
    https://www.nseindia.com/api/corporates-corporateActions
        ?index=equities&symbol=SYM&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
    JSON, one object per action, fields used: symbol, exDate, subject.
    Probed 2026-09-22: BHEL over 2015-01-01 -> 2026-09-22 returns 18 records in
    a single request, so no chunking is needed.

WHY THIS IS FETCHED AT ALL. `PREVCLOSE` in the cash bhavcopy is NOT
corporate-action adjusted -- verified on BHEL (Bonus 1:2, ex 2017-09-28,
PREVCLOSE 124.65 = the raw prior close, ratio 1.0000) and on CANBK (split, ex
2024-05-15, UDiFF `PrvsClsgPric` ratio 1.0000). An ex-date inside an event
window therefore injects a raw -33% or -79% "abnormal return".

GATE_BAN_LIST_NUISANCE.md §5 handles this by EXCLUSION, not adjustment: an
event whose window contains an ex-date on D+1..D+4 is dropped. An ex-date on D
itself is harmless, because entry is at the OPEN of D and the open is already
the ex-price.

=== CLASSIFICATION, AND WHY IT IS DELIBERATELY BLUNT ===

`subject` is free text written by a human ("Bonus 1:2", "Annual General
Meeting/Dividend - Re 0.40/- Per Share", "Face Value Split From Rs.10 To Rs.2").
`classify()` tags each record as bonus / split / rights / dividend / other by
keyword.

The classification is used ONLY to report the mix. THE EXCLUSION RULE DOES NOT
DEPEND ON IT: every record with a parseable ex-date in D+1..D+4 excludes the
event, whatever its subject reads. A keyword table that silently fails to match
some phrasing would otherwise let a split through, and the whole point is that
one unadjusted split is worth -79%. Matching only to report, never to decide,
is what keeps a text-parsing bug from becoming a data-integrity bug.

'other' records -- AGMs with no price effect, name changes -- therefore exclude
events too. That is deliberately conservative: it costs sample size, never
validity, and the cost is reported.

=== THE RENAME TRAP, AND WHY IT IS NOT HAND-MAPPED ===

The API is keyed on a company's CURRENT symbol. A stock that entered the ban
list under an old ticker returns ZERO records when queried under that ticker --
measured on the first run: 11 of 141 symbols came back empty, among them
AMARAJABAT, CADILAHC, IBULHSGFIN, L&TFH, PVR and TATAMOTORS. Every one of them
is a live company that has simply been renamed.

That failure is SILENT and it is the dangerous direction: no records means no
ex-dates means nothing excluded, so a split inside an event window survives
into the sample as a real return. It would not have shown up as an error.

The fix uses NSE's own record, not a hand-written table:

    https://nsearchives.nseindia.com/content/equities/symbolchange.csv
    rows of (company name, OLD symbol, NEW symbol, change date), no header.

`resolve_symbol()` follows that chain -- transitively, since a symbol can be
renamed twice -- and re-queries under the current name. The mapping actually
used is written into the output file so the substitution is visible rather than
buried. A symbol that is still empty after resolution is REPORTED, and
`gate_ban_list_nuisance.py` drops that stock's events rather than treating an
absent corporate-action record as evidence of no corporate action.

POLITENESS. ONE worker and a 1.0s pause. 141 requests against www.nseindia.com
(not the archive host), slower per request because this endpoint is the
API-backed one and is the more aggressively rate-limited of the two.

Run:  python src/fetch_corpactions.py
"""
from __future__ import annotations

import csv
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Final, Optional
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CACHE: Final[Path] = ROOT / "data" / "corpactions"
SECBAN: Final[Path] = ROOT / "data" / "fo_secban_2015_2026.csv"
OUT_CSV: Final[Path] = ROOT / "data" / "corpactions_banlist_2015_2026.csv"
HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}
SYMCHANGE_URL: Final[str] = ("https://nsearchives.nseindia.com/content/"
                             "equities/symbolchange.csv")
SYMCHANGE_CACHE: Final[Path] = ROOT / "data" / "corpactions" / "_symbolchange.csv"
START: Final[date] = date(2015, 1, 1)
END: Final[date] = date(2026, 9, 22)
PAUSE: Final[float] = 1.0

# Reporting only. The exclusion rule ignores this -- see the module docstring.
KEYWORDS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("bonus", ("bonus",)),
    ("split", ("split", "sub-division", "subdivision", "face value")),
    ("rights", ("rights",)),
    ("dividend", ("dividend",)),
)


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def banlist_symbols() -> list[str]:
    """The 141 distinct symbols in the consolidated ban archive."""
    syms: set[str] = set()
    with io.open(SECBAN, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0] == "ban_date":
                continue
            if len(row) > 1 and row[1] != "__NONE__":
                syms.add(row[1].strip())
    return sorted(syms)


def fetch_symbol(sym: str) -> Optional[str]:
    """Raw JSON text for one symbol over the whole span. Cached."""
    path = CACHE / f"{sym}.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    CACHE.mkdir(parents=True, exist_ok=True)
    url = ("https://www.nseindia.com/api/corporates-corporateActions"
           f"?index=equities&symbol={urllib.parse.quote(sym)}"
           f"&from_date={START.strftime('%d-%m-%Y')}"
           f"&to_date={END.strftime('%d-%m-%Y')}")
    time.sleep(PAUSE)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        raw = urllib.request.urlopen(req, timeout=40, context=_ctx()).read()
        text = str(bytes(raw).decode("utf-8", "replace"))
        json.loads(text)                       # reject a truncated body
        path.write_text(text, encoding="utf-8")
        return text
    except Exception:
        return None                            # transient: do NOT cache


def symbol_changes() -> dict[str, str]:
    """OLD symbol -> NEW symbol, from NSE's own symbolchange.csv.

    The file has no header and its first column is the company name, so the
    mapping is columns 1 -> 2. Cached like every other input."""
    if SYMCHANGE_CACHE.exists():
        text = SYMCHANGE_CACHE.read_text(encoding="utf-8")
    else:
        SYMCHANGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        time.sleep(PAUSE)
        req = urllib.request.Request(SYMCHANGE_URL, headers=HEADERS)
        raw = urllib.request.urlopen(req, timeout=40, context=_ctx()).read()
        text = str(bytes(raw).decode("utf-8", "replace"))
        SYMCHANGE_CACHE.write_text(text, encoding="utf-8")
    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 3:
            old, new = row[1].strip(), row[2].strip()
            if old and new and old != new:
                out[old] = new
    return out


def resolve_symbol(sym: str, changes: dict[str, str]) -> str:
    """Follow the rename chain to the current symbol.

    Transitive, because a ticker can be renamed more than once, and cycle-safe
    because a malformed record must not hang the fetcher."""
    seen = {sym}
    cur = sym
    for _ in range(8):
        nxt = changes.get(cur)
        if nxt is None or nxt in seen:
            break
        seen.add(nxt)
        cur = nxt
    return cur


def classify(subject: str) -> str:
    low = subject.lower()
    for tag, words in KEYWORDS:
        if any(w in low for w in words):
            return tag
    return "other"


def parse_exdate(raw: object) -> Optional[date]:
    """NSE writes ex-dates as '28-Sep-2017', sometimes padded or '-'."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s == "-":
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def main() -> int:
    syms = banlist_symbols()
    changes = symbol_changes()
    renamed = {s: resolve_symbol(s, changes) for s in syms}
    renamed = {k: v for k, v in renamed.items() if k != v}
    print(f"fetch_corpactions: {len(syms)} ban-list symbols, "
          f"{START} -> {END}, 1 worker, {PAUSE}s pause", flush=True)
    print(f"  symbolchange.csv: {len(changes):,} renames on record; "
          f"{len(renamed)} of the ban-list symbols are renamed", flush=True)
    for old, new in sorted(renamed.items()):
        print(f"    {old:<14} -> {new}", flush=True)

    rows: list[tuple[date, str, str, str]] = []
    failed: list[str] = []
    no_records: list[str] = []
    unparsed = 0
    for i, sym in enumerate(syms, 1):
        # Query under the CURRENT name, but keep the BAN-LIST name on every row
        # so the join back to the event set needs no second mapping.
        text = fetch_symbol(resolve_symbol(sym, changes))
        if text is None:
            failed.append(sym)
            continue
        try:
            recs = json.loads(text)
        except Exception:
            failed.append(sym)
            continue
        if not isinstance(recs, list) or not recs:
            no_records.append(sym)
            continue
        n_before = len(rows)
        for r in recs:
            if not isinstance(r, dict):
                continue
            ex = parse_exdate(r.get("exDate"))
            if ex is None:
                unparsed += 1
                continue
            subj = str(r.get("subject", "")).strip().replace(",", ";")
            rows.append((ex, sym, classify(subj), subj))
        if len(rows) == n_before:
            no_records.append(sym)
        if i % 25 == 0:
            print(f"  {i}/{len(syms)}  records {len(rows):,}  "
                  f"failed {len(failed)}  empty {len(no_records)}", flush=True)

    rows.sort()
    mix: dict[str, int] = {}
    for _, _, tag, _ in rows:
        mix[tag] = mix.get(tag, 0) + 1

    OUT_CSV.write_text(
        "# NSE corporate actions for the 141 ban-list symbols.\n"
        "# source   https://www.nseindia.com/api/corporates-corporateActions"
        "?index=equities&symbol=SYM&from_date=..&to_date=..\n"
        f"# fetched  {date.today().isoformat()}\n"
        f"# span     {START} -> {END}\n"
        f"# rows     {len(rows):,} records with a parseable ex-date; "
        f"{unparsed:,} records had none ('-' or blank)\n"
        f"# symbols  {len(syms) - len(failed) - len(no_records)} returned "
        f"records, {len(no_records)} returned none, {len(failed)} failed\n"
        f"# renames  {len(renamed)} ban-list symbols queried under their CURRENT\n"
        "#          name, resolved from NSE's own symbolchange.csv (the API is\n"
        "#          keyed on the current symbol and returns NOTHING for an old\n"
        "#          one -- a silent miss that would leave splits unexcluded):\n"
        + "".join(f"#            {o} -> {n}\n" for o, n in sorted(renamed.items()))
        + "#          The `symbol` column below is the BAN-LIST symbol throughout.\n"
        "# kind     KEYWORD-CLASSIFIED FOR REPORTING ONLY. The D+1..D+4\n"
        "#          exclusion rule uses the ex-date alone and ignores this\n"
        "#          column, so a keyword miss cannot let a split through.\n"
        "date,symbol,kind,subject\n"
        + "".join(f"{d.isoformat()},{s},{k},{subj}\n" for d, s, k, subj in rows),
        encoding="utf-8")

    print(f"\nDONE  {len(rows):,} ex-dated records -> {OUT_CSV}", flush=True)
    print(f"      mix: " + "  ".join(f"{k} {v:,}" for k, v in
                                     sorted(mix.items(), key=lambda x: -x[1])))
    print(f"      {unparsed:,} records had no parseable ex-date")
    print(f"      {len(renamed)} symbols queried under a resolved current name")
    if no_records:
        print(f"      *** {len(no_records)} symbols returned NO records even "
              f"after rename resolution:")
        print(f"      *** {', '.join(no_records)}")
        print(f"      *** An absent corporate-action record is NOT evidence of "
              f"no corporate action.")
        print(f"      *** gate_ban_list_nuisance.py drops these stocks' events "
              f"rather than keep them unprotected.")
    if failed:
        print(f"      *** {len(failed)} symbols FAILED and are not cached: "
              f"{', '.join(failed)}")
        print(f"      *** re-run to retry them; the gate must not run on a "
              f"partial corporate-action record.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
