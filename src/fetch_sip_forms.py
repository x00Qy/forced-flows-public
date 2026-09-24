r"""
fetch_sip_forms.py -- download and persist the published SIP application forms
the SIP date set is sourced from, and extract each form's enumerated dates.

Fetch-and-cache only. It decides nothing; GATE_SIP_TIMING.md fixes the date
set and cites what this script persists.

=== WHY THIS EXISTS, AND WHAT IT FOUND ===

The premise of a "SIP day versus other day" test is that SIP debits land on a
small, known set of dates. Checked against the actual forms of the largest
AMCs on 2026-09-22, that premise is only half true:

    SBI            1, 5, 10, 15, 20, 25, 30     default 10th
    ICICI Pru      1, 7, 10, 15, 20, 25         default 10th
    Kotak          1, 7, 10, 14, 15, 21, 25, 28
    Aditya Birla   1, 7, 10, 15, 20, 28
    HDFC           every date 1-31              "one or more of the following"
    Nippon India   any date, free field         default 10th
    Axis           any date except 29/30/31

THREE OF THE LARGEST AMCs NO LONGER RESTRICT THE DATE AT ALL. On the union of
enumerated dates, roughly half of all trading days are a SIP date for some
large fund, and with a D->D+2 window that covers almost the whole month --
which destroys the contrast the test depends on rather than protecting it.

That is why GATE_SIP_TIMING.md fixes the date set at THE 10TH ALONE: it is the
default at three of the five largest AMCs, and defaults are sticky.

VERIFICATION. SBI and ICICI were each extracted from two independent hosts and
agreed exactly, which is the check that the text extraction is reading the form
rather than inventing a plausible list.

Run:  python src/fetch_sip_forms.py
"""
from __future__ import annotations

import io
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Final, Optional

import pypdf
from require_data import guard

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FORMS: Final[Path] = ROOT / "data" / "sip_forms"
INDEX: Final[Path] = ROOT / "data" / "sip_form_dates.csv"
HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}
PAUSE: Final[float] = 1.0

# (slug, AMC, url). Two hosts each for SBI and ICICI, deliberately: agreement
# across independent copies is what makes the extraction believable.
SOURCES: Final[tuple[tuple[str, str, str], ...]] = (
    ("sbi_a", "SBI",
     "https://www.investcare.org/sip_form/sbi_sip.pdf"),
    ("sbi_b", "SBI",
     "https://www.mauryasecurities.com/sip_form/sbi_sip.pdf"),
    ("icici_a", "ICICI Prudential",
     "https://skpsecurities.com/assets/pdfs/mf/ICICI%20Pru%20MF_Comon%20&%20SIP%20NACH.pdf"),
    ("icici_b", "ICICI Prudential",
     "https://www.fslindia.com/pdf/ICICI/SIP%20FORM%20NEW%20OTM%20of%20ICICI.pdf"),
    ("hdfc", "HDFC",
     "https://www.mauryasecurities.com/sip_form/hdfc_sip.pdf"),
    ("kotak", "Kotak Mahindra",
     "https://www.investcare.org/sip_form/kotak_sip.pdf"),
    ("birla", "Aditya Birla Sun Life",
     "https://www.investcare.org/sip_form/birla_sip.pdf"),
    ("nippon", "Nippon India",
     "https://mf.nipponindiaim.com/InvestorServices/EditableForms/"
     "NipponIndia-SIP+Form-Editable.pdf"),
    ("axis", "Axis",
     "https://www.mauryasecurities.com/sip_form/axis_sip.pdf"),
)

_DATE: Final[re.Pattern[str]] = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")
_LABEL: Final[re.Pattern[str]] = re.compile(
    r"(SIP\s*(?:\+)?\s*Date|Debit\s*Date|Instal+ment\s*Date|Investment\s*Dates)",
    re.I)


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch(slug: str, url: str) -> Optional[bytes]:
    FORMS.mkdir(parents=True, exist_ok=True)
    path = FORMS / f"{slug}.pdf"
    if path.exists():
        return path.read_bytes()
    time.sleep(PAUSE)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        body = bytes(urllib.request.urlopen(
            req, timeout=60, context=_ctx()).read())
    except Exception:
        return None
    path.write_bytes(body)
    return body


def extract_dates(body: bytes) -> tuple[list[int], str]:
    """(dates found near a SIP-date label, the context they came from).

    Deliberately reports the LONGEST enumerated run near such a label rather
    than every ordinal in the document: these forms are full of ordinals in
    terms and conditions ('the 29th to 31st of a month')."""
    try:
        text = "\n".join(str(p.extract_text() or "")
                         for p in pypdf.PdfReader(io.BytesIO(body)).pages)
    except Exception:
        return [], "(unreadable)"
    best: tuple[list[int], str] = ([], "")
    for m in _LABEL.finditer(text):
        seg = re.sub(r"\s+", " ", text[m.start():m.start() + 240])
        ds = sorted({int(x) for x in _DATE.findall(seg) if 1 <= int(x) <= 31})
        if len(ds) > len(best[0]):
            best = (ds, seg[:200])
    return best


def main() -> int:
    print(f"fetch_sip_forms: {len(SOURCES)} published forms")
    rows: list[tuple[str, str, str, list[int], str]] = []
    for slug, amc, url in SOURCES:
        body = fetch(slug, url)
        if body is None:
            print(f"  {slug:<10} {amc:<24} FETCH FAILED")
            rows.append((slug, amc, url, [], "(fetch failed)"))
            continue
        ds, ctx = extract_dates(body)
        print(f"  {slug:<10} {amc:<24} {len(body):>9,}B  dates {ds}")
        rows.append((slug, amc, url, ds, ctx))

    # cross-check the two-host pairs
    print("\n  INDEPENDENT-HOST AGREEMENT")
    for a, b, name in (("sbi_a", "sbi_b", "SBI"),
                       ("icici_a", "icici_b", "ICICI Prudential")):
        da = next((r[3] for r in rows if r[0] == a), [])
        db = next((r[3] for r in rows if r[0] == b), [])
        same = da == db and bool(da)
        print(f"    {name:<20} {da} vs {db}   "
              + ("AGREE" if same else "*** DISAGREE ***"))

    INDEX.write_text(
        "# SIP dates as enumerated on published SIP application forms.\n"
        f"# fetched  {date.today().isoformat()}; PDFs persisted under "
        "data/sip_forms/\n"
        "# NOTE     HDFC enumerates every date 1-31; Nippon and Axis use a\n"
        "#          free date field. Three of the five largest AMCs therefore\n"
        "#          do NOT restrict the date, which is why GATE_SIP_TIMING.md\n"
        "#          fixes the set at the 10th alone -- the DEFAULT at SBI,\n"
        "#          ICICI Prudential and Nippon India.\n"
        "# dates    the longest enumerated run near a SIP-date label; these\n"
        "#          forms carry many other ordinals in their terms.\n"
        "slug,amc,dates,url,context\n"
        + "".join(f'{s},{a},"{" ".join(str(x) for x in d)}",{u},'
                 f'"{c.replace(chr(34), chr(39))}"\n'
                 for s, a, u, d, c in rows), encoding="utf-8")
    print(f"\n  wrote {INDEX}")
    print(f"  persisted {len(list(FORMS.glob('*.pdf')))} PDFs to {FORMS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(guard(main))
