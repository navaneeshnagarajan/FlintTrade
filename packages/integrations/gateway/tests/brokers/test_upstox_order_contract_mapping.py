"""Independent native placement intent tests, without runtime dependencies."""

import unittest
from collections import UserDict
from copy import deepcopy
from decimal import Decimal

import pytest

from flinttrade_gateway.brokers import upstox_order_mapping as mapping


def order(**changes):
    fields = {
        "quantity": 10,
        "product": "D",
        "validity": "DAY",
        "price": 0,
        "instrument_token": "NSE_EQ|INE123A01016",
        "order_type": "MARKET",
        "transaction_type": "BUY",
        "disclosed_quantity": 0,
        "trigger_price": 0,
    }
    fields.update(changes)
    return fields


class PlacementContracts(unittest.TestCase):
    def test_v3_native_fields(self):
        fields = order(tag="entry", is_amo=False, slice=True, market_protection=-1)
        self.assertEqual(mapping.v3_order_payload(fields), fields)

    def test_v3_omitted_optional_fields_stay_absent(self):
        self.assertEqual(mapping.v3_order_payload(order()), order())

    def test_v3_requires_every_core_field(self):
        for key in order():
            fields = order()
            del fields[key]
            with self.assertRaises(ValueError, msg=key):
                mapping.v3_order_payload(fields)

    def test_v3_rejects_unknown_fields(self):
        for key in ("correlation_id", "reduce_only", "marketProtection", "unexpected"):
            with self.assertRaises(ValueError, msg=key):
                mapping.v3_order_payload(order(**{key: "x"}))

    def test_v3_preserves_native_enums(self):
        for field, values in {
            "product": ("I", "D", "MTF"), "validity": ("DAY", "IOC"),
            "order_type": ("MARKET", "LIMIT", "SL", "SL-M"), "transaction_type": ("BUY", "SELL"),
        }.items():
            for value in values:
                self.assertEqual(mapping.v3_order_payload(order(**{field: value}))[field], value)

    def test_v3_rejects_invalid_enums(self):
        for field in ("product", "validity", "order_type", "transaction_type"):
            for value in ("", "unknown", "market", None, True, [], {}):
                with self.assertRaises(ValueError, msg=f"{field}: {value!r}"):
                    mapping.v3_order_payload(order(**{field: value}))

    def test_v3_requires_nonempty_instrument_identifier(self):
        for value in ("", " \t", None, 123, True, [], {}):
            with self.assertRaises(ValueError):
                mapping.v3_order_payload(order(instrument_token=value))

    def test_v3_rejects_nonmapping_fields(self):
        for value in (None, [], (), "x", 1):
            with self.assertRaises(ValueError):
                mapping.v3_order_payload(value)

    def test_v3_accepts_mapping_without_mutating(self):
        fields = UserDict(order(quantity="0010", tag="entry"))
        before = deepcopy(fields)
        result = mapping.v3_order_payload(fields)
        self.assertIs(type(result), dict)
        self.assertEqual(fields, before)
        result["tag"] = "changed"
        self.assertEqual(fields, before)

    def test_v3_rejected_input_unchanged(self):
        fields = order(quantity="0010", slice="false")
        before = deepcopy(fields)
        with self.assertRaises(ValueError):
            mapping.v3_order_payload(fields)
        self.assertEqual(fields, before)

    def test_exact_numeric_intent(self):
        for value in (1, "0001", 9007199254740993, "9007199254740993"):
            result = mapping.v3_order_payload(order(quantity=value))
            self.assertIs(type(result["quantity"]), int)
            self.assertEqual(result["quantity"], int(value))

    def test_quantity_rejects_nonexact_and_nonpositive_values(self):
        for value in (0, -1, "0", "-1", True, False, 1.0, 1.2, "1.0", "1e2", "+1", " 1", "1 ",
                      "١", "１", "", None, [], {}, Decimal("1"), float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(value)):
                mapping.v3_order_payload(order(quantity=value))

    def test_disclosed_quantity_accepts_exact_nonnegative_values(self):
        for value in (0, "000", 1, "01", 9007199254740993, "9007199254740993"):
            result = mapping.v3_order_payload(order(disclosed_quantity=value))
            self.assertIs(type(result["disclosed_quantity"]), int)
            self.assertEqual(result["disclosed_quantity"], int(value))

    def test_disclosed_quantity_rejects_nonexact_and_negative_values(self):
        for value in (-1, "-1", True, False, 0.0, 1.2, "1.0", "1e2", "+1", " 1", "1 ",
                      "١", "１", "", None, [], {}, Decimal("1"), float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(value)):
                mapping.v3_order_payload(order(disclosed_quantity=value))

    def test_prices_preserve_finite_builtin_numbers(self):
        for field in ("price", "trigger_price"):
            for value in (0, 0.0, -1, 1.25, 10**400):
                result = mapping.v3_order_payload(order(**{field: value}))
                self.assertEqual(result[field], value)
                self.assertIs(type(result[field]), type(value))

    def test_prices_reject_invalid_or_nonfinite_values(self):
        for field in ("price", "trigger_price"):
            for value in (True, False, "1", "", None, [], {}, Decimal("1"),
                          float("nan"), float("inf"), float("-inf")):
                with self.assertRaises(ValueError, msg=f"{field}: {value!r}"):
                    mapping.v3_order_payload(order(**{field: value}))

    def test_flags_preserve_actual_booleans(self):
        for field in ("slice", "is_amo"):
            for value in (False, True):
                self.assertIs(mapping.v3_order_payload(order(**{field: value}))[field], value)

    def test_flags_reject_coercion(self):
        for field in ("slice", "is_amo"):
            for value in (0, 1, "true", "false", None, [], {}):
                with self.assertRaises(ValueError):
                    mapping.v3_order_payload(order(**{field: value}))

    def test_market_protection(self):
        for value in (-1, 0, *range(1, 26)):
            self.assertEqual(mapping.v3_order_payload(order(market_protection=value))["market_protection"], value)

    def test_market_protection_rejects_invalid_values(self):
        for value in (-2, 26, True, False, -1.0, 0.0, 1.0, 1.5, "-1", "0", "1", None,
                      [], {}, Decimal("1"), float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(value)):
                mapping.v3_order_payload(order(market_protection=value))

    def test_market_protection_does_not_convert_order_types(self):
        for kind in ("MARKET", "LIMIT", "SL", "SL-M"):
            fields = order(order_type=kind, market_protection=0)
            self.assertEqual(mapping.v3_order_payload(fields), fields)

    def test_tag_preserves_empty_and_maximum_strings(self):
        for tag in ("", "x" * 40):
            self.assertEqual(mapping.v3_order_payload(order(tag=tag))["tag"], tag)

    def test_tag_rejects_nonstring_and_excess_length(self):
        for tag in (None, 1, True, [], {}, "x" * 41):
            with self.assertRaises(ValueError):
                mapping.v3_order_payload(order(tag=tag))

    def test_multi_request_identity(self):
        items = [order(correlation_id="sell", transaction_type="SELL", slice=True, is_amo=False, market_protection=0),
                 order(correlation_id="buy", slice=False, is_amo=True, market_protection=-1)]
        self.assertEqual(mapping.multi_order_payloads(items), items)

    def test_multi_accepts_one_and_ten_lines(self):
        for size in (1, 10):
            items = [order(correlation_id=str(index)) for index in range(size)]
            self.assertEqual(mapping.multi_order_payloads(items), items)

    def test_multi_rejects_empty_and_eleven_lines(self):
        for size in (0, 11):
            with self.assertRaises(ValueError):
                mapping.multi_order_payloads([order(correlation_id=str(index)) for index in range(size)])

    def test_multi_requires_correlation(self):
        with self.assertRaises(ValueError):
            mapping.multi_order_payloads([order()])

    def test_multi_rejects_duplicate_correlations(self):
        with self.assertRaises(ValueError):
            mapping.multi_order_payloads([order(correlation_id="same"), order(correlation_id="same")])

    def test_multi_rejects_invalid_correlations(self):
        for value in ("", " \t", "x" * 21, None, 1, True, [], {}):
            with self.assertRaises(ValueError):
                mapping.multi_order_payloads([order(correlation_id=value)])

    def test_multi_preserves_maximum_correlation_and_does_not_deduplicate_tags(self):
        items = [order(correlation_id="x" * 20, tag="same"), order(correlation_id="X" * 20, tag="same")]
        self.assertEqual(mapping.multi_order_payloads(items), items)

    def test_multi_validates_native_fields(self):
        for changes in ({"quantity": True}, {"price": "1"}, {"slice": 1}, {"market_protection": 26},
                        {"is_amo": "true"}, {"product": "CNC"}, {"tag": "x" * 41}, {"extra": 1}):
            with self.assertRaises(ValueError):
                mapping.multi_order_payloads([order(correlation_id="line", **changes)])

    def test_multi_requires_core_fields(self):
        for key in order():
            fields = order(correlation_id="line")
            del fields[key]
            with self.assertRaises(ValueError):
                mapping.multi_order_payloads([fields])

    def test_multi_rejects_malformed_container_or_items(self):
        for value in (None, {}, "x", b"x", 1, iter(()), [None], [[]], ["x"]):
            with self.assertRaises(ValueError):
                mapping.multi_order_payloads(value)

    def test_multi_copies_tuple_and_mapping_items(self):
        items = (UserDict(order(correlation_id="line", quantity="0010")),)
        before = deepcopy(items)
        result = mapping.multi_order_payloads(items)
        self.assertIs(type(result), list)
        self.assertIs(type(result[0]), dict)
        self.assertEqual(result[0]["quantity"], 10)
        result[0]["correlation_id"] = "changed"
        self.assertEqual(items, before)

    def test_multi_failed_later_item_does_not_mutate_earlier_items(self):
        items = [order(correlation_id="one", quantity="0010"), order(correlation_id="two", quantity=1.5)]
        before = deepcopy(items)
        with self.assertRaises(ValueError):
            mapping.multi_order_payloads(items)
        self.assertEqual(items, before)

    def test_multi_keeps_omission_and_all_explicit_protection_values(self):
        self.assertNotIn("market_protection", mapping.multi_order_payloads([order(correlation_id="one")])[0])
        for value in (-1, 0, *range(1, 26)):
            fields = order(correlation_id="one", market_protection=value)
            self.assertEqual(mapping.multi_order_payloads([fields]), [fields])

    def test_limit_preserves_requested_automatic_and_positive_protection(self):
        for value in (-1, 1, 25):
            fields = order(order_type="LIMIT", market_protection=value)
            self.assertEqual(mapping.v3_order_payload(fields), fields)
            line = dict(fields, correlation_id="limit")
            self.assertEqual(mapping.multi_order_payloads([line]), [line])

    def test_sl_preserves_requested_automatic_and_positive_protection(self):
        for value in (-1, 1, 25):
            fields = order(order_type="SL", market_protection=value)
            self.assertEqual(mapping.v3_order_payload(fields), fields)
            line = dict(fields, correlation_id="stop")
            self.assertEqual(mapping.multi_order_payloads([line]), [line])

    def test_v3_preserves_surrounding_whitespace_in_nonblank_instrument(self):
        fields = order(instrument_token=" \tNSE_EQ|INE123A01016 \t")
        self.assertEqual(mapping.v3_order_payload(fields), fields)

    def test_multi_preserves_surrounding_whitespace_in_nonblank_identifiers(self):
        fields = order(instrument_token=" \tNSE_EQ|INE123A01016 \t", correlation_id=" \tline \t")
        self.assertEqual(mapping.multi_order_payloads([fields]), [fields])


def rule(strategy="ENTRY", **changes):
    fields = {"strategy": strategy, "trigger_type": "ABOVE" if strategy == "ENTRY" else "IMMEDIATE",
              "trigger_price": 100}
    fields.update(changes)
    return fields


def gtt(**changes):
    fields = {"type": "SINGLE", "quantity": 1, "product": "D", "rules": [rule()],
              "instrument_token": "NSE_EQ|INE123A01016", "transaction_type": "BUY"}
    fields.update(changes)
    return fields


def modification(**changes):
    fields = {"type": "SINGLE", "quantity": 1, "rules": [rule()]}
    fields.update(changes)
    return fields


def observed(**changes):
    fields = {"gtt_order_id": "GTT-1", "instrument_token": "NSE_EQ|INE123A01016", "exchange": "NSE_EQ",
              "product": "D", "type": "MULTIPLE", "quantity": 1, "created_at": 1749466010000000,
              "expires_at": 1781029799000000,
              "rules": [rule(status="COMPLETED", message=None, transaction_type="BUY", order_id="child-1"),
                        rule("STOPLOSS", status="PENDING", message="waiting", transaction_type="SELL", order_id=None)]}
    fields.update(changes)
    return fields


class GttContracts(unittest.TestCase):
    def test_gtt_request_rules(self):
        fields = gtt(type="MULTIPLE", rules=[rule(market_protection=-1),
                     rule("STOPLOSS", market_protection=2, trailing_gap=0.5), rule("TARGET", market_protection=5)])
        self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_single_and_two_leg_shapes(self):
        for rules in ([rule()], [rule(), rule("STOPLOSS")], [rule("TARGET"), rule()]):
            fields = gtt(type="SINGLE" if len(rules) == 1 else "MULTIPLE", rules=rules)
            self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_requires_all_fields(self):
        for key in gtt():
            fields = gtt()
            del fields[key]
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(fields)

    def test_create_rejects_unknown_top_level_fields(self):
        for key in ("market_protection", "order_type", "price", "gtt_order_id", "extra"):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(**{key: 2}))

    def test_create_preserves_native_enums_and_identifier(self):
        for product in ("I", "D", "MTF"):
            for side in ("BUY", "SELL"):
                fields = gtt(product=product, transaction_type=side, instrument_token=" NSE_FO|123 ")
                self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_rejects_invalid_enums_and_identifier(self):
        for key in ("type", "product", "transaction_type", "instrument_token"):
            for value in (None, True, [], {}, "", " \t", "unknown"):
                if key == "instrument_token" and value == "unknown":
                    continue
                with self.assertRaises(ValueError):
                    mapping.gtt_create_payload(gtt(**{key: value}))

    def test_create_exact_quantity_strings(self):
        for value in ("0001", "9007199254740993", 9007199254740993):
            self.assertEqual(mapping.gtt_create_payload(gtt(quantity=value))["quantity"], int(value))

    def test_create_rejects_invalid_quantities(self):
        for value in (0, -1, True, 1.0, 1.5, "1.0", " 1", "+1", "١", None, float("nan")):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(quantity=value))

    def test_create_rejects_malformed_rule_containers(self):
        for value in (None, {}, "rules", [], [None], [1], ["ENTRY"]):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(rules=value))

    def test_create_rejects_invalid_rule_shapes(self):
        for kind, rules in (("SINGLE", [rule("TARGET")]), ("SINGLE", [rule(), rule("TARGET")]),
                            ("MULTIPLE", [rule()]), ("MULTIPLE", [rule("TARGET"), rule("STOPLOSS")]),
                            ("MULTIPLE", [rule(), rule("TARGET"), rule("TARGET")]),
                            ("MULTIPLE", [rule(), rule("TARGET"), rule("STOPLOSS"), rule()])):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(type=kind, rules=rules))

    def test_create_requires_rule_fields(self):
        for key in rule():
            item = rule()
            del item[key]
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(rules=[item]))

    def test_create_rejects_unknown_rule_fields(self):
        for key in ("status", "order_type", "transaction_type", "extra"):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(rules=[rule(**{key: "x"})]))

    def test_create_entry_trigger_types(self):
        for trigger in ("ABOVE", "BELOW", "IMMEDIATE"):
            fields = gtt(rules=[rule(trigger_type=trigger)])
            self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_rejects_invalid_rule_enums(self):
        for key in ("strategy", "trigger_type"):
            for value in (None, True, [], {}, "", "unknown"):
                with self.assertRaises(ValueError):
                    mapping.gtt_create_payload(gtt(rules=[rule(**{key: value})]))

    def test_create_protective_rules_require_immediate(self):
        for strategy in ("STOPLOSS", "TARGET"):
            for trigger in ("ABOVE", "BELOW"):
                with self.assertRaises(ValueError):
                    mapping.gtt_create_payload(
                        gtt(type="MULTIPLE", rules=[rule(), rule(strategy, trigger_type=trigger)]))

    def test_create_trigger_prices_positive_finite(self):
        for value in (1, 0.1, 10**400):
            fields = gtt(rules=[rule(trigger_price=value)])
            self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_rejects_invalid_trigger_prices(self):
        for value in (0, -1, True, "1", None, [], Decimal("1"), float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(rules=[rule(trigger_price=value)]))

    def test_create_trailing_only_on_stoploss(self):
        for strategy in ("ENTRY", "TARGET"):
            rules = [rule(trailing_gap=1)] if strategy == "ENTRY" else [rule(), rule(strategy, trailing_gap=1)]
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(type="SINGLE" if len(rules) == 1 else "MULTIPLE", rules=rules))

    def test_create_rejects_invalid_trailing_gaps(self):
        for value in (0, -1, True, "1", None, [], float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(gtt(type="MULTIPLE", rules=[rule(), rule("STOPLOSS", trailing_gap=value)]))

    def test_create_all_protection_values_each_rule(self):
        for value in range(-1, 26):
            fields = gtt(type="MULTIPLE", rules=[rule(market_protection=value),
                         rule("STOPLOSS", market_protection=value), rule("TARGET", market_protection=value)])
            self.assertEqual(mapping.gtt_create_payload(fields), fields)

    def test_create_rejects_invalid_protection_each_rule(self):
        for strategy in ("ENTRY", "STOPLOSS", "TARGET"):
            for value in (-2, 26, True, 1.0, "1", None, [], float("nan")):
                rules = [rule(market_protection=value)] if strategy == "ENTRY" else [
                    rule(), rule(strategy, market_protection=value)]
                with self.assertRaises(ValueError):
                    mapping.gtt_create_payload(gtt(type="SINGLE" if len(rules) == 1 else "MULTIPLE", rules=rules))

    def test_create_omission_and_independent_copy(self):
        fields = UserDict(gtt(rules=[UserDict(rule())]))
        before = deepcopy(fields)
        result = mapping.gtt_create_payload(fields)
        self.assertEqual(result, fields)
        result["rules"][0]["trigger_price"] = 5
        self.assertEqual(fields, before)

    def test_create_nonmapping_raises_value_error(self):
        for value in (None, [], "x", 1):
            with self.assertRaises(ValueError):
                mapping.gtt_create_payload(value)

    def test_gtt_modify_complete(self):
        changes = modification(type="MULTIPLE", quantity="02", rules=[rule("STOPLOSS", trailing_gap=0.5), rule()])
        self.assertEqual(mapping.gtt_modify_payload(" GTT-1 ", changes),
                         {**changes, "quantity": 2, "gtt_order_id": " GTT-1 "})

    def test_modify_requires_complete_replacement(self):
        for key in modification():
            changes = modification()
            del changes[key]
            with self.assertRaises(ValueError):
                mapping.gtt_modify_payload("GTT-1", changes)

    def test_modify_rejects_unknown_and_top_protection(self):
        for key in ("market_protection", "product", "instrument_token", "transaction_type", "gtt_order_id", "status"):
            with self.assertRaises(ValueError):
                mapping.gtt_modify_payload("GTT-1", modification(**{key: 1}))

    @pytest.mark.unit
    def test_modify_preserves_explicit_pinned_sdk_rule_protection(self):
        for strategy in ("ENTRY", "TARGET", "STOPLOSS"):
            for value in (-1, 0, 1, 25):
                rules = [rule(market_protection=value)] if strategy == "ENTRY" else [
                    rule(), rule(strategy, market_protection=value)]
                changes = modification(type="SINGLE" if len(rules) == 1 else "MULTIPLE", rules=rules)
                original = deepcopy(changes)
                self.assertEqual(mapping.gtt_modify_payload("GTT-1", changes),
                                 {**original, "gtt_order_id": "GTT-1"})
                self.assertEqual(changes, original)

    @pytest.mark.unit
    def test_modify_rejects_invalid_pinned_sdk_rule_protection(self):
        for strategy in ("ENTRY", "TARGET", "STOPLOSS"):
            for value in (-2, 26, True, 1.0, "1", None, [], float("nan")):
                rules = [rule(market_protection=value)] if strategy == "ENTRY" else [
                    rule(), rule(strategy, market_protection=value)]
                changes = modification(type="SINGLE" if len(rules) == 1 else "MULTIPLE", rules=rules)
                with self.assertRaises(ValueError):
                    mapping.gtt_modify_payload("GTT-1", changes)

    def test_modify_rejects_invalid_identifier(self):
        for value in (None, "", " \t", True, [], 1):
            with self.assertRaises(ValueError):
                mapping.gtt_modify_payload(value, modification())

    def test_modify_rejects_invalid_quantities_and_type(self):
        for key, values in (("quantity", (0, -1, True, 1.0, "1.5", None)), ("type", (None, [], "unknown"))):
            for value in values:
                with self.assertRaises(ValueError):
                    mapping.gtt_modify_payload("GTT-1", modification(**{key: value}))

    def test_modify_rejects_invalid_rules(self):
        for rules in (None, {}, [], [rule("TARGET")], [rule(trigger_price=0)], [rule(trailing_gap=1)],
                      [rule(extra=1)], [rule(trigger_type="unknown")]):
            with self.assertRaises(ValueError):
                mapping.gtt_modify_payload("GTT-1", modification(rules=rules))

    def test_modify_independent_mapping_copy(self):
        changes = UserDict(modification(rules=[UserDict(rule(trigger_type="IMMEDIATE"))]))
        before = deepcopy(changes)
        result = mapping.gtt_modify_payload("GTT-1", changes)
        self.assertEqual(result, {**changes, "gtt_order_id": "GTT-1"})
        result["rules"][0]["trigger_price"] = 2
        self.assertEqual(changes, before)

    def test_modify_nonmapping_raises_value_error(self):
        for value in (None, [], "x", 1):
            with self.assertRaises(ValueError):
                mapping.gtt_modify_payload("GTT-1", value)

    def test_gtt_projection(self):
        row = observed(status="ACTIVE", rules=[rule("STOPLOSS", status="PENDING", trailing_gap=0.5,
                       market_protection=2, message="waiting", order_id=None, transaction_type="SELL"),
                       rule(status="COMPLETED", market_protection=-1, message=None, order_id="child",
                            transaction_type="BUY")])
        self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row,
                                                  "resource_status": "ACTIVE", "entry_status": "COMPLETED"})

    def test_projection_preserves_all_raw_statuses(self):
        for status in ("SCHEDULED", "TRIGGERED", "EXPIRED", "OPEN", "COMPLETED", "CANCELLED", "PENDING", "FAILED",
                       "INACTIVE", "FUTURE_COMPLETE_PENDING", "", None):
            row = observed(rules=[rule(status=status)])
            result = mapping.project_gtt(row)
            self.assertEqual(result["entry_status"], status)
            self.assertEqual(result["rules"], row["rules"])
            self.assertNotIn("resource_status", result)

    def test_projection_completed_entry_pending_protection_no_execution_claim(self):
        row = observed()
        self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row, "entry_status": "COMPLETED"})

    def test_projection_missing_entry_status_stays_absent(self):
        for rules in ([rule()], [rule("STOPLOSS", status="PENDING")], []):
            row = observed(rules=rules)
            self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row})

    def test_projection_preserves_native_product_segment_and_unknown_evidence(self):
        for product in ("I", "D", "MTF", "FUTURE"):
            row = observed(product=product, exchange="MCX_FO", instrument_token=" MCX_FO|123 ",
                           extra={"nested": [1]}, filled_quantity=0, average_price=0)
            self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row, "entry_status": "COMPLETED"})

    def test_projection_deeply_independent_source_and_rules(self):
        row = UserDict(observed(extra={"nested": [1]}))
        before = deepcopy(row)
        result = mapping.project_gtt(row)
        result["rules"][0]["status"] = "changed"
        result["extra"]["nested"].append(2)
        self.assertEqual(result["source_fields"], before)
        result["source_fields"]["rules"][0]["status"] = "source changed"
        self.assertEqual(row, before)

    def test_projection_rejects_duplicate_strategies(self):
        for strategy in ("ENTRY", "STOPLOSS", "FUTURE"):
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(rules=[rule(strategy), rule(strategy)]))

    def test_projection_rejects_malformed_rules(self):
        for rules in (None, {}, "x", [None], [1], [{}], [rule(strategy=None)],
                      [rule(strategy=[])], [rule(strategy=" ")]):
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(rules=rules))

    def test_projection_requires_resource_identity_and_rules(self):
        for key in ("gtt_order_id", "instrument_token", "rules"):
            row = observed()
            del row[key]
            with self.assertRaises(ValueError):
                mapping.project_gtt(row)
        for key in ("gtt_order_id", "instrument_token"):
            for value in (None, "", " ", 1):
                with self.assertRaises(ValueError):
                    mapping.project_gtt(observed(**{key: value}))

    def test_projection_rejects_invalid_present_numbers(self):
        for key in ("quantity", "created_at", "expires_at", "filled_quantity"):
            for value in (True, -1, 1.5, None, float("nan")):
                with self.assertRaises(ValueError):
                    mapping.project_gtt(observed(**{key: value}))
        for key in ("trigger_price", "trailing_gap", "market_protection"):
            for value in (True, None, "1", float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    mapping.project_gtt(observed(rules=[rule(**{key: value})]))

    def test_projection_exact_quantity_preserves_raw_source(self):
        row = observed(quantity="9007199254740993")
        result = mapping.project_gtt(row)
        self.assertEqual(result["quantity"], 9007199254740993)
        self.assertEqual(result["source_fields"]["quantity"], "9007199254740993")

    def test_projection_nonmapping_raises_value_error(self):
        for value in (None, [], "x", 1):
            with self.assertRaises(ValueError):
                mapping.project_gtt(value)

    def test_projection_preserves_unfamiliar_rule_shape_and_zero_evidence(self):
        row = observed(rules=[rule("FUTURE", trigger_type="FUTURE", trigger_price=0, trailing_gap=0,
                                  status="CUSTOM", details={"codes": [1]}),
                              rule("TARGET", trailing_gap=1, status="INACTIVE")])
        self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row})

    def test_projection_missing_numeric_evidence_stays_absent(self):
        row = {"gtt_order_id": "GTT-1", "instrument_token": "NSE_EQ|123", "rules": [{"strategy": "ENTRY"}]}
        self.assertEqual(mapping.project_gtt(row), {**row, "source_fields": row})

    def test_projection_does_not_trust_incoming_derived_aliases(self):
        row = observed(rules=[rule()], entry_status="FILLED", resource_status="CLOSED", source_fields={"fake": True})
        expected = {key: value for key, value in row.items()
                    if key not in ("entry_status", "resource_status", "source_fields")}
        self.assertEqual(mapping.project_gtt(row), {**expected, "source_fields": row})

    def test_projection_present_fills_preserved_without_terminal_claim(self):
        row = observed(filled_quantity="01", average_price=5.5,
                       rules=[rule(status="CANCELLED", filled_quantity="01", pending_quantity="02", average_price=5.5)])
        expected = {**row, "filled_quantity": 1, "rules": [{**row["rules"][0], "filled_quantity": 1,
                                                           "pending_quantity": 2}]}
        self.assertEqual(mapping.project_gtt(row), {**expected, "source_fields": row, "entry_status": "CANCELLED"})

    def test_projection_rejects_invalid_rule_fills_and_ids(self):
        for key in ("quantity", "filled_quantity", "pending_quantity"):
            for value in (-1, True, 1.5, None):
                with self.assertRaises(ValueError):
                    mapping.project_gtt(observed(rules=[rule(**{key: value})]))
        for value in ("", " ", 1, [], True):
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(rules=[rule(order_id=value)]))

    def test_projection_rejects_negative_prices_and_bad_protection_range(self):
        for key in ("trigger_price", "trailing_gap", "average_price", "price"):
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(rules=[rule(**{key: -1})]))
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(**{key: -1}))
        for value in (-2, 26, 1.5):
            with self.assertRaises(ValueError):
                mapping.project_gtt(observed(rules=[rule(market_protection=value)]))

    def test_modify_target_trailing_rejected_and_all_entry_triggers_preserved(self):
        with self.assertRaises(ValueError):
            mapping.gtt_modify_payload("GTT-1", modification(type="MULTIPLE",
                                       rules=[rule(), rule("TARGET", trailing_gap=0.1)]))
        for trigger in ("ABOVE", "BELOW", "IMMEDIATE"):
            changes = modification(rules=[rule(trigger_type=trigger)])
            self.assertEqual(mapping.gtt_modify_payload("GTT-1", changes), {**changes, "gtt_order_id": "GTT-1"})

    def test_rejected_requests_leave_nested_inputs_unchanged(self):
        fields = gtt(quantity="02", rules=[rule(market_protection=26)])
        changes = modification(quantity="02", rules=[rule(market_protection=26)])
        before = deepcopy((fields, changes))
        with self.assertRaises(ValueError):
            mapping.gtt_create_payload(fields)
        with self.assertRaises(ValueError):
            mapping.gtt_modify_payload("GTT-1", changes)
        self.assertEqual((fields, changes), before)

    def test_projection_native_statuses_override_conflicting_supplied_aliases(self):
        row = observed(status="RESOURCE_PENDING", entry_status="FILLED", resource_status="CLOSED")
        self.assertEqual(mapping.project_gtt(row), {**row, "entry_status": "COMPLETED",
                                                  "resource_status": "RESOURCE_PENDING", "source_fields": row})

    def test_projection_unknown_resource_and_protective_statuses_remain_independent(self):
        row = observed(status="RESOURCE_FUTURE", rules=[rule(status="ENTRY_FUTURE", message=""),
                       rule("STOPLOSS", status="PROTECTION_FUTURE", message="")])
        self.assertEqual(mapping.project_gtt(row), {**row, "entry_status": "ENTRY_FUTURE",
                                                  "resource_status": "RESOURCE_FUTURE", "source_fields": row})

    def test_projection_nested_unknown_rule_details_are_independently_copied(self):
        row = observed(rules=[rule(status="FAILED", details={"codes": [{"messages": ["rejected"]}]})])
        before = deepcopy(row)
        result = mapping.project_gtt(row)
        result["rules"][0]["details"]["codes"][0]["messages"].append("projected")
        self.assertEqual(result["source_fields"], before)
        self.assertEqual(row, before)
        result["source_fields"]["rules"][0]["details"]["codes"][0]["messages"].append("source")
        self.assertEqual(row, before)
        self.assertEqual(result["rules"][0]["details"]["codes"][0]["messages"], ["rejected", "projected"])


def multi_response(**changes):
    response = {
        "status": "success",
        "data": [{"correlation_id": "line", "order_id": "child-1"}],
        "summary": {"total": 1, "payload_error": 0, "success": 1, "error": 0},
    }
    response.update(changes)
    return response


def cancel_response(**changes):
    response = {
        "status": "success", "data": {"order_ids": ["child-1"]}, "errors": None,
        "summary": {"total": 1, "success": 1, "error": 0},
    }
    response.update(changes)
    return response


def rejection(**changes):
    error = {"error_code": "BROKER_ERROR", "message": "Rejected", "property_path": None, "invalid_value": None}
    error.update(changes)
    return error


class BatchResultContracts(unittest.TestCase):
    def test_multi_projection_lossless(self):
        response = multi_response(
            status="partial_success",
            data=[{"correlation_id": "same", "order_id": "a", "message": "accepted", "details": [1]},
                  {"correlation_id": "same", "order_id": "b"}],
            errors=[rejection(correlation_id="bad", property_path="quantity", invalid_value={"value": -1})],
            summary={"total": 2, "payload_error": 0, "success": 1, "error": 1, "extra": {"x": 1}},
            trace={"request": [1]},
        )
        result = mapping.project_multi_result(response)
        self.assertEqual(result, {**response, "order_ids": ["a", "b"], "order_results": response["data"],
                                  "source_fields": response})

    def test_multi_preserves_suffixed_correlations(self):
        rows = [{"correlation_id": "line_1", "order_id": "a"}, {"correlation_id": "line_2", "order_id": "b"}]
        result = mapping.project_multi_result(multi_response(data=rows))
        self.assertEqual(result["order_results"], rows)
        self.assertEqual(result["summary"]["success"], 1)

    def test_multi_duplicate_child_ids_rejected(self):
        rows = [{"correlation_id": "a", "order_id": "same"}, {"correlation_id": "b", "order_id": "same"}]
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=rows))

    def test_multi_missing_child_id_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=[{"correlation_id": "a"}]))

    def test_multi_blank_child_id_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=[{"correlation_id": "a", "order_id": " "}]))

    def test_multi_missing_correlation_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=[{"order_id": "a"}]))

    def test_multi_malformed_batch_evidence(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data={"order_id": "a"}))

    def test_multi_nonmapping_row_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=["a"]))

    def test_multi_success_missing_data_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "success"})

    def test_multi_success_empty_data_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=[]))

    def test_multi_success_with_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(errors=[rejection()]))

    def test_multi_success_with_error_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"error": 1}))

    def test_multi_success_with_payload_error_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"payload_error": 1}))

    def test_multi_success_zero_success_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"success": 0}))

    def test_multi_error_only_payload_response_preserved(self):
        response = {"status": "error", "errors": [rejection(correlation_id="a"), rejection(correlation_id="b")],
                    "summary": {"total": 5, "payload_error": 2, "success": 0, "error": 0}}
        result = mapping.project_multi_result(response)
        self.assertEqual(result, {**response, "order_ids": [], "order_results": [], "source_fields": response})
        self.assertNotIn("data", result)

    def test_multi_error_without_summary_preserved(self):
        response = {"status": "error", "errors": [rejection()]}
        result = mapping.project_multi_result(response)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("summary", result)

    def test_multi_error_with_null_data_preserved(self):
        result = mapping.project_multi_result({"status": "error", "data": None, "errors": [rejection()]})
        self.assertIsNone(result["data"])

    def test_multi_error_with_success_child_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status="error", errors=[rejection()]))

    def test_multi_error_with_success_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "error", "errors": [rejection()], "summary": {"success": 1}})

    def test_multi_error_without_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "error"})

    def test_multi_partial_requires_errors(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status="partial_success"))

    def test_multi_partial_requires_success_children(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "partial_success", "errors": [rejection()]})

    def test_multi_partial_payload_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status="partial_success", errors=[rejection()],
                                                       summary={"payload_error": 1}))

    def test_multi_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status="COMPLETE"))

    def test_multi_nonstring_status_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status=[]))

    def test_multi_nonmapping_envelope_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result([])

    def test_multi_errors_mapping_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(errors={}))

    def test_multi_errors_nonmapping_item_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "error", "errors": ["bad"]})

    def test_multi_summary_list_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary=[]))

    def test_multi_summary_null_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary=None))

    def test_multi_boolean_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"total": True}))

    def test_multi_fractional_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"success": 1.5}))

    def test_multi_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"error": -1}))

    def test_multi_string_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"payload_error": "0"}))

    def test_multi_count_exceeds_total_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"total": 1, "success": 2}))

    def test_multi_count_total_contradiction_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"total": 2, "success": 1, "error": 0}))

    def test_multi_copies_every_nested_branch_independently(self):
        response = multi_response(data=[{"correlation_id": "a", "order_id": "a", "details": {"x": []}}],
                                  summary={"success": 1, "extra": []}, trace=[])
        before = deepcopy(response)
        result = mapping.project_multi_result(response)
        result["data"][0]["details"]["x"].append(1)
        result["summary"]["extra"].append(1)
        result["trace"].append(1)
        self.assertEqual(result["order_results"], before["data"])
        self.assertEqual(result["source_fields"], before)
        self.assertEqual(response, before)
        result["source_fields"]["data"][0]["details"]["x"].append(2)
        self.assertEqual(result["order_results"], before["data"])

    def test_multi_alias_collisions_cannot_forge_children(self):
        response = multi_response(order_ids=["forged"], order_results=[{"order_id": "forged"}], source_fields={})
        result = mapping.project_multi_result(response)
        self.assertEqual(result["order_ids"], ["child-1"])
        self.assertEqual(result["order_results"], response["data"])
        self.assertEqual(result["source_fields"], response)

    def test_multi_no_execution_state_invented(self):
        result = mapping.project_multi_result(multi_response())
        self.assertEqual(set(result), {"status", "data", "summary", "order_ids", "order_results", "source_fields"})
        self.assertEqual(result["order_results"], [{"correlation_id": "line", "order_id": "child-1"}])

    def test_cancel_exit_projection(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a", "b"], "extra": [1]},
                                   errors=[rejection(order_id=None, instrument_key="NSE_EQ|x", details=[1])],
                                   summary={"total": 3, "success": 2, "error": 1})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result, {**response, "order_ids": ["a", "b"], "source_fields": response})

    def test_cancel_success_null_errors_retained(self):
        result = mapping.project_cancel_exit_result(cancel_response())
        self.assertIsNone(result["errors"])
        self.assertEqual(result["order_ids"], ["child-1"])

    def test_cancel_error_only_without_data_or_summary(self):
        response = {"status": "error", "errors": [rejection(message="No open or pending order available")]}
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result, {**response, "order_ids": [], "source_fields": response})

    def test_exit_error_camel_and_snake_fields_preserved(self):
        error = rejection(errorCode="UDAPI1111", propertyPath=None, invalidValue=None)
        response = {"status": "error", "data": None, "errors": [error]}
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result, {**response, "order_ids": [], "source_fields": response})

    def test_cancel_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data={"order_ids": ["a", "a"]}))

    def test_cancel_missing_ids_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data={}))

    def test_cancel_blank_id_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data={"order_ids": [" "]}))

    def test_cancel_ids_string_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data={"order_ids": "abc"}))

    def test_cancel_data_array_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data=[{"order_id": "a"}]))

    def test_cancel_success_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(errors=[rejection()]))

    def test_cancel_success_error_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(summary={"error": 1}))

    def test_cancel_success_empty_ids_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(data={"order_ids": []}))

    def test_cancel_error_with_child_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(status="error", errors=[rejection()]))

    def test_cancel_partial_missing_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(status="partial_success"))

    def test_cancel_invalid_error_identifier_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result({"status": "error", "errors": [rejection(order_id=" ")]})

    def test_cancel_nullable_error_identifiers_preserved(self):
        response = {"status": "error", "errors": [rejection(order_id=None, instrument_key=None)]}
        self.assertEqual(mapping.project_cancel_exit_result(response)["errors"], response["errors"])

    def test_cancel_copies_errors_and_data(self):
        response = cancel_response(status="partial_success", errors=[rejection(details={"x": []})],
                                   summary={"total": 2, "success": 1, "error": 1})
        before = deepcopy(response)
        result = mapping.project_cancel_exit_result(response)
        result["errors"][0]["details"]["x"].append(1)
        result["data"]["order_ids"].append("other")
        self.assertEqual(result["order_ids"], ["child-1"])
        self.assertEqual(result["source_fields"], before)
        self.assertEqual(response, before)

    def test_cancel_alias_collision_overridden(self):
        response = cancel_response(order_ids=["forged"], source_fields={})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["order_ids"], ["child-1"])
        self.assertEqual(result["source_fields"], response)

    def test_cancel_ack_does_not_invent_terminal_state(self):
        result = mapping.project_cancel_exit_result(cancel_response())
        self.assertEqual(set(result), {"status", "data", "errors", "summary", "order_ids", "source_fields"})

    def test_batch_accepts_mapping_wrappers(self):
        result = mapping.project_multi_result(UserDict(multi_response(data=[UserDict(
            {"order_id": "a", "correlation_id": "a"})])))
        self.assertEqual(result["order_ids"], ["a"])

    def test_batch_rejection_does_not_mutate(self):
        response = multi_response(errors=[rejection(details={"x": []})])
        before = deepcopy(response)
        with self.assertRaises(ValueError):
            mapping.project_multi_result(response)
        self.assertEqual(response, before)

    def test_success_zero_total_without_success_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(summary={"total": 0}))

    def test_cancel_missing_status_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result({"data": {"order_ids": ["a"]}})

    def test_cancel_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(status="CANCELLED"))

    def test_cancel_nonmapping_envelope_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(None)

    def test_cancel_partial_without_child_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result({"status": "partial_success", "errors": [rejection()]})

    def test_cancel_boolean_summary_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(summary={"success": True}))

    def test_multi_string_data_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data="child"))

    def test_multi_string_errors_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "error", "errors": "failed"})

    def test_multi_blank_correlation_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(data=[{"correlation_id": " ", "order_id": "a"}]))

    def test_multi_long_response_correlation_preserved(self):
        row = {"correlation_id": "x" * 20 + "_100", "order_id": "a"}
        self.assertEqual(mapping.project_multi_result(multi_response(data=[row]))["order_results"], [row])

    def test_multi_empty_error_row_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result({"status": "error", "errors": [{}]})

    def test_multi_partial_zero_error_count_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_multi_result(multi_response(status="partial_success", errors=[rejection()],
                                                       summary={"error": 0}))

    def test_multi_empty_errors_and_absent_summary_preserved(self):
        response = {"status": "success", "data": [{"correlation_id": "a", "order_id": "a"}], "errors": []}
        result = mapping.project_multi_result(response)
        self.assertEqual(result["errors"], [])
        self.assertNotIn("summary", result)

    def test_cancel_multiple_errors_for_same_item_preserved(self):
        errors = [rejection(order_id="a", property_path="one"), rejection(order_id="a", property_path="two")]
        response = {"status": "error", "errors": errors, "summary": {"total": 1, "success": 0, "error": 1}}
        self.assertEqual(mapping.project_cancel_exit_result(response)["errors"], errors)

    def test_cancel_native_item_status_and_messages_remain_evidence(self):
        response = cancel_response(data={"order_ids": ["a"], "status": "CANCEL_PENDING", "message": ""})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["data"], response["data"])
        self.assertNotIn("closed", result)
        self.assertNotIn("filled_quantity", result)

    def test_multi_payload_error_precludes_processing_errors(self):
        response = {"status": "error", "errors": [rejection(correlation_id="a")],
                    "summary": {"total": 5, "payload_error": 2, "success": 0, "error": 1}}
        with self.assertRaises(ValueError):
            mapping.project_multi_result(response)

    def test_cancel_same_id_success_and_error_rejected(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a"]},
                                   errors=[rejection(order_id="a", instrument_key="NSE_EQ|x")],
                                   summary={"total": 2, "success": 1, "error": 1})
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(response, operation="cancel")

    def test_cancel_exit_child_count_is_not_summary_line_count(self):
        response = cancel_response(data={"order_ids": ["a", "b", "c"]},
                                   summary={"total": 1, "success": 1, "error": 0})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["order_ids"], ["a", "b", "c"])
        self.assertEqual(result["summary"], response["summary"])
        self.assertEqual(result["source_fields"], response)

    def test_multi_empty_error_message_preserved(self):
        response = {"status": "error", "errors": [rejection(message="")]}
        result = mapping.project_multi_result(response)
        self.assertEqual(result["errors"][0]["message"], "")
        self.assertEqual(result["source_fields"], response)

    def test_multi_null_error_message_preserved(self):
        response = {"status": "error", "errors": [rejection(message=None)]}
        result = mapping.project_multi_result(response)
        self.assertIsNone(result["errors"][0]["message"])
        self.assertEqual(result["source_fields"], response)

    def test_cancel_empty_error_message_preserved(self):
        response = {"status": "error", "errors": [rejection(message="")]}
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["errors"][0]["message"], "")
        self.assertEqual(result["source_fields"], response)

    def test_exit_null_error_message_preserved(self):
        response = {"status": "error", "data": None, "errors": [rejection(message=None, order_id=None)]}
        result = mapping.project_cancel_exit_result(response)
        self.assertIsNone(result["errors"][0]["message"])
        self.assertEqual(result["source_fields"], response)

    def test_multi_shared_success_error_correlation_preserved(self):
        response = multi_response(status="partial_success", data=[{"correlation_id": "a", "order_id": "child"}],
                                  errors=[rejection(correlation_id="a")],
                                  summary={"total": 2, "success": 1, "error": 1, "payload_error": 0})
        result = mapping.project_multi_result(response)
        self.assertEqual(result["order_ids"], ["child"])
        self.assertEqual(result["errors"], response["errors"])

    def test_cancel_payload_error_does_not_inherit_placement_only_rule(self):
        response = {"status": "error", "errors": [rejection()],
                    "summary": {"total": 5, "payload_error": 2, "success": 0, "error": 1}}
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["summary"], response["summary"])

    def test_exit_distinct_associated_error_order_preserved(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["new-exit"]},
                                   errors=[rejection(order_id="associated-position-order", instrument_key="NSE_EQ|x")],
                                   summary={"total": 2, "success": 1, "error": 1})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["errors"], response["errors"])
        self.assertEqual(result["order_ids"], ["new-exit"])

    def test_cancel_exit_unspecified_operation_marks_colliding_ids(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["b", "a"]},
                                   errors=[rejection(order_id="a"), rejection(order_id="a")],
                                   summary={"total": 3, "success": 2, "error": 1})
        result = mapping.project_cancel_exit_result(response)
        self.assertEqual(result["operation_ambiguity"], {"order_ids": ["a"]})
        self.assertEqual(result["errors"], response["errors"])
        self.assertEqual(result["source_fields"], response)

    def test_exit_colliding_opaque_error_ids_preserved(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a"]},
                                   errors=[rejection(order_id="a")], summary={"total": 2, "success": 1, "error": 1})
        result = mapping.project_cancel_exit_result(response, operation="exit")
        self.assertEqual(result["errors"], response["errors"])
        self.assertNotIn("operation_ambiguity", result)
        self.assertEqual(result["source_fields"], response)

    def test_cancel_distinct_error_ids_preserved_with_explicit_operation(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a"]},
                                   errors=[rejection(order_id="b")], summary={"total": 2, "success": 1, "error": 1})
        result = mapping.project_cancel_exit_result(response, operation="cancel")
        self.assertEqual(result["errors"], response["errors"])
        self.assertNotIn("operation_ambiguity", result)

    def test_cancel_null_error_ids_preserved_with_explicit_operation(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a"]},
                                   errors=[rejection(order_id=None)], summary={"total": 2, "success": 1, "error": 1})
        result = mapping.project_cancel_exit_result(response, operation="cancel")
        self.assertEqual(result["errors"], response["errors"])
        self.assertNotIn("operation_ambiguity", result)

    def test_exit_null_error_ids_preserved_with_explicit_operation(self):
        response = cancel_response(status="partial_success", data={"order_ids": ["a"]},
                                   errors=[rejection(order_id=None)], summary={"total": 2, "success": 1, "error": 1})
        self.assertEqual(mapping.project_cancel_exit_result(response, operation="exit")["errors"], response["errors"])

    def test_cancel_exit_explicit_none_preserves_observation(self):
        response = cancel_response()
        self.assertEqual(mapping.project_cancel_exit_result(response, operation=None),
                         mapping.project_cancel_exit_result(response))

    def test_cancel_exit_invalid_operation_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(), operation="place")

    def test_cancel_exit_nonstring_operation_rejected(self):
        with self.assertRaises(ValueError):
            mapping.project_cancel_exit_result(cancel_response(), operation=[])

    def test_cancel_exit_ambiguity_alias_cannot_be_forged(self):
        response = cancel_response(operation_ambiguity={"order_ids": ["forged"]})
        result = mapping.project_cancel_exit_result(response)
        self.assertNotIn("operation_ambiguity", result)
        self.assertEqual(result["source_fields"], response)

    def test_cancel_exit_ambiguity_ids_independent_of_source(self):
        response = cancel_response(status="partial_success", errors=[rejection(order_id="child-1")],
                                   summary={"total": 2, "success": 1, "error": 1})
        result = mapping.project_cancel_exit_result(response)
        result["operation_ambiguity"]["order_ids"].append("other")
        self.assertEqual(result["order_ids"], ["child-1"])
        self.assertEqual(result["source_fields"], response)
