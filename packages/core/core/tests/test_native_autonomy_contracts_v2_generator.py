"""Generator public rendering/check interface; no output implies qualification."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Annotated, ClassVar

import pytest
from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    PlainValidator,
    StringConstraints,
    ValidationError,
    WrapValidator,
    create_model,
    field_validator,
    model_validator,
)

from flinttrade_core import native_autonomy_contracts_v2 as contracts

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/generate-native-autonomy-v2-contracts.py"


@pytest.fixture
def generator() -> ModuleType:
    """Load the public contract generator as a fresh module.

    Returns:
        Generator module with the real schema and rendering entrypoints.
    """
    spec = importlib.util.spec_from_file_location("native_v2_contract_generator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("node", [
    {"type": "number"},
    {"type": "integer"},
    {"type": "string", "format": "date-time"},
    {"type": "string", "pattern": "(?P<python_only>.+)"},
    {"type": "string", "default": "implicit"},
    {"type": "object", "properties": {}, "required": [], "additionalProperties": True},
    {"type": "object", "properties": {"optional": {"type": "string"}}, "required": [], "additionalProperties": False},
    {"$ref": "https://example.invalid/schema"},
    {"type": "string", "x-v2-refinement": "invented"},
    {"allOf": [{"type": "string"}]},
    {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    {"type": "string", "if": {"const": "x"}, "then": {"const": "y"}},
])
def test_generator_refuses_unsupported_or_lossy_schema(generator: ModuleType, node: dict[str, object]) -> None:
    """Refuse schema constructs that cannot be represented without loss.

    Args:
        generator: Loaded public contract generator module.
        node: Unsupported synthetic schema definition.
    """
    document = generator.schema_document()
    document["$defs"]["UnsupportedV2"] = node
    with pytest.raises(ValueError):
        generator.render_zod(document)


def test_generator_refuses_dangling_and_recursive_definitions(generator: ModuleType) -> None:
    """Refuse unresolved and recursive definition references.

    Args:
        generator: Loaded public contract generator module.
    """
    for target in ("MissingV2", "RecursiveV2"):
        document = generator.schema_document()
        document["$defs"]["RecursiveV2"] = {"$ref": f"#/$defs/{target}"}
        with pytest.raises(ValueError):
            generator.render_zod(document)


def test_generator_is_deterministic_and_check_detects_drift(tmp_path: Path) -> None:
    """Keep repeated output byte-identical and detect drift without rewriting.

    Args:
        tmp_path: Disposable output root for the public generator command.
    """
    output = tmp_path / "generated"
    command = [sys.executable, str(SCRIPT), "--output-root", str(output)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    paths = sorted(p for p in output.rglob("*") if p.is_file())
    assert len(paths) == 2
    first = {str(p): p.read_bytes() for p in paths}
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert first == {str(p): p.read_bytes() for p in paths}
    assert subprocess.run([*command, "--check"], capture_output=True).returncode == 0
    paths[0].write_text("deliberately stale synthetic artifact\n")
    assert subprocess.run([*command, "--check"], capture_output=True).returncode == 1
    assert paths[0].read_text() == "deliberately stale synthetic artifact\n"


def test_structural_schema_explicitly_marks_non_schema_refinements(generator: ModuleType) -> None:
    """Expose audited refinements and refuse unrecognised refinement tags.

    Args:
        generator: Loaded public contract generator module.
    """
    document = generator.schema_document()
    assert "not qualification" in document["$comment"]
    assert document["$defs"]["RunViewV2"]["x-v2-refinement"] == "run_view"
    assert document["$defs"]["PositiveMoneyV2"]["additionalProperties"] is False
    other = copy.deepcopy(document)
    other["$defs"]["RiskPolicyV2"]["x-v2-refinement"] = "unreviewed"
    with pytest.raises(ValueError):
        generator.render_zod(other)


def _require_two(value):
    if value == "1":
        raise ValueError("unsupported_two_only")
    return value


def _wrap_two(value, handler):
    return _require_two(handler(value))


@pytest.mark.parametrize("validator", [
    AfterValidator(_require_two), BeforeValidator(_require_two),
    WrapValidator(_wrap_two), PlainValidator(_require_two),
], ids=["after", "before", "wrap", "plain"])
def test_generator_refuses_annotated_validators(
    generator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    validator: AfterValidator | BeforeValidator | WrapValidator | PlainValidator,
) -> None:
    """Reject runtime Annotated validators lost by structural projection.

    Args:
        generator: Loaded generator module.
        monkeypatch: Scoped contract registration fixture.
        validator: Unsupported runtime validator wrapper.
    """
    model = create_model("AddedMoneyV2", __base__=contracts.ClosedModel,
                         amount=(Annotated[contracts.PositiveDecimal, validator], ...))
    assert model.model_validate({"amount": "2"}).amount == "2"
    with pytest.raises(ValidationError, match="unsupported_two_only"):
        model.model_validate({"amount": "1"})
    monkeypatch.setattr(contracts, "AddedMoneyV2", model, raising=False)
    with pytest.raises(ValueError, match="Unmapped|Unsupported"):
        generator.schema_document()


@pytest.mark.parametrize("extension", ["added", "replaced", "field"])
def test_generator_refuses_validators_on_already_tagged_model(
    generator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    extension: str,
) -> None:
    """Reject extra, replaced and field validators despite a recognised tag.

    Args:
        generator: Loaded generator module.
        monkeypatch: Scoped contract registration fixture.
        extension: Unsupported decorator variation.
    """
    class AddedRiskV2(contracts.RiskPolicyV2):
        @model_validator(mode="after")
        def extra_rule(self):
            if self.max_mark_age_ms == 1:
                raise ValueError("unsupported_two_ms")
            return self

    class ReplacedRiskV2(contracts.RiskPolicyV2):
        @model_validator(mode="after")
        def coherent(self):
            if self.max_mark_age_ms == 1:
                raise ValueError("unsupported_two_ms")
            return self

    class FieldRiskV2(contracts.RiskPolicyV2):
        @field_validator("max_mark_age_ms")
        @classmethod
        def extra_rule(cls, value):
            if value == 1:
                raise ValueError("unsupported_two_ms")
            return value

    model = {"added": AddedRiskV2, "replaced": ReplacedRiskV2, "field": FieldRiskV2}[extension]
    cases = json.loads((ROOT / "packages/core/core/tests/fixtures/native-autonomy-v2.json").read_text())["cases"]
    value = next(c["value"] for c in cases if c["id"] == "RiskPolicyV2-positive")
    assert model.model_validate({**value, "max_mark_age_ms": 2}).max_mark_age_ms == 2
    for parse in (model.model_validate, lambda v: model.model_validate_json(json.dumps(v))):
        with pytest.raises(ValidationError, match="unsupported_two_ms"):
            parse(value)
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unmapped|Unsupported"):
        generator.schema_document()


def test_generator_refuses_untagged_decorator(generator: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject an untagged runtime model validator.

    Args:
        generator: Loaded generator module.
        monkeypatch: Scoped contract registration fixture.
    """
    class UntaggedMoneyV2(contracts.ClosedModel):
        amount: contracts.PositiveDecimal

        @model_validator(mode="after")
        def extra_rule(self):
            _require_two(self.amount)
            return self

    assert UntaggedMoneyV2.model_validate({"amount": "2"}).amount == "2"
    with pytest.raises(ValidationError):
        UntaggedMoneyV2.model_validate({"amount": "1"})
    monkeypatch.setattr(contracts, "UntaggedMoneyV2", UntaggedMoneyV2, raising=False)
    with pytest.raises(ValueError, match="Unmapped|Unsupported"):
        generator.schema_document()


@pytest.mark.parametrize("annotation", [
    Annotated[str, StringConstraints(strip_whitespace=True)],
    Annotated[contracts.PositiveInt, Field(strict=False)],
])
def test_generator_refuses_unrepresented_core_options(
    generator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    annotation: object,
) -> None:
    """Reject scalar transformations or coercion erased by JSON Schema.

    Args:
        generator: Loaded generator module.
        monkeypatch: Scoped contract registration fixture.
        annotation: Unsupported annotated field type.
    """
    model = create_model("ChangedScalarV2", __base__=contracts.ClosedModel, value=(annotation, ...))
    monkeypatch.setattr(contracts, "ChangedScalarV2", model, raising=False)
    with pytest.raises(ValueError, match="Unmapped|Unsupported"):
        generator.schema_document()


def test_generator_supports_structural_extensions_and_exact_inherited_validator(
    generator: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Execute supported structural and inherited mappings through actual Zod.

    Args:
        generator: Loaded generator module.
        monkeypatch: Scoped contract registration fixture.
        tmp_path: Writable isolated module directory.
    """
    class StructuralV2(contracts.ClosedModel):
        money: contracts.PositiveMoneyV2
        count: contracts.NonNegativeInt | None
        enabled: bool

    class InheritedRiskV2(contracts.RiskPolicyV2):
        pass

    for model in (StructuralV2, InheritedRiskV2):
        monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    document = generator.schema_document()
    assert document["$defs"]["InheritedRiskV2"]["x-v2-refinement"] == "risk_currency"
    text = generator.render_zod(document)
    assert "export const StructuralV2Schema = z.strictObject" in text
    assert "export const InheritedRiskV2Schema = z.strictObject" in text

    money = {"amount": "2", "currency": "INR"}
    structural = {"money": money, "count": 0, "enabled": True}
    rows = json.loads((ROOT / "packages/core/core/tests/fixtures/native-autonomy-v2.json").read_text())["cases"]
    risk = next(c["value"] for c in rows if c["id"] == "RiskPolicyV2-positive")
    bad_risk = copy.deepcopy(risk)
    bad_risk["exposure_cap"]["currency"] = "USD"
    assert StructuralV2.model_validate(structural).model_dump() == structural
    assert InheritedRiskV2.model_validate(risk).model_dump() == risk
    with pytest.raises(ValidationError):
        InheritedRiskV2.model_validate(bad_risk)
    # Execute actual newly emitted TypeScript, not a handwritten Zod facsimile.
    generated = tmp_path / "emitted.ts"
    text = text.replace(
        '"../lib/schemaValidation"',
        json.dumps(str(ROOT / "packages/apps/terminal/src/lib/schemaValidation.ts")),
    )
    text = text.replace('"zod"', json.dumps(str(ROOT / "packages/apps/terminal/node_modules/zod/index.js")))
    generated.write_text(text)
    runner = tmp_path / "verify.mjs"
    runner.write_text(
        'import assert from "node:assert/strict";\n'
        'import { StructuralV2Schema, InheritedRiskV2Schema } from "./emitted.ts";\n'
        f'assert.deepEqual(StructuralV2Schema.parse({json.dumps(structural)}), {json.dumps(structural)});\n'
        f'assert.equal(StructuralV2Schema.safeParse({json.dumps({**structural, "count": True})}).success, false);\n'
        f'assert.deepEqual(InheritedRiskV2Schema.parse({json.dumps(risk)}), {json.dumps(risk)});\n'
        f'assert.equal(InheritedRiskV2Schema.safeParse({json.dumps(bad_risk)}).success, false);\n'
    )
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("check", [False, True], ids=["write", "check"])
def test_generator_refuses_fixture_divergence_without_writes(tmp_path: Path, check: bool) -> None:
    """Reject divergent fixture bytes without any partial artifact write.

    Args:
        tmp_path: Writable isolated generator copy.
        check: Select read-only checking rather than write mode.
    """
    script = tmp_path / "scripts" / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    fixture_paths = [
        "packages/core/core/tests/fixtures/native-autonomy-v2.json",
        "packages/apps/terminal/src/generated/__tests__/fixtures/native-autonomy-v2.json",
        "packages/core/core/tests/fixtures/native-options-v2.json",
        "packages/apps/terminal/src/generated/__tests__/fixtures/native-options-v2.json",
    ]
    for relative in fixture_paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    command = [sys.executable, str(script)]
    assert subprocess.run(command, capture_output=True).returncode == 0

    def snapshot():
        return {p.relative_to(tmp_path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in tmp_path.rglob("*") if p.is_file()}

    clean = snapshot()
    assert subprocess.run([*command, "--check"], capture_output=True).returncode == 0
    assert snapshot() == clean
    projection = tmp_path / fixture_paths[1]
    projection.write_bytes(projection.read_bytes() + b"\n")
    divergent = snapshot()
    result = subprocess.run(command + (["--check"] if check else []), capture_output=True, text=True)
    assert result.returncode == 1
    assert "Fixture projection differs" in result.stdout + result.stderr
    assert snapshot() == divergent


@pytest.mark.parametrize("placement", ["direct", "inherited", "nested"])
def test_generator_refuses_unbound_public_projection(
    generator: "ModuleType", monkeypatch: pytest.MonkeyPatch, placement: str,
) -> None:
    """Refuse an unchecked projection before invoking it at any model depth.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        placement: Direct, inherited or nested use of the unsupported method.
    """
    class ProjectionOverrideV2(contracts.PositiveMoneyV2):
        """Unsupported projection that would erase the money grammar."""
        calls: ClassVar[int] = 0

        @classmethod
        def model_json_schema(cls) -> dict[str, object]:
            """Return a deliberately lossy schema.

            Returns:
                Structural money schema without its amount pattern.
            """
            cls.calls += 1
            document = super().model_json_schema()
            document["properties"]["amount"].pop("pattern")
            return document

    class InheritedProjectionV2(ProjectionOverrideV2):
        """Inherit the same unsupported projection without replacing it."""

    model = ProjectionOverrideV2 if placement == "direct" else InheritedProjectionV2
    if placement == "nested":
        model = create_model("NestedProjectionV2", __base__=contracts.ClosedModel,
                             money=(ProjectionOverrideV2, ...))
    assert ProjectionOverrideV2.model_validate({"amount": "2", "currency": "INR"}).amount == "2"
    for parse in (ProjectionOverrideV2.model_validate,
                  lambda value: ProjectionOverrideV2.model_validate_json(json.dumps(value))):
        with pytest.raises(ValidationError):
            parse({"amount": "not-money", "currency": "INR"})
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unsupported.*projection"):
        generator.render_zod(generator.schema_document())
    assert ProjectionOverrideV2.calls == InheritedProjectionV2.calls == 0


@pytest.mark.parametrize("change", ["nominal", "extra-field", "custom-eq", "custom-ne", "scalar", "nested"])
def test_generator_refuses_changed_refinement_operand_domains(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    """Challenge nominal, structural and behavioural changes behind mapped rules.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        change: Unsupported operand substitution, including a nested definition.
    """
    class ExtendedReferenceV2(contracts.RevisionRefV2):
        """Structurally identical reference with a distinct nominal type."""

    class AddedReferenceV2(contracts.RevisionRefV2):
        """Reference whose equality includes an unprojected extra field."""
        detail: contracts.OpaqueId

    class CustomEqualReferenceV2(contracts.RevisionRefV2):
        """Reference with unsupported equality behaviour."""

        def __eq__(self, other: object) -> bool:
            """Refuse every equality comparison.

            Args:
                other: Comparison operand.

            Returns:
                False, deliberately unlike value-based reference equality.
            """
            return False

    class CustomUnequalReferenceV2(contracts.RevisionRefV2):
        """Reference with unsupported inequality behaviour."""

        def __ne__(self, other: object) -> bool:
            """Report inequality regardless of supplied values.

            Args:
                other: Comparison operand.

            Returns:
                True for every operand.
            """
            return True

    ref = {"extra-field": AddedReferenceV2, "custom-eq": CustomEqualReferenceV2,
           "custom-ne": CustomUnequalReferenceV2}.get(change, ExtendedReferenceV2)
    risk = create_model("ChangedReferenceRiskV2", __base__=contracts.RiskPolicyV2,
                        policy_ref=(ref, ...))
    model = create_model("ChangedReferenceGrantV2", __base__=contracts.EntryGrantV2,
                         policy_ref=(ref, ...),
                         risk=(contracts.RiskPolicyV2 if change in {"nominal", "nested"} else risk, ...))
    if change == "scalar":
        model = create_model("ChangedScalarLimitsV2", __base__=contracts.EntryLimitsV2,
                             max_order_quantity=(contracts.PositiveDecimal, ...))
    if change == "nested":
        model = create_model("NestedChangedGrantV2", __base__=contracts.ClosedModel, grant=(model, ...))
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unsupported.*(operand|comparison)"):
        generator.render_zod(generator.schema_document())


@pytest.mark.parametrize("tag", ["entry_grant", "qualification_report", "run_view"])
def test_generator_checks_every_model_equality_mapping(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch, tag: str,
) -> None:
    """Refuse changed nominal reference or scope types at every equality mapping.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        tag: Mapping containing whole-model equality rather than scalar equality.
    """
    class OtherReferenceV2(contracts.RevisionRefV2):
        """Nominally different reference with unchanged wire shape."""

    class OtherScopeV2(contracts.RunScopeV2):
        """Nominally different scope with unchanged scalar validation."""

    base, field, annotation = {
        "entry_grant": (contracts.EntryGrantV2, "policy_ref", OtherReferenceV2),
        "qualification_report": (contracts.QualificationReportV2, "profile_ref", OtherReferenceV2),
        "run_view": (contracts.RunViewV2, "scope", OtherScopeV2),
    }[tag]
    model = create_model("ChangedEqualityV2", __base__=base, **{field: (annotation, ...)})
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unsupported.*operand"):
        generator.schema_document()


def test_generator_executes_matched_reference_extensions(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Execute matched nominal operands through Python and cold generated Zod.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        tmp_path: Writable isolated generated-module directory.
    """
    class ExtendedReferenceV2(contracts.RevisionRefV2):
        """Supported reference subclass with the exact reference domain."""

    class ExtendedRiskV2(contracts.RiskPolicyV2):
        """Risk whose reference uses the same nominal type as its grant."""
        policy_ref: ExtendedReferenceV2

    class MatchedReferenceGrantV2(contracts.EntryGrantV2):
        """Supported inherited rule with matching concrete reference operands."""
        policy_ref: ExtendedReferenceV2
        risk: ExtendedRiskV2

    class TwiceInheritedGrantV2(MatchedReferenceGrantV2):
        """Supported second inheritance level without changed semantics."""

    class NestedMatchedV2(contracts.ClosedModel):
        """Supported list containing the matched inherited grant."""
        grants: list[TwiceInheritedGrantV2]

    # Local annotations are resolved by Pydantic's parent namespace.
    fixtures = json.loads((ROOT / "packages/core/core/tests/fixtures/native-autonomy-v2.json").read_text())["cases"]
    value = next(row["value"] for row in fixtures if row["id"] == "EntryGrantV2-positive")
    invalid = copy.deepcopy(value)
    invalid["policy_ref"]["id"] = "different"
    for model in (MatchedReferenceGrantV2, TwiceInheritedGrantV2, NestedMatchedV2):
        monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    cases = [(model, {"grants": [row]} if model is NestedMatchedV2 else row, expected)
             for model in (MatchedReferenceGrantV2, TwiceInheritedGrantV2, NestedMatchedV2)
             for row, expected in ((value, True), (invalid, False))]
    for model, row, expected in cases:
        for parse, payload in ((model.model_validate, row), (model.model_validate_json, json.dumps(row))):
            if expected:
                assert parse(payload).model_dump(mode="json") == row
            else:
                with pytest.raises(ValidationError, match="entry_grant"):
                    parse(payload)
    text = generator.render_zod(generator.schema_document())
    zod = str(ROOT / "packages/apps/terminal/node_modules/zod/index.js")
    text = text.replace('"zod"', json.dumps(zod)).replace(
        '"../lib/schemaValidation"', json.dumps(str(ROOT / "packages/apps/terminal/src/lib/schemaValidation.ts")))
    (tmp_path / "emitted.ts").write_text(text)
    runner = tmp_path / "verify.mjs"
    runner.write_text(
        'import assert from "node:assert/strict";\n'
        f'import {{ z }} from {json.dumps(zod)};\n'
        'z.config({jitless:false}); const original = globalThis.Function; let calls = 0;\n'
        'globalThis.Function = function () { calls++; throw new Error("dynamic Function"); };\n'
        'let schemas; try { schemas = await import("./emitted.ts"); } finally { globalThis.Function = original; }\n'
        'assert.equal(calls, 0);\n'
        + "\n".join(
            f'assert.equal(schemas.{model.__name__}Schema.safeParse({json.dumps(row)}).success, '
            f'{json.dumps(expected)});'
            for model, row, expected in cases
        )
    )
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("base,field", [
    (contracts.RiskPolicyV2, "max_mark_age_ms"),
    (contracts.EntryLimitsV2, "max_order_quantity"),
    (contracts.ProducerPinV2, "kind"),
    (contracts.RunScopeV2, "run_id"),
    (contracts.CoverageV2, "window_start_ms"),
    (contracts.ObservationRefV2, "collected_at_ms"),
    (contracts.ReadPlanV2, "surfaces"),
    (contracts.EvidenceFactV2, "observed_at_ms"),
    (contracts.QualificationReportV2, "generated_at_ms"),
    (contracts.EntryGrantV2, "issued_by"),
    (contracts.DutyViewV2, "cumulative_entry_fill"),
    (contracts.TransferReceiptV2, "unknown_possible_writes"),
    (contracts.RunViewV2, "global_kill"),
], ids=["risk_currency", "entry_limits", "producer_pin", "run_scope", "coverage",
        "observation", "read_plan", "evidence_fact", "qualification_report",
        "entry_grant", "duty", "transfer", "run_view"])
def test_generator_binds_every_refinement_domain(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch,
    base: type[contracts.ClosedModel], field: str,
) -> None:
    """Reject a structurally representable but unmapped operand for every rule.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        base: Canonical mapped model retaining its actual validator body.
        field: Comparison operand changed to an incompatible scalar domain.
    """
    model = create_model("ChangedDomainV2", __base__=base, **{field: (str, ...)})
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unsupported.*operand shape"):
        generator.schema_document()


@pytest.mark.parametrize("container", ["single", "list"])
def test_generator_refuses_conflicting_nested_projection_names(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch, container: str,
) -> None:
    """Refuse nested definitions that would overwrite an audited canonical schema.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        container: Direct nested field or list of the conflicting definition.
    """
    leaf = create_model("RevisionRefV2", __base__=contracts.ClosedModel,
                        amount=(contracts.PositiveDecimal, ...))
    annotation = leaf if container == "single" else list[leaf]
    model = create_model("ConflictingContainerV2", __base__=contracts.ClosedModel,
                         references=(annotation, ...))
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Conflicting schema definition"):
        generator.render_zod(generator.schema_document())


@pytest.mark.parametrize("method", ["model_validate", "model_validate_json", "model_validate_strings"])
def test_generator_refuses_unbound_validation_entrypoints(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch, method: str,
) -> None:
    """Keep public Python parsing bound to the same audited compiled graph.

    Args:
        generator: Loaded public generator module.
        monkeypatch: Scoped contract registration fixture.
        method: Public Pydantic entrypoint replaced by unsupported semantics.
    """
    def reject(cls: type[contracts.ClosedModel], value: object) -> contracts.ClosedModel:
        """Reject independently of the otherwise unchanged compiled graph.

        Args:
            cls: Model class receiving the call.
            value: Supplied decoded value or JSON text.

        Raises:
            ValueError: Always, demonstrating an unmapped public parser.
        """
        raise ValueError("unsupported_public_validation")

    model = create_model("ChangedParserV2", __base__=contracts.PositiveMoneyV2,
                         __validators__={method: classmethod(reject)})
    monkeypatch.setattr(contracts, model.__name__, model, raising=False)
    with pytest.raises(ValueError, match="Unsupported.*projection"):
        generator.schema_document()


def test_current_and_historical_receipt_union_is_audited_and_emitted(generator: ModuleType) -> None:
    """Audit both strict receipt variants before exposing their generated union."""
    document = generator.schema_document()
    choices = document["$defs"]["RunViewV2"]["properties"]["transfer_receipts"]["items"]["anyOf"]
    assert choices == [{"$ref": "#/$defs/TransferReceiptV2"}, {"$ref": "#/$defs/HistoricalTransferReceiptV2"}]
    assert "z.union([TransferReceiptV2Schema, HistoricalTransferReceiptV2Schema])" in generator.render_zod(document)


def test_union_cannot_hide_an_unmapped_runtime_validator(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Translate no union branch until all nested runtime semantics are audited."""
    hidden = Annotated[str, AfterValidator(_require_two)]
    model = create_model("UnionWithHiddenValidatorV2", __base__=contracts.ClosedModel,
                         choice=(contracts.RevisionRefV2 | hidden, ...))
    monkeypatch.setattr(contracts, "UnionWithHiddenValidatorV2", model, raising=False)
    with pytest.raises(ValueError, match="validator"):
        generator.schema_document()
