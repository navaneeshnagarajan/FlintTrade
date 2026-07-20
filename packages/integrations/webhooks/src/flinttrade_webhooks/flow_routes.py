"""Flask endpoints for FlowBuilder saved workflows.

Registered as a Blueprint by ``create_flask_app()``; auth is inherited from
the app's global before_request. Backed by :class:`FlowFileStore` (one JSON
file per flow under ``<workspace_dir>/flows/``).

Endpoints (all under ``/api/v1/flows``)
---------------------------------------
GET    ""      — list summaries ``[{id, name, updatedAt, node_count, saved_at}]``
GET    /<id>   — the full stored SavedWorkflow object (plus ``saved_at``)
PUT    /<id>   — upsert; body = the frontend SavedWorkflow (id must match the
                 path). Runs :func:`validate_flow_graph` and returns its issues
                 as a non-blocking ``validation`` array alongside the record.
DELETE /<id>   — delete → 200 / 404

Response conventions match the rest of the API: ``{"status": "success",
"data": ...}`` / ``{"status": "error", "message": "..."}``; HTTP 503 when the
flow store has not been initialised.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .flow_builder import validate_flow_graph
from .flow_store import FLOW_ID_RE, FlowFileStore, FlowStoreError

logger = logging.getLogger("flinttrade.integration.flow_routes")

flows_bp = Blueprint("flows", __name__, url_prefix="/api/v1/flows")

# Module-level singleton — injected by ``init_flow_routes`` at app startup.
_store: FlowFileStore | None = None


def init_flow_routes(store: FlowFileStore) -> None:
    """Inject the :class:`FlowFileStore` instance the blueprint should use."""
    global _store  # noqa: PLW0603
    _store = store
    logger.info("FlowFileStore singleton injected into flow_routes")


def _get_store() -> FlowFileStore | None:
    return _store


def _ok(data: Any, code: int = 200) -> tuple[Response, int]:
    return jsonify({"status": "success", "data": data}), code


def _err(message: str, code: int) -> tuple[Response, int]:
    return jsonify({"status": "error", "message": message}), code


_INVALID_ID_MESSAGE = "Invalid flow id — use 1-64 characters from letters, digits, underscore, or hyphen"


def _graph_from_workflow(
    nodes: list[Any],
    edges: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map React Flow nodes/edges to the ``validate_flow_graph`` shape.

    The frontend node type lives at ``node.data.nodeType``; the validator
    expects a flat ``node_type`` key. Raises :class:`FlowStoreError` when an
    entry is structurally unusable (so the route can 400 rather than 500).
    """
    graph_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise FlowStoreError("Each node must be an object with a string id")
        data = node.get("data")
        node_type = data.get("nodeType") if isinstance(data, dict) else None
        graph_nodes.append({"id": node["id"], "node_type": node_type if isinstance(node_type, str) else ""})
    graph_edges: list[dict[str, Any]] = []
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or not isinstance(edge.get("source"), str)
            or not isinstance(edge.get("target"), str)
        ):
            raise FlowStoreError("Each edge must be an object with string source and target")
        graph_edges.append({"source": edge["source"], "target": edge["target"]})
    return graph_nodes, graph_edges


@flows_bp.route("", methods=["GET"])
def list_flows() -> tuple[Response, int]:
    """List stored workflow summaries, most recently saved first."""
    store = _get_store()
    if store is None:
        return _err("Flow store not initialised", 503)
    return _ok(store.list_flows())


@flows_bp.route("/<flow_id>", methods=["GET"])
def get_flow(flow_id: str) -> tuple[Response, int]:
    """Fetch the full stored workflow object by id."""
    store = _get_store()
    if store is None:
        return _err("Flow store not initialised", 503)
    if not FLOW_ID_RE.fullmatch(flow_id):
        return _err(_INVALID_ID_MESSAGE, 400)
    stored = store.get_flow(flow_id)
    if stored is None:
        return _err("Flow not found", 404)
    return _ok(stored)


@flows_bp.route("/<flow_id>", methods=["PUT"])
def put_flow(flow_id: str) -> tuple[Response, int]:
    """Upsert a SavedWorkflow; validation issues are advisory, never blocking."""
    store = _get_store()
    if store is None:
        return _err("Flow store not initialised", 503)
    if not FLOW_ID_RE.fullmatch(flow_id):
        return _err(_INVALID_ID_MESSAGE, 400)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _err("Request body must be a JSON object", 400)
    if body.get("id") != flow_id:
        return _err("Body id must match the flow id in the URL", 400)
    if not isinstance(body.get("name"), str):
        return _err("name must be a string", 400)
    nodes = body.get("nodes")
    edges = body.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return _err("nodes and edges must be lists", 400)
    try:
        graph_nodes, graph_edges = _graph_from_workflow(nodes, edges)
        saved = store.save_flow(flow_id, body)
    except FlowStoreError as exc:
        return _err(str(exc), 400)
    issues = validate_flow_graph(graph_nodes, graph_edges)
    return _ok({"flow": saved, "validation": [asdict(issue) for issue in issues]})


@flows_bp.route("/<flow_id>", methods=["DELETE"])
def delete_flow(flow_id: str) -> tuple[Response, int]:
    """Delete a stored workflow by id."""
    store = _get_store()
    if store is None:
        return _err("Flow store not initialised", 503)
    if not FLOW_ID_RE.fullmatch(flow_id):
        return _err(_INVALID_ID_MESSAGE, 400)
    if not store.delete_flow(flow_id):
        return _err("Flow not found", 404)
    return _ok({"deleted": flow_id})
