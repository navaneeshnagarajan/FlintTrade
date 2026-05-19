"""Extended tests for FlowBuilder — node creation, edge connection, validation, serialization.

Covers all 54 node types, the node registry, and both legacy and new APIs.
No external dependencies. Pure in-process logic.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Enum coverage (legacy)
# ---------------------------------------------------------------------------


class TestLegacyEnums:
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
# NodeType enum — all 54
# ---------------------------------------------------------------------------


class TestNodeTypeEnum:
    def test_total_count_is_54(self):
        from packages.integration.src.flow_builder import NodeType
        assert len(NodeType) == 54

    def test_trigger_types(self):
        from packages.integration.src.flow_builder import NodeType
        triggers = {"start", "priceAlert", "webhookTrigger", "httpRequest"}
        for t in triggers:
            assert NodeType(t) is not None

    def test_action_types(self):
        from packages.integration.src.flow_builder import NodeType
        actions = {
            "placeOrder", "smartOrder", "optionsOrder", "optionsMultiOrder",
            "cancelAllOrders", "closePositions", "cancelOrder", "modifyOrder",
            "basketOrder", "splitOrder",
        }
        for a in actions:
            assert NodeType(a) is not None

    def test_condition_types(self):
        from packages.integration.src.flow_builder import NodeType
        conditions = {"positionCheck", "fundCheck", "timeWindow", "timeCondition", "priceCondition"}
        for c in conditions:
            assert NodeType(c) is not None

    def test_logic_types(self):
        from packages.integration.src.flow_builder import NodeType
        logic = {"andGate", "orGate", "notGate"}
        for logic_type in logic:
            assert NodeType(logic_type) is not None

    def test_data_types(self):
        from packages.integration.src.flow_builder import NodeType
        data = {
            "getQuote", "getDepth", "getOrderStatus", "history", "openPosition",
            "expiry", "intervals", "multiQuotes", "symbol", "optionSymbol",
            "orderBook", "tradeBook", "positionBook", "syntheticFuture",
            "optionChain", "search", "holidays", "timings",
        }
        for d in data:
            assert NodeType(d) is not None

    def test_streaming_types(self):
        from packages.integration.src.flow_builder import NodeType
        streaming = {"subscribeLtp", "subscribeQuote", "subscribeDepth", "unsubscribe"}
        for s in streaming:
            assert NodeType(s) is not None

    def test_risk_types(self):
        from packages.integration.src.flow_builder import NodeType
        risk = {"holdings", "funds", "margin"}
        for r in risk:
            assert NodeType(r) is not None

    def test_utility_types(self):
        from packages.integration.src.flow_builder import NodeType
        utility = {"telegramAlert", "delay", "waitUntil", "group", "variable", "mathExpression", "log"}
        for u in utility:
            assert NodeType(u) is not None


# ---------------------------------------------------------------------------
# Node registry
# ---------------------------------------------------------------------------


class TestNodeRegistry:
    def test_registry_has_54_entries(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY
        assert len(NODE_REGISTRY) == 54

    def test_every_node_type_has_a_spec(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeType
        for nt in NodeType:
            assert nt in NODE_REGISTRY, f"Missing spec for {nt}"

    def test_every_spec_has_label(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY
        for nt, spec in NODE_REGISTRY.items():
            assert spec.label, f"Missing label for {nt}"

    def test_every_spec_has_category(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeCategory
        for nt, spec in NODE_REGISTRY.items():
            assert isinstance(spec.category, NodeCategory), f"Bad category for {nt}"

    def test_every_spec_has_description(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY
        for nt, spec in NODE_REGISTRY.items():
            assert spec.description, f"Missing description for {nt}"

    def test_get_node_spec_by_enum(self):
        from packages.integration.src.flow_builder import NodeType, get_node_spec
        spec = get_node_spec(NodeType.PLACE_ORDER)
        assert spec.label == "Place Order"

    def test_get_node_spec_by_string(self):
        from packages.integration.src.flow_builder import get_node_spec
        spec = get_node_spec("placeOrder")
        assert spec.label == "Place Order"

    def test_get_node_spec_invalid_raises(self):
        from packages.integration.src.flow_builder import get_node_spec
        with pytest.raises((KeyError, ValueError)):
            get_node_spec("nonExistentNode")

    def test_get_all_node_types(self):
        from packages.integration.src.flow_builder import get_all_node_types
        all_types = get_all_node_types()
        assert len(all_types) == 54

    def test_nodes_by_category(self):
        from packages.integration.src.flow_builder import NODES_BY_CATEGORY, NodeCategory
        assert len(NODES_BY_CATEGORY[NodeCategory.TRIGGER]) == 4
        assert len(NODES_BY_CATEGORY[NodeCategory.ACTION]) == 10
        assert len(NODES_BY_CATEGORY[NodeCategory.CONDITION]) == 5
        assert len(NODES_BY_CATEGORY[NodeCategory.LOGIC]) == 3
        assert len(NODES_BY_CATEGORY[NodeCategory.DATA]) == 18
        assert len(NODES_BY_CATEGORY[NodeCategory.STREAMING]) == 4
        assert len(NODES_BY_CATEGORY[NodeCategory.RISK]) == 3
        assert len(NODES_BY_CATEGORY[NodeCategory.UTILITY]) == 7
        # Confirm total: 4+10+5+3+17+4+3+7 = 53 — hmm, check
        total = sum(len(v) for v in NODES_BY_CATEGORY.values())
        assert total == 54  # must match NodeType enum count

    def test_get_node_types_by_category(self):
        from packages.integration.src.flow_builder import NodeCategory, NodeType, get_node_types_by_category
        triggers = get_node_types_by_category(NodeCategory.TRIGGER)
        assert NodeType.START in triggers
        assert NodeType.PRICE_ALERT in triggers

    def test_config_fields_exist_for_order_nodes(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeType
        order_types = [
            NodeType.PLACE_ORDER, NodeType.SMART_ORDER, NodeType.OPTIONS_ORDER,
            NodeType.MODIFY_ORDER, NodeType.BASKET_ORDER, NodeType.SPLIT_ORDER,
        ]
        for nt in order_types:
            spec = NODE_REGISTRY[nt]
            field_names = {f.name for f in spec.config_fields}
            assert len(field_names) > 0, f"No config fields for {nt}"

    def test_place_order_has_symbol_and_quantity(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeType
        spec = NODE_REGISTRY[NodeType.PLACE_ORDER]
        field_names = {f.name for f in spec.config_fields}
        assert "symbol" in field_names
        assert "quantity" in field_names
        assert "exchange" in field_names
        assert "action" in field_names

    def test_condition_nodes_have_bool_outputs(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeCategory
        for nt, spec in NODE_REGISTRY.items():
            if spec.category == NodeCategory.CONDITION:
                output_names = {o.name for o in spec.outputs}
                assert "yes" in output_names, f"{nt} missing 'yes' output"
                assert "no" in output_names, f"{nt} missing 'no' output"

    def test_logic_gates_have_bool_outputs(self):
        from packages.integration.src.flow_builder import NODE_REGISTRY, NodeCategory
        for nt, spec in NODE_REGISTRY.items():
            if spec.category == NodeCategory.LOGIC:
                output_names = {o.name for o in spec.outputs}
                assert "yes" in output_names, f"{nt} missing 'yes' output"
                assert "no" in output_names, f"{nt} missing 'no' output"


# ---------------------------------------------------------------------------
# Node creation — one test per node type (parametrized)
# ---------------------------------------------------------------------------


class TestNodeCreationAllTypes:
    """Test that every node type can be created via FlowBuilder.add_node()."""

    def test_create_all_54_node_types(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("AllNodes")
        ids: list[str] = []
        for nt in NodeType:
            nid = fb.add_node(nt, label=f"Test {nt.value}")
            ids.append(nid)
        flow = fb.build()
        assert len(flow.nodes) == 54
        # All IDs unique
        assert len(set(ids)) == 54

    def test_node_gets_label_from_registry(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("LabelTest")
        nid = fb.add_node(NodeType.TELEGRAM_ALERT)
        flow = fb.build()
        assert flow.nodes[nid].label == "Telegram Alert"

    def test_node_custom_label_overrides_registry(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("LabelTest")
        nid = fb.add_node(NodeType.DELAY, label="Wait 5 Seconds")
        flow = fb.build()
        assert flow.nodes[nid].label == "Wait 5 Seconds"

    def test_node_config_stored(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("ConfigTest")
        nid = fb.add_node(NodeType.PLACE_ORDER, config={"symbol": "NIFTY", "quantity": 75})
        flow = fb.build()
        assert flow.nodes[nid].config["symbol"] == "NIFTY"
        assert flow.nodes[nid].config["quantity"] == 75

    def test_trigger_node_auto_sets_entry(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("EntryTest")
        nid = fb.add_node(NodeType.START, config={"scheduleType": "daily"})
        flow = fb.build()
        assert flow.entry_node_id == nid

    def test_non_trigger_does_not_set_entry(self):
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("NoEntry")
        fb.add_node(NodeType.PLACE_ORDER)
        flow = fb.build()
        assert flow.entry_node_id == ""

    def test_add_node_with_string_type(self):
        from packages.integration.src.flow_builder import FlowBuilder
        fb = FlowBuilder("StringType")
        nid = fb.add_node("start", config={"scheduleType": "once"})
        flow = fb.build()
        assert flow.nodes[nid].node_type == "start"


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
        flow.connect("n1", "n2")
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
            ConditionType, FlowDefinition, FlowNode, SignalSource, validate_flow,
        )
        flow = FlowDefinition(name="Valid", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL",
                               subtype=SignalSource.TRADINGVIEW.value, next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="CONDITION",
                               subtype=ConditionType.PRICE_ABOVE.value, next_nodes=["n3"]))
        flow.add_node(FlowNode(id="n3", node_type="ACTION",
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
        flow.add_node(FlowNode(id="orphan", node_type="EXIT"))
        result = validate_flow(flow)
        assert result.is_valid
        assert any(w.node_id == "orphan" for w in result.warnings)

    def test_entry_not_signal_type_is_warning_not_error(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="W", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="CONDITION", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION"))
        result = validate_flow(flow)
        assert any(w.severity == "warning" for w in result.warnings)

    def test_flow_with_exit_node_valid(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="WithExit", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="EXIT", subtype="TARGET"))
        result = validate_flow(flow)
        assert result.is_valid

    def test_new_api_flow_validates(self):
        """Flow built with new add_node API should validate correctly."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("NewAPI")
        start = fb.add_node(NodeType.START, config={"scheduleType": "daily"})
        order = fb.add_node(NodeType.PLACE_ORDER, config={"symbol": "NIFTY"})
        fb.connect(start, order)
        result = fb.validate()
        assert result.is_valid

    def test_new_api_telegram_is_terminal(self):
        """Utility nodes like Telegram should count as terminal (ACTION-like)."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("TgFlow")
        start = fb.add_node(NodeType.START)
        tg = fb.add_node(NodeType.TELEGRAM_ALERT, config={"message": "Hello"})
        fb.connect(start, tg)
        result = fb.validate()
        assert result.is_valid


# ---------------------------------------------------------------------------
# FlowBuilder — legacy builder API
# ---------------------------------------------------------------------------


class TestFlowBuilderLegacyAPI:
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
        assert len(set(ids)) == 5

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
        from packages.integration.src.flow_builder import FlowBuilder
        fb = FlowBuilder("StrType")
        nid = fb.add_signal("PYTHON_SCRIPT")
        flow = fb.build()
        assert flow.nodes[nid].subtype == "PYTHON_SCRIPT"


# ---------------------------------------------------------------------------
# Full end-to-end flow: Signal -> Condition -> Action -> Exit (legacy)
# ---------------------------------------------------------------------------


class TestEndToEndFlowLegacy:
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


# ---------------------------------------------------------------------------
# Full end-to-end flow: new API with 54 node types
# ---------------------------------------------------------------------------


class TestEndToEndFlowNewAPI:
    def test_options_straddle_flow(self):
        """Build a realistic options straddle flow with the new API."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("NIFTY Straddle", description="Daily straddle at 09:16")
        start = fb.add_node(NodeType.START, config={"scheduleType": "daily", "time": "09:16"})
        quote = fb.add_node(NodeType.GET_QUOTE, config={"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        ce = fb.add_node(NodeType.OPTIONS_ORDER, label="Sell CE", config={
            "underlying": "NIFTY", "optionType": "CE", "action": "SELL", "quantity": 75,
        })
        pe = fb.add_node(NodeType.OPTIONS_ORDER, label="Sell PE", config={
            "underlying": "NIFTY", "optionType": "PE", "action": "SELL", "quantity": 75,
        })
        tg = fb.add_node(NodeType.TELEGRAM_ALERT, config={"message": "Straddle placed"})

        fb.connect(start, quote)
        fb.connect(quote, ce)
        fb.connect(quote, pe)
        fb.connect(ce, tg)

        result = fb.validate()
        assert result.is_valid
        assert len(fb.build().nodes) == 5

    def test_price_alert_flow(self):
        """Price alert -> condition -> order flow."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("Price Breakout")
        alert = fb.add_node(NodeType.PRICE_ALERT, config={
            "symbol": "RELIANCE", "exchange": "NSE", "condition": "crosses_above", "price": 2800,
        })
        check = fb.add_node(NodeType.FUND_CHECK, config={"minFunds": 50000})
        order = fb.add_node(NodeType.PLACE_ORDER, config={
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10,
        })
        fb.connect(alert, check)
        fb.connect(check, order)
        result = fb.validate()
        assert result.is_valid

    def test_data_pipeline_flow(self):
        """Data fetch -> math -> log flow."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("Data Pipeline")
        start = fb.add_node(NodeType.START, config={"scheduleType": "interval", "intervalValue": 5})
        ltp = fb.add_node(NodeType.SUBSCRIBE_LTP, config={"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        math = fb.add_node(NodeType.MATH_EXPRESSION, config={
            "expression": "{{ltp}} * 1.01", "outputVariable": "target",
        })
        log = fb.add_node(NodeType.LOG, config={"message": "Target: {{target}}"})
        fb.connect(start, ltp)
        fb.connect(ltp, math)
        fb.connect(math, log)
        result = fb.validate()
        assert result.is_valid

    def test_logic_gate_flow(self):
        """Multiple conditions -> AND gate -> order."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType
        fb = FlowBuilder("Multi-Condition")
        start = fb.add_node(NodeType.START)
        time_ok = fb.add_node(NodeType.TIME_WINDOW, config={"startTime": "09:15", "endTime": "15:20"})
        price_ok = fb.add_node(NodeType.PRICE_CONDITION, config={
            "symbol": "NIFTY", "exchange": "NSE_INDEX", "operator": "greater_than", "value": 24000,
        })
        gate = fb.add_node(NodeType.AND_GATE)
        order = fb.add_node(NodeType.PLACE_ORDER, config={"symbol": "NIFTY", "action": "BUY"})

        fb.connect(start, time_ok)
        fb.connect(start, price_ok)
        fb.connect(time_ok, gate)
        fb.connect(price_ok, gate)
        fb.connect(gate, order)

        result = fb.validate()
        assert result.is_valid

    def test_mixed_legacy_and_new_api(self):
        """Legacy add_signal + new add_node should coexist."""
        from packages.integration.src.flow_builder import FlowBuilder, NodeType, SignalSource
        fb = FlowBuilder("Mixed")
        sig = fb.add_signal(SignalSource.TRADINGVIEW)
        order = fb.add_node(NodeType.PLACE_ORDER, config={"symbol": "NIFTY"})
        fb.connect(sig, order)
        result = fb.validate()
        assert result.is_valid

    def test_serialization_roundtrip_new_api(self):
        """Flow built with new API serializes and restores correctly."""
        from packages.integration.src.flow_builder import FlowBuilder, FlowDefinition, NodeType
        fb = FlowBuilder("Roundtrip")
        start = fb.add_node(NodeType.START)
        delay = fb.add_node(NodeType.DELAY, config={"delayValue": 5, "delayUnit": "seconds"})
        log = fb.add_node(NodeType.LOG, config={"message": "Hello"})
        fb.connect(start, delay)
        fb.connect(delay, log)

        json_str = fb.to_json()
        restored = FlowDefinition.from_json(json_str)
        assert restored.name == "Roundtrip"
        assert len(restored.nodes) == 3
        # Verify connections survived roundtrip
        start_node = restored.nodes[start]
        assert delay in start_node.next_nodes
