"""Versioned histories through the existing pipeline and mounted local reader."""
from __future__ import annotations

from copy import deepcopy

import pytest
from flask import Flask

from flinttrade_backtest.data_connector import DataConnector
from flinttrade_historical.local_data_routes import init_local_data_routes, local_data_bp
from flinttrade_historical.pipeline import DataPipeline

pytestmark = pytest.mark.integration


def history_input():
    identity = {
        "instrument_id": "test-equity", "venue": "XNAS", "asset_class": "equity", "currency": "USD",
        "quantity_unit": "shares", "price_unit": "currency_per_share", "multiplier": "1",
        "interval_seconds": 60, "adjustment": "raw", "calendar_id": "test-session", "calendar_revision": "1",
    }
    scope = {"principal_id": "operator-test", "environment": "research", "account_id": None,
             "run_id": "test-run", "generation": 1}
    policy = {
        "mode": "priority_fill_gaps", "priority": ["first", "second"], "duplicates": "identical_only",
        "conflicts": "prefer_priority", "revision": "test-policy-1",
        "sessions": [{"start": "2026-01-05T14:30:00+00:00", "end": "2026-01-05T14:33:00+00:00"}],
    }

    def bar(minute, close=100):
        return {"timestamp": f"2026-01-05T14:{minute}:00+00:00", "open": 100, "high": 102, "low": 99,
                "close": close, "volume": 0.5, "oi": None, "published_at": None}

    contributors = []
    for name, bars in [("first", [bar(30), bar(30), bar(31)]), ("second", [bar(30, 101), bar(32)])]:
        contributors.append({
            "source": {"connection_id": name, "provider": "inert", "environment": "research", "account_id": None,
                       "auth_generation": 1, "configuration_generation": 1},
            "identity": deepcopy(identity), "revision": "1", "status": "available",
            "retrieved_at": "2026-01-05T15:00:00+00:00", "bars": bars,
        })
    return identity, scope, policy, contributors


def test_history_merge_roundtrip_is_immutable_reproducible_and_readable_at_public_seams(tmp_path):
    identity, scope, policy, contributors = history_input()
    path = str(tmp_path / "history.duckdb")
    with DataPipeline(path) as pipeline:
        assert callable(getattr(pipeline, "publish_history", None)), "canonical publication seam is missing"
        snapshot = pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        assert snapshot["status"] == "available"
        assert snapshot["coverage"]["missing"] == []
        assert [bar["source_id"] for bar in snapshot["bars"]] == ["first", "first", "second"]
        assert len(snapshot["conflicts"]) == 1
        assert snapshot["duplicates"] == {"first": 1, "second": 0}
        snapshot_id = snapshot["snapshot_id"]
        assert pipeline.publish_history(identity=identity, scope=scope, policy=policy,
                                        contributors=contributors)["snapshot_id"] == snapshot_id
        # A reader cannot alter the persisted evidence or the original inputs.
        snapshot["bars"][0]["close"] = 999
        contributors[0]["bars"][0]["close"] = 999
        readback = pipeline.history_snapshot(snapshot_id, scope=scope)
        assert readback["bars"][0]["close"] == 100
        app = Flask(__name__)
        app.config["DATA_SCOPE_RESOLVER"] = lambda: scope
        init_local_data_routes(pipeline=pipeline)
        app.register_blueprint(local_data_bp)
        response = app.test_client().get(f"/v1/historify/snapshots/{snapshot_id}")
        assert response.status_code == 200
        assert response.json["data"] == readback
    # The same immutable inputs remain available after closing the owning store.
    connector = DataConnector(path)
    result = connector.load_manifest(snapshot_id, scope=scope)
    assert result.success
    assert result.manifest["snapshot_id"] == snapshot_id
    assert result.exchange == "XNAS"
    assert result.bars[0]["volume"] == 0.5


@pytest.mark.parametrize("field,value", [
    ("currency", "INR"), ("venue", "XNYS"), ("quantity_unit", "contracts"), ("adjustment", "split-adjusted"),
    ("calendar_revision", "other"), ("instrument_id", "another-listing"),
])
def test_incompatible_contributors_never_publish(tmp_path, field, value):
    identity, scope, policy, contributors = history_input()
    contributors[1]["identity"][field] = value
    with DataPipeline(str(tmp_path / "history.duckdb")) as pipeline:
        with pytest.raises(ValueError, match="incompatible"):
            pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)


@pytest.mark.parametrize("change", ["nan", "range", "negative_volume", "naive", "session", "duplicate", "overlap"])
def test_invalid_observations_are_refused_atomically(tmp_path, change):
    identity, scope, policy, contributors = history_input()
    bar = contributors[0]["bars"][0]
    if change == "nan":
        bar["close"] = float("nan")
    elif change == "range":
        bar["close"] = 103
    elif change == "negative_volume":
        bar["volume"] = -1
    elif change == "naive":
        bar["timestamp"] = "2026-01-05T14:30:00"
    elif change == "session":
        bar["timestamp"] = "2026-01-05T14:30:30+00:00"
    elif change == "duplicate":
        bar["close"] = 101
    else:
        policy["conflicts"] = "reject"
    with DataPipeline(str(tmp_path / "history.duckdb")) as pipeline:
        with pytest.raises(ValueError):
            pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)


def test_failed_source_and_calendar_gap_cannot_be_complete_or_backtest_success(tmp_path):
    identity, scope, policy, contributors = history_input()
    contributors[1].update(status="unavailable", bars=[])
    path = str(tmp_path / "history.duckdb")
    with DataPipeline(path) as pipeline:
        snapshot = pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        assert snapshot["status"] == "partial"
        assert snapshot["coverage"]["missing"] == ["2026-01-05T14:32:00+00:00"]
        with pytest.raises(PermissionError):
            pipeline.history_snapshot(snapshot["snapshot_id"], scope={**scope, "generation": 2})
    result = DataConnector(path).load_manifest(snapshot["snapshot_id"], scope=scope)
    assert not result.success
    assert len(result.bars) == 2  # preserved evidence, not silently padded or discarded


def test_republication_cannot_claim_success_over_corrupt_persisted_evidence(tmp_path):
    identity, scope, policy, contributors = history_input()
    with DataPipeline(str(tmp_path / "history.duckdb")) as pipeline:
        pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        pipeline.connection.execute("UPDATE history_manifests SET document='{}'")
        with pytest.raises(ValueError):
            pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        # No automatic deletion, recreation or repair.
        assert pipeline.connection.execute("SELECT document FROM history_manifests").fetchone()[0] == "{}"
