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
