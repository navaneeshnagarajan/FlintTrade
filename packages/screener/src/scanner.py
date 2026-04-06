"""Configurable stock scanner engine.

Adapted from fluxscan (marketcalls/fluxscan). Provides a framework for
defining, validating, and executing custom Python-based market scans
against OpenAlgo data.

A Scanner is a named piece of Python code that receives OHLCV data and
returns a list of matching symbols. Scanners can be:
- Built-in templates (EMA crossover, RSI extremes, volume spike)
- User-defined custom Python code

Usage::

    from packages.screener.src.scanner import ScannerEngine, ScannerDef

    engine = ScannerEngine()

    # Register a built-in template
    engine.register(ScannerDef(
        name="RSI Oversold",
        code='results = [s for s, d in data.items() if d.get("rsi", 50) < 30]',
        category="momentum",
        parameters={"threshold": 30},
    ))

    # Execute scan
    results = engine.run("RSI Oversold", symbols=["RELIANCE", "SBIN", "ICICIBANK"])
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScannerDef:
    """Definition of a scanner.

    Attributes:
        name:        Unique scanner name.
        code:        Python code string to execute. Must set ``results`` to a list
                     of matching symbol strings.
        description: Human-readable description.
        category:    Category for grouping (trend, momentum, volatility, volume, custom).
        parameters:  Optional parameter dict injected into the scan namespace.
        is_active:   Whether this scanner is enabled.
    """

    name: str
    code: str
    description: str = ""
    category: str = "custom"
    parameters: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    def validate_code(self) -> tuple[bool, str | None]:
        """Check if the scanner code compiles without syntax errors.

        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        try:
            compile(self.code, f"<scanner:{self.name}>", "exec")
            return True, None
        except SyntaxError as exc:
            return False, str(exc)


@dataclass
class ScanResult:
    """Result of a single scanner execution.

    Attributes:
        scanner_name:    Name of the scanner that produced this result.
        matched_symbols: Symbols that matched the scan criteria.
        total_scanned:   Total number of symbols scanned.
        elapsed_ms:      Time taken in milliseconds.
        error:           Error message if the scan failed, else None.
        timestamp:       ISO timestamp of when the scan completed.
    """

    scanner_name: str
    matched_symbols: list[str] = field(default_factory=list)
    total_scanned: int = 0
    elapsed_ms: float = 0.0
    error: str | None = None
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Built-in scanner templates
# ---------------------------------------------------------------------------

_BUILTIN_TEMPLATES: dict[str, ScannerDef] = {}


def _register_builtin(scanner: ScannerDef) -> None:
    _BUILTIN_TEMPLATES[scanner.name] = scanner


_register_builtin(ScannerDef(
    name="EMA Crossover Bullish",
    description="EMA 20 crosses above EMA 50 — bullish trend signal.",
    category="trend",
    code="""\
results = []
for sym, d in data.items():
    ema20 = d.get("ema_20")
    ema50 = d.get("ema_50")
    prev_ema20 = d.get("prev_ema_20")
    prev_ema50 = d.get("prev_ema_50")
    if ema20 is not None and ema50 is not None and prev_ema20 is not None and prev_ema50 is not None:
        if ema20 > ema50 and prev_ema20 <= prev_ema50:
            results.append(sym)
""",
    parameters={"fast_period": 20, "slow_period": 50},
))


_register_builtin(ScannerDef(
    name="RSI Oversold",
    description="RSI below threshold — potential reversal or buy opportunity.",
    category="momentum",
    code="""\
threshold = params.get("threshold", 30)
results = [sym for sym, d in data.items() if d.get("rsi", 50) < threshold]
""",
    parameters={"threshold": 30},
))


_register_builtin(ScannerDef(
    name="RSI Overbought",
    description="RSI above threshold — potential reversal or sell opportunity.",
    category="momentum",
    code="""\
threshold = params.get("threshold", 70)
results = [sym for sym, d in data.items() if d.get("rsi", 50) > threshold]
""",
    parameters={"threshold": 70},
))


_register_builtin(ScannerDef(
    name="Volume Spike",
    description="Volume is N times above the 20-bar average — unusual activity.",
    category="volume",
    code="""\
multiplier = params.get("multiplier", 2.0)
results = []
for sym, d in data.items():
    vol = d.get("volume", 0)
    avg_vol = d.get("avg_volume_20", 1)
    if avg_vol > 0 and vol > avg_vol * multiplier:
        results.append(sym)
""",
    parameters={"multiplier": 2.0},
))


_register_builtin(ScannerDef(
    name="Bollinger Band Squeeze",
    description="Bollinger Band width at 6-month low — volatility expansion expected.",
    category="volatility",
    code="""\
results = []
for sym, d in data.items():
    bb_width = d.get("bb_width")
    bb_width_min = d.get("bb_width_6m_min")
    if bb_width is not None and bb_width_min is not None:
        if bb_width <= bb_width_min * 1.05:
            results.append(sym)
""",
    parameters={},
))


_register_builtin(ScannerDef(
    name="Supertrend Bullish Flip",
    description="Supertrend direction flips from bearish to bullish.",
    category="trend",
    code="""\
results = []
for sym, d in data.items():
    st_dir = d.get("supertrend_dir")
    prev_st_dir = d.get("prev_supertrend_dir")
    if st_dir == 1 and prev_st_dir == -1:
        results.append(sym)
""",
    parameters={},
))


# ---------------------------------------------------------------------------
# Scanner engine
# ---------------------------------------------------------------------------


class ScannerEngine:
    """Engine for registering and executing market scanners.

    Manages a registry of ScannerDef objects and executes them against
    provided market data. Does NOT fetch data itself — the caller provides
    a ``data`` dict mapping symbol names to indicator dicts.
    """

    def __init__(self) -> None:
        self._scanners: dict[str, ScannerDef] = {}
        # Load built-in templates
        for name, scanner in _BUILTIN_TEMPLATES.items():
            self._scanners[name] = scanner

    def register(self, scanner: ScannerDef) -> None:
        """Register or update a scanner definition.

        Args:
            scanner: Scanner definition to register.

        Raises:
            ValueError: If the scanner code has syntax errors.
        """
        valid, err = scanner.validate_code()
        if not valid:
            raise ValueError(f"Scanner '{scanner.name}' has invalid code: {err}")
        self._scanners[scanner.name] = scanner

    def unregister(self, name: str) -> bool:
        """Remove a scanner by name. Returns True if removed, False if not found."""
        if name in self._scanners:
            del self._scanners[name]
            return True
        return False

    def list_scanners(self, category: str | None = None) -> list[ScannerDef]:
        """List all registered scanners, optionally filtered by category.

        Args:
            category: If provided, only return scanners in this category.

        Returns:
            List of scanner definitions.
        """
        scanners = list(self._scanners.values())
        if category is not None:
            scanners = [s for s in scanners if s.category == category]
        return [s for s in scanners if s.is_active]

    def run(
        self,
        scanner_name: str,
        data: dict[str, dict[str, Any]],
        override_params: dict[str, Any] | None = None,
    ) -> ScanResult:
        """Execute a scanner against provided market data.

        Args:
            scanner_name:    Name of the registered scanner to run.
            data:            Dict mapping symbol names to indicator value dicts.
                             Example: ``{"RELIANCE": {"rsi": 28, "volume": 50000}}``
            override_params: Optional parameter overrides for this execution.

        Returns:
            ScanResult with matched symbols, timing, and any errors.

        Raises:
            KeyError: If scanner_name is not registered.
        """
        if scanner_name not in self._scanners:
            raise KeyError(f"Scanner '{scanner_name}' not registered")

        scanner = self._scanners[scanner_name]
        params = {**scanner.parameters}
        if override_params:
            params.update(override_params)

        from datetime import datetime, timezone

        start = time.monotonic()
        namespace: dict[str, Any] = {
            "data": data,
            "params": params,
            "results": [],
        }

        try:
            # AST validation — reject dangerous constructs before execution
            import ast as _ast  # noqa: PLC0415
            try:
                tree = _ast.parse(scanner.code)
            except SyntaxError as syn_err:
                return ScanResult(
                    scanner_name=scanner_name,
                    matched_symbols=[],
                    total_scanned=0,
                    elapsed_ms=0.0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    error=f"Syntax error: {syn_err}",
                )
            _FORBIDDEN_NODES = (
                _ast.Import, _ast.ImportFrom, _ast.Global, _ast.Nonlocal,
            )
            _FORBIDDEN_ATTRS = {"__class__", "__bases__", "__subclasses__", "__globals__",
                                "__code__", "__builtins__", "__import__", "__mro__",
                                "__dict__", "__init__", "__new__", "__reduce__",
                                "__reduce_ex__", "__module__",
                                "eval", "exec",
                                "compile", "open", "getattr", "setattr", "delattr",
                                "breakpoint", "exit", "quit"}
            _FORBIDDEN_NAMES = {"eval", "exec", "compile", "open", "getattr", "setattr",
                                "delattr", "breakpoint", "exit", "quit", "__import__",
                                "type", "chr", "ord", "bytearray", "bytes",
                                "memoryview", "vars", "dir", "help"}
            for node in _ast.walk(tree):
                if isinstance(node, _FORBIDDEN_NODES):
                    return ScanResult(
                        scanner_name=scanner_name, matched_symbols=[], total_scanned=0,
                        elapsed_ms=0.0, timestamp=datetime.now(timezone.utc).isoformat(),
                        error=f"Forbidden construct: {type(node).__name__}",
                    )
                if isinstance(node, _ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
                    return ScanResult(
                        scanner_name=scanner_name, matched_symbols=[], total_scanned=0,
                        elapsed_ms=0.0, timestamp=datetime.now(timezone.utc).isoformat(),
                        error=f"Forbidden attribute: {node.attr}",
                    )
                if isinstance(node, _ast.Name) and node.id in _FORBIDDEN_NAMES:
                    return ScanResult(
                        scanner_name=scanner_name, matched_symbols=[], total_scanned=0,
                        elapsed_ms=0.0, timestamp=datetime.now(timezone.utc).isoformat(),
                        error=f"Forbidden name: {node.id}",
                    )
            exec(scanner.code, {"__builtins__": {}}, namespace)  # noqa: S102 — AST-validated
            matched = namespace.get("results", [])
            if not isinstance(matched, list):
                matched = list(matched)
            elapsed = (time.monotonic() - start) * 1000

            return ScanResult(
                scanner_name=scanner_name,
                matched_symbols=matched,
                total_scanned=len(data),
                elapsed_ms=round(elapsed, 2),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ScanResult(
                scanner_name=scanner_name,
                total_scanned=len(data),
                elapsed_ms=round(elapsed, 2),
                error=str(exc),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def get_categories(self) -> list[str]:
        """Return sorted unique categories of all active scanners."""
        cats = {s.category for s in self._scanners.values() if s.is_active}
        return sorted(cats)

    def get_builtin_names(self) -> list[str]:
        """Return names of all built-in scanner templates."""
        return sorted(_BUILTIN_TEMPLATES.keys())
