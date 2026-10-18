"""Native provider wire contracts, not universal effort conversions.

Protocols never discover credentials, rotate identities, execute tools or retry.
Qualification remains model/auth/revision specific in the caller.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .service_connections import ServiceConnection
from .service_task_contracts import TaskRefused
from .service_usage_contracts import UsageAmounts, integer, text


def validate_protocol(connection: ServiceConnection, policy: dict[str, Any]) -> None:
    """Validate the qualified subset against actual native protocol constraints."""
    protocol = policy["protocol"]
    family = {
        "openrouter_chat": "llm:openrouter",
        "anthropic_messages": "llm:anthropic",
        "openai_decisions": "llm:openai",
        "openai_responses": "llm:openai",
        "chatgpt_responses": "llm:openai",
        "xai_responses": "llm:grok",
        "unsloth_chat": "llm:custom",
    }
    if protocol not in family or connection.provider_id != family[protocol]:
        raise TaskRefused("unsupported_protocol", 422)
    auth = "chatgpt_oauth" if protocol == "chatgpt_responses" else "api_key"
    if connection.auth_mode != auth:
        raise TaskRefused("unsupported_auth", 422)
    expected_role = "task_router" if protocol == "openai_decisions" else "assistant"
    if policy["role"] != expected_role:
        raise TaskRefused("unsupported_role", 422)
    if type(policy["efforts"]) is not dict or not policy["efforts"]:
        raise ValueError("effort profiles required")
    for name, native in policy["efforts"].items():
        text(name, "effort name")
        if type(native) is not dict:
            raise ValueError("native effort object required")
        if name == "not_applicable" and native == {}:
            continue
        if protocol in {"openrouter_chat", "openai_responses", "chatgpt_responses", "xai_responses"}:
            if (
                set(native) != {"reasoning"}
                or type(native["reasoning"]) is not dict
                or set(native["reasoning"]) != {"effort"}
            ):
                raise ValueError("invalid OpenRouter effort")
            if native["reasoning"]["effort"] not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
                raise ValueError("unsupported native effort")
        elif protocol == "unsloth_chat":
            if set(native) != {"reasoning_effort"} or native["reasoning_effort"] not in {"low", "medium", "high"}:
                raise ValueError("unsupported Unsloth effort")
        elif protocol == "anthropic_messages":
            if set(native) != {"thinking"} or type(native["thinking"]) is not dict:
                raise ValueError("invalid Messages thinking")
            thinking = native["thinking"]
            if set(thinking) != {"type", "budget_tokens"} or thinking["type"] != "enabled":
                raise ValueError("invalid Messages thinking budget")
            integer(thinking["budget_tokens"], "thinking budget", minimum=1024)
        else:
            raise ValueError("decisions has no effort control")
    supported = {"output_tokens"}
    if protocol in {"openai_decisions", "chatgpt_responses"}:
        supported = set()
    elif protocol == "xai_responses":
        supported = {"visible_output_tokens"}
    if type(policy["hard_controls"]) is not list or set(policy["hard_controls"]) - supported:
        raise ValueError("unsupported hard control")
    if protocol == "openrouter_chat":
        text(policy["downstream"], "approved downstream")
    elif policy["downstream"] is not None:
        raise ValueError("direct protocol has no downstream routing")


def build_request(
    connection: ServiceConnection,
    policy: dict[str, Any],
    task: dict[str, Any],
    effort: str,
    credential: str,
    candidates: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build exact headers/URL/native controls from a core-owned snapshot only."""
    native = policy["efforts"][effort]
    protocol = policy["protocol"]
    if connection.endpoint is None:
        raise TaskRefused("unsupported_protocol", 422)
    headers = {"Content-Type": "application/json"}
    if protocol == "anthropic_messages":
        headers.update({"x-api-key": credential, "anthropic-version": "2023-06-01"})
        if native and native["thinking"]["budget_tokens"] >= task["max_output_tokens"]:
            raise TaskRefused("effort_budget_unsupported", 422)
        return (
            connection.endpoint,
            headers,
            {
                "model": connection.model,
                "messages": [{"role": "user", "content": task["prompt"]}],
                "stream": False,
                "max_tokens": task["max_output_tokens"],
                **native,
            },
        )
    headers["Authorization"] = "Bearer " + credential
    if protocol == "unsloth_chat":
        return (
            connection.endpoint.rstrip("/") + "/v1/chat/completions",
            headers,
            {
                "model": connection.model,
                "messages": [{"role": "user", "content": task["prompt"]}],
                "max_tokens": task["max_output_tokens"],
                "stream": False,
                "tool_choice": "none",
                **native,
            },
        )
    if protocol in {"openai_responses", "chatgpt_responses", "xai_responses"}:
        body = {
            "model": connection.model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": task["prompt"]}]}],
            "store": False,
            "stream": protocol == "chatgpt_responses",
            **native,
        }
        if protocol != "chatgpt_responses":
            body["max_output_tokens"] = task["max_output_tokens"]
        origin = "https://api.x.ai" if protocol == "xai_responses" else "https://api.openai.com"
        return origin + "/v1/responses", headers, body
    if protocol == "openai_decisions":
        if not candidates:
            raise TaskRefused("eligible_pool_empty")
        projection = {
            "purpose": "assistant",
            "classification": task["classification"],
            "candidates": [{"id": key, "effort": row["effort"]} for key, row in candidates.items()],
        }
        return (
            "https://api.openai.com/v1/decisions",
            headers,
            {
                "model": connection.model,
                "input": json.dumps(projection, sort_keys=True),
                "questions": [
                    {
                        "name": "route",
                        "type": "choice",
                        "instructions": "Select one eligible opaque task profile, or abstain. No tools or configuration changes.",
                        "choices": [{"value": key} for key in candidates] + [{"value": "abstain"}],
                    }
                ],
            },
        )
    return (
        connection.endpoint,
        headers,
        {
            "model": connection.model,
            "messages": [{"role": "user", "content": task["prompt"]}],
            "stream": False,
            "max_tokens": task["max_output_tokens"],
            **native,
            "provider": {
                "only": [policy["downstream"]],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": policy["privacy"]["retention"] == "zdr",
            },
        },
    )


def decode_response(raw: bytes, protocol: str) -> dict[str, Any]:
    """Decode JSON or subscription SSE without treating partial output as complete."""
    if protocol != "chatgpt_responses":
        return json.loads(raw)
    completed = None
    for block in raw.decode("utf-8").replace("\r\n", "\n").split("\n\n"):
        lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
        if not lines:
            continue
        event = json.loads("\n".join(lines))
        if type(event) is not dict:
            raise TaskRefused("provider_contract_error", 502)
        if event.get("type") == "response.completed":
            if completed is not None:
                raise TaskRefused("provider_contract_error", 502)
            completed = event["response"]
        elif event.get("type") in {"error", "response.failed", "response.incomplete"}:
            raise TaskRefused("provider_outcome_unknown", 502)
    if completed is None:
        raise TaskRefused("provider_outcome_unknown", 502)
    return completed


def parse_result(
    data: dict[str, Any], policy: dict[str, Any], *, candidates: dict[str, Any] | None = None
) -> tuple[str, UsageAmounts, dict[str, Any]]:
    """Validate identity/terminal shape; preserve decision evidence semantics."""
    if type(data) is not dict or data.get("model") != policy["model_revision"]:
        raise TaskRefused("provider_identity_mismatch", 502)
    protocol = policy["protocol"]
    usage = data["usage"]
    evidence = {"resolved_model": data["model"], "provider_request_id": data.get("id")}
    if protocol == "openai_decisions":
        answers = data["answers"]
        if type(answers) is not list or len(answers) != 1:
            raise TaskRefused("decision_incomplete", 502)
        answer = answers[0]
        if type(answer) is not dict:
            raise TaskRefused("decision_contract_error", 502)
        if answer.get("type") == "refusal":
            raise TaskRefused("router_abstained")
        if set(answer) != {"type", "name", "choice", "probabilities", "confidence"} or (
            answer["type"],
            answer["name"],
        ) != ("choice", "route"):
            raise TaskRefused("decision_contract_error", 502)
        allowed = set(candidates or {}) | {"abstain"}
        if answer["choice"] not in allowed:
            raise TaskRefused("invented_choice", 502)
        probabilities = answer["probabilities"]
        if type(probabilities) is not list or len(probabilities) != len(allowed):
            raise TaskRefused("decision_incomplete", 502)
        seen = set()
        total = 0.0
        for row in probabilities:
            if (
                type(row) is not dict
                or set(row) != {"value", "probability"}
                or row["value"] not in allowed
                or row["value"] in seen
            ):
                raise TaskRefused("decision_contract_error", 502)
            value = row["probability"]
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise TaskRefused("decision_contract_error", 502)
            seen.add(row["value"])
            total += value
        confidence = answer["confidence"]
        if (
            abs(total - 1.0) > 1e-6
            or type(confidence) not in {int, float}
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise TaskRefused("decision_contract_error", 502)
        evidence["decision"] = answer
        # Confidence is retained as vendor evidence, never trading calibration.
        return (
            answer["choice"],
            UsageAmounts(requests=1, input_tokens=usage["input_tokens"], output_tokens=usage.get("output_tokens", 0)),
            evidence,
        )
    if protocol in {"openai_responses", "chatgpt_responses", "xai_responses"}:
        if data.get("status") != "completed" or type(data.get("output")) is not list:
            raise TaskRefused("provider_contract_error", 502)
        parts = []
        for item in data["output"]:
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message":
                raise TaskRefused("tools_unsupported", 422)
            for part in item["content"]:
                if part.get("type") != "output_text" or type(part.get("text")) is not str:
                    raise TaskRefused("provider_contract_error", 502)
                parts.append(part["text"])
        if not parts:
            raise TaskRefused("provider_contract_error", 502)
        return (
            "\n".join(parts),
            UsageAmounts(requests=1, input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"]),
            evidence,
        )
    if protocol == "anthropic_messages":
        if data["stop_reason"] not in {"end_turn", "max_tokens"} or type(data["content"]) is not list:
            raise TaskRefused("provider_contract_error", 502)
        if any(row.get("type") not in {"text", "thinking", "redacted_thinking"} for row in data["content"]):
            raise TaskRefused("tools_unsupported", 422)
        parts = [row["text"] for row in data["content"] if row["type"] == "text"]
        if not parts or any(type(part) is not str for part in parts):
            raise TaskRefused("provider_contract_error", 502)
        # Cache billing requires a qualified tariff model; never silently ignore it.
        if usage.get("cache_creation_input_tokens", 0) or usage.get("cache_read_input_tokens", 0):
            raise TaskRefused("usage_contract_unsupported", 502)
        return (
            "\n".join(parts),
            UsageAmounts(requests=1, input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"]),
            evidence,
        )
    if protocol == "openrouter_chat" and data.get("provider") != policy["downstream"]:
        raise TaskRefused("provider_identity_mismatch", 502)
    choices = data["choices"]
    if type(choices) is not list or len(choices) != 1:
        raise TaskRefused("provider_contract_error", 502)
    choice = choices[0]
    if choice["finish_reason"] not in {"stop", "length"} or type(choice["message"]["content"]) is not str:
        raise TaskRefused("provider_contract_error", 502)
    if choice["message"].get("tool_calls"):
        raise TaskRefused("tools_unsupported", 422)
    evidence["downstream"] = data.get("provider")
    return (
        choice["message"]["content"],
        UsageAmounts(requests=1, input_tokens=usage["prompt_tokens"], output_tokens=usage["completion_tokens"]),
        evidence,
    )
