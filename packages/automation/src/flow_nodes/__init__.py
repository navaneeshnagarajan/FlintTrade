"""FlintTrade flow node library.

Provides 8 node types for building visual automation flows as DAGs.
Every node implements :class:`FlowNode` and returns a :class:`FlowResult`.

Usage::

    from packages.automation.src.flow_nodes import (
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

from .base import FlowContext, FlowNode, FlowResult
from .logic_gate import AndGate, NotGate, OrGate, XorGate
from .delay_node import DelayNode
from .http_node import HTTPRequestNode
from .condition_node import IfThenElseNode
from .switch_node import SwitchNode
from .math_node import MathNode
from .alert_node import AlertNode
from .order_node import OrderNode
from .executor import FlowExecutor

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
