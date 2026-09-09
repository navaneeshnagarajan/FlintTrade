"""Contract tests for the dependency-neutral broker read capability."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path
from typing import Literal, get_type_hints

import pytest

from flinttrade_core.account_mutation_contracts import RegistrySelectorVersion
from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.workspace_migrations import BrokerWorkspaceVersion, WorkspaceVersion


EXPECTED_METHODS = (
    "quote",
    "depth",
    "historical",
    "batch_quotes",
    "option_chain",
    "lot_sizes",
    "balance",
    "portfolio_greeks",
    "positions",
    "holdings",
    "margin",
    "order_states",
    "trades",
)


def _contract():
    return importlib.import_module("flinttrade_core.broker_read_port")


def test_broker_read_contract_module_exists() -> None:
    assert importlib.util.find_spec("flinttrade_core.broker_read_port") is not None


def test_closed_domain_public_fields_publish_exact_literal_annotations() -> None:
    contract = _contract()

    assert get_type_hints(contract.MarginRequest)["action"] == Literal["BUY", "SELL"]
    assert get_type_hints(contract.PortfolioPositionRef)["option_type"] == Literal["CE", "PE"]
    assert get_type_hints(contract.OrderStateSnapshot)["order_flag"] == Literal["SINGLE", "OCO"] | None


def test_protocol_exposes_exactly_thirteen_async_fixed_reads() -> None:
    BrokerReadPort = _contract().BrokerReadPort
    methods = tuple(
        name for name, value in BrokerReadPort.__dict__.items() if not name.startswith("_") and inspect.isfunction(value)
    )

    assert methods == EXPECTED_METHODS
    assert all(inspect.iscoroutinefunction(BrokerReadPort.__dict__[name]) for name in methods)
    assert all("target" not in inspect.signature(BrokerReadPort.__dict__[name]).parameters for name in methods)


def test_contract_values_are_frozen_slotted_and_dependency_neutral() -> None:
    contract = _contract()
    BrokerDataRole = contract.BrokerDataRole
    BrokerReadPort = contract.BrokerReadPort
    DataRoleReadTarget = contract.DataRoleReadTarget
    target = DataRoleReadTarget(BrokerDataRole.QUOTE)
    assert is_dataclass(target)
    assert hasattr(type(target), "__slots__")
    assert not hasattr(target, "__dict__")
    with pytest.raises(FrozenInstanceError):
        target.role = BrokerDataRole.HISTORICAL  # type: ignore[misc]

    source = Path(inspect.getfile(BrokerReadPort)).read_text(encoding="utf-8")
    imports = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        name.startswith(("flinttrade_gateway", "flinttrade_engine", "flask")) or "sdk" in name.lower()
        for name in imports
    )


def test_targets_and_requests_reject_non_exact_primitive_shapes() -> None:
    contract = _contract()
    BatchQuoteRequest = contract.BatchQuoteRequest
    DataRoleReadTarget = contract.DataRoleReadTarget
    ExactReadTarget = contract.ExactReadTarget
    HistoricalRequest = contract.HistoricalRequest
    InstrumentRef = contract.InstrumentRef
    LotSizeRequest = contract.LotSizeRequest
    MarginRequest = contract.MarginRequest
    OptionChainRequest = contract.OptionChainRequest
    OrderStateRequest = contract.OrderStateRequest
    PortfolioGreeksRequest = contract.PortfolioGreeksRequest
    QuoteRequest = contract.QuoteRequest
    selector = BrokerSelector("dhan", "acct")
    assert ExactReadTarget(selector).selector is selector
    assert QuoteRequest(InstrumentRef("NIFTY", "NSE", "123")).instrument.symbol == "NIFTY"

    invalid_builders = (
        lambda: DataRoleReadTarget("quote"),
        lambda: ExactReadTarget(object()),
        lambda: InstrumentRef("", "NSE"),
        lambda: InstrumentRef("NIFTY", "NSE", 123),
        lambda: HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "", "2026-01-01", "2026-01-02"),
        lambda: BatchQuoteRequest([InstrumentRef("NIFTY", "NSE")]),
        lambda: OptionChainRequest(InstrumentRef("NIFTY", "NSE"), ""),
        lambda: LotSizeRequest("NSE", ["NIFTY"]),
        lambda: MarginRequest("NIFTY", "NSE", "buy", "1", "MIS", "MARKET", "0", "0"),
        lambda: PortfolioGreeksRequest([]),
        lambda: OrderStateRequest("regular"),
    )
    for build in invalid_builders:
        with pytest.raises(ValueError, match="broker_read_contract_invalid"):
            build()


def test_provenance_requires_complete_nonzero_matching_versions() -> None:
    BrokerReadProvenance = _contract().BrokerReadProvenance
    from uuid import UUID, uuid4

    selector = BrokerSelector("dhan", "acct")
    instance_id = UUID("00000000-0000-4000-8000-000000000001")
    registry = RegistrySelectorVersion(selector, uuid4(), 2, True)
    credential = CredentialVersion(selector, uuid4(), 3)
    provenance = BrokerReadProvenance(
        selector=selector,
        registry_version=registry,
        credential_version=credential,
        workspace_version=WorkspaceVersion(instance_id, 4),
        broker_workspace_version=BrokerWorkspaceVersion(instance_id, 5),
        requested_role=None,
    )
    assert tuple(field.name for field in fields(provenance)) == (
        "selector",
        "registry_version",
        "credential_version",
        "workspace_version",
        "broker_workspace_version",
        "requested_role",
    )

    with pytest.raises(ValueError, match="broker_read_contract_invalid"):
        BrokerReadProvenance(
            selector=selector,
            registry_version=RegistrySelectorVersion(selector, uuid4(), 0, False),
            credential_version=credential,
            workspace_version=WorkspaceVersion(instance_id, 4),
            broker_workspace_version=BrokerWorkspaceVersion(instance_id, 5),
            requested_role=None,
        )


def test_balance_evidence_and_failures_are_closed_typed_values() -> None:
    contract = _contract()
    BalanceEvidence = contract.BalanceEvidence
    BalanceSnapshot = contract.BalanceSnapshot
    BrokerReadErrorCode = contract.BrokerReadErrorCode
    BrokerReadFailure = contract.BrokerReadFailure
    CandleSnapshot = contract.CandleSnapshot
    balance = BalanceSnapshot(
        available_balance=0.0,
        available_balance_evidence=BalanceEvidence.DIRECT,
        used_margin=None,
        used_margin_evidence=None,
        total_balance=0.0,
        total_balance_evidence=BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
        opening_risk_capital=None,
        opening_risk_capital_evidence=None,
    )
    assert balance.available_balance == 0.0
    assert BrokerReadFailure(BrokerReadErrorCode.REVOKED).code is BrokerReadErrorCode.REVOKED
    with pytest.raises(ValueError, match="broker_read_contract_invalid"):
        BalanceSnapshot(True, BalanceEvidence.DIRECT, None, None, None, None, None, None)
    with pytest.raises(ValueError, match="broker_read_contract_invalid"):
        CandleSnapshot("2026-01-01", 1.0, 2.0, 0.5, float("nan"), 10)


def test_malformed_lot_signal_is_an_exact_internal_contract_value() -> None:
    contract = _contract()

    response = contract.BrokerReadResponseInvalid()
    balance = contract.BrokerBalanceResponseInvalid()
    lot = contract.BrokerLotSizeResponseInvalid()

    assert type(response) is contract.BrokerReadResponseInvalid
    assert str(response) == "broker_read_response_invalid"
    assert isinstance(response, contract.BrokerReadContractError)
    assert type(balance) is contract.BrokerBalanceResponseInvalid
    assert isinstance(balance, contract.BrokerReadResponseInvalid)
    assert str(balance) == "broker_balance_response_invalid"
    assert type(lot) is contract.BrokerLotSizeResponseInvalid
    assert isinstance(lot, contract.BrokerReadResponseInvalid)
    assert str(lot) == "broker_lot_size_response_invalid"


def test_order_state_order_flag_requires_an_exact_string_without_executing_hooks() -> None:
    contract = _contract()

    class StringSubclass(str):
        pass

    class HookTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __hash__(self):
            self.calls.append("hash")
            raise AssertionError("order_flag hash hook executed")

        def __eq__(self, _other):
            self.calls.append("eq")
            raise AssertionError("order_flag equality hook executed")

    def build(order_flag):
        return contract.OrderStateSnapshot(
            family=contract.BrokerOrderFamily.FOREVER,
            order_family=None,
            orderid="OID",
            status="PENDING",
            symbol="TCS",
            instrument_id=None,
            exchange="NSE",
            action="BUY",
            product="CNC",
            quantity="1",
            filled_quantity=None,
            pricetype="LIMIT",
            price=None,
            trigger_price=None,
            disclosed_quantity=None,
            option_type=None,
            expiry=None,
            strike_price=None,
            underlying=None,
            safety_order_id=None,
            broker_order_id=None,
            raw_broker_order_id=None,
            parent_order_id=None,
            exchange_order_id=None,
            leg_name=None,
            margin_unfunded=None,
            order_flag=order_flag,
            legs=(),
        )

    with pytest.raises(ValueError, match="broker_read_contract_invalid"):
        build(StringSubclass("SINGLE"))
    trap = HookTrap()
    with pytest.raises(ValueError, match="broker_read_contract_invalid"):
        build(trap)
    assert trap.calls == []
