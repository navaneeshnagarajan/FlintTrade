"""FlintTrade flow node library.

Provides 8 node types for building visual automation flows as DAGs.
Every node implements :class:`FlowNode` and returns a :class:`FlowResult`.

Usage::

    from flinttrade_automation.flow_nodes import (
        AndGate, OrGate, NotGate, XorGate,
        DelayNode,
        HTTPRequestNode,
        IfThenElseNode,
        SwitchNode,
        MathNode,
        AlertNode,
        OrderNode,
        FlowContext,
        FlowResult,
        FlowExecutor,
    )
"""

from __future__ import annotations

from .alert_node import AlertNode
from .base import FlowContext, FlowNode, FlowResult
from .condition_node import IfThenElseNode
from .delay_node import DelayNode
from .executor import FlowExecutor
from .http_node import HTTPRequestNode
from .logic_gate import AndGate, NotGate, OrGate, XorGate
from .math_node import MathNode
from .order_node import OrderNode
from .switch_node import SwitchNode

__all__ = [
    # Base
    "FlowNode",
    "FlowContext",
    "FlowResult",
    # Logic gates
    "AndGate",
    "OrGate",
    "NotGate",
    "XorGate",
    # Utility nodes
    "DelayNode",
    "HTTPRequestNode",
    "IfThenElseNode",
    "SwitchNode",
    "MathNode",
    "AlertNode",
    "OrderNode",
    # Executor
    "FlowExecutor",
]
