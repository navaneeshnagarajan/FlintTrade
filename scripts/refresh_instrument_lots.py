"""Download the public Dhan and Kotak Neo masters into the shipped excerpt.

The file covers NIFTY, BANKNIFTY and SENSEX futures for the near month and
the next month. When those URLs cannot be reached the excerpt is written
with an empty ``rows`` list, the source URLs and ``fetched_at``. Rows are
never invented.

Usage::

    python scripts/refresh_instrument_lots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "packages" / "core" / "core" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    from flinttrade_core.instrument_lot_master import write_shipped_excerpt
    from flinttrade_core.instrument_lots import fixture_path

    payload = write_shipped_excerpt()
    rows = payload.get("rows")
    count = len(rows) if isinstance(rows, list) else 0
    print(f"wrote {fixture_path()} rows={count} fetched_at={payload.get('fetched_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
