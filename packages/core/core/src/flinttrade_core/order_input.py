"""Shared validation of operator order inputs before admission or dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import abort, jsonify, make_response, request


def json_object_body() -> dict[str, Any]:
    """Decode an optional object body; never treat malformed input as empty.

    No bytes preserves body-less cancel/DELETE requests. An explicit JSON null,
    scalar, array, malformed document, or non-JSON content type is a bad body.
    """
    if not request.get_data():
        return {}
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(make_response(jsonify({"status": "error", "message": "Request body must be a JSON object"}), 400))
    return body


def normalise_order_type_fields(body: Mapping[str, Any]) -> dict[str, Any]:
    """Make both price-type aliases agree without changing omitted-field defaults.

    Raises:
        ValueError: When both non-empty aliases name different order types.
    """
    order_type = str(body.get("order_type") or "").strip().upper()
    pricetype = str(body.get("pricetype") or "").strip().upper()
    # The sandbox accepts SLM too; admission and typed orders require SL-M.
    if order_type == "SLM":
        order_type = "SL-M"
    if pricetype == "SLM":
        pricetype = "SL-M"
    if order_type and pricetype and order_type != pricetype:
        raise ValueError("order_type and pricetype must agree")
    canonical = order_type or pricetype
    if not canonical:
        return dict(body)
    return {**body, "order_type": canonical, "pricetype": canonical}
