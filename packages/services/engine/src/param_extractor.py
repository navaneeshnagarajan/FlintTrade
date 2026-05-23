"""AST-based parameter extraction for user strategy code.

Parses Python source with the ``ast`` module to discover user-configurable
parameters.  Supports two discovery mechanisms:

1. **Comment markers** — a line immediately before a top-level assignment
   that contains ``# param:`` with an optional structured annotation::

       # param: period int 14 EMA look-back period
       PERIOD = 14

   Format: ``# param: <name> <type> <default> <description...>``
   All fields after ``# param:`` are optional; missing fields fall back to
   inferred values from the assignment itself.

2. **Plain top-level assignments** — uppercase or mixed-case scalar
   assignments at module scope are auto-detected even without a comment::

       THRESHOLD = 0.5
       stop_loss_pct = 2.0

   These generate ``StrategyParam`` entries with type and default inferred
   from the assigned literal value.

Used by StrategyBuilder's UI to auto-populate a parameter panel so traders
can tweak strategy constants without editing source code.

Example::

    from flinttrade_engine.param_extractor import extract_params

    code = '''
    # param: period int 14 Look-back window
    PERIOD = 14
    THRESHOLD = 0.5
    '''
    params = extract_params(code)
    # [StrategyParam(name='PERIOD', type='int', default=14, description='Look-back window'),
    #  StrategyParam(name='THRESHOLD', type='float', default=0.5, description='')]
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("flinttrade.engine.param_extractor")

# ---------------------------------------------------------------------------
# Regex for structured comment markers
# ---------------------------------------------------------------------------

# Matches: # param: name [type [default [description...]]]
_PARAM_COMMENT_RE = re.compile(
    r"#\s*param:\s*"
    r"(?P<name>\w+)"
    r"(?:\s+(?P<type>\w+))?"
    r"(?:\s+(?P<default>\S+))?"
    r"(?:\s+(?P<description>.+))?",
    re.IGNORECASE,
)

# Types that Python ``ast.Constant`` can hold and that map cleanly to a
# JSON-serialisable Python type name.
_LITERAL_TYPE_MAP: dict[type, str] = {
    int: "int",
    float: "float",
    bool: "bool",
    str: "str",
    bytes: "bytes",
}

# Recognised type name aliases (for comment annotations)
_TYPE_ALIASES: dict[str, str] = {
    "int": "int",
    "integer": "int",
    "float": "float",
    "double": "float",
    "number": "float",
    "bool": "bool",
    "boolean": "bool",
    "str": "str",
    "string": "str",
    "text": "str",
}


# ---------------------------------------------------------------------------
# StrategyParam
# ---------------------------------------------------------------------------


@dataclass
class StrategyParam:
    """A single user-configurable strategy parameter.

    Attributes:
        name: Variable name as it appears in source code.
        type: Python type name (``"int"``, ``"float"``, ``"bool"``, ``"str"``).
        default: Default value extracted from the literal assignment.
        description: Human-readable description from the comment annotation
            (empty string when not provided).
        line: Source line number of the assignment (1-based).
        source: How this param was discovered (``"comment"`` or ``"inferred"``).
    """

    name: str
    type: str
    default: Any = None
    description: str = ""
    line: int = 0
    source: str = "inferred"  # "comment" | "inferred"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "line": self.line,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_params(source_code: str) -> list[StrategyParam]:
    """Parse Python source and return all discoverable strategy parameters.

    Processes two discovery mechanisms in a single AST pass:

    1. Assignments immediately preceded by a ``# param:`` comment line.
    2. Bare top-level scalar assignments (int / float / bool / str literals).

    Params discovered via ``# param:`` comment take precedence — if the
    same variable name is found both ways, the comment annotation wins.

    Args:
        source_code: Raw Python source text to analyse.

    Returns:
        Ordered list of ``StrategyParam`` objects, one per discovered
        parameter, in source-file order (ascending line number).

    Raises:
        ValueError: If ``source_code`` is not syntactically valid Python.
    """
    if not source_code or not source_code.strip():
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        raise ValueError(f"Could not parse source code: {exc}") from exc

    source_lines = source_code.splitlines()

    # Pass 1: collect all # param: comment annotations keyed by variable name
    comment_annotations: dict[str, _CommentAnnotation] = _collect_comment_annotations(
        source_lines
    )

    # Pass 2: walk the AST for top-level assignments
    params_by_name: dict[str, StrategyParam] = {}

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue

        value = node.value
        # Only care about simple literal assignments
        if not isinstance(value, ast.Constant):
            continue

        literal_value = value.value
        python_type = type(literal_value)
        if python_type not in _LITERAL_TYPE_MAP:
            continue

        inferred_type = _LITERAL_TYPE_MAP[python_type]

        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            var_name = target.id

            # Skip dunder variables and private names
            if var_name.startswith("__"):
                continue

            lineno = node.lineno

            # Does a comment annotation exist for this line?
            annotation = comment_annotations.get(var_name)
            comment_line = lineno - 1  # 1-based line above the assignment

            if annotation and annotation.line == comment_line:
                # Use comment metadata; fall back to inferred values for any
                # fields not specified in the annotation.
                param = StrategyParam(
                    name=annotation.name or var_name,
                    type=_TYPE_ALIASES.get(annotation.type_hint or "", inferred_type),
                    default=_coerce_default(
                        annotation.default_str, inferred_type, literal_value
                    ),
                    description=annotation.description,
                    line=lineno,
                    source="comment",
                )
            else:
                # Auto-infer from the assignment
                param = StrategyParam(
                    name=var_name,
                    type=inferred_type,
                    default=literal_value,
                    description="",
                    line=lineno,
                    source="inferred",
                )

            # Comment-sourced params always override inferred ones
            existing = params_by_name.get(var_name)
            if existing is None or existing.source == "inferred":
                params_by_name[var_name] = param

    # Sort by source line and return
    return sorted(params_by_name.values(), key=lambda p: p.line)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _CommentAnnotation:
    """Parsed content of a ``# param:`` comment line.

    Attributes:
        name: Variable name from the annotation.
        type_hint: Raw type string from the annotation (may be an alias).
        default_str: Raw default string from the annotation.
        description: Description text from the annotation.
        line: 1-based line number of the comment itself.
    """

    name: str
    type_hint: str = ""
    default_str: str = ""
    description: str = ""
    line: int = 0


def _collect_comment_annotations(
    lines: list[str],
) -> dict[str, _CommentAnnotation]:
    """Scan source lines for ``# param:`` annotations.

    Args:
        lines: Source file lines (1-based indexing when reported).

    Returns:
        Dict mapping variable name → ``_CommentAnnotation``.
        The ``line`` attribute stores the 1-based line of the comment.
    """
    annotations: dict[str, _CommentAnnotation] = {}
    for idx, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        match = _PARAM_COMMENT_RE.match(stripped)
        if match is None:
            continue
        name = match.group("name") or ""
        if not name:
            continue
        annotations[name] = _CommentAnnotation(
            name=name,
            type_hint=match.group("type") or "",
            default_str=match.group("default") or "",
            description=(match.group("description") or "").strip(),
            line=idx,
        )
    return annotations


def _coerce_default(
    default_str: str,
    inferred_type: str,
    fallback: Any,
) -> Any:
    """Try to parse ``default_str`` as ``inferred_type``; fall back to ``fallback``.

    Args:
        default_str: Raw string from the ``# param:`` annotation.
        inferred_type: Python type name (``"int"``, ``"float"``, etc.).
        fallback: Value to use when ``default_str`` is empty or unparseable.

    Returns:
        Coerced Python value.
    """
    if not default_str:
        return fallback
    try:
        if inferred_type == "int":
            return int(default_str)
        if inferred_type == "float":
            return float(default_str)
        if inferred_type == "bool":
            return default_str.lower() in ("true", "1", "yes")
        return default_str  # str: keep as-is
    except (ValueError, TypeError):
        return fallback
