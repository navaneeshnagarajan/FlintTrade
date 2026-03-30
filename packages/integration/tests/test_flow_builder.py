"""Extended tests for FlowBuilder — node creation, edge connection, validation, serialization.

No external dependencies. Pure in-process logic.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------


class TestFlowEnums:
    def test_node_type_values(self):
        from packages.integration.src.flow_builder import NodeType
        assert NodeType.SIGNAL == "SIGNAL"
        assert NodeType.CONDITION == "CONDITION"
        assert NodeType.ACTION == "ACTION"
        assert NodeType.EXIT == "EXIT"

    def test_signal_source_values(self):
        from packages.integration.src.flow_builder import SignalSource
        assert SignalSource.TRADINGVIEW == "TRADINGVIEW"
        assert SignalSource.CHARTINK == "CHARTINK"
        assert SignalSource.PYTHON_SCRIPT == "PYTHON_SCRIPT"
        assert SignalSource.CRON == "CRON"
        assert SignalSource.MANUAL == "MANUAL"

    def test_condition_types(self):
        from packages.integration.src.flow_builder import ConditionType
        expected = {"PRICE_ABOVE", "PRICE_BELOW", "OI_THRESHOLD", "TIME_WINDOW",
                    "INDICATOR_VALUE", "PCR_ABOVE", "PCR_BELOW"}
        actual = {c.value for c in ConditionType}
        assert expected == actual

    def test_action_types(self):
        from packages.integration.src.flow_builder import ActionType
        expected = {"PLACE_ORDER", "MODIFY_ORDER", "CANCEL_ORDER", "SEND_ALERT", "CLOSE_POSITION"}
        actual = {a.value for a in ActionType}
        assert expected == actual

    def test_exit_types(self):
        from packages.integration.src.flow_builder import ExitType
        expected = {"STOP_LOSS", "TARGET", "TRAILING_SL", "TIME_BASED", "SIGNAL_BASED"}
        actual = {e.value for e in ExitType}
        assert expected == actual


# ---------------------------------------------------------------------------
# FlowNode dataclass
# ---------------------------------------------------------------------------


class TestFlowNode:
    def test_defaults(self):
        from packages.integration.src.flow_builder import FlowNode
        n = FlowNode(id="n1", node_type="SIGNAL")
        assert n.subtype == ""
        assert n.label == ""
        assert n.config == {}
        assert n.next_nodes == []

    def test_to_dict_roundtrip(self):
        from packages.integration.src.flow_builder import FlowNode
        n = FlowNode(
            id="n1", node_type="SIGNAL", subtype="TRADINGVIEW",
            label="TV Alert", config={"strategy": "Flint"},
            next_nodes=["n2"],
        )
        d = n.to_dict()
        restored = FlowNode.from_dict(d)
        assert restored.id == "n1"
        assert restored.node_type == "SIGNAL"
        assert restored.subtype == "TRADINGVIEW"
        assert restored.label == "TV Alert"
        assert restored.config == {"strategy": "Flint"}
        assert restored.next_nodes == ["n2"]

    def test_to_dict_has_all_keys(self):
        from packages.integration.src.flow_builder import FlowNode
        d = FlowNode(id="x", node_type="ACTION").to_dict()
        assert "id" in d
        assert "node_type" in d
        assert "subtype" in d
        assert "label" in d
        assert "config" in d
        assert "next_nodes" in d

    def test_from_dict_missing_optional_keys(self):
        """from_dict must handle minimal dict with just id and node_type."""
        from packages.integration.src.flow_builder import FlowNode
        n = FlowNode.from_dict({"id": "n1", "node_type": "EXIT"})
        assert n.label == ""
        assert n.config == {}
        assert n.next_nodes == []


# ---------------------------------------------------------------------------
# FlowDefinition
# ---------------------------------------------------------------------------


class TestFlowDefinition:
    def test_add_node(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="Test")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        assert "n1" in flow.nodes

    def test_connect_nodes(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="Test")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        flow.connect("n1", "n2")
        assert "n2" in flow.nodes["n1"].next_nodes

    def test_connect_nonexistent_source_raises(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="Test")
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        with pytest.raises(ValueError, match="n1"):
            flow.connect("n1", "n2")

    def test_connect_nonexistent_target_raises(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="Test")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        with pytest.raises(ValueError, match="n99"):
            flow.connect("n1", "n99")

    def test_connect_does_not_duplicate_edges(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="Test", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        flow.connect("n1", "n2")
        flow.connect("n1", "n2")  # duplicate
        assert flow.nodes["n1"].next_nodes.count("n2") == 1

    def test_to_dict_structure(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="S", description="desc", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        d = flow.to_dict()
        assert d["name"] == "S"
        assert d["description"] == "desc"
        assert d["entry_node_id"] == "n1"
        assert "n1" in d["nodes"]

    def test_to_json_is_valid_json(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="X")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        raw = flow.to_json()
        parsed = json.loads(raw)
        assert parsed["name"] == "X"

    def test_from_dict_roundtrip(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="R", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", subtype="MANUAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION", subtype="PLACE_ORDER"))
        restored = FlowDefinition.from_dict(flow.to_dict())
        assert restored.name == "R"
        assert restored.entry_node_id == "n1"
        assert len(restored.nodes) == 2
        assert "n2" in restored.nodes["n1"].next_nodes

    def test_from_json_roundtrip(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode
        flow = FlowDefinition(name="JSON", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL"))
        flow.add_node(FlowNode(id="n2", node_type="EXIT", subtype="STOP_LOSS"))
        flow.connect("n1", "n2")
        restored = FlowDefinition.from_json(flow.to_json())
        assert restored.name == "JSON"
        assert "n2" in restored.nodes["n1"].next_nodes


# ---------------------------------------------------------------------------
# validate_flow — ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_valid_flow_with_signal_condition_action(self):
        from packages.integration.src.flow_builder import (
            ConditionType, FlowDefinition, FlowNode, NodeType, SignalSource, validate_flow,
        )
        flow = FlowDefinition(name="Valid", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type=NodeType.SIGNAL.value,
                               subtype=SignalSource.TRADINGVIEW.value, next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type=NodeType.CONDITION.value,
                               subtype=ConditionType.PRICE_ABOVE.value, next_nodes=["n3"]))
        flow.add_node(FlowNode(id="n3", node_type=NodeType.ACTION.value,
                               subtype="PLACE_ORDER"))
        result = validate_flow(flow)
        assert result.is_valid
        assert result.errors == []

    def test_empty_flow_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, validate_flow
        result = validate_flow(FlowDefinition(name="Empty"))
        assert not result.is_valid
        assert any("no nodes" in e.message.lower() for e in result.errors)

    def test_no_entry_node_id_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="X")
        flow.add_node(FlowNode(id="n1", node_type="ACTION"))
        result = validate_flow(flow)
        assert not result.is_valid
        assert any("entry" in e.message.lower() for e in result.errors)

    def test_entry_node_id_not_in_nodes_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="X", entry_node_id="ghost")
        flow.add_node(FlowNode(id="n1", node_type="ACTION"))
        result = validate_flow(flow)
        assert not result.is_valid
        assert any("ghost" in e.message for e in result.errors)

    def test_broken_next_node_reference_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="X", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n_missing"]))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_self_loop_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Loop", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n1"]))
        result = validate_flow(flow)
        assert not result.is_valid
        assert any("self-loop" in e.message for e in result.errors)

    def test_missing_action_or_exit_invalid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="NoAction", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="CONDITION"))
        result = validate_flow(flow)
        assert not result.is_valid
        assert any("ACTION" in e.message or "EXIT" in e.message for e in result.errors)

    def test_orphan_node_warning(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Orphan", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        flow.add_node(FlowNode(id="orphan", node_type="EXIT"))  # unreachable
        result = validate_flow(flow)
        assert result.is_valid  # warnings don't fail validation
        assert any(w.node_id == "orphan" for w in result.warnings)

    def test_entry_not_signal_type_is_warning_not_error(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="W", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="CONDITION", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        result = validate_flow(flow)
        # Should warn but not fail
        assert any(w.severity == "warning" for w in result.warnings)

    def test_flow_with_exit_node_valid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="WithExit", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="EXIT", subtype="TARGET"))
        result = validate_flow(flow)
        assert result.is_valid


# ---------------------------------------------------------------------------
# FlowBuilder — builder API
# ---------------------------------------------------------------------------


class TestFlowBuilderAPI:
    def test_add_signal_returns_id(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Test")
        sid = fb.add_signal(SignalSource.TRADINGVIEW)
        assert sid.startswith("sig_")

    def test_add_condition_returns_id(self):
        from packages.integration.src.flow_builder import ConditionType, FlowBuilder
        fb = FlowBuilder("Test")
        fb.add_signal("MANUAL")
        cid = fb.add_condition(ConditionType.PRICE_ABOVE)
        assert cid.startswith("cond_")

    def test_add_action_returns_id(self):
        from packages.integration.src.flow_builder import ActionType, FlowBuilder
        fb = FlowBuilder("Test")
        aid = fb.add_action(ActionType.PLACE_ORDER)
        assert aid.startswith("act_")

    def test_add_exit_returns_id(self):
        from packages.integration.src.flow_builder import ExitType, FlowBuilder
        fb = FlowBuilder("Test")
        eid = fb.add_exit(ExitType.STOP_LOSS)
        assert eid.startswith("exit_")

    def test_first_signal_sets_entry_node(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Test")
        sid = fb.add_signal(SignalSource.CRON)
        flow = fb.build()
        assert flow.entry_node_id == sid

    def test_second_signal_does_not_override_entry(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Test")
        first = fb.add_signal(SignalSource.TRADINGVIEW)
        fb.add_signal(SignalSource.CHARTINK)
        flow = fb.build()
        assert flow.entry_node_id == first

    def test_connect_creates_edge(self):
        from packages.integration.src.flow_builder import ActionType, FlowBuilder, SignalSource
        fb = FlowBuilder("Test")
        sig = fb.add_signal(SignalSource.MANUAL)
        act = fb.add_action(ActionType.SEND_ALERT)
        fb.connect(sig, act)
        flow = fb.build()
        assert act in flow.nodes[sig].next_nodes

    def test_connect_nonexistent_node_raises(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Test")
        sig = fb.add_signal(SignalSource.MANUAL)
        with pytest.raises(ValueError, match="not found"):
            fb.connect(sig, "nonexistent_id")

    def test_validate_valid_flow(self):
        from packages.integration.src.flow_builder import ActionType, FlowBuilder, SignalSource
        fb = FlowBuilder("Valid")
        sig = fb.add_signal(SignalSource.TRADINGVIEW)
        act = fb.add_action(ActionType.PLACE_ORDER)
        fb.connect(sig, act)
        result = fb.validate()
        assert result.is_valid

    def test_validate_empty_builder(self):
        from packages.integration.src.flow_builder import FlowBuilder
        fb = FlowBuilder("Empty")
        result = fb.validate()
        assert not result.is_valid

    def test_build_returns_flow_definition(self):
        from packages.integration.src.flow_builder import FlowBuilder, FlowDefinition
        fb = FlowBuilder("MyFlow", description="Test flow")
        flow = fb.build()
        assert isinstance(flow, FlowDefinition)
        assert flow.name == "MyFlow"
        assert flow.description == "Test flow"

    def test_to_json_is_parseable(self):
        from packages.integration.src.flow_builder import ActionType, FlowBuilder, SignalSource
        fb = FlowBuilder("JSONTest")
        sig = fb.add_signal(SignalSource.TRADINGVIEW)
        act = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY"})
        fb.connect(sig, act)
        raw = fb.to_json()
        parsed = json.loads(raw)
        assert parsed["name"] == "JSONTest"
        assert len(parsed["nodes"]) == 2

    def test_node_ids_are_unique(self):
        from packages.integration.src.flow_builder import (
            ActionType, ConditionType, ExitType, FlowBuilder, SignalSource,
        )
        fb = FlowBuilder("Unique")
        ids = [
            fb.add_signal(SignalSource.TRADINGVIEW),
            fb.add_condition(ConditionType.PRICE_ABOVE),
            fb.add_condition(ConditionType.TIME_WINDOW),
            fb.add_action(ActionType.PLACE_ORDER),
            fb.add_exit(ExitType.STOP_LOSS),
        ]
        assert len(set(ids)) == 5  # all unique

    def test_config_stored_on_node(self):
        from packages.integration.src.flow_builder import ActionType, FlowBuilder
        fb = FlowBuilder("Config")
        nid = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY", "quantity": "75"})
        flow = fb.build()
        assert flow.nodes[nid].config["symbol"] == "NIFTY"
        assert flow.nodes[nid].config["quantity"] == "75"

    def test_label_stored_on_node(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Label")
        nid = fb.add_signal(SignalSource.MANUAL, label="Manual Trigger")
        flow = fb.build()
        assert flow.nodes[nid].label == "Manual Trigger"

    def test_subtype_from_string(self):
        """Passing subtype as a plain string (not enum) should still work."""
        from packages.integration.src.flow_builder import FlowBuilder
        fb = FlowBuilder("StrType")
        nid = fb.add_signal("PYTHON_SCRIPT")
        flow = fb.build()
        assert flow.nodes[nid].subtype == "PYTHON_SCRIPT"


# ---------------------------------------------------------------------------
# Full end-to-end flow: Signal → Condition → Action → Exit
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    def _build_full_flow(self):
        from packages.integration.src.flow_builder import (
            ActionType, ConditionType, ExitType, FlowBuilder, SignalSource,
        )
        fb = FlowBuilder("NIFTY Scalper", description="Buy NIFTY on TV signal, SL at 100 pts")
        sig = fb.add_signal(SignalSource.TRADINGVIEW, label="TV BUY Signal",
                            config={"strategy_id": "nifty_scalper"})
        cond = fb.add_condition(ConditionType.TIME_WINDOW, label="Market hours",
                                config={"start": "09:15", "end": "15:20"})
        act = fb.add_action(ActionType.PLACE_ORDER, label="Buy NIFTY",
                            config={"symbol": "NIFTY", "exchange": "NFO", "quantity": "75"})
        exit_ = fb.add_exit(ExitType.STOP_LOSS, label="100pt SL",
                            config={"points": 100})
        fb.connect(sig, cond)
        fb.connect(cond, act)
        fb.connect(act, exit_)
        return fb

    def test_full_flow_validates(self):
        fb = self._build_full_flow()
        result = fb.validate()
        assert result.is_valid
        assert result.errors == []

    def test_full_flow_node_count(self):
        fb = self._build_full_flow()
        assert len(fb.build().nodes) == 4

    def test_full_flow_json_restores_connections(self):
        from packages.integration.src.flow_builder import FlowDefinition
        fb = self._build_full_flow()
        flow = fb.build()
        restored = FlowDefinition.from_json(fb.to_json())
        for nid, node in flow.nodes.items():
            assert nid in restored.nodes
            assert restored.nodes[nid].next_nodes == node.next_nodes

    def test_multiple_actions_one_signal(self):
        """One signal can fan out to multiple actions."""
        from packages.integration.src.flow_builder import ActionType, FlowBuilder, SignalSource
        fb = FlowBuilder("FanOut")
        sig = fb.add_signal(SignalSource.TRADINGVIEW)
        act1 = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY"})
        act2 = fb.add_action(ActionType.SEND_ALERT, config={"channel": "telegram"})
        fb.connect(sig, act1)
        fb.connect(sig, act2)
        flow = fb.build()
        assert act1 in flow.nodes[sig].next_nodes
        assert act2 in flow.nodes[sig].next_nodes
        result = fb.validate()
        assert result.is_valid
