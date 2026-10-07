"""Independent literal contracts; loaded only by the reviewed offline runner."""

import unittest
from decimal import Decimal
from types import MappingProxyType

from flinttrade_gateway.brokers import indstocks_order_mapping as mapping


class NormalContracts(unittest.TestCase):
    def order(self, **changes):
        return {
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "pricetype": "LIMIT",
            "quantity": 2,
            "price": 100,
            **changes,
        }

    def place(self, **changes):
        return mapping.normal_payload(self.order(**changes), security_id="00123", algo_id="custom-0001")

    def test_normal_wire_nse(self):
        self.assertEqual(
            self.place(exchange="NSE", product="CNC"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "qty": 2,
                "order_type": "LIMIT",
                "validity": "DAY",
                "security_id": "00123",
                "is_amo": False,
                "algo_id": "custom-0001",
                "limit_price": 100,
            },
        )

    def test_normal_wire_bse(self):
        self.assertEqual(
            self.place(exchange="BSE", product="MIS"),
            {
                "txn_type": "BUY",
                "exchange": "BSE",
                "segment": "EQUITY",
                "product": "INTRADAY",
                "qty": 2,
                "order_type": "LIMIT",
                "validity": "DAY",
                "security_id": "00123",
                "is_amo": False,
                "algo_id": "custom-0001",
                "limit_price": 100,
            },
        )

    def test_normal_wire_nfo(self):
        self.assertEqual(
            self.place(exchange="NFO", product="NRML"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "DERIVATIVE",
                "product": "MARGIN",
                "qty": 2,
                "order_type": "LIMIT",
                "validity": "DAY",
                "security_id": "00123",
                "is_amo": False,
                "algo_id": "custom-0001",
                "limit_price": 100,
            },
        )

    def test_normal_wire_bfo(self):
        self.assertEqual(
            self.place(exchange="BFO", product="MIS"),
            {
                "txn_type": "BUY",
                "exchange": "BSE",
                "segment": "DERIVATIVE",
                "product": "INTRADAY",
                "qty": 2,
                "order_type": "LIMIT",
                "validity": "DAY",
                "security_id": "00123",
                "is_amo": False,
                "algo_id": "custom-0001",
                "limit_price": 100,
            },
        )

    def test_sell(self):
        self.assertEqual(self.place(action="SELL")["txn_type"], "SELL")

    def test_market_wire(self):
        self.assertEqual(
            self.place(pricetype="MARKET", price=0),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "qty": 2,
                "order_type": "MARKET",
                "validity": "DAY",
                "security_id": "00123",
                "is_amo": False,
                "algo_id": "custom-0001",
            },
        )

    def test_amo(self):
        self.assertIs(self.place(variety="amo")["is_amo"], True)

    def test_explicit_amo(self):
        self.assertIs(self.place(is_amo=True)["is_amo"], True)

    def test_aliases_equal(self):
        self.assertEqual(self.place(qty="2.0", limit_price=Decimal("100.0"))["qty"], 2)

    def test_native_alias_only(self):
        order = self.order()
        del order["quantity"]
        del order["price"]
        order.update(qty="2.0", limit_price="100.25")
        self.assertEqual(mapping.normal_payload(order, security_id="1", algo_id="0")["limit_price"], 100.25)

    def test_mapping_input(self):
        self.assertEqual(mapping.normal_payload(MappingProxyType(self.order()), security_id="1", algo_id="0")["qty"], 2)

    def test_missing_action(self):
        order = self.order()
        del order["action"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_missing_exchange(self):
        order = self.order()
        del order["exchange"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_missing_product(self):
        order = self.order()
        del order["product"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_missing_pricetype(self):
        order = self.order()
        del order["pricetype"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_missing_quantity(self):
        order = self.order()
        del order["quantity"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_missing_price(self):
        order = self.order()
        del order["price"]
        with self.assertRaises(ValueError):
            mapping.normal_payload(order, security_id="1", algo_id="0")

    def test_invalid_quantity_0(self):
        with self.assertRaises(ValueError):
            self.place(quantity=True)

    def test_invalid_quantity_1(self):
        with self.assertRaises(ValueError):
            self.place(quantity=False)

    def test_invalid_quantity_2(self):
        with self.assertRaises(ValueError):
            self.place(quantity=0)

    def test_invalid_quantity_3(self):
        with self.assertRaises(ValueError):
            self.place(quantity=-1)

    def test_invalid_quantity_4(self):
        with self.assertRaises(ValueError):
            self.place(quantity=1.5)

    def test_invalid_quantity_5(self):
        with self.assertRaises(ValueError):
            self.place(quantity="2.1")

    def test_invalid_quantity_6(self):
        with self.assertRaises(ValueError):
            self.place(quantity="NaN")

    def test_invalid_quantity_7(self):
        with self.assertRaises(ValueError):
            self.place(quantity="Infinity")

    def test_invalid_quantity_8(self):
        with self.assertRaises(ValueError):
            self.place(quantity=None)

    def test_invalid_quantity_9(self):
        with self.assertRaises(ValueError):
            self.place(quantity=[])

    def test_invalid_quantity_10(self):
        with self.assertRaises(ValueError):
            self.place(quantity="bad")

    def test_invalid_quantity_11(self):
        with self.assertRaises(ValueError):
            self.place(quantity="")

    def test_invalid_quantity_12(self):
        with self.assertRaises(ValueError):
            self.place(quantity=Decimal("sNaN"))

    def test_invalid_price_0(self):
        with self.assertRaises(ValueError):
            self.place(price=True)

    def test_invalid_price_1(self):
        with self.assertRaises(ValueError):
            self.place(price=0)

    def test_invalid_price_2(self):
        with self.assertRaises(ValueError):
            self.place(price=-1)

    def test_invalid_price_3(self):
        with self.assertRaises(ValueError):
            self.place(price="NaN")

    def test_invalid_price_4(self):
        with self.assertRaises(ValueError):
            self.place(price=float("inf"))

    def test_invalid_price_5(self):
        with self.assertRaises(ValueError):
            self.place(price=None)

    def test_invalid_price_6(self):
        with self.assertRaises(ValueError):
            self.place(price={})

    def test_invalid_price_7(self):
        with self.assertRaises(ValueError):
            self.place(price="bad")

    def test_invalid_price_8(self):
        with self.assertRaises(ValueError):
            self.place(price="1e-400")

    def test_invalid_price_9(self):
        with self.assertRaises(ValueError):
            self.place(price="1.234567890123456789")

    def test_invalid_action_0(self):
        with self.assertRaises(ValueError):
            self.place(action="HOLD")

    def test_invalid_action_1(self):
        with self.assertRaises(ValueError):
            self.place(action=None)

    def test_invalid_action_2(self):
        with self.assertRaises(ValueError):
            self.place(action=[])

    def test_invalid_exchange_0(self):
        with self.assertRaises(ValueError):
            self.place(exchange="MCX")

    def test_invalid_exchange_1(self):
        with self.assertRaises(ValueError):
            self.place(exchange=None)

    def test_invalid_exchange_2(self):
        with self.assertRaises(ValueError):
            self.place(exchange=[])

    def test_invalid_product_0(self):
        with self.assertRaises(ValueError):
            self.place(product="NRML")

    def test_invalid_product_1(self):
        with self.assertRaises(ValueError):
            self.place(product=None)

    def test_invalid_product_2(self):
        with self.assertRaises(ValueError):
            self.place(product=[])

    def test_invalid_pricetype_0(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="SL")

    def test_invalid_pricetype_1(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="SL-M")

    def test_invalid_pricetype_2(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="TRIGGER")

    def test_invalid_pricetype_3(self):
        with self.assertRaises(ValueError):
            self.place(pricetype=None)

    def test_invalid_pricetype_4(self):
        with self.assertRaises(ValueError):
            self.place(pricetype=[])

    def test_invalid_validity_0(self):
        with self.assertRaises(ValueError):
            self.place(validity="IOC")

    def test_invalid_validity_1(self):
        with self.assertRaises(ValueError):
            self.place(validity="GTC")

    def test_invalid_validity_2(self):
        with self.assertRaises(ValueError):
            self.place(validity=None)

    def test_invalid_variety_0(self):
        with self.assertRaises(ValueError):
            self.place(variety="gtt")

    def test_invalid_variety_1(self):
        with self.assertRaises(ValueError):
            self.place(variety="oco")

    def test_invalid_variety_2(self):
        with self.assertRaises(ValueError):
            self.place(variety=None)

    def test_invalid_is_amo_0(self):
        with self.assertRaises(ValueError):
            self.place(is_amo="false")

    def test_invalid_is_amo_1(self):
        with self.assertRaises(ValueError):
            self.place(is_amo=1)

    def test_invalid_is_amo_2(self):
        with self.assertRaises(ValueError):
            self.place(is_amo=None)

    def test_invalid_security_id_0(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), security_id="", algo_id="0")

    def test_invalid_security_id_1(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), security_id="  ", algo_id="0")

    def test_invalid_security_id_2(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), security_id=None, algo_id="0")

    def test_invalid_security_id_3(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), security_id=1, algo_id="0")

    def test_invalid_security_id_4(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), security_id=True, algo_id="0")

    def test_invalid_algo_id_0(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), algo_id="", security_id="1")

    def test_invalid_algo_id_1(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), algo_id="  ", security_id="1")

    def test_invalid_algo_id_2(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), algo_id=None, security_id="1")

    def test_invalid_algo_id_3(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), algo_id=1, security_id="1")

    def test_invalid_algo_id_4(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload(self.order(), algo_id=True, security_id="1")

    def test_derivative_cnc(self):
        with self.assertRaises(ValueError):
            self.place(exchange="NFO")

    def test_quantity_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(qty=3)

    def test_quantity_alias_invalid(self):
        with self.assertRaises(ValueError):
            self.place(qty=True)

    def test_price_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(limit_price=101)

    def test_price_alias_invalid(self):
        with self.assertRaises(ValueError):
            self.place(limit_price="oops")

    def test_amo_conflict(self):
        with self.assertRaises(ValueError):
            self.place(variety="amo", is_amo=False)

    def test_unknown_placement_typo(self):
        with self.assertRaises(ValueError):
            self.place(typo=1)

    def test_unknown_placement_stop_loss_price(self):
        with self.assertRaises(ValueError):
            self.place(stop_loss_price=1)

    def test_unknown_placement_trigger_price(self):
        with self.assertRaises(ValueError):
            self.place(trigger_price=1)

    def test_unknown_placement_segment(self):
        with self.assertRaises(ValueError):
            self.place(segment=1)

    def test_unknown_placement_security_id(self):
        with self.assertRaises(ValueError):
            self.place(security_id=1)

    def test_unknown_placement_algo_id(self):
        with self.assertRaises(ValueError):
            self.place(algo_id=1)

    def test_reject_trailing_flag(self):
        with self.assertRaises(ValueError):
            self.place(is_tsl=True)

    def test_reject_trailing_step(self):
        with self.assertRaises(ValueError):
            self.place(tsl_step_size=1)

    def test_reject_trailing_jump(self):
        with self.assertRaises(ValueError):
            self.place(trailing_jump=1)

    def test_reject_trailing_negative(self):
        with self.assertRaises(ValueError):
            self.place(trailing_jump=-1)

    def test_inactive_trailing(self):
        self.assertEqual(self.place(is_tsl=False, tsl_step_size="0", trailing_jump=0), self.place())

    def test_malformed_trailing_flag(self):
        with self.assertRaises(ValueError):
            self.place(is_tsl="true")

    def test_malformed_trailing_step(self):
        with self.assertRaises(ValueError):
            self.place(tsl_step_size="bad")

    def test_remarks_exact(self):
        self.assertEqual(self.place(remarks="  signal-001  ")["remarks"], "  signal-001  ")

    def test_remarks_empty(self):
        self.assertEqual(self.place(remarks="")["remarks"], "")

    def test_remarks_maximum(self):
        self.assertEqual(self.place(remarks="x" * 100)["remarks"], "x" * 100)

    def test_remarks_substring(self):
        self.assertEqual(self.place(remarks="my-TV-TERMINAL-clone")["remarks"], "my-TV-TERMINAL-clone")

    def test_remarks_long(self):
        with self.assertRaises(ValueError):
            self.place(remarks="x" * 101)

    def test_remarks_reserved(self):
        with self.assertRaises(ValueError):
            self.place(remarks="  tV-TeRmInAl  ")

    def test_remarks_null(self):
        with self.assertRaises(ValueError):
            self.place(remarks=None)

    def test_remarks_number(self):
        with self.assertRaises(ValueError):
            self.place(remarks=123)

    def test_modify_exact(self):
        self.assertEqual(
            mapping.normal_modify("DRV-2049", {"quantity": 75, "price": 73}, segment="DERIVATIVE"),
            {"order_id": "DRV-2049", "segment": "DERIVATIVE", "qty": 75, "limit_price": 73},
        )

    def test_modify_native_equal_aliases(self):
        self.assertEqual(
            mapping.normal_modify(
                "EQ-0001",
                {"qty": "2", "quantity": 2, "price": "73.25", "limit_price": Decimal("73.25")},
                segment="EQUITY",
            )["limit_price"],
            73.25,
        )

    def test_modify_gtt_explicit_segment(self):
        self.assertEqual(
            mapping.normal_modify("GTT-001", {"qty": 1, "price": 1}, segment="EQUITY")["segment"], "EQUITY"
        )

    def test_modify_invalid_0(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {}, segment="DERIVATIVE")

    def test_modify_invalid_1(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1}, segment="DERIVATIVE")

    def test_modify_invalid_2(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"price": 1}, segment="DERIVATIVE")

    def test_modify_invalid_3(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1, "price": 1, "quantity": 2}, segment="DERIVATIVE")

    def test_modify_invalid_4(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1, "price": 1, "limit_price": 2}, segment="DERIVATIVE")

    def test_modify_invalid_5(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": True, "price": 1}, segment="DERIVATIVE")

    def test_modify_invalid_6(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1.5, "price": 1}, segment="DERIVATIVE")

    def test_modify_invalid_7(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1, "price": "NaN"}, segment="DERIVATIVE")

    def test_modify_invalid_8(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1, "price": 0}, segment="DERIVATIVE")

    def test_modify_unknown_remarks(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "remarks": 0}, segment="EQUITY")

    def test_modify_unknown_is_tsl(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "is_tsl": 0}, segment="EQUITY")

    def test_modify_unknown_tsl_step_size(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "tsl_step_size": 0}, segment="EQUITY")

    def test_modify_unknown_trailing_jump(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "trailing_jump": 0}, segment="EQUITY")

    def test_modify_unknown_order_type(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "order_type": 0}, segment="EQUITY")

    def test_modify_unknown_security_id(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "security_id": 0}, segment="EQUITY")

    def test_modify_unknown_unknown(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1, "unknown": 0}, segment="EQUITY")

    def test_modify_identity_0(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("", {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_identity_1(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify(" ", {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_identity_2(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify(None, {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_identity_3(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify(1, {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_identity_4(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify([], {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_eq_conflict(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1}, segment="DERIVATIVE")

    def test_modify_drv_conflict(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("DRV-1", {"qty": 1, "price": 1}, segment="EQUITY")

    def test_modify_bad_segment(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("GTT-1", {"qty": 1, "price": 1}, segment="OTHER")

    def test_execution_effects_limit(self):
        order = {"pricetype": "LIMIT", "price": "100.25"}
        self.assertEqual(
            mapping.execution_effects(order),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "requested_type": order["pricetype"],
                "effective_type": "LIMIT",
                "effective_limit_price": 100.25,
                "trailing_active": False,
                "limitations": [],
                "requested": order,
            },
        )

    def test_execution_effects_market(self):
        order = {"pricetype": "MARKET", "price": 100}
        self.assertEqual(
            mapping.execution_effects(order),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "requested_type": order["pricetype"],
                "effective_type": "LIMIT",
                "effective_limit_price": None,
                "trailing_active": False,
                "limitations": ["MARKET_TO_LIMIT"],
                "requested": order,
            },
        )

    def test_execution_effects_trigger_default(self):
        order = {"pricetype": "TRIGGER", "trigger_price": 99}
        self.assertEqual(
            mapping.execution_effects(order),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "requested_type": order["pricetype"],
                "effective_type": "TRIGGER_LIMIT",
                "effective_limit_price": 99,
                "trailing_active": False,
                "limitations": [],
                "requested": order,
            },
        )

    def test_execution_effects_trigger_explicit(self):
        order = {"pricetype": "TRIGGER", "trigger_price": 99, "price": 100}
        self.assertEqual(
            mapping.execution_effects(order),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "requested_type": order["pricetype"],
                "effective_type": "TRIGGER_LIMIT",
                "effective_limit_price": 100,
                "trailing_active": False,
                "limitations": [],
                "requested": order,
            },
        )

    def test_execution_effects_trigger_native(self):
        order = {"pricetype": "TRIGGER", "trigger_price": 99, "trigger_limit_price": 100}
        self.assertEqual(
            mapping.execution_effects(order),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "requested_type": order["pricetype"],
                "effective_type": "TRIGGER_LIMIT",
                "effective_limit_price": 100,
                "trailing_active": False,
                "limitations": [],
                "requested": order,
            },
        )

    def test_effects_trailing_flag(self):
        result = mapping.execution_effects({"pricetype": "MARKET", "is_tsl": True})
        self.assertEqual(result["limitations"], ["MARKET_TO_LIMIT", "TSL_IGNORED"])
        self.assertIs(result["trailing_active"], False)

    def test_effects_trailing_step(self):
        result = mapping.execution_effects({"pricetype": "MARKET", "tsl_step_size": 1})
        self.assertEqual(result["limitations"], ["MARKET_TO_LIMIT", "TSL_IGNORED"])
        self.assertIs(result["trailing_active"], False)

    def test_effects_trailing_jump(self):
        result = mapping.execution_effects({"pricetype": "MARKET", "trailing_jump": -1})
        self.assertEqual(result["limitations"], ["MARKET_TO_LIMIT", "TSL_IGNORED"])
        self.assertIs(result["trailing_active"], False)

    def test_effects_trailing_all(self):
        result = mapping.execution_effects(
            {"pricetype": "MARKET", "is_tsl": True, "tsl_step_size": 1, "trailing_jump": 1}
        )
        self.assertEqual(result["limitations"], ["MARKET_TO_LIMIT", "TSL_IGNORED"])
        self.assertIs(result["trailing_active"], False)

    def test_effects_requested_copy(self):
        order = {"pricetype": "MARKET", "notes": "original"}
        result = mapping.execution_effects(order)
        order["notes"] = "changed"
        self.assertEqual(result["requested"]["notes"], "original")
        self.assertIsNot(result["requested"], order)

    def test_effects_inactive(self):
        self.assertEqual(
            mapping.execution_effects({"pricetype": "MARKET", "is_tsl": False, "trailing_jump": "0"})["limitations"],
            ["MARKET_TO_LIMIT"],
        )

    def test_effects_invalid_0(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({})

    def test_effects_invalid_1(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "SL"})

    def test_effects_invalid_2(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "LIMIT"})

    def test_effects_invalid_3(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER"})

    def test_effects_invalid_4(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 0})

    def test_effects_invalid_5(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 99, "price": 0})

    def test_effects_invalid_6(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 99, "limit_price": 100})

    def test_effects_invalid_7(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects(
                {"pricetype": "TRIGGER", "trigger_price": 99, "price": 100, "trigger_limit_price": 101}
            )

    def test_effects_invalid_8(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "is_tsl": 1})

    def test_effects_invalid_9(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "trailing_jump": "NaN"})

    def test_effects_invalid_10(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "price": 100, "limit_price": 101})

    def test_nonmapping_placement(self):
        with self.assertRaises(ValueError):
            mapping.normal_payload([], security_id="1", algo_id="0")

    def test_nonmapping_modify(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", [], segment="EQUITY")

    def test_nonmapping_effects(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects([])

    def test_exact_large_quantity(self):
        self.assertEqual(self.place(quantity="9007199254740993")["qty"], 9007199254740993)

    def test_large_quantity_conflict(self):
        with self.assertRaises(ValueError):
            self.place(quantity="9007199254740993", qty="9007199254740992")

    def test_native_intraday(self):
        self.assertEqual(self.place(product="INTRADAY")["product"], "INTRADAY")

    def test_native_margin(self):
        self.assertEqual(self.place(exchange="NFO", product="MARGIN")["product"], "MARGIN")

    def test_native_equity_margin(self):
        with self.assertRaises(ValueError):
            self.place(product="MARGIN")

    def test_market_without_price(self):
        order = self.order(pricetype="MARKET")
        del order["price"]
        self.assertNotIn("limit_price", mapping.normal_payload(order, security_id="1", algo_id="0"))

    def test_market_bad_price(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="MARKET", price="bad")

    def test_market_price_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="MARKET", limit_price=101)

    def test_placement_does_not_mutate(self):
        order = self.order(price="100.25", quantity="2")
        before = dict(order)
        mapping.normal_payload(order, security_id="1", algo_id="0")
        self.assertEqual(order, before)

    def test_modify_does_not_mutate(self):
        changes = {"price": "73", "qty": "75"}
        mapping.normal_modify("DRV-1", changes, segment="DERIVATIVE")
        self.assertEqual(changes, {"price": "73", "qty": "75"})

    def test_modify_mapping_proxy(self):
        self.assertEqual(
            mapping.normal_modify("EQ-1", MappingProxyType({"qty": 1, "price": 1}), segment="EQUITY")["qty"], 1
        )

    def test_modify_null_segment(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "price": 1}, segment=None)

    def test_modify_malformed_equal_alias(self):
        with self.assertRaises(ValueError):
            mapping.normal_modify("EQ-1", {"qty": 1, "quantity": True, "price": 1}, segment="EQUITY")

    def test_effects_market_trigger(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "trigger_price": 1})

    def test_effects_limit_trigger(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "LIMIT", "price": 1, "trigger_limit_price": 1})

    def test_effects_true_flag_invalid_step(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "is_tsl": True, "tsl_step_size": "bad"})

    def test_effects_negative_price(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "MARKET", "price": -1})

    def test_effects_invalid_alias(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "LIMIT", "price": 1, "limit_price": True})

    def test_effects_trigger_equal_alias(self):
        self.assertEqual(
            mapping.execution_effects(
                {"pricetype": "TRIGGER", "trigger_price": 99, "price": "100", "trigger_limit_price": 100}
            )["effective_limit_price"],
            100,
        )

    def test_effects_limit_trailing(self):
        self.assertEqual(
            mapping.execution_effects({"pricetype": "LIMIT", "price": 1, "is_tsl": True})["limitations"],
            ["TSL_IGNORED"],
        )

    def test_effects_trigger_trailing(self):
        self.assertEqual(
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 1, "is_tsl": True})["limitations"],
            ["TSL_IGNORED"],
        )

    def test_effects_mapping_proxy(self):
        self.assertEqual(
            mapping.execution_effects(MappingProxyType({"pricetype": "MARKET"}))["requested"], {"pricetype": "MARKET"}
        )

    def test_explicit_ids_unchanged(self):
        result = mapping.normal_payload(self.order(exchange="BSE"), security_id="000123", algo_id=" 000custom ")
        self.assertEqual(result["security_id"], "000123")
        self.assertEqual(result["algo_id"], " 000custom ")

    def test_wire_excludes_effects(self):
        self.assertNotIn("requested", self.place())
        self.assertNotIn("limitations", self.place())
        self.assertNotIn("schema_id", self.place())

    def test_regular_conflicts_with_explicit_amo(self):
        with self.assertRaises(ValueError):
            self.place(variety="regular", is_amo=True)

    def test_trigger_null_canonical_price_does_not_fall_back(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 99, "price": None})

    def test_trigger_null_native_price_does_not_fall_back(self):
        with self.assertRaises(ValueError):
            mapping.execution_effects({"pricetype": "TRIGGER", "trigger_price": 99, "trigger_limit_price": None})


class SmartContracts(unittest.TestCase):
    def order(self, **changes):
        return {
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "pricetype": "LIMIT",
            "quantity": 2,
            "price": 100,
            "variety": "gtt",
            "sl_trigger_price": 90,
            "sl_limit_price": 89,
            "tgt_trigger_price": 110,
            "tgt_limit_price": 111,
            **changes,
        }

    def place(self, **changes):
        return mapping.smart_payload(self.order(**changes), security_id="00123", algo_id="custom-0001")

    def modify(self, changes, existing="LIMIT", order_id="GTT-123", segment="EQUITY"):
        return mapping.smart_modify(
            order_id, changes, segment=segment, existing_order_type=existing, algo_id="custom-0001"
        )

    def test_exact_limit(self):
        self.assertEqual(
            self.place(),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_exact_market(self):
        self.assertEqual(
            self.place(pricetype="MARKET"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "MARKET",
            },
        )

    def test_exact_trigger(self):
        self.assertEqual(
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=99),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "TRIGGER",
                "trigger_price": 99,
                "trigger_limit_price": 100,
            },
        )

    def test_sell_directions(self):
        self.assertEqual(
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=111, tgt_trigger_price=90, tgt_limit_price=89
            ),
            {
                "txn_type": "SELL",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 110,
                "sl_limit_price": 111,
                "tgt_trigger_price": 90,
                "tgt_limit_price": 89,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_oco(self):
        self.assertEqual(self.place(variety="oco"), self.place())

    def test_trigger_without_explicit_limit(self):
        order = self.order(variety="trigger", pricetype="TRIGGER", trigger_price=100)
        del order["price"]
        self.assertEqual(
            mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "TRIGGER",
                "trigger_price": 100,
            },
        )

    def test_trigger_native_price(self):
        order = self.order(variety="trigger", pricetype="TRIGGER", trigger_price=99, trigger_limit_price=100)
        del order["price"]
        self.assertEqual(
            mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "TRIGGER",
                "trigger_price": 99,
                "trigger_limit_price": 100,
            },
        )

    def test_sl_alias(self):
        order = self.order(stop_loss_price=90)
        del order["sl_trigger_price"]
        self.assertEqual(mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"), self.place())

    def test_sl_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(stop_loss_price=95)

    def test_sl_trigger_price_unpaired(self):
        with self.assertRaises(ValueError):
            order = self.order()
            del order["sl_trigger_price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_sl_limit_price_unpaired(self):
        with self.assertRaises(ValueError):
            order = self.order()
            del order["sl_limit_price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_tgt_alias(self):
        order = self.order(target_price=110)
        del order["tgt_trigger_price"]
        self.assertEqual(mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"), self.place())

    def test_tgt_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(target_price=95)

    def test_tgt_trigger_price_unpaired(self):
        with self.assertRaises(ValueError):
            order = self.order()
            del order["tgt_trigger_price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_tgt_limit_price_unpaired(self):
        with self.assertRaises(ValueError):
            order = self.order()
            del order["tgt_limit_price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_direction_BUY_sl_trigger_price_100(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", sl_trigger_price=100)

    def test_direction_BUY_sl_trigger_price_101(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", sl_trigger_price=101)

    def test_direction_BUY_sl_limit_price_90(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", sl_limit_price=90)

    def test_direction_BUY_sl_limit_price_91(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", sl_limit_price=91)

    def test_direction_BUY_tgt_trigger_price_100(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", tgt_trigger_price=100)

    def test_direction_BUY_tgt_trigger_price_99(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", tgt_trigger_price=99)

    def test_direction_BUY_tgt_limit_price_110(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", tgt_limit_price=110)

    def test_direction_BUY_tgt_limit_price_109(self):
        with self.assertRaises(ValueError):
            self.place(action="BUY", tgt_limit_price=109)

    def test_direction_SELL_sl_trigger_price_100(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=100, sl_limit_price=111, tgt_trigger_price=90, tgt_limit_price=89
            )

    def test_direction_SELL_sl_trigger_price_99(self):
        with self.assertRaises(ValueError):
            self.place(action="SELL", sl_trigger_price=99, sl_limit_price=111, tgt_trigger_price=90, tgt_limit_price=89)

    def test_direction_SELL_sl_limit_price_110(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=110, tgt_trigger_price=90, tgt_limit_price=89
            )

    def test_direction_SELL_sl_limit_price_109(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=109, tgt_trigger_price=90, tgt_limit_price=89
            )

    def test_direction_SELL_tgt_trigger_price_100(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=111, tgt_trigger_price=100, tgt_limit_price=89
            )

    def test_direction_SELL_tgt_trigger_price_101(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=111, tgt_trigger_price=101, tgt_limit_price=89
            )

    def test_direction_SELL_tgt_limit_price_90(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=111, tgt_trigger_price=90, tgt_limit_price=90
            )

    def test_direction_SELL_tgt_limit_price_91(self):
        with self.assertRaises(ValueError):
            self.place(
                action="SELL", sl_trigger_price=110, sl_limit_price=111, tgt_trigger_price=90, tgt_limit_price=91
            )

    def test_regular(self):
        with self.assertRaises(ValueError):
            self.place(variety="regular")

    def test_amo(self):
        with self.assertRaises(ValueError):
            self.place(is_amo=False)

    def test_ioc(self):
        with self.assertRaises(ValueError):
            self.place(validity="IOC")

    def test_bad_action(self):
        with self.assertRaises(ValueError):
            self.place(action="HOLD")

    def test_bad_exchange(self):
        with self.assertRaises(ValueError):
            self.place(exchange="X")

    def test_bad_product(self):
        with self.assertRaises(ValueError):
            self.place(product="MARGIN")

    def test_trigger_gtt(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="TRIGGER", trigger_price=99)

    def test_limit_trigger(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger")

    def test_limit_trigger_price(self):
        with self.assertRaises(ValueError):
            self.place(trigger_price=99)

    def test_limit_trigger_limit(self):
        with self.assertRaises(ValueError):
            self.place(trigger_limit_price=100)

    def test_trigger_limit_price(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=99, limit_price=100)

    def test_trigger_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=99, trigger_limit_price=101)

    def test_active_tsl(self):
        with self.assertRaises(ValueError):
            self.place(is_tsl=True)

    def test_active_step(self):
        with self.assertRaises(ValueError):
            self.place(tsl_step_size=1)

    def test_active_jump(self):
        with self.assertRaises(ValueError):
            self.place(trailing_jump=-1)

    def test_unknown(self):
        with self.assertRaises(ValueError):
            self.place(unknown=1)

    def test_remarks_long(self):
        with self.assertRaises(ValueError):
            self.place(remarks="x" * 101)

    def test_remarks_reserved(self):
        with self.assertRaises(ValueError):
            self.place(remarks=" TV-Terminal ")

    def test_qty_alias_conflict(self):
        with self.assertRaises(ValueError):
            self.place(qty=3)

    def test_quantity_zero(self):
        with self.assertRaises(ValueError):
            self.place(quantity=0)

    def test_quantity_negative(self):
        with self.assertRaises(ValueError):
            self.place(quantity=-1)

    def test_quantity_bool(self):
        with self.assertRaises(ValueError):
            self.place(quantity=True)

    def test_quantity_null(self):
        with self.assertRaises(ValueError):
            self.place(quantity=None)

    def test_quantity_nan(self):
        with self.assertRaises(ValueError):
            self.place(quantity="NaN")

    def test_quantity_infinite(self):
        with self.assertRaises(ValueError):
            self.place(quantity="Infinity")

    def test_price_zero(self):
        with self.assertRaises(ValueError):
            self.place(price=0)

    def test_price_negative(self):
        with self.assertRaises(ValueError):
            self.place(price=-1)

    def test_price_bool(self):
        with self.assertRaises(ValueError):
            self.place(price=True)

    def test_price_null(self):
        with self.assertRaises(ValueError):
            self.place(price=None)

    def test_price_nan(self):
        with self.assertRaises(ValueError):
            self.place(price="NaN")

    def test_price_infinite(self):
        with self.assertRaises(ValueError):
            self.place(price="Infinity")

    def test_sl_trigger_price_zero(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price=0)

    def test_sl_trigger_price_negative(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price=-1)

    def test_sl_trigger_price_bool(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price=True)

    def test_sl_trigger_price_null(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price=None)

    def test_sl_trigger_price_nan(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price="NaN")

    def test_sl_trigger_price_infinite(self):
        with self.assertRaises(ValueError):
            self.place(sl_trigger_price="Infinity")

    def test_sl_limit_price_zero(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price=0)

    def test_sl_limit_price_negative(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price=-1)

    def test_sl_limit_price_bool(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price=True)

    def test_sl_limit_price_null(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price=None)

    def test_sl_limit_price_nan(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price="NaN")

    def test_sl_limit_price_infinite(self):
        with self.assertRaises(ValueError):
            self.place(sl_limit_price="Infinity")

    def test_tgt_trigger_price_zero(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price=0)

    def test_tgt_trigger_price_negative(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price=-1)

    def test_tgt_trigger_price_bool(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price=True)

    def test_tgt_trigger_price_null(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price=None)

    def test_tgt_trigger_price_nan(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price="NaN")

    def test_tgt_trigger_price_infinite(self):
        with self.assertRaises(ValueError):
            self.place(tgt_trigger_price="Infinity")

    def test_tgt_limit_price_zero(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price=0)

    def test_tgt_limit_price_negative(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price=-1)

    def test_tgt_limit_price_bool(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price=True)

    def test_tgt_limit_price_null(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price=None)

    def test_tgt_limit_price_nan(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price="NaN")

    def test_tgt_limit_price_infinite(self):
        with self.assertRaises(ValueError):
            self.place(tgt_limit_price="Infinity")

    def test_fractional_qty(self):
        with self.assertRaises(ValueError):
            self.place(quantity=1.5)

    def test_market_invalid_price(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="MARKET", price="bad")

    def test_market_trigger_field(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="MARKET", trigger_price=100)

    def test_remarks(self):
        self.assertEqual(self.place(remarks="signal"), self.place() | {"remarks": "signal"})

    def test_inactive_trailing(self):
        self.assertEqual(self.place(is_tsl=False, tsl_step_size=0, trailing_jump=0), self.place())

    def test_market_no_invented_entry(self):
        self.assertEqual(
            self.place(
                pricetype="MARKET",
                price=0,
                sl_trigger_price=200,
                sl_limit_price=199,
                tgt_trigger_price=10,
                tgt_limit_price=11,
            ),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 200,
                "sl_limit_price": 199,
                "tgt_trigger_price": 10,
                "tgt_limit_price": 11,
                "order_type": "MARKET",
            },
        )

    def test_trigger_effective_entry(self):
        self.assertEqual(self.place(variety="trigger", pricetype="TRIGGER", trigger_price=120)["sl_trigger_price"], 90)

    def test_trigger_no_legs(self):
        order = {
            "action": "SELL",
            "exchange": "NFO",
            "product": "NRML",
            "pricetype": "TRIGGER",
            "quantity": 75,
            "variety": "trigger",
            "trigger_price": 100,
        }
        self.assertEqual(
            mapping.smart_payload(order, security_id="s", algo_id="a"),
            {
                "txn_type": "SELL",
                "exchange": "NSE",
                "segment": "DERIVATIVE",
                "product": "MARGIN",
                "order_type": "TRIGGER",
                "validity": "DAY",
                "qty": 75,
                "trigger_price": 100,
                "security_id": "s",
                "algo_id": "a",
            },
        )

    def test_gtt_no_legs(self):
        with self.assertRaises(ValueError):
            order = self.order()
            for field in ("sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price"):
                del order[field]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_modify_empty(self):
        self.assertEqual(
            self.modify({}, "LIMIT"), {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001"}
        )

    def test_modify_limit(self):
        self.assertEqual(
            self.modify({"qty": 2, "price": 101, "order_type": "LIMIT"}, "LIMIT"),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "qty": 2,
                "limit_price": 101,
                "order_type": "LIMIT",
            },
        )

    def test_modify_market(self):
        self.assertEqual(
            self.modify({"quantity": 3}, "MARKET"),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "qty": 3},
        )

    def test_modify_trigger(self):
        self.assertEqual(
            self.modify({"trigger_price": 99, "price": 100, "order_type": "TRIGGER"}, "TRIGGER"),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "trigger_price": 99,
                "trigger_limit_price": 100,
                "order_type": "TRIGGER",
            },
        )

    def test_modify_trigger_no_limit(self):
        self.assertEqual(
            self.modify({"trigger_price": 99}, "TRIGGER"),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "trigger_price": 99},
        )

    def test_modify_partial_leg(self):
        self.assertEqual(
            self.modify({"sl_trigger_price": 90}, "LIMIT"),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "sl_trigger_price": 90},
        )

    def test_modify_aliases(self):
        self.assertEqual(
            self.modify({"stop_loss_price": 90, "target_price": 110}, "LIMIT"),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "tgt_trigger_price": 110,
            },
        )

    def test_modify_equal_aliases(self):
        self.assertEqual(
            self.modify({"qty": 2, "quantity": "2.0", "price": 100, "limit_price": "100.0"}, "LIMIT"),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "qty": 2, "limit_price": 100},
        )

    def test_modify_type_mismatch(self):
        with self.assertRaises(ValueError):
            self.modify({"order_type": "TRIGGER"}, "LIMIT")

    def test_modify_existing_unknown(self):
        with self.assertRaises(ValueError):
            self.modify({}, "SL")

    def test_modify_type_unknown(self):
        with self.assertRaises(ValueError):
            self.modify({"order_type": "SL"}, "LIMIT")

    def test_modify_trigger_required(self):
        with self.assertRaises(ValueError):
            self.modify({"qty": 2}, "TRIGGER")

    def test_modify_trigger_limit_forbidden(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_price": 99, "limit_price": 100}, "TRIGGER")

    def test_modify_trigger_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_price": 99, "price": 100, "trigger_limit_price": 101}, "TRIGGER")

    def test_modify_market_price(self):
        with self.assertRaises(ValueError):
            self.modify({"price": 100}, "MARKET")

    def test_modify_market_limit(self):
        with self.assertRaises(ValueError):
            self.modify({"limit_price": 100}, "MARKET")

    def test_modify_limit_trigger(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_price": 99}, "LIMIT")

    def test_modify_limit_trigger_limit(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_limit_price": 100}, "LIMIT")

    def test_modify_remarks(self):
        with self.assertRaises(ValueError):
            self.modify({"remarks": "x"}, "LIMIT")

    def test_modify_tsl(self):
        with self.assertRaises(ValueError):
            self.modify({"is_tsl": False}, "LIMIT")

    def test_modify_step(self):
        with self.assertRaises(ValueError):
            self.modify({"tsl_step_size": 0}, "LIMIT")

    def test_modify_jump(self):
        with self.assertRaises(ValueError):
            self.modify({"trailing_jump": 0}, "LIMIT")

    def test_modify_unknown(self):
        with self.assertRaises(ValueError):
            self.modify({"unknown": 1}, "LIMIT")

    def test_modify_quantity_fraction(self):
        with self.assertRaises(ValueError):
            self.modify({"quantity": 1.5}, "LIMIT")

    def test_modify_quantity_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({"qty": 2, "quantity": 3}, "LIMIT")

    def test_modify_price_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({"price": 100, "limit_price": 101}, "LIMIT")

    def test_modify_leg_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({"stop_loss_price": 90, "sl_trigger_price": 91}, "LIMIT")

    def test_modify_null_trigger(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_price": None}, "TRIGGER")

    def test_modify_null_trigger_limit(self):
        with self.assertRaises(ValueError):
            self.modify({"trigger_price": 99, "price": None}, "TRIGGER")

    def test_modify_invalid_sl_trigger_price(self):
        with self.assertRaises(ValueError):
            self.modify({"sl_trigger_price": 0})

    def test_modify_invalid_sl_limit_price(self):
        with self.assertRaises(ValueError):
            self.modify({"sl_limit_price": 0})

    def test_modify_invalid_tgt_trigger_price(self):
        with self.assertRaises(ValueError):
            self.modify({"tgt_trigger_price": 0})

    def test_modify_invalid_tgt_limit_price(self):
        with self.assertRaises(ValueError):
            self.modify({"tgt_limit_price": 0})

    def test_cancel_GTT_1_EQUITY(self):
        self.assertEqual(mapping.cancel_payload("GTT-1", segment="EQUITY"), {"order_id": "GTT-1", "segment": "EQUITY"})

    def test_cancel_GTT_1_DERIVATIVE(self):
        self.assertEqual(
            mapping.cancel_payload("GTT-1", segment="DERIVATIVE"), {"order_id": "GTT-1", "segment": "DERIVATIVE"}
        )

    def test_cancel_EQ_1_EQUITY(self):
        self.assertEqual(mapping.cancel_payload("EQ-1", segment="EQUITY"), {"order_id": "EQ-1", "segment": "EQUITY"})

    def test_cancel_DRV_1_DERIVATIVE(self):
        self.assertEqual(
            mapping.cancel_payload("DRV-1", segment="DERIVATIVE"), {"order_id": "DRV-1", "segment": "DERIVATIVE"}
        )

    def test_cancel_x_EQUITY(self):
        self.assertEqual(mapping.cancel_payload("  x  ", segment="EQUITY"), {"order_id": "  x  ", "segment": "EQUITY"})

    def test_cancel_eq_conflict(self):
        with self.assertRaises(ValueError):
            mapping.cancel_payload("EQ-1", segment="DERIVATIVE")

    def test_modify_eq_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({}, order_id="EQ-1", segment="DERIVATIVE")

    def test_cancel_drv_conflict(self):
        with self.assertRaises(ValueError):
            mapping.cancel_payload("DRV-1", segment="EQUITY")

    def test_modify_drv_conflict(self):
        with self.assertRaises(ValueError):
            self.modify({}, order_id="DRV-1", segment="EQUITY")

    def test_cancel_blank(self):
        with self.assertRaises(ValueError):
            mapping.cancel_payload("", segment="EQUITY")

    def test_modify_blank(self):
        with self.assertRaises(ValueError):
            self.modify({}, order_id="", segment="EQUITY")

    def test_cancel_segment(self):
        with self.assertRaises(ValueError):
            mapping.cancel_payload("GTT-1", segment="NSE")

    def test_modify_segment(self):
        with self.assertRaises(ValueError):
            self.modify({}, order_id="GTT-1", segment="NSE")

    def test_modify_bad_mapping(self):
        with self.assertRaises(ValueError):
            self.modify([])

    def test_place_bad_mapping(self):
        with self.assertRaises(ValueError):
            mapping.smart_payload([], security_id="s", algo_id="a")

    def test_place_blank_security(self):
        with self.assertRaises(ValueError):
            mapping.smart_payload(self.order(), security_id=" ", algo_id="a")

    def test_place_blank_algo(self):
        with self.assertRaises(ValueError):
            mapping.smart_payload(self.order(), security_id="s", algo_id=" ")

    def test_modify_blank_algo(self):
        with self.assertRaises(ValueError):
            mapping.smart_modify("GTT-1", {}, segment="EQUITY", existing_order_type="LIMIT", algo_id=" ")

    def test_mapping_proxy_nonmutation(self):
        order = self.order()
        original = dict(order)
        self.assertEqual(
            mapping.smart_payload(MappingProxyType(order), security_id="00123", algo_id="custom-0001"), self.place()
        )
        self.assertEqual(order, original)

    def test_modify_mapping_nonmutation(self):
        changes = {"price": 100}
        self.assertEqual(
            self.modify(MappingProxyType(changes)),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "limit_price": 100},
        )
        self.assertEqual(changes, {"price": 100})

    def test_single_remaining_target_leg(self):
        order = self.order()
        del order["sl_trigger_price"]
        del order["sl_limit_price"]
        self.assertEqual(
            mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_single_remaining_stop_leg(self):
        order = self.order()
        del order["tgt_trigger_price"]
        del order["tgt_limit_price"]
        self.assertEqual(
            mapping.smart_payload(order, security_id="00123", algo_id="custom-0001"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_segment_BSE(self):
        self.assertEqual(
            self.place(exchange="BSE", product="MIS"),
            {
                "txn_type": "BUY",
                "exchange": "BSE",
                "segment": "EQUITY",
                "product": "INTRADAY",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_segment_BFO(self):
        self.assertEqual(
            self.place(exchange="BFO", product="NRML"),
            {
                "txn_type": "BUY",
                "exchange": "BSE",
                "segment": "DERIVATIVE",
                "product": "MARGIN",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_segment_NFO(self):
        self.assertEqual(
            self.place(exchange="NFO", product="MIS"),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "DERIVATIVE",
                "product": "INTRADAY",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100,
            },
        )

    def test_trigger_fallback_sl_direction(self):
        with self.assertRaises(ValueError):
            order = self.order(variety="trigger", pricetype="TRIGGER", trigger_price=80)
            del order["price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_trigger_fallback_tgt_direction(self):
        with self.assertRaises(ValueError):
            order = self.order(variety="trigger", pricetype="TRIGGER", trigger_price=120)
            del order["price"]
            mapping.smart_payload(order, security_id="s", algo_id="a")

    def test_sell_trigger_exact(self):
        self.assertEqual(
            self.place(
                action="SELL",
                variety="trigger",
                pricetype="TRIGGER",
                trigger_price=105,
                sl_trigger_price=110,
                sl_limit_price=111,
                tgt_trigger_price=90,
                tgt_limit_price=89,
            ),
            {
                "txn_type": "SELL",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 110,
                "sl_limit_price": 111,
                "tgt_trigger_price": 90,
                "tgt_limit_price": 89,
                "order_type": "TRIGGER",
                "trigger_price": 105,
                "trigger_limit_price": 100,
            },
        )

    def test_sell_market_exact(self):
        self.assertEqual(
            self.place(
                action="SELL",
                pricetype="MARKET",
                sl_trigger_price=110,
                sl_limit_price=111,
                tgt_trigger_price=90,
                tgt_limit_price=89,
            ),
            {
                "txn_type": "SELL",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 110,
                "sl_limit_price": 111,
                "tgt_trigger_price": 90,
                "tgt_limit_price": 89,
                "order_type": "MARKET",
            },
        )

    def test_trigger_zero(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=0)

    def test_trigger_missing(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER")

    def test_trigger_price_null(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=99, price=None)

    def test_trigger_native_null(self):
        with self.assertRaises(ValueError):
            self.place(variety="trigger", pricetype="TRIGGER", trigger_price=99, trigger_limit_price=None)

    def test_market_leg_order(self):
        with self.assertRaises(ValueError):
            self.place(pricetype="MARKET", sl_limit_price=91)

    def test_trailing_bool(self):
        with self.assertRaises(ValueError):
            self.place(is_tsl=1)

    def test_trailing_nan(self):
        with self.assertRaises(ValueError):
            self.place(tsl_step_size="NaN")

    def test_remarks_type(self):
        with self.assertRaises(ValueError):
            self.place(remarks=1)

    def test_modify_all_legs_exact(self):
        self.assertEqual(
            self.modify(
                {"sl_trigger_price": 90, "sl_limit_price": 89, "tgt_trigger_price": 110, "tgt_limit_price": 111}
            ),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
            },
        )

    def test_modify_derivative_gtt_exact(self):
        self.assertEqual(
            self.modify({"qty": 75}, segment="DERIVATIVE"),
            {"order_id": "GTT-123", "segment": "DERIVATIVE", "algo_id": "custom-0001", "qty": 75},
        )

    def test_modify_native_trigger_exact(self):
        self.assertEqual(
            self.modify({"trigger_price": 99, "trigger_limit_price": 100}, "TRIGGER"),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "trigger_price": 99,
                "trigger_limit_price": 100,
            },
        )

    def test_modify_matching_market_type(self):
        self.assertEqual(
            self.modify({"order_type": "MARKET"}, "MARKET"),
            {"order_id": "GTT-123", "segment": "EQUITY", "algo_id": "custom-0001", "order_type": "MARKET"},
        )

    def test_exact_decimal_prices(self):
        self.assertEqual(
            self.place(price=Decimal("100.5")),
            {
                "txn_type": "BUY",
                "exchange": "NSE",
                "segment": "EQUITY",
                "product": "CNC",
                "validity": "DAY",
                "security_id": "00123",
                "qty": 2,
                "algo_id": "custom-0001",
                "sl_trigger_price": 90,
                "sl_limit_price": 89,
                "tgt_trigger_price": 110,
                "tgt_limit_price": 111,
                "order_type": "LIMIT",
                "limit_price": 100.5,
            },
        )

    def test_inexact_decimal_price(self):
        with self.assertRaises(ValueError):
            self.place(price=Decimal("100.000000000000000001"))

    def test_modify_stop_limit_only_exact(self):
        self.assertEqual(
            self.modify({"sl_limit_price": 89}),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "sl_limit_price": 89,
            },
        )

    def test_modify_target_limit_only_exact(self):
        self.assertEqual(
            self.modify({"tgt_limit_price": 111}),
            {
                "order_id": "GTT-123",
                "segment": "EQUITY",
                "algo_id": "custom-0001",
                "tgt_limit_price": 111,
            },
        )

    def test_modify_market_zero_canonical_price_rejected(self):
        with self.assertRaises(ValueError):
            self.modify({"price": 0}, "MARKET")

    def test_modify_market_zero_native_price_rejected(self):
        with self.assertRaises(ValueError):
            self.modify({"limit_price": 0}, "MARKET")


class ReadEvidenceContracts(unittest.TestCase):
    def test_read_fields_complete(self):
        self.assertEqual(
            mapping.project_order(
                {
                    "id": "DRV-123",
                    "requested_qty": "100",
                    "traded_qty": 40,
                    "status": "PARTIALLY FILLED - CANCELLED",
                    "security_id": "005",
                    "exch_order_id": "000999",
                    "exchange": "NSE",
                    "segment": "DERIVATIVE",
                    "product": "MARGIN",
                    "requested_price": "100.5",
                    "traded_price": "100.25",
                    "trigger_price": "99",
                    "trigger_limit_price": "100",
                    "sl_trigger_price": "90",
                    "sl_limit_price": "89",
                    "tgt_trigger_price": "110",
                    "tgt_limit_price": "111",
                    "extra_info": "exchange note",
                    "remarks": "signal",
                    "created_at": "2026-10-06T10:00:00+05:30",
                    "updated_at": "2026-10-06T10:01:00+05:30",
                    "txn_type": "BUY",
                    "order_type": "TRIGGER",
                    "validity": "DAY",
                }
            ),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {
                    "id": "DRV-123",
                    "requested_qty": "100",
                    "traded_qty": 40,
                    "status": "PARTIALLY FILLED - CANCELLED",
                    "security_id": "005",
                    "exch_order_id": "000999",
                    "exchange": "NSE",
                    "segment": "DERIVATIVE",
                    "product": "MARGIN",
                    "requested_price": "100.5",
                    "traded_price": "100.25",
                    "trigger_price": "99",
                    "trigger_limit_price": "100",
                    "sl_trigger_price": "90",
                    "sl_limit_price": "89",
                    "tgt_trigger_price": "110",
                    "tgt_limit_price": "111",
                    "extra_info": "exchange note",
                    "remarks": "signal",
                    "created_at": "2026-10-06T10:00:00+05:30",
                    "updated_at": "2026-10-06T10:01:00+05:30",
                    "txn_type": "BUY",
                    "order_type": "TRIGGER",
                    "validity": "DAY",
                },
                "orderid": "DRV-123",
                "quantity": 100,
                "filled_quantity": 40,
                "exchange_order_id": "000999",
                "attempt_state": "CANCELLED",
                "status": "PARTIALLY FILLED - CANCELLED",
                "security_id": "005",
                "exchange": "NSE",
                "segment": "DERIVATIVE",
                "product": "MARGIN",
                "requested_price": 100.5,
                "traded_price": 100.25,
                "trigger_price": 99.0,
                "trigger_limit_price": 100.0,
                "sl_trigger_price": 90.0,
                "sl_limit_price": 89.0,
                "tgt_trigger_price": 110.0,
                "tgt_limit_price": 111.0,
                "extra_info": "exchange note",
                "remarks": "signal",
                "created_at": "2026-10-06T10:00:00+05:30",
                "updated_at": "2026-10-06T10:01:00+05:30",
                "txn_type": "BUY",
                "order_type": "TRIGGER",
                "validity": "DAY",
            },
        )

    def test_missing_quantity(self):
        self.assertEqual(mapping.project_order({})["quantity"], None)

    def test_missing_filled(self):
        self.assertEqual(mapping.project_order({})["filled_quantity"], None)

    def test_missing_trigger(self):
        self.assertEqual(mapping.project_order({})["trigger_price"], None)

    def test_missing_identity(self):
        self.assertEqual(mapping.project_order({})["orderid"], None)

    def test_trigger_price_blank(self):
        self.assertEqual(mapping.project_order({"trigger_price": ""})["trigger_price"], None)

    def test_trigger_price_whitespace(self):
        self.assertEqual(mapping.project_order({"trigger_price": "  "})["trigger_price"], None)

    def test_trigger_price_null(self):
        self.assertEqual(mapping.project_order({"trigger_price": None})["trigger_price"], None)

    def test_trigger_price_zero(self):
        self.assertEqual(mapping.project_order({"trigger_price": 0})["trigger_price"], 0)

    def test_trigger_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_price": "oops"})

    def test_trigger_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_price": -1})

    def test_trigger_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_price": True})

    def test_trigger_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_price": "NaN"})

    def test_requested_price_blank(self):
        self.assertEqual(mapping.project_order({"requested_price": ""})["requested_price"], None)

    def test_requested_price_whitespace(self):
        self.assertEqual(mapping.project_order({"requested_price": "  "})["requested_price"], None)

    def test_requested_price_null(self):
        self.assertEqual(mapping.project_order({"requested_price": None})["requested_price"], None)

    def test_requested_price_zero(self):
        self.assertEqual(mapping.project_order({"requested_price": 0})["requested_price"], 0)

    def test_requested_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_price": "oops"})

    def test_requested_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_price": -1})

    def test_requested_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_price": True})

    def test_requested_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_price": "NaN"})

    def test_traded_price_blank(self):
        self.assertEqual(mapping.project_order({"traded_price": ""})["traded_price"], None)

    def test_traded_price_whitespace(self):
        self.assertEqual(mapping.project_order({"traded_price": "  "})["traded_price"], None)

    def test_traded_price_null(self):
        self.assertEqual(mapping.project_order({"traded_price": None})["traded_price"], None)

    def test_traded_price_zero(self):
        self.assertEqual(mapping.project_order({"traded_price": 0})["traded_price"], 0)

    def test_traded_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_price": "oops"})

    def test_traded_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_price": -1})

    def test_traded_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_price": True})

    def test_traded_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_price": "NaN"})

    def test_sl_trigger_price_blank(self):
        self.assertEqual(mapping.project_order({"sl_trigger_price": ""})["sl_trigger_price"], None)

    def test_sl_trigger_price_whitespace(self):
        self.assertEqual(mapping.project_order({"sl_trigger_price": "  "})["sl_trigger_price"], None)

    def test_sl_trigger_price_null(self):
        self.assertEqual(mapping.project_order({"sl_trigger_price": None})["sl_trigger_price"], None)

    def test_sl_trigger_price_zero(self):
        self.assertEqual(mapping.project_order({"sl_trigger_price": 0})["sl_trigger_price"], 0)

    def test_sl_trigger_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_trigger_price": "oops"})

    def test_sl_trigger_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_trigger_price": -1})

    def test_sl_trigger_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_trigger_price": True})

    def test_sl_trigger_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_trigger_price": "NaN"})

    def test_sl_limit_price_blank(self):
        self.assertEqual(mapping.project_order({"sl_limit_price": ""})["sl_limit_price"], None)

    def test_sl_limit_price_whitespace(self):
        self.assertEqual(mapping.project_order({"sl_limit_price": "  "})["sl_limit_price"], None)

    def test_sl_limit_price_null(self):
        self.assertEqual(mapping.project_order({"sl_limit_price": None})["sl_limit_price"], None)

    def test_sl_limit_price_zero(self):
        self.assertEqual(mapping.project_order({"sl_limit_price": 0})["sl_limit_price"], 0)

    def test_sl_limit_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_limit_price": "oops"})

    def test_sl_limit_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_limit_price": -1})

    def test_sl_limit_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_limit_price": True})

    def test_sl_limit_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"sl_limit_price": "NaN"})

    def test_tgt_trigger_price_blank(self):
        self.assertEqual(mapping.project_order({"tgt_trigger_price": ""})["tgt_trigger_price"], None)

    def test_tgt_trigger_price_whitespace(self):
        self.assertEqual(mapping.project_order({"tgt_trigger_price": "  "})["tgt_trigger_price"], None)

    def test_tgt_trigger_price_null(self):
        self.assertEqual(mapping.project_order({"tgt_trigger_price": None})["tgt_trigger_price"], None)

    def test_tgt_trigger_price_zero(self):
        self.assertEqual(mapping.project_order({"tgt_trigger_price": 0})["tgt_trigger_price"], 0)

    def test_tgt_trigger_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_trigger_price": "oops"})

    def test_tgt_trigger_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_trigger_price": -1})

    def test_tgt_trigger_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_trigger_price": True})

    def test_tgt_trigger_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_trigger_price": "NaN"})

    def test_tgt_limit_price_blank(self):
        self.assertEqual(mapping.project_order({"tgt_limit_price": ""})["tgt_limit_price"], None)

    def test_tgt_limit_price_whitespace(self):
        self.assertEqual(mapping.project_order({"tgt_limit_price": "  "})["tgt_limit_price"], None)

    def test_tgt_limit_price_null(self):
        self.assertEqual(mapping.project_order({"tgt_limit_price": None})["tgt_limit_price"], None)

    def test_tgt_limit_price_zero(self):
        self.assertEqual(mapping.project_order({"tgt_limit_price": 0})["tgt_limit_price"], 0)

    def test_tgt_limit_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_limit_price": "oops"})

    def test_tgt_limit_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_limit_price": -1})

    def test_tgt_limit_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_limit_price": True})

    def test_tgt_limit_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"tgt_limit_price": "NaN"})

    def test_trigger_limit_price_blank(self):
        self.assertEqual(mapping.project_order({"trigger_limit_price": ""})["trigger_limit_price"], None)

    def test_trigger_limit_price_whitespace(self):
        self.assertEqual(mapping.project_order({"trigger_limit_price": "  "})["trigger_limit_price"], None)

    def test_trigger_limit_price_null(self):
        self.assertEqual(mapping.project_order({"trigger_limit_price": None})["trigger_limit_price"], None)

    def test_trigger_limit_price_zero(self):
        self.assertEqual(mapping.project_order({"trigger_limit_price": 0})["trigger_limit_price"], 0)

    def test_trigger_limit_price_bad(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_limit_price": "oops"})

    def test_trigger_limit_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_limit_price": -1})

    def test_trigger_limit_price_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_limit_price": True})

    def test_trigger_limit_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"trigger_limit_price": "NaN"})

    def test_id_blank(self):
        self.assertEqual(mapping.project_order({"id": ""})["orderid"], None)

    def test_id_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"id": 123})

    def test_exch_order_id_blank(self):
        self.assertEqual(mapping.project_order({"exch_order_id": ""})["exchange_order_id"], None)

    def test_exch_order_id_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"exch_order_id": 123})

    def test_security_id_blank(self):
        self.assertEqual(mapping.project_order({"security_id": ""})["security_id"], None)

    def test_security_id_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"security_id": 123})

    def test_requested_qty_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": ""})

    def test_requested_qty_null(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": None})

    def test_requested_qty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": True})

    def test_requested_qty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": 1.5})

    def test_requested_qty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": -1})

    def test_requested_qty_nan(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": "NaN"})

    def test_requested_qty_zero(self):
        self.assertEqual(mapping.project_order({"requested_qty": 0})["quantity"], 0)

    def test_traded_qty_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": ""})

    def test_traded_qty_null(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": None})

    def test_traded_qty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": True})

    def test_traded_qty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": 1.5})

    def test_traded_qty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": -1})

    def test_traded_qty_nan(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": "NaN"})

    def test_traded_qty_zero(self):
        self.assertEqual(mapping.project_order({"traded_qty": 0})["filled_quantity"], 0)

    def test_filled_above_total(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": 10, "traded_qty": 11})

    def test_filled_without_total(self):
        self.assertEqual(mapping.project_order({"traded_qty": 4})["filled_quantity"], 4)

    def test_parent_trigger_never_derived(self):
        self.assertEqual(
            mapping.project_order(
                {"sl_trigger_price": 90, "tgt_trigger_price": 110, "requested_price": 100, "traded_price": 101}
            )["trigger_price"],
            None,
        )

    def test_conflicting_orderid(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"id": "EQ-1", "orderid": "EQ-2"})

    def test_conflicting_order_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"id": "EQ-1", "order_id": "EQ-2"})

    def test_conflicting_quantity(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": 1, "quantity": 2})

    def test_conflicting_filled_quantity(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"traded_qty": 1, "filled_quantity": 2})

    def test_conflicting_exchange_order_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"exch_order_id": "EQ-1", "exchange_order_id": "E-2"})

    def test_conflicting_order_status(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"status": "INITIATED", "order_status": "SUCCESS"})

    def test_equivalent_quantity_alias(self):
        self.assertEqual(mapping.project_order({"requested_qty": "4", "quantity": 4})["quantity"], 4)

    def test_equivalent_identity_alias(self):
        self.assertEqual(mapping.project_order({"id": "EQ-1", "order_id": "EQ-1"})["orderid"], "EQ-1")

    def test_blank_quantity_alias_not_ignored(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_qty": 4, "quantity": ""})

    def test_order_not_mapping(self):
        with self.assertRaises(ValueError):
            mapping.project_order([])

    def test_mapping_and_raw_copy(self):
        row = MappingProxyType({"id": "EQ-1", "future": {"x": 1}})
        result = mapping.project_order(row)
        self.assertEqual(result["raw"], dict(row))
        self.assertIsNot(result["raw"], row)

    def test_exact_state_0(self):
        self.assertEqual(mapping.attempt_state("SUCCESS"), "FILLED")

    def test_exact_state_1(self):
        self.assertEqual(mapping.attempt_state("CANCELLED"), "CANCELLED")

    def test_exact_state_2(self):
        self.assertEqual(mapping.attempt_state("PARTIALLY FILLED - CANCELLED"), "CANCELLED")

    def test_exact_state_3(self):
        self.assertEqual(mapping.attempt_state("EXPIRED"), "EXPIRED")

    def test_exact_state_4(self):
        self.assertEqual(mapping.attempt_state("PARTIALLY FILLED - EXPIRED"), "EXPIRED")

    def test_exact_state_5(self):
        self.assertEqual(mapping.attempt_state("PARTIALLY FILLED"), "PARTIALLY_FILLED")

    def test_exact_state_6(self):
        self.assertEqual(mapping.attempt_state("INITIATED"), "ACKNOWLEDGED")

    def test_exact_state_7(self):
        self.assertEqual(mapping.attempt_state("QUEUED"), "SUBMITTING")

    def test_exact_state_8(self):
        self.assertEqual(mapping.attempt_state("PROCESSING"), "SUBMITTING")

    def test_exact_state_9(self):
        self.assertEqual(mapping.attempt_state("O-PENDING"), "WORKING")

    def test_exact_state_10(self):
        self.assertEqual(mapping.attempt_state("SL-PENDING"), "WORKING")

    def test_exact_state_11(self):
        self.assertEqual(mapping.attempt_state("PENDING"), "WORKING")

    def test_exact_state_12(self):
        self.assertEqual(mapping.attempt_state("MODIFIED"), "WORKING")

    def test_exact_state_13(self):
        self.assertEqual(mapping.attempt_state("CANCEL_PENDING"), "CANCEL_PENDING")

    def test_exact_state_14(self):
        self.assertEqual(mapping.attempt_state("CANCEL_REQUESTED"), "CANCEL_PENDING")

    def test_exact_state_15(self):
        self.assertEqual(mapping.attempt_state("CANCEL PENDING"), "CANCEL_PENDING")

    def test_exact_state_16(self):
        self.assertEqual(mapping.attempt_state("CANCEL REQUESTED"), "CANCEL_PENDING")

    def test_unknown_state_0(self):
        self.assertEqual(mapping.attempt_state("FAILED"), "UNKNOWN")

    def test_unknown_state_1(self):
        self.assertEqual(mapping.attempt_state("ABORTED"), "UNKNOWN")

    def test_unknown_state_2(self):
        self.assertEqual(mapping.attempt_state(""), "UNKNOWN")

    def test_unknown_state_3(self):
        self.assertEqual(mapping.attempt_state("CREATED"), "UNKNOWN")

    def test_unknown_state_4(self):
        self.assertEqual(mapping.attempt_state("PF"), "UNKNOWN")

    def test_unknown_state_5(self):
        self.assertEqual(mapping.attempt_state("PFC"), "UNKNOWN")

    def test_unknown_state_6(self):
        self.assertEqual(mapping.attempt_state("NOT CANCELLED"), "UNKNOWN")

    def test_unknown_state_7(self):
        self.assertEqual(mapping.attempt_state("SUCCESS_PENDING"), "UNKNOWN")

    def test_unknown_state_8(self):
        self.assertEqual(mapping.attempt_state("REJECTED_LATER"), "UNKNOWN")

    def test_unknown_state_9(self):
        self.assertEqual(mapping.attempt_state("COMPLETE"), "UNKNOWN")

    def test_unknown_state_10(self):
        self.assertEqual(mapping.attempt_state("success"), "UNKNOWN")

    def test_unknown_state_11(self):
        self.assertEqual(mapping.attempt_state(" SUCCESS "), "UNKNOWN")

    def test_unknown_state_12(self):
        self.assertEqual(mapping.attempt_state(None), "UNKNOWN")

    def test_unknown_state_13(self):
        self.assertEqual(mapping.attempt_state(True), "UNKNOWN")

    def test_unknown_state_14(self):
        self.assertEqual(mapping.attempt_state(123), "UNKNOWN")

    def test_unknown_state_15(self):
        self.assertEqual(mapping.attempt_state([]), "UNKNOWN")

    def test_unknown_state_16(self):
        self.assertEqual(mapping.attempt_state({}), "UNKNOWN")

    def test_gtt_success(self):
        self.assertEqual(mapping.project_order({"id": "GTT-1", "status": "SUCCESS"})["attempt_state"], "UNKNOWN")

    def test_gtt_cancelled(self):
        self.assertEqual(mapping.project_order({"id": "GTT-1", "status": "CANCELLED"})["attempt_state"], "UNKNOWN")

    def test_gtt_expired(self):
        self.assertEqual(mapping.project_order({"id": "GTT-1", "status": "EXPIRED"})["attempt_state"], "UNKNOWN")

    def test_oco_resource_unknown(self):
        self.assertEqual(mapping.project_order({"order_type": "OCO", "status": "SUCCESS"})["attempt_state"], "UNKNOWN")

    def test_fill_complete_no_order(self):
        self.assertEqual(
            mapping.project_fill(
                {
                    "fill_id": 1279916,
                    "exch_order_id": "00099",
                    "quantity": 65,
                    "price": 77.8,
                    "trade_date": "2026-07-20T09:31:20+05:30",
                    "trade_serial_no": "000002",
                    "scrip_code": "009",
                    "remarks": "tag",
                }
            ),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {
                    "fill_id": 1279916,
                    "exch_order_id": "00099",
                    "quantity": 65,
                    "price": 77.8,
                    "trade_date": "2026-07-20T09:31:20+05:30",
                    "trade_serial_no": "000002",
                    "scrip_code": "009",
                    "remarks": "tag",
                },
                "order_id": None,
                "fill_id": 1279916,
                "exch_order_id": "00099",
                "quantity": 65,
                "price": 77.8,
                "trade_date": "2026-07-20T09:31:20+05:30",
                "trade_serial_no": "000002",
                "scrip_code": "009",
                "remarks": "tag",
            },
        )

    def test_fill_explicit_order(self):
        self.assertEqual(
            mapping.project_fill(
                {
                    "fill_id": 1279916,
                    "exch_order_id": "00099",
                    "quantity": 65,
                    "price": 77.8,
                    "trade_date": "2026-07-20T09:31:20+05:30",
                    "trade_serial_no": "000002",
                    "scrip_code": "009",
                    "remarks": "tag",
                },
                order_id="DRV-1",
            )["order_id"],
            "DRV-1",
        )

    def test_fill_row_order(self):
        self.assertEqual(mapping.project_fill({"order_id": "EQ-1"})["order_id"], "EQ-1")

    def test_fill_order_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"order_id": "EQ-1"}, order_id="EQ-2")

    def test_fill_explicit_blank_order(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({}, order_id="")

    def test_fill_invalid_quantity_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"quantity": -1})

    def test_fill_invalid_quantity_fractional(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"quantity": 1.2})

    def test_fill_invalid_quantity_boolean(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"quantity": True})

    def test_fill_invalid_quantity_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"quantity": ""})

    def test_fill_invalid_price_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"price": "NaN"})

    def test_fill_invalid_price_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"price": -1})

    def test_fill_invalid_fill_id_boolean(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"fill_id": True})

    def test_fill_invalid_fill_id_fractional(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"fill_id": 1.5})

    def test_fill_invalid_fill_id_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"fill_id": -1})

    def test_fill_invalid_exchange_id_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"exch_order_id": 123})

    def test_fill_invalid_serial_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"trade_serial_no": 123})

    def test_fill_invalid_scrip_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"scrip_code": 123})

    def test_fill_invalid_date_numeric(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"trade_date": 123})

    def test_fill_zero_evidence(self):
        self.assertEqual(
            mapping.project_fill({"quantity": 0, "price": 0, "fill_id": 0}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"quantity": 0, "price": 0, "fill_id": 0},
                "order_id": None,
                "fill_id": 0,
                "quantity": 0,
                "price": 0,
                "exch_order_id": None,
                "trade_date": None,
                "trade_serial_no": None,
                "scrip_code": None,
                "remarks": None,
            },
        )

    def test_fill_missing_quantity(self):
        self.assertEqual(mapping.project_fill({})["quantity"], None)

    def test_fill_blank_exchange(self):
        self.assertEqual(mapping.project_fill({"exch_order_id": ""})["exch_order_id"], None)

    def test_fill_not_mapping(self):
        with self.assertRaises(ValueError):
            mapping.project_fill([])

    def test_fills_remain_independent(self):
        a = mapping.project_fill({"fill_id": 1, "exch_order_id": "E", "quantity": 2})
        b = mapping.project_fill({"fill_id": 2, "exch_order_id": "E", "quantity": 3})
        self.assertNotEqual(a["fill_id"], b["fill_id"])
        self.assertIsNone(a["order_id"])
        self.assertIsNone(b["order_id"])

    def test_linked_results_all_items(self):
        self.assertEqual(
            mapping.smart_results(
                {
                    "status": "success",
                    "data": {
                        "order_data": [
                            {
                                "order_id": "DRV-1",
                                "order_status": "CREATED",
                                "child_order_details": {"order_id": "GTT-2", "order_status": "CREATED"},
                            },
                            {"order_id": "GTT-3", "order_status": "SUCCESS", "error": {"message": "partial"}},
                            {"error": "refused"},
                        ]
                    },
                }
            ),
            [
                {
                    "schema_id": "indstocks-public-rest-2026-10-06",
                    "raw": {
                        "order_id": "DRV-1",
                        "order_status": "CREATED",
                        "child_order_details": {"order_id": "GTT-2", "order_status": "CREATED"},
                    },
                    "parent_order_id": "DRV-1",
                    "parent_status": "CREATED",
                    "child_order_id": "GTT-2",
                    "child_status": "CREATED",
                    "error": None,
                },
                {
                    "schema_id": "indstocks-public-rest-2026-10-06",
                    "raw": {"order_id": "GTT-3", "order_status": "SUCCESS", "error": {"message": "partial"}},
                    "parent_order_id": "GTT-3",
                    "parent_status": "SUCCESS",
                    "child_order_id": None,
                    "child_status": None,
                    "error": {"message": "partial"},
                },
                {
                    "schema_id": "indstocks-public-rest-2026-10-06",
                    "raw": {"error": "refused"},
                    "parent_order_id": None,
                    "parent_status": None,
                    "child_order_id": None,
                    "child_status": None,
                    "error": "refused",
                },
            ],
        )

    def test_linked_results_empty(self):
        self.assertEqual(mapping.smart_results({"data": {"order_data": []}}), [])

    def test_malformed_smart_0(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({})

    def test_malformed_smart_1(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": None})

    def test_malformed_smart_2(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {}})

    def test_malformed_smart_3(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": None}})

    def test_malformed_smart_4(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": {}}})

    def test_malformed_smart_5(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [None]}})

    def test_malformed_smart_6(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{}]}})

    def test_malformed_smart_7(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"order_id": "EQ-1", "child_order_details": []}]}})

    def test_malformed_smart_8(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"order_id": 123}]}})

    def test_malformed_smart_9(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"order_id": "EQ-1", "order_status": False}]}})

    def test_smart_absent_child(self):
        self.assertEqual(
            mapping.smart_results({"data": {"order_data": [{"order_id": "EQ-1", "child_order_details": None}]}})[0][
                "child_order_id"
            ],
            None,
        )

    def test_error_TokenException_403(self):
        self.assertEqual(
            mapping.project_error(403, {"error_type": "TokenException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "TokenException", "message": "detail"},
                "http_status": 403,
                "broker_code": "TokenException",
                "reason": "detail",
                "category": "SESSION_EXPIRED",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_RequestValidationException_400(self):
        self.assertEqual(
            mapping.project_error(400, {"error_type": "RequestValidationException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "RequestValidationException", "message": "detail"},
                "http_status": 400,
                "broker_code": "RequestValidationException",
                "reason": "detail",
                "category": "VALIDATION",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_GatewayTimeoutException_504(self):
        self.assertEqual(
            mapping.project_error(504, {"error_type": "GatewayTimeoutException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "GatewayTimeoutException", "message": "detail"},
                "http_status": 504,
                "broker_code": "GatewayTimeoutException",
                "reason": "detail",
                "category": "TIMEOUT",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_NetworkException_503(self):
        self.assertEqual(
            mapping.project_error(503, {"error_type": "NetworkException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "NetworkException", "message": "detail"},
                "http_status": 503,
                "broker_code": "NetworkException",
                "reason": "detail",
                "category": "UNKNOWN",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_TokenException_429(self):
        self.assertEqual(
            mapping.project_error(429, {"error_type": "TokenException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "TokenException", "message": "detail"},
                "http_status": 429,
                "broker_code": "TokenException",
                "reason": "detail",
                "category": "RATE_LIMIT",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_OrderException_400(self):
        self.assertEqual(
            mapping.project_error(400, {"error_type": "OrderException", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "OrderException", "message": "detail"},
                "http_status": 400,
                "broker_code": "OrderException",
                "reason": "detail",
                "category": "UNKNOWN",
                "execution_state": "UNKNOWN",
            },
        )

    def test_error_tokenexception_403(self):
        self.assertEqual(
            mapping.project_error(403, {"error_type": "tokenexception", "message": "detail"}),
            {
                "schema_id": "indstocks-public-rest-2026-10-06",
                "raw": {"error_type": "tokenexception", "message": "detail"},
                "http_status": 403,
                "broker_code": "tokenexception",
                "reason": "detail",
                "category": "UNKNOWN",
                "execution_state": "UNKNOWN",
            },
        )

    def test_bare_429(self):
        self.assertEqual(mapping.project_error(429, {})["category"], "RATE_LIMIT")

    def test_bare_504_unknown(self):
        self.assertEqual(mapping.project_error(504, {})["category"], "UNKNOWN")

    def test_error_debug_detail(self):
        self.assertEqual(
            mapping.project_error(400, {"message": "Bad Request", "debug_info": "specific"})["reason"], "specific"
        )

    def test_error_alternate_shape(self):
        self.assertEqual(
            mapping.project_error(429, {"error": "Rate limit exceeded", "success": False})["reason"],
            "Rate limit exceeded",
        )

    def test_ack_not_execution(self):
        self.assertEqual(
            mapping.project_error(200, {"status": "success", "data": {"order_id": "EQ-1"}})["execution_state"],
            "UNKNOWN",
        )

    def test_invalid_http_0(self):
        with self.assertRaises(ValueError):
            mapping.project_error(True, {})

    def test_invalid_http_1(self):
        with self.assertRaises(ValueError):
            mapping.project_error("400", {})

    def test_invalid_http_2(self):
        with self.assertRaises(ValueError):
            mapping.project_error(99, {})

    def test_invalid_http_3(self):
        with self.assertRaises(ValueError):
            mapping.project_error(600, {})

    def test_invalid_http_4(self):
        with self.assertRaises(ValueError):
            mapping.project_error(None, {})

    def test_error_payload_not_mapping(self):
        with self.assertRaises(ValueError):
            mapping.project_error(500, [])

    def test_error_code_malformed(self):
        with self.assertRaises(ValueError):
            mapping.project_error(400, {"error_type": []})


class ReadEvidenceEdgeContracts(unittest.TestCase):
    def test_pending_alias_0(self):
        self.assertEqual(mapping.attempt_state("CANCEL-PENDING"), "CANCEL_PENDING")

    def test_pending_alias_1(self):
        self.assertEqual(mapping.attempt_state("CANCEL-REQUESTED"), "CANCEL_PENDING")

    def test_pending_alias_2(self):
        self.assertEqual(mapping.attempt_state("CANCELLATION_PENDING"), "CANCEL_PENDING")

    def test_pending_alias_3(self):
        self.assertEqual(mapping.attempt_state("CANCELLATION_REQUESTED"), "CANCEL_PENDING")

    def test_pending_alias_4(self):
        self.assertEqual(mapping.attempt_state("CANCELLATION PENDING"), "CANCEL_PENDING")

    def test_pending_alias_5(self):
        self.assertEqual(mapping.attempt_state("CANCELLATION REQUESTED"), "CANCEL_PENDING")

    def test_fill_id_blank(self):
        self.assertEqual(mapping.project_fill({"fill_id": ""})["fill_id"], None)

    def test_fill_id_null(self):
        self.assertEqual(mapping.project_fill({"fill_id": None})["fill_id"], None)

    def test_fill_id_whitespace(self):
        self.assertEqual(mapping.project_fill({"fill_id": " "})["fill_id"], None)

    def test_fill_string_id_integral(self):
        self.assertEqual(mapping.project_fill({"fill_id": "00012"})["fill_id"], 12)

    def test_read_gtt_type_without_identity(self):
        self.assertEqual(
            mapping.project_order({"order_type": "GTT", "status": "CANCELLED"})["attempt_state"], "UNKNOWN"
        )

    def test_read_blank_status_preserved(self):
        self.assertEqual(mapping.project_order({"status": ""})["status"], "")

    def test_read_status_alias(self):
        self.assertEqual(mapping.project_order({"order_status": "INITIATED"})["status"], "INITIATED")

    def test_read_unknown_field_retained(self):
        self.assertEqual(mapping.project_order({"future_flag": True})["raw"], {"future_flag": True})

    def test_read_remarks_not_placement_validation(self):
        self.assertEqual(mapping.project_order({"remarks": " TV-TERMINAL "})["remarks"], " TV-TERMINAL ")

    def test_read_empty_extra_info(self):
        self.assertEqual(mapping.project_order({"extra_info": ""})["extra_info"], "")

    def test_read_partial_expiry_preserves_fill(self):
        self.assertEqual(
            mapping.project_order({"requested_qty": 100, "traded_qty": 40, "status": "PARTIALLY FILLED - EXPIRED"})[
                "filled_quantity"
            ],
            40,
        )

    def test_read_fill_total_equal(self):
        self.assertEqual(mapping.project_order({"requested_qty": 40, "traded_qty": 40})["filled_quantity"], 40)

    def test_read_decimal_price(self):
        self.assertEqual(mapping.project_order({"requested_price": Decimal("0.125")})["requested_price"], 0.125)

    def test_read_lossy_price(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"requested_price": Decimal("0.123456789123456789")})

    def test_read_bad_security_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"security_id": {}})

    def test_read_bad_exchange(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"exchange": {}})

    def test_read_bad_segment(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"segment": {}})

    def test_read_bad_product(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"product": {}})

    def test_read_bad_txn_type(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"txn_type": {}})

    def test_read_bad_order_type(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"order_type": {}})

    def test_read_bad_validity(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"validity": {}})

    def test_read_bad_created_at(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"created_at": {}})

    def test_read_bad_updated_at(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"updated_at": {}})

    def test_read_bad_remarks(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"remarks": {}})

    def test_read_bad_extra_info(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"extra_info": {}})

    def test_read_bad_status(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"status": {}})

    def test_read_blank_identity_conflicts(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"id": "EQ-1", "orderid": ""})

    def test_read_blank_status_conflicts(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"status": "", "order_status": "SUCCESS"})

    def test_fill_price_blank(self):
        self.assertEqual(mapping.project_fill({"price": ""})["price"], None)

    def test_fill_price_null(self):
        self.assertEqual(mapping.project_fill({"price": None})["price"], None)

    def test_fill_quantity_numeric_string(self):
        self.assertEqual(mapping.project_fill({"quantity": "12"})["quantity"], 12)

    def test_fill_quantity_null(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"quantity": None})

    def test_fill_exchange_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"exch_order_id": "E-1", "exchange_order_id": "E-2"})

    def test_fill_bad_remarks(self):
        with self.assertRaises(ValueError):
            mapping.project_fill({"remarks": {}})

    def test_fill_blank_row_order_not_exchange(self):
        self.assertEqual(mapping.project_fill({"order_id": "", "exch_order_id": "123"})["order_id"], None)

    def test_fill_unknown_field_retained(self):
        self.assertEqual(mapping.project_fill({"future": "value"})["raw"], {"future": "value"})

    def test_smart_two_same_parent_items_preserved(self):
        items = [{"order_id": "EQ-1"}, {"order_id": "EQ-1"}]
        result = mapping.smart_results({"data": {"order_data": items}})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], result[1])

    def test_smart_child_status_never_inferred(self):
        self.assertEqual(
            mapping.smart_results(
                {
                    "data": {
                        "order_data": [
                            {
                                "order_id": "GTT-1",
                                "order_status": "SUCCESS",
                                "child_order_details": {"order_id": "EQ-2"},
                            }
                        ]
                    }
                }
            )[0]["child_status"],
            None,
        )

    def test_smart_child_only_error_preserved(self):
        self.assertEqual(
            mapping.smart_results(
                {"data": {"order_data": [{"order_id": "EQ-1", "child_order_details": {"error": "failed"}}]}}
            )[0]["raw"]["child_order_details"],
            {"error": "failed"},
        )

    def test_smart_parent_alias_conflict(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"order_id": "EQ-1", "parent_order_id": "EQ-2"}]}})

    def test_smart_child_alias_conflict(self):
        with self.assertRaises(ValueError):
            mapping.smart_results(
                {
                    "data": {
                        "order_data": [
                            {
                                "order_id": "EQ-1",
                                "child_order_details": {"order_id": "GTT-1", "child_order_id": "GTT-2"},
                            }
                        ]
                    }
                }
            )

    def test_smart_child_bad_status(self):
        with self.assertRaises(ValueError):
            mapping.smart_results(
                {"data": {"order_data": [{"order_id": "EQ-1", "child_order_details": {"order_status": False}}]}}
            )

    def test_smart_bad_error(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"error": False}]}})

    def test_smart_late_malformed_item_not_dropped(self):
        with self.assertRaises(ValueError):
            mapping.smart_results({"data": {"order_data": [{"order_id": "EQ-1"}, None]}})

    def test_smart_mapping_input(self):
        self.assertEqual(mapping.smart_results(MappingProxyType({"data": {"order_data": []}})), [])

    def test_error_blank_message_uses_error(self):
        self.assertEqual(mapping.project_error(500, {"message": "", "error": "detail"})["reason"], "detail")

    def test_error_missing_reason(self):
        self.assertEqual(mapping.project_error(500, {})["reason"], None)

    def test_error_unknown_substring(self):
        self.assertEqual(mapping.project_error(403, {"error_type": "NotTokenException"})["category"], "UNKNOWN")

    def test_error_http_does_not_assert_session(self):
        self.assertEqual(mapping.project_error(403, {})["category"], "UNKNOWN")

    def test_error_bad_message(self):
        with self.assertRaises(ValueError):
            mapping.project_error(400, {"message": []})

    def test_error_bad_debug_info(self):
        with self.assertRaises(ValueError):
            mapping.project_error(400, {"debug_info": []})

    def test_error_bad_error(self):
        with self.assertRaises(ValueError):
            mapping.project_error(400, {"error": []})

    def test_error_raw_copy(self):
        payload = MappingProxyType({"error_type": "TokenException", "future": 1})
        result = mapping.project_error(403, payload)
        self.assertEqual(result["raw"], dict(payload))
        self.assertIsNot(result["raw"], payload)
