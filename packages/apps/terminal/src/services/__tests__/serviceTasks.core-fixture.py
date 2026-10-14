"""Generate real normal-factory task DTOs for the TS/React contract regression.

Only run inside the authorised disposable runtime. The sole provider boundary
is an httpx.MockTransport; auth, configuration and durable readers are real.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import httpx

from flinttrade_core.app import _close_runtime_request_admission, create_flask_app
from flinttrade_core.auth_routes import _create_token
from flinttrade_core.service_usage_contracts import canonical
from packages.core.core.tests import test_service_tasks as helpers


def main() -> None:
    target = Path(sys.argv[1])
    assert str(Path.home()) == "/run/test/home", "Isolated HOME required"
    workspace = target.parent / "workspace"
    workspace.mkdir(mode=0o700)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
    os.environ["FLINTTRADE_API_KEY"] = secrets.token_urlsafe(32)
    master = workspace / "master_password"
    master.write_text(secrets.token_urlsafe(48))
    master.chmod(0o600)
    app = create_flask_app()
    calls = []
    output = ""

    def transport(request):
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        wire = json.loads(request.content)
        assert wire["provider"]["allow_fallbacks"] is False
        assert wire["max_tokens"] == 256
        assert "tools" not in wire
        calls.append(wire)
        return httpx.Response(200, json={"id": "synthetic-inert", "model": "test-model-v1",
            "choices": [{"message": {"content": output}, "finish_reason": "stop"}],
            "provider": "approved-upstream", "usage": {"prompt_tokens": 12, "completion_tokens": 5}})

    try:
        assert not app.config["BACKEND_LEASE_READY"]
        app.config["AUTH_SERVICE"].setup_account("synthetic-r25", "r25@example.invalid", secrets.token_urlsafe(32))
        with app.app_context():
            headers = {"Authorization": "Bearer " + _create_token("synthetic-r25")}
        app.config.update(SERVICE_TASK_TRANSPORT=httpx.MockTransport(transport), SERVICE_TASK_CLOCK=lambda: helpers.NOW)
        client = app.test_client()
        base = helpers.BASE
        revision = client.get(base, headers=headers).headers["ETag"]
        created = client.post(base, headers={**headers, "If-Match": revision, "Idempotency-Key": str(uuid4())},
            json={"provider_id": "llm:openrouter", "model": "test-model-v1", "label": "Synthetic R25",
                  "auth_mode": "api_key", "credential": secrets.token_urlsafe(32)})
        assert created.status_code == 201, created.json
        identifier = created.json["connection_id"]
        admission = helpers.policy(created.headers["ETag"])
        admission["reservation"].update(input_tokens=8192, currency_micros=1000)
        group = client.put(base + "/quota-groups/synthetic-shared-account", headers={**headers, "If-Match": '"0"'}, json=admission["budget"])
        assert group.status_code == 200, group.json
        configured = client.put(base + f"/{identifier}/admission", headers={**headers, "If-Match": '"0"'}, json=admission)
        assert configured.status_code == 200, configured.json
        connections = client.get(base, headers=headers)
        catalogue = client.get("/v1/knowledge/skills", headers=headers)
        procedure = client.get("/v1/knowledge/skills/risk_management", headers=headers)
        assert connections.status_code == catalogue.status_code == procedure.status_code == 200
        cases = []
        for output in ("Inert normal-core answer", 'Quotes " and \\ and /\n\r\t\b\f\x00\x1f', "नमस्ते 中文 🚦\u2028\u2029\x7f\x80", ""):
            task = helpers.task(identifier, connections.headers["ETag"], context_refs=["skill:risk_management"])
            sent = client.post(base + "/tasks", headers=headers, json=task)
            durable = client.get(base + "/tasks/" + task["request_id"], headers=headers)
            assert sent.status_code == durable.status_code == 200
            assert sent.json["outcome"] == "completed", sent.json
            assert sent.json["output"] == output
            assert "output" not in durable.json
            expected = hashlib.sha256(canonical(output).encode()).hexdigest()
            assert durable.json["output_digest"] == expected == sent.json["output_digest"]
            assert durable.json == {key: value for key, value in sent.json.items() if key != "output"}
            # The real HTTP GET reads this actor's digest-only durable owner.
            assert "output" not in durable.json
            cases.append({"task": task, "post": sent.json, "get": durable.json})
        assert len(calls) == len(cases)
        target.write_text(json.dumps({"cases": cases, "connections": connections.json,
            "etag": connections.headers["ETag"], "catalogue": catalogue.json, "procedure": procedure.json,
            "provider_calls": len(calls), "task_posts": len(cases), "task_gets": len(cases)}, ensure_ascii=True))
    finally:
        tracker = _close_runtime_request_admission(app)
        assert tracker.wait_for_idle(timeout=10)
        for key in ("EXECUTION_SESSION_MANAGER", "MODEL_RUN_SERVICES", "DATA_RUNTIME", "LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME", "SERVICE_TASK_DISPATCHER"):
            owner = app.config.get(key)
            if owner is not None:
                assert owner.close() is not False


if __name__ == "__main__":
    main()
