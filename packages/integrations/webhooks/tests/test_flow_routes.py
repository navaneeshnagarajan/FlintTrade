"""Tests for flow_routes.py + flow_store.py — FlowBuilder saved-workflow persistence."""

from __future__ import annotations

import json
from typing import Any

import pytest
from flask import Flask

import flinttrade_webhooks.flow_routes as mod
from flinttrade_webhooks.flow_store import FlowFileStore, FlowStoreError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _workflow(flow_id: str = "flow_1720000000000", **overrides: Any) -> dict[str, Any]:
    """A minimal valid SavedWorkflow body (trigger → action, connected)."""
    body: dict[str, Any] = {
        "id": flow_id,
        "name": "My flow",
        "nodes": [
            {
                "id": "n1",
                "type": "flowNode",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Start", "nodeType": "start", "category": "trigger", "color": "#0f0", "config": {}},
            },
            {
                "id": "n2",
                "type": "flowNode",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "Place order",
                    "nodeType": "placeOrder",
                    "category": "action",
                    "color": "#f00",
                    "config": {},
                },
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        "updatedAt": "2026-07-20T09:00:00.000Z",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def store(tmp_path):
    return FlowFileStore(tmp_path / "flows")


@pytest.fixture()
def app(store):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_flow_routes(store)
    flask_app.register_blueprint(mod.flows_bp)
    yield flask_app
    mod._store = None  # reset the module singleton between tests


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# CRUD roundtrip
# ---------------------------------------------------------------------------


def test_put_get_list_delete_roundtrip(client, store):
    """PUT persists the SavedWorkflow verbatim + saved_at; GET/list/DELETE agree."""
    body = _workflow()
    resp = client.put(f"/api/v1/flows/{body['id']}", json=body)
    assert resp.status_code == 200
    saved = resp.get_json()
    assert saved["status"] == "success"
    flow = saved["data"]["flow"]
    assert flow["name"] == "My flow"
    assert flow["nodes"] == body["nodes"]
    assert flow["saved_at"]
    assert saved["data"]["validation"] == []

    # File exists on disk with the verbatim payload + saved_at
    on_disk = json.loads((store.base_dir / f"{body['id']}.json").read_text(encoding="utf-8"))
    assert on_disk["updatedAt"] == body["updatedAt"]
    assert on_disk["saved_at"] == flow["saved_at"]

    # GET returns the full stored object
    resp = client.get(f"/api/v1/flows/{body['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == flow

    # List shape
    resp = client.get("/api/v1/flows")
    assert resp.status_code == 200
    listed = resp.get_json()["data"]
    assert listed == [
        {
            "id": body["id"],
            "name": "My flow",
            "updatedAt": body["updatedAt"],
            "node_count": 2,
            "saved_at": flow["saved_at"],
        }
    ]

    # DELETE removes row + file; second delete is 404
    resp = client.delete(f"/api/v1/flows/{body['id']}")
    assert resp.status_code == 200
    assert not (store.base_dir / f"{body['id']}.json").exists()
    assert client.delete(f"/api/v1/flows/{body['id']}").status_code == 404
    assert client.get(f"/api/v1/flows/{body['id']}").status_code == 404


def test_put_is_an_upsert(client):
    """A second PUT for the same id overwrites rather than duplicating."""
    body = _workflow()
    assert client.put(f"/api/v1/flows/{body['id']}", json=body).status_code == 200
    body["name"] = "Renamed flow"
    assert client.put(f"/api/v1/flows/{body['id']}", json=body).status_code == 200
    listed = client.get("/api/v1/flows").get_json()["data"]
    assert [f["name"] for f in listed] == ["Renamed flow"]


def test_list_orders_most_recently_saved_first(client):
    """Summaries come back saved_at-descending."""
    first = _workflow("flow_a", name="First")
    second = _workflow("flow_b", name="Second")
    assert client.put("/api/v1/flows/flow_a", json=first).status_code == 200
    assert client.put("/api/v1/flows/flow_b", json=second).status_code == 200
    listed = client.get("/api/v1/flows").get_json()["data"]
    assert [f["id"] for f in listed] == ["flow_b", "flow_a"] or listed[0]["saved_at"] >= listed[1]["saved_at"]


# ---------------------------------------------------------------------------
# Id validation (path-traversal guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "a.b",
        "x" * 65,
        "sp ace",
        "semi;colon",
    ],
)
def test_invalid_ids_rejected_400(client, bad_id):
    """Out-of-alphabet ids (incl. dot segments) are 400 on every verb."""
    assert client.get(f"/api/v1/flows/{bad_id}").status_code == 400
    assert client.put(f"/api/v1/flows/{bad_id}", json=_workflow(bad_id)).status_code == 400
    assert client.delete(f"/api/v1/flows/{bad_id}").status_code == 400


def test_encoded_slash_traversal_never_reaches_a_flow(client, store):
    """%2F traversal is refused (Werkzeug 404s the segment; the regex would 400)."""
    resp = client.put("/api/v1/flows/..%2F..%2Fescape", json=_workflow("../../escape"))
    assert resp.status_code in (400, 404)
    assert not (store.base_dir.parent / "escape.json").exists()
    assert store.list_flows() == []


def test_store_rejects_traversal_ids_directly(store):
    """The store itself refuses bad ids — defence in depth below the routes."""
    with pytest.raises(FlowStoreError):
        store.save_flow("../escape", _workflow("../escape"))
    with pytest.raises(FlowStoreError):
        store.get_flow("a/b")
    with pytest.raises(FlowStoreError):
        store.delete_flow(".")


def test_trailing_newline_id_rejected_by_routes_and_store(client, store):
    """"abc\\n" must fail the guard everywhere — ``match`` + ``$`` would pass it.

    Werkzeug decodes %0A in a path segment, so PUT /api/v1/flows/abc%0A reaches
    the routes with flow_id == "abc\\n"; a $-anchored ``match`` accepts that and
    writes the file "abc\\n.json". Pins the ``fullmatch`` fix (finding 9).
    """
    resp = client.put("/api/v1/flows/abc%0A", json=_workflow("abc\n"))
    assert resp.status_code == 400
    assert client.get("/api/v1/flows/abc%0A").status_code == 400
    assert client.delete("/api/v1/flows/abc%0A").status_code == 400
    assert store.list_flows() == []
    assert not store.base_dir.exists() or list(store.base_dir.iterdir()) == []

    # Defence in depth: the store itself refuses the id too.
    with pytest.raises(FlowStoreError):
        store.save_flow("abc\n", _workflow("abc\n"))
    with pytest.raises(FlowStoreError):
        store.get_flow("abc\n")
    with pytest.raises(FlowStoreError):
        store.delete_flow("abc\n")


def test_body_id_must_match_path(client):
    resp = client.put("/api/v1/flows/flow_a", json=_workflow("flow_b"))
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# Body validation + size cap
# ---------------------------------------------------------------------------


def test_put_requires_object_body_name_nodes_edges(client):
    fid = "flow_1"
    assert client.put(f"/api/v1/flows/{fid}", data="[]", content_type="application/json").status_code == 400
    assert client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, name=7)).status_code == 400
    assert client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, nodes="nope")).status_code == 400
    assert client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, edges={})).status_code == 400


def test_put_rejects_structurally_unusable_graph_entries(client):
    fid = "flow_1"
    resp = client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, nodes=[{"data": {}}], edges=[]))
    assert resp.status_code == 400
    resp = client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, edges=[{"source": "n1"}]))
    assert resp.status_code == 400


def test_size_cap_512_kib(client, store):
    """An encoded payload beyond 512 KiB is refused and nothing is written."""
    fid = "flow_big"
    body = _workflow(fid, notes="x" * (512 * 1024))
    resp = client.put(f"/api/v1/flows/{fid}", json=body)
    assert resp.status_code == 400
    assert "512" in resp.get_json()["message"]
    assert not (store.base_dir / f"{fid}.json").exists()


# ---------------------------------------------------------------------------
# Validation warnings passthrough (non-blocking)
# ---------------------------------------------------------------------------


def test_validation_issues_returned_but_do_not_block_save(client, store):
    """A trigger-less graph still saves; issues surface in the validation array."""
    fid = "flow_notrigger"
    body = _workflow(fid)
    for node in body["nodes"]:
        node["data"]["nodeType"] = "placeOrder"
    resp = client.put(f"/api/v1/flows/{fid}", json=body)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert (store.base_dir / f"{fid}.json").exists()
    codes = [issue["code"] for issue in data["validation"]]
    assert "NO_TRIGGER" in codes
    assert {"node_id", "code", "description"} <= set(data["validation"][0])


# ---------------------------------------------------------------------------
# 503 degradation when the store is absent
# ---------------------------------------------------------------------------


def test_uninitialised_store_returns_503():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod._store = None
    flask_app.register_blueprint(mod.flows_bp)
    with flask_app.test_client() as c:
        assert c.get("/api/v1/flows").status_code == 503
        assert c.get("/api/v1/flows/flow_1").status_code == 503
        assert c.put("/api/v1/flows/flow_1", json=_workflow("flow_1")).status_code == 503
        assert c.delete("/api/v1/flows/flow_1").status_code == 503


# ---------------------------------------------------------------------------
# Store robustness
# ---------------------------------------------------------------------------


def test_list_skips_unreadable_files(store):
    store.save_flow("flow_ok", _workflow("flow_ok"))
    store.base_dir.joinpath("broken.json").write_text("{not json", encoding="utf-8")
    store.base_dir.joinpath("scalar.json").write_text("42", encoding="utf-8")
    assert [f["id"] for f in store.list_flows()] == ["flow_ok"]


def test_list_on_missing_directory_is_empty(tmp_path):
    assert FlowFileStore(tmp_path / "never-created").list_flows() == []
