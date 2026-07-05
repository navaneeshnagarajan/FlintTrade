"""Public gateway package surface regression tests."""

from __future__ import annotations

import importlib
import inspect

import pytest

import flinttrade_gateway
from flinttrade_core.models import Fund, Order, OrderResponse, Position, Quote
from flinttrade_gateway.brokers._base import BrokerAdapter
from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter
from flinttrade_gateway.registry import BrokerRegistry


_WRITE_METHODS = (
    "place_order",
    "modify_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "place_options_order",
)


def test_package_root_exports_only_canonical_broker_surfaces() -> None:
    """Root imports must resolve to the live registry/adapter/core-model stack."""
    assert flinttrade_gateway.BrokerRegistry is BrokerRegistry
    assert flinttrade_gateway.BrokerAdapter is BrokerAdapter
    assert flinttrade_gateway.OpenAlgoAdapter is OpenAlgoAdapter
    assert flinttrade_gateway.Order is Order
    assert flinttrade_gateway.OrderResponse is OrderResponse
    assert flinttrade_gateway.Position is Position
    assert flinttrade_gateway.Quote is Quote
    assert flinttrade_gateway.Fund is Fund


def test_package_root_does_not_export_legacy_sync_broker_stack() -> None:
    """The old sync OpenAlgoBroker path bypassed the router-token invariant."""
    removed = {
        "BrokerInterface",
        "OpenAlgoBroker",
        "OrderRequest",
        "FundsInfo",
        "BrokerCredentials",
        "AuthResult",
    }
    assert not removed.intersection(flinttrade_gateway.__all__)
    for name in removed:
        assert not hasattr(flinttrade_gateway, name)


def test_broker_interface_module_is_retired() -> None:
    """The duplicate module must not remain importable beside the live stack."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("flinttrade_gateway.broker_interface")


def test_public_openalgo_adapter_is_async_and_router_guarded() -> None:
    """The package-level OpenAlgo surface is the async BrokerAdapter, not a sync shim."""
    adapter = flinttrade_gateway.OpenAlgoAdapter()
    assert isinstance(adapter, BrokerAdapter)
    assert inspect.iscoroutinefunction(adapter.place_order)
    assert "_router_token" in inspect.signature(adapter.place_order).parameters


def test_public_registry_exposes_no_order_write_methods() -> None:
    """Root-exported BrokerRegistry must stay a pure resolver/read surface."""
    leaked = [name for name in _WRITE_METHODS if hasattr(flinttrade_gateway.BrokerRegistry, name)]
    assert not leaked
