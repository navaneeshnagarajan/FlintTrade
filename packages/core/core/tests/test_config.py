"""Regression coverage for OpenAlgo endpoint derivation."""

from __future__ import annotations

import pytest

from flinttrade_core.config import Settings, openalgo_ws_base_url


@pytest.mark.unit
def test_openalgo_ws_base_url_maps_https_to_wss_and_uses_workspace_port() -> None:
    settings = Settings(openalgo_host="https://openalgo.local", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "wss://openalgo.local:8770"


@pytest.mark.unit
def test_openalgo_ws_base_url_replaces_rest_port_and_preserves_ipv6_host() -> None:
    settings = Settings(openalgo_host="http://[::1]:5000", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "ws://[::1]:8770"
