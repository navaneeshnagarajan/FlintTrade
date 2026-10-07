"""Independent current-public parameter tests; no SDK or runtime imports."""

import unittest
from collections import UserDict
from decimal import Decimal, localcontext

import pytest

from flinttrade_gateway.brokers import kotakneo_order_mapping as mapping


def order(**changes):
    result = {"action": "BUY", "pricetype": "MARKET", "exchange": "NSE", "product": "MIS", "quantity": 10}
    result.update(changes)
    return result


class KotakParametersTests(unittest.TestCase):
    def test_place_contract(self):
        self.assertEqual(
            mapping.place_parameters(order(), trading_symbol="ABC-EQ"),
            {
                "exchange_segment": "nse_cm",
                "product": "MIS",
                "price": "0",
                "order_type": "MKT",
                "quantity": "10",
                "validity": "DAY",
                "trading_symbol": "ABC-EQ",
                "transaction_type": "B",
                "trigger_price": "0",
                "disclosed_quantity": "0",
                "amo": "NO",
            },
        )

    def test_modify_contract(self):
        self.assertEqual(
            mapping.modify_parameters("123", {"quantity": 10, "pricetype": "MARKET"}),
            {
                "order_id": "123",
                "order_type": "MKT",
                "price": "0",
                "quantity": "10",
                "validity": "DAY",
                "trigger_price": "0",
                "disclosed_quantity": "0",
            },
        )

    def test_schema_identity(self):
        self.assertEqual(mapping.SCHEMA_ID, "kotak-public-v3-order-parameters-2026-10-06")

    def test_mapping_not_mutated(self):
        source = UserDict(order(price=Decimal("12.3400"), disclosed_quantity=2))
        before = dict(source)
        result = mapping.place_parameters(source, trading_symbol="ABC", tag=" tag ")
        self.assertEqual(source, before)
        self.assertEqual(result["tag"], " tag ")
        self.assertEqual(result["price"], "12.34")
        self.assertEqual(result["disclosed_quantity"], "2")

    def test_modify_mapping_not_mutated(self):
        source = UserDict(quantity=10, order_type="L", price="1.25", product="MTF", action="SELL", exchange="NFO")
        before = dict(source)
        result = mapping.modify_parameters("123", source)
        self.assertEqual(source, before)
        self.assertEqual(
            set(result),
            {"order_id", "order_type", "price", "quantity", "validity", "trigger_price", "disclosed_quantity"},
        )

    def test_decimal_context_does_not_round(self):
        with localcontext() as ctx:
            ctx.prec = 2
            result = mapping.place_parameters(order(price=Decimal("123456789.1234567890123456")), trading_symbol="ABC")
        self.assertEqual(result["price"], "123456789.1234567890123456")

    def test_place_sell(self):
        result = mapping.place_parameters(order(action="SELL"), trading_symbol="ABC")
        self.assertEqual(result["transaction_type"], "S")

    def test_place_bse(self):
        result = mapping.place_parameters(order(exchange="BSE"), trading_symbol="ABC")
        self.assertEqual(result["exchange_segment"], "bse_cm")

    def test_place_nfo(self):
        result = mapping.place_parameters(order(exchange="NFO"), trading_symbol="ABC")
        self.assertEqual(result["exchange_segment"], "nse_fo")

    def test_place_bfo(self):
        result = mapping.place_parameters(order(exchange="BFO"), trading_symbol="ABC")
        self.assertEqual(result["exchange_segment"], "bse_fo")

    def test_place_mcx(self):
        result = mapping.place_parameters(order(exchange="MCX"), trading_symbol="ABC")
        self.assertEqual(result["exchange_segment"], "mcx_fo")

    def test_place_cnc(self):
        result = mapping.place_parameters(order(product="CNC"), trading_symbol="ABC")
        self.assertEqual(result["product"], "CNC")

    def test_place_nrml(self):
        result = mapping.place_parameters(order(product="NRML"), trading_symbol="ABC")
        self.assertEqual(result["product"], "NRML")

    def test_place_mtf(self):
        result = mapping.place_parameters(order(product="MTF"), trading_symbol="ABC")
        self.assertEqual(result["product"], "MTF")

    def test_place_amo(self):
        result = mapping.place_parameters(order(variety="amo"), trading_symbol="ABC")
        self.assertEqual(result["amo"], "YES")

    def test_place_ioc(self):
        result = mapping.place_parameters(order(validity="IOC"), trading_symbol="ABC")
        self.assertEqual(result["validity"], "IOC")

    def test_place_limit(self):
        result = mapping.place_parameters(
            order(pricetype="LIMIT", price="10.5", trigger_price="10"), trading_symbol="ABC"
        )
        self.assertEqual(result["order_type"], "L")

    def test_place_stop(self):
        result = mapping.place_parameters(order(pricetype="SL", price="10.5", trigger_price="10"), trading_symbol="ABC")
        self.assertEqual(result["order_type"], "SL")

    def test_place_stop_market(self):
        result = mapping.place_parameters(
            order(pricetype="SL-M", price="10.5", trigger_price="10"), trading_symbol="ABC"
        )
        self.assertEqual(result["order_type"], "SL-M")

    def test_numeric_integer_limit(self):
        result = mapping.place_parameters(order(price="9" * 64), trading_symbol="ABC")
        self.assertEqual(result["price"], "9" * 64)

    def test_numeric_places_limit(self):
        result = mapping.place_parameters(order(price="0.0000000000000001"), trading_symbol="ABC")
        self.assertEqual(result["price"], "0.0000000000000001")

    def test_numeric_exponent(self):
        result = mapping.place_parameters(order(price="1.25e2"), trading_symbol="ABC")
        self.assertEqual(result["price"], "125")

    def test_numeric_float(self):
        result = mapping.place_parameters(order(price=12.5), trading_symbol="ABC")
        self.assertEqual(result["price"], "12.5")

    def test_numeric_trailing_zeroes(self):
        result = mapping.place_parameters(order(price="1.2500000000000000000"), trading_symbol="ABC")
        self.assertEqual(result["price"], "1.25")

    def test_reject_place_unknown(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(mystery=1), trading_symbol="ABC")

    def test_reject_place_co(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(product="CO"), trading_symbol="ABC")

    def test_reject_place_bo(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(product="BO"), trading_symbol="ABC")

    def test_reject_place_bad_product(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(product="X"), trading_symbol="ABC")

    def test_reject_place_gtc(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(validity="GTC"), trading_symbol="ABC")

    def test_reject_place_gtd(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(validity="GTD"), trading_symbol="ABC")

    def test_reject_place_eos(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(validity="EOS"), trading_symbol="ABC")

    def test_reject_place_bad_action(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(action="B"), trading_symbol="ABC")

    def test_reject_place_bad_exchange(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(exchange="CDS"), trading_symbol="ABC")

    def test_reject_place_spread(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="SP"), trading_symbol="ABC")

    def test_reject_place_two_leg(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="2L"), trading_symbol="ABC")

    def test_reject_place_three_leg(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="3L"), trading_symbol="ABC")

    def test_reject_place_bad_variety(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(variety="iceberg"), trading_symbol="ABC")

    def test_reject_place_bool_qty(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=True), trading_symbol="ABC")

    def test_reject_place_zero_qty(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=0), trading_symbol="ABC")

    def test_reject_place_negative_qty(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=-1), trading_symbol="ABC")

    def test_reject_place_fraction_qty(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity="1.5"), trading_symbol="ABC")

    def test_reject_place_none_qty(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=None), trading_symbol="ABC")

    def test_reject_place_bool_price(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price=True), trading_symbol="ABC")

    def test_reject_place_negative_price(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price=-1), trading_symbol="ABC")

    def test_reject_place_nan(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="NaN"), trading_symbol="ABC")

    def test_reject_place_infinity(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="Infinity"), trading_symbol="ABC")

    def test_reject_place_negative_infinity(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="-Infinity"), trading_symbol="ABC")

    def test_reject_place_snan(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="sNaN"), trading_symbol="ABC")

    def test_reject_place_bad_numeric(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="x"), trading_symbol="ABC")

    def test_reject_place_blank_numeric(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price=""), trading_symbol="ABC")

    def test_reject_place_negative_trigger(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(trigger_price=-1), trading_symbol="ABC")

    def test_reject_place_negative_disclosed(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(disclosed_quantity=-1), trading_symbol="ABC")

    def test_reject_place_fraction_disclosed(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(disclosed_quantity="1.5"), trading_symbol="ABC")

    def test_reject_place_excess_disclosed(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(disclosed_quantity=11), trading_symbol="ABC")

    def test_reject_place_mp(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(mp=0), trading_symbol="ABC")

    def test_reject_place_market_protection(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(market_protection=0), trading_symbol="ABC")

    def test_reject_place_removed_pf(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pf=0), trading_symbol="ABC")

    def test_reject_place_removed_scrip_token(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(scrip_token=0), trading_symbol="ABC")

    def test_reject_place_removed_square_off_type(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(square_off_type=0), trading_symbol="ABC")

    def test_reject_place_removed_stop_loss_type(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(stop_loss_type=0), trading_symbol="ABC")

    def test_reject_place_removed_stop_loss_value(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(stop_loss_value=0), trading_symbol="ABC")

    def test_reject_place_removed_square_off_value(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(square_off_value=0), trading_symbol="ABC")

    def test_reject_place_removed_last_traded_price(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(last_traded_price=0), trading_symbol="ABC")

    def test_reject_place_removed_trailing_stop_loss(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(trailing_stop_loss=0), trading_symbol="ABC")

    def test_reject_place_removed_trailing_sl_value(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(trailing_sl_value=0), trading_symbol="ABC")

    def test_missing_quantity(self):
        source = order()
        del source["quantity"]
        with self.assertRaises(ValueError):
            mapping.place_parameters(source, trading_symbol="ABC")

    def test_missing_product(self):
        source = order()
        del source["product"]
        with self.assertRaises(ValueError):
            mapping.place_parameters(source, trading_symbol="ABC")

    def test_missing_action(self):
        source = order()
        del source["action"]
        with self.assertRaises(ValueError):
            mapping.place_parameters(source, trading_symbol="ABC")

    def test_missing_pricetype(self):
        source = order()
        del source["pricetype"]
        with self.assertRaises(ValueError):
            mapping.place_parameters(source, trading_symbol="ABC")

    def test_missing_exchange(self):
        source = order()
        del source["exchange"]
        with self.assertRaises(ValueError):
            mapping.place_parameters(source, trading_symbol="ABC")

    def test_reject_numeric_too_many_digits(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="9" * 65), trading_symbol="ABC")

    def test_reject_numeric_too_many_places(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="1e-17"), trading_symbol="ABC")

    def test_reject_numeric_huge_exponent(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="1e999999999"), trading_symbol="ABC")

    def test_reject_numeric_huge_negative_exponent(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="1e-999999999"), trading_symbol="ABC")

    def test_reject_numeric_mixed_significant(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price="9" * 64 + ".1"), trading_symbol="ABC")

    def test_reject_numeric_container(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(price=[]), trading_symbol="ABC")

    def test_reject_missing_price_limit(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="LIMIT", trigger_price=1), trading_symbol="ABC")

    def test_reject_missing_price_sl(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="SL", trigger_price=1), trading_symbol="ABC")

    def test_reject_missing_trigger_sl(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="SL", price=1), trading_symbol="ABC")

    def test_reject_missing_trigger_sl_m(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(pricetype="SL-M", price=1), trading_symbol="ABC")

    def test_reject_blank_symbol(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(), trading_symbol="  ")

    def test_reject_nonstr_symbol(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(), trading_symbol=123)

    def test_reject_blank_tag(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(), trading_symbol="ABC", tag=" ")

    def test_reject_nonstr_tag(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(), trading_symbol="ABC", tag=12)

    def test_reject_mcx_ioc(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(exchange="MCX", validity="IOC"), trading_symbol="ABC")

    def test_reject_place_nonmapping(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters([], trading_symbol="ABC")

    def test_modify_equivalent_alias_market(self):
        result = mapping.modify_parameters(
            "123", {"quantity": 1, "pricetype": "MARKET", "order_type": "MKT", "price": 2, "trigger_price": 1}
        )
        self.assertEqual(result["order_type"], "MKT")

    def test_modify_equivalent_alias_limit(self):
        result = mapping.modify_parameters(
            "123", {"quantity": 1, "pricetype": "LIMIT", "order_type": "L", "price": 2, "trigger_price": 1}
        )
        self.assertEqual(result["order_type"], "L")

    def test_modify_equivalent_alias_sl(self):
        result = mapping.modify_parameters(
            "123", {"quantity": 1, "pricetype": "SL", "order_type": "SL", "price": 2, "trigger_price": 1}
        )
        self.assertEqual(result["order_type"], "SL")

    def test_modify_equivalent_alias_sl_m(self):
        result = mapping.modify_parameters(
            "123", {"quantity": 1, "pricetype": "SL-M", "order_type": "SL-M", "price": 2, "trigger_price": 1}
        )
        self.assertEqual(result["order_type"], "SL-M")

    def test_modify_amo(self):
        source = {"quantity": 10, "order_type": "MKT", "amo": "YES"}
        result = mapping.modify_parameters("123", source)
        self.assertEqual(result["amo"], "YES")

    def test_modify_regular(self):
        source = {"quantity": 10, "order_type": "MKT", "variety": "regular"}
        result = mapping.modify_parameters("123", source)
        self.assertEqual(result["amo"], "NO")

    def test_modify_amo_variety(self):
        source = {"quantity": 10, "order_type": "MKT", "variety": "amo"}
        result = mapping.modify_parameters("123", source)
        self.assertEqual(result["amo"], "YES")

    def test_modify_equivalent_amo(self):
        source = {"quantity": 10, "order_type": "MKT", "variety": "amo", "amo": "YES"}
        result = mapping.modify_parameters("123", source)
        self.assertEqual(result["amo"], "YES")

    def test_modify_ioc(self):
        source = {"quantity": 10, "order_type": "MKT", "validity": "IOC"}
        result = mapping.modify_parameters("123", source)
        self.assertEqual(result["validity"], "IOC")

    def test_reject_modify_alias_conflict(self):
        with self.assertRaisesRegex(ValueError, "Explicit unambiguous order type is required"):
            mapping.modify_parameters("123", {"quantity": 1, "pricetype": "LIMIT", "order_type": "MKT", "price": 2})

    def test_reject_modify_missing_quantity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"order_type": "MKT"})

    def test_reject_modify_missing_type(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1})

    def test_reject_modify_mcx_ioc(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "MKT", "exchange": "MCX", "validity": "IOC"})

    def test_reject_modify_amo_conflict(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "MKT", "variety": "regular", "amo": "YES"})

    def test_reject_modify_bad_exchange(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "exchange": "CDS"})

    def test_reject_modify_bad_product(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "product": "CO"})

    def test_reject_modify_bad_action(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "action": "X"})

    def test_reject_modify_bad_amo(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "amo": "true"})

    def test_reject_modify_bool_quantity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": True, "order_type": "MKT"})

    def test_reject_modify_bad_quantity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": "1.5", "order_type": "MKT"})

    def test_reject_modify_bad_disclosed_quantity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "disclosed_quantity": 11})

    def test_reject_modify_bad_price(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "price": "NaN"})

    def test_reject_modify_bad_validity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "validity": "GTC"})

    def test_reject_modify_bad_isVerify(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "isVerify": True})

    def test_reject_modify_bad_filled_quantity(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "filled_quantity": 0})

    def test_reject_modify_bad_dd(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "dd": 0})

    def test_reject_modify_bad_mp(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "mp": 0})

    def test_reject_modify_bad_market_protection(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "market_protection": 0})

    def test_reject_modify_bad_tag(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "tag": "tag"})

    def test_reject_modify_bad_instrument_token(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "instrument_token": "123"})

    def test_reject_modify_bad_trading_symbol(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "trading_symbol": "ABC"})

    def test_reject_modify_bad_transaction_type(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "transaction_type": "B"})

    def test_reject_modify_bad_exchange_segment(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 10, "order_type": "MKT", "exchange_segment": "nse_cm"})

    def test_reject_modify_blank_id(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters(" ", {"quantity": 1, "order_type": "MKT"})

    def test_reject_modify_nonstr_id(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters(123, {"quantity": 1, "order_type": "MKT"})

    def test_reject_modify_nonmapping(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", [])

    def test_modify_limit_requires_price(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "L"})

    def test_modify_stop_requires_trigger(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "SL", "price": 2})

    def test_modify_stop_market_requires_trigger(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "SL-M"})

    def test_modify_stop_requires_price(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "SL", "trigger_price": 2})

    def test_modify_canonical_order_type(self):
        result = mapping.modify_parameters("123", {"quantity": 1, "order_type": "LIMIT", "price": 2})
        self.assertEqual(result["order_type"], "L")

    def test_modify_invalid_populated_alias(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "MKT", "pricetype": None})

    def test_modify_invalid_wire_type(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "SP"})

    def test_modify_explicit_no_amo(self):
        result = mapping.modify_parameters("123", {"quantity": 1, "order_type": "MKT", "amo": "NO"})
        self.assertEqual(result["amo"], "NO")

    def test_quantity_integral_decimal(self):
        result = mapping.place_parameters(order(quantity=Decimal("10.000")), trading_symbol="ABC")
        self.assertEqual(result["quantity"], "10")

    def test_disclosure_equal_quantity(self):
        result = mapping.place_parameters(order(disclosed_quantity=10), trading_symbol="ABC")
        self.assertEqual(result["disclosed_quantity"], "10")

    def test_quantity_sixty_four_digits(self):
        result = mapping.place_parameters(order(quantity=10**64 - 1), trading_symbol="ABC")
        self.assertEqual(result["quantity"], "9" * 64)

    def test_quantity_sixty_five_digits(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=10**64), trading_symbol="ABC")

    def test_quantity_huge_integer(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(quantity=10**5000), trading_symbol="ABC")

    def test_zero_exponent_is_bounded(self):
        result = mapping.place_parameters(order(price="0e999999999"), trading_symbol="ABC")
        self.assertEqual(result["price"], "0")

    def test_redundant_decimal_precision(self):
        result = mapping.place_parameters(order(price=Decimal("1." + "0" * 10000)), trading_symbol="ABC")
        self.assertEqual(result["price"], "1")

    def test_trigger_bool(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(trigger_price=True), trading_symbol="ABC")

    def test_disclosure_bool(self):
        with self.assertRaises(ValueError):
            mapping.place_parameters(order(disclosed_quantity=True), trading_symbol="ABC")

    def test_modify_tag_rejected(self):
        with self.assertRaises(ValueError):
            mapping.modify_parameters("123", {"quantity": 1, "order_type": "MKT", "tag": "tracking"})

    def test_modify_numeric_precision(self):
        result = mapping.modify_parameters(
            "123",
            {
                "quantity": "1e1",
                "order_type": "SL",
                "price": "12.340",
                "trigger_price": "12.1",
                "disclosed_quantity": "2.00",
                "validity": "IOC",
            },
        )
        self.assertEqual(
            result,
            {
                "order_id": "123",
                "order_type": "SL",
                "quantity": "10",
                "price": "12.34",
                "trigger_price": "12.1",
                "disclosed_quantity": "2",
                "validity": "IOC",
            },
        )


class KotakObservationTests(unittest.TestCase):
    @pytest.mark.unit
    def test_order_rejects_fills_above_total(self):
        rows = (
            {"nOrdNo": "1", "qty": 1, "fldQty": 2, "ordSt": "complete"},
            {"nOrdNo": "1", "qty": "0", "fldQty": "1", "ordSt": "open"},
            {"nOrdNo": "1", "quantity": "100", "filled_quantity": "101", "ordSt": "cancelled"},
            {"nOrdNo": "1", "qty": "9007199254740992", "fldQty": "9007199254740993"},
        )
        for row in rows:
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, "filled_quantity cannot exceed quantity"):
                    mapping.project_order(row)
                with self.assertRaisesRegex(ValueError, "filled_quantity cannot exceed quantity"):
                    mapping.history_rows({"stat": "Ok", "data": [row]})

    def test_order_projection(self):
        row = UserDict(
            nOrdNo="001",
            qty=100,
            fldQty="40",
            prc="12.50",
            trgPrc=0,
            avgPrc="12.25",
            prod="BO",
            trdSym="ABC-EQ",
            sym="ABC",
            exSeg="old_segment",
            trnsTp="B",
            prcTp="L",
            rejRsn="reason",
            exchOrdId="E1",
            GuiOrdId="G1",
            ordDtTm="ordered",
            ordEntTm="entered",
            vldt="GTC",
            ordSt=" cancelled ",
        )
        before = dict(row)
        result = mapping.project_order(row)
        self.assertEqual(
            result,
            {
                "schema_id": mapping.SCHEMA_ID,
                "raw": before,
                "orderid": "001",
                "quantity": "100",
                "filled_quantity": "40",
                "price": "12.5",
                "trigger_price": "0",
                "average_price": "12.25",
                "broker_product": "BO",
                "trading_symbol": "ABC-EQ",
                "symbol": "ABC",
                "exchange_segment": "old_segment",
                "transaction_type": "B",
                "order_type": "L",
                "rejection_reason": "reason",
                "exchange_order_id": "E1",
                "gui_order_id": "G1",
                "timestamp": "ordered",
                "validity": "GTC",
                "status": " cancelled ",
                "attempt_state": "CANCELLED",
            },
        )
        self.assertEqual(row, before)
        self.assertIsNot(result["raw"], row)

    def test_missing_quantities_stay_absent(self):
        result = mapping.project_order({"nOrdNo": "1"})
        self.assertEqual(
            result, {"schema_id": mapping.SCHEMA_ID, "raw": {"nOrdNo": "1"}, "orderid": "1", "attempt_state": "UNKNOWN"}
        )

    def test_explicit_zero_quantities_stay_present(self):
        result = mapping.project_order({"nOrdNo": "1", "qty": 0, "fldQty": "0"})
        self.assertEqual((result["quantity"], result["filled_quantity"]), ("0", "0"))

    def test_populated_order_aliases_agree(self):
        result = mapping.project_order(
            {
                "nOrdNo": "1",
                "orderid": "1",
                "qty": "2.0",
                "quantity": 2,
                "ordSt": " Open ",
                "stat": "open",
                "exchOrdId": "E",
                "exOrdId": "E",
                "ordDur": "DAY",
                "vldt": "DAY",
            }
        )
        self.assertEqual(result["quantity"], "2")
        self.assertEqual(result["attempt_state"], "WORKING")
        self.assertEqual(result["status"], " Open ")

    def test_blank_alias_does_not_mask_populated_identity(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "", "orderid": "1"})["orderid"], "1")

    def test_partial_cancel_retains_exposure(self):
        result = mapping.project_order({"nOrdNo": "1", "qty": 100, "fldQty": 40, "ordSt": "cancelled"})
        self.assertEqual(
            (result["quantity"], result["filled_quantity"], result["attempt_state"]), ("100", "40", "CANCELLED")
        )
        self.assertNotIn("position_closed", result)

    def test_trade_projection(self):
        row = UserDict(
            nOrdNo="1",
            fldQty=1,
            qty=0,
            avgPrc="9.39",
            flId="F1",
            exOrdId="E1",
            flDtTm="filled",
            exTm="exchange",
            GuiOrdId="G",
            trdSym="IDEA-EQ",
            sym="IDEA",
        )
        before = dict(row)
        result = mapping.project_trade(row)
        self.assertEqual(
            result,
            {
                "schema_id": mapping.SCHEMA_ID,
                "raw": before,
                "orderid": "1",
                "quantity": "1",
                "price": "9.39",
                "fill_id": "F1",
                "exchange_order_id": "E1",
                "gui_order_id": "G",
                "timestamp": "filled",
                "trading_symbol": "IDEA-EQ",
                "symbol": "IDEA",
            },
        )
        self.assertEqual(row, before)
        self.assertIsNot(result["raw"], row)
        self.assertEqual(result["raw"]["qty"], 0)
        self.assertEqual(result["raw"]["exTm"], "exchange")

    def test_trade_fallbacks(self):
        result = mapping.project_trade({"nOrdNo": "1", "qty": 2, "flPrc": "3.1", "exTm": "t"})
        self.assertEqual((result["quantity"], result["price"], result["timestamp"]), ("2", "3.1", "t"))
        self.assertNotIn("fill_id", result)

    def test_trade_zero_filled_is_not_missing(self):
        result = mapping.project_trade({"nOrdNo": "1", "fldQty": 0, "qty": 7})
        self.assertEqual(result["quantity"], "0")

    def test_trade_missing_optional_values(self):
        self.assertEqual(
            mapping.project_trade({"nOrdNo": "1"}),
            {"schema_id": mapping.SCHEMA_ID, "raw": {"nOrdNo": "1"}, "orderid": "1"},
        )

    def test_history_copies_and_preserves_order_duplicates(self):
        row = UserDict(nOrdNo="1", ordSt="open")
        response = UserDict(data=[row, row])
        result = mapping.history_rows(response)
        self.assertEqual(result, [dict(row), dict(row)])
        self.assertIsNot(result, response["data"])
        self.assertIsNot(result[0], row)
        self.assertIsNot(result[0], result[1])

    def test_history_nested_rows(self):
        row = {"nOrdNo": "1", "ordSt": "complete"}
        self.assertEqual(mapping.history_rows({"data": {"stat": "Ok", "stCode": 200, "data": [row]}}), [row])

    def test_status_complete(self):
        self.assertEqual(mapping.attempt_state("complete"), "FILLED")

    def test_status_traded(self):
        self.assertEqual(mapping.attempt_state(" TRADED "), "FILLED")

    def test_status_cancelled(self):
        self.assertEqual(mapping.attempt_state("Cancelled"), "CANCELLED")

    def test_status_rejected(self):
        self.assertEqual(mapping.attempt_state("rejected"), "REJECTED")

    def test_status_open(self):
        self.assertEqual(mapping.attempt_state(" open "), "WORKING")

    def test_status_cancel_pending(self):
        self.assertEqual(mapping.attempt_state("CANCEL_PENDING"), "CANCEL_PENDING")

    def test_status_cancel_requested(self):
        self.assertEqual(mapping.attempt_state("cancel_requested"), "CANCEL_PENDING")

    def test_status_blank(self):
        self.assertEqual(mapping.attempt_state(""), "UNKNOWN")

    def test_status_none(self):
        self.assertEqual(mapping.attempt_state(None), "UNKNOWN")

    def test_status_bool(self):
        self.assertEqual(mapping.attempt_state(True), "UNKNOWN")

    def test_status_number(self):
        self.assertEqual(mapping.attempt_state(200), "UNKNOWN")

    def test_status_list(self):
        self.assertEqual(mapping.attempt_state([]), "UNKNOWN")

    def test_status_dict(self):
        self.assertEqual(mapping.attempt_state({}), "UNKNOWN")

    def test_status_not_cancelled(self):
        self.assertEqual(mapping.attempt_state("NOT_CANCELLED"), "UNKNOWN")

    def test_status_complete_pending(self):
        self.assertEqual(mapping.attempt_state("COMPLETE_PENDING"), "UNKNOWN")

    def test_status_space_cancel(self):
        self.assertEqual(mapping.attempt_state("cancel pending"), "UNKNOWN")

    def test_status_open_pending(self):
        self.assertEqual(mapping.attempt_state("open pending"), "UNKNOWN")

    def test_status_filled(self):
        self.assertEqual(mapping.attempt_state("filled"), "UNKNOWN")

    def test_order_conflicting_identity(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "orderid": "2"})

    def test_order_conflicting_quantity(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "qty": 1, "quantity": 2})

    def test_order_conflicting_filled(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "fldQty": 1, "filled_quantity": 2})

    def test_order_conflicting_price(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "prc": 1, "price": 2})

    def test_order_conflicting_trigger(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "trgPrc": 1, "trigger_price": 2})

    def test_order_conflicting_average(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "avgPrc": 1, "average_price": 2})

    def test_order_conflicting_status(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "ordSt": "open", "stat": "complete"})

    def test_order_conflicting_exchange_id(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "exOrdId": "1", "exchOrdId": "2"})

    def test_order_conflicting_validity(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "vldt": "DAY", "ordDur": "IOC"})

    def test_project_order_not_mapping(self):
        with self.assertRaises(ValueError):
            mapping.project_order([])

    def test_project_order_missing_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({})

    def test_project_order_blank_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": " "})

    def test_project_order_numeric_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": 123})

    def test_project_order_bool_id(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": True})

    def test_project_order_qty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": -1})

    def test_project_order_qty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": 1.1})

    def test_project_order_qty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": True})

    def test_project_order_qty_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": "NaN"})

    def test_project_order_qty_text(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": "oops"})

    def test_project_order_qty_list(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": []})

    def test_project_order_qty_too_large(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "qty": "1e65"})

    def test_project_order_fldQty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": -1})

    def test_project_order_fldQty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": 1.1})

    def test_project_order_fldQty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": True})

    def test_project_order_fldQty_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": "NaN"})

    def test_project_order_fldQty_text(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": "oops"})

    def test_project_order_fldQty_list(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": []})

    def test_project_order_fldQty_too_large(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "fldQty": "1e65"})

    def test_project_order_blank_optional(self):
        result = mapping.project_order({"nOrdNo": "1", "qty": " ", "fldQty": None})
        self.assertNotIn("quantity", result)
        self.assertNotIn("filled_quantity", result)

    def test_project_trade_not_mapping(self):
        with self.assertRaises(ValueError):
            mapping.project_trade([])

    def test_project_trade_missing_id(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({})

    def test_project_trade_blank_id(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": " "})

    def test_project_trade_numeric_id(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": 123})

    def test_project_trade_bool_id(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": True})

    def test_project_trade_fldQty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": -1})

    def test_project_trade_fldQty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": 1.1})

    def test_project_trade_fldQty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": True})

    def test_project_trade_fldQty_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": "NaN"})

    def test_project_trade_fldQty_text(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": "oops"})

    def test_project_trade_fldQty_list(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": []})

    def test_project_trade_fldQty_too_large(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": "1e65"})

    def test_project_trade_qty_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": -1})

    def test_project_trade_qty_fraction(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": 1.1})

    def test_project_trade_qty_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": True})

    def test_project_trade_qty_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": "NaN"})

    def test_project_trade_qty_text(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": "oops"})

    def test_project_trade_qty_list(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": []})

    def test_project_trade_qty_too_large(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "qty": "1e65"})

    def test_project_trade_blank_optional(self):
        result = mapping.project_trade({"nOrdNo": "1", "qty": " ", "fldQty": None})
        self.assertNotIn("quantity", result)
        self.assertNotIn("filled_quantity", result)

    def test_historical_product_co(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "prod": "CO"})["broker_product"], "CO")

    def test_historical_product_bo(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "prod": "BO"})["broker_product"], "BO")

    def test_historical_product_mtf(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "prod": "MTF"})["broker_product"], "MTF")

    def test_historical_product_future_product(self):
        self.assertEqual(
            mapping.project_order({"nOrdNo": "1", "prod": "FUTURE_PRODUCT"})["broker_product"], "FUTURE_PRODUCT"
        )

    def test_history_empty_direct(self):
        self.assertEqual(mapping.history_rows({"data": []}), [])

    def test_history_empty_success(self):
        self.assertEqual(mapping.history_rows({"stat": "Ok", "stCode": 200, "data": []}), [])

    def test_history_empty_nested(self):
        self.assertEqual(mapping.history_rows({"data": {"data": []}}), [])

    def test_history_rejects_list(self):
        with self.assertRaises(ValueError):
            mapping.history_rows([])

    def test_history_rejects_missing(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({})

    def test_history_rejects_none(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": None})

    def test_history_rejects_string(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": ""})

    def test_history_rejects_mapping(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": {}})

    def test_history_rejects_deep(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": {"data": {"data": []}}})

    def test_history_rejects_row_none(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": [None]})

    def test_history_rejects_row_empty(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": [{}]})

    def test_history_rejects_row_invalid_quantity(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": [{"nOrdNo": "1", "qty": -1}]})

    def test_history_rejects_error(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"error": "failed", "data": []})

    def test_history_rejects_error_caps(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"Error": "failed", "data": []})

    def test_history_rejects_error_message(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"Error Message": "failed", "data": []})

    def test_history_rejects_not_ok(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stat": "Not_Ok", "data": []})

    def test_history_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stat": "weird", "data": []})

    def test_history_rejects_bad_code(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stCode": 400, "data": []})

    def test_history_rejects_string_code(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stCode": "200", "data": []})

    def test_history_rejects_bool_code(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stCode": True, "data": []})

    def test_history_rejects_status_code(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"status_code": 400, "data": []})

    def test_history_rejects_outer_error(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"stat": "Not_Ok", "data": {"stat": "Ok", "data": []}})

    def test_history_rejects_inner_error(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": {"error": "oops", "data": []}})

    def test_project_order_error_row(self):
        with self.assertRaisesRegex(ValueError, "error"):
            mapping.project_order({"nOrdNo": "1", "error": "failed"})

    def test_project_order_nonstring_key(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", 3: "x"})

    def test_project_trade_error_row(self):
        with self.assertRaisesRegex(ValueError, "error"):
            mapping.project_trade({"nOrdNo": "1", "error": "failed"})

    def test_project_trade_nonstring_key(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", 3: "x"})

    def test_trade_placeholder_fill_na(self):
        self.assertNotIn("fill_id", mapping.project_trade({"nOrdNo": "1", "flId": "NA"}))

    def test_trade_placeholder_fill_dash(self):
        self.assertNotIn("fill_id", mapping.project_trade({"nOrdNo": "1", "flId": "--"}))

    def test_trade_conflicting_fill(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_trade({"nOrdNo": "1", "flId": "A", "fill_id": "B"})

    def test_trade_conflicting_exchange(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_trade({"nOrdNo": "1", "exOrdId": "A", "exchOrdId": "B"})

    def test_project_order_prc_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "prc": -1})

    def test_project_order_prc_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "prc": True})

    def test_project_order_prc_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "prc": "Infinity"})

    def test_project_order_prc_precision(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "prc": "0.00000000000000001"})

    def test_project_order_trgPrc_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "trgPrc": -1})

    def test_project_order_trgPrc_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "trgPrc": True})

    def test_project_order_trgPrc_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "trgPrc": "Infinity"})

    def test_project_order_trgPrc_precision(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "trgPrc": "0.00000000000000001"})

    def test_project_order_avgPrc_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "avgPrc": -1})

    def test_project_order_avgPrc_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "avgPrc": True})

    def test_project_order_avgPrc_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "avgPrc": "Infinity"})

    def test_project_order_avgPrc_precision(self):
        with self.assertRaises(ValueError):
            mapping.project_order({"nOrdNo": "1", "avgPrc": "0.00000000000000001"})

    def test_project_trade_avgPrc_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "avgPrc": -1})

    def test_project_trade_avgPrc_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "avgPrc": True})

    def test_project_trade_avgPrc_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "avgPrc": "Infinity"})

    def test_project_trade_avgPrc_precision(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "avgPrc": "0.00000000000000001"})

    def test_project_trade_flPrc_negative(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "flPrc": -1})

    def test_project_trade_flPrc_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "flPrc": True})

    def test_project_trade_flPrc_nonfinite(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "flPrc": "Infinity"})

    def test_project_trade_flPrc_precision(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "flPrc": "0.00000000000000001"})

    def test_order_timestamp_entry(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "ordEntTm": "t"})["timestamp"], "t")

    def test_order_timestamp_fill(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "flDtTm": "t"})["timestamp"], "t")

    def test_order_timestamp_exchange(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "exTm": "t"})["timestamp"], "t")

    def test_order_timestamp_exchange_stamp(self):
        self.assertEqual(mapping.project_order({"nOrdNo": "1", "exchTmstp": "t"})["timestamp"], "t")

    def test_trade_distinct_price_evidence(self):
        result = mapping.project_trade({"nOrdNo": "1", "avgPrc": "3", "flPrc": "4"})
        self.assertEqual(result["price"], "3")
        self.assertEqual(result["raw"]["flPrc"], "4")

    def test_trade_invalid_fallback_not_silently_discarded(self):
        with self.assertRaises(ValueError):
            mapping.project_trade({"nOrdNo": "1", "fldQty": 1, "qty": -1})

    def test_different_unknown_statuses_conflict(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            mapping.project_order({"nOrdNo": "1", "ordSt": "pending", "stat": "other pending"})

    def test_history_second_bad_row_fails_whole_book(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": [{"nOrdNo": "1"}, {"nOrdNo": "2", "qty": -1}]})

    def test_history_error_row(self):
        with self.assertRaises(ValueError):
            mapping.history_rows({"data": [{"nOrdNo": "1", "error": "failed"}]})

    def test_trade_native_placeholder_canonical_fill_identity(self):
        row = {"nOrdNo": "1", "flId": "NA", "fill_id": "F1"}
        result = mapping.project_trade(row)
        self.assertEqual(result["fill_id"], "F1")
        self.assertEqual(result["raw"]["flId"], "NA")
        self.assertEqual(result["raw"]["fill_id"], "F1")

    def test_trade_canonical_placeholder_native_fill_identity(self):
        row = {"nOrdNo": "1", "flId": "F1", "fill_id": "NA"}
        result = mapping.project_trade(row)
        self.assertEqual(result["fill_id"], "F1")
        self.assertEqual(result["raw"]["flId"], "F1")
        self.assertEqual(result["raw"]["fill_id"], "NA")

    def test_trade_valid_fill_time_invalid_exchange_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "exTm must be a nonblank string"):
            mapping.project_trade({"nOrdNo": "1", "flDtTm": "filled", "exTm": 123})

    def test_trade_blank_fill_time_falls_back_to_exchange_time(self):
        row = {"nOrdNo": "1", "flDtTm": " ", "exTm": "exchange"}
        result = mapping.project_trade(row)
        self.assertEqual(result["timestamp"], "exchange")
        self.assertEqual(result["raw"], row)

    def test_trade_null_fill_time_falls_back_to_exchange_time(self):
        row = {"nOrdNo": "1", "flDtTm": None, "exTm": "exchange"}
        result = mapping.project_trade(row)
        self.assertEqual(result["timestamp"], "exchange")
        self.assertEqual(result["raw"], row)


class KotakWriteEvidenceTests(unittest.TestCase):
    def test_ack_and_rejection(self):
        row = {"stat": "Ok", "nOrdNo": "001", "stCode": 200}
        self.assertEqual(
            mapping.project_write_result(row, expected_order_id="001"),
            {
                "schema_id": mapping.SCHEMA_ID,
                "raw": row,
                "order_id": "001",
                "accepted": True,
                "broker_code": 200,
                "reason": None,
                "execution_state": "UNKNOWN",
            },
        )

    def test_empty(self):
        row = {}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_id_only(self):
        row = {"nOrdNo": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_stat_only(self):
        row = {"stat": "Ok"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_code_only(self):
        row = {"stCode": 200}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_missing_id(self):
        row = {"stat": "Ok", "stCode": 200}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_missing_stat(self):
        row = {"nOrdNo": "1", "stCode": 200}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_missing_code(self):
        row = {"stat": "Ok", "nOrdNo": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_http_success(self):
        row = {"status_code": 200, "nOrdNo": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_canonical_id_not_native_ack(self):
        row = {"stat": "Ok", "stCode": 200, "order_id": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_unknown_stat(self):
        row = {"stat": "complete", "stCode": 200, "nOrdNo": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_not_ok(self):
        row = {"stat": "Not_Ok", "nOrdNo": "1"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_backend_rejection(self):
        row = {
            "stCode": 1021,
            "errMsg": "order is completed",
            "stat": "please provide valid order number",
            "status_code": 400,
        }
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_http_bad_request(self):
        row = {"status_code": 400}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_timeout(self):
        row = {"status_code": 504}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_server_error(self):
        row = {"status_code": 500}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_unknown_broker_code(self):
        row = {"stCode": 999}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_nested_ack(self):
        row = {"data": {"stat": "Ok", "stCode": 200, "nOrdNo": "1"}}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], None)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_filled_hint(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "ordSt": "complete", "fldQty": 100}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], True)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_cancelled_hint(self):
        row = {"stat": "Not_Ok", "ordSt": "cancelled"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["execution_state"], "UNKNOWN")
        self.assertEqual(result["raw"], row)

    def test_explicit_Error_string(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error": "denied"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], "denied")
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_mapping(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error": {"message": "denied"}}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], {"message": "denied"})
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_false(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error": False}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], False)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_zero(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error": 0}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], 0)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_empty_list(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error": []}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], [])
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_Message_string(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error Message": "denied"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], "denied")
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_Message_mapping(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error Message": {"message": "denied"}}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], {"message": "denied"})
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_Message_false(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error Message": False}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], False)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_Message_zero(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error Message": 0}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], 0)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_Error_Message_empty_list(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "Error Message": []}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], [])
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_error_string(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": "denied"}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], "denied")
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_error_mapping(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": {"message": "denied"}}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], {"message": "denied"})
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_error_false(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": False}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], False)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_error_zero(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": 0}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], 0)
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_explicit_error_empty_list(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": []}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], False)
        self.assertEqual(result["reason"], [])
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_null_stat(self):
        row = {"stat": None, "stCode": 200, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_bool_stat(self):
        row = {"stat": True, "stCode": 200, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_numeric_stat(self):
        row = {"stat": 200, "stCode": 200, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_string_code(self):
        row = {"stat": "Ok", "stCode": "200", "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_float_code(self):
        row = {"stat": "Ok", "stCode": 200.0, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_bool_code(self):
        row = {"stat": "Ok", "stCode": True, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_null_code(self):
        row = {"stat": "Ok", "stCode": None, "nOrdNo": "1"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_string_http_code(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": "400"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_float_http_code(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": 400.0}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_backend_overrides_ack(self):
        row = {"stat": "Ok", "stCode": 1021, "nOrdNo": "1"}
        self.assertIs(mapping.project_write_result(row)["accepted"], False)

    def test_http_overrides_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": 400}
        self.assertIs(mapping.project_write_result(row)["accepted"], False)

    def test_not_ok_overrides_ack(self):
        row = {"stat": "Not_Ok", "stCode": 200, "nOrdNo": "1"}
        self.assertIs(mapping.project_write_result(row)["accepted"], False)

    def test_invalid_nordno_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": " "})

    def test_invalid_order_id_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": " "})

    def test_invalid_orderid_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": " "})

    def test_invalid_nordno_empty(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": ""})

    def test_invalid_order_id_empty(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": ""})

    def test_invalid_orderid_empty(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": ""})

    def test_invalid_nordno_null(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": None})

    def test_invalid_order_id_null(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": None})

    def test_invalid_orderid_null(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": None})

    def test_invalid_nordno_integer(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": 1})

    def test_invalid_order_id_integer(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": 1})

    def test_invalid_orderid_integer(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": 1})

    def test_invalid_nordno_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": True})

    def test_invalid_order_id_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": True})

    def test_invalid_orderid_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": True})

    def test_invalid_nordno_list(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": []})

    def test_invalid_order_id_list(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": []})

    def test_invalid_orderid_list(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"orderid": []})

    def test_canonical_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "1", "order_id": "2"})

    def test_observation_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "1", "orderid": "2"})

    def test_alias_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": "1", "orderid": "2"})

    def test_whitespace_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "1", "order_id": " 1 "})

    def test_leading_zero_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "01", "order_id": "1"})

    def test_invalid_expected_blank(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({}, expected_order_id=" ")

    def test_invalid_expected_empty(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({}, expected_order_id="")

    def test_invalid_expected_integer(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({}, expected_order_id=1)

    def test_invalid_expected_bool(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({}, expected_order_id=True)

    def test_invalid_expected_list(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({}, expected_order_id=[])

    def test_expected_conflict(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "01"}, expected_order_id="1")

    def test_expected_conflict_rejection(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "2", "error": "denied"}, expected_order_id="1")

    def test_expected_not_synthesized(self):
        result = mapping.project_write_result({}, expected_order_id="1")
        self.assertIsNone(result["order_id"])
        self.assertIsNone(result["accepted"])

    def test_matching_aliases(self):
        row = {"nOrdNo": "01", "order_id": "01", "orderid": "01", "stat": "Ok", "stCode": 200}
        self.assertEqual(mapping.project_write_result(row, expected_order_id="01")["order_id"], "01")

    def test_invalid_response_list(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result([])

    def test_invalid_response_none(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result(None)

    def test_invalid_response_string(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result("ok")

    def test_invalid_response_nonstring_key(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({1: "x"})

    def test_raw_copy_and_input_unchanged(self):
        row = UserDict(stat="Ok", stCode=200, nOrdNo="1", extra={"x": 1})
        before = dict(row)
        result = mapping.project_write_result(row)
        self.assertEqual(row, before)
        self.assertEqual(result["raw"], before)
        self.assertIsNot(result["raw"], row)
        result["raw"]["stat"] = "changed"
        self.assertEqual(row, before)

    def test_reason_and_code_preserved(self):
        row = {"stCode": 1021, "status_code": 400, "errMsg": " order is completed ", "error": "other"}
        result = mapping.project_write_result(row)
        self.assertEqual(result["broker_code"], 1021)
        self.assertEqual(result["reason"], " order is completed ")
        self.assertEqual(result["raw"], row)

    def test_http_code_fallback(self):
        self.assertEqual(mapping.project_write_result({"status_code": 400})["broker_code"], 400)

    def test_unrecognized_code_preserved(self):
        self.assertEqual(mapping.project_write_result({"stCode": "200"})["broker_code"], "200")

    def test_reason_only_unknown(self):
        result = mapping.project_write_result({"reason": "timeout"})
        self.assertEqual(result["reason"], "timeout")
        self.assertIsNone(result["accepted"])

    def test_err_msg_only_unknown(self):
        self.assertIsNone(mapping.project_write_result({"errMsg": "timeout"})["accepted"])

    def test_normalized_stat(self):
        self.assertIs(mapping.project_write_result({"stat": " ok ", "stCode": 200, "nOrdNo": "1"})["accepted"], True)

    def test_normalized_not_ok(self):
        self.assertIs(mapping.project_write_result({"stat": " not_ok "})["accepted"], False)

    def test_identity_preserved_exact(self):
        self.assertEqual(mapping.project_write_result({"nOrdNo": " 01 "})["order_id"], " 01 ")

    def test_empty_error_null(self):
        self.assertIs(
            mapping.project_write_result({"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": None})["accepted"], True
        )

    def test_empty_error_blank(self):
        self.assertIs(
            mapping.project_write_result({"stat": "Ok", "stCode": 200, "nOrdNo": "1", "error": " "})["accepted"], True
        )

    def test_err_msg_blocks_positive_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "errMsg": "unclassified failure"}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_successful_http_code_with_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": 200}
        self.assertIs(mapping.project_write_result(row)["accepted"], True)

    def test_timeout_blocks_positive_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": 504}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_null_http_code_blocks_positive_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": None}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_bool_http_code_blocks_positive_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "status_code": True}
        self.assertIsNone(mapping.project_write_result(row)["accepted"])

    def test_float_backend_rejection_is_unknown(self):
        self.assertIsNone(mapping.project_write_result({"stCode": 1021.0})["accepted"])

    def test_string_backend_rejection_is_unknown(self):
        self.assertIsNone(mapping.project_write_result({"stCode": "1021"})["accepted"])

    def test_error_overrides_malformed_code(self):
        row = {"stCode": "200", "error": "denied"}
        self.assertIs(mapping.project_write_result(row)["accepted"], False)

    def test_expected_whitespace_is_exact(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"nOrdNo": "1"}, expected_order_id=" 1 ")

    def test_expected_canonical_identity_checked(self):
        with self.assertRaises(ValueError):
            mapping.project_write_result({"order_id": "2"}, expected_order_id="1")

    def test_canonical_identity_preserved_without_native(self):
        self.assertEqual(mapping.project_write_result({"order_id": "1"})["order_id"], "1")

    def test_observation_identity_preserved_without_native(self):
        self.assertEqual(mapping.project_write_result({"orderid": "1"})["order_id"], "1")

    def test_error_reason_precedence_keeps_all_raw(self):
        row = {"Error Message": "first", "Error": "second", "error": "third", "reason": "fourth"}
        result = mapping.project_write_result(row)
        self.assertEqual(result["reason"], "first")
        self.assertEqual(result["raw"], row)

    def test_blank_reason_fallback(self):
        row = {"errMsg": " ", "Error Message": None, "Error": "denied"}
        self.assertEqual(mapping.project_write_result(row)["reason"], "denied")

    def test_null_backend_code_preserves_http_in_raw(self):
        result = mapping.project_write_result({"stCode": None, "status_code": 400})
        self.assertIsNone(result["broker_code"])
        self.assertEqual(result["raw"]["status_code"], 400)
        self.assertIs(result["accepted"], False)

    def test_not_ok_substring_is_unknown(self):
        self.assertIsNone(mapping.project_write_result({"stat": "NOT_OK_PENDING"})["accepted"])

    def test_error_stat_alone_unknown(self):
        self.assertIsNone(mapping.project_write_result({"stat": "Error"})["accepted"])

    def test_null_err_msg_allows_complete_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "errMsg": None}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], True)
        self.assertIsNone(result["reason"])
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")

    def test_whitespace_err_msg_allows_complete_ack(self):
        row = {"stat": "Ok", "stCode": 200, "nOrdNo": "1", "errMsg": " \t "}
        result = mapping.project_write_result(row)
        self.assertIs(result["accepted"], True)
        self.assertIsNone(result["reason"])
        self.assertEqual(result["raw"], row)
        self.assertEqual(result["execution_state"], "UNKNOWN")
