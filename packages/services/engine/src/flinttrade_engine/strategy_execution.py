"""Fail-closed execution contracts for scheduled strategies.

The scheduler may use an :class:`OpenAlgoClient` for market-data reads, but a
strategy instance must never retain that client for broker mutations. Live
orders are available only through :class:`GatedStrategyDispatcher`, which
mints a fresh ``SafetyContext`` and delegates to the canonical
``BrokerRouter`` for every order.
"""

from __future__ import annotations

import asyncio
import dis
import functools
import gc
import sys
import types
import weakref
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from flinttrade_core.models import Order

from .request_context import RequestContext
from .safety import SafetySystem, gate_order

if TYPE_CHECKING:
    from .strategy import BaseStrategy


class _CapabilityInspectionLimitExceeded(RuntimeError):
    """Raised when a retained object graph cannot be inspected safely."""


class StrategyExecutionMode(StrEnum):
    """Mutually exclusive scheduler execution surfaces."""

    READ_ONLY = "read_only"
    PRACTICE = "practice"
    LIVE_GATED = "live_gated"


class GatedStrategyDispatcher:
    """Canonical live strategy order dispatcher.

    The dispatcher resolves the current request identity and router generation
    for each mutation, runs the safety layers, mints a one-shot context through
    :func:`gate_order`, and hands the write to ``BrokerRouter``. It deliberately
    exposes no raw adapter or OpenAlgo client.
    """

    def __init__(
        self,
        *,
        safety: SafetySystem,
        request_context_provider: Callable[[], RequestContext],
        router_provider: Callable[[], Any],
        adapter_id: str,
        account_id: str,
        portfolio_state_provider: Callable[
            [Order, tuple[Any, ...]],
            Awaitable[Any],
        ]
        | None = None,
    ) -> None:
        self._safety = safety
        self._request_context_provider = request_context_provider
        self._router_provider = router_provider
        self._adapter_id = adapter_id.strip().lower()
        self._account_id = account_id.strip()
        self._portfolio_state_provider = portfolio_state_provider
        if not self._adapter_id or not self._account_id:
            raise ValueError("A gated strategy dispatcher requires an adapter and account")

    async def dispatch_order(self, order: Order) -> Any:
        """Dispatch one live order through a fresh gate and current router."""
        request_ctx = self._request_context_provider()
        if not isinstance(request_ctx, RequestContext) or request_ctx.mode != "live":
            raise RuntimeError("Live strategy dispatch requires a live RequestContext")
        try:
            selected_target = request_ctx.selector_parts()
        except ValueError as exc:
            raise RuntimeError("Live strategy dispatch requires a valid account selector") from exc
        if selected_target is None:
            raise RuntimeError("Live strategy dispatch requires an account selector")
        selected_adapter, selected_account = selected_target
        if (selected_adapter, selected_account) != (self._adapter_id, self._account_id):
            raise RuntimeError("Live strategy dispatch target does not match the request selector")

        if self._portfolio_state_provider is None:
            raise RuntimeError("Live strategy dispatch requires a portfolio safety-state provider")
        selector = f"{self._adapter_id}:{self._account_id}"
        async with self._safety.order_admission_async(selector) as lease:
            portfolio_state = await self._portfolio_state_provider(order, lease.reservations)
            lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
            admission = portfolio_state.admission_for(0)
            results = self._safety.check_order(
                order,
                selector=selector,
                positions=admission.positions,
                used_margin=admission.used_margin,
                total_balance=portfolio_state.total_balance,
                daily_pnl=portfolio_state.daily_pnl,
                starting_capital=portfolio_state.starting_capital,
                ltp=portfolio_state.ltp_for(order),
                net_delta=admission.net_delta,
                net_vega=admission.net_vega,
            )
            blocked = next((result for result in results if not result.passed), None)
            if blocked is not None:
                raise RuntimeError(f"Strategy order blocked by safety layer {blocked.layer}")

            router = self._router_provider()
            from flinttrade_gateway.router import BrokerRouter  # noqa: PLC0415

            if type(router) is not BrokerRouter:
                raise RuntimeError("The current canonical BrokerRouter generation is unavailable")
            safety_ctx = gate_order(
                order,
                request_ctx,
                adapter_id=self._adapter_id,
                account_id=self._account_id,
            )
            from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

            reservation = lease.reserve(order, admission.positions)
            result = await router.place_order(
                request_ctx,
                order=order,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=self._adapter_id, account_id=self._account_id),
            )
            lease.acknowledge(reservation, result)
            return result


_CANONICAL_GATED_DISPATCH_ORDER = GatedStrategyDispatcher.dispatch_order
_MANAGED_DISPATCHER_STATE_NAMES = frozenset(
    {
        "_account_id",
        "_adapter_id",
        "_portfolio_state_provider",
        "_request_context_provider",
        "_router_provider",
        "_safety",
    }
)
_TYPE_METADATA_DESCRIPTORS = types.MappingProxyType(
    {
        name: type.__dict__[name]
        for name in ("__dict__", "__module__", "__mro__", "__name__", "__qualname__")
    }
)
_MODULE_DICTIONARY_DESCRIPTOR = types.ModuleType.__dict__["__dict__"]
_WEAKREF_CALL_DESCRIPTOR = weakref.ReferenceType.__dict__["__call__"]
_WEAKREF_CALLBACK_DESCRIPTOR = weakref.ReferenceType.__dict__["__callback__"]
_PARTIAL_FUNC_DESCRIPTOR = functools.partial.__dict__["func"]
_PARTIAL_ARGS_DESCRIPTOR = functools.partial.__dict__["args"]
_PARTIAL_KEYWORDS_DESCRIPTOR = functools.partial.__dict__["keywords"]
_STATICMETHOD_FUNC_DESCRIPTOR = staticmethod.__dict__["__func__"]
_CLASSMETHOD_FUNC_DESCRIPTOR = classmethod.__dict__["__func__"]
_PROPERTY_GETTER_DESCRIPTOR = property.__dict__["fget"]
_PROPERTY_SETTER_DESCRIPTOR = property.__dict__["fset"]
_PROPERTY_DELETER_DESCRIPTOR = property.__dict__["fdel"]
_STATIC_ATTRIBUTE_MISSING = object()


@dataclass(frozen=True)
class StrategyExecutionContract:
    """Immutable declaration of one strategy runner's execution surface."""

    mode: StrategyExecutionMode
    dispatcher: GatedStrategyDispatcher | None = None

    _MUTATION_METHODS: ClassVar[frozenset[str]] = frozenset(
        {
            "cancel_all_orders",
            "cancel_conditional_trigger",
            "cancel_forever",
            "cancel_gtt",
            "cancel_order",
            "cancel_smart_order",
            "cancel_super_order",
            "close_position",
            "convert_position",
            "dispatch_order",
            "exit_all_positions",
            "modify_conditional_trigger",
            "modify_forever",
            "modify_gtt",
            "modify_order",
            "modify_super_order",
            "place_basket_order",
            "place_conditional_trigger",
            "place_gtt",
            "place_multi_order",
            "place_options_multi_order",
            "place_options_order",
            "place_order",
            "place_reducing_order",
            "place_smart_order",
            "place_split_order",
            "route_order",
        }
    )
    _MAX_CAPABILITY_GRAPH_DEPTH: ClassVar[int] = 12
    _MAX_CAPABILITY_GRAPH_NODES: ClassVar[int] = 2048
    _CAPABILITY_LEAF_TYPES: ClassVar[frozenset[type[Any]]] = frozenset(
        {
            type(None),
            bool,
            int,
            float,
            complex,
            str,
            bytes,
            bytearray,
            memoryview,
            StrategyExecutionMode,
        }
    )

    def __post_init__(self) -> None:
        if self.mode == StrategyExecutionMode.LIVE_GATED:
            if type(self.dispatcher) is not GatedStrategyDispatcher:
                raise ValueError("Live strategy execution requires the canonical gated dispatcher")
            if not self._dispatcher_uses_canonical_dispatch(self.dispatcher):
                raise ValueError("Live strategy execution requires the canonical dispatch_order implementation")
        elif self.dispatcher is not None:
            raise ValueError("Only live-gated strategy execution may hold a live dispatcher")

    @classmethod
    def read_only(cls) -> StrategyExecutionContract:
        """Create a contract that permits market-data callbacks but no orders."""
        return cls(mode=StrategyExecutionMode.READ_ONLY)

    @classmethod
    def practice(cls) -> StrategyExecutionContract:
        """Create an explicitly non-live practice contract.

        Practice order simulation remains owned by the sandbox subsystem. The
        scheduled strategy runtime may generate intents, but this contract does
        not expose a broker mutation capability.
        """
        return cls(mode=StrategyExecutionMode.PRACTICE)

    @classmethod
    def live(cls, dispatcher: GatedStrategyDispatcher) -> StrategyExecutionContract:
        """Create a live contract bound to the canonical gated dispatcher."""
        return cls(mode=StrategyExecutionMode.LIVE_GATED, dispatcher=dispatcher)

    def validate_strategy(self, strategy: BaseStrategy) -> None:
        """Revalidate one strategy at registration and immediately before start."""
        supported = strategy.supported_execution_modes
        if self.mode not in supported:
            raise RuntimeError(f"Strategy {strategy.name!r} does not support execution mode {self.mode.value!r}")
        if self.mode == StrategyExecutionMode.LIVE_GATED and not strategy.uses_managed_order_dispatch:
            raise RuntimeError(f"Strategy {strategy.name!r} is not implemented against the managed gated dispatcher")

        try:
            retained_path = self._find_retained_mutation_capability(strategy)
        except _CapabilityInspectionLimitExceeded as exc:
            raise RuntimeError(
                f"Strategy {strategy.name!r} retained capability graph cannot be safely inspected: {exc}"
            ) from exc
        if retained_path is not None:
            raise RuntimeError(f"Strategy {strategy.name!r} retains raw broker mutation handle {retained_path!r}")

    async def dispatch_order(self, order: Order) -> Any:
        """Dispatch only when this is a canonical live-gated contract."""
        if self.mode != StrategyExecutionMode.LIVE_GATED or self.dispatcher is None:
            raise RuntimeError(f"Strategy execution mode {self.mode.value!r} cannot mutate a broker")
        return await self.dispatcher.dispatch_order(order)

    @staticmethod
    def _builtin_descriptor_value(descriptor: Any, value: Any, label: str) -> Any:
        """Read one trusted C descriptor without dynamic attribute dispatch."""
        try:
            return descriptor.__get__(value, type(value))
        except Exception as exc:  # noqa: BLE001 - unreadable backing state fails closed
            raise _CapabilityInspectionLimitExceeded(f"{label} could not be inspected statically") from exc

    @classmethod
    def _type_metadata(cls, owner: type[Any], name: str) -> Any:
        """Read intrinsic class metadata while bypassing custom metaclasses."""
        if name not in _TYPE_METADATA_DESCRIPTORS:
            raise _CapabilityInspectionLimitExceeded("class metadata request was invalid")
        return cls._builtin_descriptor_value(
            _TYPE_METADATA_DESCRIPTORS[name],
            owner,
            f"class {name}",
        )

    @classmethod
    def _static_mro(cls, owner: type[Any]) -> tuple[type[Any], ...]:
        """Return the type-owned MRO tuple without invoking metaclass hooks."""
        mro = cls._type_metadata(owner, "__mro__")
        if type(mro) is not tuple:
            raise _CapabilityInspectionLimitExceeded("class MRO is not a concrete type tuple")
        return mro

    @classmethod
    def _type_inherits(cls, value_type: type[Any], base_type: type[Any]) -> bool:
        """Test an actual type against a base using identity-only MRO checks."""
        return any(owner is base_type for owner in cls._static_mro(value_type))

    @classmethod
    def _is_class_object(cls, value: Any) -> bool:
        """Return whether ``value`` is intrinsically a class object."""
        return cls._type_inherits(type(value), type)

    @classmethod
    def _is_module_object(cls, value: Any) -> bool:
        """Return whether ``value`` is intrinsically a module object."""
        return cls._type_inherits(type(value), types.ModuleType)

    @classmethod
    def _mapping_proxy_backing_dict(cls, value: types.MappingProxyType) -> dict[Any, Any]:
        """Return a proxy's concrete dict backing without using mapping methods."""
        try:
            referents = gc.get_referents(value)
        except Exception as exc:  # noqa: BLE001 - opaque proxy backing fails closed
            raise _CapabilityInspectionLimitExceeded("mapping proxy backing could not be inspected") from exc
        if len(referents) != 1 or not cls._type_inherits(type(referents[0]), dict):
            raise _CapabilityInspectionLimitExceeded("mapping proxy backing is not a concrete dictionary")
        return referents[0]

    @classmethod
    def _class_namespace(cls, owner: type[Any]) -> dict[str, Any]:
        """Return the actual class dictionary without metaclass dispatch."""
        namespace = cls._type_metadata(owner, "__dict__")
        if type(namespace) is not types.MappingProxyType:
            raise _CapabilityInspectionLimitExceeded("class dictionary is not a mapping proxy")
        backing = cls._mapping_proxy_backing_dict(namespace)
        if type(backing) is not dict:
            raise _CapabilityInspectionLimitExceeded("class dictionary backing is not a concrete dictionary")
        if any(type(name) is not str for name in dict.keys(backing)):
            raise _CapabilityInspectionLimitExceeded("class dictionary key is not concrete text")
        return backing

    @classmethod
    def _module_namespace(cls, module: types.ModuleType) -> dict[str, Any]:
        """Return a module's actual dictionary without module subclass hooks."""
        namespace = cls._builtin_descriptor_value(
            _MODULE_DICTIONARY_DESCRIPTOR,
            module,
            "module dictionary",
        )
        if type(namespace) is not dict:
            raise _CapabilityInspectionLimitExceeded("module dictionary is not a concrete mapping")
        if any(type(name) is not str for name in dict.keys(namespace)):
            raise _CapabilityInspectionLimitExceeded("module dictionary key is not concrete text")
        return namespace

    @classmethod
    def _static_type_name(cls, value_type: type[Any]) -> str:
        """Return a type's intrinsic display name without metaclass access."""
        module = cls._type_metadata(value_type, "__module__")
        qualname = cls._type_metadata(value_type, "__qualname__")
        if type(module) is not str or type(qualname) is not str:
            raise _CapabilityInspectionLimitExceeded("class name metadata is not concrete text")
        return f"{module}.{qualname}"

    @classmethod
    def _static_class_member(cls, owner: type[Any], name: str) -> Any:
        """Find one class-table member without metaclass or descriptor dispatch."""
        for base in cls._static_mro(owner):
            namespace = cls._class_namespace(base)
            if name in namespace:
                return dict.__getitem__(namespace, name)
        return _STATIC_ATTRIBUTE_MISSING

    @classmethod
    def _is_data_descriptor(cls, value: Any) -> bool:
        """Classify descriptor precedence from static type dictionaries only."""
        descriptor_type = type(value)
        return any(
            cls._static_class_member(descriptor_type, method_name) is not _STATIC_ATTRIBUTE_MISSING
            for method_name in ("__set__", "__delete__")
        )

    @classmethod
    def _getattr_static(cls, value: Any, name: str, default: Any = _STATIC_ATTRIBUTE_MISSING) -> Any:
        """Resolve an attribute without invoking user lookup or descriptor hooks."""
        if type(name) is not str:
            raise _CapabilityInspectionLimitExceeded("static attribute name is not concrete text")

        if cls._is_class_object(value):
            metaclass_member = cls._static_class_member(type(value), name)
            if metaclass_member is not _STATIC_ATTRIBUTE_MISSING and cls._is_data_descriptor(metaclass_member):
                return metaclass_member
            class_member = cls._static_class_member(value, name)
            if class_member is not _STATIC_ATTRIBUTE_MISSING:
                return class_member
            if metaclass_member is not _STATIC_ATTRIBUTE_MISSING:
                return metaclass_member
        else:
            class_member = cls._static_class_member(type(value), name)
            if class_member is not _STATIC_ATTRIBUTE_MISSING and cls._is_data_descriptor(class_member):
                return class_member
            state = cls._static_instance_state(value)
            if name in state:
                return dict.__getitem__(state, name)
            if class_member is not _STATIC_ATTRIBUTE_MISSING:
                return class_member

        if default is not _STATIC_ATTRIBUTE_MISSING:
            return default
        raise AttributeError(name)

    @classmethod
    def _has_callable(cls, value: Any, method_name: str) -> bool:
        try:
            member = cls._getattr_static(value, method_name)
        except AttributeError:
            return False
        except Exception as exc:  # noqa: BLE001 - ambiguous static lookup cannot authorise a live graph
            raise _CapabilityInspectionLimitExceeded("mutation surface could not be inspected") from exc
        if cls._type_inherits(type(member), staticmethod):
            member = cls._builtin_descriptor_value(
                _STATICMETHOD_FUNC_DESCRIPTOR,
                member,
                "staticmethod function",
            )
        elif cls._type_inherits(type(member), classmethod):
            member = cls._builtin_descriptor_value(
                _CLASSMETHOD_FUNC_DESCRIPTOR,
                member,
                "classmethod function",
            )
        return callable(member)

    @classmethod
    def _is_direct_mutation_capability(cls, value: Any) -> bool:
        """Detect a writer object or a directly retained broker-bound routine."""
        if value is StrategyExecutionContract or value is GatedStrategyDispatcher:
            return False
        if type(value) is StrategyExecutionContract and value.dispatcher is None:
            return False
        value_type = type(value)
        value_module = cls._type_metadata(value_type, "__module__")
        if type(value_module) is not str:
            raise _CapabilityInspectionLimitExceeded("class module metadata is not concrete text")
        if value_module == "unittest.mock":
            mock_state = cls._static_instance_state(value)
            configured_names: set[str] = set()
            mock_methods = mock_state.get("_mock_methods")
            if mock_methods is not None:
                if cls._type_inherits(type(mock_methods), list):
                    method_names = tuple(list.__iter__(mock_methods))
                elif cls._type_inherits(type(mock_methods), tuple):
                    method_names = tuple(tuple.__iter__(mock_methods))
                else:
                    raise _CapabilityInspectionLimitExceeded("mock method declarations are not concrete")
                if any(type(name) is not str for name in method_names):
                    raise _CapabilityInspectionLimitExceeded("mock method declaration is not concrete text")
                configured_names.update(method_names)
            mock_children = mock_state.get("_mock_children")
            if mock_children is not None:
                if not cls._type_inherits(type(mock_children), dict):
                    raise _CapabilityInspectionLimitExceeded("mock child table is not concrete")
                child_names = tuple(dict.keys(mock_children))
                if any(type(name) is not str for name in child_names):
                    raise _CapabilityInspectionLimitExceeded("mock child name is not concrete text")
                configured_names.update(child_names)
            if configured_names & cls._MUTATION_METHODS:
                return True
        if cls._is_class_object(value):
            return any(cls._has_callable(value, method_name) for method_name in cls._MUTATION_METHODS)
        mutation_methods = cls._MUTATION_METHODS
        if cls._uses_canonical_strategy_dispatch(value):
            mutation_methods = mutation_methods - {"dispatch_order"}
        if any(cls._has_callable(value, method) for method in mutation_methods):
            return True
        if not any(
            type(value) is routine_type
            for routine_type in (
                types.FunctionType,
                types.MethodType,
                types.BuiltinFunctionType,
                types.MethodDescriptorType,
                types.WrapperDescriptorType,
            )
        ):
            return False
        callable_name = getattr(value, "__name__", "")
        if callable_name in cls._MUTATION_METHODS:
            return True
        owner = getattr(value, "__self__", None)
        return owner is not None and any(cls._has_callable(owner, method) for method in cls._MUTATION_METHODS)

    @staticmethod
    def _uses_canonical_strategy_dispatch(value: Any) -> bool:
        """Return whether an object inherits the exact managed strategy dispatcher wrapper."""
        from .strategy import BaseStrategy  # noqa: PLC0415

        if not any(owner is BaseStrategy for owner in StrategyExecutionContract._static_mro(type(value))):
            return False
        try:
            canonical_dispatch = StrategyExecutionContract._static_class_member(BaseStrategy, "dispatch_order")
            return StrategyExecutionContract._getattr_static(value, "dispatch_order") is canonical_dispatch
        except Exception as exc:  # noqa: BLE001 - ambiguous dispatch identity must fail closed
            raise _CapabilityInspectionLimitExceeded("strategy dispatch identity could not be inspected") from exc

    def _find_retained_mutation_capability(
        self,
        strategy: BaseStrategy,
    ) -> str | None:
        """Walk a bounded retained graph and return the first unsafe root path."""
        seen: set[int] = set()
        inspected_nodes = 0
        strategy_mro = self._static_mro(type(strategy))
        strategy_methods: set[Any] = set()
        for owner in strategy_mro:
            for name, member in dict.items(self._class_namespace(owner)):
                if name in self._MUTATION_METHODS:
                    continue
                candidate = member
                if self._type_inherits(type(member), staticmethod):
                    candidate = self._builtin_descriptor_value(
                        _STATICMETHOD_FUNC_DESCRIPTOR,
                        member,
                        "staticmethod function",
                    )
                elif self._type_inherits(type(member), classmethod):
                    candidate = self._builtin_descriptor_value(
                        _CLASSMETHOD_FUNC_DESCRIPTOR,
                        member,
                        "classmethod function",
                    )
                if type(candidate) is types.FunctionType:
                    strategy_methods.add(candidate)
        approved_strategy_methods = frozenset(strategy_methods)

        def describe(value: Any) -> str:
            if type(value) is types.FunctionType:
                return value.__qualname__
            if type(value) is types.CodeType:
                return value.co_qualname
            return self._static_type_name(type(value))

        def walk(value: Any, depth: int, path: tuple[str, ...]) -> bool:
            nonlocal inspected_nodes
            if any(type(value) is leaf_type for leaf_type in self._CAPABILITY_LEAF_TYPES):
                return False
            identity = id(value)
            if identity in seen:
                return False
            current_path = (*path, describe(value))
            if depth > self._MAX_CAPABILITY_GRAPH_DEPTH:
                raise _CapabilityInspectionLimitExceeded(
                    f"capability graph depth exceeded at {' -> '.join(current_path)}"
                )
            seen.add(identity)
            inspected_nodes += 1
            if inspected_nodes > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            if value is strategy:
                # The strategy's state and complete MRO are already named roots.
                return False
            if self._is_class_object(value) and any(value is owner for owner in strategy_mro):
                # Every retained member of these classes is already a named root
                # below. Avoid re-entering the same MRO through ``__class__``
                # closure cells such as the one created by ``super()``.
                return False
            approved_strategy_method = bool(
                type(value) is types.MethodType
                and value.__self__ is strategy
                and value.__func__ in approved_strategy_methods
            )
            if approved_strategy_method:
                # Its exact implementation is already either an inspected MRO
                # root or a trusted member of the canonical BaseStrategy.
                return False
            if self._is_direct_mutation_capability(value) and not self._is_approved_capability(value):
                return True
            try:
                children = self._retained_children(value)
            except _CapabilityInspectionLimitExceeded as exc:
                raise _CapabilityInspectionLimitExceeded(f"{exc} at {' -> '.join(current_path)}") from exc
            return any(walk(child, depth + 1, current_path) for child in children)

        for attribute_name, value in self._strategy_roots(strategy):
            if walk(value, 0, (attribute_name,)):
                return attribute_name
        return None

    def _is_approved_capability(self, value: Any) -> bool:
        """Approve only this contract, its dispatcher, and that dispatcher's exact method."""
        if value is self:
            return True
        dispatcher = self.dispatcher
        if value is dispatcher:
            return dispatcher is not None and self._dispatcher_uses_canonical_dispatch(dispatcher)
        return bool(
            dispatcher is not None
            and type(value) is types.MethodType
            and value.__self__ is dispatcher
            and value.__func__ is _CANONICAL_GATED_DISPATCH_ORDER
        )

    @staticmethod
    def _dispatcher_uses_canonical_dispatch(dispatcher: GatedStrategyDispatcher) -> bool:
        try:
            return (
                StrategyExecutionContract._getattr_static(dispatcher, "dispatch_order")
                is _CANONICAL_GATED_DISPATCH_ORDER
            )
        except Exception:  # noqa: BLE001 - ambiguous dispatch identity must fail closed
            return False

    @classmethod
    def _strategy_roots(cls, strategy: BaseStrategy) -> tuple[tuple[str, Any], ...]:
        """Return instance, slot, and complete user-MRO roots without invoking properties."""
        from .strategy import BaseStrategy as CanonicalBaseStrategy  # noqa: PLC0415

        roots: list[tuple[str, Any]] = list(cls._static_instance_state(strategy).items())
        state_names = {name for name, _value in roots}
        for slot_name, slot_value in cls._slot_state(strategy).items():
            if slot_name not in state_names:
                roots.append((slot_name, slot_value))

        for owner in cls._static_mro(type(strategy)):
            # The exact framework base is trusted, but the scan must continue:
            # legal C3 MROs can place capability-bearing mixins after it.
            owner_module = cls._type_metadata(owner, "__module__")
            if type(owner_module) is not str:
                raise _CapabilityInspectionLimitExceeded("class module metadata is not concrete text")
            if owner is CanonicalBaseStrategy or owner_module in {"abc", "builtins"}:
                continue
            class_state = cls._class_namespace(owner)
            owner_name = cls._type_metadata(owner, "__name__")
            if type(owner_name) is not str:
                raise _CapabilityInspectionLimitExceeded("class name metadata is not concrete text")
            for attribute_name, value in dict.items(class_state):
                if attribute_name in {"__classcell__", "__dict__", "__weakref__"}:
                    continue
                if any(
                    type(value) is descriptor_type
                    for descriptor_type in (types.GetSetDescriptorType, types.MemberDescriptorType)
                ):
                    continue
                roots.append((f"{owner_name}.{attribute_name}", value))
        return tuple(roots)

    def _retained_children(self, value: Any) -> tuple[Any, ...]:
        """Return statically retained children without invoking user properties."""
        if type(value) is StrategyExecutionContract:
            return (value.mode, value.dispatcher)
        if value is self.dispatcher:
            return tuple(
                retained
                for name, retained in dict.items(self._static_instance_state(value))
                if name not in _MANAGED_DISPATCHER_STATE_NAMES
            )
        value_type = type(value)
        value_module = self._type_metadata(value_type, "__module__")
        if type(value_module) is not str:
            raise _CapabilityInspectionLimitExceeded("class module metadata is not concrete text")
        if value_module == "unittest.mock":
            state = self._static_instance_state(value)
            mock_children = state.get("_mock_children")
            if mock_children is None:
                children: list[Any] = []
            elif self._type_inherits(type(mock_children), dict):
                children = list(dict.values(mock_children))
            else:
                raise _CapabilityInspectionLimitExceeded("mock child table is not concrete")
            children.extend(
                retained
                for name in ("_mock_return_value", "_mock_side_effect", "_mock_wraps")
                if (retained := state.get(name)) is not None
            )
            return tuple(children)
        if any(
            value_type is asyncio_type
            for asyncio_type in (
                asyncio.Event,
                asyncio.Lock,
                asyncio.Condition,
                asyncio.Semaphore,
                asyncio.BoundedSemaphore,
                asyncio.Queue,
                asyncio.PriorityQueue,
                asyncio.LifoQueue,
            )
        ):
            return tuple(retained for name, retained in self._static_instance_state(value).items() if name != "_loop")
        if self._type_inherits(value_type, dict):
            if dict.__len__(value) * 2 > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            children = [item for pair in dict.items(value) for item in pair]
            children.extend(self._container_subclass_children(value, dict))
            return tuple(children)
        if value_type is types.MappingProxyType:
            backing = self._mapping_proxy_backing_dict(value)
            if dict.__len__(backing) * 2 > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (backing,)
        if self._type_inherits(value_type, list):
            if list.__len__(value) > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (*tuple(list.__iter__(value)), *self._container_subclass_children(value, list))
        if self._type_inherits(value_type, tuple):
            if tuple.__len__(value) > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (*tuple(tuple.__iter__(value)), *self._container_subclass_children(value, tuple))
        if self._type_inherits(value_type, set):
            if set.__len__(value) > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (*tuple(set.__iter__(value)), *self._container_subclass_children(value, set))
        if self._type_inherits(value_type, frozenset):
            if frozenset.__len__(value) > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (*tuple(frozenset.__iter__(value)), *self._container_subclass_children(value, frozenset))
        if self._type_inherits(value_type, deque):
            if deque.__len__(value) > self._MAX_CAPABILITY_GRAPH_NODES:
                raise _CapabilityInspectionLimitExceeded("capability graph node limit exceeded")
            return (*tuple(deque.__iter__(value)), *self._container_subclass_children(value, deque))
        if self._type_inherits(value_type, functools.partial):
            function = self._builtin_descriptor_value(_PARTIAL_FUNC_DESCRIPTOR, value, "partial function")
            args = self._builtin_descriptor_value(_PARTIAL_ARGS_DESCRIPTOR, value, "partial arguments")
            keywords = self._builtin_descriptor_value(_PARTIAL_KEYWORDS_DESCRIPTOR, value, "partial keywords")
            if type(args) is not tuple or (keywords is not None and type(keywords) is not dict):
                raise _CapabilityInspectionLimitExceeded("partial state is not concrete")
            children = [function, *tuple.__iter__(args), *(() if keywords is None else dict.values(keywords))]
            children.extend(self._container_subclass_children(value, functools.partial))
            return tuple(children)
        if self._type_inherits(value_type, functools.partialmethod):
            return (
                *tuple(dict.values(self._static_instance_state(value))),
                *tuple(dict.values(self._slot_state(value))),
                *self._class_children(value_type, skip_standard_library=True),
            )
        if self._type_inherits(value_type, weakref.ReferenceType):
            try:
                referent = _WEAKREF_CALL_DESCRIPTOR(value)
            except Exception as exc:  # noqa: BLE001 - opaque references fail closed
                raise _CapabilityInspectionLimitExceeded("weak reference target could not be inspected") from exc
            callback = self._builtin_descriptor_value(
                _WEAKREF_CALLBACK_DESCRIPTOR,
                value,
                "weak reference callback",
            )
            children = [child for child in (referent, callback) if child is not None]
            children.extend(self._container_subclass_children(value, weakref.ReferenceType))
            return tuple(children)
        if any(value_type is proxy_type for proxy_type in weakref.ProxyTypes):
            raise _CapabilityInspectionLimitExceeded("weak proxy referent cannot be inspected statically")
        if type(value) is asyncio.Task:
            try:
                coroutine = asyncio.Task.get_coro(value)
                children: list[Any]
                from .scheduler import StrategyRunner  # noqa: PLC0415

                frame = coroutine.cr_frame
                retained_runner = frame.f_locals.get("self") if frame is not None else None
                if (
                    coroutine.cr_code is StrategyRunner._run_loop.__code__
                    and type(retained_runner) is StrategyRunner
                    and object.__getattribute__(retained_runner, "_task") is value
                ):
                    children = list(frame.f_locals.values())
                    if coroutine.cr_await is not None:
                        children.append(coroutine.cr_await)
                else:
                    children = [coroutine]
                if value.done() and not value.cancelled():
                    error = asyncio.Future.exception(value)
                    children.append(error if error is not None else asyncio.Future.result(value))
            except Exception as exc:  # noqa: BLE001 - task state can retain capability-bearing values
                raise _CapabilityInspectionLimitExceeded("async task could not be inspected") from exc
            return tuple(child for child in children if child is not None)
        if type(value) is asyncio.Future:
            try:
                callbacks = asyncio.Future._callbacks.__get__(value, type(value))  # noqa: SLF001
                children = [
                    item
                    for callback, context in callbacks or ()
                    if not self._is_asyncio_task_wakeup(callback)
                    for item in (callback, context)
                ]
                if value.done() and not value.cancelled():
                    error = asyncio.Future.exception(value)
                    children.append(error if error is not None else asyncio.Future.result(value))
            except Exception as exc:  # noqa: BLE001 - future callbacks can retain mutation handles
                raise _CapabilityInspectionLimitExceeded("async future could not be inspected") from exc
            return tuple(child for child in children if child is not None)
        if self._type_inherits(value_type, staticmethod):
            function = self._builtin_descriptor_value(_STATICMETHOD_FUNC_DESCRIPTOR, value, "staticmethod function")
            return (function, *self._container_subclass_children(value, staticmethod))
        if self._type_inherits(value_type, classmethod):
            function = self._builtin_descriptor_value(_CLASSMETHOD_FUNC_DESCRIPTOR, value, "classmethod function")
            return (function, *self._container_subclass_children(value, classmethod))
        if self._type_inherits(value_type, property):
            accessors = (
                self._builtin_descriptor_value(_PROPERTY_GETTER_DESCRIPTOR, value, "property getter"),
                self._builtin_descriptor_value(_PROPERTY_SETTER_DESCRIPTOR, value, "property setter"),
                self._builtin_descriptor_value(_PROPERTY_DELETER_DESCRIPTOR, value, "property deleter"),
            )
            return (
                *(member for member in accessors if member is not None),
                *self._container_subclass_children(value, property),
            )
        if value_type is types.MethodType:
            if self._is_approved_capability(value):
                return (value.__self__,)
            return (value.__self__, value.__func__)
        if value_type is types.BuiltinFunctionType:
            owner = getattr(value, "__self__", None)
            return () if owner is None or self._is_module_object(owner) else (owner,)
        if value_type is types.MethodWrapperType:
            owner = getattr(value, "__self__", None)
            return () if owner is None else (owner,)
        if value_type is types.FunctionType:
            children: list[Any] = []
            children.extend(value.__defaults__ or ())
            children.extend(dict.values(value.__kwdefaults__ or {}))
            children.extend(self._referenced_global_values(value))
            for cell in value.__closure__ or ():
                try:
                    children.append(cell.cell_contents)
                except ValueError:
                    continue
            children.extend(dict.values(self._static_instance_state(value)))
            return tuple(children)
        if type(value) is types.CellType:
            try:
                return (value.cell_contents,)
            except ValueError:
                return ()
        if type(value) is types.GeneratorType:
            return self._execution_frame_children(value.gi_frame, value.gi_yieldfrom)
        if type(value) is types.CoroutineType:
            return self._execution_frame_children(value.cr_frame, value.cr_await)
        if type(value) is types.AsyncGeneratorType:
            return self._execution_frame_children(value.ag_frame, value.ag_await)
        if type(value) is types.FrameType:
            return self._frame_children(value)
        if any(
            value_type is descriptor_type
            for descriptor_type in (
                types.MethodDescriptorType,
                types.WrapperDescriptorType,
                types.ClassMethodDescriptorType,
                types.GetSetDescriptorType,
                types.MemberDescriptorType,
            )
        ):
            return ()
        if self._is_module_object(value):
            raise _CapabilityInspectionLimitExceeded("module retained without a static attribute reference")
        if type(value) is types.CodeType:
            raise _CapabilityInspectionLimitExceeded("standalone code object has no inspectable globals")
        if value is StrategyExecutionContract or value is GatedStrategyDispatcher:
            # Strategy constructors may reference contract types as globals;
            # types are not retained dispatcher instances.
            return ()
        if self._is_class_object(value):
            return self._class_children(value, skip_standard_library=True)

        children = list(dict.values(self._static_instance_state(value)))
        children.extend(dict.values(self._slot_state(value)))
        children.extend(self._class_children(type(value), skip_standard_library=True))
        wrapped = self._getattr_static(value, "__wrapped__", None)
        if wrapped is not None:
            children.append(wrapped)
        return tuple(children)

    def _container_subclass_children(self, value: Any, base_type: type[Any]) -> tuple[Any, ...]:
        """Inspect state attached to a builtin container or wrapper subclass."""
        if type(value) is base_type:
            return ()
        return (
            *tuple(dict.values(self._static_instance_state(value))),
            *tuple(dict.values(self._slot_state(value))),
            *self._class_children(type(value), skip_standard_library=True),
        )

    @staticmethod
    def _is_asyncio_task_wakeup(callback: Any) -> bool:
        """Identify asyncio's internal future-to-task scheduling callback."""
        return bool(
            type(callback) is types.BuiltinMethodType
            and type(getattr(callback, "__self__", None)) is asyncio.Task
            and getattr(callback, "__name__", None) == "task_wakeup"
        )

    @classmethod
    def _class_children(
        cls,
        value: type[Any],
        *,
        skip_standard_library: bool = False,
    ) -> tuple[Any, ...]:
        """Return retained class members across the full MRO."""
        children: list[Any] = []
        for owner in cls._static_mro(value):
            if skip_standard_library and cls._is_standard_library_owner(owner):
                continue
            class_state = cls._class_namespace(owner)
            children.extend(
                member
                for name, member in dict.items(class_state)
                if name not in {"__classcell__", "__dict__", "__weakref__"}
                and not any(
                    type(member) is descriptor_type
                    for descriptor_type in (types.GetSetDescriptorType, types.MemberDescriptorType)
                )
            )
        return tuple(children)

    @classmethod
    def _is_standard_library_owner(cls, owner: type[Any]) -> bool:
        if not cls._is_declared_module_class(owner):
            return False
        module = cls._type_metadata(owner, "__module__")
        if type(module) is not str:
            raise _CapabilityInspectionLimitExceeded("class module metadata is not concrete text")
        return module in {
            "abc",
            "builtins",
            "flinttrade_core.models",
            "flinttrade_engine.safety",
            "flinttrade_engine.scheduler",
            "flinttrade_engine.strategy",
        } or module.startswith(
            (
                "_thread",
                "asyncio.",
                "collections",
                "concurrent.",
                "contextvars",
                "dataclasses",
                "enum",
                "functools",
                "pathlib",
                "pydantic.",
                "threading",
                "types",
                "typing",
                "unittest.mock",
                "weakref",
            )
        )

    @classmethod
    def _is_declared_module_class(cls, owner: type[Any]) -> bool:
        """Reject spoofed ``__module__`` values before trusting a class table."""
        owner_module = cls._type_metadata(owner, "__module__")
        owner_qualname = cls._type_metadata(owner, "__qualname__")
        if type(owner_module) is not str or type(owner_qualname) is not str:
            return False
        module = dict.get(sys.modules, owner_module)
        if module is None:
            return False
        current: Any = module
        for component in str.split(owner_qualname, "."):
            if component == "<locals>":
                return False
            if cls._is_module_object(current):
                namespace = cls._module_namespace(current)
            elif cls._is_class_object(current):
                namespace = cls._class_namespace(current)
            else:
                return False
            if component not in namespace:
                return False
            current = namespace[component]
        return current is owner

    @classmethod
    def _slot_state(cls, value: Any) -> dict[str, Any]:
        """Read concrete slot descriptors throughout an instance's MRO."""
        state: dict[str, Any] = {}
        for owner in cls._static_mro(type(value)):
            class_state = cls._class_namespace(owner)
            for name, descriptor in dict.items(class_state):
                if name in {"__dict__", "__weakref__"} or type(descriptor) is not types.MemberDescriptorType:
                    continue
                try:
                    state[name] = descriptor.__get__(value, type(value))
                except AttributeError:
                    continue
                except Exception as exc:  # noqa: BLE001 - unreadable slots fail closed
                    raise _CapabilityInspectionLimitExceeded("instance slot could not be inspected") from exc
        return state

    def _execution_frame_children(self, frame: types.FrameType | None, delegated: Any) -> tuple[Any, ...]:
        children = list(self._frame_children(frame)) if frame is not None else []
        if delegated is not None:
            children.append(delegated)
        return tuple(children)

    def _frame_children(self, frame: types.FrameType) -> tuple[Any, ...]:
        try:
            local_values = tuple(frame.f_locals.values())
            global_values = (
                ()
                if frame.f_code in self._canonical_runtime_codes()
                else self._referenced_code_values(frame.f_code, frame.f_globals)
            )
        except Exception as exc:  # noqa: BLE001 - execution frames are capability-bearing state
            if self._type_inherits(type(exc), _CapabilityInspectionLimitExceeded):
                raise
            raise _CapabilityInspectionLimitExceeded("execution frame could not be inspected") from exc
        return (*local_values, *global_values)

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _canonical_runtime_codes() -> frozenset[types.CodeType]:
        """Return exact framework code objects whose globals are not strategy-retained state."""
        from . import scheduler as scheduler_module  # noqa: PLC0415
        from .scheduler import StrategyRunner, StrategyScheduler, TimeScheduler  # noqa: PLC0415

        codes: set[types.CodeType] = set()

        def add_code(code: types.CodeType) -> None:
            if code in codes:
                return
            codes.add(code)
            for constant in code.co_consts:
                if type(constant) is types.CodeType:
                    add_code(constant)

        for owner in (StrategyRunner, StrategyScheduler, TimeScheduler):
            for member in dict.values(StrategyExecutionContract._class_namespace(owner)):
                if StrategyExecutionContract._type_inherits(type(member), staticmethod):
                    member = StrategyExecutionContract._builtin_descriptor_value(
                        _STATICMETHOD_FUNC_DESCRIPTOR,
                        member,
                        "staticmethod function",
                    )
                elif StrategyExecutionContract._type_inherits(type(member), classmethod):
                    member = StrategyExecutionContract._builtin_descriptor_value(
                        _CLASSMETHOD_FUNC_DESCRIPTOR,
                        member,
                        "classmethod function",
                    )
                if type(member) is types.FunctionType:
                    add_code(member.__code__)
                elif StrategyExecutionContract._type_inherits(type(member), property):
                    accessors = (
                        StrategyExecutionContract._builtin_descriptor_value(
                            _PROPERTY_GETTER_DESCRIPTOR,
                            member,
                            "property getter",
                        ),
                        StrategyExecutionContract._builtin_descriptor_value(
                            _PROPERTY_SETTER_DESCRIPTOR,
                            member,
                            "property setter",
                        ),
                        StrategyExecutionContract._builtin_descriptor_value(
                            _PROPERTY_DELETER_DESCRIPTOR,
                            member,
                            "property deleter",
                        ),
                    )
                    for accessor in accessors:
                        if accessor is not None:
                            add_code(accessor.__code__)
        scheduler_namespace = StrategyExecutionContract._module_namespace(scheduler_module)
        scheduler_name = scheduler_namespace.get("__name__")
        if type(scheduler_name) is not str:
            raise _CapabilityInspectionLimitExceeded("scheduler module name is not concrete text")
        for member in dict.values(scheduler_namespace):
            if type(member) is types.FunctionType and member.__module__ == scheduler_name:
                add_code(member.__code__)
        return frozenset(codes)

    @staticmethod
    def _referenced_global_values(function: Callable[..., Any]) -> tuple[Any, ...]:
        """Return only globals named by function bytecode, rejecting dynamic access."""
        try:
            function_globals = object.__getattribute__(function, "__globals__")
            code = object.__getattribute__(function, "__code__")
        except (AttributeError, TypeError) as exc:
            raise _CapabilityInspectionLimitExceeded("function internals could not be inspected") from exc
        if type(function_globals) is not dict or type(code) is not types.CodeType:
            raise _CapabilityInspectionLimitExceeded("function globals are not a concrete mapping")

        return StrategyExecutionContract._referenced_code_values(code, function_globals)

    @staticmethod
    def _referenced_code_values(
        code: types.CodeType,
        function_globals: dict[str, Any],
    ) -> tuple[Any, ...]:
        """Resolve bytecode-referenced globals and concrete module attribute chains."""

        referenced: list[Any] = []
        visited_codes: set[int] = set()
        if any(type(name) is not str for name in dict.keys(function_globals)):
            raise _CapabilityInspectionLimitExceeded("function global name is not concrete text")

        def inspect_code(current: types.CodeType) -> None:
            code_id = id(current)
            if code_id in visited_codes:
                return
            visited_codes.add(code_id)
            try:
                instructions = tuple(dis.get_instructions(current))
            except Exception as exc:  # noqa: BLE001 - non-standard code must not gain live access
                raise _CapabilityInspectionLimitExceeded("function bytecode could not be inspected") from exc
            for index, instruction in enumerate(instructions):
                if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                    continue
                global_name = instruction.argval
                if type(global_name) is not str:
                    raise _CapabilityInspectionLimitExceeded("function global name could not be resolved")
                if global_name in {"globals", "vars"}:
                    raise _CapabilityInspectionLimitExceeded("function uses dynamic global lookup")
                if global_name in function_globals:
                    global_value = function_globals[global_name]
                    if StrategyExecutionContract._is_module_object(global_value):
                        referenced.extend(
                            StrategyExecutionContract._referenced_module_values(
                                global_value,
                                instructions[index + 1 :],
                            )
                        )
                    else:
                        referenced.append(global_value)
            for constant in current.co_consts:
                if type(constant) is types.CodeType:
                    inspect_code(constant)

        inspect_code(code)
        return tuple(referenced)

    @classmethod
    def _referenced_module_values(
        cls,
        module: types.ModuleType,
        following: tuple[dis.Instruction, ...],
    ) -> tuple[Any, ...]:
        """Resolve the concrete attributes loaded immediately from one global module."""
        current: Any = module
        resolved: list[Any] = []
        for instruction in following:
            if instruction.opname in {"CACHE", "EXTENDED_ARG", "NOP"}:
                continue
            if instruction.opname not in {"LOAD_ATTR", "LOAD_METHOD"} or not cls._is_module_object(current):
                break
            attribute_name = instruction.argval
            if type(attribute_name) is not str:
                raise _CapabilityInspectionLimitExceeded("module attribute name could not be resolved")
            module_state = cls._module_namespace(current)
            if any(type(name) is not str for name in dict.keys(module_state)):
                raise _CapabilityInspectionLimitExceeded("module attribute name is not concrete text")
            if attribute_name not in module_state:
                raise _CapabilityInspectionLimitExceeded("module attribute could not be inspected statically")
            current = module_state[attribute_name]
            resolved.append(current)
        if not resolved:
            raise _CapabilityInspectionLimitExceeded("module global used without a static attribute reference")
        return tuple(resolved)

    @classmethod
    def _static_instance_state(cls, value: Any) -> dict[str, Any]:
        """Read a real instance dictionary while bypassing custom attribute hooks."""
        static_dictionary = cls._static_class_member(type(value), "__dict__")
        if static_dictionary is _STATIC_ATTRIBUTE_MISSING:
            return {}
        if not any(
            type(static_dictionary) is descriptor_type
            for descriptor_type in (types.GetSetDescriptorType, types.MemberDescriptorType)
        ):
            raise _CapabilityInspectionLimitExceeded("instance dictionary is shadowed")
        state = cls._builtin_descriptor_value(static_dictionary, value, "instance dictionary")
        if type(state) is not dict:
            raise _CapabilityInspectionLimitExceeded("instance dictionary is not a concrete mapping")
        if any(type(name) is not str for name in dict.keys(state)):
            raise _CapabilityInspectionLimitExceeded("instance dictionary key is not concrete text")
        return state
