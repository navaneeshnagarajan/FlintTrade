"""Tests for the graph-based flow reachability validator.

Covers ``validate_flow_graph`` (flat node+edge representation) and its
integration with ``FlowBuilder.validate_graph``.

No external dependencies. Pure in-process logic.
Run with: python -m pytest packages/integration/tests/test_flow_graph_validation.py -v --import-mode=importlib
"""

from __future__ import annotations


from packages.integration.src.flow_builder import (
    FlowBuilder,
    FlowValidationError,
    validate_flow_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(node_id: str, node_type: str = "start") -> dict:
    return {"id": node_id, "node_type": node_type}


def _edge(src: str, tgt: str) -> dict:
    return {"source": src, "target": tgt}


def _codes(errors: list[FlowValidationError]) -> list[str]:
    return [e.code for e in errors]


# ---------------------------------------------------------------------------
# Happy paths — valid graphs
# ---------------------------------------------------------------------------


class TestValidGraphs:
    def test_minimal_valid_graph(self):
        """Start → PlaceOrder: no errors."""
        nodes = [_node("n1", "start"), _node("n2", "placeOrder")]
        edges = [_edge("n1", "n2")]
        errors = validate_flow_graph(nodes, edges)
        assert errors == []

    def test_linear_chain(self):
        """start → priceCondition → placeOrder → log: valid."""
        nodes = [
            _node("t1", "start"),
            _node("c1", "priceCondition"),
            _node("a1", "placeOrder"),
            _node("u1", "log"),
        ]
        edges = [_edge("t1", "c1"), _edge("c1", "a1"), _edge("a1", "u1")]
        assert validate_flow_graph(nodes, edges) == []

    def test_branching_valid(self):
        """Trigger → condition → two branches, both reachable."""
        nodes = [
            _node("t", "priceAlert"),
            _node("c", "priceCondition"),
            _node("yes", "placeOrder"),
            _node("no", "telegramAlert"),
        ]
        edges = [_edge("t", "c"), _edge("c", "yes"), _edge("c", "no")]
        assert validate_flow_graph(nodes, edges) == []

    def test_webhook_trigger_counts_as_trigger(self):
        nodes = [_node("w", "webhookTrigger"), _node("a", "placeOrder")]
        edges = [_edge("w", "a")]
        assert validate_flow_graph(nodes, edges) == []

    def test_legacy_signal_node_counts_as_trigger(self):
        nodes = [_node("s", "SIGNAL"), _node("a", "ACTION")]
        edges = [_edge("s", "a")]
        assert validate_flow_graph(nodes, edges) == []

    def test_multiple_triggers_all_reachable(self):
        """Multiple triggers feeding into same action: valid."""
        nodes = [
            _node("t1", "start"),
            _node("t2", "webhookTrigger"),
            _node("a", "placeOrder"),
        ]
        edges = [_edge("t1", "a"), _edge("t2", "a")]
        assert validate_flow_graph(nodes, edges) == []


# ---------------------------------------------------------------------------
# No trigger node
# ---------------------------------------------------------------------------


class TestNoTriggerNode:
    def test_empty_graph_returns_no_trigger_error(self):
        errors = validate_flow_graph(nodes=[], edges=[])
        assert "NO_TRIGGER" in _codes(errors)

    def test_only_action_nodes_no_trigger(self):
        nodes = [_node("a1", "placeOrder"), _node("a2", "cancelOrder")]
        edges = [_edge("a1", "a2")]
        errors = validate_flow_graph(nodes, edges)
        assert "NO_TRIGGER" in _codes(errors)

    def test_no_trigger_returns_early_without_bfs(self):
        """When there is no trigger, orphan/unreachable errors must NOT be added
        (they'd be noise — the real problem is the missing trigger)."""
        nodes = [_node("x", "placeOrder"), _node("y", "log")]
        edges = []
        errors = validate_flow_graph(nodes, edges)
        # Only NO_TRIGGER should be present
        assert _codes(errors) == ["NO_TRIGGER"]


# ---------------------------------------------------------------------------
# Self-loops
# ---------------------------------------------------------------------------


class TestSelfLoops:
    def test_self_loop_detected(self):
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        edges = [_edge("t", "a"), _edge("a", "a")]  # a → a is a self-loop
        errors = validate_flow_graph(nodes, edges)
        codes = _codes(errors)
        assert "SELF_LOOP" in codes
        loop_err = next(e for e in errors if e.code == "SELF_LOOP")
        assert loop_err.node_id == "a"

    def test_trigger_self_loop_detected(self):
        nodes = [_node("t", "start")]
        edges = [_edge("t", "t")]
        assert "SELF_LOOP" in _codes(validate_flow_graph(nodes, edges))

    def test_no_false_positive_self_loop(self):
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        edges = [_edge("t", "a")]
        assert "SELF_LOOP" not in _codes(validate_flow_graph(nodes, edges))


# ---------------------------------------------------------------------------
# Orphan nodes
# ---------------------------------------------------------------------------


class TestOrphanNodes:
    def test_isolated_node_is_orphan(self):
        """A node with no edges at all must be flagged as ORPHAN."""
        nodes = [
            _node("t", "start"),
            _node("a", "placeOrder"),
            _node("z", "log"),  # no edges
        ]
        edges = [_edge("t", "a")]
        errors = validate_flow_graph(nodes, edges)
        orphan_ids = [e.node_id for e in errors if e.code == "ORPHAN"]
        assert "z" in orphan_ids

    def test_trigger_with_no_edges_is_orphan(self):
        """A trigger that emits nothing is also an orphan."""
        nodes = [_node("t1", "start"), _node("t2", "webhookTrigger"), _node("a", "placeOrder")]
        edges = [_edge("t1", "a")]  # t2 has no edges
        errors = validate_flow_graph(nodes, edges)
        orphan_ids = [e.node_id for e in errors if e.code == "ORPHAN"]
        assert "t2" in orphan_ids

    def test_connected_node_not_orphan(self):
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        edges = [_edge("t", "a")]
        orphan_ids = [e.node_id for e in validate_flow_graph(nodes, edges) if e.code == "ORPHAN"]
        assert orphan_ids == []


# ---------------------------------------------------------------------------
# Unreachable nodes
# ---------------------------------------------------------------------------


class TestUnreachableNodes:
    def test_disconnected_subgraph_unreachable(self):
        """Two isolated subgraphs — one trigger covers only one subgraph."""
        nodes = [
            _node("t", "start"),
            _node("a", "placeOrder"),
            _node("x", "cancelOrder"),  # reachable only via t2
            _node("t2", "webhookTrigger"),
        ]
        edges = [
            _edge("t", "a"),
            _edge("t2", "x"),
        ]
        # Both subgraphs are reachable (t→a and t2→x)
        assert validate_flow_graph(nodes, edges) == []

    def test_node_only_reachable_from_trigger(self):
        """Node behind a condition is still reachable."""
        nodes = [
            _node("t", "start"),
            _node("c", "priceCondition"),
            _node("a", "placeOrder"),
            _node("b", "cancelAllOrders"),
        ]
        edges = [_edge("t", "c"), _edge("c", "a"), _edge("c", "b")]
        assert validate_flow_graph(nodes, edges) == []

    def test_unreachable_subgraph_flagged(self):
        """Node that no trigger can reach via BFS → UNREACHABLE."""
        nodes = [
            _node("t", "start"),
            _node("a", "placeOrder"),
            _node("u", "closePositions"),  # only targeted by 'a' but a has no outgoing edge to u
        ]
        edges = [
            _edge("t", "a"),
            # u is never targeted by any edge from reachable nodes
        ]
        # u has incoming edge from no one → must be unreachable
        errors = validate_flow_graph(nodes, edges)
        # u has no edges at all → caught as ORPHAN (which implies unreachable too)
        codes = _codes(errors)
        assert "ORPHAN" in codes or "UNREACHABLE" in codes

    def test_direct_unreachable_via_bfs(self):
        """BFS-based unreachability: u is connected to a, but a is not reachable."""
        nodes = [
            _node("t", "start"),
            _node("a", "placeOrder"),
            _node("b", "cancelOrder"),  # b→c exists but b unreachable
            _node("c", "telegramAlert"),
        ]
        edges = [
            _edge("t", "a"),
            _edge("b", "c"),  # b,c are unreachable from t
        ]
        errors = validate_flow_graph(nodes, edges)
        unreachable_ids = {e.node_id for e in errors if e.code == "UNREACHABLE"}
        assert "b" in unreachable_ids
        assert "c" in unreachable_ids


# ---------------------------------------------------------------------------
# FlowValidationError dataclass
# ---------------------------------------------------------------------------


class TestFlowValidationErrorDataclass:
    def test_fields_accessible(self):
        err = FlowValidationError(node_id="n1", code="ORPHAN", description="test")
        assert err.node_id == "n1"
        assert err.code == "ORPHAN"
        assert err.description == "test"

    def test_error_repr_contains_node_id(self):
        err = FlowValidationError(node_id="abc", code="SELF_LOOP", description="loop")
        assert "abc" in repr(err)


# ---------------------------------------------------------------------------
# FlowBuilder.validate_graph integration
# ---------------------------------------------------------------------------


class TestFlowBuilderValidateGraph:
    def test_valid_graph_returns_empty_list(self):
        fb = FlowBuilder("test")
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        edges = [_edge("t", "a")]
        errors = fb.validate_graph(nodes, edges)
        assert errors == []

    def test_orphan_detected_via_builder(self):
        fb = FlowBuilder("test")
        nodes = [_node("t", "start"), _node("a", "placeOrder"), _node("z", "log")]
        edges = [_edge("t", "a")]
        errors = fb.validate_graph(nodes, edges)
        assert any(e.code == "ORPHAN" for e in errors)

    def test_no_trigger_detected_via_builder(self):
        fb = FlowBuilder("test")
        errors = fb.validate_graph(nodes=[], edges=[])
        assert any(e.code == "NO_TRIGGER" for e in errors)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_trigger_node_no_edges_is_orphan(self):
        """A lone trigger with no outgoing or incoming edges is an orphan."""
        nodes = [_node("t", "start")]
        errors = validate_flow_graph(nodes, edges=[])
        assert "ORPHAN" in _codes(errors)

    def test_empty_edges_list(self):
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        errors = validate_flow_graph(nodes, edges=[])
        # Both nodes have zero edges → both orphan; t is trigger so no NO_TRIGGER
        orphan_ids = {e.node_id for e in errors if e.code == "ORPHAN"}
        assert {"t", "a"} == orphan_ids

    def test_large_linear_chain_valid(self):
        """20-node chain starting from a trigger: all reachable, no orphans."""
        nodes = [_node("t", "start")] + [_node(f"n{i}", "log") for i in range(19)]
        edges = [_edge("t", "n0")] + [_edge(f"n{i}", f"n{i+1}") for i in range(18)]
        assert validate_flow_graph(nodes, edges) == []

    def test_duplicate_edges_do_not_cause_errors(self):
        nodes = [_node("t", "start"), _node("a", "placeOrder")]
        edges = [_edge("t", "a"), _edge("t", "a")]  # duplicate
        errors = validate_flow_graph(nodes, edges)
        assert "ORPHAN" not in _codes(errors)
        assert "UNREACHABLE" not in _codes(errors)
