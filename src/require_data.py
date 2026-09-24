r"""
require_data.py -- turn a missing data file into instructions, not a traceback.

=== WHY THIS EXISTS ===

None of this repository's data is committed. NSE and NSE Indices both prohibit
redistribution in writing (both clauses are quoted in README.md), so every input is
FETCHED, never shipped. A fresh clone therefore has an empty `data/` and every
analysis script fails on its first read.

That failure is expected. What it must not be is a bare traceback. A reader who
clones this to check a number should be told which file is absent and which
script regenerates it, in one screen, with no Python knowledge required.

Same defect class, and the same fix, as `require_yalgo_core.py`: the text exists
ONCE, here, rather than drifting across fourteen scripts.

=== THE RULE THIS APPLIES, STATED PRECISELY ===

  A missing path UNDER `data/` is absent input. It is reported as a clean
  message and exit code 2.

  A missing path ANYWHERE ELSE is a bug, and is re-raised with its traceback
  intact.

That distinction is the whole point. Swallowing every FileNotFoundError would
hide a genuine defect behind a friendly banner the first time one appeared on a
code path -- which is exactly the kind of error this project has spent its
addendum chain catching.

Scripts use it at the entry point only:

    from require_data import guard
    if __name__ == "__main__":
        raise SystemExit(guard(main))

No call site changes. Existing `FileNotFoundError`s already carrying good
instructions -- `precheck_ban_list.py`, `precheck_index_recon.py`,
`consolidate_secban.py` -- keep their own text; this only strips the traceback
and adds the fetch command. Reads that had no guidance at all, such as
`precheck_sip_timing.py`'s bare `io.open`, get the PRODUCERS table below.

Run:  python src/require_data.py        (self-test, needs no data)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA: Final[Path] = ROOT / "data"

# Which script regenerates each input. Keyed by the path RELATIVE to data/,
# matched longest-prefix-first so a directory entry covers everything under it.
PRODUCERS: Final[dict[str, str]] = {
    "fo_secban": "python src/fetch_secban.py",
    "fo_secban_2015_2026.csv":
        "python src/fetch_secban.py && python src/consolidate_secban.py",
    "bhavcopy": "python src/fetch_cash_bhavcopy.py",
    "nse_cash_turnover_daily.csv": "python src/fetch_cash_bhavcopy.py",
    "index_close": "python src/fetch_index_close.py",
    "nifty500_daily_2015_2026.csv": "python src/fetch_index_close.py",
    "corpactions": "python src/fetch_corpactions.py",
    "corpactions_banlist_2015_2026.csv": "python src/fetch_corpactions.py",
    "sip_forms": "python src/fetch_sip_forms.py",
    "sip_form_dates.csv": "python src/fetch_sip_forms.py",
    "amfi_notes": "python src/precheck_sip_timing.py  (fetches on first run)",
    "amfi_monthly_notes_index.csv":
        "python src/precheck_sip_timing.py  (fetches on first run)",
    "amfi_sip_monthly.csv":
        "python src/precheck_sip_timing.py  (fetches on first run)",
    "nse_index_recon_announcements_2026-09-21.csv":
        "NOT FETCHABLE -- see the note below",
}

# The one input with no fetcher. Recorded here rather than left to be
# discovered, because a reader who runs the Phase 1 pre-check hits it first.
_RECON_NOTE: Final[str] = """
  This one file is NOT produced by any script in this repository. It is a DOM
  extraction from the niftyindices.com press-release archive, taken 2026-09-21,
  and `precheck_index_recon.py` deliberately refuses to synthesise a substitute
  rather than run on invented events. Phase 1's result is reproducible from
  `results/precheck_index_recon_2026-09-21.txt` without it.
"""


class DataMissing(Exception):
    """A required input under data/ is absent. Carries its own instructions."""


def _relative_to_data(path: Path) -> str | None:
    """The path's location inside data/, or None if it is not under data/."""
    try:
        return str(path.resolve().relative_to(DATA)).replace("\\", "/")
    except (ValueError, OSError):
        return None


def producer_for(rel: str) -> str:
    """Longest-prefix match, so `fo_secban/2020/x.csv` finds `fo_secban`."""
    parts = rel.split("/")
    for cut in range(len(parts), 0, -1):
        key = "/".join(parts[:cut])
        if key in PRODUCERS:
            return PRODUCERS[key]
    return "see SETUP.md -- no fetcher is registered for this path"


def report(path: Path, detail: str = "") -> str:
    """The message a reader sees. No traceback, no Python vocabulary."""
    rel = _relative_to_data(path) or str(path)
    how = producer_for(rel)
    lines = [
        "",
        "=" * 78,
        "  DATA NOT PRESENT -- this is expected in a fresh clone.",
        "=" * 78,
        "",
        f"  MISSING:  data/{rel}",
        "",
        "  No data file is committed to this repository. NSE and NSE Indices both",
        "  prohibit redistribution in writing, so every input is fetched rather than",
        "  shipped. See the data note in README.md.",
        "",
        f"  TO PRODUCE IT:  {how}",
    ]
    if rel.startswith("nse_index_recon"):
        lines.append(_RECON_NOTE.rstrip("\n"))
    if detail:
        lines += ["", "  THE SCRIPT ADDS:", "    " + detail.replace("\n", "\n    ")]
    lines += [
        "",
        "  Every figure in RESULTS.md can be read without fetching anything: the",
        "  output of each cited run is committed under results/.",
        "",
        "=" * 78,
        "",
    ]
    return "\n".join(lines)


def require(path: Path, detail: str = "") -> Path:
    """Return `path`, or raise DataMissing if it is not there."""
    if not path.exists():
        raise DataMissing(report(path, detail))
    return path


def path_in_message(text: str) -> Path | None:
    """Find a path under data/ inside a hand-written error message.

    Scripts that raise their own FileNotFoundError -- `precheck_ban_list.py`,
    `precheck_index_recon.py`, `consolidate_secban.py` -- pass a MESSAGE and no
    `filename`, so there is nothing structured to read. Their message does name
    the file, and that name is what decides whether this is absent input or a
    bug, so it is parsed rather than guessed at.
    """
    for hit in re.findall(r"[A-Za-z]:[\\/][^\s,;:]*|/[^\s,;:]+", text):
        cand = Path(hit.rstrip(".,;:"))
        if _relative_to_data(cand) is not None:
            return cand
    return None


def guard(main: Callable[[], int | None]) -> int:
    """Run `main`, converting an absent data file into a clean exit.

    A missing path under data/ exits 2 with instructions. Anything else --
    including a FileNotFoundError on a path outside data/ -- propagates with
    its traceback, because that is a bug and not a fresh clone.
    """
    def emit(text: str) -> int:
        # Flush stdout first. These scripts print progress to stdout, which is
        # block buffered when piped, while stderr is not -- without this the
        # banner lands ABOVE the output it is meant to follow, which reads as
        # if the script failed before it started.
        sys.stdout.flush()
        print(text, file=sys.stderr)
        sys.stderr.flush()
        return 2

    try:
        return int(main() or 0)
    except DataMissing as exc:
        return emit(str(exc))
    except FileNotFoundError as exc:
        raw = getattr(exc, "filename", None)
        if raw is not None:
            # Raised by the interpreter: `filename` is authoritative and the
            # message is boilerplate, so no detail is carried through.
            path = Path(str(raw))
            if _relative_to_data(path) is None:
                raise                  # a bug, not absent input -- keep the trace
            return emit(report(path))
        # Raised by a script with its own wording. That wording is worth more
        # than anything reconstructed here, so it is passed through whole.
        found = path_in_message(str(exc))
        if found is None:
            raise
        return emit(report(found, str(exc)))


def _self_test() -> int:
    """Known answers, no data required."""
    ok = True

    def check(label: str, got: object, want: object) -> None:
        nonlocal ok
        good = got == want
        ok &= good
        print(f"    {label:<52} {'PASS' if good else '*** FAIL ***'}")
        if not good:
            print(f"        got  {got!r}\n        want {want!r}")

    print("\n  SELF-TEST -- require_data.py")
    print("  (the DATA NOT PRESENT blocks above and below are arms firing, "
          "not failures)")
    check("longest-prefix: fo_secban/2020/x.csv",
          producer_for("fo_secban/2020/x.csv"), "python src/fetch_secban.py")
    check("exact beats prefix: fo_secban_2015_2026.csv",
          producer_for("fo_secban_2015_2026.csv"),
          "python src/fetch_secban.py && python src/consolidate_secban.py")
    check("unregistered path falls back",
          producer_for("no_such_thing.csv").startswith("see SETUP.md"), True)
    check("a path outside data/ is not ours",
          _relative_to_data(ROOT / "README.md"), None)
    check("a path inside data/ is ours",
          _relative_to_data(DATA / "x" / "y.csv"), "x/y.csv")

    # guard() must NOT swallow a missing file outside data/
    def outside() -> int:
        raise FileNotFoundError(2, "No such file or directory",
                                str(ROOT / "src" / "not_here.py"))
    try:
        guard(outside)
        check("guard re-raises for a path outside data/", "returned", "raised")
    except FileNotFoundError:
        check("guard re-raises for a path outside data/", "raised", "raised")

    # guard() MUST convert a missing file inside data/
    def inside() -> int:
        raise FileNotFoundError(2, "No such file or directory",
                                str(DATA / "fo_secban_2015_2026.csv"))
    check("guard returns 2 for a path inside data/", guard(inside), 2)

    def raises_data_missing() -> int:
        # A name chosen so the arm cannot pass or fail on what happens to be
        # in data/ today. An earlier version of this test used a real input
        # and silently passed because the file was present.
        require(DATA / "__absent_by_construction__.csv")
        return 0
    check("require() raises DataMissing when absent",
          guard(raises_data_missing), 2)

    # A script's own message, with no `filename` set -- the common case here.
    def own_wording() -> int:
        raise FileNotFoundError(
            f"{DATA / 'fo_secban_2015_2026.csv'} is missing. Run "
            f"src/fetch_secban.py then src/consolidate_secban.py.")
    check("guard handles a hand-written message under data/",
          guard(own_wording), 2)

    def own_wording_outside() -> int:
        raise FileNotFoundError(f"{ROOT / 'src' / 'nope.py'} is missing.")
    try:
        guard(own_wording_outside)
        check("...and re-raises the same shape outside data/",
              "returned", "raised")
    except FileNotFoundError:
        check("...and re-raises the same shape outside data/",
              "raised", "raised")

    check("path_in_message finds a data path",
          path_in_message(f"{DATA / 'x.csv'} is missing") is not None, True)
    check("path_in_message ignores a non-data path",
          path_in_message(f"{ROOT / 'README.md'} is missing"), None)

    print(f"\n  SELF-TEST: {'ALL PASS' if ok else '*** FAILED ***'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
