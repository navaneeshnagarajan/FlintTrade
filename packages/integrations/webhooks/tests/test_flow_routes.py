"""Tests for flow_routes.py + flow_store.py — FlowBuilder saved-workflow persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

import flinttrade_webhooks.flow_routes as mod
from flinttrade_webhooks.flow_store import (
    REASON_INVALID_EDGE,
    REASON_INVALID_NODE,
    REASON_TOO_LARGE,
    REJECTION_MESSAGES,
    FlowFileStore,
    FlowStoreError,
)

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


def test_resolved_path_is_a_direct_child_of_base_dir(store):
    """``_path_for`` returns an absolute, normalised path inside ``base_dir``.

    The containment assertion is the store's second traversal guard, below
    the id allowlist: whatever an accepted id produces must sit directly in
    the flows directory, never a sibling or a descendant of one.
    """
    path = store._path_for("flow_ok")

    assert path.is_absolute()
    assert path.name == "flow_ok.json"
    assert str(path.parent) == os.path.abspath(store.base_dir)


def test_relative_base_dir_still_resolves(monkeypatch, tmp_path):
    """A relative ``base_dir`` survives containment — it is absolutised first.

    A lexical prefix check against a relative root would reject every id
    (``"flows/x.json"`` normalises away the ``"./"`` the root still carries),
    so the store absolutises both sides before comparing.
    """
    monkeypatch.chdir(tmp_path)
    store = FlowFileStore(Path("flows"))

    store.save_flow("flow_rel", _workflow("flow_rel"))

    assert (tmp_path / "flows" / "flow_rel.json").is_file()
    assert store.get_flow("flow_rel") is not None
    assert store.delete_flow("flow_rel") is True


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


def test_rejection_bodies_are_the_fixed_table_entries(client):
    """400 messages are the mapped constants, never the exception's own text.

    The route logs the exception and answers with the string its rejection
    code maps to, so no server-side detail can ride out in a response body.
    """
    fid = "flow_1"
    resp = client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, nodes=[{"data": {}}], edges=[]))
    assert resp.get_json()["message"] == REJECTION_MESSAGES[REASON_INVALID_NODE]

    resp = client.put(f"/api/v1/flows/{fid}", json=_workflow(fid, edges=[{"source": "n1"}]))
    assert resp.get_json()["message"] == REJECTION_MESSAGES[REASON_INVALID_EDGE]

    resp = client.put("/api/v1/flows/flow_big", json=_workflow("flow_big", notes="x" * (512 * 1024)))
    assert resp.get_json()["message"] == REJECTION_MESSAGES[REASON_TOO_LARGE]


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


# ---------------------------------------------------------------------------
# Default flows-directory resolution + the one-shot legacy migration
# ---------------------------------------------------------------------------


class TestDefaultFlowsDirMigration:
    """``flows/`` resolves under the workspace and migrates a pre-workspace tree once.

    The store used to fall back to a hardcoded ``~/.flinttrade/flows`` whenever
    importing the workspace resolver raised, which on macOS/Windows wrote the
    operator's saved workflows into a second, invisible directory the
    uninstaller could not purge. The fallback is gone; ``create_flask_app``
    already degrades a failed store construction to the routes' 503 branch.
    """

    @staticmethod
    def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> tuple[Any, Any]:
        """Redirect both the resolver and the legacy probe into ``tmp_path``.

        Clears the workspace environment overrides so the migration probe is
        live, then points the platform-default resolver and the module's
        ``_legacy_flows_dir`` seam at temporary directories — the real home
        directory is never touched.

        Returns:
            The ``(workspace, legacy_flows)`` directories the run will use.
        """
        import flinttrade_core.workspace as workspace_mod

        import flinttrade_webhooks.flow_store as flow_store_mod

        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        workspace = tmp_path / "workspace"
        legacy = tmp_path / "legacy-home" / ".flinttrade" / "flows"
        monkeypatch.setattr(workspace_mod, "_default_home", lambda: workspace)
        monkeypatch.setattr(flow_store_mod, "_legacy_flows_dir", lambda: legacy)
        return workspace, legacy

    def test_fresh_install_resolves_under_workspace_without_copying(self, monkeypatch, tmp_path):
        """No legacy tree: the default lands in the workspace, nothing is created."""
        workspace, legacy = self._isolate(monkeypatch, tmp_path)

        store = FlowFileStore()

        assert store.base_dir == workspace / "flows"
        assert not legacy.exists()
        assert not (workspace / "flows").exists()

    def test_legacy_flows_are_copied_into_the_workspace(self, monkeypatch, tmp_path):
        """Legacy-only: the whole tree travels and the original is retained."""
        workspace, legacy = self._isolate(monkeypatch, tmp_path)

        legacy.mkdir(parents=True)
        legacy.joinpath("flow_1.json").write_text('{"id": "flow_1"}', encoding="utf-8")

        store = FlowFileStore()

        assert store.base_dir == workspace / "flows"
        assert (workspace / "flows" / "flow_1.json").read_text(encoding="utf-8") == '{"id": "flow_1"}'
        # Copy, not move — the legacy tree stays behind as a backup.
        assert legacy.joinpath("flow_1.json").exists()

    def test_existing_workspace_flows_are_never_overwritten(self, monkeypatch, tmp_path):
        """Both populated: the workspace wins silently and nothing is merged."""
        workspace, legacy = self._isolate(monkeypatch, tmp_path)

        legacy.mkdir(parents=True)
        legacy.joinpath("flow_legacy.json").write_text('{"id": "flow_legacy"}', encoding="utf-8")
        (workspace / "flows").mkdir(parents=True)
        (workspace / "flows" / "flow_current.json").write_text('{"id": "flow_current"}', encoding="utf-8")

        store = FlowFileStore()

        assert sorted(p.name for p in store.base_dir.iterdir()) == ["flow_current.json"]
        assert legacy.joinpath("flow_legacy.json").exists()

    def test_workspace_override_makes_the_probe_inert(self, monkeypatch, tmp_path):
        """An explicit override wins and suppresses the legacy probe entirely."""
        _workspace, legacy = self._isolate(monkeypatch, tmp_path)

        override = tmp_path / "override"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(override))
        legacy.mkdir(parents=True)
        legacy.joinpath("flow_1.json").write_text('{"id": "flow_1"}', encoding="utf-8")

        store = FlowFileStore()

        assert store.base_dir == override / "flows"
        assert not (override / "flows").exists()

    def test_explicit_base_dir_skips_the_probe(self, monkeypatch, tmp_path):
        """A caller-supplied directory bypasses both the resolver and the probe."""
        _workspace, legacy = self._isolate(monkeypatch, tmp_path)

        legacy.mkdir(parents=True)
        legacy.joinpath("flow_1.json").write_text('{"id": "flow_1"}', encoding="utf-8")

        store = FlowFileStore(tmp_path / "explicit")

        assert store.base_dir == tmp_path / "explicit"
        assert not (tmp_path / "explicit").exists()

    def test_unimportable_workspace_raises_instead_of_shadow_writing(self, monkeypatch, tmp_path):
        """A broken install must fail loudly, never silently write to ``~/.flinttrade``."""
        import sys

        self._isolate(monkeypatch, tmp_path)
        monkeypatch.setitem(sys.modules, "flinttrade_core.workspace", None)

        with pytest.raises(ImportError):
            FlowFileStore()
