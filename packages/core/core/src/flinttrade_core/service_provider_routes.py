"""Authenticated read-only service-provider catalogue routes."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify

from .auth_scopes import require_scope
from .service_providers import ServiceProviderCatalogue

service_provider_bp = Blueprint("service_providers", __name__, url_prefix="/v1/services")


@service_provider_bp.get("/providers")
@require_scope("admin.observability.read")
def list_service_providers() -> tuple[Response, int]:
    """Return the static, non-invoking service-provider catalogue."""
    catalogue = current_app.config.get("SERVICE_PROVIDER_CATALOGUE")
    if not isinstance(catalogue, ServiceProviderCatalogue):
        return jsonify({"status": "error", "message": "Service provider catalogue unavailable"}), 503
    return jsonify({"status": "success", "data": catalogue.to_public_payload()}), 200
