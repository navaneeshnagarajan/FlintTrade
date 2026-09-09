"""Tests for the Account Manager's consolidated connection + reauth status."""

from __future__ import annotations


import pytest
from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

# Per-package pytest binds 'tests' locally; load the shared opt-in fixture by path.
import importlib.util as _fixture_import
from pathlib import Path as _FixturePath

_fixture_spec = _fixture_import.spec_from_file_location(
    "_credential_fixtures", _FixturePath(__file__).resolve().parents[4] / "tests" / "credential_fixtures.py",
)
_fixture_module = _fixture_import.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
seed_credentials = _fixture_module.seed_credentials



pytestmark = pytest.mark.unit


class _FakeResp:
    def __init__(self, code: int):
        self.status_code = code


class _FakeHttp:
    """Stand-in for the httpx client used by the OpenAlgo ping."""

    def __init__(self, code: int | None = None, raise_exc: Exception | None = None):
        self.code = code
        self.raise_exc = raise_exc

    def post(self, url, json=None):  # noqa: A002 - mirror httpx signature
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResp(self.code or 200)

    def close(self):
        pass


@pytest.fixture
def mgr(tmp_path):
    from flinttrade_core.secure_file import harden_directory

    harden_directory(tmp_path)
    m = AccountManager(
        db_path=str(tmp_path / "acc.db"), master_password="test-master-pw", mutation_admission=lambda: None,
    )
    seed_credentials(m._cred, "A1", "openalgo", "Acc 1", {"api_key": "k"}, adapter_id="openalgo")
    m.add_account(BrokerAccount(account_id="A1", openalgo_host="http://host:5000", api_key="k", name="Acc 1"))
    yield m
    m.close()


def test_authenticated_when_ping_200(mgr):
    mgr._http = _FakeHttp(code=200)  # noqa: SLF001
    s = mgr.connection_status(mgr.get_account("A1"))
    assert s.connected is True
    assert s.authenticated is True
    assert s.needs_reauth is False


def test_needs_reauth_on_auth_error(mgr):
    mgr._http = _FakeHttp(code=403)  # noqa: SLF001
    s = mgr.connection_status(mgr.get_account("A1"))
    assert s.connected is True  # reachable
    assert s.authenticated is False
    assert s.needs_reauth is True
    assert "403" in s.error


def test_offline_on_connection_error(mgr):
    mgr._http = _FakeHttp(raise_exc=ConnectionError("connection refused"))  # noqa: SLF001
    s = mgr.connection_status(mgr.get_account("A1"))
    assert s.connected is False
    assert s.needs_reauth is True
    assert s.error == "OpenAlgo connection failed"
    assert "refused" not in s.error


def test_account_status_all(mgr):
    mgr._http = _FakeHttp(code=200)  # noqa: SLF001
    statuses = mgr.account_status_all()
    assert len(statuses) == 1
    assert statuses[0].account_id == "A1"
    assert statuses[0].authenticated is True
    # serialisable for the route
    assert statuses[0].to_dict()["needs_reauth"] is False
