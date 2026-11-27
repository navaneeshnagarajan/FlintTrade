"""Normal write-capable factory with real safety/client owners and inert external HTTP.

The explicit synthetic default selects an account; only CONNECT can register it.
No readiness field, session receipt or gate verdict is supplied by this fixture.
"""
from __future__ import annotations
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
import json
import pytest
from flinttrade_core.auth_routes import _create_token
from flinttrade_core.workspace_migrations import compare_and_swap_workspace
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk

@pytest.fixture
def mounted_desk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory: Callable[[], Any],
    owned_flask_apps: Any,
) -> Iterator[MountedDesk]:
    """Use the normal factory with genuine disposable account custody.

    Explicit CONNECT uses the normal account owner and installed SDK with inert
    profile/trade HTTP. No real account, master read, model or financial I/O is
    permitted; no pre-populated registry is adopted by the factory.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.

    Yields:
        The real mounted desk until its existing factory owners are drained.
    """
    from datetime import datetime, timedelta
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    import requests

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.secure_file import harden_directory

    harden_directory(tmp_path)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)

    def configure(value: dict[str, Any]) -> None:
        value["brokers"]["execution"] = {"default": "dhan:Mounted"}
        value["brokers"]["account_acls"] = {
            "dhan": {"Mounted": ["mounted-operator", "bounded:mounted-native"]},
        }

    compare_and_swap_workspace(tmp_path, None, configure)
    calls: list[str] = []
    expiry = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)

    class Transport:
        """Only external HTTP is inert; login, SDK and adapter remain real."""

        def __init__(self) -> None:
            self.before_read: Callable[[], None] = lambda: None
            self.authentication_calls: list[str] = []

        def send(self, request: requests.PreparedRequest) -> requests.Response:
            """Supply separately labelled profile and daily-trade observations."""
            assert request.method == "GET"
            if request.url == "https://api.dhan.co/v2/profile":
                self.authentication_calls.append(request.url)
                data: Any = {"dhanClientId": "Mounted", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
            else:
                assert request.url == "https://api.dhan.co/v2/trades/"
                calls.append("trades")
                self.before_read()
                data = []
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(data).encode()
            return response

    transport = Transport()

    def send(_session: requests.Session, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        return transport.send(request)

    monkeypatch.setattr(requests.Session, "send", send)
    import asyncio
    from flinttrade_core.broker_client import BrokerClient
    from flinttrade_core.safety_config import load_workspace_safety_config
    from flinttrade_engine.safety import SafetySystem

    client_owner = BrokerClient()
    safety = SafetySystem(load_workspace_safety_config(tmp_path),
                          reservation_db_path=tmp_path / "order_exposure_reservations.sqlite")

    async def bind_safety() -> None:
        safety.bind_runtime_loop(asyncio.get_running_loop())

    client_owner.run_sync(bind_safety())
    app = create_flask_app(backend_lease_proof=backend_lease_factory(), client=client_owner, safety=safety)
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].setup_account("mounted-operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = _create_token("mounted-operator", mode="live", live_mode_unlocked=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer " + token}
    try:
        connected = client.post("/api/v1/native/accounts", json={
            "adapter_id": "dhan", "account_id": "Mounted",
            "credentials": {"client_id": "Mounted", "access_token": "synthetic-access"},
        }, headers={**headers, "Idempotency-Key": str(uuid4())})
        assert connected.status_code == 200, connected.get_json()
        assert connected.get_json()["receipt"]["state"] == "committed"
        assert transport.authentication_calls == ["https://api.dhan.co/v2/profile"]
        assert calls == []
        from flinttrade_core.app import _configure_broker_writes

        # Exercise the existing desktop runtime publication operation against
        # the SAME account owner's dependencies. No dependency or router is injected.
        assert _configure_broker_writes(app, app.extensions["flinttrade_broker_dependencies"])
        assert app.config["BROKER_ROUTER"] is not None
        yield MountedDesk(app, client, headers, calls, transport)
    finally:
        owned_flask_apps.close()
        client_owner.close_sync()
