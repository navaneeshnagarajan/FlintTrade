"""Generate closed v2 transport schemas; never mint or verify authority.

The JSON Schema describes structural validation. x-v2-refinement names the
additional cross-field rule enforced by Python and generated Zod, not by a
plain JSON Schema validator. Unsupported constructs abort generation.

Supported extensions use the unmodified Pydantic projection, construction and
attribute/comparison protocols. Untagged structural models may compose the
closed supported core subset. Mapped models may inherit their exact validator
and replace nested classes with structurally identical subclasses, including
multiple inheritance levels, but must retain every canonical field domain.
Whole-model equality additionally requires identical concrete operand types.
Extra reference fields, private state, custom equality/access and generic
origins are not silently reduced to value-only wire equality. This contract is
for decoded JSON values, not preconstructed Python subclass instances or
arbitrary runtime monkeypatching. Conflicting nested definition names refuse
rather than overwrite an audited schema. Changing a mapped rule requires
parity review.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import get_args

from flinttrade_core import native_autonomy_contracts_v2 as contracts

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path("packages/core/core/src/flinttrade_core/data/native-autonomy-v2.schema.json")
TS_PATH = Path("packages/apps/terminal/src/generated/nativeAutonomyV2.ts")

# Explicit Python/ECMAScript-compatible patterns, exercised by both runtimes.
# A new pattern needs review and parity cases rather than silent translation.
SUPPORTED_PATTERNS = {
    r"^(?:[1-9][0-9]{0,17}(?:\.[0-9]{0,7}[1-9])?|0\.[0-9]{0,7}[1-9])(?![\s\S])",
    r"^[A-Z]{3}(?![\s\S])",
    r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}(?![\s\S])",
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?![\s\S])",
    r"^[0-9a-f]{64}(?![\s\S])",
    r"^[a-z0-9][a-z0-9_-]{0,63}(?![\s\S])",
    r"^(?=[A-Za-z0-9._:@+\-]*[A-Za-z0-9])[A-Za-z0-9._:@+\-]{1,128}(?![\s\S])",
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\s\S])",
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])",
    r"^operator:[0-9a-f]{64}(?![\s\S])",
    r"^bounded:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}(?![\s\S])",
}

# Deliberately explicit, not a general-purpose JSON Schema translator.
REFINEMENTS = {
    "run_view": (
        "(() => { const {scope: s, config: c, report: r, grant: g, duty: d} = v; if (s.run_id !== "
        "c.run_id || s.broker !== c.broker || s.account_id !== c.account_id || s.environment !== "
        "c.environment || (r !== null && (!sameScope(r.scope, s) || !sameRef(r.profile_ref, "
        "c.operation_profile_ref) || !sameRef(r.policy_ref, c.risk.policy_ref))) || (g !== null && "
        "(!sameScope(g.scope, s) || JSON.stringify(g.risk) !== JSON.stringify(c.risk))) || (d !== "
        "null && !sameScope(d.scope, s)) || v.transfer_receipts.some(t => !sameScope(t.scope, s)) || "
        "new Set(v.transfer_receipts.map(t => t.transfer_ref.id)).size !== v.transfer_receipts.length"
        " || ((d === null) !== (v.duty_state === 'none')) || (d !== null && v.duty_state !== "
        "'reconciliation_required' && v.duty_state !== (d.custody === 'run_retained' ? 'retained' : "
        "d.custody)) || (v.producer_state === 'running' && v.entry_state !== 'started') || "
        "(['granted', 'started'].includes(v.entry_state) && (g === null || v.global_kill)) || "
        "(v.loss_threshold_latched && v.entry_state !== 'retired') || ((v.global_kill || "
        "v.loss_threshold_latched) && v.effective_authority !== 'none')) return false; if "
        "(v.effective_authority === 'none') return true; return v.requested_authority === "
        "'bounded_entry' && v.entry_state === 'started' && v.producer_state === 'running' && "
        "v.observation_freshness === 'fresh' && r !== null && r.status === 'eligible' && g !== null "
        "&& g.state === 'active' && sameRef(g.report_ref, r.report_ref) && g.expires_at_ms <= "
        "r.expires_at_ms && g.issued_at_ms >= r.generated_at_ms && d !== null && "
        "!d.unknown_possible_writes && d.possible_entry_quantity !== null && ['contingent', "
        "'open'].includes(d.state) && ['verified_broker_held', "
        "'operator_accepted'].includes(d.coverage) && v.duty_state !== 'reconciliation_required'; "
        "})()"
    ),
    "transfer": (
        "v.scope.broker === v.account_provenance.broker && v.scope.account_id === "
        "v.account_provenance.account_id && v.scope.registry_generation === "
        "v.account_provenance.registry_generation && v.unknown_possible_writes === "
        "v.obligations.some(o => o.kind === 'unknown_write') && ((v.obligations.length === 0 && "
        "v.model_obligations.length === 0) || v.reconciliation_required) && new "
        "Set(v.obligations.map(o => o.obligation_id)).size === v.obligations.length && new "
        "Set(v.model_obligations.map(m => m.request_ref.id)).size === v.model_obligations.length"
    ),
    "duty": (
        "v.cumulative_exit_fill <= v.cumulative_entry_fill && (v.cumulative_entry_fill === 0 || "
        "v.entry_fill_refs.length > 0) && (v.cumulative_exit_fill === 0 || v.exit_fill_refs.length > "
        "0) && v.unknown_possible_writes === v.obligations.some(o => o.kind === 'unknown_write') && "
        "(() => { let total = 0n; for (const o of v.obligations) { if (o.kind === 'unknown_write') "
        "return v.possible_entry_quantity === null; if (o.kind === 'possible_entry') { if "
        "(o.possible_quantity === null) return v.possible_entry_quantity === null; total += "
        "BigInt(o.possible_quantity); } } return v.possible_entry_quantity !== null && "
        "BigInt(v.possible_entry_quantity) === total; })() && new Set(v.obligations.map(o => "
        "o.obligation_id)).size === v.obligations.length && (v.custody !== 'operator' || "
        "v.receiving_acceptance_ref !== null) && (v.coverage !== 'operator_accepted' || v.custody ==="
        " 'operator') && (v.custody !== 'broker_held' || v.coverage === 'verified_broker_held') && "
        "(v.state !== 'transferred' || v.custody === 'operator') && (v.state !== 'settled' || "
        "(v.obligations.length === 0 && v.model_obligations.length === 0 && v.possible_entry_quantity"
        " === 0 && v.cumulative_entry_fill === v.cumulative_exit_fill)) && new "
        "Set(v.model_obligations.map(m => m.request_ref.id)).size === v.model_obligations.length"
    ),
    "entry_grant": (
        "v.issued_by === v.scope.operator && sameRef(v.policy_ref, v.risk.policy_ref) && "
        "v.expires_at_ms > v.issued_at_ms && v.expires_at_ms - v.issued_at_ms <= "
        "v.limits.max_duration_ms"
    ),
    "qualification_report": (
        "(() => { const d = v.dimensions; const facts = [d.software, d.account_eligibility, "
        "d.observations, d.demonstrated_action, d.custody, d.fees, d.producer]; if (v.expires_at_ms "
        "<= v.generated_at_ms || facts.some(f => !sameRef(f.profile_ref, v.profile_ref)) || "
        "((v.status === 'blocked') !== (v.blocking_reasons.length > 0))) return false; if (v.status "
        "!== 'eligible') return true; if (facts.some(f => !['verified', "
        "'not_required'].includes(f.status) || (f.status === 'verified' && (f.observed_at_ms === null"
        " || f.expires_at_ms === null || f.observed_at_ms > v.generated_at_ms || v.expires_at_ms > "
        "f.expires_at_ms)))) return false; if (v.scope.environment !== 'production') return true; "
        "const allowed = [['reviewed_software', 'installed_runtime'], ['broker_read'], "
        "['broker_read'], ['demonstrated_broker_action'], ['demonstrated_broker_action', "
        "'operator_policy'], ['documented_contract', 'broker_read'], ['reviewed_software', "
        "'installed_runtime']]; return facts.every((f, i) => f.status === 'not_required' || "
        "allowed[i]?.includes(f.provenance) === true); })()"
    ),
    "evidence_fact": (
        "(v.observed_at_ms === null) === (v.expires_at_ms === null) && (v.observed_at_ms === null || "
        "(v.expires_at_ms !== null && v.expires_at_ms > v.observed_at_ms)) && (!['verified', "
        "'stale'].includes(v.status) || (v.evidence_ref !== null && v.observed_at_ms !== null && "
        "v.expires_at_ms !== null)) && (v.status !== 'not_required' || v.provenance === "
        "'documented_contract') && new Set(v.coverage).size === v.coverage.length"
    ),
    "read_plan": (
        "new Set(v.surfaces).size === v.surfaces.length"
    ),
    "observation": (
        "new Set(v.coverage.map(c => JSON.stringify([c.surface, c.family]))).size === "
        "v.coverage.length && v.coverage.every(c => c.window_end_ms <= v.collected_at_ms) && "
        "(v.availability !== 'complete' || v.coverage.every(c => c.availability === 'complete')) && "
        "(v.broker_as_of_ms === null || v.broker_as_of_ms <= v.collected_at_ms)"
    ),
    "coverage": (
        "v.window_start_ms <= v.window_end_ms && (v.availability !== 'complete' || v.pages_complete)"
    ),
    "run_scope": (
        "v.actor === `bounded:${v.run_id}`"
    ),
    "producer_pin": (
        "(v.kind === 'model') === (v.model !== null)"
    ),
    "entry_limits": (
        "v.max_order_quantity <= v.max_total_quantity && new Set(v.actions).size === v.actions.length"
        " && v.actions.includes('place') && new Set(v.instruments.map(i => "
        "JSON.stringify([i.instrument_id, i.exchange, i.product]))).size === v.instruments.length"
    ),
    "risk_currency": (
        "v.capital_cap.currency === v.exposure_cap.currency && v.capital_cap.currency === "
        "v.loss_action_threshold.currency"
    ),
    "historical_transfer": (
        "v.scope.broker === v.account_provenance.broker && v.scope.account_id === "
        "v.account_provenance.account_id && v.scope.registry_generation === "
        "v.account_provenance.registry_generation && v.unknown_possible_writes === "
        "v.obligations.some(o => o.kind === 'unknown_write') && (v.obligations.length === 0 || "
        "v.reconciliation_required) && new Set(v.obligations.map(o => o.obligation_id)).size === "
        "v.obligations.length"
    ),
    "model_attempt_duty": (
        "(() => { const known = ['SETTLED', 'CANCELLED'].includes(v.state); return (v.observed_tokens"
        " !== null) === known && (v.observed_cost_micros !== null) === known && (v.state !== "
        "'CANCELLED' || (v.observed_tokens === 0 && v.observed_cost_micros === 0)); })()"
    ),
    "model_duty": (
        "new Set(v.attempts.map(a => a.attempt_id)).size === v.attempts.length && v.attempts.every(a "
        "=> a.currency === v.currency) && (['reserved', 'pending'].includes(v.task_outcome) || "
        "v.attempts.some(a => !['SETTLED', 'CANCELLED'].includes(a.state)))"
    ),
}


# Bind the actual supported functions, not method names or a blanket tag.
# Changing one of these rules still requires Python/Zod semantic parity review.
REFINEMENTS.update({
    "options_risk_currency": REFINEMENTS["risk_currency"],
    "options_entry_grant": REFINEMENTS["entry_grant"],
    "options_run_view": REFINEMENTS["run_view"],
})
VALIDATOR_BINDINGS = {
    "model_attempt_duty": contracts.ModelAttemptDutyV2.coherent,
    "model_duty": contracts.ModelDutyV2.coherent,
    "historical_transfer": contracts.HistoricalTransferReceiptV2.coherent,
    "options_risk_currency": contracts.OptionsRiskPolicyV2.coherent,
    "options_entry_grant": contracts.OptionsEntryGrantV2.coherent,
    "options_run_view": contracts.OptionsRunViewV2.coherent,
    "risk_currency": contracts.RiskPolicyV2.coherent,
    "entry_limits": contracts.EntryLimitsV2.coherent,
    "producer_pin": contracts.ProducerPinV2.coherent,
    "run_scope": contracts.RunScopeV2.coherent,
    "coverage": contracts.CoverageV2.coherent,
    "observation": contracts.ObservationRefV2.coherent,
    "read_plan": contracts.ReadPlanV2.coherent,
    "evidence_fact": contracts.EvidenceFactV2.coherent,
    "qualification_report": contracts.QualificationReportV2.coherent,
    "entry_grant": contracts.EntryGrantV2.coherent,
    "duty": contracts.DutyViewV2.coherent,
    "transfer": contracts.TransferReceiptV2.coherent,
    "run_view": contracts.RunViewV2.coherent,
}

# Finite operand contract: mapped models keep the complete canonical field
# domains, including nested shapes, nullability, list bounds and scalar rules.
# Structural subclasses are allowed; changed domains need a new reviewed map.
# Domains used by each mapping (all are checked, not just whole-model equality):
# risk_currency: currency strings; entry_limits: safe integers/string tuple sets;
# producer_pin: enum/null; run_scope: strings; coverage: time integers/enum/bool;
# observation: string tuple sets/time integers/enum/null; read_plan: string sets;
# evidence_fact: time/null/enum/string sets; qualification_report: refs/times/enums;
# entry_grant: operator strings/refs/time integers; duty: safe-integer sums/null,
# strings/sets/bools; transfer: scalar scope identifiers/sets/bools;
# run_view: complete scope/risk/ref equality plus scalar states/times/null/bools.
REFINEMENT_MODELS = {
    "model_attempt_duty": contracts.ModelAttemptDutyV2,
    "model_duty": contracts.ModelDutyV2,
    "historical_transfer": contracts.HistoricalTransferReceiptV2,
    "options_risk_currency": contracts.OptionsRiskPolicyV2,
    "options_entry_grant": contracts.OptionsEntryGrantV2,
    "options_run_view": contracts.OptionsRunViewV2,
    "risk_currency": contracts.RiskPolicyV2,
    "entry_limits": contracts.EntryLimitsV2,
    "producer_pin": contracts.ProducerPinV2,
    "run_scope": contracts.RunScopeV2,
    "coverage": contracts.CoverageV2,
    "observation": contracts.ObservationRefV2,
    "read_plan": contracts.ReadPlanV2,
    "evidence_fact": contracts.EvidenceFactV2,
    "qualification_report": contracts.QualificationReportV2,
    "entry_grant": contracts.EntryGrantV2,
    "duty": contracts.DutyViewV2,
    "transfer": contracts.TransferReceiptV2,
    "run_view": contracts.RunViewV2,
}
# Python compares concrete Pydantic types as well as values. Wire equality is
# sound only when both decoded operands have the same audited concrete class.
MODEL_EQUALITIES = {
    "entry_grant": (("policy_ref", "risk.policy_ref"),),
    "qualification_report": tuple((f"dimensions.{name}.profile_ref", "profile_ref")
                                 for name in ("software", "account_eligibility", "observations",
                                              "demonstrated_action", "custody", "fees", "producer")),
    "run_view": (("report.scope", "scope"), ("report.profile_ref", "config.operation_profile_ref"),
                 ("report.policy_ref", "config.risk.policy_ref"), ("grant.scope", "scope"),
                 ("grant.risk", "config.risk"), ("duty.scope", "scope"),
                 ("grant.report_ref", "report.report_ref")),
}


MODEL_EQUALITIES.update({
    "options_entry_grant": MODEL_EQUALITIES["entry_grant"],
    "options_run_view": MODEL_EQUALITIES["run_view"],
})


def _operand_shape(model: type[contracts.ClosedModel]) -> tuple:
    """Describe compiled operand domains without erasing constraints.

    Args:
        model: Runtime model whose compiled graph has passed the core audit.

    Returns:
        Comparable shape, ignoring only nominal model names and descriptions.

    Raises:
        ValueError: A reference is missing or recursive.
    """
    definitions = {}

    def collect(value: object) -> None:
        """Index compiled definitions.

        Args:
            value: A nested compiled-schema value.
        """
        if isinstance(value, dict):
            if "ref" in value:
                definitions[value["ref"]] = value
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    def shape(node: dict, active: frozenset[str] = frozenset()) -> tuple:
        """Project an already audited node into its comparison domain.

        Args:
            node: Compiled validation node.
            active: References on the current traversal path.

        Returns:
            Exact structural domain, retaining mapped function identity.

        Raises:
            ValueError: A reference is absent or cyclic.
        """
        kind = node["type"]
        if kind == "definition-ref":
            ref = node["schema_ref"]
            if ref in active or ref not in definitions:
                raise ValueError("Unsupported refinement operand reference")
            return shape(definitions[ref], active | {ref})
        if kind in {"definitions", "model", "model-field"}:
            return shape(node["schema"], active)
        if kind == "model-fields":
            return (kind, tuple((name, shape(field, active)) for name, field in sorted(node["fields"].items())))
        if kind == "function-after":
            return (kind, node["function"]["function"], shape(node["schema"], active))
        if kind == "union":
            return (kind, tuple(shape(choice, active) for choice in node["choices"]))
        options = {k: v for k, v in node.items() if k not in {"ref", "metadata", "schema", "items_schema"}}
        children = tuple(shape(node[key], active) for key in ("schema", "items_schema") if key in node)
        return (json.dumps(options, sort_keys=True), children)

    collect(model.__pydantic_core_schema__)
    return shape(model.__pydantic_core_schema__)


def _operand_model(model: type[contracts.ClosedModel], path: str) -> type[contracts.ClosedModel]:
    """Resolve the concrete model at an equality operand path.

    Args:
        model: Root model of the mapped refinement.
        path: Dotted path traversing models, optionally nullable.

    Returns:
        Concrete class used to decode the operand.

    Raises:
        ValueError: The path is not an audited model-valued operand.
    """
    for part in path.split("."):
        annotation = model.model_fields[part].annotation
        args = get_args(annotation)
        if args:
            candidates = [arg for arg in args if arg is not type(None)]
            if len(candidates) != 1:
                raise ValueError("Unsupported refinement operand union")
            annotation = candidates[0]
        if not isinstance(annotation, type) or not issubclass(annotation, contracts.ClosedModel):
            raise ValueError("Unsupported refinement operand model")
        model = annotation
    return model


def _check_operands(model: type[contracts.ClosedModel], tag: str) -> None:
    """Bind all mapped operand domains and whole-model equality pairs.

    Args:
        model: Candidate canonical model or structural inherited extension.
        tag: Previously bound refinement identifier.

    Raises:
        ValueError: Shape or concrete equality domains differ from the mapping.
    """
    if _operand_shape(model) != _operand_shape(REFINEMENT_MODELS[tag]):
        raise ValueError(f"Unsupported refinement operand shape: {model.__name__}")
    for left, right in MODEL_EQUALITIES.get(tag, ()):
        if _operand_model(model, left) is not _operand_model(model, right):
            raise ValueError(f"Unsupported refinement equality operands: {model.__name__}.{left}/{right}")


# Pydantic JSON Schema omits runtime-only validation/transformation. Audit the
# compiled validation graph before projecting it. Unknown kinds/options refuse.
CORE_KEYS = {
    "definitions": {"schema", "definitions"},
    "definition-ref": {"schema_ref"},
    "model": {"cls", "schema", "custom_init", "root_model", "config"},
    "model-fields": {"fields", "model_name", "computed_fields"},
    "model-field": {"schema"},
    "function-after": {"function", "schema"},
    "str": {"pattern", "strict"},
    "int": {"gt", "ge", "le", "strict"},
    "bool": {"strict"},
    "literal": {"expected"},
    "list": {"items_schema", "min_length", "max_length", "strict"},
    "nullable": {"schema"},
    "union": {"choices"},
}


def _check_model(model: type[contracts.ClosedModel]) -> None:
    if type(model) is not type(contracts.BaseModel) or model.__private_attributes__:
        raise ValueError(f"Unsupported comparison model: {model.__name__}")
    for method in ("__eq__", "__ne__", "__getattribute__", "__getattr__"):
        if inspect.getattr_static(model, method) is not inspect.getattr_static(contracts.BaseModel, method):
            raise ValueError(f"Unsupported comparison behaviour: {model.__name__}.{method}")
    if model.__pydantic_generic_metadata__.get("origin") is not None:
        raise ValueError(f"Unsupported comparison generic: {model.__name__}")
    for field in model.model_fields:
        if any(field in vars(base) for base in model.__mro__):
            raise ValueError(f"Unsupported operand descriptor: {model.__name__}.{field}")
    decorators = model.__pydantic_decorators__
    if any(getattr(decorators, key) for key in (
        "validators", "root_validators", "field_validators", "field_serializers",
        "model_serializers", "computed_fields",
    )):
        raise ValueError(f"Unmapped validator/serializer: {model.__name__}")
    extra = model.model_config.get("json_schema_extra", {})
    if not isinstance(extra, dict) or set(extra) - {"x-v2-refinement"}:
        raise ValueError(f"Unsupported schema customisation: {model.__name__}")
    tag = extra.get("x-v2-refinement")
    rules = list(decorators.model_validators.values())
    if tag is None:
        if rules:
            raise ValueError(f"Unmapped validator: {model.__name__}")
    elif (tag not in VALIDATOR_BINDINGS or len(rules) != 1
          or rules[0].func is not VALIDATOR_BINDINGS[tag] or rules[0].info.mode != "after"):
        raise ValueError(f"Unmapped validator: {model.__name__}")
    for hook in ("model_json_schema", "model_validate", "model_validate_json", "model_validate_strings",
                 "__get_pydantic_core_schema__", "__get_pydantic_json_schema__"):
        if inspect.getattr_static(model, hook) is not inspect.getattr_static(contracts.BaseModel, hook):
            raise ValueError(f"Unsupported schema projection: {model.__name__}.{hook}")
    if set(model.model_config) - {"extra", "strict", "frozen", "regex_engine", "json_schema_extra"}:
        raise ValueError(f"Unsupported model configuration: {model.__name__}")
    if any(model.model_config.get(k) != v for k, v in contracts.ClosedModel.model_config.items()):
        raise ValueError(f"Unsupported model configuration: {model.__name__}")


def _check_core(node: dict) -> None:
    kind = node.get("type")
    if kind not in CORE_KEYS or set(node) - (CORE_KEYS[kind] | {"type", "ref", "metadata"}):
        raise ValueError(f"Unsupported core schema construct: {kind}")
    metadata = node.get("metadata", {})
    if set(metadata) - {"pydantic_js_functions"}:
        raise ValueError("Unsupported core schema metadata")
    for hook in metadata.get("pydantic_js_functions", []):
        if (kind not in {"model", "function-after"}
                or getattr(hook, "__func__", None) is not contracts.BaseModel.__get_pydantic_json_schema__.__func__):
            raise ValueError("Unsupported JSON schema hook")
    if "strict" in node and node["strict"] is not True:
        raise ValueError("Unsupported coercing core schema")
    if kind == "model":
        _check_model(node["cls"])
        if node.get("custom_init") is not False or node.get("root_model") is not False:
            raise ValueError("Unsupported model construction")
        config = {k: v for k, v in node["config"].items() if k != "title"}
        if config != {"extra_fields_behavior": "forbid", "strict": True, "regex_engine": "python-re"}:
            raise ValueError("Unsupported core model configuration")
    elif kind == "function-after":
        fn = node["function"]
        child = node["schema"]
        if (set(fn) != {"type", "function"} or fn["type"] != "no-info"
                or child.get("type") != "model"):
            raise ValueError("Unmapped core validator")
        tag = child["cls"].model_config.get("json_schema_extra", {}).get("x-v2-refinement")
        if tag not in VALIDATOR_BINDINGS or fn["function"] is not VALIDATOR_BINDINGS[tag]:
            raise ValueError("Unmapped core validator")
    elif kind == "model-fields":
        if node.get("computed_fields"):
            raise ValueError("Unsupported computed fields")
        for field in node["fields"].values():
            _check_core(field)
    if kind == "union":
        choices = node["choices"]
        if type(choices) is not list or len(choices) < 2 or any(type(choice) is not dict for choice in choices):
            raise ValueError("Unsupported labelled or incomplete core union")
        for choice in choices:
            _check_core(choice)
    if "schema" in node:
        _check_core(node["schema"])
    if "items_schema" in node:
        _check_core(node["items_schema"])
    for definition in node.get("definitions", []):
        _check_core(definition)
    if kind == "model":
        model = node["cls"]
        tag = model.model_config.get("json_schema_extra", {}).get("x-v2-refinement")
        if tag is not None:
            _check_operands(model, tag)


def schema_document() -> dict:
    """Project audited runtime models to structural JSON Schema.

    Returns:
        Closed v2 definitions with explicit semantic-refinement tags.

    Raises:
        ValueError: A validator identity, core construct or customisation has
            no reviewed translation. Tags alone never cover extra validators.

    Reference existence, genuine evidence and owner authority are not verified.
    """
    models = {name: model for name, model in vars(contracts).items()
              if isinstance(model, type) and issubclass(model, contracts.ClosedModel)
              and model is not contracts.ClosedModel}
    # Complete the nested runtime audit before calling any projection method.
    for model in models.values():
        _check_model(model)
        _check_core(model.__pydantic_core_schema__)
    definitions = {}
    for name, model in models.items():
        schema = contracts.BaseModel.model_json_schema.__func__(model)
        nested = schema.pop("$defs", {})
        for key, definition in [(name, schema), *nested.items()]:
            if key in definitions and definitions[key] != definition:
                raise ValueError(f"Conflicting schema definition: {key}")
            definitions[key] = definition
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:flinttrade:native-autonomy:v2",
        "$comment": ("Transport validation is not qualification, a grant, or Start. "
                     "x-v2-refinement requires the accompanying Python/Zod validator."),
        "$ref": "#/$defs/RunViewV2",
        "$defs": definitions,
    }


def render_zod(document: dict) -> str:
    """Render the supported schema subset with reviewed Zod refinements.

    Args:
        document: Structural schema from the audited model projection.

    Returns:
        Deterministic TypeScript using the maintained no-eval bootstrap.

    Raises:
        ValueError: A construct, bound, pattern or reference is unsupported.

    Decoded-value parity does not preserve raw numeric JSON spelling. This
    renderer cannot prove arbitrary input schemas describe Python validators;
    use schema_document for the runtime audit, and test changed rules in both
    languages. Parsing the output never establishes execution authority.
    """
    if set(document) != {"$schema", "$id", "$comment", "$ref", "$defs"}:
        raise ValueError("Unsupported schema document")
    definitions = document["$defs"]
    emitted = set()
    visiting = set()
    lines = [
        "// Generated by scripts/generate-native-autonomy-v2-contracts.py. Do not edit.",
        "// DTO validation is not production qualification or execution authority.",
        'import { z } from "zod";',
        'import { initialiseSchemaValidation } from "../lib/schemaValidation";',
        "initialiseSchemaValidation();",
        (
            "function sameRef(a: RevisionRefV2, b: RevisionRefV2): boolean { return a.id === b.id && "
            "a.revision === b.revision; }"
        ),
        (
            "function sameScope(a: RunScopeV2, b: RunScopeV2): boolean { return a.run_id === b.run_id "
            "&& a.operator === b.operator && a.actor === b.actor && a.broker === b.broker && "
            "a.account_id === b.account_id && a.environment === b.environment && a.registry_generation "
            "=== b.registry_generation && a.binding_revision === b.binding_revision; }"
        ),
        "",
    ]

    def emit(name: str) -> None:
        if name in emitted:
            return
        if name in visiting or name not in definitions or not name.isidentifier():
            raise ValueError("Cyclic, invalid or missing definition")
        visiting.add(name)
        expression = translate(definitions[name])
        lines.append(f"export const {name}Schema = {expression};")
        lines.append(f"export type {name} = z.infer<typeof {name}Schema>;\n")
        emitted.add(name)
        visiting.remove(name)

    def translate(node: dict) -> str:
        if not isinstance(node, dict):
            raise ValueError("Boolean or non-object schemas unsupported")
        base = {"title", "description", "x-v2-refinement"}
        if "$ref" in node:
            allowed = base | {"$ref"}
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
                raise ValueError("Non-local schema reference")
            name = ref.removeprefix("#/$defs/")
            emit(name)
            result = f"{name}Schema"
        elif "anyOf" in node:
            allowed = base | {"anyOf"}
            if not isinstance(node["anyOf"], list) or len(node["anyOf"]) < 2:
                raise ValueError("Invalid union")
            result = "z.union([" + ", ".join(translate(n) for n in node["anyOf"]) + "])"
        elif "const" in node:
            allowed = base | {"const", "type"}
            if node.get("type") != "string" or not isinstance(node["const"], str):
                raise ValueError("Only string literals supported")
            result = f"z.literal({json.dumps(node["const"])})"
        elif "enum" in node:
            allowed = base | {"enum", "type"}
            if node.get("type") != "string" or not node["enum"] or not all(type(x) is str for x in node["enum"]):
                raise ValueError("Only nonempty string enums supported")
            result = f"z.enum({json.dumps(node["enum"])})"
        elif node.get("type") == "object":
            allowed = base | {"type", "properties", "required", "additionalProperties"}
            if (node.get("additionalProperties") is not False
                    or set(node.get("required", [])) != set(node.get("properties", {}))):
                raise ValueError("Only closed all-required objects supported")
            fields = [f"  {json.dumps(key)}: {translate(value)}" for key, value in sorted(node["properties"].items())]
            result = "z.strictObject({\n" + ",\n".join(fields) + "\n})"
        elif node.get("type") == "array":
            allowed = base | {"type", "items", "minItems", "maxItems"}
            result = f"z.array({translate(node["items"])})"
            for keyword, method in [("minItems", "min"), ("maxItems", "max")]:
                if keyword in node:
                    result += f".{method}({node[keyword]})"
        elif node.get("type") == "string":
            allowed = base | {"type", "pattern"}
            result = "z.string()"
            if "pattern" in node:
                if node["pattern"] not in SUPPORTED_PATTERNS:
                    raise ValueError("Unsupported unreviewed regex pattern")
                result += f".regex(new RegExp({json.dumps(node["pattern"])}))"
        elif node.get("type") == "integer":
            allowed = base | {"type", "minimum", "maximum", "exclusiveMinimum"}
            bounds = [node[key] for key in ("minimum", "maximum", "exclusiveMinimum") if key in node]
            if ("maximum" not in node or not ({"minimum", "exclusiveMinimum"} & set(node))
                    or any(type(bound) is not int or abs(bound) > 9007199254740991 for bound in bounds)):
                raise ValueError("Only explicitly bounded safe integers supported")
            result = "z.number().int()"
            for keyword, method in [("minimum", "min"), ("maximum", "max"), ("exclusiveMinimum", "gt")]:
                if keyword in node:
                    result += f".{method}({node[keyword]})"
        elif node.get("type") in {"null", "boolean"}:
            allowed = base | {"type"}
            result = "z.null()" if node["type"] == "null" else "z.boolean()"
        else:
            raise ValueError(f"Unsupported schema type: {node.get("type")}")
        if set(node) - allowed:
            raise ValueError(f"Unsupported schema keywords: {sorted(set(node) - allowed)}")
        rule = node.get("x-v2-refinement")
        if rule is not None:
            if rule not in REFINEMENTS:
                raise ValueError(f"Unsupported refinement: {rule}")
            result += f".refine(v => {REFINEMENTS[rule]}, {json.dumps(rule)})"
        return result

    for name in sorted(definitions):
        emit(name)
    lines.append("export const nativeAutonomyV2Schemas = {\n"
                 + ",\n".join(f"  {name}: {name}Schema" for name in sorted(definitions)) + "\n};\n")
    return "\n".join(lines)


def render() -> dict[Path, str]:
    """Check fixture equality and render both artefacts without writing.

    The Python fixture is canonical; its TS projection must match exact bytes.
    The check applies to source inputs even with a separate output directory.

    Returns:
        Complete relative-path/text outputs after runtime and schema checks.

    Raises:
        ValueError: Fixtures diverge or a runtime/schema construct is unmapped.
        OSError: A required source fixture cannot be read.
    """
    for name in ("native-autonomy-v2.json", "native-options-v2.json"):
        canonical = ROOT / "packages/core/core/tests/fixtures" / name
        projection = ROOT / "packages/apps/terminal/src/generated/__tests__/fixtures" / name
        if canonical.read_bytes() != projection.read_bytes():
            raise ValueError("Fixture projection differs from canonical Python corpus")
    document = schema_document()
    return {SCHEMA_PATH: json.dumps(document, indent=2, sort_keys=True) + "\n", TS_PATH: render_zod(document)}


def main() -> int:
    """Generate artefacts or compare them using read-only --check.

    Returns:
        Zero for a match or successful generation; one for stale output.

    Raises:
        ValueError: Fixture or schema validation fails before any output write.
        OSError: Required input/output storage is unavailable.

    No route, qualification or owner authority is installed by this command.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    outputs = render()  # Fully validate before writing either output.
    for relative, text in outputs.items():
        path = args.output_root / relative
        if args.check:
            if not path.is_file() or path.read_text() != text:
                print(f"Stale generated artefact: {relative}")
                return 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
