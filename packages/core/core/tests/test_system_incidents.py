# Test source: GNU AGPL v3, as licensed in the repository LICENSE.
from __future__ import annotations
import time
from unittest.mock import MagicMock
import pytest

pytestmark = pytest.mark.integration
HEADERS = {"X-API-Key": "synthetic-incident-key"}


@pytest.fixture
def factory(tmp_path, monkeypatch):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("FLINTTRADE_API_KEY", HEADERS["X-API-Key"])
    apps = []

    def create():
        from flask.testing import FlaskClient

        class BufferedClient(FlaskClient):
            def open(self, *args, **kwargs):
                kwargs.setdefault("buffered", True)
                return super().open(*args, **kwargs)

        app = create_flask_app(safety=MagicMock(order_reservations_durable=True), contract_manager=MagicMock())
        app.test_client_class = BufferedClient
        app.config["TESTING"] = True

        @app.get("/synthetic-incident-failure")
        def synthetic_failure():
            return {"error": "inert"}, 503

        apps.append(app)
        return app, app.test_client()

    yield create
    for app in reversed(apps):
        recovery = app.extensions.get("incident.cleanup")
        if recovery is None:
            recovery = _DesktopShutdownRecoveryOwner(app)
            app.extensions["incident.cleanup"] = recovery
        recovery.release(deadline=time.monotonic() + 10)


def test_normal_factory_persists_one_correlated_incident_across_reopen(factory):
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    app, client = factory()
    response = client.get("/synthetic-incident-failure?token=PRIVATE-PROMPT", headers=HEADERS)
    assert response.status_code == 503
    snapshot = client.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]
    evidence = snapshot["operational_events"]
    assert evidence["durable"] is True, "normal factory still exposes only the process ring"
    assert evidence["retention"] == "until_manual_deletion"
    rows = evidence["incidents"]
    matching = [r for r in rows if r["correlation_id"] == response.headers["X-Diagnostic-Request-ID"]]
    assert len(matching) == 1
    row = matching[0]
    assert row["severity"] == "critical"
    assert row["measurement"]["duration_ms"] >= 0
    assert row["measurement"]["state"] == "measured"
    assert row["root_cause"] == {"state": "unknown", "code": None}
    assert "PRIVATE-PROMPT" not in str(evidence)
    owner = app.config["SYSTEM_INCIDENTS"]
    cleanup = _DesktopShutdownRecoveryOwner(app)
    app.extensions["incident.cleanup"] = cleanup
    cleanup.release(deadline=time.monotonic() + 10)
    assert owner.closed
    second, reopened = factory()
    found = reopened.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]["operational_events"]["incidents"]
    assert [r for r in found if r["id"] == row["id"]] == [row]
    assert second.config["SYSTEM_INCIDENTS"] is not owner


def test_delivery_is_opt_in_durable_and_unknown_is_never_retried(factory, monkeypatch, tmp_path):
    import io
    from flinttrade_core import desktop_notify

    app, client = factory()
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    wire = io.StringIO()
    monkeypatch.setattr(desktop_notify.sys, "stdout", wire)
    response = client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    assert hasattr(owner, "deliver_pending"), "no durable delivery lifecycle is installed"
    owner.deliver_pending()
    receipt = owner.snapshot()["incidents"][0]
    assert receipt["correlation_id"] == response.headers["X-Diagnostic-Request-ID"]
    states = {row["channel"]: row for row in receipt["deliveries"]}
    assert states["desktop"]["state"] == "submitted_unobserved"
    assert states["telegram"]["state"] == states["email"]["state"] == "disabled"
    assert wire.getvalue().count("FLINTTRADE_NOTIFY\t") == 1
    owner.deliver_pending()
    assert wire.getvalue().count("FLINTTRADE_NOTIFY\t") == 1
    assert states["desktop"]["attempts"] == 1
    import json

    (tmp_path / "native-wire.json").write_text(json.dumps({"wire": wire.getvalue(), "receipt": states["desktop"]}))


def test_passive_collectors_read_existing_owners_without_creating_or_invoking(factory):
    from flinttrade_core.service_task_routes import get_service_task_dispatcher
    from flinttrade_historical.historify_jobs import HistorifyJobManager

    app, client = factory()
    assert "SERVICE_TASK_DISPATCHER" not in app.config
    before = client.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]
    assert before["models"]["capacity"] is None
    assert "SERVICE_TASK_DISPATCHER" not in app.config
    with app.app_context():
        dispatcher = get_service_task_dispatcher()
    dispatcher.ledger.begin_task("synthetic-observed-task", "synthetic-actor", "synthetic-digest")
    manager = HistorifyJobManager()
    app.config["HISTORIFY_JOB_MANAGER"] = manager
    after = client.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]
    assert after["models"]["status"] == "available", "bound usage observations remain unmeasured"
    assert after["models"]["source"] == "service_usage_ledger"
    assert after["models"]["capacity"] is None
    assert after["models"]["tasks"]["unknown"] == 1
    assert after["jobs"]["collectors"]["historical_downloads"]["active"] == 0
    assert after["jobs"]["coverage"] == "registered_collectors_only"
    assert "synthetic-digest" not in str(after)
    assert app.config["SERVICE_TASK_DISPATCHER"] is dispatcher


def test_opt_in_telegram_uses_exact_configured_owner_and_no_replay_after_timeout(factory, monkeypatch):
    import httpx
    from flinttrade_automation.telegram_bot import TelegramBot, BotConfig

    app, client = factory()
    bot = TelegramBot(BotConfig(token="inert-telegram-secret", chat_id="12345", enabled=True))
    app.config["TELEGRAM_BOT"] = bot
    calls = []

    def transport(url, **kwargs):
        calls.append((url, kwargs))
        raise httpx.ReadTimeout("private failure detail")

    monkeypatch.setattr(httpx, "post", transport)
    config = client.put(
        "/api/v1/system/incidents/channels/telegram",
        headers=HEADERS,
        json={"enabled": True, "recipient": "12345", "provider": "telegram"},
    )
    assert config.status_code == 200, "explicit incident channel enablement is not mounted"
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    owner.deliver_pending()
    row = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "telegram")
    assert row["state"] == "unknown"
    assert len(calls) == 1
    assert calls[0][0] == "https://api.telegram.org/botinert-telegram-secret/sendMessage"
    assert calls[0][1]["json"]["chat_id"] == "12345"
    assert "Root cause unconfirmed" in calls[0][1]["json"]["text"]
    assert (
        client.post("/api/v1/system/incidents/deliveries/" + row["id"] + "/retry", headers=HEADERS).status_code == 409
    )
    owner.deliver_pending()
    assert len(calls) == 1
    assert all(
        value not in str(owner.snapshot()) for value in ("inert-telegram-secret", "12345", "private failure detail")
    )


def test_email_opt_in_uses_selected_service_without_provider_fallback(factory, monkeypatch):
    from flinttrade_core import auth_routes

    monkeypatch.setenv("SMTP_HOST", "inert-smtp.invalid")
    monkeypatch.setenv("SMTP_FROM", "sender@example.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("AWS_SES_REGION", "inert-region")
    configured = auth_routes.EmailTransport()
    monkeypatch.setattr(auth_routes, "_email_transport", configured)
    calls = []

    class SMTP:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def sendmail(self, sender, recipients, message):
            calls.append((sender, recipients, message))
            return {}

    monkeypatch.setattr(auth_routes.smtplib, "SMTP", SMTP)
    app, client = factory()
    response = client.put(
        "/api/v1/system/incidents/channels/email",
        headers=HEADERS,
        json={"enabled": True, "recipient": "operator@example.invalid", "provider": "smtp"},
    )
    assert response.status_code == 200, "configured email owner has no incident transport"
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    owner.deliver_pending()
    receipt = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "email")
    assert receipt["state"] == "submitted_unobserved"
    assert calls[0] == ("inert-smtp.invalid", 587)
    assert calls[1][1] == ["operator@example.invalid"]
    import email

    message = email.message_from_string(calls[1][2])
    assert "Root cause unconfirmed" in message.get_payload()[0].get_payload(decode=True).decode()
    assert "operator@example.invalid" not in str(owner.snapshot())
    owner.deliver_pending()
    assert len(calls) == 2


def test_diagnostics_rechecks_permission_after_actual_blocking_read(factory, monkeypatch):
    import threading

    app, client = factory()
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    original = owner.snapshot
    entered, release = threading.Event(), threading.Event()
    responses = []

    def held(**kwargs):
        result = original(**kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(owner, "snapshot", held)
    thread = threading.Thread(
        target=lambda: responses.append(client.get("/api/v1/system/diagnostics", headers=HEADERS))
    )
    thread.start()
    try:
        assert entered.wait(5)
        monkeypatch.setenv("FLINTTRADE_API_KEY", "new-synthetic-authority")
    finally:
        release.set()
        thread.join(5)
    assert responses[0].status_code == 401, "retired reader received private incident evidence"
    assert "incidents" not in str(responses[0].json)


def test_normal_shutdown_retains_owner_while_real_request_is_held(factory, monkeypatch):
    import threading
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner, DesktopBackendShutdownIncomplete

    app, client = factory()
    owner = app.config["SYSTEM_INCIDENTS"]
    entered, release, drain = threading.Event(), threading.Event(), threading.Event()
    original = owner.observe_http

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, "observe_http", held)
    tracker = app.config["RUNTIME_REQUEST_TRACKER"]
    wait = tracker.wait_for_idle

    def observe_wait(timeout):
        drain.set()
        return wait(timeout)

    monkeypatch.setattr(tracker, "wait_for_idle", observe_wait)
    result = []
    thread = threading.Thread(target=lambda: result.append(client.get("/synthetic-incident-failure", headers=HEADERS)))
    thread.start()
    cleanup = _DesktopShutdownRecoveryOwner(app)
    app.extensions["incident.cleanup"] = cleanup
    try:
        assert entered.wait(5)
        with pytest.raises(DesktopBackendShutdownIncomplete):
            cleanup.release(deadline=time.monotonic() + 0.2)
        assert drain.is_set()
        assert not owner.closed
        assert app.config["SYSTEM_INCIDENTS"] is owner
    finally:
        release.set()
        thread.join(5)
    assert result[0].status_code == 503
    assert len(owner.snapshot()["incidents"]) == 1
    cleanup.release(deadline=time.monotonic() + 10)
    assert owner.closed


def test_manual_retention_exceeds_ring_and_missing_storage_never_recreates(factory):
    from uuid import uuid4
    from flinttrade_core.system_incidents import IncidentUnavailable

    app, client = factory()
    owner = app.config["SYSTEM_INCIDENTS"]
    for _ in range(502):
        owner.observe_http(str(uuid4()), 404, 1.5)
    rows, cursor = [], None
    while True:
        page = owner.snapshot(limit=100, before=cursor)
        rows.extend(page["incidents"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert len({r["id"] for r in rows}) == 502
    assert all(r["root_cause"]["state"] == "unknown" for r in rows)
    path = owner._database.path
    moved = path.with_suffix(".held")
    path.rename(moved)
    try:
        with pytest.raises(IncidentUnavailable):
            owner.snapshot()
        assert not path.exists()
        with pytest.raises(IncidentUnavailable):
            owner.close()
        assert not owner.closed
    finally:
        moved.rename(path)
    owner.close()
    assert owner.closed


def test_browser_claim_is_single_use_session_bound_and_never_claims_delivery(factory, monkeypatch):
    app, client = factory()
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    receipt = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "desktop")
    base = "/api/v1/system/incidents/deliveries/" + receipt["id"]
    claimed = client.post(base + "/claim", headers=HEADERS)
    assert claimed.status_code == 200, "browser delivery has no durable at-most-once claim"
    assert client.post(base + "/claim", headers=HEADERS).status_code == 409
    assert claimed.json["state"] == "sending"
    payload = {"claim": claimed.json["claim"], "state": "submitted_unobserved"}
    monkeypatch.setenv("FLINTTRADE_API_KEY", "replacement-reader")
    assert client.post(base + "/receipt", headers={"X-API-Key": "replacement-reader"}, json=payload).status_code == 409
    monkeypatch.setenv("FLINTTRADE_API_KEY", HEADERS["X-API-Key"])
    ack = client.post(base + "/receipt", headers=HEADERS, json=payload)
    assert ack.status_code == 200
    assert ack.json["state"] == "submitted_unobserved"
    assert client.post(base + "/receipt", headers=HEADERS, json=payload).status_code == 200
    assert client.post(base + "/retry", headers=HEADERS).status_code == 409
    assert owner.delivery(receipt["id"])["attempts"] == 1


def test_actual_critical_logger_is_captured_once_without_private_message(factory):
    import logging

    app, client = factory()
    logger = logging.getLogger("flinttrade.incident.inert_worker")
    with app.app_context():
        logger.critical("password=PRIVATE-LOG /home/private https://private.invalid PROMPT")
    rows = app.config["SYSTEM_INCIDENTS"].snapshot()["incidents"]
    assert len(rows) == 1, "background critical producer is not mounted"
    assert rows[0]["source"] == "core_log"
    assert rows[0]["measurement"] == {"state": "unmeasured", "duration_ms": None, "status_code": None}
    assert rows[0]["root_cause"]["state"] == "unknown"
    assert all(secret not in str(rows) for secret in ("PRIVATE-LOG", "/home/private", "private.invalid", "PROMPT"))


def test_refused_auth_request_gets_server_correlation_once(factory):
    app, client = factory()
    response = client.get("/api/v1/system/diagnostics", headers={"X-Diagnostic-Request-ID": "client-chosen"})
    assert response.status_code == 401
    assert "X-Diagnostic-Request-ID" in response.headers, "early refusal bypassed the diagnostic binder"
    rows = app.config["SYSTEM_INCIDENTS"].snapshot()["incidents"]
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == response.headers["X-Diagnostic-Request-ID"]
    assert rows[0]["correlation_id"] != "client-chosen"


def test_definite_provider_rejection_has_bounded_explicit_retries(factory, monkeypatch):
    import httpx
    from flinttrade_automation.telegram_bot import TelegramBot, BotConfig

    app, client = factory()
    app.config["TELEGRAM_BOT"] = TelegramBot(BotConfig(token="inert", chat_id="99", enabled=True))
    calls = []

    def reject(url, **kwargs):
        calls.append(url)
        return httpx.Response(429, json={"ok": False})

    monkeypatch.setattr(httpx, "post", reject)
    assert (
        client.put(
            "/api/v1/system/incidents/channels/telegram",
            headers=HEADERS,
            json={"enabled": True, "provider": "telegram", "recipient": "99"},
        ).status_code
        == 200
    )
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    owner.deliver_pending()
    row = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "telegram")
    base = "/api/v1/system/incidents/deliveries/" + row["id"]
    assert row["state"] == "failed"
    for _ in range(2):
        assert client.post(base + "/retry", headers=HEADERS).status_code == 200
        owner.deliver_pending()
    assert owner.delivery(row["id"])["attempts"] == 3
    assert client.post(base + "/retry", headers=HEADERS).status_code == 409
    assert len(calls) == 3
    assert [h["state"] for h in owner.delivery(row["id"])["history"]].count("failed") == 3


def test_pending_cancellation_and_abandoned_claim_survive_normal_reopen(factory):
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    app, client = factory()
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    first = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "desktop")
    base = "/api/v1/system/incidents/deliveries/"
    assert client.post(base + first["id"] + "/cancel", headers=HEADERS).json["state"] == "cancelled"
    client.get("/synthetic-incident-failure", headers=HEADERS)
    second = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "desktop")
    assert client.post(base + second["id"] + "/claim", headers=HEADERS).status_code == 200
    cleanup = _DesktopShutdownRecoveryOwner(app)
    app.extensions["incident.cleanup"] = cleanup
    cleanup.release(deadline=time.monotonic() + 10)
    reopened, read = factory()
    retained = reopened.config["SYSTEM_INCIDENTS"]
    assert retained.delivery(first["id"])["state"] == "cancelled"
    assert retained.delivery(second["id"])["state"] == "unknown"
    assert read.post(base + second["id"] + "/retry", headers=HEADERS).status_code == 409
    assert read.post(base + second["id"] + "/claim", headers=HEADERS).status_code == 409


def test_real_held_transport_retains_failed_close_and_does_not_duplicate(factory, monkeypatch):
    import httpx
    import threading
    from flinttrade_core.system_incidents import IncidentUnavailable
    from flinttrade_automation.telegram_bot import TelegramBot, BotConfig

    app, client = factory()
    app.config["TELEGRAM_BOT"] = TelegramBot(BotConfig(token="inert", chat_id="99", enabled=True))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def held(url, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", held)
    assert (
        client.put(
            "/api/v1/system/incidents/channels/telegram",
            headers=HEADERS,
            json={"enabled": True, "provider": "telegram", "recipient": "99"},
        ).status_code
        == 200
    )
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    try:
        assert entered.wait(5)
        with pytest.raises(IncidentUnavailable):
            owner.close(timeout=0.01)
        assert not owner.closed
        assert app.config["SYSTEM_INCIDENTS"] is owner
    finally:
        release.set()
    owner.close(timeout=5)
    assert owner.closed
    assert len(calls) == 1


def test_real_registered_job_liveness_is_passive_not_a_fabricated_zero(factory, tmp_path):
    import asyncio
    import threading

    app, client = factory()
    manager = app.config["HISTORIFY_JOB_MANAGER"]
    entered, release = threading.Event(), threading.Event()

    async def runner(progress):
        entered.set()
        await asyncio.to_thread(release.wait, 5)

    _job = manager.start(total=1, runner=runner, storage_path=str(tmp_path))
    try:
        assert entered.wait(5)
        snapshot = client.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]
        assert snapshot["jobs"]["collectors"]["historical_downloads"]["active"] == 1
        assert snapshot["jobs"]["active"] is None
    finally:
        release.set()
    assert manager.close(timeout=5) is not False


def test_channel_readback_is_exact_and_revocation_prevents_queued_send(factory, monkeypatch):
    import httpx
    from flinttrade_automation.telegram_bot import TelegramBot, BotConfig

    app, client = factory()
    app.config["TELEGRAM_BOT"] = TelegramBot(BotConfig(token="inert", chat_id="99", enabled=True))
    calls = []
    monkeypatch.setattr(
        httpx, "post", lambda *args, **kwargs: calls.append(args) or httpx.Response(200, json={"ok": True})
    )
    owner = app.config["SYSTEM_INCIDENTS"]
    with owner._delivery_lock:
        config = client.put(
            "/api/v1/system/incidents/channels/telegram",
            headers=HEADERS,
            json={"enabled": True, "provider": "telegram", "recipient": "99"},
        )
        assert config.status_code == 200
        read = client.get("/api/v1/system/incidents/channels/telegram", headers=HEADERS)
        assert read.status_code == 200, "channel enablement has no exact durable readback"
        assert read.json["enabled"] is True
        assert read.json["binding"] == config.json["binding"]
        client.get("/synthetic-incident-failure", headers=HEADERS)
        assert (
            client.put(
                "/api/v1/system/incidents/channels/telegram", headers=HEADERS, json={"enabled": False}
            ).status_code
            == 200
        )
    owner.deliver_pending()
    assert calls == []
    assert (
        next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "telegram")["state"]
        == "revoked"
    )


def test_native_flush_failure_is_unknown_without_duplicate_write(factory, monkeypatch):
    from flinttrade_core import desktop_notify

    app, client = factory()
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")

    class BrokenPipe:
        def __init__(self):
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            raise OSError("private pipe failure")

    pipe = BrokenPipe()
    monkeypatch.setattr(desktop_notify.sys, "stdout", pipe)
    client.get("/synthetic-incident-failure", headers=HEADERS)
    owner = app.config["SYSTEM_INCIDENTS"]
    owner.deliver_pending()
    owner.deliver_pending()
    receipt = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "desktop")
    assert receipt["state"] == "unknown"
    assert len(pipe.writes) == 1
    assert (
        client.post("/api/v1/system/incidents/deliveries/" + receipt["id"] + "/retry", headers=HEADERS).status_code
        == 409
    )


def test_read_never_recreates_missing_registration(factory):
    app, client = factory()
    owner = app.config.pop("SYSTEM_INCIDENTS")
    try:
        result = client.get("/api/v1/system/diagnostics", headers=HEADERS).json["data"]["operational_events"]
        assert result["status"] == "unavailable"
        assert "SYSTEM_INCIDENTS" not in app.config
    finally:
        app.config["SYSTEM_INCIDENTS"] = owner


def test_delivery_backpressure_retains_every_incident_without_ttl(factory):
    from uuid import uuid4

    app, _ = factory()
    owner = app.config["SYSTEM_INCIDENTS"]
    for _ in range(1001):
        owner.observe_http(str(uuid4()), 503, 1.0)
    latest = owner.snapshot(limit=1)["incidents"][0]
    assert next(d for d in latest["deliveries"] if d["channel"] == "desktop")["state"] == "backpressure"
    count = 0
    cursor = None
    while True:
        page = owner.snapshot(limit=100, before=cursor)
        count += len(page["incidents"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert count == 1001


def test_owner_keeps_custody_until_delivery_worker_really_exits(factory, monkeypatch):
    import threading
    from flinttrade_core.system_incidents import IncidentUnavailable

    app, _ = factory()
    owner = app.config["SYSTEM_INCIDENTS"]
    entered, release = threading.Event(), threading.Event()
    original = owner.deliver_pending

    def finishing():
        original()
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(owner, "deliver_pending", finishing)
    owner._wake.set()
    try:
        assert entered.wait(5)
        with pytest.raises(IncidentUnavailable):
            owner.close(timeout=0.01)
        assert not owner.closed, "owner released custody before its real worker exited"
        assert owner._ownership.is_locked
    finally:
        release.set()
    owner.close(timeout=5)
    assert owner.closed
    assert not owner._thread.is_alive()


def test_critical_signal_in_successful_http_response_is_not_lost_or_duplicated(factory):
    import logging

    app, client = factory()

    @app.get("/incident-critical-success")
    def critical_success():
        logging.getLogger("flinttrade.incident").critical("private reason must not be retained")
        return {"status": "accepted"}, 200

    response = client.get("/incident-critical-success", headers=HEADERS)
    rows = app.config["SYSTEM_INCIDENTS"].snapshot()["incidents"]
    assert len(rows) == 1, "critical signal disappeared because HTTP status was successful"
    assert rows[0]["correlation_id"] == response.headers["X-Diagnostic-Request-ID"]
    assert rows[0]["severity"] == "critical"
    assert rows[0]["measurement"]["status_code"] == 200
    assert rows[0]["operation"] == "critical_success"
    assert "private reason" not in str(rows)
