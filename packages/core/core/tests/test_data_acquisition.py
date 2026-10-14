"""Acquisition ownership, not funded-feed qualification."""
from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest



def acquisition_module():
    import flinttrade_core
    from pathlib import Path
    assert (Path(flinttrade_core.__file__).parent / "data_acquisition.py").exists(), "shared lease interface missing"
    return importlib.import_module("flinttrade_core.data_acquisition")


def binding():
    return {
        "identity": {"instrument_id": "synthetic", "venue": "XNAS", "asset_class": "equity", "currency": "USD",
                     "quantity_unit": "shares", "price_unit": "currency_per_share", "multiplier": "1",
                     "interval_seconds": 1, "adjustment": "raw", "calendar_id": "test", "calendar_revision": "1"},
        "source": {"connection_id": "test-feed", "provider": "inert", "environment": "research", "account_id": None,
                   "auth_generation": 1, "configuration_generation": 1},
        "scope": {"principal_id": "test", "environment": "research", "account_id": None, "run_id": "test", "generation": 1},
        "policy_revision": "1", "max_age_seconds": 5, "lease_seconds": 60,
    }


def frame(sequence=1, kind="snapshot", price=100, second="00"):
    return {"sequence": sequence, "kind": kind, "observed_at": f"2026-01-01T00:00:{second}+00:00",
            "published_at": None, "retrieved_at": f"2026-01-01T00:00:{second}+00:00", "payload": {"price": price}}


@pytest.mark.unit
def test_two_views_share_one_acquisition_then_final_close_releases_it():
    module = acquisition_module()
    from datetime import datetime
    now = [datetime.fromisoformat("2026-01-01T00:00:00+00:00").timestamp()]
    opened, closed, publishers = [], [], []

    def open_feed(publish):
        opened.append(True)
        publishers.append(publish)
        publish(frame())
        return lambda: closed.append(True)

    owner = module.SharedAcquisition(clock=lambda: now[0])
    config = binding()
    owner.register("quote", **config, open_feed=open_feed, authorised=lambda: True)
    a = owner.acquire("quote", scope=config["scope"])
    b = owner.acquire("quote", scope=config["scope"])
    assert len(opened) == 1
    assert a["snapshot"]["status"] == "fresh"
    now[0] += 1
    publishers[0](frame(2, "update", 101, "01"))
    snapshot = owner.read(b["lease_id"], scope=config["scope"], after_sequence=1)
    assert snapshot["payload"] == {"price": 101}
    assert [event["sequence"] for event in snapshot["updates"]] == [2]
    now[0] += 10
    assert owner.read(a["lease_id"], scope=config["scope"])["status"] == "stale"
    owner.release(a["lease_id"], scope=config["scope"])
    assert closed == []
    owner.release(b["lease_id"], scope=config["scope"])
    assert len(closed) == 1
    assert publishers[0](frame(3, "update", 999, "02")) is False
    assert owner.diagnostics()["active_acquisitions"] == 0


@pytest.mark.unit
def test_concurrent_views_and_retired_blocked_opener_cannot_publish_to_replacement():
    module = acquisition_module()
    config = binding()
    started, finish = Event(), Event()
    old_publish, closed = [], []

    def old_feed(publish):
        old_publish.append(publish)
        started.set()
        assert finish.wait(3)
        publish(frame())
        return lambda: closed.append("old")

    owner = module.SharedAcquisition()
    owner.register("quote", **config, open_feed=old_feed, authorised=lambda: True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(owner.acquire, "quote", scope=config["scope"])
        try:
            assert started.wait(3)
            second = owner.acquire("quote", scope=config["scope"])
            assert len(old_publish) == 1
            replacement = {**config, "source": {**config["source"], "auth_generation": 2}}
            owner.register("quote", **replacement, open_feed=lambda publish: (lambda: None), authorised=lambda: True)
            assert old_publish[0](frame()) is False
            with pytest.raises(KeyError):
                owner.read(second["lease_id"], scope=config["scope"])
        finally:
            finish.set()
        with pytest.raises(KeyError):
            pending.result(3)
    assert closed == ["old"]
    owner.close()


@pytest.mark.unit
def test_gap_requires_snapshot_and_failed_reconnect_cannot_freshen_previous_data():
    module = acquisition_module()
    from datetime import datetime
    now = [datetime.fromisoformat("2026-01-01T00:00:03+00:00").timestamp()]
    config, publishers, closed = binding(), [], []

    def feed(publish):
        publishers.append(publish)
        if len(publishers) > 1:
            raise RuntimeError("synthetic transport failure")
        publish(frame())
        return lambda: closed.append(True)

    owner = module.SharedAcquisition(clock=lambda: now[0])
    owner.register("quote", **config, open_feed=feed, authorised=lambda: True, reconnect_limit=1)
    lease = owner.acquire("quote", scope=config["scope"])["lease_id"]
    assert publishers[0](frame(3, "update", 103, "03")) is False
    assert owner.read(lease, scope=config["scope"])["reason"] == "resync_required"
    assert owner.reconnect(lease, scope=config["scope"]) is False
    view = owner.read(lease, scope=config["scope"])
    assert view["status"] == "stale" and view["observed_at"].endswith("00+00:00")
    assert view["payload"] == {"price": 100}
    assert owner.reconnect(lease, scope=config["scope"]) is False
    assert len(publishers) == 2 and len(closed) == 1
    assert publishers[0](frame(4, "snapshot", 999, "03")) is False
    assert publishers[1](frame(4, "snapshot", 999, "03")) is False
    owner.close()


@pytest.mark.unit
def test_revocation_and_expiry_release_leases_and_close_is_terminal():
    module = acquisition_module()
    now, authorised, closed = [1.0], [True], []
    config = binding()
    owner = module.SharedAcquisition(clock=lambda: now[0])
    owner.register("quote", **config, open_feed=lambda publish: lambda: closed.append(True),
                   authorised=lambda: authorised[0])
    lease = owner.acquire("quote", scope=config["scope"])["lease_id"]
    with pytest.raises(PermissionError):
        owner.read(lease, scope={**config["scope"], "account_id": "other"})
    authorised[0] = False
    with pytest.raises(PermissionError):
        owner.read(lease, scope=config["scope"])
    owner.expire()
    assert closed == [True]
    authorised[0] = True
    lease = owner.acquire("quote", scope=config["scope"])["lease_id"]
    now[0] += 61
    owner.expire()
    with pytest.raises(KeyError):
        owner.read(lease, scope=config["scope"])
    assert len(closed) == 2
    owner.close()
    with pytest.raises(RuntimeError):
        owner.acquire("quote", scope=config["scope"])


@pytest.mark.integration
def test_mounted_data_leases_use_only_the_injected_owner_and_server_scope(monkeypatch):
    from flask import Flask
    from flinttrade_historical.local_data_routes import local_data_bp
    module, config, closed = acquisition_module(), binding(), []
    owner = module.SharedAcquisition()
    owner.register("quote", **config, open_feed=lambda publish: lambda: closed.append(True), authorised=lambda: True)
    app = Flask(__name__)
    app.config["DATA_ACQUISITION_OWNER"] = owner
    app.config["DATA_SCOPE_RESOLVER"] = lambda: config["scope"]
    app.register_blueprint(local_data_bp)
    client = app.test_client()
    created = client.post("/api/v1/data/leases", json={"dataset_id": "quote"})
    assert created.status_code == 201
    lease_id = created.json["data"]["lease_id"]
    read = client.get(f"/api/v1/data/leases/{lease_id}")
    assert read.status_code == 200 and read.json["data"]["status"] == "unavailable"
    # A client cannot supply a different account/run as authority.
    assert client.post("/api/v1/data/leases", json={"dataset_id": "quote", "scope": {}}).status_code == 400
    for body in ([], None, "quote", 3):
        assert client.post("/api/v1/data/leases", json=body).status_code == 400
    assert client.post("/api/v1/data/leases", data="{", content_type="application/json").status_code == 400
    assert client.delete(f"/api/v1/data/leases/{lease_id}").status_code == 200
    assert closed == [True]
    owner.close()


@pytest.mark.unit
def test_snapshot_resync_replay_loss_and_clock_refusal():
    from datetime import datetime
    module, config, callbacks = acquisition_module(), binding(), []
    now = datetime.fromisoformat("2026-01-01T00:10:00+00:00").timestamp()
    def feed(publish):
        callbacks.append(publish)
        publish(frame())
        return lambda: None
    owner = module.SharedAcquisition(clock=lambda: now)
    owner.register("quote", **config, open_feed=feed, authorised=lambda: True)
    lease = owner.acquire("quote", scope=config["scope"])["lease_id"]
    assert callbacks[0](frame(4, "update")) is False
    assert callbacks[0](frame(5, "snapshot")) is True
    for sequence in range(6, 140):
        assert callbacks[0](frame(sequence, "update")) is True
    assert owner.read(lease, scope=config["scope"], after_sequence=5)["replay_gap"] is True
    future = frame(140, "update")
    future.update(observed_at="2099-01-01T00:00:00+00:00", retrieved_at="2099-01-01T00:00:00+00:00")
    assert callbacks[0](future) is False
    assert owner.read(lease, scope=config["scope"])["status"] == "stale"
    owner.close()


@pytest.mark.unit
def test_failed_close_is_visible_and_cannot_start_a_second_owner():
    module, config = acquisition_module(), binding()
    def fail_close():
        raise RuntimeError("synthetic failed close")
    owner = module.SharedAcquisition()
    owner.register("quote", **config, open_feed=lambda publish: fail_close, authorised=lambda: True)
    lease = owner.acquire("quote", scope=config["scope"])["lease_id"]
    with pytest.raises(RuntimeError):
        owner.release(lease, scope=config["scope"])
    assert owner.diagnostics()["retirement_pending"] == 1
    with pytest.raises(RuntimeError):
        owner.acquire("quote", scope=config["scope"])
