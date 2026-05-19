"""Tests for IPWhitelist — per-user IP restrictions with CIDR support.

Run with:
    python -m pytest packages/core/tests/test_ip_whitelist.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest

from packages.core.src.ip_whitelist import IPWhitelist, _parse_network


# ---------------------------------------------------------------------------
# _parse_network helper
# ---------------------------------------------------------------------------


class TestParseNetwork:
    def test_single_ipv4(self):
        net = _parse_network("10.0.0.1")
        assert str(net) == "10.0.0.1/32"

    def test_cidr_ipv4(self):
        net = _parse_network("192.168.0.0/24")
        assert net.prefixlen == 24

    def test_host_in_cidr_normalised(self):
        # strict=False — 192.168.0.5/24 normalises to 192.168.0.0/24
        net = _parse_network("192.168.0.5/24")
        assert str(net) == "192.168.0.0/24"

    def test_ipv6_address(self):
        net = _parse_network("::1")
        assert net.prefixlen == 128

    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid IP"):
            _parse_network("not-an-ip")

    def test_whitespace_stripped(self):
        net = _parse_network("  10.0.0.1  ")
        assert str(net) == "10.0.0.1/32"


# ---------------------------------------------------------------------------
# add_ip / list_ips
# ---------------------------------------------------------------------------


class TestAddIp:
    def _wl(self) -> IPWhitelist:
        return IPWhitelist()

    def test_add_single_ip(self):
        wl = self._wl()
        wl.add_ip("alice", "10.0.0.1", label="Home")
        ips = wl.list_ips("alice")
        assert len(ips) == 1
        assert ips[0]["ip"] == "10.0.0.1"
        assert ips[0]["label"] == "Home"

    def test_add_cidr(self):
        wl = self._wl()
        wl.add_ip("alice", "192.168.1.0/24", label="LAN")
        assert len(wl.list_ips("alice")) == 1

    def test_add_is_idempotent(self):
        wl = self._wl()
        wl.add_ip("alice", "10.0.0.1")
        wl.add_ip("alice", "10.0.0.1")
        assert len(wl.list_ips("alice")) == 1

    def test_add_invalid_ip_raises(self):
        wl = self._wl()
        with pytest.raises(ValueError):
            wl.add_ip("alice", "bad-ip")

    def test_multiple_users_isolated(self):
        wl = self._wl()
        wl.add_ip("alice", "10.0.0.1")
        wl.add_ip("bob", "10.0.0.2")
        assert len(wl.list_ips("alice")) == 1
        assert len(wl.list_ips("bob")) == 1
        assert wl.list_ips("alice")[0]["ip"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# remove_ip
# ---------------------------------------------------------------------------


class TestRemoveIp:
    def test_remove_existing(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        removed = wl.remove_ip("alice", "10.0.0.1")
        assert removed is True
        assert wl.list_ips("alice") == []

    def test_remove_nonexistent_returns_false(self):
        wl = IPWhitelist()
        removed = wl.remove_ip("alice", "10.0.0.1")
        assert removed is False

    def test_remove_unknown_user_returns_false(self):
        wl = IPWhitelist()
        removed = wl.remove_ip("nobody", "10.0.0.1")
        assert removed is False


# ---------------------------------------------------------------------------
# is_whitelisted
# ---------------------------------------------------------------------------


class TestIsWhitelisted:
    def test_disabled_whitelist_allows_all(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        # whitelist is disabled by default
        assert wl.is_whitelisted("alice", "8.8.8.8") is True

    def test_empty_whitelist_allows_all(self):
        wl = IPWhitelist()
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "8.8.8.8") is True

    def test_enabled_whitelist_blocks_foreign_ip(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "8.8.8.8") is False

    def test_enabled_whitelist_allows_listed_ip(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "10.0.0.1") is True

    def test_cidr_match(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "192.168.1.0/24")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "192.168.1.100") is True
        assert wl.is_whitelisted("alice", "192.168.2.1") is False

    def test_unknown_user_allows_all(self):
        wl = IPWhitelist()
        assert wl.is_whitelisted("nobody", "1.2.3.4") is True

    def test_invalid_ip_returns_false_when_enabled(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "not-valid") is False


# ---------------------------------------------------------------------------
# enable / disable / is_enabled
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_default_is_disabled(self):
        wl = IPWhitelist()
        assert wl.is_enabled("alice") is False

    def test_enable_sets_flag(self):
        wl = IPWhitelist()
        wl.enable("alice")
        assert wl.is_enabled("alice") is True

    def test_disable_clears_flag(self):
        wl = IPWhitelist()
        wl.enable("alice")
        wl.disable("alice")
        assert wl.is_enabled("alice") is False

    def test_disable_makes_everything_allowed(self):
        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.1")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "8.8.8.8") is False
        wl.disable("alice")
        assert wl.is_whitelisted("alice", "8.8.8.8") is True
