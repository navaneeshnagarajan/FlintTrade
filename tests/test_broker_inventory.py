"""The declared implemented brokers must mirror the runtime catalogue, not readiness."""

from pathlib import Path
import tomllib

import pytest

from flinttrade_gateway.adapter import BROKER_CATALOG

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_declared_native_brokers_match_catalogue_names_without_duplicates():
    """Keep the public configuration's implemented list complete and exactly named."""
    declared = tomllib.loads((ROOT / "flint.toml").read_text(encoding="utf-8"))["brokers"]["supported"]
    native_names = {info.display_name for info in BROKER_CATALOG.values() if info.native}

    assert len(declared) == len(set(declared))
    assert set(declared) == native_names


@pytest.mark.unit
def test_implemented_inventory_does_not_promote_delta_connectability():
    """Implementation presence leaves the independent broker safety blockers intact."""
    delta = BROKER_CATALOG["deltaexchange"]

    assert delta.native is True
    assert delta.connectable is False
    assert delta.native_connect_blockers
