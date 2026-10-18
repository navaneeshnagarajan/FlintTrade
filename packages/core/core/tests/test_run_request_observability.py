"""Run policy and protection metadata stay private before route hooks."""
from __future__ import annotations

import pytest

from flinttrade_core.request_observability import (
    classify_secret_envelope, project_safe_request, sentry_event_is_secret,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("prefix", ["/v1/model-runs", "/api/v1/execution-sessions", "/api/v1/protection", "/api/v1/backtest/run"])
@pytest.mark.parametrize("suffix", ["", "/private-run/configuration/confirm", "/unmatched/private-detail"])
@pytest.mark.parametrize("method", ["GET", "POST", "HEAD", "OPTIONS"])
def test_run_control_families_have_fixed_pre_hook_projection(prefix, suffix, method):
    path = prefix + suffix
    expected = prefix + "/{resource}"
    assert classify_secret_envelope(method, path) == expected
    summary = project_safe_request(method, "/ft-api" + path + "?private=query", 12)
    assert summary is not None
    assert summary.to_dict() == {"route_template": expected, "method": method,
                                 "content_length": 12, "has_credentials": True}
    assert sentry_event_is_secret({"request": {"method": method, "url": "http://localhost" + path}})
    assert sentry_event_is_secret({"request": {"env": {"PATH_INFO": "/ft-api" + path}}})


@pytest.mark.parametrize("path", ["/v1/model-runs-extra", "/api/v1/execution-sessions-old", "/api/v1/protection-summary"])
def test_adjacent_non_control_routes_keep_ordinary_observability(path):
    assert classify_secret_envelope("POST", path) is None
