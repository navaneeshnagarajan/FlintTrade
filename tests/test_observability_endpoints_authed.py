"""Gate-11 (observability §16.3): every admin audit/activity route enforces @require_scope.

The audit + activity view functions must carry the ``__required_scope__`` marker that
``require_scope`` sets, so a scope-limited session cannot reach them (closing the hole
where any caller holding the shared API key could export the full audit log).
"""

from __future__ import annotations

from flinttrade_core import operations_routes
from flinttrade_data import activity_routes, audit_routes


def _scope(fn):
    return getattr(fn, "__required_scope__", None)


def test_audit_log_route_requires_audit_read():
    assert _scope(audit_routes.audit_log) == "admin.audit.read"


def test_audit_export_route_requires_audit_read():
    # The hole the audit flagged: /v1/audit/export with zero scope check. Now gated.
    assert _scope(audit_routes.audit_export) == "admin.audit.read"


def test_audit_stats_route_requires_audit_read():
    assert _scope(audit_routes.audit_stats) == "admin.audit.read"


def test_activity_route_requires_activity_scope():
    assert _scope(activity_routes.get_activity) == "admin.activity"


def test_operations_audit_logs_requires_audit_read():
    assert _scope(operations_routes.audit_logs) == "admin.audit.read"
