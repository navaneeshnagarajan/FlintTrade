import ast
import hashlib
from pathlib import Path
import re
import subprocess

from flinttrade_core.model_rights_policies import TIMESFM_3_RESTRICTION_POLICY
from flinttrade_core.service_providers import (
    EvidenceUseScope,
    LicenceFact,
    ModelIdentity,
    PermissionState,
    RightsBasis,
    RightsGrant,
    UsageRights,
    intersect_rights,
)


def _fact(basis: RightsBasis, *, identifier: str, subject_kind: str = "service") -> LicenceFact:
    return LicenceFact(
        fact_id=f"{basis.value}:{identifier}",
        subject_kind=subject_kind,
        identifier=identifier,
        source_uri="https://evidence.example.invalid/v1",
        revision="revision-1",
        sha256="f" * 64,
        reviewed_at="2026-09-04T00:00:00Z",
        basis=basis,
    )


def _contains_restricted_identifier(line: str) -> bool:
    return (
        _RESTRICTED_IDENTIFIER_PATTERN.search(line) is not None
        or _TIMESFM_PHRASE_PATTERN.search(line) is not None
        or _static_literal_chain_contains_restricted_identifier(line)
        or _static_literal_contains_restricted_identifier(line)
    )


_STATIC_LITERAL_PATTERN = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
_GUARD_STRUCTURE_DIGEST = "c59f6d2d5c2dd8a77ca7f05f5c80d678b4ce973abfbd34d9e53f5a3a291f559b"
_RESTRICTED_IDENTIFIER_PATTERN = re.compile(r"times[ _.-]*fm", flags=re.IGNORECASE)
_TIMESFM_PHRASE_PATTERN = re.compile(
    r"(?<![a-z0-9])times(?:[ _.-]+)fm",
    flags=re.IGNORECASE,
)
_STATIC_ESCAPE_PATTERN = re.compile(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[\\\"'nrtbfv])")
_STATIC_ESCAPE_REPLACEMENTS = {
    r"\\": "\\",
    r'\"': '"',
    r"\'": "'",
    r"\n": "\n",
    r"\r": "\r",
    r"\t": "\t",
    r"\b": "\b",
    r"\f": "\f",
    r"\v": "\v",
}


def _is_restricted_identifier_chain(chain: str) -> bool:
    return "timesfm" in re.sub(r"[^a-z0-9]+", "", chain.casefold())


def _guard_file_structure_digest(source: str) -> str:
    normalised = re.sub(
        r'_GUARD_STRUCTURE_DIGEST = "[0-9a-f]*"',
        '_GUARD_STRUCTURE_DIGEST = "<guard-structure>"',
        source,
    )
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _decode_static_literal(literal: str) -> str:
    value = literal[1:-1]

    def replace_escape(match: re.Match[str]) -> str:
        escape = match.group(0)
        if escape[1] in {"x", "u", "U"}:
            return chr(int(f"0x{escape[2:]}", 0))
        return _STATIC_ESCAPE_REPLACEMENTS[escape]

    return _STATIC_ESCAPE_PATTERN.sub(replace_escape, value)


def _static_literal_contains_restricted_identifier(source: str) -> bool:
    return any(
        _is_restricted_identifier_chain(_decode_static_literal(literal))
        for literal in re.findall(_STATIC_LITERAL_PATTERN, source)
    )


def _python_static_strings(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
        return (node.value.decode("utf-8", errors="ignore"),)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return tuple(left + right for left in _python_static_strings(node.left) for right in _python_static_strings(node.right))
    if isinstance(node, ast.JoinedStr):
        parts = [_python_static_strings(value) for value in node.values]
        if any(len(part) != 1 for part in parts):
            return ()
        return ("".join(part[0] for part in parts),)
    return ()


def _python_source_contains_restricted_identifier(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        _is_restricted_identifier_chain(value)
        for node in ast.walk(tree)
        for value in _python_static_strings(node)
    )


def _static_literal_chain_contains_restricted_identifier(source: str) -> bool:
    chains = re.finditer(
        rf"(?:{_STATIC_LITERAL_PATTERN})(?:(?:\s*\+\s*|\s+)(?:{_STATIC_LITERAL_PATTERN}))+",
        source,
        flags=re.DOTALL,
    )
    return any(
        _is_restricted_identifier_chain(
            "".join(_decode_static_literal(literal) for literal in re.findall(_STATIC_LITERAL_PATTERN, chain.group(0)))
        )
        for chain in chains
    )


def test_timesfm_guard_detects_static_concatenated_identifier() -> None:
    assert _contains_restricted_identifier('const restricted = "times" + "fm";')
    assert _contains_restricted_identifier('restricted = "times" "fm"')
    assert _contains_restricted_identifier('const restricted = "times-fm";')
    assert _contains_restricted_identifier('const restricted = "times_fm";')
    assert _contains_restricted_identifier('const restricted = "times fm";')
    assert not _contains_restricted_identifier("datetime.strptime(s, fmt).timestamp()")
    assert _python_source_contains_restricted_identifier('restricted = ("times" +\n"fm")')
    assert _python_source_contains_restricted_identifier('restricted = f"times\\x66m"')
    assert _python_source_contains_restricted_identifier('restricted = b"times\\x66m"')
    assert _static_literal_chain_contains_restricted_identifier('const restricted = "times" +\n "fm";')
    assert _static_literal_contains_restricted_identifier(r'const restricted = "\x74imes\x66m";')
    assert _contains_restricted_identifier("from times_fm3 import Times_FM3_Forecaster")
    assert _contains_restricted_identifier("class Times_FM3_Adapter:")
    assert _contains_restricted_identifier("times_fm3_worker = object()")
    assert _contains_restricted_identifier("class Times_FM3Forecaster:")
    assert _contains_restricted_identifier("from times.fm3 import Forecaster")
    assert _contains_restricted_identifier("times___fm3_worker = object()")
    assert _contains_restricted_identifier("class GoogleTimesFM3Forecaster:")
    assert _contains_restricted_identifier("googleTimes_FM3Worker = object()")
    assert _contains_restricted_identifier("from googleTimes.FM3 import Forecaster")
    assert _contains_restricted_identifier('restricted = "times" + "fm"')
    assert _contains_restricted_identifier('restricted = "times" "fm"')
    assert not _contains_restricted_identifier("for times, fm in measurements:")
    assert not _contains_restricted_identifier('("times", "fm")')
    assert not _contains_restricted_identifier("time_series_timestamp = object()")


def test_timesfm_policy_preserves_licence_and_conservative_policy_attribution() -> None:
    policy = TIMESFM_3_RESTRICTION_POLICY

    assert policy.rights.model_distribution is PermissionState.DENIED
    assert policy.rights.derivative_distribution is PermissionState.DENIED
    assert policy.rights.commercial_use is PermissionState.DENIED
    assert policy.rights.production_use is PermissionState.DENIED
    assert policy.rights.output_use is PermissionState.UNKNOWN
    assert policy.rights.retention is PermissionState.UNKNOWN
    assert policy.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH
    assert tuple(grant.basis for grant in policy.grants) == (
        RightsBasis.LICENCE,
        RightsBasis.FLINTTRADE_POLICY,
    )
    licence_grant = policy.grants[0]
    assert licence_grant.model_identity is not None
    assert licence_grant.model_identity.model_id == "google/timesfm-3.0-pytorch"
    assert licence_grant.model_identity.revision == "43046b85ec22d584a13f8098c2ed39c889e129c2"
    assert licence_grant.model_identity.sha256 == "a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da"
    assert licence_grant.evidence[0].sha256 == "3e36db7240d23adb6ac6d7d931892dcc5706a14a7d31581f08c35d2f25736dfd"
    assert policy.grants[1].evidence == ()


def test_timesfm_policy_cannot_be_widened_by_a_caller_claim() -> None:
    caller_claim = RightsGrant(
        grant_id="grant:caller-claim",
        basis=RightsBasis.ENTITLEMENT,
        rights=UsageRights(
            model_distribution=PermissionState.ALLOWED,
            derivative_distribution=PermissionState.ALLOWED,
            commercial_use=PermissionState.ALLOWED,
            production_use=PermissionState.ALLOWED,
            max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
        ),
        evidence=(
            _fact(
                RightsBasis.ENTITLEMENT,
                identifier="google/timesfm-3.0-pytorch",
                subject_kind="model_entitlement",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:google-timesfm",
            model_id="google/timesfm-3.0-pytorch",
            revision="43046b85ec22d584a13f8098c2ed39c889e129c2",
            sha256="a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da",
        ),
    )

    effective = intersect_rights(TIMESFM_3_RESTRICTION_POLICY, caller_claim)

    assert effective.rights.model_distribution is PermissionState.DENIED
    assert effective.rights.derivative_distribution is PermissionState.DENIED
    assert effective.rights.commercial_use is PermissionState.DENIED
    assert effective.rights.production_use is PermissionState.DENIED
    assert effective.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH


def test_timesfm_identity_mismatch_remains_isolated_research() -> None:
    mismatched_worker_claim = RightsGrant(
        grant_id="grant:worker-claim",
        basis=RightsBasis.PROVIDER_TERMS,
        rights=UsageRights(
            model_distribution=PermissionState.ALLOWED,
            derivative_distribution=PermissionState.ALLOWED,
            commercial_use=PermissionState.ALLOWED,
            production_use=PermissionState.ALLOWED,
            max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION,
        ),
        evidence=(
            _fact(
                RightsBasis.PROVIDER_TERMS,
                identifier="fixture/model",
                subject_kind="model_terms",
            ),
        ),
        model_identity=ModelIdentity(
            provider_id="forecast:fixture",
            model_id="fixture/model",
            revision="revision-1",
            sha256="c" * 64,
        ),
    )

    effective = intersect_rights(TIMESFM_3_RESTRICTION_POLICY, mismatched_worker_claim)

    assert effective.rights.model_distribution is PermissionState.DENIED
    assert effective.rights.derivative_distribution is PermissionState.DENIED
    assert effective.rights.commercial_use is PermissionState.DENIED
    assert effective.rights.production_use is PermissionState.DENIED
    assert effective.rights.max_evidence_use_scope is EvidenceUseScope.ISOLATED_RESEARCH
    assert mismatched_worker_claim in effective.grants


def test_timesfm_has_no_runtime_artifact_or_dependency() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    tracked_files = subprocess.run(
        ("git", "ls-files"),
        cwd=repository_root,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.splitlines()
    allowed_timesfm_files = {
        "packages/core/core/src/flinttrade_core/model_rights_policies.py",
        "packages/core/core/tests/test_timesfm_distribution_boundary.py",
    }
    path_matches = {
        path for path in tracked_files if "timesfm" in re.sub(r"[^a-z0-9]+", "", path.lower())
    }
    content_matches: set[str] = set()
    for path in tracked_files:
        content = (repository_root / path).read_bytes()
        text = content.decode("utf-8", errors="ignore")
        if (
            b"timesfm" in content.lower()
            or _contains_restricted_identifier(text)
            or (path.endswith(".py") and _python_source_contains_restricted_identifier(text))
        ):
            content_matches.add(path)

    assert path_matches <= allowed_timesfm_files
    assert content_matches == allowed_timesfm_files
    blocked_artifact_suffixes = {
        ".adapter",
        ".bin",
        ".bin.index.json",
        ".ckpt",
        ".diff",
        ".dat",
        ".gguf",
        ".ggml",
        ".h5",
        ".hdf5",
        ".joblib",
        ".keras",
        ".lora",
        ".mlmodel",
        ".model",
        ".npy",
        ".npz",
        ".onnx",
        ".pb",
        ".pkl",
        ".pickle",
        ".pt",
        ".pth",
        ".safetensors",
        ".safetensors.index.json",
        ".tar",
        ".tar.bz2",
        ".tar.gz",
        ".tar.xz",
        ".tflite",
        ".torchscript",
        ".weights",
        ".fp16",
        ".fp32",
        ".q4_0",
        ".q4_1",
        ".q4_k_m",
        ".q4_k_s",
        ".q5_k_m",
        ".q5_k_s",
        ".q6_k",
        ".q8_0",
        ".q8_1",
        ".q3_k_s",
        ".q2_k",
        ".tar.zst",
        ".tgz",
        ".zip",
    }
    assert not {
        path
        for path in tracked_files
        if any(path.lower().endswith(suffix) for suffix in blocked_artifact_suffixes)
    }


def test_neutral_catalogue_modules_import_no_provider_runtime_packages() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core"
    prohibited_prefixes = ("flinttrade_gateway", "flinttrade_historical", "flinttrade_ai")

    for module_name in ("service_providers.py", "model_rights_policies.py"):
        tree = ast.parse((source_root / module_name).read_text(encoding="utf-8"))
        from_imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        direct_imports = [
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        ]
        assert all(not imported.startswith(prohibited_prefixes) for imported in from_imports + direct_imports)


def test_timesfm_allowlisted_policy_module_is_structurally_inert() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core"
    policy_tree = ast.parse((source_root / "model_rights_policies.py").read_text(encoding="utf-8"))
    policy_direct_imports = [
        alias.name for node in ast.walk(policy_tree) if isinstance(node, ast.Import) for alias in node.names
    ]
    assert _has_only_policy_contract_import(policy_tree)
    assert policy_direct_imports == []
    assert [alias.name for alias in policy_tree.body[1].names] == [
        "EvidenceUseScope",
        "LicenceFact",
        "ModelIdentity",
        "PermissionState",
        "RightsBasis",
        "RightsGrant",
        "RightsResolution",
        "UsageRights",
        "intersect_rights",
    ]
    assignments = [node for node in policy_tree.body[2:] if isinstance(node, (ast.Assign, ast.AnnAssign))]
    assert all(_assignment_targets(node) for node in assignments)
    assert [target.id for node in assignments for target in _assignment_targets(node)] == [
        "_TIMESFM_3_MODEL_IDENTITY",
        "TIMESFM_3_RESTRICTION_POLICY",
    ]
    policy_calls = [node for node in ast.walk(policy_tree) if isinstance(node, ast.Call)]
    assert all(isinstance(node.func, ast.Name) for node in policy_calls)
    assert {node.func.id for node in policy_calls if isinstance(node.func, ast.Name)} == {
        "LicenceFact",
        "ModelIdentity",
        "RightsGrant",
        "UsageRights",
        "intersect_rights",
    }
    policy_attributes = [node for node in ast.walk(policy_tree) if isinstance(node, ast.Attribute)]
    assert all(isinstance(node.value, ast.Name) for node in policy_attributes)
    assert {
        f"{node.value.id}.{node.attr}"
        for node in policy_attributes
        if isinstance(node.value, ast.Name)
    } == {
        "EvidenceUseScope.ISOLATED_RESEARCH",
        "PermissionState.DENIED",
        "RightsBasis.FLINTTRADE_POLICY",
        "RightsBasis.LICENCE",
    }
    assert all(isinstance(node.value, str) for node in ast.walk(policy_tree) if isinstance(node, ast.Constant))
    assert all(isinstance(node, ast.Tuple) for node in ast.walk(policy_tree) if isinstance(node, (ast.List, ast.Set, ast.Dict, ast.Tuple)))
    allowed_node_types = {
        ast.Module,
        ast.Expr,
        ast.Constant,
        ast.ImportFrom,
        ast.alias,
        ast.Assign,
        ast.AnnAssign,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Call,
        ast.keyword,
        ast.Attribute,
        ast.Tuple,
    }
    assert {type(node) for node in ast.walk(policy_tree)} <= allowed_node_types


def test_timesfm_policy_guard_rejects_relative_runtime_import_mutation() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core"
    policy_source = (source_root / "model_rights_policies.py").read_text(encoding="utf-8")
    mutated_source = re.sub(
        r"from flinttrade_core\.service_providers import \(\n(?:    .+\n)+\)\n",
        "from . import ollama_runtime\n",
        policy_source,
    )
    mutated_tree = ast.parse(mutated_source)

    assert not _has_only_policy_contract_import(mutated_tree)


def _has_only_policy_contract_import(tree: ast.AST) -> bool:
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    expected_names = (
        "EvidenceUseScope",
        "LicenceFact",
        "ModelIdentity",
        "PermissionState",
        "RightsBasis",
        "RightsGrant",
        "RightsResolution",
        "UsageRights",
        "intersect_rights",
    )
    return (
        len(imports) == 1
        and imports[0].level == 0
        and imports[0].module == "flinttrade_core.service_providers"
        and tuple((alias.name, alias.asname) for alias in imports[0].names) == tuple((name, None) for name in expected_names)
    )


def _assignment_targets(node: ast.stmt) -> tuple[ast.Name, ...]:
    if isinstance(node, ast.Assign):
        return tuple(target for target in node.targets if isinstance(target, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return (node.target,)
    return ()


def test_timesfm_guard_file_has_only_its_scanning_exception() -> None:
    guard_source = Path(__file__).read_text(encoding="utf-8")
    guard_tree = ast.parse(guard_source)
    guard_direct_imports = [alias.name for node in ast.walk(guard_tree) if isinstance(node, ast.Import) for alias in node.names]
    guard_from_imports = [
        node.module
        for node in ast.walk(guard_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    subprocess_attributes = [
        node
        for node in ast.walk(guard_tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "subprocess"
    ]
    subprocess_calls = [
        node
        for node in ast.walk(guard_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]
    guard_top_level_functions = [node.name for node in guard_tree.body if isinstance(node, ast.FunctionDef)]

    assert guard_direct_imports == ["ast", "hashlib", "re", "subprocess"]
    assert set(guard_from_imports) == {"pathlib", "flinttrade_core.model_rights_policies", "flinttrade_core.service_providers"}
    assert all(node.attr == "run" for node in subprocess_attributes)
    assert len(subprocess_calls) == 1
    assert isinstance(subprocess_calls[0].args[0], ast.Tuple)
    assert [item.value for item in subprocess_calls[0].args[0].elts if isinstance(item, ast.Constant)] == ["git", "ls-files"]
    assert guard_top_level_functions == [
        "_fact",
        "_contains_restricted_identifier",
        "_is_restricted_identifier_chain",
        "_guard_file_structure_digest",
        "_decode_static_literal",
        "_static_literal_contains_restricted_identifier",
        "_python_static_strings",
        "_python_source_contains_restricted_identifier",
        "_static_literal_chain_contains_restricted_identifier",
        "test_timesfm_guard_detects_static_concatenated_identifier",
        "test_timesfm_policy_preserves_licence_and_conservative_policy_attribution",
        "test_timesfm_policy_cannot_be_widened_by_a_caller_claim",
        "test_timesfm_identity_mismatch_remains_isolated_research",
        "test_timesfm_has_no_runtime_artifact_or_dependency",
        "test_neutral_catalogue_modules_import_no_provider_runtime_packages",
        "test_timesfm_allowlisted_policy_module_is_structurally_inert",
        "test_timesfm_policy_guard_rejects_relative_runtime_import_mutation",
        "_has_only_policy_contract_import",
        "_assignment_targets",
        "test_timesfm_guard_file_has_only_its_scanning_exception",
        "test_timesfm_guard_structure_rejects_runtime_mutations",
    ]
    assert not [
        node for node in ast.walk(guard_tree) if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
    ]
    assert not [
        node
        for node in ast.walk(guard_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"__import__", "compile", "eval", "exec"}
    ]
    assert _guard_file_structure_digest(guard_source) == _GUARD_STRUCTURE_DIGEST


def test_timesfm_guard_structure_rejects_runtime_mutations() -> None:
    guard_source = Path(__file__).read_text(encoding="utf-8")
    mutation_suffixes = (
        "\nrunner = subprocess.run\nrunner((\"git\", \"status\"))\n",
        "\nsubprocess.Popen((\"curl\", \"https://example.invalid\"))\n",
        "\nclass DownloadWorker:\n    pass\n",
        "\nrunner = lambda: None\nrunner()\n",
        "\n__import__(\"socket\")\n",
        "\neval(\"1 + 1\")\n",
        "\nexec(\"import socket\")\n",
        "\ncompile(\"pass\", \"<guard>\", \"exec\")\n",
    )
    mutated_sources = tuple(guard_source + suffix for suffix in mutation_suffixes) + (
        guard_source.replace(
            "    return LicenceFact(\n",
            "    subprocess.Popen((\"curl\", \"https://example.invalid\"))\n    return LicenceFact(\n",
            1,
        ),
    )

    assert all(_guard_file_structure_digest(source) != _GUARD_STRUCTURE_DIGEST for source in mutated_sources)
