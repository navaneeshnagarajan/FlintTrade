"""Hook-free structural validation and detachment of finite JSON evidence.

This module establishes no broker coherence, execution, protection or authority.
Callers retain their own field semantics and translate ValueError as appropriate.
"""

from __future__ import annotations

import math


def copy_json_evidence(value: object) -> object:
    """Return a detached tree containing only exact, finite JSON values.

    Accept None and exact built-in str, bool, int, finite float, list and dict
    values; dictionary keys must be exact strings. Count the root container as
    one: at most 64 containers may occur on a branch, including an empty leaf
    container. Primitives beneath the 64th container remain valid. Reject cycles
    on the current ancestor branch; copy shared acyclic containers independently
    for each occurrence rather than retaining aliases.

    No conversion, serialisation, deepcopy or subclass hooks are invoked. Keep
    insertion/list order, nulls, exact integers and float values (including -0.0).
    Immutable primitives may be shared; every returned container is new.

    Args:
        value: Untrusted decoded evidence, not an admission or execution claim.

    Returns:
        The structurally validated tree, detached from every input container.

    Raises:
        ValueError: A value/key is not an exact permitted type, a float is not
            finite, a branch is cyclic, or a branch exceeds 64 containers.
    """
    def copy_branch(current: object, ancestors: frozenset[int]) -> object:
        if current is None or type(current) is str or type(current) is bool or type(current) is int:
            return current
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError("JSON evidence requires finite floats")
            return current
        if type(current) is list or type(current) is dict:
            if id(current) in ancestors or len(ancestors) >= 64:
                raise ValueError("JSON evidence requires acyclic branches of at most 64 containers")
            ancestors = ancestors | {id(current)}
            if type(current) is list:
                return [copy_branch(child, ancestors) for child in current]
            if type(current) is dict:
                if any(type(key) is not str for key in current):
                    raise ValueError("JSON evidence requires exact string keys")
                return {key: copy_branch(child, ancestors) for key, child in current.items()}
        raise ValueError("JSON evidence requires exact built-in values")

    return copy_branch(value, frozenset())
