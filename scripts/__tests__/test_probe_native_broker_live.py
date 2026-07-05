from __future__ import annotations

import asyncio

from scripts import probe_native_broker_live as probe
from scripts import probe_kotakneo_live as kotak_wrapper


class _FakeAdapter:
    def __init__(self) -> None:
        self.credentials: dict[str, str] | None = None
        self.logged_out = False
        self.calls: list[tuple] = []

    async def login(self, credentials: dict[str, str]) -> object:
        self.credentials = credentials
        return object()

    async def logout(self, _session: object) -> None:
        self.logged_out = True

    async def user_profile(self, _session: object) -> dict:
        return {"secret": "SHOULD_NOT_PRINT"}

    async def profile(self, _session: object) -> dict:
        return {"secret": "SHOULD_NOT_PRINT"}

    async def funds(self, _session: object) -> dict:
        return {"available_cash": 1000}

    async def limits(self, _session: object) -> dict:
        self.calls.append(("limits",))
        return {"available_cash": 1000}

    async def positions(self, _session: object) -> list:
        return []

    async def holdings(self, _session: object) -> list:
        return [{"symbol": "SECRET"}]

    async def order_book(self, _session: object) -> list:
        return []

    async def trade_book(self, _session: object) -> list:
        return []

    async def scrip_master(self, _session: object, exchange: str | None = None) -> dict:
        self.calls.append(("scrip_master", exchange))
        return {"segments": [exchange]}

    async def search_scrip(self, _session: object, symbol: str, exchange: str = "NSE", **_kwargs: object) -> list:
        self.calls.append(("search_scrip", symbol, exchange))
        return [{"symbol": symbol, "exchange": exchange, "token": "12345"}]

    async def quotes(self, _session: object, symbols: list[str]) -> list:
        self.calls.append(("quotes", tuple(symbols)))
        return [{"symbol": symbols[0]}]

    async def quote_details(self, _session: object, symbols: list[str], quote_type: str = "all") -> list:
        self.calls.append(("quote_details", tuple(symbols), quote_type))
        return [{"symbol": symbols[0], "type": quote_type}]

    async def market_depth(self, _session: object, symbols: list[str]) -> list:
        self.calls.append(("market_depth", tuple(symbols)))
        return [{"symbol": symbols[0], "bids": [], "asks": []}]

    async def margin_calculator(self, _session: object, order: object) -> dict:
        self.calls.append(("margin", getattr(order, "symbol", ""), getattr(order, "exchange", "")))
        return {"required_margin": 1}

    async def historical(self, _session: object, req: dict) -> dict:
        self.calls.append(("history", req.get("symbol"), req.get("exchange"), req.get("interval")))
        return {"bars": []}

    async def expiry_list(self, _session: object, symbol: str, exchange: str) -> list:
        self.calls.append(("expiry", symbol, exchange))
        return ["2026-07-30"]

    async def option_chain(self, _session: object, req: dict) -> dict:
        self.calls.append(("optionchain", req.get("underlying"), req.get("exchange")))
        return {"strikes": []}

    async def option_greeks(self, _session: object, symbols: list[str]) -> list:
        self.calls.append(("optiongreeks", tuple(symbols)))
        return []

    async def search_instruments(self, _session: object, query: str) -> list:
        self.calls.append(("search", query))
        return [{"symbol": query}]

    async def market_timings(self, _session: object, timing_date: str) -> list:
        self.calls.append(("timings", timing_date))
        return []

    async def market_holidays(self, _session: object, date: str | None = None) -> list:
        self.calls.append(("holidays", date))
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


def test_kotak_probe_prompts_for_docs_token_once() -> None:
    fields = probe.CREDENTIAL_FIELDS["kotakneo"]["totp_mpin"]

    assert [field.name for field in fields] == [
        "access_token",
        "mobile_number",
        "ucc",
        "totp",
        "mpin",
        "neo_fin_key",
    ]
    assert fields[0].required is True
    assert fields[-1].required is False
    assert "consumer_key" not in {field.name for field in fields}


def test_resolve_reads_is_broker_specific() -> None:
    assert "market_depth" not in probe._resolve_reads("dhan", ["all"])
    assert "depth" in probe._resolve_reads("dhan", ["default"])
    assert "quotes" in probe._resolve_reads("groww", ["default"])
    assert "search" in probe._resolve_reads("upstox", ["default"])
    assert "optiongreeks" in probe._resolve_reads("upstox", ["all"])
    assert "market_depth" in probe._resolve_reads("kotakneo", ["all"])
    assert "quote_details" in probe._resolve_reads("kotakneo", ["default"])


def test_upstox_default_probe_exercises_market_and_calendar_reads(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["upstox-test-token", "upstox-user"])
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "upstox", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("upstox", "access_token", ["default"]))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.credentials == {"access_token": "upstox-test-token", "client_id": "upstox-user"}
    assert ("quotes", ("NSE:RELIANCE",)) in fake.calls
    assert ("market_depth", ("NSE:RELIANCE",)) in fake.calls
    assert ("margin", "RELIANCE", "NSE") in fake.calls
    assert ("history", "RELIANCE", "NSE", "1d") in fake.calls
    assert ("search", "RELIANCE") in fake.calls
    assert any(call[0] == "timings" for call in fake.calls)
    assert ("holidays", None) in fake.calls
    assert "quotes: ok rows=1" in out
    assert "depth: ok rows=1" in out
    assert "history: ok object_keys=1" in out
    assert "upstox-test-token" not in out
    assert "upstox-user" not in out


def test_kotak_default_probe_exercises_extended_reads(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["kotak-test-token", "+910000000000", "demo-ucc", "000000", "111111", ""])
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "kotakneo", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("kotakneo", "totp_mpin", ["default"]))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.credentials == {
        "environment": "prod",
        "access_token": "kotak-test-token",
        "mobile_number": "+910000000000",
        "ucc": "demo-ucc",
        "totp": "000000",
        "mpin": "111111",
    }
    assert ("limits",) in fake.calls
    assert ("margin", "RELIANCE", "NSE") in fake.calls
    assert ("scrip_master", "NSE") in fake.calls
    assert ("search_scrip", "RELIANCE", "NSE") in fake.calls
    assert ("quotes", ("NSE:RELIANCE",)) in fake.calls
    assert ("quote_details", ("NSE:RELIANCE",), "ltp") in fake.calls
    assert ("market_depth", ("NSE:RELIANCE",)) in fake.calls
    assert "limits: ok object_keys=1" in out
    assert "market_depth: ok rows=1" in out
    assert "kotak-test-token" not in out
    assert "+910000000000" not in out


def test_run_probe_dispatches_groww_access_token_reads(monkeypatch, capsys) -> None:
    fake = _FakeAdapter()
    values = iter(["groww-test-token", "groww-user"])
    monkeypatch.setitem(probe.ADAPTER_FACTORIES, "groww", lambda: fake)
    monkeypatch.setattr("scripts.probe_native_broker_live.getpass.getpass", lambda _prompt: next(values))

    code = asyncio.run(probe.run_probe("groww", "access_token", ["profile", "funds", "orders"]))

    out = capsys.readouterr().out
    assert code == 0
    assert fake.credentials == {"access_token": "groww-test-token", "user_id": "groww-user"}
    assert fake.logged_out is False
    assert "profile: ok object_keys=1" in out
    assert "funds: ok object_keys=1" in out
    assert "orders: ok rows=0" in out
    assert "logout: skipped" in out
    assert "groww-test-token" not in out
    assert "groww-user" not in out


def test_kotak_wrapper_help_is_kotak_specific(capsys) -> None:
    try:
        kotak_wrapper.parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - argparse always exits on --help
        raise AssertionError("--help should exit")

    out = capsys.readouterr().out
    assert "Read-only Kotak Neo native adapter probe" in out
    assert "market_depth" in out
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
