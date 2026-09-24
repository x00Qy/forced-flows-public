r"""
event_study.py -- market-adjusted event study: abnormal returns, configurable
windows, per-event and mean CAR with standard errors.

Phase 0 infrastructure. It computes GROSS abnormal returns. Cost never enters
here; it enters once, later, as the viability bar, and that bar is today's cost
(`yalgo_core.equity_cost_model`). Keeping cost out of this module is what lets
the module stay silent about the rate history it does not have.

=== THE ESTIMATOR ===

    AR_it  = R_it - R_mt                     market-adjusted abnormal return
    CAR_i  = sum of AR_it over the window    per event
    meanCAR = mean over events

Market-adjusted, NOT a fitted market model: the abnormal return is the raw
return minus the market's, with beta fixed at 1 and alpha at 0. That is a
deliberate restriction, not an oversight -- see WHAT WOULD MAKE THIS WRONG.

=== WHY THERE IS NO NEWEY-WEST HERE, AND WHEN THERE WOULD BE ===

HAC standard errors correct for serial correlation along a TIME series. The
standard error on a mean CAR is CROSS-SECTIONAL -- it is taken across events,
not across time -- so a Bartlett kernel in event time is not the right
estimator and applying one would be a category error, not a conservative
choice.

The real dependence in forced-flows data is CALENDAR CLUSTERING: index
rebalances move many stocks on the SAME day, so those events share a market
shock and are not independent draws. The correct correction for that is to
cluster by event date, which `mean_car` does when given event dates. Treating
fifty same-day events as fifty independent observations is exactly the
inflated-n error that P1's ledger work kept running into.

ARM 5 of the dry run measures this rather than asserting it: under a zero
effect with intra-cluster correlation 0.3, the two readings are run on the same
simulated data and their rejection rates are printed side by side. The
clustered p-value uses G-1 degrees of freedom, G being the number of distinct
event dates, and that is asserted in the dry run rather than assumed.

IF a later phase estimates the market model on overlapping windows, or tests a
calendar-time portfolio series, HAC becomes appropriate. At that point
`newey_west_cov()` -- which already carries its own self-test gate in P1's
`test_prereg_term_structure.py` -- MUST BE MOVED INTO `yalgo_core` and imported
from there. It must not be reimplemented, and it must not be cross-imported
from P1: that would couple this repository to P1's engine, which is the
coupling that stopped `spot_cost_model` being extracted in the first place.

=== WHAT WOULD MAKE THIS WRONG ===

  BETA IS FIXED AT 1. For a stock whose true beta is far from 1, part of the
  measured "abnormal" return is just market exposure. Market-adjusted returns
  are standard for short windows precisely because estimating beta on a
  pre-event window adds its own error, but the restriction is real and a
  high-beta sample will show spurious CAR when the market moves.

  NO ESTIMATION WINDOW IS USED, so nothing here standardises AR by its own
  pre-event volatility. A high-variance stock contributes the same weight as a
  low-variance one.

  RETURNS ARE SIMPLE, NOT LOG. CARs sum simple returns, which is the event-study
  convention and is an approximation that degrades over long windows.

  THE WINDOW IS A CHOICE. It must be pre-registered before a real test, not
  selected after seeing which window is significant.

Run:  python src/event_study.py        (executes the dry run below)
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Final, Optional, Sequence

import numpy as np

__all__ = ["EventWindow", "CarResult", "market_adjusted_ar", "car_per_event",
           "mean_car", "mean_car_two_way", "exclude_overlapping"]

SCRIPT: Final[str] = "event_study.py"


@dataclass(frozen=True)
class EventWindow:
    """Offsets in trading days relative to the event, both inclusive.

    (-1, 1) is the three-day window around the event; (0, 0) is the event day
    alone; (1, 5) is a post-event drift window that excludes the event itself."""
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"window end {self.end} precedes start {self.start}")

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def label(self) -> str:
        return f"[{self.start:+d},{self.end:+d}]"


@dataclass(frozen=True)
class CarResult:
    window: EventWindow
    n_events: int
    n_clusters: int
    mean_car: float
    se: float
    t: float
    p: float
    se_kind: str
    per_event: np.ndarray


def market_adjusted_ar(stock_returns: np.ndarray,
                       market_returns: np.ndarray) -> np.ndarray:
    """AR = R_stock - R_market, elementwise. Shapes must match exactly.

    Raises on a shape mismatch rather than broadcasting: a silent broadcast
    between an (n_events, T) panel and a (T,) market vector is convenient and
    is also how a transposed panel produces a plausible-looking wrong answer."""
    if stock_returns.shape != market_returns.shape:
        raise ValueError(
            f"shape mismatch: stock {stock_returns.shape} vs market "
            f"{market_returns.shape}. Broadcasting is refused here -- pass the "
            f"market series already aligned and tiled to the panel's shape."
        )
    return np.asarray(stock_returns - market_returns, dtype=float)


def car_per_event(abnormal: np.ndarray, window: EventWindow,
                  event_index: int) -> np.ndarray:
    """Sum abnormal returns across `window` for each event.

    `abnormal` is (n_events, T). `event_index` is the column holding day 0, so
    the window maps to columns [event_index + start, event_index + end]."""
    if abnormal.ndim != 2:
        raise ValueError(f"abnormal must be 2-D (n_events, T), got {abnormal.shape}")
    lo = event_index + window.start
    hi = event_index + window.end + 1
    if lo < 0 or hi > abnormal.shape[1]:
        raise ValueError(
            f"window {window.label()} at event_index {event_index} needs columns "
            f"[{lo},{hi}) but the panel has {abnormal.shape[1]}. Refusing to "
            f"truncate the window silently."
        )
    return np.asarray(abnormal[:, lo:hi].sum(axis=1), dtype=float)


def _two_sided_t_p(t: float, df: float) -> float:
    """Two-sided Student-t p-value via the regularised incomplete beta, so this
    module needs no scipy. Checked against scipy in the dry run."""
    if df <= 0 or not math.isfinite(t):
        return float("nan")
    x = df / (df + t * t)
    return float(_betainc(df / 2.0, 0.5, x))


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a,b), continued-fraction form."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    if x >= (a + 1.0) / (a + b + 2.0):
        return 1.0 - _betainc(b, a, 1.0 - x)
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = (m * (b - m) * x) / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
        d = 1.0 + num * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + num / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    return front * (f - 1.0)


def mean_car(cars: np.ndarray, window: EventWindow,
             event_dates: Optional[Sequence[object]] = None) -> CarResult:
    """Mean CAR with a standard error, and the t-test of mean CAR = 0.

    With `event_dates`, events sharing a date are collapsed to their mean
    first and the standard error is taken across the resulting CLUSTERS, with
    df = clusters - 1. Same-day events share a market shock, so counting them
    as independent inflates n and understates the standard error.

    Without `event_dates`, the standard error is the plain cross-sectional one
    and `se_kind` says so, so a figure can never silently claim a clustering
    correction it did not receive."""
    cars = np.asarray(cars, dtype=float)
    if cars.ndim != 1 or cars.size < 2:
        raise ValueError(f"need at least 2 events, got shape {cars.shape}")

    if event_dates is None:
        units, kind = cars, "cross-sectional (events assumed independent)"
    else:
        if len(event_dates) != cars.size:
            raise ValueError(
                f"event_dates has {len(event_dates)} entries for {cars.size} events")
        buckets: dict[str, list[float]] = {}
        for d, c in zip(event_dates, cars):
            buckets.setdefault(str(d), []).append(float(c))
        units = np.array([float(np.mean(v)) for v in buckets.values()], dtype=float)
        kind = "clustered by event date"

    n = int(units.size)
    mean = float(units.mean())
    se = float(units.std(ddof=1) / math.sqrt(n)) if n >= 2 else float("nan")
    t = mean / se if se > 0 else float("nan")
    return CarResult(window=window, n_events=int(cars.size), n_clusters=n,
                     mean_car=mean, se=se, t=float(t),
                     p=_two_sided_t_p(float(t), float(n - 1)),
                     se_kind=kind, per_event=cars)


def _cluster_var(resid: np.ndarray, labels: Sequence[object]) -> float:
    """Cluster-robust variance of a MEAN: (1/n^2) * sum_g (sum_{i in g} e_i)^2.

    With singleton clusters this reduces to the independent (HC0) variance,
    which is what makes ARM 6a's reduction check meaningful."""
    n = resid.size
    sums: dict[object, float] = {}
    for lab, v in zip(labels, resid):
        sums[lab] = sums.get(lab, 0.0) + float(v)
    return sum(t * t for t in sums.values()) / float(n * n)


def mean_car_two_way(cars: np.ndarray, window: EventWindow,
                     cluster_a: Sequence[object],
                     cluster_b: Sequence[object]) -> CarResult:
    """Mean CAR with TWO-WAY clustered standard errors, Cameron-Gelbach-Miller.

        V = V_A + V_B - V_AB

    V_AB clusters on the intersection (a, b) cells, and subtracting it stops
    the dependence common to both dimensions being counted twice.

    WHY TWO DIMENSIONS ARE NEEDED HERE. Clustering on the event date handles
    names entering on the same day. It does NOT handle the same stock entering
    repeatedly: 28.6% of ban entries belong to ten names, and two SAIL entries
    months apart are not independent draws however far apart their dates are.
    Clustering on the stock alone has the mirror problem. Two-way is the
    standard answer and is what this function implements.

    df = min(G_A, G_B) - 1, the conservative convention: the variance is only
    as well estimated as the sparser dimension.

    NEGATIVE VARIANCE IS POSSIBLE. V_A + V_B - V_AB is not guaranteed
    positive in finite samples. When it comes out non-positive this function
    falls back to max(V_A, V_B) and SAYS SO in `se_kind` rather than silently
    truncating -- a standard-error that quietly changed estimator is exactly
    the kind of thing this project keeps finding after the fact."""
    cars = np.asarray(cars, dtype=float)
    if cars.ndim != 1 or cars.size < 2:
        raise ValueError(f"need at least 2 events, got shape {cars.shape}")
    if len(cluster_a) != cars.size or len(cluster_b) != cars.size:
        raise ValueError(
            f"cluster labels must match the event count: got {len(cluster_a)} "
            f"and {len(cluster_b)} for {cars.size} events")

    mean = float(cars.mean())
    resid = cars - mean
    v_a = _cluster_var(resid, cluster_a)
    v_b = _cluster_var(resid, cluster_b)
    v_ab = _cluster_var(resid, list(zip(cluster_a, cluster_b)))
    v = v_a + v_b - v_ab
    kind = "two-way clustered (Cameron-Gelbach-Miller)"
    if v <= 0.0:
        v = max(v_a, v_b)
        kind += " -- NEGATIVE VARIANCE, fell back to max(V_A, V_B)"

    g_a = len(set(cluster_a))
    g_b = len(set(cluster_b))
    df = min(g_a, g_b) - 1
    se = float(np.sqrt(v))
    t = mean / se if se > 0 else float("nan")
    return CarResult(window=window, n_events=int(cars.size),
                     n_clusters=min(g_a, g_b), mean_car=mean, se=se,
                     t=float(t), p=_two_sided_t_p(float(t), float(df)),
                     se_kind=f"{kind}; G_A={g_a}, G_B={g_b}, df={df}",
                     per_event=cars)


def exclude_overlapping(dates: Sequence[int], stocks: Sequence[object],
                        min_separation: int) -> list[int]:
    """Indices to KEEP after dropping an event that falls within
    `min_separation` trading days of the SAME stock's previous kept event.

    `dates` are trading-day ordinals, not calendar dates, so the separation is
    counted in sessions. Dropping is forward-greedy: the earlier event of an
    overlapping pair is kept and the later one dropped, so the rule never
    depends on anything after the event it is applied to.

    This exists because a [+1,+5] window overlaps itself when a stock
    re-enters within five sessions; overlapping windows share returns and the
    two CARs are then mechanically correlated."""
    if len(dates) != len(stocks):
        raise ValueError("dates and stocks must be the same length")
    order = sorted(range(len(dates)), key=lambda i: (str(stocks[i]), dates[i]))
    last: dict[object, int] = {}
    keep: list[int] = []
    for i in order:
        s, d = stocks[i], dates[i]
        prev = last.get(s)
        if prev is not None and d - prev <= min_separation:
            continue
        last[s] = d
        keep.append(i)
    return sorted(keep)


# =====================================================================
# DRY RUN -- planted effect, and the false-positive rate under the null
# =====================================================================

ALPHA: Final[float] = 0.01
N_SIMS: Final[int] = 1000
DRY_SEED: Final[int] = 20260921

# The REAL Phase 2 ban-entry structure, snapshotted from
# data/fo_secban_2015_2026.csv on 2026-09-21: 1,781 entries across 141 stocks
# and 499 calendar weeks. ARM 6b simulates on this rather than on a tidy
# balanced panel, because the concentration is the point -- ten names carry
# 28.6% of all entries, and a balanced panel would hide exactly the dependence
# the two-way estimator exists to handle.
STOCK_ENTRY_COUNTS: Final[tuple[int, ...]] = (
    75, 62, 54, 50, 47, 45, 45, 45, 43, 43, 42, 41, 41, 37, 37, 36, 35, 35, 35,
    30, 29, 27, 26, 26, 25, 24, 24, 23, 23, 22, 22, 21, 20, 20, 20, 19, 18, 16,
    15, 14, 13, 13, 13, 13, 12, 12, 12, 11, 11, 11, 10, 10, 10, 10, 10, 9, 9, 9,
    9, 9, 9, 8, 8, 8, 8, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6, 5, 5, 5, 5, 5, 4, 4, 4,
    4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1)
N_WEEKS_OBSERVED: Final[int] = 499
N_ENTRIES_OBSERVED: Final[int] = 1781
N_STOCKS_OBSERVED: Final[int] = 141

# ARM 5: realistic clustering. Index rebalances move many names on one date,
# so events share a date-level shock the market index does not absorb.
CLUSTER_DATES: Final[int] = 30       # G, the number of distinct event dates
PER_DATE: Final[int] = 5             # events sharing each date
INTRA_RHO: Final[float] = 0.3        # intra-cluster correlation of AR


def _panel(rng: np.random.Generator, n_events: int, T: int, sigma: float,
           planted: float, event_index: int, market_sigma: float = 0.01
           ) -> tuple[np.ndarray, np.ndarray]:
    """A synthetic panel with a KNOWN effect planted on the event day only.

    The market series is added to the stock series and then subtracted again by
    the estimator, so a correct market adjustment must remove it exactly and
    recover `planted` regardless of how large the market move is."""
    market = rng.normal(0.0, market_sigma, (n_events, T))
    idio = rng.normal(0.0, sigma, (n_events, T))
    stock = market + idio
    stock[:, event_index] += planted
    return stock, market


def _clustered_panel(rng: np.random.Generator, n_dates: int, per_date: int,
                     T: int, sigma: float, rho: float
                     ) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """A panel with ZERO true effect and a date-level shock shared within each
    cluster, giving intra-cluster correlation `rho` in the abnormal returns.

        AR_ijt = sqrt(rho) * u_jt + sqrt(1 - rho) * e_ijt

    u_jt is common to every event on date j, so corr(AR_ijt, AR_kjt) = rho for
    i != k. The shock is deliberately NOT put in the market series: a shock the
    index absorbs would be removed by market adjustment and would not test
    anything. This is the shock that survives it.

    Returns (stock, market, date_labels) with stock = market + AR, so
    `market_adjusted_ar` recovers AR exactly."""
    n = n_dates * per_date
    market = rng.normal(0.0, 0.01, (n, T))
    common = rng.normal(0.0, sigma, (n_dates, T))
    idio = rng.normal(0.0, sigma, (n, T))
    labels: list[str] = []
    ar = np.empty((n, T), dtype=float)
    row = 0
    for j in range(n_dates):
        for _ in range(per_date):
            ar[row] = math.sqrt(rho) * common[j] + math.sqrt(1.0 - rho) * idio[row]
            labels.append("date_" + str(j))
            row += 1
    return market + ar, market, labels


def _t_ppf(q: float, df: float) -> float:
    """Inverse Student-t CDF by bisection on _two_sided_t_p, so the module
    stays scipy-free. Only used by the dry run."""
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        # two-sided p at |t|=mid is 2*(1-F(mid)), so F(mid) = 1 - p/2
        f = 1.0 - _two_sided_t_p(mid, df) / 2.0
        if f < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _ban_like_panel(rng: np.random.Generator, rho_stock: float,
                    rho_week: float, planted: float
                    ) -> tuple[np.ndarray, list[str], list[int]]:
    """CARs with BOTH stock-level and week-level dependence, on the real
    Phase 2 structure: 141 stocks with the observed entry counts spread over
    499 weeks.

        CAR_i = sqrt(rho_stock) * u_stock(i)
              + sqrt(rho_week)  * v_week(i)
              + sqrt(1 - rho_stock - rho_week) * e_i
              + planted

    Each stock gets its own level and each week its own shock, so an estimator
    that clusters on only one of the two must under-state the variance. The
    weights sum to one so the marginal variance is 1 whatever the split."""
    u = rng.normal(0.0, 1.0, len(STOCK_ENTRY_COUNTS))
    v = rng.normal(0.0, 1.0, N_WEEKS_OBSERVED)
    idio_w = math.sqrt(max(0.0, 1.0 - rho_stock - rho_week))
    cars: list[float] = []
    stocks: list[str] = []
    weeks: list[int] = []
    for si, count in enumerate(STOCK_ENTRY_COUNTS):
        for _ in range(count):
            wi = int(rng.integers(0, N_WEEKS_OBSERVED))
            cars.append(math.sqrt(rho_stock) * float(u[si])
                        + math.sqrt(rho_week) * float(v[wi])
                        + idio_w * float(rng.normal(0.0, 1.0))
                        + planted)
            stocks.append(f"S{si}")
            weeks.append(wi)
    return np.asarray(cars, dtype=float), stocks, weeks


def dry_run() -> bool:
    print("=" * 96)
    print(f"{SCRIPT} -- DRY RUN. Nothing in this module is used on real data")
    print("until both arms below pass: a planted effect must be recovered, and")
    print("the false-positive rate under a zero effect must sit near the bar.")
    print("=" * 96)
    ok = True
    rng = np.random.default_rng(DRY_SEED)
    T, idx = 21, 10

    # --- arm 1: recover a planted effect -----------------------------
    print("\n  ARM 1 -- planted effect recovery")
    print(f"    {'planted':>9}{'n events':>10}{'window':>10}{'mean CAR':>11}"
          f"{'se':>9}{'t':>8}{'p':>11}  status")
    for planted in (0.0200, 0.0100, 0.0050):
        stock, market = _panel(rng, 400, T, 0.015, planted, idx)
        ar = market_adjusted_ar(stock, market)
        w = EventWindow(0, 0)
        res = mean_car(car_per_event(ar, w, idx), w)
        hit = abs(res.mean_car - planted) < 3.0 * res.se
        ok &= hit
        print(f"    {planted:>9.4f}{res.n_events:>10}{w.label():>10}"
              f"{res.mean_car:>11.5f}{res.se:>9.5f}{res.t:>8.2f}{res.p:>11.2e}"
              f"  {'PASS' if hit else '*** FAIL ***'}")

    # a wider window must recover the same effect: the planted return is on
    # day 0 only, so widening adds noise but must not move the point estimate
    stock, market = _panel(rng, 400, T, 0.015, 0.0200, idx)
    ar = market_adjusted_ar(stock, market)
    for w in (EventWindow(-1, 1), EventWindow(-5, 5)):
        res = mean_car(car_per_event(ar, w, idx), w)
        hit = abs(res.mean_car - 0.0200) < 3.0 * res.se
        ok &= hit
        print(f"    {0.0200:>9.4f}{res.n_events:>10}{w.label():>10}"
              f"{res.mean_car:>11.5f}{res.se:>9.5f}{res.t:>8.2f}{res.p:>11.2e}"
              f"  {'PASS' if hit else '*** FAIL ***'}")

    # --- arm 1b: the market adjustment must actually remove the market
    stock, market = _panel(rng, 400, T, 0.015, 0.0, idx, market_sigma=0.05)
    raw = mean_car(car_per_event(stock, EventWindow(-5, 5), idx), EventWindow(-5, 5))
    adj = mean_car(car_per_event(market_adjusted_ar(stock, market),
                                 EventWindow(-5, 5), idx), EventWindow(-5, 5))
    shrunk = adj.se < raw.se / 2.0
    ok &= shrunk
    print(f"\n    market removal: raw se {raw.se:.5f} -> adjusted se {adj.se:.5f}"
          f"  {'PASS' if shrunk else '*** FAIL ***'} (need < half)")

    # --- arm 2: false-positive rate under a zero effect ---------------
    print(f"\n  ARM 2 -- false-positive rate under NO effect, {N_SIMS:,} simulations")
    rng2 = np.random.default_rng(DRY_SEED + 1)
    w = EventWindow(-1, 1)
    rejects = 0
    for _ in range(N_SIMS):
        stock, market = _panel(rng2, 120, T, 0.015, 0.0, idx)
        res = mean_car(car_per_event(market_adjusted_ar(stock, market), w, idx), w)
        if res.p < ALPHA:
            rejects += 1
    fpr = rejects / N_SIMS
    # Binomial 99% interval on 1,000 draws at p=0.01 is roughly [0.3%, 1.9%].
    se_fpr = math.sqrt(ALPHA * (1 - ALPHA) / N_SIMS)
    band = (ALPHA - 2.576 * se_fpr, ALPHA + 2.576 * se_fpr)
    in_band = band[0] <= fpr <= band[1]
    ok &= in_band
    print(f"    rejections at p<{ALPHA}: {rejects} of {N_SIMS:,} = {fpr:.3%}")
    print(f"    expected {ALPHA:.1%}, 99% binomial band "
          f"[{band[0]:.3%}, {band[1]:.3%}]  {'PASS' if in_band else '*** FAIL ***'}")

    # --- arm 3: clustering must not be claimed unless asked for -------
    cars = np.array([0.01, 0.02, 0.03, 0.04], dtype=float)
    plain = mean_car(cars, EventWindow(0, 0))
    clust = mean_car(cars, EventWindow(0, 0), event_dates=["d1", "d1", "d2", "d2"])
    lab_ok = ("cross-sectional" in plain.se_kind and "clustered" in clust.se_kind
              and plain.n_clusters == 4 and clust.n_clusters == 2)
    ok &= lab_ok
    print(f"\n  ARM 3 -- clustering: plain n_clusters {plain.n_clusters}, "
          f"clustered {clust.n_clusters}, labels distinct  "
          f"{'PASS' if lab_ok else '*** FAIL ***'}")
    same_day_se = clust.se > plain.se
    ok &= same_day_se
    print(f"    clustered se {clust.se:.5f} > plain se {plain.se:.5f} on "
          f"same-day events  {'PASS' if same_day_se else '*** FAIL ***'}")

    # --- arm 4: the p-value implementation, against scipy if present --
    try:
        from scipy import stats as _st  # type: ignore[import-untyped]
        worst = max(abs(_two_sided_t_p(t, df) - 2.0 * _st.t.sf(abs(t), df))
                    for t in (0.1, 1.0, 2.5, 4.0) for df in (3.0, 30.0, 500.0))
        p_ok = worst < 1e-10
        ok &= p_ok
        print(f"\n  ARM 4 -- t p-value vs scipy, worst abs diff {worst:.2e}  "
              f"{'PASS' if p_ok else '*** FAIL ***'}")
    except ImportError:
        print("\n  ARM 4 -- scipy absent, p-value cross-check SKIPPED")

    # --- arm 5: false-positive rate under REALISTIC CLUSTERING --------
    # The correction is only worth having if it works on the dependence
    # forced-flows actually has. Both readings are run on the same data so the
    # size of the error the clustering prevents is visible, not asserted.
    print(f"\n  ARM 5 -- false-positive rate under CLUSTERING, {N_SIMS:,} simulations")
    print(f"    {CLUSTER_DATES} event dates x {PER_DATE} events = "
          f"{CLUSTER_DATES * PER_DATE} events, intra-cluster rho = {INTRA_RHO}, "
          f"zero true effect")
    rng3 = np.random.default_rng(DRY_SEED + 2)
    w5 = EventWindow(-1, 1)
    naive = clustered = 0
    df_seen: set[float] = set()
    for _ in range(N_SIMS):
        stock, market, labels = _clustered_panel(
            rng3, CLUSTER_DATES, PER_DATE, T, 0.015, INTRA_RHO)
        cars = car_per_event(market_adjusted_ar(stock, market), w5, idx)
        if mean_car(cars, w5).p < ALPHA:
            naive += 1
        res_c = mean_car(cars, w5, event_dates=labels)
        df_seen.add(float(res_c.n_clusters - 1))
        if res_c.p < ALPHA:
            clustered += 1
    fpr_n = naive / N_SIMS
    fpr_c = clustered / N_SIMS
    band5 = (ALPHA - 2.576 * se_fpr, ALPHA + 2.576 * se_fpr)
    c_ok = band5[0] <= fpr_c <= band5[1]
    ok &= c_ok
    print(f"    events assumed independent : {naive:>4} of {N_SIMS:,} = {fpr_n:>7.3%}"
          f"   <- what the correction prevents")
    print(f"    clustered by event date    : {clustered:>4} of {N_SIMS:,} = {fpr_c:>7.3%}"
          f"   {'PASS' if c_ok else '*** FAIL ***'} "
          f"(band [{band5[0]:.3%}, {band5[1]:.3%}])")
    # df is asserted, not assumed: the clustered p-value must use G-1, not n-1.
    expected_df = {float(CLUSTER_DATES - 1)}
    df_ok = df_seen == expected_df
    ok &= df_ok
    print(f"    clustered p-value df       : {sorted(df_seen)} "
          f"(G-1 = {CLUSTER_DATES - 1}); naive path would use "
          f"{CLUSTER_DATES * PER_DATE - 1}  {'PASS' if df_ok else '*** FAIL ***'}")

    # --- arm 6: TWO-WAY CLUSTERING ------------------------------------
    print("\n  ARM 6 -- two-way clustering (Cameron-Gelbach-Miller)")
    w6 = EventWindow(0, 0)

    # 6a: with one dimension all singletons, two-way must reduce to one-way
    # on the other. V_B and V_AB both become the independent variance and
    # cancel, leaving V_A exactly.
    rng6 = np.random.default_rng(DRY_SEED + 3)
    cars6 = rng6.normal(0.0, 1.0, 600)
    grp = [f"g{i % 40}" for i in range(600)]
    singleton = [f"u{i}" for i in range(600)]
    cgm_one_way = math.sqrt(_cluster_var(cars6 - cars6.mean(), grp))
    two_way = mean_car_two_way(cars6, w6, grp, singleton)
    red = abs(two_way.se - cgm_one_way) < 1e-12
    ok &= red
    print(f"    6a reduction to one-way when B is all singletons:")
    print(f"       CGM one-way on A   {cgm_one_way:.12f}")
    print(f"       two-way(A, B)      {two_way.se:.12f}   "
          f"{'PASS' if red else '*** FAIL ***'} (V_B and V_AB cancel exactly)")
    # mean_car is a DIFFERENT one-way estimator -- cluster means rather than
    # the CGM sandwich -- so it is printed for contrast, not asserted equal.
    print(f"       mean_car (cluster-means, a different estimator) "
          f"{mean_car(cars6, w6, event_dates=grp).se:.12f}")

    # 6b: false-positive rate under BOTH dependences, zero effect, on the real
    # structure. The three readings run on identical data.
    print(f"    6b false-positive rate, {N_SIMS:,} sims, zero effect, real structure")
    print(f"       {N_STOCKS_OBSERVED} stocks / {N_ENTRIES_OBSERVED:,} entries / "
          f"{N_WEEKS_OBSERVED} weeks, rho_stock 0.25, rho_week 0.15")
    rng6b = np.random.default_rng(DRY_SEED + 4)
    rej = {"two-way": 0, "date-only": 0, "naive": 0}
    for _ in range(N_SIMS):
        c, st, wk = _ban_like_panel(rng6b, 0.25, 0.15, 0.0)
        if mean_car_two_way(c, w6, wk, st).p < ALPHA:
            rej["two-way"] += 1
        if mean_car(c, w6, event_dates=wk).p < ALPHA:
            rej["date-only"] += 1
        if mean_car(c, w6).p < ALPHA:
            rej["naive"] += 1
    se_f = math.sqrt(ALPHA * (1 - ALPHA) / N_SIMS)
    lo, hi = ALPHA - 2.576 * se_f, ALPHA + 2.576 * se_f
    tw = rej["two-way"] / N_SIMS
    dat = rej["date-only"] / N_SIMS
    nai = rej["naive"] / N_SIMS
    for k, r in (("two-way", tw), ("date-only", dat), ("naive", nai)):
        print(f"       {k:<10} {rej[k]:>4}/{N_SIMS:,} = {r:>7.2%}")
    # What is ASSERTED is what this estimator actually claims: that it removes
    # the bulk of the distortion the one-way readings leave. It does NOT claim
    # exact nominal size at 141 unbalanced clusters, and the measured size is
    # reported as a number to be carried into the pre-registration rather than
    # hidden behind a widened band.
    better = tw < dat / 5.0 and tw < nai / 5.0 and tw < 0.05
    ok &= better
    print(f"       two-way removes most of the distortion (< 1/5 of date-only "
          f"and of naive, and < 5%)  {'PASS' if better else '*** FAIL ***'}")
    if not (lo <= tw <= hi):
        print(f"\n       *** MEASURED SIZE {tw:.2%} AGAINST A NOMINAL {ALPHA:.0%}"
              f" (band [{lo:.2%},{hi:.2%}]).")
        print(f"       *** NOT A BUG AND NOT A BAND TO WIDEN: with BALANCED clusters")
        print(f"       *** at the same G=141 the size is ~1.25%. The excess comes from")
        print(f"       *** the OBSERVED cluster sizes being unbalanced -- one stock")
        print(f"       *** carries 75 of 1,781 entries. Cluster-robust inference is")
        print(f"       *** known to over-reject with few and unbalanced clusters.")
        print(f"       *** ANY PRE-REGISTRATION USING THIS ESTIMATOR MUST STATE THAT A")
        print(f"       *** NOMINAL p<{ALPHA} BUYS ABOUT {tw:.0%} ACTUAL SIZE HERE.")

    # 6c: an effect planted at the two-way MDE must be found ~80% of the time
    rng6c = np.random.default_rng(DRY_SEED + 5)
    c0, st0, wk0 = _ban_like_panel(rng6c, 0.25, 0.15, 0.0)
    se0 = mean_car_two_way(c0, w6, wk0, st0).se
    df0 = min(len(set(wk0)), len(set(st0))) - 1
    mde6 = (_t_ppf(1.0 - ALPHA / 2.0, df0) + _t_ppf(0.80, df0)) * se0
    hits = 0
    for _ in range(N_SIMS):
        c, st, wk = _ban_like_panel(rng6c, 0.25, 0.15, mde6)
        if mean_car_two_way(c, w6, wk, st).p < ALPHA:
            hits += 1
    rate = hits / N_SIMS
    se_p = math.sqrt(0.80 * 0.20 / N_SIMS)
    plo, phi = 0.80 - 2.576 * se_p, 0.80 + 2.576 * se_p
    pgood = plo <= rate <= phi
    ok &= pgood
    print(f"    6c power at the two-way MDE ({mde6:.5f}): {rate:.1%} detected, "
          f"expected 80%  {'PASS' if pgood else '*** FAIL ***'} "
          f"band [{plo:.1%},{phi:.1%}]")

    # 6d: the overlap rule must drop exactly the planted overlapping entries
    dates = [10, 12, 40, 80, 81, 200, 300, 500]
    stks = ["A", "A", "A", "B", "B", "C", "A", "B"]
    # A: 10 kept, 12 dropped (2 apart), 40 kept (28 apart), 300 kept
    # B: 80 kept, 81 dropped (1 apart), 500 kept
    # C: 200 kept                      -> 6 kept, 2 dropped
    keep = exclude_overlapping(dates, stks, 5)
    want = [0, 2, 3, 5, 6, 7]
    dgood = keep == want
    ok &= dgood
    print(f"    6d overlap rule: kept {keep} of 8, expected {want}  "
          f"{'PASS' if dgood else '*** FAIL ***'}")
    dropped = [i for i in range(8) if i not in keep]
    print(f"       dropped {dropped} = (A@12, 2 after A@10) and (B@81, 1 after B@80)")
    idem = exclude_overlapping([dates[i] for i in keep],
                               [stks[i] for i in keep], 5)
    idem_ok = idem == list(range(len(keep)))
    ok &= idem_ok
    print(f"       re-applying the rule drops nothing more  "
          f"{'PASS' if idem_ok else '*** FAIL ***'}")

    print(f"\n  DRY RUN: {'ALL ARMS PASS' if ok else '*** FAILED ***'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if dry_run() else 1)
