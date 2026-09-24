# forced-flows

**Four research ideas about Indian markets: three pre-registered, tested and closed, and one
deliberately not pursued. None produced a tradable edge.**

The ideas were about *forced* institutional flows — money that moves on a schedule or a rule
rather than on a view. They are enumerated with their verdicts and the single number that decided
each one in **[`RESULTS.md`](RESULTS.md)**.

**This repository exists for the method, not the findings.** A negative result is worth little on
its own; what is worth something is being able to show that it is a real negative and not a
botched test. Three things do that work here, and they are what the repository is for:

- **Pre-registration.** The hypothesis, the acceptance bar and the kill condition are committed to
  version control *before the script that tests them exists*, so the git history — not a claim in
  a document — is the evidence of the order. All three tested phases are verifiably
  doc-before-script; the fourth, Phase 2b, never had a test designed.
- **Blinded nuisance gates.** Phases 2 and 3 decide whether a test is worth running using only
  variance and correlation, with the effect itself made unreachable in code: the data layer
  returns mean-removed residuals, and every published figure passes through an allow-list writer
  where an unlisted key raises.
- **Standing rules written after specific failures.** Each of the five in
  **[`STANDING_RULES.md`](STANDING_RULES.md)** names the failure that produced it. Rule 1 exists
  because Phase 2's pre-check **passed** and the gate later found it wrong twice over — it had
  assumed a 5% per-event standard deviation where the measured figure was 7.75%, and the
  clustering argument that superseded it was also wrong.

So the apparatus is the output. Everything needed to check it is here; **none of the market data
is, and none ever will be** — see [Data policy](#data-policy).

---

## The question

Some flows into the Indian equity market are **forced** — they happen on a schedule or a rule,
not because anyone thinks the price is wrong. Index funds must buy a stock the day it enters the
index. Systematic investment plans debit on a fixed date each month. A stock entering the F&O ban
list has its derivative positions frozen.

If a flow is large, predictable and price-insensitive, it may move the price in a way a
participant could anticipate. **The question is whether any such effect is large enough for a
retail participant to trade after costs.**

The answer, for the three candidates tested: **no, or not decidably on the available data.** A
fourth, the ASM/GSM surveillance lists (Phase 2b), was not pursued: no test was designed and no data
fetched, because every factor that bound Phase 2 is worse there.

## The method

Three rules, applied to every phase, and they are what the project is actually about.

**1. The bar is a cost floor, fixed before the test.** A price effect is only interesting if it
exceeds what it costs to capture. Every phase compares against **3× the statutory round-trip
cost** for the instrument that would trade it — 71.35 bps for cash-market delivery, 16.97 bps for
NIFTY futures. Both come from a sourced, date-keyed cost model.

**2. Pre-registration, committed before the script exists.** The hypothesis, the acceptance bar
and the kill condition go into version control first. Every document here is timestamped by its
commit, and none is edited afterwards — corrections go in numbered addenda, and the original
stands as the record of what was believed at the time.

**3. A cheap arithmetic pre-check before any expensive test.** Most ideas die to arithmetic. The
pre-check asks "could this possibly clear the bar?" using data already on hand. Only survivors get
a real test.

To these a fourth was added after Phase 2 failed for want of it: **power is computed with the
planned test's own estimator, and its nuisance parameters are measured blind from real data.**
See `STANDING_RULES.md`.

## What was found

| phase | candidate | verdict | the number that decided it |
|---|---|---|---|
| **1** | Index reconstitution — buying additions | **CLOSED** at pre-check | n = 110 events; MDE above the bar |
| **2** | F&O ban-list entry | **CLOSED** at the gate | MDE **120.42 bps** vs a **71.35 bps** bar |
| **2b** | ASM/GSM surveillance lists | **NOT PURSUED** | no test designed; every binding factor worse than Phase 2 |
| **3** | SIP debit-date timing | **CLOSED** at the gate | MDE **53.20 bps** vs a **16.97 bps** bar |
| **4** | — | **NOT STARTED** | line closed under the stopping rule |

Full detail, including each phase's pre-registration and gate, is in **[`RESULTS.md`](RESULTS.md)**.

**"Closed as underpowered" is not "no effect exists."** It means the smallest effect the data
could reliably detect is larger than the smallest effect worth trading. For Phase 2 the sample was
the entire F&O ban archive, 2015–2026; for Phase 3, clearing the bar would need about **106 years**
of index history. These are not problems more data solves.

**Two results are worth more than the verdicts.**

Phase 2's pre-check originally **passed**, and the gate later found it wrong for a reason nobody
had checked: the pre-check assumed a 5% per-event return standard deviation, and the measured
figure was **7.75%**. The clustering argument that superseded it — which looked decisive — turned
out to be wrong too; measured stock-level correlation was **−0.003**, essentially zero. Both
corrections are recorded in `GATE_BAN_LIST_NUISANCE_ADDENDUM_02.md`.

Phase 3's gate contained a flaw that made the design look better than it was: overlapping
comparison windows absorb part of any real effect, so the measured difference is only **0.900** of
the true one. Recorded and measured in `GATE_SIP_TIMING_ADDENDUM_01.md`.

Both errors ran in the direction that flattered the design. Both were caught by assertions written
to catch them, before any confirmatory test.

## Reproducing a headline result

The Phase 3 gate is the cheapest to reproduce — **one input file, and the gate itself runs in
under a minute.** Building that input is the slower part: `fetch_index_close.py` pulls ~2,900 daily
index files from NSE's archive, **roughly 15 minutes**, throttled. It caches, so you pay it once.

```bash
pip install -r requirements.txt
git clone https://github.com/x00Qy/yalgo-core    # beside this repository
pip install -e ../yalgo-core                     # NOT on PyPI -- see SETUP.md
python src/fetch_index_close.py          # NIFTY 500 daily open/close from NSE's archive
python src/gate_sip_timing.py            # dry run, then the gate
```

Expect `MDE 53.20 bps` against a `16.9664 bps` bar and `VERDICT: CLOSE AS UNDERPOWERED`. The
script runs eight validation arms on synthetic data with known answers before it touches the real
series; if any fails, it refuses to run.

The Phase 2 gate needs the cash bhavcopy — about 2,900 files, throttled to three workers with a
0.35s pause, roughly 40 minutes:

```bash
python src/fetch_secban.py && python src/consolidate_secban.py
python src/fetch_cash_bhavcopy.py && python src/fetch_corpactions.py
python src/gate_ban_list_nuisance.py
```

**Do not raise the fetcher concurrency.** NSE blocks addresses that pull too fast, and every
fetcher caches, so a slow run that finishes beats a fast one that gets blocked.

## Where the key documents are

| document | what it is |
|---|---|
| **[`SETUP.md`](SETUP.md)** | install, where data must sit, how to regenerate it, running the scripts |
| **[`RESULTS.md`](RESULTS.md)** | every phase, its verdict, and the one number that decided it |
| **[`STANDING_RULES.md`](STANDING_RULES.md)** | five rules, each with the failure that produced it |
| **[`TEST_REGISTRY.csv`](TEST_REGISTRY.csv)** | append-only ledger of every verdict, with its reason |
| `PRECHECK_INDEX_RECON.md` | Phase 1 pre-registration |
| `PRECHECK_BAN_LIST.md` | Phase 2 pre-check (verdict later superseded) |
| `GATE_BAN_LIST_NUISANCE.md` + Addenda 01, 02 | Phase 2's blinded gate and its result |
| `PREREG_BAN_LIST_ENTRY.md` | Phase 2's full design — **never locked**, kept as reusable |
| `PRECHECK_SIP_TIMING.md` | Phase 3 pre-check |
| `GATE_SIP_TIMING.md` + Addendum 01 | Phase 3's blinded gate and its result |

`results/` holds the stdout and the machine-readable output of every run cited above.

## Notes

**Blinded gates.** Phases 2 and 3 decide on power alone, and the scripts are built so the answer
is unreachable while that decision is made: the data layer returns mean-removed residuals or one
undifferentiated array, and every published figure passes through an allow-list writer where an
unlisted key raises. The blinding is procedural — the data on disk obviously contains the answer —
and both gate documents say so rather than claiming more.

**[`yalgo_core`](https://github.com/x00Qy/yalgo-core)** is a separate package holding the shared
statistics and cost-model code, installed editable: `pip install -e ../yalgo-core`. Import it through `src/require_yalgo_core.py`,
which turns a missing install into instructions. `mypy --strict` cannot follow editable installs
and will report `import-not-found` for it; that error is expected.

**What "P1" means in these documents.** Several files here — the pre-registrations and gate
documents especially — refer to *P1*. That is the author's earlier options-research project: a
separate repository, **not public**, whose cost model and closure audit this line borrowed method
from. Where a document cites a file inside it, such as `spot_cost_model.py` or
`PAPER_no_alpha_at_retail_cost_v2.md`, **that file is not reachable from here** and the citation is
there because it is where the figure came from, not as something to follow.

**Those citations are not edited out, deliberately.** The pre-registrations, gate documents and
addenda are locked records — this repository's second methodological claim is that none of them is
edited after the fact, and quietly rewriting them for publication would make that claim false. They
are published exactly as they were committed, private references and all.

**One input has no fetcher.** `data/nse_index_recon_announcements_2026-09-21.csv` is a DOM
extraction from the niftyindices.com press-release archive, taken 2026-09-21.
`precheck_index_recon.py` refuses to synthesise a substitute rather than run on invented events,
so Phase 1 is reproducible from `results/precheck_index_recon_2026-09-21.txt` and not from a
fresh clone alone.

---

## Data policy

**No data file is committed to this repository, and none ever will be.** Every input is fetched
from its publisher at runtime by a script in `src/`, and every fetcher caches, so a re-run is
free. This is not caution — it is what the publishers' terms require.

### The licensing position

**NSE**, *[Website Policies](https://www.nseindia.com/website-policies)*, checked 2026-09-22:

> "Except as specifically permitted herein the Exchange is the owner of copyright in all
> information featured on this website and **no portion of the information on this website may be
> reproduced on or transmitted to or stored in any other website** or in other form of electronic
> retrieval system or by in any other form or by in any other means."

A public repository is another website and an electronic retrieval system. This covers the cash
bhavcopy, the F&O ban archive, the index close files and the corporate-actions API — every one is
served from `nseindia.com` or `nsearchives.nseindia.com`.

**NSE Indices**, *[Terms of Use](https://www.niftyindices.com/terms-of-use)*, same date:

> "No material from the Site may be copied, modified, reproduced, republished, uploaded,
> transmitted, posted or distributed in any form **without prior written permission** from the
> Company."

> "**Use or distribution of the Company's … index data** and the use of their index data to create
> financial products **require a license from NSE Indices Ltd.**"

The NIFTY 500 series used here comes from NSE's own `ind_close_all` archive, so both clauses apply
to it.

**AMFI** publishes no equivalent blanket prohibition that was found. Its Monthly Notes and SIP
application forms get the same treatment regardless, because consistency costs nothing here and
avoids a second judgement call.

**This is not "unclear, so be careful."** It is explicitly prohibited, in writing, by the
publisher. There is no judgement call to make.

### What that means mechanically

- **The whole `data/` tree is gitignored**, rather than a list of known filenames — so an input
  added later cannot reach a commit by someone forgetting to update the ignore file.
- **This repository has a single initial commit**, not a rewritten history. The private working
  repository's earlier revisions do contain derived data files, and removing them from `HEAD`
  alone would not remove them from the object store. A fresh repository is the only clean answer.
- **A clone therefore has an empty `data/` and every analysis script stops on its first read.**
  That is designed, not broken. Each names the file that is absent and the fetcher that produces
  it, then exits 2. `src/require_data.py` is the one place that message lives, and it applies one
  rule: a missing path *under* `data/` is absent input; a missing path anywhere else is a bug and
  keeps its traceback.

### What a reader can do without fetching anything

**Every figure in [`RESULTS.md`](RESULTS.md) can be checked.** The stdout and machine-readable
output of every cited run is committed under `results/`, and the gates' validation arms are
synthetic and run offline — so the estimators can be exercised end to end with no downloads at
all.

To re-derive rather than read: Phase 3's input takes **roughly 15 minutes** to fetch (~2,900
daily index files). Phase 2's take **roughly 40 minutes** on top of that, because the cash bhavcopy
is ~2,900 zip archives. Phase 1's announcement inventory cannot be fetched at all (see Notes).
Every fetcher caches and is resumable, so the cost is paid once.

### The audit behind the claim

Before this repository was created, every committed file was checked line by line for figures that
amount to redistributed data rather than derived results:

| checked | finding |
|---|---|
| all 14 documents | no data table. The largest numeric table in any `.md` is **11 rows of version pins** in `SETUP.md` |
| all 7 `results/*.txt` run logs | **≤140 lines each**, summary output only; zero rows matching a `SYMBOL,number` shape |
| both `results/*.csv` gate outputs | only the gates' own allow-listed keys — variance components, counts, MDE, verdict. No per-event row, no price |
| the 18 `results/interval_cov/*.json` | bootstrap coverage rates from **synthetic** samples; no market data enters them |
| `TEST_REGISTRY.csv` | one row per verdict with its reason; counts only |

Summary statistics derived from licensed data are findings, not the data, and are what any paper
on the subject would report. Nothing here reproduces a series.

### AI assistance

This research was carried out with AI assistance. All design decisions, pre-registrations and
verdicts were made by the author.
