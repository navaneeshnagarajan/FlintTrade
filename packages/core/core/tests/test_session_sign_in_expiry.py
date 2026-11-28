"""Sign-in expiry at 08:00 IST, and grants that would outlast the session."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flinttrade_core.auth_routes import (
    SESSION_EXPIRES_SOON_CODE,
    SESSION_EXPIRES_SOON_MESSAGE,
    _create_token,
    _session_expiry,
    decode_token,
)
from packages.core.core.tests.test_native_autonomy import URL, armed
from packages.core.core.tests.test_native_autonomy import desk as desk
from packages.core.core.tests.test_native_custody_owner import _preview, _selection
from packages.core.core.tests.test_native_financial_owner import RUN, _facts, _qualify
from packages.core.core.tests.test_native_producer_v2 import _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration

IST = ZoneInfo("Asia/Kolkata")
BEFORE_EIGHT = datetime(2026, 11, 28, 7, 59, 40, tzinfo=IST)
SEVEN = datetime(2026, 11, 28, 7, 0, tzinfo=IST)
EIGHT = datetime(2026, 11, 28, 8, 0, tzinfo=IST)
NEXT_EIGHT = datetime(2026, 11, 29, 8, 0, tzinfo=IST)


def _pin_clock(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    current = instant.astimezone(UTC)

    class Instant(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            stamp = current if tz is None else current.astimezone(tz)
            return cls(
                stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute,
                stamp.second, stamp.microsecond, tzinfo=stamp.tzinfo,
            )

    import jwt.api_jwt

    monkeypatch.setattr("flinttrade_core.auth_routes.datetime", Instant)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Instant)
    monkeypatch.setattr(time, "time", lambda: current.timestamp())


def _facts_on_clock() -> dict[str, Any]:
    facts = _facts()
    facts["native_order_date"] = datetime.fromtimestamp(time.time(), IST).date().isoformat()
    return facts


def test_sign_in_just_before_eight_lasts_until_the_following_morning(desk: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sign-in at 07:59:40 IST expires at 08:00 IST the following day."""
    app, _client, _headers, _other = desk
    _pin_clock(monkeypatch, BEFORE_EIGHT)
    with app.app_context():
        expiry = _session_expiry()
        token = _create_token("synthetic-operator", mode="live", live_mode_unlocked=True)
        claims = decode_token(token)
    assert expiry == NEXT_EIGHT.astimezone(UTC)
    assert claims["exp"] == int(expiry.timestamp())


def test_sign_in_an_hour_before_eight_ends_at_that_morning(desk: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sign-in at 07:00 IST still ends at 08:00 IST the same morning."""
    app, _client, _headers, _other = desk
    _pin_clock(monkeypatch, SEVEN)
    with app.app_context():
        expiry = _session_expiry()
        token = _create_token("synthetic-operator", mode="live", live_mode_unlocked=True)
        claims = decode_token(token)
    assert expiry == EIGHT.astimezone(UTC)
    assert claims["exp"] == int(expiry.timestamp())


def test_legacy_grant_that_outlasts_the_session_is_refused_at_075940(
    desk: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 60-second grant at 07:59:40 IST is refused when the session ends at 08:00."""
    app, client, headers, _other = desk
    _pin_clock(monkeypatch, SEVEN)
    with app.app_context():
        headers["Authorization"] = "Bearer " + _create_token(
            "synthetic-operator", mode="live", live_mode_unlocked=True,
        )
    _pin_clock(monkeypatch, BEFORE_EIGHT)
    grant = armed(desk, lifetime=60, issue_grant=False)
    refused = client.post(URL + "/bounded-one/autonomy/grant", json=grant, headers=headers)
    assert refused.status_code == 409, refused.json
    assert refused.get_json() == {
        "status": "error",
        "code": SESSION_EXPIRES_SOON_CODE,
        "message": SESSION_EXPIRES_SOON_MESSAGE,
    }
    status = client.get(URL + "/bounded-one/autonomy", headers=headers)
    assert status.status_code == 200, status.json
    assert status.get_json()["data"]["grant"] is None


def test_custody_grant_that_outlasts_the_session_is_refused_at_075940(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A v2 grant at 07:59:40 IST is refused when the session ends at 08:00."""
    desk = mounted_desk
    _pin_clock(monkeypatch, SEVEN)
    with desk.app.app_context():
        desk.headers["Authorization"] = "Bearer " + _create_token(
            "mounted-operator", mode="live", live_mode_unlocked=True,
        )
    _pin_clock(monkeypatch, BEFORE_EIGHT)
    monkeypatch.setattr("packages.core.core.tests.test_native_producer_v2._facts", _facts_on_clock)
    monkeypatch.setattr("packages.core.core.tests.test_native_financial_owner._facts", _facts_on_clock)
    _registered(desk)
    view = _qualify(desk)
    selection = _selection(view)
    selection["limits"]["max_reads"] = 128
    selection["expires_at_ms"] = int(time.time() * 1000) + 30_000
    preview = _preview(desk, selection)
    accepted = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert accepted.status_code == 200, accepted.get_json()
    refused = desk.client.post(RUN + "/autonomy-v2/grant", json=selection, headers=desk.headers)
    assert refused.status_code == 409, refused.get_json()
    assert refused.get_json() == {
        "status": "error",
        "code": SESSION_EXPIRES_SOON_CODE,
        "message": SESSION_EXPIRES_SOON_MESSAGE,
    }
    readback = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
    assert readback.status_code == 200, readback.get_json()
    assert readback.get_json()["data"]["grant"] is None
    assert readback.get_json()["data"]["entry_state"] == "ungranted"


SEVEN_THIRTY = datetime(2026, 11, 28, 7, 30, tzinfo=IST)
SEVEN_FORTY_FIVE = datetime(2026, 11, 28, 7, 45, tzinfo=IST)
_ACCOUNT = {
    "username": "nav",
    "email": "nav@example.com",
    "password": "StrongP@ss123!",
    "pin": "123456",
}


@pytest.fixture()
def auth_client(tmp_path, monkeypatch, owned_flask_apps):
    """Flask test client with a temporary auth service."""
    from unittest.mock import patch

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_service import AuthService

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    with patch("flinttrade_core.auth_routes._get_auth_service") as mock:
        svc = AuthService(db_path=tmp_path / "auth.db")
        mock.return_value = svc
        app = create_flask_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client, svc, app
    owned_flask_apps.close()


def _open_account(client: Any) -> None:
    created = client.post("/v1/auth/setup", json=_ACCOUNT)
    assert created.status_code == 201, created.get_json()


def _enable_totp(svc: Any, password: str = "StrongP@ss123!") -> None:
    import pyotp

    assert svc.verify_password(password)
    code = pyotp.TOTP(svc.get_totp_secret()).now()
    assert svc.enable_totp(code)


def _auth_header(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def _next_morning_iso() -> str:
    return NEXT_EIGHT.astimezone(UTC).isoformat()


def test_setup_create_at_0730_lasts_until_the_following_morning(
    auth_client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Account create at 07:30 IST uses the sign-in expiry and returns it."""
    client, _svc, app = auth_client
    _pin_clock(monkeypatch, SEVEN_THIRTY)
    created = client.post("/v1/auth/setup", json=_ACCOUNT)
    assert created.status_code == 201, created.get_json()
    body = created.get_json()["data"]
    assert body["expires_at"] == _next_morning_iso()
    with app.app_context():
        assert decode_token(body["token"])["exp"] == int(NEXT_EIGHT.astimezone(UTC).timestamp())


def test_setup_resume_at_0745_keeps_the_create_expiry(
    auth_client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup resume that still holds the create token keeps that expiry."""
    client, _svc, app = auth_client
    _pin_clock(monkeypatch, SEVEN_THIRTY)
    created = client.post("/v1/auth/setup", json=_ACCOUNT)
    assert created.status_code == 201, created.get_json()
    original = created.get_json()["data"]["expires_at"]
    token = created.get_json()["data"]["token"]
    _pin_clock(monkeypatch, SEVEN_FORTY_FIVE)
    resumed = client.post(
        "/v1/auth/setup/resume",
        json={"password": "StrongP@ss123!"},
        headers=_auth_header(token),
    )
    assert resumed.status_code == 200, resumed.get_json()
    body = resumed.get_json()["data"]
    assert body["expires_at"] == original == _next_morning_iso()
    with app.app_context():
        assert decode_token(body["token"])["exp"] == int(NEXT_EIGHT.astimezone(UTC).timestamp())


def test_pin_unlock_in_the_last_hour_keeps_the_sign_in_expiry(
    auth_client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PIN unlock at 07:45 IST keeps the 07:30 IST sign-in expiry."""
    client, _svc, app = auth_client
    _open_account(client)
    _pin_clock(monkeypatch, SEVEN_THIRTY)
    signed_in = client.post("/v1/auth/login", json={"password": "StrongP@ss123!"})
    assert signed_in.status_code == 200, signed_in.get_json()
    original = signed_in.get_json()["data"]["expires_at"]
    token = signed_in.get_json()["data"]["token"]
    assert original == _next_morning_iso()
    _pin_clock(monkeypatch, SEVEN_FORTY_FIVE)
    unlocked = client.post("/v1/auth/pin", json={"pin": "123456"}, headers=_auth_header(token))
    assert unlocked.status_code == 200, unlocked.get_json()
    body = unlocked.get_json()["data"]
    assert body["expires_at"] == original
    with app.app_context():
        assert decode_token(body["token"])["exp"] == int(NEXT_EIGHT.astimezone(UTC).timestamp())


def test_live_switch_in_the_last_hour_keeps_the_sign_in_expiry(
    auth_client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Live switch at 07:45 IST keeps the 07:30 IST sign-in expiry."""
    client, svc, app = auth_client
    _open_account(client)
    _pin_clock(monkeypatch, SEVEN_THIRTY)
    signed_in = client.post("/v1/auth/login", json={"password": "StrongP@ss123!"})
    assert signed_in.status_code == 200, signed_in.get_json()
    original = signed_in.get_json()["data"]["expires_at"]
    token = signed_in.get_json()["data"]["token"]
    _enable_totp(svc)
    _pin_clock(monkeypatch, SEVEN_FORTY_FIVE)
    switched = client.post("/v1/auth/live", json={"pin": "123456"}, headers=_auth_header(token))
    assert switched.status_code == 200, switched.get_json()
    body = switched.get_json()["data"]
    assert body["expires_at"] == original == _next_morning_iso()
    with app.app_context():
        assert decode_token(body["token"])["exp"] == int(NEXT_EIGHT.astimezone(UTC).timestamp())


def test_mode_downgrade_in_the_last_hour_keeps_the_sign_in_expiry(
    auth_client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Mode downgrade at 07:45 IST keeps the 07:30 IST sign-in expiry."""
    client, svc, app = auth_client
    _open_account(client)
    _pin_clock(monkeypatch, SEVEN_THIRTY)
    signed_in = client.post("/v1/auth/login", json={"password": "StrongP@ss123!"})
    assert signed_in.status_code == 200, signed_in.get_json()
    token = signed_in.get_json()["data"]["token"]
    original = signed_in.get_json()["data"]["expires_at"]
    _enable_totp(svc)
    live = client.post("/v1/auth/live", json={"pin": "123456"}, headers=_auth_header(token))
    assert live.status_code == 200, live.get_json()
    live_token = live.get_json()["data"]["token"]
    _pin_clock(monkeypatch, SEVEN_FORTY_FIVE)
    downgraded = client.post(
        "/v1/auth/mode", json={"mode": "practice"}, headers=_auth_header(live_token),
    )
    assert downgraded.status_code == 200, downgraded.get_json()
    body = downgraded.get_json()["data"]
    assert body["expires_at"] == original == _next_morning_iso()
    with app.app_context():
        assert decode_token(body["token"])["exp"] == int(NEXT_EIGHT.astimezone(UTC).timestamp())
