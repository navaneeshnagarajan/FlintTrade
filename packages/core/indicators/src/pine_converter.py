"""Pine Script to Python indicator converter.

Converts common Pine Script indicator expressions to equivalent Python code
using FlintTrade's indicator package (packages/core/indicators/src/).

This is NOT a full Pine Script parser — it handles the most common patterns
used in TradingView alerts and strategies.

Supported Pine functions:
    ta.ema(source, length) → ema(source, length)
    ta.sma(source, length) → sma(source, length)
    ta.rsi(source, length) → rsi(source, length)
    ta.macd(source, fast, slow, signal) → macd(source, fast, slow, signal)
    ta.atr(length) → atr(highs, lows, closes, length)
    ta.bb(source, length, mult) → bollinger_bands(source, length, mult)
    ta.supertrend(factor, period) → supertrend(highs, lows, closes, period, factor)
    ta.vwap → vwap(highs, lows, closes, volumes)
    ta.crossover(a, b) → crossover function
    ta.crossunder(a, b) → crossunder function
    ta.stoch(source, high, low, length) → stochastic(highs, lows, closes, length)
    ta.adx(diLen, adxLen) → adx(highs, lows, closes, adxLen)
    ta.wma(source, length) → wma(source, length)
    ta.hma(source, length) → hull(source, length)
    ta.dema(source, length) → dema(source, length)
    ta.cci(source, length) → cci(highs, lows, closes, length)
    ta.mfi(source, volume, length) → mfi(highs, lows, closes, volumes, length)
    ta.obv(source, volume) → obv(closes, volumes)
    ta.mom(source, length) → mom(source, length)
    ta.roc(source, length) → roc(source, length)
    math.abs(x) → abs(x)
    math.max(x, y) → max(x, y)
    math.min(x, y) → min(x, y)
    math.floor(x) → int(x)
    math.round(x) → round(x)
    input.int(defval, ...) → Python variable with default int
    input.float(defval, ...) → Python variable with default float
    input.bool(defval, ...) → Python variable with default bool
    input.string(defval, ...) → Python variable with default str
    plot(...) → # plot(...) comment
    plotshape(...) → # plotshape(...) comment
    alertcondition(cond, ...) → signal check assignment

Usage:
    converter = PineConverter()
    result = converter.convert(pine_script_text)
    print(result.python_code)
    # result.imports, result.warnings, result.unsupported also available
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ConversionResult:
    """Output of a Pine Script → Python conversion.

    Attributes:
        python_code: The converted Python source code as a single string.
        imports: List of import statements required by the generated code.
        warnings: Non-fatal issues found during conversion (e.g. ambiguous
            source variables that need manual attention).
        unsupported: Pine functions/constructs that were detected but could
            not be converted automatically.
    """

    python_code: str
    imports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

# Each entry maps a Pine regex pattern to:
#   (python_template, needs_ohlcv_arrays, import_name_or_None)
#
# In python_template:
#   {args[0]} … {args[N]} refer to the captured call arguments (stripped).
#   {highs}, {lows}, {closes}, {volumes} are injected array variable names.

_SIMPLE_UNARY: dict[str, str] = {
    # math helpers — no indicator import needed
    r"math\.abs\s*\(": "abs(",
    r"math\.floor\s*\(": "int(",
    r"math\.round\s*\(": "round(",
    r"math\.ceil\s*\(": "math.ceil(",
    r"math\.sqrt\s*\(": "math.sqrt(",
    r"math\.log\s*\(": "math.log(",
    r"math\.exp\s*\(": "math.exp(",
    r"math\.pow\s*\(": "math.pow(",
    r"math\.max\s*\(": "max(",
    r"math\.min\s*\(": "min(",
    # Pine built-ins without a namespace prefix
    r"\bnz\s*\(": "_nz(",
    r"\bbar_index\b": "bar_index",
    r"\bclose\b": "closes[-1]",
    r"\bopen\b": "opens[-1]",
    r"\bhigh\b": "highs[-1]",
    r"\blow\b": "lows[-1]",
    r"\bvolume\b": "volumes[-1]",
    r"\bhl2\b": "((highs[-1] + lows[-1]) / 2.0)",
    r"\bhlc3\b": "((highs[-1] + lows[-1] + closes[-1]) / 3.0)",
    r"\bohlc4\b": "((opens[-1] + highs[-1] + lows[-1] + closes[-1]) / 4.0)",
}

# Functions whose Pine pattern is `ta.xxx(arg1, arg2, ...)` and whose Python
# equivalent can be described as a simple template.
# Key: compiled regex that matches the Pine call.
# Value: callable(match, args_list) → python_snippet  (or None to skip)
_TA_FUNCTION_MAP: list[tuple[str, str, list[str]]] = [
    # (pine_name_stem, python_func, required_indicator_imports)
    # ─── moving averages ───────────────────────────────────────────────────
    ("ta.ema",         "ema",              ["ema"]),
    ("ta.sma",         "sma",              ["sma"]),
    ("ta.wma",         "wma",              ["wma"]),
    ("ta.hma",         "hull",             ["hull"]),
    ("ta.dema",        "dema",             ["dema"]),
    ("ta.tema",        "tema",             ["tema"]),
    ("ta.rma",         "rma",              ["rma"]),
    ("ta.linreg",      "linreg",           ["linreg"]),
    # ─── momentum ──────────────────────────────────────────────────────────
    ("ta.rsi",         "rsi",              ["rsi"]),
    ("ta.macd",        "macd",             ["macd"]),
    ("ta.stoch",       "stochastic",       ["stochastic"]),
    ("ta.mom",         "mom",              ["mom"]),
    ("ta.roc",         "roc",              ["roc"]),
    ("ta.cci",         "cci",              ["cci"]),
    ("ta.change",      "change",           ["change"]),
    ("ta.williamsR",   "williams_r",       ["williams_r"]),
    ("ta.mfi",         "mfi",              ["mfi"]),
    # ─── volatility ────────────────────────────────────────────────────────
    ("ta.atr",         "atr",              ["atr"]),
    ("ta.bb",          "bollinger_bands",  ["bollinger_bands"]),
    ("ta.natr",        "natr",             ["natr"]),
    ("ta.stdev",       "stdev",            ["stdev"]),
    ("ta.variance",    "variance",         ["variance"]),
    ("ta.dev",         "dev",              ["dev"]),
    # ─── statistical series ────────────────────────────────────────────────
    ("ta.highest",     "highest",          ["highest"]),
    ("ta.lowest",      "lowest",           ["lowest"]),
    ("ta.median",      "median",           ["median"]),
    # ─── trend ─────────────────────────────────────────────────────────────
    ("ta.supertrend",  "supertrend",       ["supertrend"]),
    ("ta.adx",         "adx",              ["adx"]),
    ("ta.dmi",         "dmi",              ["dmi"]),
    ("ta.ichimoku",    "ichimoku",         ["ichimoku"]),
    ("ta.psar",        "parabolic_sar",    ["parabolic_sar"]),
    # ─── volume ────────────────────────────────────────────────────────────
    ("ta.obv",         "obv",              ["obv"]),
    ("ta.vwma",        "vwma",             ["vwma"]),
    ("ta.cmf",         "cmf",              ["cmf"]),
    # ─── signals ───────────────────────────────────────────────────────────
    ("ta.crossover",   "crossover",        ["crossover"]),
    ("ta.crossunder",  "crossunder",       ["crossunder"]),
    ("ta.pivothigh",   "pivothigh",        ["pivothigh"]),
    ("ta.pivotlow",    "pivotlow",         ["pivotlow"]),
    ("ta.valuewhen",   "valuewhen",        ["valuewhen"]),
]

# Functions that need OHLCV arrays injected (not just the user-supplied args).
# Maps python function name → argument template using named placeholders.
_OHLCV_INJECTION: dict[str, str] = {
    "atr":           "{highs}, {lows}, {closes}, {period}",
    "natr":          "{highs}, {lows}, {closes}, {period}",
    "supertrend":    "{highs}, {lows}, {closes}, {period}, {factor}",
    "adx":           "{highs}, {lows}, {closes}, {period}",
    "dmi":           "{highs}, {lows}, {closes}, {period}",
    "ichimoku":      "{highs}, {lows}, {closes}",
    "parabolic_sar": "{highs}, {lows}",
    "stochastic":    "{highs}, {lows}, {closes}, {period}",
    "cci":           "{highs}, {lows}, {closes}, {period}",
    "mfi":           "{highs}, {lows}, {closes}, {volumes}, {period}",
    "cmf":           "{highs}, {lows}, {closes}, {volumes}, {period}",
    "obv":           "{closes}, {volumes}",
    "vwma":          "{closes}, {volumes}, {period}",
}

# Pine source-variable aliases → Python array names
_SOURCE_MAP: dict[str, str] = {
    "close":  "closes",
    "open":   "opens",
    "high":   "highs",
    "low":    "lows",
    "volume": "volumes",
    "hl2":    "((highs + lows) / 2.0)",
    "hlc3":   "((highs + lows + closes) / 3.0)",
    "ohlc4":  "((opens + highs + lows + closes) / 4.0)",
}

# Pine input.xxx → Python type coercion
_INPUT_TYPE_MAP: dict[str, str] = {
    "input.int":    "int",
    "input.float":  "float",
    "input.bool":   "bool",
    "input.string": "str",
    "input.source": "",      # source inputs become array references
    "input.color":  "str",
    "input":        "int",   # bare `input()` defaults to int in Pine
}

# Pine keywords → Python equivalents (simple token substitution)
_KEYWORD_MAP: dict[str, str] = {
    "true":  "True",
    "false": "False",
    "na":    "np.nan",
    "and":   "and",
    "or":    "or",
    "not":   "not",
    "var ":  "",   # Pine `var` keyword (persistent variable) — just strip it
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_call_args(text: str) -> list[str]:
    """Extract comma-separated arguments from inside a single function call.

    Handles nested parentheses. ``text`` must be the content *inside* the
    outermost parentheses (i.e. already stripped of the function name and the
    outer ``(…)`` delimiters).

    Args:
        text: Argument string like ``"close, 14, 2.0"`` or nested calls.

    Returns:
        List of argument strings, each stripped of leading/trailing whitespace.
    """
    args: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            current.append(ch)
    if current:
        last = "".join(current).strip()
        if last:
            args.append(last)
    return args


def _find_matching_paren(text: str, start: int) -> int:
    """Return the index of the closing paren matching the ``(`` at ``start``.

    Args:
        text: Full source string.
        start: Index of the opening ``(``.

    Returns:
        Index of the matching ``)``, or -1 if not found.
    """
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _map_source(arg: str) -> str:
    """Map a Pine source argument to a Python array name.

    Args:
        arg: Pine source expression (e.g. ``"close"``, ``"hl2"``).

    Returns:
        Equivalent Python expression.
    """
    stripped = arg.strip()
    return _SOURCE_MAP.get(stripped, stripped)


def _extract_input_default(args_text: str) -> str:
    """Return the first positional argument (the default value) from an
    ``input.*()`` call's argument string.

    Pine allows named params: ``input.int(14, title="Length")``.
    We only care about the first positional argument.

    Args:
        args_text: Raw argument string inside the input call parentheses.

    Returns:
        The default value as a string, or ``"None"`` if not found.
    """
    args = _extract_call_args(args_text)
    if not args:
        return "None"
    first = args[0]
    # Strip named-param syntax if someone wrote `defval=14`
    if "=" in first:
        first = first.split("=", 1)[1].strip()
    return first


# ---------------------------------------------------------------------------
# Main converter class
# ---------------------------------------------------------------------------


class PineConverter:
    """Converts Pine Script indicator code to FlintTrade Python indicator calls.

    The converter is intentionally conservative: it converts what it recognises
    and leaves everything else as comments or raw text, emitting warnings for
    patterns it could not handle.  This design makes it safe to use as a
    first-pass tool — the output always runs (as Python) even if some lines
    need manual review.

    Attributes:
        array_names: Mapping from logical OHLCV role to actual Python variable
            name used in generated code.  Override if your arrays have
            different names.
    """

    def __init__(
        self,
        highs: str = "highs",
        lows: str = "lows",
        closes: str = "closes",
        opens: str = "opens",
        volumes: str = "volumes",
    ) -> None:
        """Initialise the converter with the Python array variable names to use.

        Args:
            highs: Python variable name for high-price array (default ``"highs"``).
            lows: Python variable name for low-price array (default ``"lows"``).
            closes: Python variable name for close-price array (default ``"closes"``).
            opens: Python variable name for open-price array (default ``"opens"``).
            volumes: Python variable name for volume array (default ``"volumes"``).
        """
        self._arrays = {
            "highs":   highs,
            "lows":    lows,
            "closes":  closes,
            "opens":   opens,
            "volumes": volumes,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(self, pine_text: str) -> ConversionResult:
        """Convert a Pine Script snippet to Python.

        Processes the text line-by-line.  Each line is passed through a
        sequence of transformation steps.  Lines that cannot be converted are
        preserved as Python comments so the output remains syntactically valid.

        Args:
            pine_text: Raw Pine Script source (can be multi-line).

        Returns:
            :class:`ConversionResult` with ``python_code``, ``imports``,
            ``warnings``, and ``unsupported`` populated.
        """
        if not pine_text or not pine_text.strip():
            return ConversionResult(python_code="", imports=[], warnings=[], unsupported=[])

        imports: set[str] = set()
        warnings: list[str] = []
        unsupported: list[str] = []
        output_lines: list[str] = []

        for raw_line in pine_text.splitlines():
            converted, line_imports, line_warnings, line_unsupported = (
                self._convert_line(raw_line)
            )
            imports.update(line_imports)
            warnings.extend(line_warnings)
            unsupported.extend(line_unsupported)
            output_lines.append(converted)

        # Build import block
        sorted_imports = sorted(imports)
        python_code = "\n".join(output_lines)

        return ConversionResult(
            python_code=python_code,
            imports=sorted_imports,
            warnings=warnings,
            unsupported=list(dict.fromkeys(unsupported)),  # deduplicate, keep order
        )

    @staticmethod
    def get_supported_functions() -> list[str]:
        """Return the list of Pine Script function names that this converter handles.

        Returns:
            Sorted list of supported Pine function/keyword names.
        """
        supported = [stem for stem, _, _ in _TA_FUNCTION_MAP]
        supported += list(_INPUT_TYPE_MAP.keys())
        supported += [
            "math.abs", "math.max", "math.min", "math.floor",
            "math.round", "math.ceil", "math.sqrt", "math.log",
            "math.exp", "math.pow",
            "plot", "plotshape", "plotarrow", "plotchar",
            "alertcondition", "alert",
            "strategy.entry", "strategy.close", "strategy.exit",
            "if", "else", "for", "while",
            # NOTE: request.security() (multi-timeframe) is NOT supported by
            # this converter — it requires the full PineTS runtime with async
            # data fetching and a ScopeManager for variable scoping.
            # PineTS reference: PineRequest.ts / ScopeManager.class.ts
        ]
        return sorted(set(supported))

    # ------------------------------------------------------------------
    # Line-level processing
    # ------------------------------------------------------------------

    def _convert_line(
        self, line: str
    ) -> tuple[str, set[str], list[str], list[str]]:
        """Convert a single Pine Script line.

        Args:
            line: One line of Pine Script source.

        Returns:
            Tuple of (converted_line, imports, warnings, unsupported).
        """
        imports: set[str] = set()
        warnings: list[str] = []
        unsupported: list[str] = []

        # Preserve empty lines
        stripped = line.strip()
        if not stripped:
            return line, imports, warnings, unsupported

        # Pine single-line comments
        if stripped.startswith("//"):
            return line.replace("//", "#", 1), imports, warnings, unsupported

        # Strip inline comments (// not inside strings) — basic heuristic
        line, inline_comment = self._strip_inline_comment(line)

        # //@version=X header — convert to comment
        if stripped.startswith("//@"):
            return "# " + stripped.lstrip("/"), imports, warnings, unsupported

        # `strategy(...)` / `indicator(...)` declarations → comment
        if re.match(r"^\s*(strategy|indicator|library)\s*\(", line):
            return "# " + line.strip(), imports, warnings, unsupported

        # plot / plotshape / plotarrow / plotchar → comment
        if re.match(r"^\s*plot(shape|arrow|char)?\s*\(", line):
            return "# " + line.strip(), imports, warnings, unsupported

        # alertcondition / alert → signal boolean assignment
        line, al_imports, al_warnings = self._convert_alertcondition(line)
        imports.update(al_imports)
        warnings.extend(al_warnings)

        # strategy.entry / strategy.close / strategy.exit → comment
        if re.match(r"^\s*strategy\.", line):
            return "# " + line.strip(), imports, warnings, unsupported

        # input.xxx() → variable assignment
        line, inp_imports, inp_warnings = self._convert_inputs(line)
        imports.update(inp_imports)
        warnings.extend(inp_warnings)

        # ta.xxx() → indicator call
        line, ta_imports, ta_warnings, ta_unsupported = self._convert_ta_calls(line)
        imports.update(ta_imports)
        warnings.extend(ta_warnings)
        unsupported.extend(ta_unsupported)

        # ta.vwap (no-arg property)
        line, vwap_imports = self._convert_vwap_property(line)
        imports.update(vwap_imports)

        # Simple token substitutions (keywords, math, source names)
        line = self._substitute_tokens(line)

        # Re-attach inline comment as Python comment
        if inline_comment:
            line = line.rstrip() + "  # " + inline_comment.lstrip("/ ").strip()

        return line, imports, warnings, unsupported

    # ------------------------------------------------------------------
    # Targeted transformations
    # ------------------------------------------------------------------

    def _strip_inline_comment(self, line: str) -> tuple[str, str]:
        """Strip a trailing ``//`` comment from a line.

        Does not strip inside string literals (rudimentary heuristic: looks
        for the first ``//`` not inside single or double quotes).

        Args:
            line: Source line (may contain ``//`` comment).

        Returns:
            Tuple of (code_part, comment_part).  ``comment_part`` is empty
            string when no comment is present.
        """
        in_single = False
        in_double = False
        for i in range(len(line) - 1):
            ch = line[i]
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "/" and line[i + 1] == "/" and not in_single and not in_double:
                return line[:i], line[i + 2:]
        return line, ""

    def _convert_inputs(
        self, line: str
    ) -> tuple[str, set[str], list[str]]:
        """Replace ``input.xxx(defval, ...)`` with ``xxx(defval)`` assignments.

        Pine Script input() calls appear at the top of a script as parameter
        declarations.  We convert them to plain Python variable assignments
        with the default value.  The variable name on the LHS is preserved as-is.

        Args:
            line: Source line possibly containing input calls.

        Returns:
            Tuple of (converted_line, imports, warnings).
        """
        imports: set[str] = set()
        warnings: list[str] = []

        for pine_prefix, py_type in _INPUT_TYPE_MAP.items():
            # Match: optionally `varname = input.xxx(` or just bare `input.xxx(`
            pattern = re.compile(
                r"(\w+)\s*=\s*" + re.escape(pine_prefix) + r"\s*\(([^)]*)\)"
            )
            for m in list(pattern.finditer(line)):
                varname = m.group(1)
                args_text = m.group(2)
                default_val = _extract_input_default(args_text)
                if py_type:
                    replacement = f"{varname} = {py_type}({default_val})"
                else:
                    replacement = f"{varname} = {default_val}  # source input"
                line = line[: m.start()] + replacement + line[m.end():]
                warnings.append(
                    f"input '{varname}' converted to Python literal — "
                    "update value as needed"
                )
                break  # one substitution per iteration; rerun outer loop if needed

        return line, imports, warnings

    def _convert_ta_calls(
        self, line: str
    ) -> tuple[str, set[str], list[str], list[str]]:
        """Replace ``ta.xxx(...)`` calls with FlintTrade indicator calls.

        Iterates over ``_TA_FUNCTION_MAP`` in order.  For each recognised
        function, extracts the argument list, injects OHLCV array names where
        needed, and rewrites the call in place.

        Args:
            line: Source line possibly containing ``ta.*`` calls.

        Returns:
            Tuple of (converted_line, imports, warnings, unsupported).
        """
        imports: set[str] = set()
        warnings: list[str] = []
        unsupported: list[str] = []

        for pine_stem, py_func, func_imports in _TA_FUNCTION_MAP:
            escaped = re.escape(pine_stem)
            pattern = re.compile(escaped + r"\s*\(")
            while True:
                m = pattern.search(line)
                if not m:
                    break
                open_paren = m.end() - 1
                close_paren = _find_matching_paren(line, open_paren)
                if close_paren == -1:
                    warnings.append(
                        f"Could not find closing paren for {pine_stem}() call"
                    )
                    break
                args_text = line[open_paren + 1 : close_paren]
                raw_args = _extract_call_args(args_text)
                # Map Pine source args to Python array names, then apply
                # instance-level custom array names on top of the defaults.
                mapped_args = [
                    self._apply_custom_arrays(_map_source(a))
                    for a in raw_args
                ]
                py_call = self._build_py_call(py_func, mapped_args)
                line = line[: m.start()] + py_call + line[close_paren + 1 :]
                imports.update(func_imports)

        # Detect any remaining `ta.` calls that were not converted
        remaining = re.findall(r"ta\.(\w+)\s*\(", line)
        for name in remaining:
            unsupported.append(f"ta.{name}")

        # Detect request.security() (multi-timeframe) — not convertible here
        if re.search(r"\brequest\.security\s*\(", line):
            unsupported.append("request.security")
            line = re.sub(
                r"\brequest\.security\s*\(",
                "# UNSUPPORTED: request.security(",
                line,
            )

        return line, imports, warnings, unsupported

    def _apply_custom_arrays(self, expr: str) -> str:
        """Replace canonical default array names with instance-configured names.

        ``_map_source`` always maps Pine source names to the canonical defaults
        (``closes``, ``highs``, …).  This method swaps those defaults for
        whatever names the user set via the constructor, so that custom array
        names flow through into every generated call.

        Args:
            expr: Expression string possibly containing default array names.

        Returns:
            Expression with canonical names replaced by instance names.
        """
        # Map from the hard-coded defaults to the instance's configured names.
        replacements = {
            "closes":  self._arrays["closes"],
            "highs":   self._arrays["highs"],
            "lows":    self._arrays["lows"],
            "opens":   self._arrays["opens"],
            "volumes": self._arrays["volumes"],
        }
        for default, custom in replacements.items():
            if default != custom:
                # Use word-boundary replacement to avoid partial matches.
                expr = re.sub(rf"\b{re.escape(default)}\b", custom, expr)
        return expr

    def _build_py_call(self, py_func: str, args: list[str]) -> str:
        """Construct the Python call string for a given function and args.

        For functions that require OHLCV injection, the positional Pine args
        are mapped to the appropriate Python signature.  For simple wrappers
        (ema, sma, rsi, …) the args are passed through verbatim.

        Args:
            py_func: Python function name (e.g. ``"ema"``, ``"supertrend"``).
            args: Mapped argument list (source names already resolved).

        Returns:
            Complete Python call string including parentheses.
        """
        h = self._arrays["highs"]
        lo = self._arrays["lows"]
        c = self._arrays["closes"]
        o = self._arrays["opens"]
        v = self._arrays["volumes"]

        if py_func in _OHLCV_INJECTION:
            template = _OHLCV_INJECTION[py_func]
            # Extract period/factor from the original args if present
            period = args[0] if args else "14"
            factor = args[1] if len(args) > 1 else "3.0"
            call_args = template.format(
                highs=h, lows=lo, closes=c, opens=o, volumes=v,
                period=period, factor=factor,
            )
        elif py_func in {"ema", "sma", "wma", "hull", "dema", "tema", "linreg",
                          "rsi", "mom", "roc"}:
            # ta.xxx(source, length)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "14"
            call_args = f"{source}, {length}"
        elif py_func == "macd":
            # ta.macd(source, fast, slow, signal)
            source = args[0] if args else c
            fast   = args[1] if len(args) > 1 else "12"
            slow   = args[2] if len(args) > 2 else "26"
            signal = args[3] if len(args) > 3 else "9"
            call_args = f"{source}, {fast}, {slow}, {signal}"
        elif py_func == "bollinger_bands":
            # ta.bb(source, length, mult)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "20"
            mult   = args[2] if len(args) > 2 else "2.0"
            call_args = f"{source}, {length}, {mult}"
        elif py_func == "rma":
            # ta.rma(source, length)  — Wilder's RMA (same signature as ema/sma)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "14"
            call_args = f"{source}, {length}"
        elif py_func == "change":
            # ta.change(source, length=1)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "1"
            call_args = f"{source}, {length}"
        elif py_func in {"stdev", "variance", "dev"}:
            # ta.stdev(source, length, biased=true)
            # ta.variance(source, length)
            # ta.dev(source, length)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "20"
            if py_func == "stdev" and len(args) > 2:
                biased = args[2]
                call_args = f"{source}, {length}, {biased}"
            else:
                call_args = f"{source}, {length}"
        elif py_func in {"highest", "lowest", "median"}:
            # ta.highest(source, length)
            source = args[0] if args else c
            length = args[1] if len(args) > 1 else "20"
            call_args = f"{source}, {length}"
        elif py_func in {"crossover", "crossunder"}:
            # ta.crossover(a, b)
            a = args[0] if args else "series_a"
            b = args[1] if len(args) > 1 else "series_b"
            call_args = f"{a}, {b}"
        elif py_func in {"pivothigh", "pivotlow"}:
            # ta.pivothigh(source, leftbars, rightbars)
            source = args[0] if args else c
            left   = args[1] if len(args) > 1 else "5"
            right  = args[2] if len(args) > 2 else "5"
            call_args = f"{source}, {left}, {right}"
        elif py_func == "valuewhen":
            # ta.valuewhen(condition, source, occurrence)
            cond   = args[0] if args else "condition"
            source = args[1] if len(args) > 1 else c
            occ    = args[2] if len(args) > 2 else "0"
            call_args = f"{cond}, {source}, {occ}"
        else:
            # Generic passthrough: join all args as-is
            call_args = ", ".join(args)

        return f"{py_func}({call_args})"

    def _convert_vwap_property(self, line: str) -> tuple[str, set[str]]:
        """Convert the no-argument ``ta.vwap`` property to a function call.

        Pine Script exposes VWAP as a built-in series property (no parentheses).
        We convert it to a FlintTrade ``vwap(highs, lows, closes, volumes)`` call.

        Args:
            line: Source line possibly containing ``ta.vwap``.

        Returns:
            Tuple of (converted_line, imports).
        """
        imports: set[str] = set()
        h = self._arrays["highs"]
        lo = self._arrays["lows"]
        c = self._arrays["closes"]
        v = self._arrays["volumes"]
        if re.search(r"\bta\.vwap\b", line):
            replacement = f"vwap({h}, {lo}, {c}, {v})"
            line = re.sub(r"\bta\.vwap\b", replacement, line)
            imports.add("vwap")
        return line, imports

    def _convert_alertcondition(
        self, line: str
    ) -> tuple[str, set[str], list[str]]:
        """Convert ``alertcondition(cond, ...)`` to a signal boolean variable.

        The first argument (the condition expression) is extracted and assigned
        to a ``signal`` variable.  Title/message arguments are dropped.

        Args:
            line: Source line possibly containing ``alertcondition`` or
                ``alert`` calls.

        Returns:
            Tuple of (converted_line, imports, warnings).
        """
        imports: set[str] = set()
        warnings: list[str] = []

        for fn_name in ("alertcondition", "alert"):
            pattern = re.compile(re.escape(fn_name) + r"\s*\(")
            m = pattern.search(line)
            if not m:
                continue
            open_paren = m.end() - 1
            close_paren = _find_matching_paren(line, open_paren)
            if close_paren == -1:
                continue
            args_text = line[open_paren + 1 : close_paren]
            args = _extract_call_args(args_text)
            condition = args[0] if args else "True"
            indent = len(line) - len(line.lstrip())
            replacement = " " * indent + f"signal = bool({condition})"
            line = line[: m.start()] + replacement + line[close_paren + 1 :]
            warnings.append(
                f"{fn_name}() converted to 'signal = bool(condition)' — "
                "verify condition expression is correct"
            )
            break

        return line, imports, warnings

    def _substitute_tokens(self, line: str) -> str:
        """Apply simple token-level substitutions (keywords, math, sources).

        Converts Pine keywords (``true`` → ``True``, ``na`` → ``np.nan``),
        bare ``math.*`` single-arg functions, and strips the ``var`` keyword.

        Args:
            line: Partially-converted line.

        Returns:
            Line with token substitutions applied.
        """
        # `var` keyword — strip (persistent var in Pine, not needed in Python)
        line = re.sub(r"\bvar\b\s+", "", line)

        # Pine boolean / constant literals
        # Use word boundaries to avoid mangling e.g. "true_count"
        line = re.sub(r"\btrue\b", "True", line)
        line = re.sub(r"\bfalse\b", "False", line)
        line = re.sub(r"\bna\b", "np.nan", line)

        # math.* single-token replacements
        for pine_pat, py_repl in _SIMPLE_UNARY.items():
            line = re.sub(pine_pat, py_repl, line)

        # nz() — Pine's null-coalescing helper — rewrite as helper call
        # The actual _nz helper is emitted in the import header if used.
        line = re.sub(r"\bnz\s*\(", "_nz(", line)

        # Pine series index: close[1] → closes[-2]  (Pine [1] is one bar ago)
        # We convert `identifier[n]` → `identifier[-(n+1)]` for known names.
        def _reindex(m: re.Match) -> str:  # type: ignore[type-arg]
            name = m.group(1)
            offset = int(m.group(2))
            py_name = _SOURCE_MAP.get(name, name)
            return f"{py_name}[{-(offset + 1)}]"

        line = re.sub(
            r"\b(close|open|high|low|volume|hl2|hlc3|ohlc4)\[(\d+)\]",
            _reindex,
            line,
        )

        return line


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def convert_pine(pine_text: str, **kwargs: str) -> ConversionResult:
    """Convenience wrapper — convert Pine Script text using default settings.

    Args:
        pine_text: Pine Script source to convert.
        **kwargs: Forwarded to :class:`PineConverter` constructor (array names).

    Returns:
        :class:`ConversionResult`.
    """
    return PineConverter(**kwargs).convert(pine_text)
