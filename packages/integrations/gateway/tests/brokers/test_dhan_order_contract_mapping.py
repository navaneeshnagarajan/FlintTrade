"""Independent literal REST contracts; no adapter, SDK or repository fixtures."""

import copy
import unittest
from decimal import Decimal
from types import MappingProxyType

from flinttrade_gateway.brokers import dhan_order_mapping as mapping


def create_fields():
    return {
        "dhanClientId": "client-example",
        "securityId": "security-example",
        "transactionType": "BUY",
        "exchangeSegment": "NSE_EQ",
        "productType": "CNC",
        "orderType": "LIMIT",
        "orderFlag": "SINGLE",
        "quantity": 5,
        "price": 1428,
        "triggerPrice": 1427,
        "validity": "DAY",
    }


def modify_fields():
    return {
        "dhanClientId": "client-example",
        "orderType": "LIMIT",
        "orderFlag": "SINGLE",
        "legName": "TARGET_LEG",
        "quantity": 5,
        "price": 1428,
        "triggerPrice": 1427,
        "disclosedQuantity": 0,
        "validity": "DAY",
    }


class ForeverContracts(unittest.TestCase):
    def test_forever_create_contract(self):
        for side in ("BUY", "SELL"):
            for product in ("CNC", "MTF"):
                for kind in ("LIMIT", "MARKET"):
                    for validity in ("DAY", "IOC"):
                        fields = create_fields() | {
                            "transactionType": side,
                            "productType": product,
                            "orderType": kind,
                            "validity": validity,
                        }
                        self.assertEqual(mapping.forever_create_payload(fields), fields)

    def test_forever_create_optional_fields(self):
        fields = create_fields() | {"correlationId": "correlation-example", "disclosedQuantity": "0"}
        self.assertEqual(mapping.forever_create_payload(fields), fields | {"disclosedQuantity": 0})

    def test_forever_create_oco(self):
        fields = create_fields() | {"orderFlag": "OCO", "quantity1": "10", "price1": 1420, "triggerPrice1": 1419}
        self.assertEqual(mapping.forever_create_payload(fields), fields | {"quantity1": 10})

    def test_forever_create_required_fields(self):
        for key in create_fields():
            fields = create_fields()
            del fields[key]
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(fields)

    def test_forever_create_rejects_unknown_fields(self):
        for key in ("orderId", "trigger_Price", "afterMarketOrder", "trailingJump", "unknown"):
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(create_fields() | {key: 1})

    def test_forever_create_rejects_invalid_enums(self):
        cases = {
            "transactionType": ("buy", "HOLD", None, []),
            "orderFlag": ("LIMIT", "oco", None, []),
            "orderType": ("STOP_LOSS", "STOP_LOSS_MARKET", "SINGLE", "OCO", "SL", []),
            "productType": ("INTRADAY", "MARGIN", "CO", "BO", "FUTURE_PRODUCT", []),
            "validity": ("GTC", "day", None, []),
        }
        for key, values in cases.items():
            for value in values:
                with self.assertRaises(ValueError):
                    mapping.forever_create_payload(create_fields() | {key: value})

    def test_forever_oco_requires_complete_leg(self):
        for flag in ("SINGLE", "OCO"):
            for mask in range(1 if flag == "SINGLE" else 0, 7):
                fields = create_fields() | {"orderFlag": flag}
                for bit, key in enumerate(("quantity1", "price1", "triggerPrice1")):
                    if mask & (1 << bit):
                        fields[key] = 10
                with self.assertRaises(ValueError):
                    mapping.forever_create_payload(fields)
        with self.assertRaises(ValueError):
            mapping.forever_create_payload(create_fields() | {"quantity1": 1, "price1": 1, "triggerPrice1": 1})

    def test_forever_oco_positive_fields(self):
        base = create_fields() | {"orderFlag": "OCO", "quantity1": 10, "price1": 1420, "triggerPrice1": 1419}
        for key in ("quantity1", "price1", "triggerPrice1"):
            for value in (0, -1, True, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    mapping.forever_create_payload(base | {key: value})

    def test_forever_modify_contract(self):
        for kind in ("LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_MARKET"):
            for flag, leg in (("SINGLE", "TARGET_LEG"), ("OCO", "TARGET_LEG"), ("OCO", "STOP_LOSS_LEG")):
                fields = modify_fields() | {"orderType": kind, "orderFlag": flag, "legName": leg}
                self.assertEqual(
                    mapping.forever_modify_payload("order-example", fields), fields | {"orderId": "order-example"}
                )

    def test_forever_modify_required_fields(self):
        for key in modify_fields():
            fields = modify_fields()
            del fields[key]
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", fields)

    def test_forever_modify_order_binding(self):
        fields = modify_fields() | {"orderId": "order-example"}
        self.assertEqual(mapping.forever_modify_payload("order-example", fields), fields)
        for value in ("different", "", None, 1, True):
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", fields | {"orderId": value})

    def test_forever_modify_rejects_invalid_fields(self):
        cases = {
            "legName": ("ENTRY_LEG", "STOP_LOSS_LEG", [], None),
            "orderType": ("OCO", "SINGLE", "SL", []),
            "orderFlag": ("LIMIT", []),
            "validity": ("GTC", []),
            "securityId": ("different",),
            "quantity1": (5,),
            "correlationId": ("correlation-example",),
        }
        for key, values in cases.items():
            for value in values:
                with self.assertRaises(ValueError):
                    mapping.forever_modify_payload("order-example", modify_fields() | {key: value})

    def test_request_identifiers(self):
        for value in ("", "  ", 1, True, None, []):
            for key in ("dhanClientId", "securityId", "exchangeSegment", "correlationId"):
                with self.assertRaises(ValueError):
                    mapping.forever_create_payload(create_fields() | {key: value})
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload(value, modify_fields())
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", modify_fields() | {"dhanClientId": value})

    def test_request_exact_quantities(self):
        for bad in (
            True,
            False,
            0,
            -1,
            1.5,
            1.0,
            "1.5",
            "1e2",
            "-1",
            "",
            float("inf"),
            float("nan"),
            None,
            Decimal("1"),
        ):
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(create_fields() | {"quantity": bad})
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", modify_fields() | {"quantity": bad})
        for value, expected in ((1, 1), ("12", 12), ("0012", 12)):
            self.assertEqual(
                mapping.forever_create_payload(create_fields() | {"quantity": value})["quantity"], expected
            )
            self.assertEqual(
                mapping.forever_modify_payload("order-example", modify_fields() | {"quantity": value})["quantity"],
                expected,
            )

    def test_request_disclosed_quantities(self):
        for value in (0, "0", 1, "1"):
            self.assertEqual(
                mapping.forever_create_payload(create_fields() | {"disclosedQuantity": value})["disclosedQuantity"],
                int(value),
            )
        for value in (True, -1, 1.5, "1.5", float("nan")):
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(create_fields() | {"disclosedQuantity": value})
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", modify_fields() | {"disclosedQuantity": value})

    def test_request_prices(self):
        for key in ("price", "triggerPrice"):
            for value in (True, None, "12", Decimal("12"), float("nan"), float("inf"), -1):
                with self.assertRaises(ValueError):
                    mapping.forever_create_payload(create_fields() | {key: value})
                with self.assertRaises(ValueError):
                    mapping.forever_modify_payload("order-example", modify_fields() | {key: value})
        for factory, call in (
            (create_fields, mapping.forever_create_payload),
            (modify_fields, lambda fields: mapping.forever_modify_payload("order-example", fields)),
        ):
            with self.assertRaises(ValueError):
                call(factory() | {"triggerPrice": 0})
            self.assertEqual(call(factory() | {"orderType": "MARKET", "price": 0})["price"], 0)

    def test_inputs_are_mappings_and_unchanged(self):
        for value in (None, [], "fields", 1):
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(value)
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", value)
            with self.assertRaises(ValueError):
                mapping.project_forever(value)
        fields = create_fields()
        snapshot = copy.deepcopy(fields)
        result = mapping.forever_create_payload(MappingProxyType(fields))
        result["quantity"] = 99
        self.assertEqual(fields, snapshot)
        changes = modify_fields()
        snapshot = copy.deepcopy(changes)
        mapping.forever_modify_payload("order-example", MappingProxyType(changes))
        self.assertEqual(changes, snapshot)

    def test_forever_projection(self):
        row = {
            "dhanClientId": "client-example",
            "orderId": "order-example",
            "orderStatus": "CONFIRM",
            "orderType": "SINGLE",
            "productType": "CNC",
            "exchangeSegment": "NSE_EQ",
            "legName": "ENTRY_LEG",
            "quantity": 10,
            "createTime": "2022-08-05 12:41:19",
            "updateTime": None,
            "exchangeTime": None,
        }
        result = mapping.project_forever(row)
        self.assertEqual(result["order_flag"], "SINGLE")
        self.assertEqual(result["pricetype"], "")
        self.assertEqual(result["source_fields"], row)
        for key, value in row.items():
            self.assertEqual(result[key], value)

    def test_projection_execution_type_and_flag(self):
        for kind in ("LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_MARKET", "FUTURE_TYPE"):
            result = mapping.project_forever({"orderType": kind, "orderFlag": "OCO"})
            self.assertEqual(result["pricetype"], kind)
            self.assertEqual(result["order_flag"], "OCO")
        for flag in ("SINGLE", "OCO"):
            self.assertEqual(mapping.project_forever({"orderType": flag, "orderFlag": flag})["pricetype"], "")
        with self.assertRaises(ValueError):
            mapping.project_forever({"orderType": "SINGLE", "orderFlag": "OCO"})
        with self.assertRaises(ValueError):
            mapping.project_forever({"orderType": "OCO", "orderFlag": "SINGLE"})

    def test_projection_preserves_historical_products_and_segments(self):
        for product in ("CNC", "MTF", "INTRADAY", "MARGIN", "CO", "BO", "FUTURE_PRODUCT"):
            for segment in ("NSE_EQ", "NSE_FNO", "BSE_EQ", "MCX_COMM", "FUTURE_SEGMENT"):
                row = {"productType": product, "exchangeSegment": segment}
                result = mapping.project_forever(row)
                self.assertEqual(result["productType"], product)
                self.assertEqual(result["exchangeSegment"], segment)
                self.assertEqual(result["source_fields"], row)

    def test_projection_missing_evidence_stays_missing(self):
        result = mapping.project_forever({"orderId": "order-example", "orderStatus": "TRADED"})
        self.assertNotIn("order_flag", result)
        self.assertNotIn("pricetype", result)
        for key in (
            "filledQty",
            "remainingQuantity",
            "validity",
            "children",
            "childOrderId",
            "reduceOnly",
            "terminal",
            "closed",
            "filled_quantity",
            "averagePrice",
        ):
            self.assertNotIn(key, result)
            self.assertNotIn(key, result["source_fields"])

    def test_projection_preserves_status_and_quantities(self):
        for status in ("PENDING", "TRADED", "CANCEL_PENDING", "CANCELLED", "CONFIRM", "FUTURE_STATUS"):
            row = {
                "orderStatus": status,
                "quantity": 10,
                "remainingQuantity": 7,
                "filledQty": 3,
                "validity": "IOC",
                "averagePrice": 12.5,
            }
            result = mapping.project_forever(row)
            for key, value in row.items():
                self.assertEqual(result[key], value)

    def test_projection_independent_copies(self):
        row = {
            "orderId": "parent-example",
            "orderStatus": "TRADED",
            "legs": [
                {"orderId": "parent-example", "legName": "TARGET_LEG", "orderStatus": "PENDING"},
                {"orderId": "parent-example", "legName": "STOP_LOSS_LEG", "orderStatus": "CANCEL_PENDING"},
            ],
        }
        snapshot = copy.deepcopy(row)
        result = mapping.project_forever(MappingProxyType(row))
        self.assertEqual(result["legs"], snapshot["legs"])
        self.assertEqual(result["source_fields"], snapshot)
        result["legs"][0]["orderStatus"] = "CHANGED"
        self.assertEqual(result["source_fields"], snapshot)
        self.assertEqual(row, snapshot)
        result["source_fields"]["legs"][1]["orderStatus"] = "CHANGED"
        self.assertEqual(row, snapshot)

    def test_projection_unknown_evidence_is_not_interpreted(self):
        row = {"orderFlag": "FUTURE_FLAG", "orderType": None, "quantity": None, "vendorExtension": {"x": [1]}}
        result = mapping.project_forever(row)
        self.assertEqual(result["source_fields"], row)
        self.assertEqual(result["order_flag"], "FUTURE_FLAG")
        self.assertIsNone(result["pricetype"])

    def test_modify_normalises_string_disclosed_quantity(self):
        fields = modify_fields() | {"disclosedQuantity": "0002"}
        result = mapping.forever_modify_payload("order-example", fields)
        self.assertEqual(result, fields | {"orderId": "order-example", "disclosedQuantity": 2})
        self.assertIs(type(result["disclosedQuantity"]), int)
        self.assertEqual(fields["disclosedQuantity"], "0002")

    def test_projection_family_only_oco(self):
        row = {"orderType": "OCO"}
        self.assertEqual(
            mapping.project_forever(row),
            {"orderType": "OCO", "order_flag": "OCO", "pricetype": "", "source_fields": row},
        )

    def test_projection_execution_only_limit(self):
        row = {"orderType": "LIMIT"}
        self.assertEqual(
            mapping.project_forever(row),
            {"orderType": "LIMIT", "pricetype": "LIMIT", "source_fields": row},
        )

    def test_rejected_requests_preserve_inputs(self):
        create_cases = (
            create_fields() | {"quantity": "005", "orderFlag": "OCO", "quantity1": "002"},
            create_fields() | {"quantity": "005", "productType": "INTRADAY"},
            create_fields() | {"unknown": {"nested": [1, 2]}},
        )
        for fields in create_cases:
            snapshot = copy.deepcopy(fields)
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(fields)
            self.assertEqual(fields, snapshot)
        modify_cases = (
            modify_fields() | {"quantity": "005", "disclosedQuantity": "000", "legName": "STOP_LOSS_LEG"},
            modify_fields() | {"quantity": "005", "triggerPrice": -1},
            modify_fields() | {"orderId": "different-example"},
            modify_fields() | {"unknown": {"nested": [1, 2]}},
        )
        for fields in modify_cases:
            snapshot = copy.deepcopy(fields)
            with self.assertRaises(ValueError):
                mapping.forever_modify_payload("order-example", fields)
            self.assertEqual(fields, snapshot)


def super_entry_fields():
    return {
        "dhanClientId": "client-example",
        "legName": "ENTRY_LEG",
        "orderType": "LIMIT",
        "quantity": 5,
        "price": 1500,
        "targetPrice": 1600,
        "stopLossPrice": 1400,
        "trailingJump": 10,
    }


class SuperContracts(unittest.TestCase):
    def test_super_modify_leg_fields(self):
        fields = super_entry_fields()
        self.assertEqual(mapping.super_modify_payload("order-example", fields), fields | {"orderId": "order-example"})

    def test_super_modify_market_entry(self):
        fields = super_entry_fields() | {"orderType": "MARKET", "price": 0}
        self.assertEqual(mapping.super_modify_payload("order-example", fields), fields | {"orderId": "order-example"})

    def test_super_modify_target_leg(self):
        fields = {"dhanClientId": "client-example", "legName": "TARGET_LEG", "targetPrice": 1600.5}
        self.assertEqual(mapping.super_modify_payload("order-example", fields), fields | {"orderId": "order-example"})

    def test_super_modify_stop_loss_leg(self):
        fields = {
            "dhanClientId": "client-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 1400.5, "trailingJump": 2.5
        }
        self.assertEqual(mapping.super_modify_payload("order-example", fields), fields | {"orderId": "order-example"})

    def test_super_modify_requires_explicit_leg_fields(self):
        for fields in (
            super_entry_fields(),
            {"dhanClientId": "client-example", "legName": "TARGET_LEG", "targetPrice": 1600},
            {"dhanClientId": "client-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 1400, "trailingJump": 10},
        ):
            for key in fields:
                changes = fields.copy()
                del changes[key]
                with self.assertRaises(ValueError):
                    mapping.super_modify_payload("order-example", changes)

    def test_super_modify_zero_trailing_is_intentional(self):
        for fields in (
            super_entry_fields(),
            {"dhanClientId": "client-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 1400},
        ):
            result = mapping.super_modify_payload("order-example", fields | {"trailingJump": 0})
            self.assertEqual(result["trailingJump"], 0)
            self.assertIs(type(result["trailingJump"]), int)

    def test_super_modify_rejects_irrelevant_edits(self):
        target = {"dhanClientId": "client-example", "legName": "TARGET_LEG", "targetPrice": 1600}
        stop = {"dhanClientId": "client-example", "legName": "STOP_LOSS_LEG", "stopLossPrice": 1400, "trailingJump": 10}
        for fields, keys in (
            (target, ("quantity", "price", "orderType", "stopLossPrice", "trailingJump")),
            (stop, ("quantity", "price", "orderType", "targetPrice")),
            (super_entry_fields(), ("securityId", "correlationId", "transactionType", "validity", "unknown")),
        ):
            for key in keys:
                with self.assertRaises(ValueError):
                    mapping.super_modify_payload("order-example", fields | {key: 1})

    def test_super_modify_rejects_invalid_enums(self):
        for kind in ("STOP_LOSS", "STOP_LOSS_MARKET", "SL", "limit", None, []):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", super_entry_fields() | {"orderType": kind})
        for leg in ("ENTRY", "entry_leg", "", None, []):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", super_entry_fields() | {"legName": leg})

    def test_super_modify_order_binding(self):
        fields = super_entry_fields() | {"orderId": "order-example"}
        self.assertEqual(mapping.super_modify_payload("order-example", fields), fields)
        for value in ("different", "", None, 1, True):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", fields | {"orderId": value})

    def test_super_modify_identifiers(self):
        for value in ("", "  ", 1, True, None, []):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload(value, super_entry_fields())
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", super_entry_fields() | {"dhanClientId": value})

    def test_super_modify_exact_quantity(self):
        for value, expected in ((1, 1), ("0012", 12)):
            fields = super_entry_fields() | {"quantity": value}
            result = mapping.super_modify_payload("order-example", fields)
            self.assertEqual(result["quantity"], expected)
            self.assertIs(type(result["quantity"]), int)
            self.assertEqual(fields["quantity"], value)
        for value in (True, False, 0, -1, 1.5, 1.0, "1.5", "1e2", "-1", "", float("inf"), float("nan"), None):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", super_entry_fields() | {"quantity": value})

    def test_super_modify_prices(self):
        for key in ("price", "targetPrice", "stopLossPrice", "trailingJump"):
            for value in (True, None, "12", Decimal("12"), float("nan"), float("inf"), -1):
                with self.assertRaises(ValueError):
                    mapping.super_modify_payload("order-example", super_entry_fields() | {key: value})
        for key in ("targetPrice", "stopLossPrice"):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", super_entry_fields() | {key: 0})

    def test_super_inputs_are_mappings_and_unchanged(self):
        for value in (None, [], "fields", 1):
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", value)
            with self.assertRaises(ValueError):
                mapping.project_super(value)
        fields = super_entry_fields() | {"quantity": "005"}
        snapshot = copy.deepcopy(fields)
        result = mapping.super_modify_payload("order-example", MappingProxyType(fields))
        result["quantity"] = 99
        self.assertEqual(fields, snapshot)

    def test_super_rejected_requests_preserve_inputs(self):
        for fields in (
            super_entry_fields() | {"quantity": "005", "trailingJump": -1},
            super_entry_fields() | {"orderId": "different-example"},
            super_entry_fields() | {"unknown": {"nested": [1, 2]}},
        ):
            snapshot = copy.deepcopy(fields)
            with self.assertRaises(ValueError):
                mapping.super_modify_payload("order-example", fields)
            self.assertEqual(fields, snapshot)

    def test_super_projection(self):
        row = {
            "dhanClientId": "client-example", "orderId": "parent-example", "exchangeOrderId": "exchange-example",
            "correlationId": "correlation-example", "orderStatus": "PART_TRADED", "legName": "ENTRY_LEG",
            "quantity": 10, "remainingQuantity": 7, "filledQty": 3, "price": 1500, "ltp": 1510.5,
            "averageTradedPrice": 1500.5, "targetPrice": 1600, "stopLossPrice": 1400, "trailingJump": 0,
            "createTime": "2025-02-27 19:09:42", "updateTime": None, "exchangeTime": None,
        }
        self.assertEqual(mapping.project_super(row), row | {"source_fields": row})

    def test_super_projection_preserves_live_children_after_parent_trade(self):
        row = {
            "orderId": "parent-example", "orderStatus": "TRADED", "filledQty": 10, "remainingQuantity": 0,
            "legDetails": [
                {"orderId": "parent-example", "legName": "TARGET_LEG", "orderStatus": "PENDING",
                 "remainingQuantity": 7, "triggeredQuantity": 3, "filledQty": 1, "price": 1600, "trailingJump": 0},
                {"orderId": "parent-example", "legName": "STOP_LOSS_LEG", "orderStatus": "CANCEL_PENDING",
                 "totalQuatity": 10, "remainingQuantity": 10, "triggeredQuantity": 0,
                 "price": 1400, "trailingJump": 10},
            ],
        }
        result = mapping.project_super(row)
        self.assertEqual(result, row | {"source_fields": row})
        self.assertEqual(len(result["legDetails"]), 2)
        for key in ("terminal", "closed", "reduceOnly", "childOrderId", "filled_quantity"):
            self.assertNotIn(key, result)
            for leg in result["legDetails"]:
                self.assertNotIn(key, leg)

    def test_super_projection_absent_evidence_stays_absent(self):
        for row in ({}, {"orderId": "order-example", "orderStatus": "TRADED"}, {"legDetails": []}):
            self.assertEqual(mapping.project_super(row), row | {"source_fields": row})

    def test_super_projection_unknown_statuses_and_extensions_survive(self):
        for status in ("TRIGGERED", "CLOSED", "CANCELLED", "CANCEL_PENDING", "FUTURE_COMPLETE", "", None):
            row = {
                "orderStatus": status, "productType": "FUTURE_PRODUCT", "exchangeSegment": "FUTURE_SEGMENT",
                "legDetails": [{"orderStatus": status, "vendorExtension": {"x": [1]}}],
            }
            self.assertEqual(mapping.project_super(row), row | {"source_fields": row})

    def test_super_projection_finite_numbers_are_not_coerced(self):
        for value in (0, 1, 1.5, -1, 10**400):
            row = {"quantity": value, "legDetails": [{"totalQuatity": value}]}
            result = mapping.project_super(row)
            self.assertEqual(result, row | {"source_fields": row})
            self.assertIs(type(result["quantity"]), type(value))

    def test_super_projection_rejects_invalid_numeric_evidence(self):
        for key in (
            "quantity", "remainingQuantity", "filledQty", "totalQuatity", "triggeredQuantity", "price", "ltp",
            "averageTradedPrice", "targetPrice", "stopLossPrice", "trailingJump",
        ):
            for value in (True, False, None, "12", Decimal("12"), float("nan"), float("inf"), -float("inf")):
                with self.assertRaises(ValueError):
                    mapping.project_super({key: value})
                with self.assertRaises(ValueError):
                    mapping.project_super({"legDetails": [{key: value}]})

    def test_super_projection_rejects_malformed_leg_details(self):
        for legs in (None, "legs", {}, (), [None], ["leg"], [1], [[]]):
            with self.assertRaises(ValueError):
                mapping.project_super({"legDetails": legs})

    def test_super_projection_independent_copies(self):
        row = {
            "orderId": "parent-example", "legDetails": [{"orderId": "child-example", "price": 1400}],
            "vendorExtension": {"x": [1]},
        }
        snapshot = copy.deepcopy(row)
        result = mapping.project_super(MappingProxyType(row))
        result["legDetails"][0]["price"] = 99
        result["vendorExtension"]["x"].append(2)
        self.assertEqual(result["source_fields"], snapshot)
        self.assertEqual(row, snapshot)
        result["source_fields"]["legDetails"][0]["orderId"] = "changed"
        self.assertEqual(row, snapshot)
        self.assertEqual(result["legDetails"][0]["orderId"], "child-example")

    def test_super_projection_rejection_preserves_input(self):
        row = {"legDetails": [{"price": 1400}, {"totalQuatity": "bad"}], "vendorExtension": {"x": [1]}}
        snapshot = copy.deepcopy(row)
        with self.assertRaises(ValueError):
            mapping.project_super(row)
        self.assertEqual(row, snapshot)

    def test_super_projection_accepts_immutable_child_mapping(self):
        leg = {
            "orderId": "child-example", "legName": "STOP_LOSS_LEG", "orderStatus": "CANCEL_PENDING",
            "remainingQuantity": 7, "price": 1400, "vendorExtension": {"x": [1]},
        }
        row = {"orderId": "parent-example", "legDetails": [MappingProxyType(leg)]}
        snapshot = {"orderId": "parent-example", "legDetails": [copy.deepcopy(leg)]}
        result = mapping.project_super(MappingProxyType(row))
        self.assertEqual(result, snapshot | {"source_fields": snapshot})
        result["legDetails"][0]["vendorExtension"]["x"].append(2)
        self.assertEqual(result["source_fields"], snapshot)
        self.assertEqual(row, snapshot)
        result["source_fields"]["legDetails"][0]["remainingQuantity"] = 1
        self.assertEqual(result["legDetails"][0]["remainingQuantity"], 7)
        self.assertEqual(row, snapshot)
        leg["vendorExtension"]["x"].append(3)
        self.assertEqual(result["legDetails"][0]["vendorExtension"]["x"], [1, 2])
        self.assertEqual(result["source_fields"]["legDetails"][0]["vendorExtension"]["x"], [1])


def normal_fields():
    return {
        "dhanClientId": "client-example",
        "securityId": "security-example",
        "exchangeSegment": "NSE_EQ",
        "transactionType": "BUY",
        "productType": "CNC",
        "orderType": "LIMIT",
        "validity": "DAY",
        "quantity": 5,
        "price": 1428,
    }


class NormalContracts(unittest.TestCase):
    def test_normal_wire_contract(self):
        for side in ("BUY", "SELL"):
            for product in ("CNC", "INTRADAY", "MARGIN", "MTF", "CO", "BO"):
                for kind in ("LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_MARKET"):
                    for validity in ("DAY", "IOC"):
                        fields = normal_fields() | {
                            "transactionType": side, "productType": product, "orderType": kind,
                            "validity": validity, "triggerPrice": 1400,
                        }
                        self.assertEqual(mapping.normal_order_payload(fields), fields)

    def test_normal_requires_all_core_fields(self):
        for key in normal_fields():
            fields = normal_fields()
            del fields[key]
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(fields)

    def test_normal_rejects_unknown_fields(self):
        for key in ("orderId", "orderFlag", "trigger_Price", "legName", "slice", "endpoint", "reduceOnly", "unknown"):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {key: 1})

    def test_normal_rejects_invalid_enums(self):
        cases = {
            "transactionType": ("buy", "HOLD", None, []),
            "productType": ("MIS", "SUPER", "FUTURE_PRODUCT", None, []),
            "orderType": ("SL", "SL-M", "SINGLE", "OCO", "limit", None, []),
            "validity": ("GTC", "day", None, []),
        }
        for key, values in cases.items():
            for value in values:
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(normal_fields() | {key: value})

    def test_normal_identifiers(self):
        for key in ("dhanClientId", "securityId", "exchangeSegment", "correlationId"):
            for value in ("", "  ", True, 1, None, []):
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(normal_fields() | {key: value})

    def test_normal_retains_optional_native_fields(self):
        fields = normal_fields() | {"correlationId": "correlation-example", "disclosedQuantity": "0002"}
        result = mapping.normal_order_payload(fields)
        self.assertEqual(result, fields | {"disclosedQuantity": 2})
        self.assertIs(type(result["disclosedQuantity"]), int)
        self.assertEqual(fields["disclosedQuantity"], "0002")

    def test_normal_stop_types_require_trigger(self):
        for kind in ("STOP_LOSS", "STOP_LOSS_MARKET"):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {"orderType": kind})
            for value in (0, -1, True, None, "1", float("nan"), float("inf"), -float("inf")):
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(normal_fields() | {"orderType": kind, "triggerPrice": value})

    def test_normal_optional_trigger_is_validated(self):
        for kind in ("LIMIT", "MARKET"):
            for value in (0, 0.0, 12.5):
                fields = normal_fields() | {"orderType": kind, "triggerPrice": value}
                self.assertEqual(mapping.normal_order_payload(fields), fields)
            for value in (-1, True, None, "", "12", Decimal("12"), float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(normal_fields() | {"orderType": kind, "triggerPrice": value})

    def test_normal_prices_are_finite_builtin_numbers(self):
        for value in (True, False, None, "12", "", Decimal("12"), float("nan"), float("inf"), -float("inf"), -1):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {"price": value})
        for value in (0, 0.0, 12, 12.5, 10**400):
            fields = normal_fields() | {"price": value}
            result = mapping.normal_order_payload(fields)
            self.assertEqual(result, fields)
            self.assertIs(type(result["price"]), type(value))

    def test_normal_market_zero_price(self):
        fields = normal_fields() | {"orderType": "MARKET", "price": 0}
        self.assertEqual(mapping.normal_order_payload(fields), fields)

    def test_normal_bo_preserves_profit_and_stop_values(self):
        fields = normal_fields() | {"productType": "BO", "boProfitValue": 10, "boStopLossValue": 5}
        self.assertEqual(mapping.normal_order_payload(fields), fields)

    def test_normal_co_remains_distinct(self):
        fields = normal_fields() | {"productType": "CO", "triggerPrice": 1400}
        self.assertEqual(mapping.normal_order_payload(fields), fields)

    def test_normal_bo_values_preserve_finite_numbers(self):
        for key in ("boProfitValue", "boStopLossValue"):
            for value in (0, 1, 2.5, -2.5, 10**400):
                fields = normal_fields() | {"productType": "BO", key: value}
                result = mapping.normal_order_payload(fields)
                self.assertEqual(result, fields)
                self.assertIs(type(result[key]), type(value))

    def test_normal_bo_values_reject_nonfinite_and_non_numeric(self):
        for key in ("boProfitValue", "boStopLossValue"):
            for value in (True, False, None, "5", "", Decimal("5"), float("nan"), float("inf"), -float("inf")):
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(normal_fields() | {"productType": "BO", key: value})

    def test_exact_quantities(self):
        for factory, call in (
            (normal_fields, mapping.normal_order_payload),
            (create_fields, mapping.forever_create_payload),
            (modify_fields, lambda fields: mapping.forever_modify_payload("order-example", fields)),
            (super_entry_fields, lambda fields: mapping.super_modify_payload("order-example", fields)),
        ):
            for bad in (
                True, False, 0, -1, 1.5, 1.0, "0", "1.5", "1e2", "-1", "+1", " 1", "1 ", "", "١",
                float("inf"), -float("inf"), float("nan"), None, Decimal("1"),
            ):
                with self.assertRaises(ValueError):
                    call(factory() | {"quantity": bad})
            for value, expected in ((1, 1), ("12", 12), ("0012", 12), ("9007199254740993", 9007199254740993)):
                result = call(factory() | {"quantity": value})
                self.assertEqual(result["quantity"], expected)
                self.assertIs(type(result["quantity"]), int)

    def test_normal_disclosed_quantities(self):
        for value, expected in ((0, 0), ("0", 0), ("0012", 12), (12, 12)):
            self.assertEqual(
                mapping.normal_order_payload(normal_fields() | {"disclosedQuantity": value})["disclosedQuantity"],
                expected,
            )
        for value in (True, False, -1, 1.5, 1.0, "-1", "1.5", "1e2", None, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {"disclosedQuantity": value})

    def test_amo_timing(self):
        for timing in ("PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"):
            fields = normal_fields() | {"afterMarketOrder": True, "amoTime": timing}
            self.assertEqual(mapping.normal_order_payload(fields), fields)

    def test_amo_requires_explicit_valid_timing(self):
        with self.assertRaises(ValueError):
            mapping.normal_order_payload(normal_fields() | {"afterMarketOrder": True})
        for timing in (None, "", "open", "OPEN_15", True, 1, []):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {"afterMarketOrder": True, "amoTime": timing})

    def test_amo_flag_requires_actual_bool(self):
        for flag in (0, 1, "true", "false", None, [], {}):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(normal_fields() | {"afterMarketOrder": flag, "amoTime": "OPEN"})

    def test_normal_preserves_explicit_non_amo_flag(self):
        fields = normal_fields() | {"afterMarketOrder": False}
        self.assertEqual(mapping.normal_order_payload(fields), fields)
        for timing in ("PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"):
            self.assertEqual(mapping.normal_order_payload(fields | {"amoTime": timing}), fields | {"amoTime": timing})

    def test_normal_validates_timing_even_without_amo_true(self):
        for flag_fields in ({}, {"afterMarketOrder": False}):
            fields = normal_fields() | flag_fields
            self.assertEqual(mapping.normal_order_payload(fields | {"amoTime": "OPEN"}), fields | {"amoTime": "OPEN"})
            for timing in (None, "", "OPEN_15", [], 0):
                with self.assertRaises(ValueError):
                    mapping.normal_order_payload(fields | {"amoTime": timing})

    def test_normal_mapping_and_independence(self):
        for fields in (None, [], "fields", 1):
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(fields)
        fields = normal_fields() | {"quantity": "005", "disclosedQuantity": "000"}
        snapshot = fields.copy()
        result = mapping.normal_order_payload(MappingProxyType(fields))
        self.assertEqual(result, fields | {"quantity": 5, "disclosedQuantity": 0})
        result["quantity"] = 99
        self.assertEqual(fields, snapshot)

    def test_normal_rejection_preserves_input(self):
        for extra in ({"triggerPrice": -1}, {"afterMarketOrder": True}, {"unknown": {"nested": [1]}}):
            fields = normal_fields() | {"quantity": "005", "disclosedQuantity": "000"} | extra
            snapshot = copy.deepcopy(fields)
            with self.assertRaises(ValueError):
                mapping.normal_order_payload(fields)
            self.assertEqual(fields, snapshot)

    def test_normal_does_not_synthesize_defaults_or_slice_results(self):
        fields = normal_fields() | {"quantity": "100000"}
        self.assertEqual(mapping.normal_order_payload(fields), fields | {"quantity": 100000})


class SecondLegQuantityContracts(unittest.TestCase):
    def test_forever_oco_second_quantity_rejects_lossy_or_noncanonical_values(self):
        fields = create_fields() | {"orderFlag": "OCO", "quantity1": 10, "price1": 1420, "triggerPrice1": 1419}
        for value in (
            True, False, 0, -1, 1.5, 1.0, "0", "1.5", "1e2", "-1", "+1", " 1", "1 ", "", "١",
            float("inf"), -float("inf"), float("nan"), None, Decimal("1"),
        ):
            with self.assertRaises(ValueError):
                mapping.forever_create_payload(fields | {"quantity1": value})

    def test_forever_oco_second_quantity_preserves_large_exact_integer_strings(self):
        fields = create_fields() | {"orderFlag": "OCO", "quantity1": 10, "price1": 1420, "triggerPrice1": 1419}
        for value, expected in ((1, 1), ("12", 12), ("0012", 12), ("9007199254740993", 9007199254740993)):
            request = fields | {"quantity1": value}
            result = mapping.forever_create_payload(request)
            self.assertEqual(result, request | {"quantity1": expected})
            self.assertIs(type(result["quantity1"]), int)
            self.assertEqual(request["quantity1"], value)
