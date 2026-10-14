"""Licence facts are narrowly tied to real bundled source, not data consent."""
from __future__ import annotations

import hashlib

import pytest

from flinttrade_core.knowledge_integration import bundled_procedure_rights
from flinttrade_core.service_providers import PermissionState
from flinttrade_core.source_root import discover_source_root

pytestmark = pytest.mark.unit


def test_bundled_source_rights_do_not_imply_training_or_private_data_grants():
    rights = bundled_procedure_rights()
    assert rights.rights.output_use is PermissionState.ALLOWED
    assert rights.rights.retention is PermissionState.ALLOWED
    assert rights.rights.training_distillation is PermissionState.UNKNOWN
    assert rights.rights.model_distribution is PermissionState.UNKNOWN
    fact = rights.grants[0].evidence[0]
    assert fact.source_uri == "repo:LICENSE"
    source = discover_source_root(module_file=__file__) / "LICENSE"
    assert fact.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "AGPL-3.0" in fact.revision
