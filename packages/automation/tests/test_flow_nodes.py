"""Tests for FlintTrade flow node system.

Covers all 8 node types, FlowExecutor (linear + DAG), and error handling.

Run with:
    python -m pytest packages/automation/tests/test_flow_nodes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(**variables):
    from packages.automation.src.flow_nodes.base import FlowContext  # noqa: PLC0415
    return FlowContext(variables=dict(variables))


# ---------------------------------------------------------------------------
# Logic gates
# ---------------------------------------------------------------------------


class TestAndGate:
    """Tests for AndGate."""

    def test_all_true(self):
        from packages.automation.src.flow_nodes import AndGate  # noqa: PLC0415
        ctx = _ctx(a=True, b=True)
        result = AndGate(inputs=["a", "b"]).execute(ctx)
        assert result.success
        assert result.output is True

    def test_one_false(self):
        from packages.automation.src.flow_nodes import AndGate  # noqa: PLC0415
        ctx = _ctx(a=True, b=False)
        result = AndGate(inputs=["a", "b"]).execute(ctx)
        assert result.output is False

    def test_all_false(self):
        from packages.automation.src.flow_nodes import AndGate  # noqa: PLC0415
        ctx = _ctx(a=False, b=False)
        assert AndGate(inputs=["a", "b"]).execute(ctx).output is False

    def test_empty_inputs_vacuous_true(self):
        from packages.automation.src.flow_nodes import AndGate  # noqa: PLC0415
        result = AndGate(inputs=[]).execute(_ctx())
        assert result.output is True

    def test_missing_variable_treated_as_false(self):
        from packages.automation.src.flow_nodes import AndGate  # noqa: PLC0415
        ctx = _ctx(a=True)
        result = AndGate(inputs=["a", "missing"]).execute(ctx)
        assert result.output is False


class TestOrGate:
    """Tests for OrGate."""

    def test_one_true(self):
        from packages.automation.src.flow_nodes import OrGate  # noqa: PLC0415
        ctx = _ctx(a=False, b=True)
        assert OrGate(inputs=["a", "b"]).execute(ctx).output is True

    def test_all_false(self):
        from packages.automation.src.flow_nodes import OrGate  # noqa: PLC0415
        ctx = _ctx(a=False, b=False)
        assert OrGate(inputs=["a", "b"]).execute(ctx).output is False

    def test_empty_inputs_returns_false(self):
        from packages.automation.src.flow_nodes import OrGate  # noqa: PLC0415
        assert OrGate(inputs=[]).execute(_ctx()).output is False


class TestNotGate:
    """Tests for NotGate."""

    def test_negate_true(self):
        from packages.automation.src.flow_nodes import NotGate  # noqa: PLC0415
        assert NotGate(input_var="x").execute(_ctx(x=True)).output is False

    def test_negate_false(self):
        from packages.automation.src.flow_nodes import NotGate  # noqa: PLC0415
        assert NotGate(input_var="x").execute(_ctx(x=False)).output is True

    def test_negate_missing_variable(self):
        from packages.automation.src.flow_nodes import NotGate  # noqa: PLC0415
        # Missing var is None → falsy → NOT → True
        assert NotGate(input_var="absent").execute(_ctx()).output is True


class TestXorGate:
    """Tests for XorGate."""

    def test_different_values(self):
        from packages.automation.src.flow_nodes import XorGate  # noqa: PLC0415
        ctx = _ctx(a=True, b=False)
        assert XorGate(input_a="a", input_b="b").execute(ctx).output is True

    def test_same_values_true(self):
        from packages.automation.src.flow_nodes import XorGate  # noqa: PLC0415
        ctx = _ctx(a=True, b=True)
        assert XorGate(input_a="a", input_b="b").execute(ctx).output is False

    def test_same_values_false(self):
        from packages.automation.src.flow_nodes import XorGate  # noqa: PLC0415
        ctx = _ctx(a=False, b=False)
        assert XorGate(input_a="a", input_b="b").execute(ctx).output is False


# ---------------------------------------------------------------------------
# Delay node
# ---------------------------------------------------------------------------


class TestDelayNode:
    """Tests for DelayNode."""

    def test_delay_zero_succeeds(self):
        from packages.automation.src.flow_nodes import DelayNode  # noqa: PLC0415
        result = DelayNode(seconds=0).execute(_ctx())
        assert result.success
        assert result.output >= 0

    def test_delay_negative_raises(self):
        from packages.automation.src.flow_nodes import DelayNode  # noqa: PLC0415
        with pytest.raises(ValueError, match=">= 0"):
            DelayNode(seconds=-1)

    def test_delay_output_is_elapsed(self):
        from packages.automation.src.flow_nodes import DelayNode  # noqa: PLC0415
        result = DelayNode(seconds=0).execute(_ctx())
        assert isinstance(result.output, float)

    def test_delay_requested_seconds_in_metadata(self):
        from packages.automation.src.flow_nodes import DelayNode  # noqa: PLC0415
        result = DelayNode(seconds=0).execute(_ctx())
        assert result.metadata["requested_seconds"] == 0


# ---------------------------------------------------------------------------
# HTTP node
# ---------------------------------------------------------------------------


class TestHTTPRequestNode:
    """Tests for HTTPRequestNode."""

    def test_successful_get(self):
        from packages.automation.src.flow_nodes import HTTPRequestNode  # noqa: PLC0415

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"hello": "world"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client

            node = HTTPRequestNode(url="https://example.com/api", output_var="resp")
            result = node.execute(_ctx())

        assert result.success
        assert result.output == {"hello": "world"}

    def test_http_error_returns_failure(self):
        from packages.automation.src.flow_nodes import HTTPRequestNode  # noqa: PLC0415

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "server error"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client

            node = HTTPRequestNode(url="https://example.com/api")
            result = node.execute(_ctx())

        assert not result.success
        assert "500" in (result.error or "")

    def test_url_placeholder_resolution(self):
        from packages.automation.src.flow_nodes import HTTPRequestNode  # noqa: PLC0415

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        captured_url: list[str] = []

        with patch(
            "packages.automation.src.flow_nodes.http_node._validate_public_url"
        ), patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)

            def capture_request(method, url, **kwargs):  # noqa: ANN001
                captured_url.append(url)
                return mock_response

            mock_client.request.side_effect = capture_request
            mock_client_cls.return_value = mock_client

            node = HTTPRequestNode(url="https://api.example.com/{symbol}")
            node.execute(_ctx(symbol="NIFTY"))

        assert captured_url[0] == "https://api.example.com/NIFTY"

    def test_output_var_written_to_context(self):
        from packages.automation.src.flow_nodes import HTTPRequestNode  # noqa: PLC0415

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"price": 100}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request.return_value = mock_response
            mock_client_cls.return_value = mock_client

            ctx = _ctx()
            HTTPRequestNode(url="https://x.com", output_var="data").execute(ctx)

        assert ctx.get("data") == {"price": 100}


# ---------------------------------------------------------------------------
# IfThenElse node
# ---------------------------------------------------------------------------


class TestIfThenElseNode:
    """Tests for IfThenElseNode."""

    def test_true_branch_taken(self):
        from packages.automation.src.flow_nodes import IfThenElseNode  # noqa: PLC0415
        ctx = _ctx(signal=True)
        node = IfThenElseNode(condition="signal")
        result = node.execute(ctx)
        assert result.success
        assert result.branch == "true"

    def test_false_branch_taken(self):
        from packages.automation.src.flow_nodes import IfThenElseNode  # noqa: PLC0415
        ctx = _ctx(signal=False)
        result = IfThenElseNode(condition="signal").execute(ctx)
        assert result.branch == "false"

    def test_callable_condition(self):
        from packages.automation.src.flow_nodes import IfThenElseNode  # noqa: PLC0415
        ctx = _ctx(price=110)
        node = IfThenElseNode(condition=lambda c: c.get("price") > 100)
        result = node.execute(ctx)
        assert result.branch == "true"

    def test_true_branch_nodes_executed(self):
        from packages.automation.src.flow_nodes import IfThenElseNode, MathNode  # noqa: PLC0415
        ctx = _ctx(x=5, signal=True)
        math = MathNode("add", ["x", 10], output_var="result")
        math.node_id = "math1"
        node = IfThenElseNode(condition="signal", true_branch=[math])
        result = node.execute(ctx)
        assert result.success
        assert ctx.get("result") == 15.0

    def test_false_branch_nodes_executed(self):
        from packages.automation.src.flow_nodes import IfThenElseNode, MathNode  # noqa: PLC0415
        ctx = _ctx(x=5, signal=False)
        math = MathNode("mul", ["x", 2], output_var="result")
        math.node_id = "math2"
        node = IfThenElseNode(condition="signal", false_branch=[math])
        node.execute(ctx)
        assert ctx.get("result") == 10.0


# ---------------------------------------------------------------------------
# Switch node
# ---------------------------------------------------------------------------


class TestSwitchNode:
    """Tests for SwitchNode."""

    def test_matching_case(self):
        from packages.automation.src.flow_nodes import SwitchNode  # noqa: PLC0415
        ctx = _ctx(mode="buy")
        node = SwitchNode(value="mode", cases={"buy": [], "sell": []})
        result = node.execute(ctx)
        assert result.branch == "buy"

    def test_default_case(self):
        from packages.automation.src.flow_nodes import SwitchNode  # noqa: PLC0415
        ctx = _ctx(mode="unknown")
        node = SwitchNode(value="mode", cases={"buy": []}, default=[])
        result = node.execute(ctx)
        assert result.branch == "default"

    def test_no_match_no_default(self):
        from packages.automation.src.flow_nodes import SwitchNode  # noqa: PLC0415
        ctx = _ctx(mode="unknown")
        result = SwitchNode(value="mode", cases={"buy": []}).execute(ctx)
        assert result.branch is None

    def test_callable_value(self):
        from packages.automation.src.flow_nodes import SwitchNode  # noqa: PLC0415
        ctx = _ctx(price=200)
        node = SwitchNode(
            value=lambda c: "high" if c.get("price") > 100 else "low",
            cases={"high": [], "low": []},
        )
        result = node.execute(ctx)
        assert result.branch == "high"


# ---------------------------------------------------------------------------
# Math node
# ---------------------------------------------------------------------------


class TestMathNode:
    """Tests for MathNode."""

    def test_add(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("add", [10, 20]).execute(_ctx())
        assert result.output == 30.0

    def test_sub(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("sub", [50, 20]).execute(_ctx())
        assert result.output == 30.0

    def test_mul(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("mul", [5, 4]).execute(_ctx())
        assert result.output == 20.0

    def test_div(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("div", [100, 4]).execute(_ctx())
        assert result.output == 25.0

    def test_mod(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("mod", [10, 3]).execute(_ctx())
        assert result.output == 1.0

    def test_div_by_zero(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("div", [10, 0]).execute(_ctx())
        assert not result.success
        assert "zero" in (result.error or "").lower()

    def test_mod_by_zero(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("mod", [10, 0]).execute(_ctx())
        assert not result.success

    def test_variable_operands(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        ctx = _ctx(price=100, qty=5)
        result = MathNode("mul", ["price", "qty"], output_var="notional").execute(ctx)
        assert result.output == 500.0
        assert ctx.get("notional") == 500.0

    def test_missing_operand_fails(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("add", ["missing_var", 10]).execute(_ctx())
        assert not result.success

    def test_fewer_than_two_operands_raises(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        with pytest.raises(ValueError, match="2 operands"):
            MathNode("add", [10])

    def test_fold_multiple_operands(self):
        from packages.automation.src.flow_nodes import MathNode  # noqa: PLC0415
        result = MathNode("add", [1, 2, 3, 4]).execute(_ctx())
        assert result.output == 10.0


# ---------------------------------------------------------------------------
# Alert node
# ---------------------------------------------------------------------------


class TestAlertNode:
    """Tests for AlertNode."""

    def test_log_channel_always_succeeds(self):
        from packages.automation.src.flow_nodes import AlertNode  # noqa: PLC0415
        result = AlertNode(channel="log", message="Hello {name}").execute(_ctx(name="NIFTY"))
        assert result.success
        assert result.output == "Hello NIFTY"

    def test_telegram_channel_calls_fn(self):
        from packages.automation.src.flow_nodes import AlertNode  # noqa: PLC0415
        fn = MagicMock()
        node = AlertNode(channel="telegram", message="Signal!", channel_fn=fn)
        result = node.execute(_ctx())
        fn.assert_called_once_with("Signal!")
        assert result.success

    def test_missing_channel_fn_fails(self):
        from packages.automation.src.flow_nodes import AlertNode  # noqa: PLC0415
        result = AlertNode(channel="telegram", message="Test").execute(_ctx())
        assert not result.success
        assert "channel_fn" in (result.error or "")

    def test_template_missing_var_fails(self):
        from packages.automation.src.flow_nodes import AlertNode  # noqa: PLC0415
        result = AlertNode(channel="log", message="Hello {missing}").execute(_ctx())
        assert not result.success

    def test_channel_in_metadata(self):
        from packages.automation.src.flow_nodes import AlertNode  # noqa: PLC0415
        result = AlertNode(channel="log", message="Hi").execute(_ctx())
        assert result.metadata.get("channel") == "log"


# ---------------------------------------------------------------------------
# Order node
# ---------------------------------------------------------------------------


class TestOrderNode:
    """Tests for OrderNode."""

    def _make_place_fn(self, response=None):
        fn = MagicMock(return_value=response or {"status": "success", "orderid": "ORD001"})
        return fn

    def test_successful_order(self):
        from packages.automation.src.flow_nodes import OrderNode  # noqa: PLC0415
        fn = self._make_place_fn()
        node = OrderNode(
            symbol="NIFTY", exchange="NFO", qty=50,
            action="BUY", place_order_fn=fn,
        )
        result = node.execute(_ctx())
        assert result.success
        fn.assert_called_once()

    def test_order_params_built_correctly(self):
        from packages.automation.src.flow_nodes import OrderNode  # noqa: PLC0415
        fn = self._make_place_fn()
        OrderNode(
            symbol="BANKNIFTY", exchange="NFO", qty=25,
            action="SELL", place_order_fn=fn,
        ).execute(_ctx())
        params = fn.call_args[0][0]
        assert params["symbol"] == "BANKNIFTY"
        assert params["action"] == "SELL"
        assert params["quantity"] == "25"

    def test_variable_qty_resolved(self):
        from packages.automation.src.flow_nodes import OrderNode  # noqa: PLC0415
        fn = self._make_place_fn()
        ctx = _ctx(lot_size=75)
        OrderNode(
            symbol="NIFTY", exchange="NFO", qty="lot_size",
            action="BUY", place_order_fn=fn,
        ).execute(ctx)
        params = fn.call_args[0][0]
        assert params["quantity"] == "75"

    def test_place_order_fn_error_returns_failure(self):
        from packages.automation.src.flow_nodes import OrderNode  # noqa: PLC0415
        fn = MagicMock(side_effect=RuntimeError("Broker error"))
        result = OrderNode(
            symbol="NIFTY", exchange="NFO", qty=50,
            action="BUY", place_order_fn=fn,
        ).execute(_ctx())
        assert not result.success
        assert "Broker error" in (result.error or "")

    def test_output_var_written(self):
        from packages.automation.src.flow_nodes import OrderNode  # noqa: PLC0415
        fn = self._make_place_fn({"status": "success", "orderid": "ORD999"})
        ctx = _ctx()
        OrderNode(
            symbol="NIFTY", exchange="NFO", qty=50, action="BUY",
            place_order_fn=fn, output_var="order_result",
        ).execute(ctx)
        assert ctx.get("order_result") == {"status": "success", "orderid": "ORD999"}


# ---------------------------------------------------------------------------
# FlowExecutor — linear
# ---------------------------------------------------------------------------


class TestFlowExecutorLinear:
    """Tests for FlowExecutor.run_linear()."""

    def test_linear_all_succeed(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        nodes = [
            MathNode("add", [10, 5], output_var="a"),
            MathNode("mul", ["a", 2], output_var="b"),
        ]
        result = FlowExecutor().run_linear(nodes)
        assert result.success
        assert result.context.get("b") == 30.0

    def test_linear_stops_on_failure(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        nodes = [
            MathNode("div", [10, 0]),  # fails
            MathNode("add", [1, 1], output_var="should_not_run"),
        ]
        result = FlowExecutor().run_linear(nodes)
        assert not result.success
        assert result.context.get("should_not_run") is None

    def test_linear_continue_on_error(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        nodes = [
            MathNode("div", [10, 0]),  # fails
            MathNode("add", [1, 1], output_var="ran"),
        ]
        result = FlowExecutor(continue_on_error=True).run_linear(nodes)
        assert result.context.get("ran") == 2.0

    def test_linear_initial_variables(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        nodes = [MathNode("mul", ["price", 2], output_var="doubled")]
        result = FlowExecutor().run_linear(nodes, initial_variables={"price": 50.0})
        assert result.context.get("doubled") == 100.0

    def test_linear_empty_list(self):
        from packages.automation.src.flow_nodes import FlowExecutor  # noqa: PLC0415
        result = FlowExecutor().run_linear([])
        assert result.success
        assert result.outputs == {}


# ---------------------------------------------------------------------------
# FlowExecutor — DAG
# ---------------------------------------------------------------------------


class TestFlowExecutorDAG:
    """Tests for FlowExecutor.run_dag() with dependency ordering."""

    def test_dag_topological_order(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        from packages.automation.src.flow_nodes.executor import NodeSpec  # noqa: PLC0415

        n1 = MathNode("add", [5, 10], output_var="x")
        n2 = MathNode("mul", ["x", 2], output_var="y")

        specs = [
            NodeSpec(node_id="n2", node=n2, depends_on=["n1"]),
            NodeSpec(node_id="n1", node=n1, depends_on=[]),
        ]
        result = FlowExecutor().run_dag(specs)
        assert result.success
        assert result.context.get("y") == 30.0

    def test_dag_cycle_raises(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        from packages.automation.src.flow_nodes.executor import NodeSpec  # noqa: PLC0415

        specs = [
            NodeSpec("a", MathNode("add", [1, 2]), depends_on=["b"]),
            NodeSpec("b", MathNode("add", [1, 2]), depends_on=["a"]),
        ]
        result = FlowExecutor().run_dag(specs)
        assert not result.success
        assert "cycle" in (result.error or "").lower()

    def test_dag_unknown_dependency_raises(self):
        from packages.automation.src.flow_nodes import FlowExecutor, MathNode  # noqa: PLC0415
        from packages.automation.src.flow_nodes.executor import NodeSpec  # noqa: PLC0415

        specs = [
            NodeSpec("a", MathNode("add", [1, 2]), depends_on=["ghost"]),
        ]
        result = FlowExecutor().run_dag(specs)
        assert not result.success


# ---------------------------------------------------------------------------
# FlowContext
# ---------------------------------------------------------------------------


class TestFlowContext:
    """Tests for FlowContext set/get helpers."""

    def test_set_and_get(self):
        from packages.automation.src.flow_nodes import FlowContext  # noqa: PLC0415
        ctx = FlowContext()
        ctx.set("key", 42)
        assert ctx.get("key") == 42

    def test_get_default(self):
        from packages.automation.src.flow_nodes import FlowContext  # noqa: PLC0415
        ctx = FlowContext()
        assert ctx.get("missing", "default") == "default"

    def test_get_missing_returns_none(self):
        from packages.automation.src.flow_nodes import FlowContext  # noqa: PLC0415
        ctx = FlowContext()
        assert ctx.get("missing") is None
