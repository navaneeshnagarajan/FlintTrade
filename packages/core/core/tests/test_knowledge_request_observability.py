"""Sensitive knowledge routes are classified even before Flask hooks run."""
from __future__ import annotations

import pytest

from flinttrade_core.request_observability import (
    classify_secret_envelope, project_safe_request, sentry_event_is_secret,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("prefix", ["/v1/knowledge", "/v1/learning", "/api/v1/ai/skill-drafts"])
@pytest.mark.parametrize("suffix", ["", "/private-resource", "/unmatched/private-detail"])
def test_knowledge_families_have_fixed_pre_hook_projection(prefix, suffix):
    path = prefix + suffix
    expected = prefix + "/{resource}"
    assert classify_secret_envelope("POST", path) == expected
    summary = project_safe_request("GET", "/ft-api" + path + "?sensitive=query", 12)
    assert summary is not None
    assert summary.to_dict() == {"route_template": expected, "method": "GET",
                                 "content_length": 12, "has_credentials": True}
    assert sentry_event_is_secret({"request": {"method": "POST", "url": "http://localhost" + path}})
    assert sentry_event_is_secret({"request": {"env": {"PATH_INFO": path}}})


@pytest.mark.parametrize("path", ["/v1/knowledgeable", "/v1/learning-progress"])
def test_neighbouring_routes_keep_their_ordinary_classification(path):
    assert classify_secret_envelope("POST", path) is None
