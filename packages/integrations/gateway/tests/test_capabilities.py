"""Tests for the BrokerCapabilities and CapabilityRegistry.

Covers:
- Default registry contains all 11 seeded brokers
- Field defaults (all booleans False, rate limits positive)
- Individual broker capability spot-checks
- register() adds / overwrites entries
- get() returns correct entry or None
- all() returns sorted list
- broker_names() returns sorted list
- Custom registry is independent of module-level REGISTRY
"""

from __future__ import annotations


from flinttrade_gateway.capabilities import BrokerCapabilities, CapabilityRegistry, REGISTRY


# ---------------------------------------------------------------------------
# BrokerCapabilities dataclass
# ---------------------------------------------------------------------------


def test_capabilities_defaults_are_false() -> None:
    """A minimally-constructed BrokerCapabilities has all booleans False."""
    caps = BrokerCapabilities(broker_name="test_broker")
    bool_fields = [
        "supports_market_orders",
        "supports_limit_orders",
        "supports_sl_orders",
        "supports_sl_m_orders",
        "supports_bracket_orders",
        "supports_cover_orders",
        "supports_basket_orders",
        "supports_options",
        "supports_futures",
        "supports_commodities",
        "supports_currency",
        "supports_equity",
        "supports_mis",
        "supports_cnc",
        "supports_nrml",
        "supports_websocket",
        "supports_multi_quote",
        "supports_multi_option_greeks",
    ]
    for f in bool_fields:
        assert getattr(caps, f) is False, f"Expected {f} to default to False"


def test_capabilities_rate_limit_defaults_positive() -> None:
    """Default rate limits are positive integers."""
    caps = BrokerCapabilities(broker_name="test_broker")
    assert caps.order_rate_limit_per_sec > 0
    assert caps.quote_rate_limit_per_sec > 0


def test_capabilities_broker_name_stored() -> None:
    """broker_name is stored correctly."""
    caps = BrokerCapabilities(broker_name="my_broker")
    assert caps.broker_name == "my_broker"


# ---------------------------------------------------------------------------
# CapabilityRegistry — basic operations
# ---------------------------------------------------------------------------


def test_registry_register_and_get() -> None:
    """register() adds an entry that get() can retrieve."""
    reg = CapabilityRegistry()
    caps = BrokerCapabilities(broker_name="broker_x", supports_equity=True)
    reg.register(caps)
    result = reg.get("broker_x")
    assert result is not None
    assert result.supports_equity is True


def test_registry_get_unknown_returns_none() -> None:
    """get() returns None for an unregistered broker."""
    reg = CapabilityRegistry()
    assert reg.get("unknown_broker") is None


def test_registry_all_returns_sorted_list() -> None:
    """all() returns entries sorted by broker_name."""
    reg = CapabilityRegistry()
    reg.register(BrokerCapabilities(broker_name="zebra"))
    reg.register(BrokerCapabilities(broker_name="alpha"))
    names = [c.broker_name for c in reg.all()]
    assert names == sorted(names)


def test_registry_broker_names_sorted() -> None:
    """broker_names() returns a sorted list."""
    reg = CapabilityRegistry()
    reg.register(BrokerCapabilities(broker_name="z_broker"))
    reg.register(BrokerCapabilities(broker_name="a_broker"))
    names = reg.broker_names()
    assert names == sorted(names)


def test_registry_register_overwrites_existing() -> None:
    """Registering the same broker_name twice replaces the first entry."""
    reg = CapabilityRegistry()
    reg.register(BrokerCapabilities(broker_name="broker_a", supports_equity=False))
    reg.register(BrokerCapabilities(broker_name="broker_a", supports_equity=True))
    assert reg.get("broker_a").supports_equity is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Default REGISTRY — seeded broker spot-checks
# ---------------------------------------------------------------------------


def test_default_registry_contains_11_brokers() -> None:
    """The default REGISTRY contains exactly 11 seeded brokers."""
    assert len(REGISTRY.all()) == 11


def test_default_registry_zerodha_websocket() -> None:
    """Zerodha supports WebSocket in the default registry."""
    caps = REGISTRY.get("zerodha")
    assert caps is not None
    assert caps.supports_websocket is True


def test_default_registry_zerodha_has_bracket_orders() -> None:
    """Zerodha supports bracket orders."""
    caps = REGISTRY.get("zerodha")
    assert caps is not None
    assert caps.supports_bracket_orders is True


def test_default_registry_iifl_no_websocket() -> None:
    """IIFL does not support WebSocket in the default registry."""
    caps = REGISTRY.get("iifl")
    assert caps is not None
    assert caps.supports_websocket is False


def test_default_registry_angel_multi_option_greeks() -> None:
    """Angel One supports multi-option greeks."""
    caps = REGISTRY.get("angel")
    assert caps is not None
    assert caps.supports_multi_option_greeks is True


def test_default_registry_dhan_present() -> None:
    """Dhan is present in the default registry."""
    assert REGISTRY.get("dhan") is not None


def test_default_registry_shoonya_websocket() -> None:
    """Shoonya supports WebSocket."""
    caps = REGISTRY.get("shoonya")
    assert caps is not None
    assert caps.supports_websocket is True


def test_default_registry_all_have_positive_rate_limits() -> None:
    """All seeded brokers have positive order and quote rate limits."""
    for caps in REGISTRY.all():
        assert caps.order_rate_limit_per_sec > 0, caps.broker_name
        assert caps.quote_rate_limit_per_sec > 0, caps.broker_name


def test_custom_registry_independent_of_module_registry() -> None:
    """A new CapabilityRegistry instance is empty and independent of REGISTRY."""
    reg = CapabilityRegistry()
    assert len(reg.all()) == 0
    assert reg.get("zerodha") is None


def test_native_registry_flags_match_adapter_capabilities() -> None:
    """The BrokerCapabilities registry (served by GET /broker/capabilities) must
    agree with the authoritative per-adapter Capabilities (which feed the
    recommendation engine) on bracket/cover support.

    They diverged for Dhan: the registry said False while the adapter places
    bracket/cover natively via super_order. This tripwire fails if any native
    broker present in BOTH systems disagrees again.
    """
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES
    from flinttrade_gateway.brokers.kotakneo import KOTAKNEO_CAPABILITIES
    from flinttrade_gateway.brokers.upstox import UPSTOX_CAPABILITIES

    natives = {
        "dhan": DHAN_CAPABILITIES,
        "upstox": UPSTOX_CAPABILITIES,
        "kotakneo": KOTAKNEO_CAPABILITIES,
    }
    checked = 0
    for name, adapter_caps in natives.items():
        reg_caps = REGISTRY.get(name)
        if reg_caps is None:
            continue  # not every native is seeded into the registry (e.g. kotakneo)
        checked += 1
        assert reg_caps.supports_bracket_orders == adapter_caps.bracket_order_native, name
        assert reg_caps.supports_cover_orders == adapter_caps.cover_order_native, name
    assert checked >= 2  # dhan + upstox are both seeded; guard the loop ran
