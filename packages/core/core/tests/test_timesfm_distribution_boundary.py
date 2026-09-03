import ast
from pathlib import Path
import subprocess

from flinttrade_core.model_rights_policies import TIMESFM_3_RESTRICTION_POLICY
from flinttrade_core.service_providers import (
    EvidenceUseScope,
    ModelIdentity,
    PermissionState,
    RightsBasis,
    RightsGrant,
    UsageRights,
    intersect_rights,
)


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
    relevant_suffixes = {
        ".bat",
        ".bin",
        ".cjs",
        ".ckpt",
        ".cmd",
        ".conf",
        ".config",
        ".gguf",
        ".h5",
        ".ini",
        ".js",
        ".json",
        ".jsonc",
        ".lock",
        ".mjs",
        ".onnx",
        ".ps1",
        ".pt",
        ".pth",
        ".pkl",
        ".pickle",
        ".py",
        ".pyi",
        ".rs",
        ".safetensors",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".yml",
        ".yaml",
        ".zip",
    }
    relevant_names = {"Dockerfile", "Makefile", "Pipfile", "poetry.lock", "requirements.txt", "uv.lock"}
    relevant_files = [
        path
        for path in tracked_files
        if Path(path).suffix in relevant_suffixes
        or Path(path).name in relevant_names
        or path.startswith(("scripts/", "presets/", "config/", "configs/"))
    ]
    path_matches = sorted(path for path in relevant_files if "timesfm" in path.lower())
    content_matches = sorted(
        path
        for path in relevant_files
        if "timesfm" in (repository_root / path).read_text(encoding="utf-8", errors="ignore").lower()
    )

    assert path_matches == ["packages/core/core/tests/test_timesfm_distribution_boundary.py"]
    assert content_matches == [
        "packages/core/core/src/flinttrade_core/model_rights_policies.py",
        "packages/core/core/tests/test_timesfm_distribution_boundary.py",
    ]
    blocked_weight_suffixes = {
        ".bin",
        ".ckpt",
        ".gguf",
        ".h5",
        ".onnx",
        ".pkl",
        ".pickle",
        ".pt",
        ".pth",
        ".safetensors",
    }
    assert all(Path(path).suffix not in blocked_weight_suffixes for path in path_matches)


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
