"""Public instrument-lot lookup.

``GET /api/v1/instrument-lots`` returns the rows the backend order check
uses (disk cache when it has rows, otherwise the shipped excerpt) and the
same index line the risk skill prints. The terminal does not bundle a
second copy of the excerpt.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

from .instrument_lots import active_rows, index_lot_line

instrument_lots_bp = Blueprint("instrument_lots", __name__, url_prefix="/api/v1")


@instrument_lots_bp.route("/instrument-lots", methods=["GET"])
def get_instrument_lots() -> Response:
    """Rows and the Scalper-format index line from the active lookup."""
    rows = [dict(row) for row in active_rows()]
    return jsonify({"rows": rows, "line": index_lot_line()})
