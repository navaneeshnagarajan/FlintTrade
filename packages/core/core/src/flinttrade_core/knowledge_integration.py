"""App-owned knowledge composition; no credential or provider work at boot."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
from flinttrade_core.service_providers import (
    LicenceFact,
    PermissionState,
    RightsBasis,
    RightsGrant,
    RightsResolution,
    UsageRights,
    intersect_rights,
)
from flinttrade_core.source_root import discover_source_root


class KnowledgeUnavailable(RuntimeError):
    """The durable knowledge owner cannot safely serve this request."""


def bundled_procedure_rights() -> RightsResolution:
    """Resolve use/retention of bundled procedures, not model/data-training rights."""
    root = discover_source_root(module_file=__file__)
    source = (root / "LICENSE").read_bytes()
    if b"GNU AFFERO GENERAL PUBLIC LICENSE" not in source or b"Version 3" not in source:
        raise KnowledgeUnavailable("bundled licence unavailable")
    digest = hashlib.sha256(source).hexdigest()
    return intersect_rights(RightsGrant(
        "bundled-procedure-use:" + digest, RightsBasis.LICENCE,
        UsageRights(output_use=PermissionState.ALLOWED, retention=PermissionState.ALLOWED,
                    restrictions=("AGPL-3.0 conditions apply; no private-data or model-training grant.",)),
        (LicenceFact("flinttrade-source-licence", "document", "bundled-procedures", "repo:LICENSE",
                     "AGPL-3.0:sha256:" + digest, digest, "2026-10-10", RightsBasis.LICENCE),),
    ))


def require_knowledge_runtime(app: Any) -> KnowledgeRuntime:
    """Return the existing owner or fail unavailable, never construct a fallback."""
    owner = app.config.get("KNOWLEDGE_RUNTIME")
    if not isinstance(owner, KnowledgeRuntime):
        raise KnowledgeUnavailable("knowledge unavailable")
    return owner


def get_learning_consent_ledger(app: Any) -> Any:
    """Lazily share the *real* dispatcher's usage owner, never a second ledger."""
    from flinttrade_core import service_task_routes
    from flinttrade_core.learning_consent import LearningConsentLedger

    with app.config["KNOWLEDGE_OWNER_LOCK"]:
        owner = app.config.get("LEARNING_CONSENT_LEDGER")
        if owner is not None:
            return owner
        if app.config.get("LEARNING_CONSENT_UNAVAILABLE"):
            raise KnowledgeUnavailable("learning consent unavailable")
        try:
            with app.app_context():
                dispatcher = service_task_routes.get_service_task_dispatcher()
            owner = LearningConsentLedger(app.config["KNOWLEDGE_WORKSPACE"] / "learning-consent",
                                          usage=dispatcher.ledger, clock=dispatcher.clock)
        except Exception:
            app.config["LEARNING_CONSENT_UNAVAILABLE"] = True
            raise KnowledgeUnavailable("learning consent unavailable") from None
        app.config["LEARNING_CONSENT_LEDGER"] = owner
        return owner


def install_knowledge_runtime(app: Any, workspace: Path) -> None:
    """Install one durable runtime, task resolver and authenticated control plane.

    The parent closes KNOWLEDGE_RUNTIME and LEARNING_CONSENT_LEDGER only after
    consumers drain, then SERVICE_TASK_DISPATCHER. The latter two remain lazy.
    """
    if app.config.get("KNOWLEDGE_INSTALLED"):
        return
    from flinttrade_core.knowledge_routes import install_knowledge_routes
    from flinttrade_core.knowledge_task_context import KnowledgeTaskContextResolver

    app.config["KNOWLEDGE_WORKSPACE"] = Path(workspace)
    app.config["KNOWLEDGE_OWNER_LOCK"] = threading.RLock()
    try:
        owner = KnowledgeRuntime(Path(workspace), stock_rights=bundled_procedure_rights())
    except Exception:
        owner = None
    app.config["KNOWLEDGE_RUNTIME"] = owner
    app.config["SKILL_REGISTRY"] = owner.registry if owner is not None else None
    app.config["KNOWLEDGE_STATUS"] = "available" if owner is not None else "unavailable"
    resolver = KnowledgeTaskContextResolver(app)
    from flinttrade_core.agent_routes import authorised_knowledge_scope
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: authorised_knowledge_scope(app, actor)
    app.config["SERVICE_TASK_CONTEXT_RESOLVER"] = resolver
    dispatcher = app.config.get("SERVICE_TASK_DISPATCHER")
    if dispatcher is not None:
        dispatcher.context_resolver = resolver
    install_knowledge_routes(app)
    app.config["KNOWLEDGE_INSTALLED"] = True
