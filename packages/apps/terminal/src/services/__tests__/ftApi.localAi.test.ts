import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storeState = vi.hoisted(() => ({
  apiKey: "backend-key",
  token: "session-token",
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: storeState.apiKey }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: storeState.token }) },
}));

import {
  acceptLocalAiModelDigest,
  createLocalAiAdmissionId,
  deleteLocalAiModel,
  getLocalAiStatus,
  installLocalAiRuntime,
  isLocalAiModelPullResult,
  LOCAL_AI_REQUEST_TIMEOUT_MS,
  localAiModelAliasesEquivalent,
  LocalAiApiError,
  listLocalAiModels,
  pruneLocalAiModels,
  pullLocalAiModel,
  reconcileLocalAiOperation,
  repairLocalAiRuntime,
  resetLocalAiModelDigests,
  rollbackLocalAiRuntime,
  startLocalAiRuntime,
  stopLocalAiRuntime,
  uninstallLocalAiRuntime,
  updateLocalAiRuntime,
  type LocalAiStatus,
} from "../ftApi.localAi";

const ADMISSION_A = `adm_${"a".repeat(32)}`;
const ADMISSION_B = `adm_${"b".repeat(32)}`;
const OPERATION_A = `op_${"a".repeat(32)}`;

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ status: "success", data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function errorResponse(
  message: string,
  data: Record<string, unknown>,
  status: number,
): Response {
  return new Response(JSON.stringify({ status: "error", message, data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function runtimeStatus(overrides: Partial<LocalAiStatus> = {}): LocalAiStatus {
  return {
    version: "v0.32.0",
    active_version: "v0.32.0",
    target_version: "v0.32.0",
    previous_version: "v0.31.2",
    update_available: false,
    rollback_available: true,
    rollback_allowed: true,
    rollback_blocked_reason: null,
    repair_allowed: false,
    repair_blocked_reason: "Runtime repair is not required.",
    supported: true,
    installed: true,
    state: "installed",
    ready: false,
    managed_process: false,
    external_process: false,
    downloaded_bytes: 0,
    download_total_bytes: 0,
    install_required_bytes: 1_500_000_000,
    operation: null,
    model_pull: null,
    teardown: { state: "idle", mode: null, active_inferences: 0 },
    ...overrides,
  };
}

describe("ftApi.localAi", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(runtimeStatus()))));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads status and models from the bare v1 control plane", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(jsonResponse(runtimeStatus({
        state: "ready",
        ready: true,
        managed_process: true,
      })))
      .mockResolvedValueOnce(jsonResponse([{ name: "qwen3:8b" }]));

    await getLocalAiStatus();
    await listLocalAiModels();

    expect(fetch).toHaveBeenNthCalledWith(1, "/ft-api/v1/ai/local-runtime/status", {
      headers: {
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      signal: expect.any(AbortSignal),
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/ft-api/v1/ai/local-runtime/models", {
      headers: {
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      signal: expect.any(AbortSignal),
    });
  });

  it("accepts the durable provider-transition receipt kind", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(runtimeStatus({
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "provider_transition",
        state: "running",
      },
    })));

    const result = await getLocalAiStatus();

    expect(result.operation?.kind).toBe("provider_transition");
  });

  it("uses explicit confirmation for runtime and model downloads", async () => {
    await installLocalAiRuntime(ADMISSION_A);
    await pullLocalAiModel("qwen3:8b", ADMISSION_B);

    expect(fetch).toHaveBeenNthCalledWith(1, "/ft-api/v1/ai/local-runtime/install", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ confirmed: true, admission_id: ADMISSION_A }),
      signal: expect.any(AbortSignal),
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/ft-api/v1/ai/local-runtime/models/pull", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ model: "qwen3:8b", confirmed: true, admission_id: ADMISSION_B }),
      signal: expect.any(AbortSignal),
    });
  });

  it("uses explicit confirmation on the exact runtime recovery endpoints", async () => {
    await repairLocalAiRuntime(ADMISSION_A);
    await resetLocalAiModelDigests(ADMISSION_B);

    expect(fetch).toHaveBeenNthCalledWith(1, "/ft-api/v1/ai/local-runtime/repair", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ confirmed: true, admission_id: ADMISSION_A }),
      signal: expect.any(AbortSignal),
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/ft-api/v1/ai/local-runtime/models/digests/reset", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ confirmed: true, admission_id: ADMISSION_B }),
      signal: expect.any(AbortSignal),
    });
  });

  it("reconciles only the exact indeterminate operation and original admission", async () => {
    await reconcileLocalAiOperation(OPERATION_A, ADMISSION_A);

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/ai/local-runtime/operations/reconcile", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({
        confirmed: true,
        operation_id: OPERATION_A,
        admission_id: ADMISSION_A,
      }),
      signal: expect.any(AbortSignal),
    });
    expect(() => reconcileLocalAiOperation("not-an-operation", ADMISSION_A)).toThrow(
      "operation ID is invalid",
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("confirms every stopped-runtime replacement operation", async () => {
    await updateLocalAiRuntime(ADMISSION_A);
    await rollbackLocalAiRuntime(ADMISSION_A);
    await uninstallLocalAiRuntime(ADMISSION_A);

    for (const [index, operation] of ["update", "rollback", "uninstall"].entries()) {
      expect(fetch).toHaveBeenNthCalledWith(
        index + 1,
        `/ft-api/v1/ai/local-runtime/${operation}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": "backend-key",
            Authorization: "Bearer session-token",
          },
          body: JSON.stringify({ confirmed: true, admission_id: ADMISSION_A }),
          signal: expect.any(AbortSignal),
        },
      );
    }
  });

  it("sends exact model deletion and narrow prune confirmations", async () => {
    await deleteLocalAiModel("other:latest", ADMISSION_A);
    await pruneLocalAiModels(ADMISSION_B);

    expect(fetch).toHaveBeenNthCalledWith(1, "/ft-api/v1/ai/local-runtime/models/delete", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ model: "other:latest", confirmed: true, admission_id: ADMISSION_A }),
      signal: expect.any(AbortSignal),
    });
    expect(fetch).toHaveBeenNthCalledWith(2, "/ft-api/v1/ai/local-runtime/models/prune", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "backend-key",
        Authorization: "Bearer session-token",
      },
      body: JSON.stringify({ confirmed: true, admission_id: ADMISSION_B }),
      signal: expect.any(AbortSignal),
    });
  });

  it("accepts only the exact model digest shown to the operator", async () => {
    const digest = "b".repeat(64);
    const acceptance = {
      accepted: true,
      model: `flinttrade/sha256-${digest}:locked`,
      source_model: "qwen3:8b",
      digest,
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(acceptance));

    await expect(acceptLocalAiModelDigest("qwen3:8b", digest, ADMISSION_A)).resolves.toEqual(acceptance);

    expect(fetch).toHaveBeenCalledWith(
      "/ft-api/v1/ai/local-runtime/models/digests/accept",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": "backend-key",
          Authorization: "Bearer session-token",
        },
        body: JSON.stringify({ model: "qwen3:8b", digest, confirmed: true, admission_id: ADMISSION_A }),
        signal: expect.any(AbortSignal),
      },
    );
  });

  it.each([
    {
      name: "source model",
      receipt: (digest: string) => ({
        accepted: true,
        model: `flinttrade/sha256-${digest}:locked`,
        source_model: "other:latest",
        digest,
      }),
    },
    {
      name: "digest",
      receipt: (_digest: string) => ({
        accepted: true,
        model: `flinttrade/sha256-${"c".repeat(64)}:locked`,
        source_model: "qwen3:8b",
        digest: "c".repeat(64),
      }),
    },
    {
      name: "locked alias",
      receipt: (digest: string) => ({
        accepted: true,
        model: "qwen3:8b",
        source_model: "qwen3:8b",
        digest,
      }),
    },
  ])("rejects a digest-acceptance receipt for the wrong $name", async ({ receipt }) => {
    const digest = "b".repeat(64);
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(receipt(digest)));

    await expect(acceptLocalAiModelDigest("qwen3:8b", digest, ADMISSION_A)).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
  });

  it("starts and stops only through the managed runtime endpoints", async () => {
    await startLocalAiRuntime(ADMISSION_A);
    await stopLocalAiRuntime(OPERATION_A);

    expect(fetch).toHaveBeenNthCalledWith(1, "/ft-api/v1/ai/local-runtime/start", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ admission_id: ADMISSION_A }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/ft-api/v1/ai/local-runtime/stop", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_operation_id: OPERATION_A }),
    }));
  });

  it("generates lowercase 128-bit admission IDs for mutation ownership", () => {
    expect(createLocalAiAdmissionId()).toMatch(/^adm_[0-9a-f]{32}$/);
    expect(createLocalAiAdmissionId()).not.toBe(createLocalAiAdmissionId());
  });

  it("reuses a caller-owned admission ID for an idempotent retry", async () => {
    await updateLocalAiRuntime(ADMISSION_A);
    await updateLocalAiRuntime(ADMISSION_A);

    for (const call of (fetch as ReturnType<typeof vi.fn>).mock.calls) {
      expect(JSON.parse((call[1] as RequestInit).body as string)).toMatchObject({
        admission_id: ADMISSION_A,
      });
    }
  });

  it("treats an omitted tag and :latest as equivalent without folding explicit tags", () => {
    expect(localAiModelAliasesEquivalent("qwen3", "qwen3:latest")).toBe(true);
    expect(localAiModelAliasesEquivalent("library/qwen3", "library/qwen3:latest")).toBe(true);
    expect(localAiModelAliasesEquivalent("qwen3:8b", "qwen3:latest")).toBe(false);
    expect(localAiModelAliasesEquivalent("qwen3", "other:latest")).toBe(false);
  });

  it("validates a pull result as one exact model and digest outcome", () => {
    const result = {
      model: "qwen3:8b",
      status: "awaiting_digest_acceptance",
      completed: 1,
      total: 1,
      digest: "b".repeat(64),
      previous_digest: null,
      digest_changed: false,
      acceptance_required: true,
      error: null,
    };

    expect(isLocalAiModelPullResult(result)).toBe(true);
    expect(isLocalAiModelPullResult({ ...result, completed: 0 })).toBe(false);
    expect(isLocalAiModelPullResult({ ...result, digest_changed: true })).toBe(false);
    expect(isLocalAiModelPullResult({ ...result, digest: "not-a-digest" })).toBe(false);
  });

  it("aborts a hung local-AI request after the bounded client timeout", async () => {
    vi.useFakeTimers();
    (fetch as ReturnType<typeof vi.fn>).mockImplementationOnce((_url: string, init: RequestInit) => (
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })
    ));

    const request = expect(getLocalAiStatus()).rejects.toMatchObject({
      message: "Managed local AI request timed out",
      statusCode: 408,
    });
    await vi.advanceTimersByTimeAsync(LOCAL_AI_REQUEST_TIMEOUT_MS);

    await request;
    vi.useRealTimers();
  });

  it("preserves a bounded unsupported-platform reason in the surfaced error", async () => {
    const reason = `unsupported darwin/unknown\u0000${"x".repeat(400)}`;
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(errorResponse(
      "Managed local AI is unavailable on this platform",
      { supported: false, reason },
      503,
    ));

    const error = await getLocalAiStatus().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(LocalAiApiError);
    expect(error).toMatchObject({ statusCode: 503 });
    expect((error as LocalAiApiError).reason).toHaveLength(300);
    expect((error as Error).message).toContain("Reason: unsupported darwin/unknown");
    expect((error as Error).message.match(/Reason:/g)).toHaveLength(1);
    expect((error as Error).message).not.toContain("\u0000");
  });

  it("surfaces the backend correlation ID for an unexpected runtime failure", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(errorResponse(
      "Managed local AI operation failed",
      { correlation_id: "local_0123456789abcdef" },
      500,
    ));

    await expect(installLocalAiRuntime()).rejects.toMatchObject({
      message: "Managed local AI operation failed Diagnostic ID: local_0123456789abcdef.",
      correlationId: "local_0123456789abcdef",
      statusCode: 500,
    });
  });

  it("rejects malformed successful status and model payloads", async () => {
    (fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(jsonResponse({ state: "ready" }))
      .mockResolvedValueOnce(jsonResponse([{}]))
      .mockResolvedValueOnce(jsonResponse(runtimeStatus({ package_variant: "cuda" as never })));

    await expect(getLocalAiStatus()).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
    await expect(listLocalAiModels()).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
    await expect(getLocalAiStatus()).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
  });

  it.each([
    [{ name: "qwen3:8b", digest: "not-a-digest" }],
    [{
      name: "qwen3:8b",
      inference_model: `flinttrade/sha256-${"a".repeat(64)}:locked`,
      digest: "b".repeat(64),
      accepted_digest: "b".repeat(64),
      digest_drift: false,
    }],
    [{
      name: `flinttrade/sha256-${"a".repeat(64)}:locked`,
      digest: "b".repeat(64),
      accepted_digest: "b".repeat(64),
      digest_drift: false,
      locked_alias: true,
    }],
  ])("rejects inconsistent successful model trust metadata", async (models) => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(models));

    await expect(listLocalAiModels()).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
  });

  it("rejects an action-mismatched successful operation receipt", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({
      deleted: ["qwen3:8b"],
      pruned: [],
    }));

    await expect(resetLocalAiModelDigests(ADMISSION_A)).rejects.toMatchObject({
      message: "Managed local AI returned an invalid response",
      statusCode: 200,
    });
  });

  it("accepts a valid direct operation receipt", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ reset: true }));

    await expect(resetLocalAiModelDigests(ADMISSION_A)).resolves.toEqual({ reset: true });
  });
});
