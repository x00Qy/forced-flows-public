r"""
require_yalgo_core.py -- import `yalgo_core` with an actionable failure.

A bare `ModuleNotFoundError: No module named 'yalgo_core'` is not actionable.
It names a package that is not on PyPI, gives no path, and gives no hint that
the fix is an editable install of a sibling repository. This module is the one
place that failure is turned into instructions.

WHY A GUARD MODULE RATHER THAN A try/except IN EACH IMPORTER. Two scripts here
need `yalgo_core` today and more will later. Two copies of the same error text
drift apart. The same reasoning put the shared statistics code behind a shim
in the options-research repository this line grew out of, rather than editing
every import site. The text exists once, here.

Importers do:

    from require_yalgo_core import round_trip_cost_bps

which is the same function object as
`yalgo_core.equity_cost_model.round_trip_cost_bps`, so output is unchanged.
"""
from __future__ import annotations

_FIX = r"""
  yalgo_core is not installed, so forced-flows cannot load its cost model.

  yalgo_core is a SIBLING REPOSITORY, not a PyPI package. It holds the shared
  statistics and transaction-cost code shared with the options-research work
  this line grew out of.

  FIX -- clone it beside this repository and install it editable:

      git clone https://github.com/x00Qy/yalgo-core
      pip install -e ../yalgo-core

  (package name `yalgo-core`, import name `yalgo_core`. It is NOT on PyPI.)

  Any path works; `../yalgo-core` is a convention, not a requirement. Install
  from wherever your clone actually is.

  FOR mypy, SEPARATELY: mypy cannot follow a PEP 660 editable install, so
  type-checking additionally needs

      MYPYPATH=/path/to/yalgo-core

  Without it `mypy --strict` reports import-not-found for yalgo_core, and that
  error is expected rather than a defect.

  See SETUP.md in this repository.
"""

try:
    from yalgo_core.equity_cost_model import (  # noqa: F401
        DEFAULT_EQUITY_COST,
        rate_on,
        round_trip_cost_bps,
        round_trip_cost_rupees,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - install-time only
    if exc.name is not None and not exc.name.startswith("yalgo_core"):
        raise
    raise ModuleNotFoundError("\n" + _FIX) from exc

__all__ = ["DEFAULT_EQUITY_COST", "rate_on", "round_trip_cost_bps",
           "round_trip_cost_rupees"]
