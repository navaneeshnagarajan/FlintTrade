"""Fresh retained-capability checks beside exact-container absence classification."""
from __future__ import annotations

from typing import Any

import pytest

from flinttrade_engine.strategy_execution import StrategyExecutionContract
from packages.services.engine.tests.test_scheduler_lifecycle_regressions import _RawWriter, _TestStrategy

pytestmark = pytest.mark.unit

_GLOBAL_CAPABILITY: Any = None


def _empty(_value: Any = None) -> None:
    """Benign callback with no retained writer."""


def _global() -> Any:
    """Read the current referenced global; identity is not immutable state."""
    return _GLOBAL_CAPABILITY


@pytest.mark.parametrize("container", [dict, list, tuple, set, frozenset, lambda: _empty,
                                     lambda: len, lambda: str.__repr__, lambda: list.append,
                                     lambda: dict.fromkeys, lambda: property(_empty),
                                     lambda: staticmethod(_empty), lambda: classmethod(_empty)],
                         ids=["dict", "list", "tuple", "set", "frozenset", "<lambda>", "builtin-function",
                              "wrapper-descriptor", "method-descriptor", "builtin-method", "property",
                              "staticmethod", "classmethod"])
def test_exact_container_classification_avoids_repeated_absence_probes(monkeypatch: Any, container: type) -> None:
    """Skip redundant direct-name absence probes, not the graph or its children."""
    value = container()
    strategy = _TestStrategy(name="exact-container")
    strategy.retained = value
    probes = []
    original = StrategyExecutionContract._has_callable

    def observe(cls: type, target: Any, name: str) -> bool:
        if target is value:
            probes.append(name)
        return original(target, name)

    monkeypatch.setattr(StrategyExecutionContract, "_has_callable", classmethod(observe))
    strategy.require_execution_contract()
    assert probes == []


@pytest.mark.parametrize("shape", ["dict-key", "dict-value", "list", "tuple", "set", "frozenset"])
def test_exact_containers_still_retain_nested_writers(shape: str) -> None:
    """Every eligible container must still traverse its actual retained contents."""
    writer = _RawWriter()
    values = {"dict-key": {writer: None}, "dict-value": {"writer": writer}, "list": [writer],
              "tuple": (writer,), "set": {writer}, "frozenset": frozenset({writer})}
    strategy = _TestStrategy(name="nested-writer")
    strategy.retained = values[shape]
    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        strategy.require_execution_contract()


@pytest.mark.parametrize("shape", ["dict", "list", "set"])
def test_same_container_is_rechecked_after_writer_injection(shape: str) -> None:
    """A previous clean walk cannot authorise a later mutation of the same object."""
    value: Any = {"dict": {}, "list": [], "set": set()}[shape]
    strategy = _TestStrategy(name="mutable-container")
    strategy.retained = value
    strategy.require_execution_contract()
    if shape == "dict":
        value["writer"] = _RawWriter()
    elif shape == "list":
        value.append(_RawWriter())
    else:
        value.add(_RawWriter())
    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        strategy.require_execution_contract()


@pytest.mark.parametrize("container", [dict, list, tuple, set, frozenset])
@pytest.mark.parametrize("kind", ["method", "state"])
def test_container_subclasses_keep_generic_capability_checks(container: type, kind: str) -> None:
    """A builtin subclass may carry its own direct or retained mutation surface."""
    class Wrapped(container):
        """An ordinary user-controlled subclass, never an exact builtin."""

    value = Wrapped()
    if kind == "method":
        Wrapped.place_order = _empty
    else:
        value.writer = _RawWriter()
    strategy = _TestStrategy(name="subclass-writer")
    strategy.retained = value
    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        strategy.require_execution_contract()


@pytest.mark.parametrize("container", [dict, list, tuple, set, frozenset, lambda: _empty])
@pytest.mark.parametrize("method", ["__str__", "__iter__"])
def test_current_mutation_policy_checks_builtin_and_object_names(
    monkeypatch: Any, container: type, method: str,
) -> None:
    """An extended policy must fall back for callable names inherited from object."""
    value = container()
    if value is _empty and method == "__iter__":
        method = "__call__"
    assert not StrategyExecutionContract._is_direct_mutation_capability(value)
    monkeypatch.setattr(StrategyExecutionContract, "_MUTATION_METHODS",
                        StrategyExecutionContract._MUTATION_METHODS | {method})
    assert StrategyExecutionContract._is_direct_mutation_capability(value)


def test_function_attached_mutation_method_is_not_an_absent_name(monkeypatch: Any) -> None:
    """Exact functions can gain direct capabilities without changing their identity."""
    assert not StrategyExecutionContract._is_direct_mutation_capability(_empty)
    monkeypatch.setattr(_empty, "place_order", lambda: None, raising=False)
    assert StrategyExecutionContract._is_direct_mutation_capability(_empty)


@pytest.mark.parametrize("kind", ["code", "defaults", "kwdefaults", "closure", "global", "attached", "callable"])
def test_same_callable_identity_rechecks_current_retained_state(monkeypatch: Any, kind: str) -> None:
    """Code, closures and callable state remain fresh on each authority inspection."""
    def callback(value: Any = None, *, other: Any = None) -> Any:
        return value, other

    retained = None

    def closure() -> Any:
        return retained

    class Callback:
        """Callable object with mutable retained state."""
        target: Any = None

        def __call__(self) -> None:
            """No invocation is needed to inspect retained state."""

    value: Any = (closure if kind == "closure" else _global if kind == "global"
                  else Callback() if kind == "callable" else callback)
    strategy = _TestStrategy(name="callable-state")
    strategy.retained = value
    strategy.require_execution_contract()
    writer = _RawWriter()
    if kind == "code":
        monkeypatch.setattr(callback, "__code__", _global.__code__)
        monkeypatch.setitem(callback.__globals__, "_GLOBAL_CAPABILITY", writer)
    elif kind == "defaults":
        callback.__defaults__ = (writer,)
    elif kind == "kwdefaults":
        callback.__kwdefaults__ = {"other": writer}
    elif kind == "closure":
        assert closure.__closure__ is not None
        closure.__closure__[0].cell_contents = writer
    elif kind == "global":
        monkeypatch.setitem(_global.__globals__, "_GLOBAL_CAPABILITY", writer)
    elif kind == "attached":
        callback.__dict__["state"] = {"writer": writer}
    else:
        value.target = writer
    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        strategy.require_execution_contract()


@pytest.mark.parametrize("shape", ["empty", "parameter", "default", "annotation", "return", "recursive"])
def test_signature_baseline_preserves_bounded_inspection_refusal(shape: str) -> None:
    """Do not invent clean Signature admission to manufacture a mutation oracle."""
    import inspect

    def callback() -> None:
        """A signature-free callback has no retained capability."""

    strategy = _TestStrategy(name="signature-baseline")
    strategy.retained = callback
    strategy.require_execution_contract()
    callback.__dict__["__signature__"] = None
    strategy.require_execution_contract()
    state: list[Any] = []
    parameters = [] if shape in {"empty", "return"} else [inspect.Parameter(
        "value", inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=state if shape in {"default", "recursive"} else None,
        annotation=state if shape == "annotation" else None,
    )]
    signature = inspect.Signature(parameters, return_annotation=state if shape == "return" else None)
    if shape == "recursive":
        state.append(signature)
    callback.__dict__["__signature__"] = signature
    for _ in range(2):
        with pytest.raises(RuntimeError, match="capability graph cannot be safely inspected"):
            strategy.require_execution_contract()


@pytest.mark.parametrize("shape", ["default", "annotation", "return", "recursive"])
def test_same_function_signature_state_retains_nested_writer(shape: str) -> None:
    """Re-read attached Signature/Parameter slots, including recursive mutable state."""
    import inspect

    def callback() -> None:
        """Never invoke the callback or its test-owned signature."""

    strategy = _TestStrategy(name="signature-writer")
    strategy.retained = callback
    callback.__dict__["__signature__"] = None
    strategy.require_execution_contract()
    state: list[Any] = []
    parameters = [] if shape == "return" else [inspect.Parameter(
        "value", inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=state if shape in {"default", "recursive"} else None,
        annotation=state if shape == "annotation" else None,
    )]
    signature = inspect.Signature(parameters, return_annotation=state if shape == "return" else None)
    callback.__dict__["__signature__"] = signature
    if shape == "recursive":
        state.append(signature)
    # Clean Signature refusal is independently tested above. This oracle must
    # reach the writer rather than pass on an earlier inspection-limit refusal.
    state.append(_RawWriter())
    assert strategy.retained is callback and callback.__dict__["__signature__"] is signature
    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        strategy.require_execution_contract()
