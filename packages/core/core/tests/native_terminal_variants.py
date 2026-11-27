"""Independent inert rows for existing canonical semantic comparisons.

Each case starts from its own genuine zero-fill terminal settlement. Native
identity fields stay original except the explicitly labelled refusal controls.
"""
from __future__ import annotations

from typing import Any

# (external order delta, independent native fill, expected retained fills,
#  comparison code). None marks an identity/prerequisite or benign control.
TERMINAL_VARIANTS: dict[str, tuple[dict[str, Any], str, int, str | None]] = {
    "price-conflict": ({"price": 5}, "0", 0, "signed_price_mismatch"),
    "symbol-conflict": ({"tradingSymbol": "OTHER"}, "0", 0, "signed_symbol_mismatch"),
    "product-conflict": ({"productType": "INTRADAY"}, "0", 0, "signed_product_mismatch"),
    "action-conflict": ({"transactionType": "SELL"}, "0", 0, "signed_action_mismatch"),
    "pricetype-conflict": ({"orderType": "MARKET"}, "0", 0, "signed_pricetype_mismatch"),
    "native-fill-conflict": ({"filledQty": 1}, "0", 1, "independent_child_fill_mismatch"),
    "traded-zero-conflict": ({"orderStatus": "TRADED"}, "0", 0, "native_lifecycle_quantity_mismatch"),
    "rejected-fill-conflict": (
        {"orderStatus": "REJECTED", "filledQty": 1}, "1", 1, "native_lifecycle_quantity_mismatch",
    ),
    "zero-quantity-conflict": ({"quantity": 0}, "0", 0, "independent_child_quantities_invalid"),
    "fractional-quantity-conflict": ({"quantity": 1.5}, "0", 0, "independent_child_quantities_invalid"),
    "fractional-fill-conflict": ({"filledQty": 0.5}, "0", 0, "independent_child_quantities_invalid"),
    "negative-fill-conflict": ({"filledQty": -1}, "0", 0, "independent_child_quantities_invalid"),
    "excess-fill-conflict": ({"filledQty": 2}, "0", 2, "independent_child_quantities_invalid"),
    "equivalent-price": ({"price": "4.000"}, "0", 0, None),
    "equivalent-quantity": ({"quantity": "1.0", "filledQty": "0.00"}, "0", 0, None),
    "equivalent-canonical-text": (
        {"tradingSymbol": " SYNTH ", "transactionType": "buy",
         "productType": "cnc", "orderType": "limit"}, "0", 0, None,
    ),
    "equivalent-terminal-status": ({"orderStatus": "EXPIRED"}, "0", 0, None),
    "ignored-inactive-fields": ({"triggerPrice": 7, "validity": "IOC", "afterMarketOrder": True}, "0", 0, None),
    "unrelated-resource": ({"orderId": "unrelated-order"}, "0", 0, None),
    "foreign-exchange-identity": ({"exchangeSegment": "BSE_EQ"}, "0", 0, None),
    "foreign-exchange-order": ({"exchangeOrderId": "ExchangeOther"}, "0", 0, None),
    "unavailable-price": ({"price": None}, "0", 0, None),
    "unavailable-symbol": ({"tradingSymbol": None}, "0", 0, None),
    "unavailable-product": ({"productType": None}, "0", 0, None),
    "unavailable-action": ({"transactionType": None}, "0", 0, None),
    "unavailable-pricetype": ({"orderType": None}, "0", 0, None),
}
