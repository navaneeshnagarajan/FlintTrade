"""Strategy flow builder — visual strategy definition as connected nodes.

Adapts all 54 node types from openalgo-flow: N8N-style node graph for
defining trading strategies without code.

Categories (8):
- Trigger: Start, PriceAlert, WebhookTrigger, HttpRequest
- Action: PlaceOrder, SmartOrder, OptionsOrder, OptionsMultiOrder,
          CancelAllOrders, ClosePositions, CancelOrder, ModifyOrder,
          BasketOrder, SplitOrder
- Condition: PositionCheck, FundCheck, TimeWindow, TimeCondition, PriceCondition
- Logic: AndGate, OrGate, NotGate
- Data: GetQuote, GetDepth, GetOrderStatus, History, OpenPosition,
        Expiry, Intervals, MultiQuotes, Symbol, OptionSymbol,
        OrderBook, TradeBook, PositionBook, SyntheticFuture, OptionChain,
        Search, Holidays, Timings
- Streaming: SubscribeLTP, SubscribeQuote, SubscribeDepth, Unsubscribe
- Risk: Holdings, Funds, Margin
- Utility: TelegramAlert, Delay, WaitUntil, Group, Variable,
           MathExpression, Log

A Flow is a JSON-serializable graph of connected nodes. The FlowBuilder
validates the graph and FlowRunner executes it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.integration.flow_builder")


# ---------------------------------------------------------------------------
# Node Category
# ---------------------------------------------------------------------------


class NodeCategory(StrEnum):
    TRIGGER = "TRIGGER"
    ACTION = "ACTION"
    CONDITION = "CONDITION"
    LOGIC = "LOGIC"
    DATA = "DATA"
    STREAMING = "STREAMING"
    RISK = "RISK"
    UTILITY = "UTILITY"


# ---------------------------------------------------------------------------
# Node types — all 54 from openalgo-flow
# ---------------------------------------------------------------------------


class NodeType(StrEnum):
    """All 54 node types supported by the flow builder."""

    # --- Trigger (4) ---
    START = "start"
    PRICE_ALERT = "priceAlert"
    WEBHOOK_TRIGGER = "webhookTrigger"
    HTTP_REQUEST = "httpRequest"

    # --- Action (10) ---
    PLACE_ORDER = "placeOrder"
    SMART_ORDER = "smartOrder"
    OPTIONS_ORDER = "optionsOrder"
    OPTIONS_MULTI_ORDER = "optionsMultiOrder"
    CANCEL_ALL_ORDERS = "cancelAllOrders"
    CLOSE_POSITIONS = "closePositions"
    CANCEL_ORDER = "cancelOrder"
    MODIFY_ORDER = "modifyOrder"
    BASKET_ORDER = "basketOrder"
    SPLIT_ORDER = "splitOrder"

    # --- Condition (5) ---
    POSITION_CHECK = "positionCheck"
    FUND_CHECK = "fundCheck"
    TIME_WINDOW = "timeWindow"
    TIME_CONDITION = "timeCondition"
    PRICE_CONDITION = "priceCondition"

    # --- Logic (3) ---
    AND_GATE = "andGate"
    OR_GATE = "orGate"
    NOT_GATE = "notGate"

    # --- Data (18) ---
    GET_QUOTE = "getQuote"
    GET_DEPTH = "getDepth"
    GET_ORDER_STATUS = "getOrderStatus"
    HISTORY = "history"
    OPEN_POSITION = "openPosition"
    EXPIRY = "expiry"
    INTERVALS = "intervals"
    MULTI_QUOTES = "multiQuotes"
    SYMBOL = "symbol"
    OPTION_SYMBOL = "optionSymbol"
    ORDER_BOOK = "orderBook"
    TRADE_BOOK = "tradeBook"
    POSITION_BOOK = "positionBook"
    SYNTHETIC_FUTURE = "syntheticFuture"
    OPTION_CHAIN = "optionChain"
    SEARCH = "search"
    HOLIDAYS = "holidays"
    TIMINGS = "timings"

    # --- Streaming (4) ---
    SUBSCRIBE_LTP = "subscribeLtp"
    SUBSCRIBE_QUOTE = "subscribeQuote"
    SUBSCRIBE_DEPTH = "subscribeDepth"
    UNSUBSCRIBE = "unsubscribe"

    # --- Risk (3) ---
    HOLDINGS = "holdings"
    FUNDS = "funds"
    MARGIN = "margin"

    # --- Utility (8) ---
    TELEGRAM_ALERT = "telegramAlert"
    DELAY = "delay"
    WAIT_UNTIL = "waitUntil"
    GROUP = "group"
    VARIABLE = "variable"
    MATH_EXPRESSION = "mathExpression"
    LOG = "log"


# Legacy aliases for backward compatibility
class SignalSource(StrEnum):
    TRADINGVIEW = "TRADINGVIEW"
    CHARTINK = "CHARTINK"
    PYTHON_SCRIPT = "PYTHON_SCRIPT"
    CRON = "CRON"
    MANUAL = "MANUAL"


class ConditionType(StrEnum):
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    OI_THRESHOLD = "OI_THRESHOLD"
    TIME_WINDOW = "TIME_WINDOW"
    INDICATOR_VALUE = "INDICATOR_VALUE"
    PCR_ABOVE = "PCR_ABOVE"
    PCR_BELOW = "PCR_BELOW"


class ActionType(StrEnum):
    PLACE_ORDER = "PLACE_ORDER"
    MODIFY_ORDER = "MODIFY_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    SEND_ALERT = "SEND_ALERT"
    CLOSE_POSITION = "CLOSE_POSITION"


class ExitType(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    TRAILING_SL = "TRAILING_SL"
    TIME_BASED = "TIME_BASED"
    SIGNAL_BASED = "SIGNAL_BASED"


# ---------------------------------------------------------------------------
# Node registry — metadata for all 54 node types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodePortSpec:
    """Specification for a node's input or output port."""

    name: str
    label: str
    data_type: str = "any"  # "any", "trigger", "bool", "number", "quote", "order"


@dataclass(frozen=True)
class ConfigFieldSpec:
    """Specification for a single config field."""

    name: str
    label: str
    field_type: str = "string"  # string, number, select, boolean
    required: bool = False
    default: str | int | float | bool | None = None
    options: tuple[str, ...] = ()  # for select fields


@dataclass(frozen=True)
class NodeSpec:
    """Complete specification for a node type."""

    node_type: NodeType
    label: str
    category: NodeCategory
    description: str
    inputs: tuple[NodePortSpec, ...] = ()
    outputs: tuple[NodePortSpec, ...] = ()
    config_fields: tuple[ConfigFieldSpec, ...] = ()
    icon: str = ""  # lucide icon name


def _build_registry() -> dict[NodeType, NodeSpec]:
    """Build the complete node type registry."""
    r: dict[NodeType, NodeSpec] = {}

    def _reg(spec: NodeSpec) -> None:
        r[spec.node_type] = spec

    _in = NodePortSpec
    _out = NodePortSpec
    _cfg = ConfigFieldSpec

    # -----------------------------------------------------------------------
    # Trigger nodes (4)
    # -----------------------------------------------------------------------
    _reg(NodeSpec(
        node_type=NodeType.START, label="Start", category=NodeCategory.TRIGGER,
        description="Schedule-based trigger: one-time, daily, weekly, or interval",
        outputs=(_out("trigger", "Trigger"),),
        config_fields=(
            _cfg("scheduleType", "Schedule Type", "select", True, "daily",
                 ("once", "daily", "weekly", "interval")),
            _cfg("time", "Time (HH:MM)", "string", False, "09:15"),
            _cfg("days", "Days (0=Sun..6=Sat)", "string", False, "1,2,3,4,5"),
            _cfg("intervalValue", "Interval Value", "number", False, 1),
            _cfg("intervalUnit", "Interval Unit", "select", False, "minutes",
                 ("seconds", "minutes", "hours")),
        ),
        icon="Clock",
    ))
    _reg(NodeSpec(
        node_type=NodeType.PRICE_ALERT, label="Price Alert", category=NodeCategory.TRIGGER,
        description="Trigger when price crosses a threshold via WebSocket monitoring",
        outputs=(
            _out("yes", "Condition Met", "bool"),
            _out("no", "Condition Not Met", "bool"),
        ),
        config_fields=(
            _cfg("symbol", "Symbol", "string", True),
            _cfg("exchange", "Exchange", "select", True, "NSE",
                 ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX")),
            _cfg("condition", "Condition", "select", True, "crosses_above",
                 ("crosses_above", "crosses_below", "equals")),
            _cfg("price", "Price", "number", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Bell",
    ))
    _reg(NodeSpec(
        node_type=NodeType.WEBHOOK_TRIGGER, label="Webhook Trigger",
        category=NodeCategory.TRIGGER,
        description="Trigger flow from an inbound webhook (TradingView, ChartInk, custom)",
        outputs=(_out("trigger", "Trigger"),),
        config_fields=(
            _cfg("webhookId", "Webhook ID", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Webhook",
    ))
    _reg(NodeSpec(
        node_type=NodeType.HTTP_REQUEST, label="HTTP Request",
        category=NodeCategory.TRIGGER,
        description="Make an outbound HTTP request and use the response",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("response", "Response"),),
        config_fields=(
            _cfg("url", "URL", "string", True),
            _cfg("method", "Method", "select", True, "GET",
                 ("GET", "POST", "PUT", "DELETE")),
            _cfg("headers", "Headers (JSON)", "string"),
            _cfg("body", "Body (JSON)", "string"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Globe",
    ))

    # -----------------------------------------------------------------------
    # Action nodes (10)
    # -----------------------------------------------------------------------
    _sym_exchange = (
        _cfg("symbol", "Symbol", "string", True),
        _cfg("exchange", "Exchange", "select", True, "NSE",
             ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX")),
    )
    _order_common = (
        *_sym_exchange,
        _cfg("action", "Action", "select", True, "BUY", ("BUY", "SELL")),
        _cfg("quantity", "Quantity", "number", True, 1),
        _cfg("priceType", "Price Type", "select", True, "MARKET",
             ("MARKET", "LIMIT", "SL", "SL-M")),
        _cfg("product", "Product", "select", True, "MIS",
             ("MIS", "CNC", "NRML")),
        _cfg("price", "Price", "number", False, 0),
        _cfg("triggerPrice", "Trigger Price", "number", False, 0),
    )

    _reg(NodeSpec(
        node_type=NodeType.PLACE_ORDER, label="Place Order",
        category=NodeCategory.ACTION,
        description="Place a regular order via OpenAlgo",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Order Result"),),
        config_fields=(*_order_common, _cfg("outputVariable", "Output Variable", "string")),
        icon="ShoppingCart",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SMART_ORDER, label="Smart Order",
        category=NodeCategory.ACTION,
        description="Place a smart order with position sizing via OpenAlgo",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Order Result"),),
        config_fields=(
            *_order_common,
            _cfg("positionSize", "Position Size", "number", False, 0),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Zap",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OPTIONS_ORDER, label="Options Order",
        category=NodeCategory.ACTION,
        description="Place an options order by strike offset (ATM, ITM, OTM)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Order Result"),),
        config_fields=(
            _cfg("underlying", "Underlying", "string", True, "NIFTY"),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO")),
            _cfg("expiryType", "Expiry Type", "select", True, "current_week",
                 ("current_week", "next_week", "current_month", "next_month")),
            _cfg("optionType", "Option Type", "select", True, "CE", ("CE", "PE")),
            _cfg("offset", "Strike Offset", "string", True, "ATM"),
            _cfg("action", "Action", "select", True, "BUY", ("BUY", "SELL")),
            _cfg("quantity", "Quantity", "number", True, 1),
            _cfg("priceType", "Price Type", "select", True, "MARKET",
                 ("MARKET", "LIMIT", "SL", "SL-M")),
            _cfg("product", "Product", "select", True, "MIS", ("MIS", "NRML")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="TrendingUp",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OPTIONS_MULTI_ORDER, label="Options Multi Order",
        category=NodeCategory.ACTION,
        description="Place multiple options legs simultaneously (straddle, strangle, etc.)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Order Result"),),
        config_fields=(
            _cfg("underlying", "Underlying", "string", True, "NIFTY"),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO")),
            _cfg("expiryType", "Expiry Type", "select", True, "current_week",
                 ("current_week", "next_week", "current_month", "next_month")),
            _cfg("legs", "Legs (JSON array)", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Layers",
    ))
    _reg(NodeSpec(
        node_type=NodeType.CANCEL_ALL_ORDERS, label="Cancel All Orders",
        category=NodeCategory.ACTION,
        description="Cancel all open orders",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="XCircle",
    ))
    _reg(NodeSpec(
        node_type=NodeType.CLOSE_POSITIONS, label="Close Positions",
        category=NodeCategory.ACTION,
        description="Close all open positions",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="LogOut",
    ))
    _reg(NodeSpec(
        node_type=NodeType.CANCEL_ORDER, label="Cancel Order",
        category=NodeCategory.ACTION,
        description="Cancel a specific order by order ID",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            _cfg("orderId", "Order ID", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="X",
    ))
    _reg(NodeSpec(
        node_type=NodeType.MODIFY_ORDER, label="Modify Order",
        category=NodeCategory.ACTION,
        description="Modify an existing order's price, quantity, or type",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            _cfg("orderId", "Order ID", "string", True),
            *_sym_exchange,
            _cfg("action", "Action", "select", True, "BUY", ("BUY", "SELL")),
            _cfg("quantity", "New Quantity", "number", True),
            _cfg("priceType", "Price Type", "select", True, "LIMIT",
                 ("MARKET", "LIMIT", "SL", "SL-M")),
            _cfg("price", "New Price", "number"),
            _cfg("triggerPrice", "Trigger Price", "number"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Edit",
    ))
    _reg(NodeSpec(
        node_type=NodeType.BASKET_ORDER, label="Basket Order",
        category=NodeCategory.ACTION,
        description="Place multiple orders as a basket in one call",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            _cfg("orders", "Orders (JSON array)", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="ShoppingBag",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SPLIT_ORDER, label="Split Order",
        category=NodeCategory.ACTION,
        description="Split a large order into smaller slices with optional delay",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            *_sym_exchange,
            _cfg("action", "Action", "select", True, "BUY", ("BUY", "SELL")),
            _cfg("totalQuantity", "Total Quantity", "number", True),
            _cfg("sliceSize", "Slice Size", "number", True),
            _cfg("delayMs", "Delay Between Slices (ms)", "number", False, 1000),
            _cfg("priceType", "Price Type", "select", True, "MARKET",
                 ("MARKET", "LIMIT")),
            _cfg("product", "Product", "select", True, "MIS", ("MIS", "CNC", "NRML")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Scissors",
    ))

    # -----------------------------------------------------------------------
    # Condition nodes (5)
    # -----------------------------------------------------------------------
    _bool_outputs = (
        _out("yes", "Condition True", "bool"),
        _out("no", "Condition False", "bool"),
    )

    _reg(NodeSpec(
        node_type=NodeType.POSITION_CHECK, label="Position Check",
        category=NodeCategory.CONDITION,
        description="Check if a position exists for a given symbol",
        inputs=(_in("trigger", "Trigger"),),
        outputs=_bool_outputs,
        config_fields=(
            *_sym_exchange,
            _cfg("product", "Product", "select", False, "MIS", ("MIS", "CNC", "NRML")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Search",
    ))
    _reg(NodeSpec(
        node_type=NodeType.FUND_CHECK, label="Fund Check",
        category=NodeCategory.CONDITION,
        description="Check if available funds exceed a threshold",
        inputs=(_in("trigger", "Trigger"),),
        outputs=_bool_outputs,
        config_fields=(
            _cfg("minFunds", "Minimum Funds", "number", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Wallet",
    ))
    _reg(NodeSpec(
        node_type=NodeType.TIME_WINDOW, label="Time Window",
        category=NodeCategory.CONDITION,
        description="Check if current time is within a start/end window",
        inputs=(_in("trigger", "Trigger"),),
        outputs=_bool_outputs,
        config_fields=(
            _cfg("startTime", "Start Time (HH:MM)", "string", True, "09:15"),
            _cfg("endTime", "End Time (HH:MM)", "string", True, "15:20"),
        ),
        icon="Clock",
    ))
    _reg(NodeSpec(
        node_type=NodeType.TIME_CONDITION, label="Time Condition",
        category=NodeCategory.CONDITION,
        description="Check time against a specific condition (before, after, at)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=_bool_outputs,
        config_fields=(
            _cfg("condition", "Condition", "select", True, "after",
                 ("before", "after", "at", "between")),
            _cfg("time", "Time (HH:MM)", "string", True, "09:15"),
            _cfg("endTime", "End Time (HH:MM, for between)", "string"),
        ),
        icon="Timer",
    ))
    _reg(NodeSpec(
        node_type=NodeType.PRICE_CONDITION, label="Price Condition",
        category=NodeCategory.CONDITION,
        description="Compare current price against a value using an operator",
        inputs=(_in("trigger", "Trigger"),),
        outputs=_bool_outputs,
        config_fields=(
            *_sym_exchange,
            _cfg("operator", "Operator", "select", True, "greater_than",
                 ("greater_than", "less_than", "equals", "greater_equal",
                  "less_equal", "not_equals")),
            _cfg("value", "Value", "number", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="GitCompare",
    ))

    # -----------------------------------------------------------------------
    # Logic gate nodes (3)
    # -----------------------------------------------------------------------
    _reg(NodeSpec(
        node_type=NodeType.AND_GATE, label="AND Gate",
        category=NodeCategory.LOGIC,
        description="Outputs true only if ALL inputs are true",
        inputs=(
            _in("input-0", "Input A", "bool"),
            _in("input-1", "Input B", "bool"),
        ),
        outputs=_bool_outputs,
        config_fields=(_cfg("inputCount", "Number of Inputs", "number", False, 2),),
        icon="GitMerge",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OR_GATE, label="OR Gate",
        category=NodeCategory.LOGIC,
        description="Outputs true if ANY input is true",
        inputs=(
            _in("input-0", "Input A", "bool"),
            _in("input-1", "Input B", "bool"),
        ),
        outputs=_bool_outputs,
        config_fields=(_cfg("inputCount", "Number of Inputs", "number", False, 2),),
        icon="GitBranch",
    ))
    _reg(NodeSpec(
        node_type=NodeType.NOT_GATE, label="NOT Gate",
        category=NodeCategory.LOGIC,
        description="Inverts the boolean input",
        inputs=(_in("input-0", "Input", "bool"),),
        outputs=_bool_outputs,
        config_fields=(),
        icon="ToggleLeft",
    ))

    # -----------------------------------------------------------------------
    # Data nodes (17)
    # -----------------------------------------------------------------------
    _data_sym = (
        *_sym_exchange,
        _cfg("outputVariable", "Output Variable", "string"),
    )

    _reg(NodeSpec(
        node_type=NodeType.GET_QUOTE, label="Get Quote",
        category=NodeCategory.DATA,
        description="Fetch real-time quote (LTP, open, high, low, close, volume)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("quote", "Quote Data", "quote"),),
        config_fields=_data_sym,
        icon="BarChart3",
    ))
    _reg(NodeSpec(
        node_type=NodeType.GET_DEPTH, label="Get Depth",
        category=NodeCategory.DATA,
        description="Fetch market depth (bid/ask levels)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("depth", "Depth Data"),),
        config_fields=_data_sym,
        icon="Layers",
    ))
    _reg(NodeSpec(
        node_type=NodeType.GET_ORDER_STATUS, label="Get Order Status",
        category=NodeCategory.DATA,
        description="Get the status of a specific order by ID",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("status", "Order Status"),),
        config_fields=(
            _cfg("orderId", "Order ID", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="FileSearch",
    ))
    _reg(NodeSpec(
        node_type=NodeType.HISTORY, label="History",
        category=NodeCategory.DATA,
        description="Fetch OHLCV historical candle data",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("candles", "Candle Data"),),
        config_fields=(
            *_sym_exchange,
            _cfg("interval", "Interval", "select", True, "1d",
                 ("1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1M")),
            _cfg("startDate", "Start Date (YYYY-MM-DD)", "string"),
            _cfg("endDate", "End Date (YYYY-MM-DD)", "string"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="CandlestickChart",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OPEN_POSITION, label="Open Position",
        category=NodeCategory.DATA,
        description="Get open position details for a symbol",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("position", "Position Data"),),
        config_fields=(
            *_sym_exchange,
            _cfg("product", "Product", "select", False, "MIS", ("MIS", "CNC", "NRML")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Briefcase",
    ))
    _reg(NodeSpec(
        node_type=NodeType.EXPIRY, label="Expiry",
        category=NodeCategory.DATA,
        description="Get expiry dates for a symbol",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("expiries", "Expiry Dates"),),
        config_fields=(
            _cfg("symbol", "Symbol", "string", True),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO", "MCX", "CDS")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Calendar",
    ))
    _reg(NodeSpec(
        node_type=NodeType.INTERVALS, label="Intervals",
        category=NodeCategory.DATA,
        description="Get supported candle intervals for a broker",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("intervals", "Intervals List"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="BarChart",
    ))
    _reg(NodeSpec(
        node_type=NodeType.MULTI_QUOTES, label="Multi Quotes",
        category=NodeCategory.DATA,
        description="Fetch quotes for multiple symbols in one call",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("quotes", "Multi Quote Data"),),
        config_fields=(
            _cfg("symbols", "Symbols (JSON array)", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="BarChart2",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SYMBOL, label="Symbol Lookup",
        category=NodeCategory.DATA,
        description="Look up symbol details (token, lot size, tick size)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("symbolInfo", "Symbol Info"),),
        config_fields=_data_sym,
        icon="Hash",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OPTION_SYMBOL, label="Option Symbol",
        category=NodeCategory.DATA,
        description="Resolve an option symbol from underlying, expiry, strike, and type",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("optionSymbol", "Option Symbol"),),
        config_fields=(
            _cfg("underlying", "Underlying", "string", True),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO")),
            _cfg("expiryType", "Expiry Type", "select", True, "current_week",
                 ("current_week", "next_week", "current_month", "next_month")),
            _cfg("optionType", "Option Type", "select", True, "CE", ("CE", "PE")),
            _cfg("strikePrice", "Strike Price", "number"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Tag",
    ))
    _reg(NodeSpec(
        node_type=NodeType.ORDER_BOOK, label="Order Book",
        category=NodeCategory.DATA,
        description="Fetch the full order book (all orders today)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("orders", "Order Book"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="BookOpen",
    ))
    _reg(NodeSpec(
        node_type=NodeType.TRADE_BOOK, label="Trade Book",
        category=NodeCategory.DATA,
        description="Fetch the trade book (all executed trades today)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("trades", "Trade Book"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="FileText",
    ))
    _reg(NodeSpec(
        node_type=NodeType.POSITION_BOOK, label="Position Book",
        category=NodeCategory.DATA,
        description="Fetch all current positions",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("positions", "Position Book"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="Table",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SYNTHETIC_FUTURE, label="Synthetic Future",
        category=NodeCategory.DATA,
        description="Calculate synthetic future price from option chain",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("price", "Synthetic Future Price", "number"),),
        config_fields=(
            _cfg("symbol", "Symbol", "string", True),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO")),
            _cfg("expiry", "Expiry Date", "string"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Activity",
    ))
    _reg(NodeSpec(
        node_type=NodeType.OPTION_CHAIN, label="Option Chain",
        category=NodeCategory.DATA,
        description="Fetch the full option chain for a symbol and expiry",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("chain", "Option Chain Data"),),
        config_fields=(
            _cfg("symbol", "Symbol", "string", True),
            _cfg("exchange", "Exchange", "select", True, "NFO", ("NFO", "BFO")),
            _cfg("expiry", "Expiry Date", "string"),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Table2",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SEARCH, label="Search Symbol",
        category=NodeCategory.DATA,
        description="Search for symbols by name or keyword",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("results", "Search Results"),),
        config_fields=(
            _cfg("query", "Search Query", "string", True),
            _cfg("exchange", "Exchange", "select", False, "",
                 ("", "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Search",
    ))
    _reg(NodeSpec(
        node_type=NodeType.HOLIDAYS, label="Holidays",
        category=NodeCategory.DATA,
        description="Get list of market holidays",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("holidays", "Holiday List"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="CalendarOff",
    ))
    _reg(NodeSpec(
        node_type=NodeType.TIMINGS, label="Market Timings",
        category=NodeCategory.DATA,
        description="Get market open/close timings for each segment",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("timings", "Timings Data"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="Clock3",
    ))

    # -----------------------------------------------------------------------
    # Streaming nodes (4)
    # -----------------------------------------------------------------------
    _stream_cfg = (
        *_sym_exchange,
        _cfg("outputVariable", "Output Variable", "string"),
    )

    _reg(NodeSpec(
        node_type=NodeType.SUBSCRIBE_LTP, label="Subscribe LTP",
        category=NodeCategory.STREAMING,
        description="Subscribe to real-time LTP updates via WebSocket",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("ltp", "LTP Data", "number"),),
        config_fields=_stream_cfg,
        icon="Radio",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SUBSCRIBE_QUOTE, label="Subscribe Quote",
        category=NodeCategory.STREAMING,
        description="Subscribe to real-time quote updates via WebSocket",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("quote", "Quote Data", "quote"),),
        config_fields=_stream_cfg,
        icon="Radio",
    ))
    _reg(NodeSpec(
        node_type=NodeType.SUBSCRIBE_DEPTH, label="Subscribe Depth",
        category=NodeCategory.STREAMING,
        description="Subscribe to real-time depth updates via WebSocket",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("depth", "Depth Data"),),
        config_fields=_stream_cfg,
        icon="Radio",
    ))
    _reg(NodeSpec(
        node_type=NodeType.UNSUBSCRIBE, label="Unsubscribe",
        category=NodeCategory.STREAMING,
        description="Unsubscribe from a WebSocket stream",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            *_sym_exchange,
            _cfg("mode", "Mode", "select", True, "LTP", ("LTP", "Quote", "Depth")),
        ),
        icon="RadioOff",
    ))

    # -----------------------------------------------------------------------
    # Risk management nodes (3)
    # -----------------------------------------------------------------------
    _reg(NodeSpec(
        node_type=NodeType.HOLDINGS, label="Holdings",
        category=NodeCategory.RISK,
        description="Fetch current portfolio holdings",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("holdings", "Holdings Data"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="PieChart",
    ))
    _reg(NodeSpec(
        node_type=NodeType.FUNDS, label="Funds",
        category=NodeCategory.RISK,
        description="Fetch available margin/funds",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("funds", "Funds Data"),),
        config_fields=(_cfg("outputVariable", "Output Variable", "string"),),
        icon="IndianRupee",
    ))
    _reg(NodeSpec(
        node_type=NodeType.MARGIN, label="Margin",
        category=NodeCategory.RISK,
        description="Calculate margin required for a position",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("margin", "Margin Data"),),
        config_fields=(
            *_sym_exchange,
            _cfg("action", "Action", "select", True, "BUY", ("BUY", "SELL")),
            _cfg("quantity", "Quantity", "number", True),
            _cfg("priceType", "Price Type", "select", True, "MARKET",
                 ("MARKET", "LIMIT")),
            _cfg("product", "Product", "select", True, "MIS", ("MIS", "CNC", "NRML")),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Calculator",
    ))

    # -----------------------------------------------------------------------
    # Utility nodes (7)
    # -----------------------------------------------------------------------
    _reg(NodeSpec(
        node_type=NodeType.TELEGRAM_ALERT, label="Telegram Alert",
        category=NodeCategory.UTILITY,
        description="Send a notification via Telegram",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result"),),
        config_fields=(
            _cfg("message", "Message", "string", True),
        ),
        icon="Send",
    ))
    _reg(NodeSpec(
        node_type=NodeType.DELAY, label="Delay",
        category=NodeCategory.UTILITY,
        description="Wait for a specified duration before continuing",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("trigger", "Continue"),),
        config_fields=(
            _cfg("delayValue", "Delay Value", "number", True, 5),
            _cfg("delayUnit", "Delay Unit", "select", True, "seconds",
                 ("seconds", "minutes", "hours")),
        ),
        icon="Timer",
    ))
    _reg(NodeSpec(
        node_type=NodeType.WAIT_UNTIL, label="Wait Until",
        category=NodeCategory.UTILITY,
        description="Wait until a specific time of day before continuing",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("trigger", "Continue"),),
        config_fields=(
            _cfg("time", "Time (HH:MM)", "string", True, "09:15"),
        ),
        icon="Clock",
    ))
    _reg(NodeSpec(
        node_type=NodeType.GROUP, label="Group",
        category=NodeCategory.UTILITY,
        description="Visual grouping of nodes (no logic, organizational only)",
        inputs=(),
        outputs=(),
        config_fields=(
            _cfg("label", "Group Label", "string"),
            _cfg("color", "Color", "string", False, "#1e1e2e"),
        ),
        icon="Square",
    ))
    _reg(NodeSpec(
        node_type=NodeType.VARIABLE, label="Variable",
        category=NodeCategory.UTILITY,
        description="Set or compute a variable for use in later nodes",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("value", "Value"),),
        config_fields=(
            _cfg("variableName", "Variable Name", "string", True),
            _cfg("value", "Value / Expression", "string", True),
            _cfg("valueType", "Value Type", "select", True, "string",
                 ("string", "number", "boolean", "json")),
        ),
        icon="Variable",
    ))
    _reg(NodeSpec(
        node_type=NodeType.MATH_EXPRESSION, label="Math Expression",
        category=NodeCategory.UTILITY,
        description="Evaluate a math expression using variables (e.g. {{ltp}} * 1.01)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("result", "Result", "number"),),
        config_fields=(
            _cfg("expression", "Expression", "string", True),
            _cfg("outputVariable", "Output Variable", "string"),
        ),
        icon="Calculator",
    ))
    _reg(NodeSpec(
        node_type=NodeType.LOG, label="Log",
        category=NodeCategory.UTILITY,
        description="Log a message to the execution log (supports {{variable}} interpolation)",
        inputs=(_in("trigger", "Trigger"),),
        outputs=(_out("trigger", "Continue"),),
        config_fields=(
            _cfg("message", "Message", "string", True),
            _cfg("level", "Level", "select", False, "info", ("info", "warning", "error")),
        ),
        icon="FileText",
    ))

    return r


NODE_REGISTRY: dict[NodeType, NodeSpec] = _build_registry()

# Category-to-node-type mapping for easy lookup
NODES_BY_CATEGORY: dict[NodeCategory, list[NodeType]] = {}
for _nt, _spec in NODE_REGISTRY.items():
    NODES_BY_CATEGORY.setdefault(_spec.category, []).append(_nt)


def get_node_spec(node_type: NodeType | str) -> NodeSpec:
    """Look up the spec for a node type. Raises KeyError if not found."""
    if isinstance(node_type, str):
        node_type = NodeType(node_type)
    return NODE_REGISTRY[node_type]


def get_all_node_types() -> list[NodeType]:
    """Return a list of all registered node types."""
    return list(NODE_REGISTRY.keys())


def get_node_types_by_category(category: NodeCategory) -> list[NodeType]:
    """Return node types for a given category."""
    return NODES_BY_CATEGORY.get(category, [])


# ---------------------------------------------------------------------------
# Flow Node
# ---------------------------------------------------------------------------


@dataclass
class FlowNode:
    """A single node in a strategy flow graph."""

    id: str
    node_type: str  # NodeType value
    subtype: str = ""  # Legacy — kept for backward compat
    label: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    next_nodes: list[str] = field(default_factory=list)  # IDs of connected nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "subtype": self.subtype,
            "label": self.label,
            "config": self.config,
            "next_nodes": self.next_nodes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowNode:
        return cls(
            id=data["id"],
            node_type=data["node_type"],
            subtype=data.get("subtype", ""),
            label=data.get("label", ""),
            config=data.get("config", {}),
            next_nodes=data.get("next_nodes", []),
        )


# ---------------------------------------------------------------------------
# Flow Definition
# ---------------------------------------------------------------------------


@dataclass
class FlowDefinition:
    """A complete strategy flow — a DAG of connected nodes."""

    name: str
    description: str = ""
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    entry_node_id: str = ""

    def add_node(self, node: FlowNode) -> None:
        self.nodes[node.id] = node

    def connect(self, from_id: str, to_id: str) -> None:
        """Connect one node's output to another node's input."""
        if from_id not in self.nodes:
            raise ValueError(f"Source node '{from_id}' not found")
        if to_id not in self.nodes:
            raise ValueError(f"Target node '{to_id}' not found")
        if to_id not in self.nodes[from_id].next_nodes:
            self.nodes[from_id].next_nodes.append(to_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "entry_node_id": self.entry_node_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowDefinition:
        flow = cls(
            name=data["name"],
            description=data.get("description", ""),
            entry_node_id=data.get("entry_node_id", ""),
        )
        for nid, ndata in data.get("nodes", {}).items():
            flow.nodes[nid] = FlowNode.from_dict(ndata)
        return flow

    @classmethod
    def from_json(cls, json_str: str) -> FlowDefinition:
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Flow Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    """A single validation issue."""

    node_id: str
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of flow validation."""

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)


# Node types considered "terminal" — flows must have at least one
_TERMINAL_CATEGORIES = {NodeCategory.ACTION.value, NodeCategory.UTILITY.value}
# Legacy top-level types that also count as terminal
_TERMINAL_LEGACY_TYPES = {"ACTION", "EXIT"}


def validate_flow(flow: FlowDefinition) -> ValidationResult:
    """Validate a flow definition for structural correctness.

    Checks:
    - At least one node exists
    - Entry node is set and exists
    - Entry node is a trigger type
    - All next_node references are valid
    - No orphan nodes (unreachable from entry)
    - At least one ACTION, EXIT, or terminal-category node
    - No self-loops
    """
    result = ValidationResult()

    # Must have nodes
    if not flow.nodes:
        result.is_valid = False
        result.errors.append(ValidationError("", "Flow has no nodes"))
        return result

    # Entry node must exist
    if not flow.entry_node_id:
        result.is_valid = False
        result.errors.append(ValidationError("", "No entry node specified"))
        return result

    if flow.entry_node_id not in flow.nodes:
        result.is_valid = False
        result.errors.append(ValidationError(
            flow.entry_node_id,
            f"Entry node '{flow.entry_node_id}' does not exist",
        ))
        return result

    # Entry should be a trigger type
    entry = flow.nodes[flow.entry_node_id]
    _trigger_types = {nt.value for nt in get_node_types_by_category(NodeCategory.TRIGGER)}
    _trigger_types.add("SIGNAL")  # legacy
    if entry.node_type not in _trigger_types:
        result.warnings.append(ValidationError(
            entry.id,
            f"Entry node should be a trigger type, got {entry.node_type}",
            severity="warning",
        ))

    # Check all connections point to existing nodes
    all_ids = set(flow.nodes.keys())
    for nid, node in flow.nodes.items():
        for target in node.next_nodes:
            if target not in all_ids:
                result.is_valid = False
                result.errors.append(ValidationError(
                    nid,
                    f"Node '{nid}' connects to non-existent node '{target}'",
                ))
            if target == nid:
                result.is_valid = False
                result.errors.append(ValidationError(
                    nid, f"Node '{nid}' has a self-loop",
                ))

    # Check for orphan nodes
    reachable: set[str] = set()
    _walk(flow, flow.entry_node_id, reachable)

    orphans = all_ids - reachable
    for orphan in orphans:
        result.warnings.append(ValidationError(
            orphan,
            f"Node '{orphan}' is not reachable from entry node",
            severity="warning",
        ))

    # Must have at least one ACTION/EXIT/terminal node
    has_terminal = any(
        _is_terminal_node(n) for n in flow.nodes.values()
    )
    if not has_terminal:
        result.is_valid = False
        result.errors.append(ValidationError(
            "", "Flow must have at least one ACTION or EXIT node",
        ))

    return result


def _is_terminal_node(node: FlowNode) -> bool:
    """Check if a node is considered a terminal (action/exit) node."""
    # Legacy top-level types
    if node.node_type in _TERMINAL_LEGACY_TYPES:
        return True
    # New category-based check
    try:
        nt = NodeType(node.node_type)
        spec = NODE_REGISTRY.get(nt)
        if spec and spec.category.value in _TERMINAL_CATEGORIES:
            return True
    except ValueError:
        pass
    return False


def _walk(flow: FlowDefinition, node_id: str, visited: set[str]) -> None:
    """Recursively walk the flow graph from a starting node."""
    if node_id in visited:
        return
    visited.add(node_id)
    node = flow.nodes.get(node_id)
    if node:
        for next_id in node.next_nodes:
            _walk(flow, next_id, visited)


# ---------------------------------------------------------------------------
# Graph-based reachability validation (flat nodes + edges representation)
# ---------------------------------------------------------------------------


@dataclass
class FlowValidationError:
    """A single error from graph-based flow validation.

    This is the canonical error type returned by ``validate_flow_graph`` and
    used in the flow execution pre-check.
    """

    node_id: str
    code: str  # machine-readable code, e.g. "ORPHAN", "SELF_LOOP"
    description: str


# Trigger node types that count as valid entry points for BFS
_TRIGGER_TYPE_VALUES: frozenset[str] = frozenset(
    nt.value for nt in NodeType
    if NODE_REGISTRY.get(nt) and NODE_REGISTRY[nt].category == NodeCategory.TRIGGER
) | frozenset({"SIGNAL"})  # legacy


def validate_flow_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[FlowValidationError]:
    """Validate a flow expressed as flat node and edge lists.

    This function is the canonical pre-execution check.  It accepts the
    JSON-serialisable graph structure emitted by the React flow editor and
    returns a list of ``FlowValidationError`` objects.  An empty list means
    the graph is structurally valid.

    Checks performed (in order):
    1. At least one trigger node exists (``TRIGGER`` category or legacy
       ``SIGNAL``/``WEBHOOK_TRIGGER`` types).
    2. All nodes are connected — no isolated/orphan nodes with zero edges.
    3. No self-loops (an edge whose source equals its target).
    4. No unreachable nodes — BFS from every trigger node must visit all
       non-trigger nodes.

    Args:
        nodes: List of node dicts, each with at least ``{"id": str,
            "node_type": str}``.  Extra keys (``label``, ``config``) are
            ignored.
        edges: List of edge dicts, each with at least ``{"source": str,
            "target": str}``.  Extra keys (``id``) are ignored.

    Returns:
        List of ``FlowValidationError``.  Empty means valid.

    Examples::

        errors = validate_flow_graph(
            nodes=[
                {"id": "n1", "node_type": "start"},
                {"id": "n2", "node_type": "placeOrder"},
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        assert errors == []
    """
    errors: list[FlowValidationError] = []

    # Build convenience lookups
    node_ids: set[str] = {n["id"] for n in nodes}

    # Adjacency list (forward)
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    # Reverse adjacency to detect isolated nodes
    reverse_adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        if src in adjacency:
            adjacency[src].append(tgt)
        if tgt in reverse_adjacency:
            reverse_adjacency[tgt].append(src)

    # ------------------------------------------------------------------
    # 1. At least one trigger node
    # ------------------------------------------------------------------
    trigger_ids: list[str] = [
        n["id"] for n in nodes
        if n.get("node_type") in _TRIGGER_TYPE_VALUES
    ]
    if not trigger_ids:
        errors.append(FlowValidationError(
            node_id="",
            code="NO_TRIGGER",
            description=(
                "Flow has no trigger node. Add a Start, Price Alert, or "
                "Webhook Trigger node."
            ),
        ))
        # Cannot do BFS without triggers — return early
        return errors

    # ------------------------------------------------------------------
    # 2. Self-loops
    # ------------------------------------------------------------------
    for edge in edges:
        if edge["source"] == edge["target"]:
            errors.append(FlowValidationError(
                node_id=edge["source"],
                code="SELF_LOOP",
                description=(
                    f"Node '{edge['source']}' has an edge that connects back "
                    "to itself."
                ),
            ))

    # ------------------------------------------------------------------
    # 3. Orphan nodes — nodes with no edges at all
    # ------------------------------------------------------------------
    for n in nodes:
        nid = n["id"]
        has_out = bool(adjacency.get(nid))
        has_in = bool(reverse_adjacency.get(nid))
        if not has_out and not has_in:
            errors.append(FlowValidationError(
                node_id=nid,
                code="ORPHAN",
                description=(
                    f"Node '{nid}' ({n.get('node_type', '?')}) has no "
                    "connections and will never execute."
                ),
            ))

    # ------------------------------------------------------------------
    # 4. Unreachable nodes — BFS from all triggers
    # ------------------------------------------------------------------
    reachable: set[str] = set()
    queue = list(trigger_ids)
    while queue:
        current = queue.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for neighbour in adjacency.get(current, []):
            if neighbour not in reachable and neighbour in node_ids:
                queue.append(neighbour)

    unreachable = node_ids - reachable
    for nid in sorted(unreachable):  # sorted for deterministic order
        node_type = next(
            (n.get("node_type", "?") for n in nodes if n["id"] == nid), "?"
        )
        errors.append(FlowValidationError(
            node_id=nid,
            code="UNREACHABLE",
            description=(
                f"Node '{nid}' ({node_type}) cannot be reached from any "
                "trigger node."
            ),
        ))

    return errors


# ---------------------------------------------------------------------------
# FlowBuilder — convenience API
# ---------------------------------------------------------------------------


class FlowBuilder:
    """Builder API for constructing strategy flows.

    Usage::

        fb = FlowBuilder("My Strategy")
        sig = fb.add_signal(SignalSource.TRADINGVIEW, label="TV Alert")
        cond = fb.add_condition(ConditionType.PRICE_ABOVE, config={"value": 24000})
        act = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY", "action": "BUY"})
        exit_ = fb.add_exit(ExitType.STOP_LOSS, config={"points": 100})

        fb.connect(sig, cond)
        fb.connect(cond, act)
        fb.connect(act, exit_)

        flow = fb.build()
        result = fb.validate()

    New API — add any of the 54 node types::

        fb = FlowBuilder("Options Flow")
        start = fb.add_node(NodeType.START, config={"scheduleType": "daily", "time": "09:16"})
        quote = fb.add_node(NodeType.GET_QUOTE, config={"symbol": "NIFTY", "exchange": "NSE"})
        check = fb.add_node(NodeType.PRICE_CONDITION, config={"operator": "greater_than", "value": 24000})
        order = fb.add_node(NodeType.PLACE_ORDER, config={"symbol": "NIFTY", "action": "BUY", "quantity": 75})

        fb.connect(start, quote)
        fb.connect(quote, check)
        fb.connect(check, order)

        flow = fb.build()
    """

    def __init__(self, name: str, description: str = "") -> None:
        self._flow = FlowDefinition(name=name, description=description)
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    # --- New generic API ---

    def add_node(
        self,
        node_type: NodeType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add any node type. Returns node ID.

        The node type determines the ID prefix and whether it auto-sets
        as the entry node (triggers only).
        """
        if isinstance(node_type, str):
            node_type = NodeType(node_type)

        spec = NODE_REGISTRY.get(node_type)
        prefix = node_type.value[:6]  # short prefix from type name
        nid = self._next_id(prefix)

        resolved_label = label or (spec.label if spec else node_type.value)
        node = FlowNode(
            id=nid,
            node_type=node_type.value,
            label=resolved_label,
            config=config or {},
        )
        self._flow.add_node(node)

        # First trigger node becomes entry
        if spec and spec.category == NodeCategory.TRIGGER and not self._flow.entry_node_id:
            self._flow.entry_node_id = nid

        return nid

    # --- Legacy API (backward compatible) ---

    def add_signal(
        self,
        source: SignalSource | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add a SIGNAL node (legacy). Returns node ID."""
        nid = self._next_id("sig")
        subtype = source.value if isinstance(source, SignalSource) else source
        node = FlowNode(
            id=nid, node_type="SIGNAL",
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        if not self._flow.entry_node_id:
            self._flow.entry_node_id = nid
        return nid

    def add_condition(
        self,
        condition: ConditionType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add a CONDITION node (legacy). Returns node ID."""
        nid = self._next_id("cond")
        subtype = condition.value if isinstance(condition, ConditionType) else condition
        node = FlowNode(
            id=nid, node_type="CONDITION",
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    def add_action(
        self,
        action: ActionType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add an ACTION node (legacy). Returns node ID."""
        nid = self._next_id("act")
        subtype = action.value if isinstance(action, ActionType) else action
        node = FlowNode(
            id=nid, node_type="ACTION",
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    def add_exit(
        self,
        exit_type: ExitType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add an EXIT node (legacy). Returns node ID."""
        nid = self._next_id("exit")
        subtype = exit_type.value if isinstance(exit_type, ExitType) else exit_type
        node = FlowNode(
            id=nid, node_type="EXIT",
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    # --- Common ---

    def connect(self, from_id: str, to_id: str) -> None:
        """Connect two nodes."""
        self._flow.connect(from_id, to_id)

    def build(self) -> FlowDefinition:
        """Return the built flow definition."""
        return self._flow

    def validate(self) -> ValidationResult:
        """Validate the current flow.

        Runs graph reachability checks (via ``validate_flow_graph``) first as
        a pre-check, then the full ``FlowDefinition``-based structural
        validation.  Any graph errors are surfaced as ``ValidationError``
        entries in the result.
        """
        result = validate_flow(self._flow)

        # Run graph-level pre-check using flat representation
        graph_nodes = [
            {"id": nid, "node_type": n.node_type}
            for nid, n in self._flow.nodes.items()
        ]
        graph_edges: list[dict[str, Any]] = []
        for nid, n in self._flow.nodes.items():
            for target in n.next_nodes:
                graph_edges.append({"source": nid, "target": target})

        graph_errors = validate_flow_graph(graph_nodes, graph_edges)
        for ge in graph_errors:
            # Avoid duplicating errors already found by validate_flow()
            already_reported = any(
                e.node_id == ge.node_id and ge.code in e.message
                for e in result.errors + result.warnings
            )
            if not already_reported:
                result.errors.append(
                    ValidationError(
                        node_id=ge.node_id,
                        message=f"[{ge.code}] {ge.description}",
                    )
                )
                if result.is_valid and ge.code in {"ORPHAN", "UNREACHABLE"}:
                    # Demote to warning — these don't prevent execution
                    pass
                elif ge.code in {"NO_TRIGGER", "SELF_LOOP"}:
                    result.is_valid = False

        return result

    def validate_graph(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> list[FlowValidationError]:
        """Run graph reachability validation on a flat node/edge list.

        Convenience wrapper around the module-level ``validate_flow_graph``
        function, suitable for use in the FlowBuilder UI pre-save check.

        Args:
            nodes: List of ``{"id": str, "node_type": str}`` dicts.
            edges: List of ``{"source": str, "target": str}`` dicts.

        Returns:
            List of ``FlowValidationError``.  Empty means valid.
        """
        return validate_flow_graph(nodes, edges)

    def to_json(self) -> str:
        """Export flow as JSON."""
        return self._flow.to_json()
