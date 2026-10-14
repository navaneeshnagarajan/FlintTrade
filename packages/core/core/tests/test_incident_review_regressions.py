"""Maintained regressions for incident custody; all external I/O is inert."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import pytest

from .test_system_incidents import HEADERS, factory as factory

pytestmark = pytest.mark.integration


def test_real_httpx_telegram_redacts_before_every_log_sink(factory, monkeypatch, capsys):
    from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
    from flinttrade_core.log_stream import LogBuffer
    from flinttrade_core.workspace import Workspace

    app, client = factory()
    token = "123456:" + uuid4().hex + "Synthetic"
    app.config["TELEGRAM_BOT"] = TelegramBot(BotConfig(token=token, chat_id="99", enabled=True))
    sent, violations, raw = [], [], []

    def inert_transport(self, request):
        valid = (
            request.method == "POST"
            and str(request.url) == f"https://api.telegram.org/bot{token}/sendMessage"
            and json.loads(request.content)["chat_id"] == "99"
        )
        if not valid:
            violations.append("unexpected wire request")
        sent.append(request.method)
        return httpx.Response(200, json={"ok": True}, request=request)

    class Sink(logging.Handler):
        def emit(self, record):
            raw.append(record.getMessage())

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", inert_transport)
    logger = logging.getLogger("httpx")
    sink = Sink()
    logger.addHandler(sink)
    original_level, original_disabled = logger.level, logger.disabled
    try:
        configured = client.put(
            "/api/v1/system/incidents/channels/telegram",
            headers=HEADERS,
            json={"enabled": True, "provider": "telegram", "recipient": "99"},
        )
        assert configured.status_code == 200
        client.get("/synthetic-incident-failure", headers=HEADERS)
        owner = app.config["SYSTEM_INCIDENTS"]
        owner.deliver_pending()
        logger.info("safe concurrent HTTP diagnostic")
        for handler in logging.getLogger().handlers:
            handler.flush()
        file_log = (Workspace().log_dir / "flinttrade.log").read_text()
        recent = client.get("/api/v1/logs/recent?n=500", headers=HEADERS)
        ring = LogBuffer().recent(500)
        streamed = client.get("/v1/logs/recent?n=500", headers=HEADERS)
        console = capsys.readouterr()
        # Booleans only: pytest must not print the generated canary on RED.
        leaks = {
            name: token in text
            for name, text in {
                "source_logger": str(raw),
                "file": file_log,
                "mounted_file_reader": recent.get_data(as_text=True),
                "ring": str(ring),
                "mounted_ring_reader": streamed.get_data(as_text=True),
                "stdout": console.out,
                "stderr": console.err,
                "incident_custody": str(owner.snapshot()),
            }.items()
        }
        assert sent == ["POST"] and violations == []
        assert recent.status_code == streamed.status_code == 200
        assert any("HTTP Request: POST" in record for record in raw)
        assert "safe concurrent HTTP diagnostic" in raw
        assert logger.level == original_level and logger.disabled == original_disabled
        assert not any(leaks.values()), leaks
        delivery = next(d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "telegram")
        assert delivery["state"] == "submitted_unobserved"
        owner.deliver_pending()
        assert sent == ["POST"]
    finally:
        logger.removeHandler(sink)
        # Factory logging captured this test's stderr; drain before capsys retires.
        from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
        import time

        cleanup = _DesktopShutdownRecoveryOwner(app)
        app.extensions["incident.cleanup"] = cleanup
        cleanup.release(deadline=time.monotonic() + 10)


@pytest.mark.parametrize("barrier", ["configure", "fingerprint", "persistence"])
def test_retired_operator_enablement_never_commits(factory, monkeypatch, barrier):
    import threading
    from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
    from flinttrade_core.incident_delivery import ConfiguredAlertBinding

    app, _ = factory()
    app.config["TELEGRAM_BOT"] = TelegramBot(BotConfig(token=uuid4().hex, chat_id="99", enabled=True))
    owner = app.config["SYSTEM_INCIDENTS"]
    entered, release = threading.Event(), threading.Event()
    results = []
    calls = 0
    target, name = (owner, "configure") if barrier == "configure" else (ConfiguredAlertBinding, "fingerprint")
    original = getattr(target, name)

    def held(*args, **kwargs):
        nonlocal calls
        calls += 1
        # First fingerprint resolves the route binding; second is inside configure.
        if calls == (1 if barrier == "configure" else 2):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("synthetic barrier timed out")
        return original(*args, **kwargs)

    if barrier == "persistence":
        from contextlib import contextmanager

        transaction = owner._database.transaction

        @contextmanager
        def held_transaction():
            with transaction() as db:

                class Connection:
                    def execute(self, sql, parameters=()):
                        result = db.execute(sql, parameters)
                        if sql.startswith("INSERT INTO channels") and not entered.is_set():
                            entered.set()
                            if not release.wait(5):
                                raise RuntimeError("synthetic persistence barrier timed out")
                        return result

                yield Connection()

        monkeypatch.setattr(owner._database, "transaction", held_transaction)
    else:
        monkeypatch.setattr(target, name, held)

    def send():
        with app.test_client() as client:
            results.append(
                client.put(
                    "/api/v1/system/incidents/channels/telegram",
                    headers=HEADERS,
                    json={"enabled": True, "provider": "telegram", "recipient": "99"},
                )
            )

    worker = threading.Thread(target=send)
    worker.start()
    try:
        assert entered.wait(5)
        monkeypatch.setenv("FLINTTRADE_API_KEY", uuid4().hex)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert [result.status_code for result in results] == [401]
    retained = owner.channel("telegram")
    assert retained["enabled"] is False and retained["effective"] is False
    # Independent healthy authority can still opt in after the refused request.
    monkeypatch.setenv("FLINTTRADE_API_KEY", HEADERS["X-API-Key"])
    with app.test_client() as client:
        healthy = client.put(
            "/api/v1/system/incidents/channels/telegram",
            headers=HEADERS,
            json={"enabled": True, "provider": "telegram", "recipient": "99"},
        )
    assert healthy.status_code == 200
    assert owner.channel("telegram")["effective"] is True


@pytest.mark.parametrize("producer", ["history_job", "model_task"])
def test_passive_failure_is_retained_once_with_trusted_provenance(factory, tmp_path, producer):
    import time
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
    from flinttrade_core.service_task_routes import get_service_task_dispatcher

    app, client = factory()
    owner = app.config["SYSTEM_INCIDENTS"]
    private = uuid4().hex
    if producer == "history_job":
        manager = app.config["HISTORIFY_JOB_MANAGER"]

        async def fail(progress):
            raise RuntimeError(private)

        async def healthy(progress):
            progress(1, 1)

        job = manager.start(total=1, runner=fail, storage_path=str(tmp_path))
        manager.start(total=1, runner=healthy, storage_path=str(tmp_path))
        assert manager.close(timeout=5)
        assert manager.get(job.job_id).status == "error"
    else:
        with app.app_context():
            ledger = get_service_task_dispatcher().ledger
        ledger.begin_task(private, "synthetic-actor", "synthetic-digest")
        receipt = {"request_id": "untrusted-payload-label", "outcome": "failed", "code": private, "attempts": []}
        ledger.finish_task(private, receipt)
        ledger.finish_task(private, receipt)  # same durable producer identity, not another incident
        ledger.begin_task("healthy", "synthetic-actor", "synthetic-digest")
        ledger.finish_task("healthy", {"outcome": "completed"})
    rows = owner.snapshot()["incidents"]
    assert len(rows) == 1, "real failed producer did not publish exactly one retained incident"
    row = rows[0]
    assert row["source"] == producer
    assert row["producer"]["reference"] == row["correlation_id"]
    assert row["producer"]["kind"] == ("historify_job_manager" if producer == "history_job" else "service_usage_ledger")
    assert row["severity"] == "warning" and row["deliveries"] == []
    assert row["root_cause"] == {"state": "unknown", "code": None}
    assert row["measurement"] == {"state": "unmeasured", "duration_ms": None, "status_code": None}
    leaked = private in str(rows) or "untrusted-payload-label" in str(rows)
    assert not leaked, "producer payload escaped into incident custody"
    for _ in range(3):
        observed = client.get("/api/v1/system/diagnostics", headers=HEADERS)
        assert observed.status_code == 200
        assert observed.json["data"]["operational_events"]["incidents"] == rows
    # Failed HTTP remains its own measured correlation, never guessed as the cause.
    control = client.get("/synthetic-incident-failure", headers=HEADERS)
    assert len(owner.snapshot()["incidents"]) == 2
    assert owner.snapshot()["incidents"][0]["correlation_id"] == control.headers["X-Diagnostic-Request-ID"]
    cleanup = _DesktopShutdownRecoveryOwner(app)
    app.extensions["incident.cleanup"] = cleanup
    cleanup.release(deadline=time.monotonic() + 10)
    assert owner.closed
    reopened, reader = factory()
    retained = reader.get("/api/v1/system/incidents", headers=HEADERS).json["incidents"]
    assert [value for value in retained if value["id"] == row["id"]] == [row]
    if producer == "model_task":
        with reopened.app_context():
            get_service_task_dispatcher().ledger.finish_task(private, receipt)
        assert len(reopened.config["SYSTEM_INCIDENTS"].snapshot()["incidents"]) == 2
