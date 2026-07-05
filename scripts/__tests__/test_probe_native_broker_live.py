from __future__ import annotations

import asyncio

from scripts import probe_native_broker_live as probe
from scripts import probe_kotakneo_live as kotak_wrapper


class _FakeAdapter:
    def __init__(self) -> None:
        self.credentials: dict[str, str] | None = None
        self.logged_out = False

    async def login(self, credentials: dict[str, str]) -> object:
        self.credentials = credentials
        return object()

    async def logout(self, _session: object) -> None:
        self.logged_out = True

    async def user_profile(self, _session: object) -> dict:
        return {"secret": "SHOULD_NOT_PRINT"}

    async def funds(self, _session: object) -> dict:
        return {"available_cash": 1000}

    async def positions(self, _session: object) -> list:
        return []

    async def holdings(self, _session: object) -> list:
        return [{"symbol": "SECRET"}]

    async def order_book(self, _session: object) -> list:
        return []

    async def trade_book(self, _session: object) -> list:
        return []


def test_redact_removes_secret_and_account_like_values() -> None:
    raw = (
        "consumer_key=abcdef1234567890TOKEN mobile_number=9876543210 "
        "ucc=AB12C3 access_token=eyJabc.def.ghi ip=203.0.113.9 "
        "email=n@example.com redirect_uri=https://localhost/callback"
    )

    redacted = probe.redact(raw)

    assert "abcdef" not in redacted
    assert "9876543210" not in redacted
    assert "AB12C3" not in redacted
    assert "eyJabc" not in redacted
    assert "203.0.113.9" not in redacted
    assert "n@example.com" not in redacted
    assert "localhost" not in redacted


def test_redact_removes_camel_case_broker_payload_fields() -> None:
    raw = (
        "{'accessToken': 'shortTok', 'clientId': 'AB1234', 'apiSecret': 'tinySecret', "
        "'tokenId': 'oneTimeCode', 'redirectUri': 'http://127.0.0.1:5100/callback'}"
    )

    redacted = probe.redact(raw)

    assert "shortTok" not in redacted
    assert "AB1234" not in redacted
    assert "tinySecret" not in redacted
    assert "oneTimeCode" not in redacted
    assert "127.0.0.1" not in redacted
    assert "accessToken" in redacted
    assert "clientId" in redacted
    assert "[redacted]'" not in redacted


def test_redact_removes_bearer_authorization_headers() -> None:
    redacted = probe.redact("Authorization: Bearer short.token-value")

    assert "short.token-value" not in redacted
    assert "Bearer [redacted]" in redacted


def test_summarise_payload_reports_shape_only() -> None:
    assert probe.summarise_payload([{"order_id": "SECRET"}]) == "ok rows=1"
    assert probe.summarise_payload({"available_cash": 1000, "account": "SECRET"}) == "ok object_keys=2"
    assert probe.summarise_payload(None) == "ok empty"


def test_run_probe_cancels_before_login_without_traceback(monkeypatch, capsys) -> None:
    def _raise_eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", _raise_eof)

    code = asyncio.run(probe.run_probe("kotakneo", read_names=["funds"]))

    assert code == 130
    assert "probe: cancelled before login" in capsys.readouterr().out


def test_run_probe_dispatches_dhan_profile_and_common_reads(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["CLIENT1", "TOKEN1"])
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "dhan", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("dhan", "access_token", ["profile", "funds"]))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.credentials == {"client_id": "CLIENT1", "access_token": "TOKEN1"}
    assert fake.logged_out is False
    assert "profile: ok object_keys=1" in out
    assert "funds: ok object_keys=1" in out
    assert "logout: skipped" in out
    assert "TOKEN1" not in out


def test_run_probe_logout_is_explicit_opt_in(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["CLIENT1", "TOKEN1"])
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "dhan", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("dhan", "access_token", ["funds"], logout=True))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.logged_out is True
    assert "logout: ok" in out


def test_run_probe_keeps_session_on_service_window_read_error(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["TOKEN1", ""])

    async def _service_window(_session: object) -> dict:
        raise Exception(
            "The Funds service is accessible from 5:30 AM to 12:00 AM IST daily. "
            "Please try again during these service hours."
        )

    fake.funds = _service_window  # type: ignore[method-assign]
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "upstox", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("upstox", "access_token", ["funds", "positions"]))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.credentials == {"access_token": "TOKEN1"}
    assert fake.logged_out is False
    assert "funds: inconclusive" in out
    assert "service hours" in out
    assert "positions: ok rows=0" in out
    assert "logout: skipped" in out
    assert "TOKEN1" not in out


def test_kotak_wrapper_help_is_kotak_specific(capsys) -> None:
    try:
        kotak_wrapper.parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - argparse always exits on --help
        raise AssertionError("--help should exit")

    out = capsys.readouterr().out
    assert "Read-only Kotak Neo native adapter probe" in out
    assert "{dhan,indmoney,kotakneo,upstox}" not in out


def test_kotak_wrapper_dispatches_to_shared_probe(monkeypatch) -> None:
    calls: list[tuple[str, str | None, list[str] | None, str, bool]] = []

    async def _fake_run_probe(
        broker: str,
        method: str | None = None,
        read_names: list[str] | None = None,
        environment: str = "prod",
        *,
        logout: bool = False,
    ) -> int:
        calls.append((broker, method, read_names, environment, logout))
        return 0

    monkeypatch.setattr(kotak_wrapper, "run_probe", _fake_run_probe)

    code = kotak_wrapper.main(["--environment", "uat", "--reads", "funds", "orders", "--logout"])

    assert code == 0
    assert calls == [("kotakneo", "totp_mpin", ["funds", "orders"], "uat", True)]
