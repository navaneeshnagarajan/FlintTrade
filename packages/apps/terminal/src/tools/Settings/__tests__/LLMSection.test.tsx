import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";

const localAi = vi.hoisted(() => ({
  acceptModelDigest: vi.fn(),
  createAdmissionId: vi.fn(),
  getStatus: vi.fn(),
  install: vi.fn(),
  update: vi.fn(),
  repair: vi.fn(),
  rollback: vi.fn(),
  uninstall: vi.fn(),
  resetModelDigests: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  listModels: vi.fn(),
  pullModel: vi.fn(),
  reconcileOperation: vi.fn(),
  deleteModel: vi.fn(),
  pruneModels: vi.fn(),
}));

const llmApi = vi.hoisted(() => ({
  testConnection: vi.fn(),
}));

vi.mock("@/services/ftApi.localAi", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/services/ftApi.localAi")>(),
  acceptLocalAiModelDigest: localAi.acceptModelDigest,
  createLocalAiAdmissionId: localAi.createAdmissionId,
  getLocalAiStatus: localAi.getStatus,
  installLocalAiRuntime: localAi.install,
  updateLocalAiRuntime: localAi.update,
  repairLocalAiRuntime: localAi.repair,
  rollbackLocalAiRuntime: localAi.rollback,
  uninstallLocalAiRuntime: localAi.uninstall,
  resetLocalAiModelDigests: localAi.resetModelDigests,
  startLocalAiRuntime: localAi.start,
  stopLocalAiRuntime: localAi.stop,
  listLocalAiModels: localAi.listModels,
  pullLocalAiModel: localAi.pullModel,
  reconcileLocalAiOperation: localAi.reconcileOperation,
  deleteLocalAiModel: localAi.deleteModel,
  pruneLocalAiModels: localAi.pruneModels,
}));

vi.mock("@/services/ftApi.llm", () => ({
  testLlmConnection: llmApi.testConnection,
}));

import { LocalAiApiError, type LocalAiModel, type LocalAiStatus } from "@/services/ftApi.localAi";
import { LLMSection } from "../LLMSection";

const ADMISSION_A = `adm_${"a".repeat(32)}`;
const ADMISSION_B = `adm_${"b".repeat(32)}`;
const OPERATION_A = `op_${"a".repeat(32)}`;
const OPERATION_B = `op_${"b".repeat(32)}`;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  vi.useRealTimers();
});

function status(overrides: Partial<LocalAiStatus> = {}): LocalAiStatus {
  return {
    version: "v0.32.0",
    active_version: "v0.32.0",
    target_version: "v0.32.0",
    previous_version: null,
    update_available: false,
    rollback_available: false,
    rollback_allowed: false,
    rollback_blocked_reason: null,
    repair_allowed: false,
    repair_blocked_reason: "Runtime repair is not required.",
    supported: true,
    installed: false,
    state: "not_installed",
    ready: false,
    managed_process: false,
    external_process: false,
    downloaded_bytes: 0,
    download_total_bytes: 0,
    install_required_bytes: 1_500_000_000,
    operation: null,
    model_pull: null,
    error: null,
    ...overrides,
  };
}

function trustedModel(source = "qwen3:8b", digest = "b".repeat(64)): LocalAiModel {
  return {
    name: source,
    inference_model: `flinttrade/sha256-${digest}:locked`,
    digest,
    accepted_digest: digest,
    digest_drift: false,
  };
}

function pullResult(model = "qwen3:8b", digest = "b".repeat(64)) {
  return {
    model,
    status: "awaiting_digest_acceptance" as const,
    completed: 1,
    total: 1,
    digest,
    previous_digest: null,
    digest_changed: false,
    acceptance_required: true,
    error: null,
  };
}

function renderOllama(overrides: {
  model?: string;
  onChange?: (field: "provider" | "host" | "model" | "apiKey", value: string) => void;
  onProviderChange?: (provider: string, host?: string, model?: string, apiKey?: string) => Promise<void>;
  providerActivationRequired?: boolean;
} = {}) {
  return render(
    <LLMSection
      settings={{
        provider: "ollama",
        host: "http://127.0.0.1:11434",
        model: overrides.model ?? "qwen3:8b",
        apiKey: "",
      }}
      onChange={overrides.onChange ?? vi.fn()}
      onProviderChange={overrides.onProviderChange ?? vi.fn().mockResolvedValue(undefined)}
      providerActivationRequired={overrides.providerActivationRequired}
    />,
  );
}

describe("LLMSection managed Ollama", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localAi.createAdmissionId
      .mockReturnValueOnce(ADMISSION_A)
      .mockReturnValue(ADMISSION_B);
    localAi.getStatus.mockResolvedValue(status());
    localAi.install.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "installed",
      operation: { id: OPERATION_A, admission_id: admissionId, kind: "install", state: "succeeded" },
    })));
    localAi.update.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "installed",
      operation: { id: OPERATION_A, admission_id: admissionId, kind: "update", state: "succeeded" },
    })));
    localAi.repair.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "installed",
      operation: { id: OPERATION_A, admission_id: admissionId, kind: "repair", state: "succeeded" },
    })));
    localAi.rollback.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "installed",
      operation: { id: OPERATION_A, admission_id: admissionId, kind: "rollback", state: "succeeded" },
    })));
    localAi.uninstall.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: false,
      state: "not_installed",
      operation: { id: OPERATION_B, admission_id: admissionId, kind: "uninstall", state: "succeeded" },
    })));
    localAi.resetModelDigests.mockResolvedValue({ reset: true });
    localAi.acceptModelDigest.mockResolvedValue({
      accepted: true,
      model: "qwen3:8b",
      source_model: "qwen3:8b",
      digest: "b".repeat(64),
    });
    localAi.start.mockImplementation((admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: admissionId, kind: "start", state: "succeeded" },
    })));
    localAi.stop.mockResolvedValue(status({ installed: true, state: "installed" }));
    localAi.listModels.mockResolvedValue([]);
    localAi.pullModel.mockImplementation((_model: string, admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: admissionId,
        kind: "pull_model",
        state: "succeeded",
        result: pullResult(),
      },
    })));
    localAi.reconcileOperation.mockImplementation((operationId: string, admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: operationId,
        admission_id: admissionId,
        kind: "pull_model",
        state: "indeterminate",
        error: "Managed Ollama operation outcome is unknown",
        reconciled_at: 3,
      },
      unresolved_operation: null,
    })));
    localAi.deleteModel.mockResolvedValue({ deleted: ["other:latest"], pruned: [] });
    localAi.pruneModels.mockResolvedValue({ deleted: [], pruned: [] });
    llmApi.testConnection.mockResolvedValue({
      status: "success",
      data: { provider: "openai", model: "gpt-4o" },
    });
  });

  it("offers a confirmed managed install and removes the editable host", async () => {
    renderOllama();

    expect(await screen.findByText("Not installed")).toBeInTheDocument();
    expect(screen.queryByLabelText("LLM host URL")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("LLM provider API key")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Install runtime" }));
    expect(await screen.findByText("Install managed Ollama?" )).toBeInTheDocument();
    expect(screen.getByText(/MIT licence/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download and install" }));

    await waitFor(() => expect(localAi.install).toHaveBeenCalledTimes(1));
  });

  it("labels the automatically selected Linux overlay as a package choice", async () => {
    localAi.getStatus.mockResolvedValue({ ...status(), package_variant: "rocm" } as LocalAiStatus);

    renderOllama();

    expect(await screen.findByText("Package selection ROCm")).toBeInTheDocument();
    expect(screen.queryByText(/accelerator rocm/i)).not.toBeInTheDocument();
  });

  it("waits for runtime readiness and a trusted installed model before explicit activation", async () => {
    const install = deferred<LocalAiStatus>();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    const model = trustedModel();
    localAi.install.mockImplementationOnce(() => install.promise);
    localAi.listModels.mockResolvedValue([model]);
    renderOllama({ onProviderChange, providerActivationRequired: true });

    expect(await screen.findByText("Not installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install runtime" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download and install" }));
    expect(onProviderChange).not.toHaveBeenCalled();

    await act(async () => {
      install.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "install",
          state: "succeeded",
        },
      }));
      await Promise.resolve();
    });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
    expect(onProviderChange).not.toHaveBeenCalled();
    fireEvent.click(activate);

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "ollama",
      "",
      model.inference_model,
    ));
  });

  it("requires explicit confirmation before repairing a corrupt managed install", async () => {
    localAi.getStatus.mockResolvedValue(status({
      integrity_error: "managed Ollama runtime integrity verification failed",
      repair_allowed: true,
      repair_blocked_reason: null,
    }));
    renderOllama();

    expect(await screen.findByText("Repair required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start runtime" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/runtime integrity verification failed/i);
    expect(screen.queryByRole("button", { name: "Install runtime" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Repair runtime" }));
    expect(await screen.findByText("Repair managed Ollama?")).toBeInTheDocument();
    expect(screen.getByText(/replace the corrupt managed runtime files/i)).toBeInTheDocument();
    expect(localAi.repair).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Replace and repair" }));

    await waitFor(() => expect(localAi.repair).toHaveBeenCalledTimes(1));
  });

  it.each([
    ["managed process", { managed_process: true }],
    ["external process", { external_process: true }],
    ["running operation", {
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "install" as const,
        state: "running" as const,
      },
    }],
    ["otherwise ready server", { ready: true, state: "ready" }],
  ])("does not offer destructive repair while a %s is active", async (_label, overrides) => {
    localAi.getStatus.mockResolvedValue(status({
      integrity_error: "managed Ollama runtime integrity verification failed",
      repair_allowed: true,
      repair_blocked_reason: null,
      ...overrides,
    }));
    renderOllama();

    expect(await screen.findByRole("alert")).toHaveTextContent(/runtime integrity verification failed/i);
    expect(screen.queryByRole("button", { name: "Repair runtime" })).not.toBeInTheDocument();
  });

  it("does not offer runtime-file repair for unavailable operation receipt truth", async () => {
    localAi.getStatus.mockResolvedValue(status({
      integrity_error: "managed Ollama operation truth is unavailable because its receipt journal is missing",
      repair_allowed: false,
      repair_blocked_reason:
        "Durable operation receipt truth is unavailable; runtime-file repair cannot recover it.",
    }));
    renderOllama();

    expect(await screen.findByText("Recovery blocked")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/runtime-file repair cannot recover/i);
    expect(screen.queryByRole("button", { name: "Repair runtime" })).not.toBeInTheDocument();
    expect(localAi.repair).not.toHaveBeenCalled();
  });

  it("updates a stopped legacy runtime only after confirmation", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "installed",
      active_version: "v0.31.2",
      previous_version: null,
      update_available: true,
    }));
    renderOllama();

    expect(await screen.findByText("Runtime v0.31.2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Update runtime" }));
    expect(await screen.findByText("Update managed Ollama?")).toBeInTheDocument();
    expect(localAi.update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Download and update" }));

    await waitFor(() => expect(localAi.update).toHaveBeenCalledTimes(1));
  });

  it("rolls back or uninstalls a stopped runtime only after confirmation", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "installed",
      active_version: "v0.32.0",
      previous_version: "v0.31.2",
      rollback_available: true,
      rollback_allowed: true,
    }));
    renderOllama();

    expect(await screen.findByText("Rollback v0.31.2 available")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rollback runtime" }));
    fireEvent.click(await screen.findByRole("button", { name: "Switch to v0.31.2" }));
    await waitFor(() => expect(localAi.rollback).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Uninstall runtime" }));
    expect(await screen.findByText(/models and accepted-digest metadata will remain/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove runtime" }));
    await waitFor(() => expect(localAi.uninstall).toHaveBeenCalledTimes(1));
  });

  it("uses the backend rollback capability even when the active release has failed integrity", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "failed",
      active_version: "v0.32.0",
      previous_version: "v0.31.2",
      rollback_available: true,
      rollback_allowed: true,
      integrity_error: "active runtime digest mismatch",
    }));
    renderOllama();

    const rollback = await screen.findByRole("button", { name: "Rollback runtime" });
    expect(rollback).not.toBeDisabled();
    fireEvent.click(rollback);
    fireEvent.click(await screen.findByRole("button", { name: "Switch to v0.31.2" }));

    await waitFor(() => expect(localAi.rollback).toHaveBeenCalledTimes(1));
  });

  it("surfaces the backend reason when rollback is blocked", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "installed",
      previous_version: "v0.31.2",
      rollback_available: true,
      rollback_allowed: false,
      rollback_blocked_reason: "stop the external Ollama process first",
    }));
    renderOllama();

    expect(await screen.findByRole("button", { name: "Rollback runtime" })).toBeDisabled();
    expect(screen.getByText(/stop the external Ollama process first/i)).toBeInTheDocument();
  });

  it("requires confirmation before pulling the selected model", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", size: 5_000_000_000 }]);
    renderOllama();

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pull model" }));
    expect(await screen.findByText("Download qwen3:8b?" )).toBeInTheDocument();
    expect(screen.getByText(/licence and disk requirements/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.pullModel).toHaveBeenCalledWith("qwen3:8b", ADMISSION_A));
  });

  it("deletes only an unselected model alias and separately prunes managed aliases", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([
      { name: "qwen3:8b", size: 5_000_000_000 },
      { name: "other:latest", size: 2_000_000_000 },
    ]);
    renderOllama({ model: "qwen3:8b" });

    expect(await screen.findByText("other:latest")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete qwen3:8b" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete other:latest" }));
    expect(await screen.findByText("Delete other:latest?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete model" }));
    await waitFor(() => expect(localAi.deleteModel).toHaveBeenCalledWith("other:latest", ADMISSION_A));

    fireEvent.click(screen.getByRole("button", { name: "Prune unused model aliases" }));
    expect(await screen.findByText("Prune unused FlintTrade aliases?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prune aliases" }));
    await waitFor(() => expect(localAi.pruneModels).toHaveBeenCalledTimes(1));
  });

  it("invalidates a pre-mutation model request before publishing deletion inventory", async () => {
    const staleInventory = deferred<LocalAiModel[]>();
    const beforeDeletion = [
      { name: "qwen3:8b", size: 5_000_000_000 },
      { name: "other:latest", size: 2_000_000_000 },
    ];
    const afterDeletion = [{ name: "qwen3:8b", size: 5_000_000_000 }];
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels
      .mockResolvedValueOnce(beforeDeletion)
      .mockImplementationOnce(() => staleInventory.promise)
      .mockResolvedValue(afterDeletion);
    renderOllama({ model: "qwen3:8b" });

    expect(await screen.findByText("other:latest")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete other:latest" })).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Delete other:latest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete model" }));
    await waitFor(() => expect(screen.queryByText("other:latest")).not.toBeInTheDocument());

    await act(async () => {
      staleInventory.resolve(beforeDeletion);
      await staleInventory.promise;
    });

    expect(screen.queryByText("other:latest")).not.toBeInTheDocument();
    expect(localAi.listModels.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("forces a new status generation after a direct mutation result", async () => {
    vi.useFakeTimers();
    const deletion = deferred<{ deleted: string[]; pruned: string[] }>();
    const staleStatus = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        inference_processor: "Initial",
      }))
      .mockImplementationOnce(() => staleStatus.promise)
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        inference_processor: "Fresh",
      }));
    localAi.listModels.mockResolvedValue([
      { name: "qwen3:8b", size: 5_000_000_000 },
      { name: "other:latest", size: 2_000_000_000 },
    ]);
    localAi.deleteModel.mockImplementation(() => deletion.promise);
    renderOllama({ model: "qwen3:8b" });

    fireEvent.click(await vi.waitFor(() => screen.getByRole("button", { name: "Delete other:latest" })));
    fireEvent.click(await vi.waitFor(() => screen.getByRole("button", { name: "Delete model" })));
    await vi.waitFor(() => expect(localAi.deleteModel).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      deletion.resolve({ deleted: ["other:latest"], pruned: [] });
      await deletion.promise;
    });
    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(3));
    expect(await vi.waitFor(() => screen.getByText("Inference processor Fresh"))).toBeInTheDocument();

    await act(async () => {
      staleStatus.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        inference_processor: "Stale",
      }));
      await staleStatus.promise;
    });

    expect(screen.getByText("Inference processor Fresh")).toBeInTheDocument();
    expect(screen.queryByText("Inference processor Stale")).not.toBeInTheDocument();
  });

  it("invalidates a pre-pull model request before publishing the installed model", async () => {
    const staleInventory = deferred<LocalAiModel[]>();
    const installedModel = { name: "qwen3:8b", digest: "b".repeat(64) };
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => staleInventory.promise)
      .mockResolvedValue([installedModel]);
    localAi.pullModel.mockImplementation((_model: string, admissionId: string) => Promise.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: admissionId,
        kind: "pull_model",
        state: "succeeded",
        result: pullResult(),
      },
      model_pull: {
        model: "qwen3:8b",
        status: "awaiting_digest_acceptance",
        completed: 1,
        total: 1,
        digest: "b".repeat(64),
        acceptance_required: true,
      },
    })));
    renderOllama({ model: "qwen3:8b" });

    expect(await screen.findByText("Model not installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    expect(await screen.findByText("Model installed")).toBeInTheDocument();

    await act(async () => {
      staleInventory.resolve([]);
      await staleInventory.promise;
    });

    expect(screen.getByText("Model installed")).toBeInTheDocument();
    expect(localAi.listModels.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("wraps long model identifiers in narrow delete and download confirmations", async () => {
    const longModel = `publisher/${"verylongmodelidentifier".repeat(12)}:latest`;
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([
      { name: "qwen3:8b", size: 5_000_000_000 },
      { name: longModel, size: 2_000_000_000 },
    ]);
    const view = renderOllama({ model: "qwen3:8b" });

    fireEvent.click(await screen.findByRole("button", { name: `Delete ${longModel}` }));
    expect(await screen.findByRole("heading", { name: `Delete ${longModel}?` })).toHaveClass("break-all");
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));

    view.rerender(
      <LLMSection
        settings={{ provider: "ollama", host: "http://127.0.0.1:11434", model: longModel, apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    expect(await screen.findByRole("heading", { name: `Download ${longModel}?` })).toHaveClass("break-all");
  });

  it("never offers to stop an externally owned Ollama process", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: false,
      state: "ready",
      ready: true,
      managed_process: true,
      external_process: true,
    }));
    renderOllama();

    expect(await screen.findByText("External server")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop runtime" })).not.toBeInTheDocument();
  });

  it("stops only a managed ready process after confirmation and reports teardown", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.stop.mockResolvedValue(status({
      installed: true,
      state: "installed",
      teardown: { state: "stopped", mode: "graceful", active_inferences: 2 },
    }));
    renderOllama();

    const stopButton = await screen.findByRole("button", { name: "Stop runtime" });
    await waitFor(() => expect(stopButton).not.toBeDisabled());
    fireEvent.click(stopButton);
    expect(await screen.findByText("Stop managed Ollama?")).toBeInTheDocument();
    expect(localAi.stop).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Stop runtime" }));

    await waitFor(() => expect(localAi.stop).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Teardown mode: graceful\. Active inferences: 2\./i)).toBeInTheDocument();
  });

  it("offers Stop instead of Start for a managed process that is no longer ready", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "failed",
      ready: false,
      managed_process: true,
      error: "readiness probe failed",
    }));
    renderOllama();

    const stopButton = await screen.findByRole("button", { name: "Stop runtime" });
    expect(screen.queryByRole("button", { name: "Start runtime" })).not.toBeInTheDocument();
    fireEvent.click(stopButton);
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stop runtime" }));

    await waitFor(() => expect(localAi.stop).toHaveBeenCalledTimes(1));
  });

  it("keeps controls locked until an ambiguous stop receives a fresh status", async () => {
    const refreshed = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => refreshed.promise);
    localAi.stop.mockRejectedValueOnce(new LocalAiApiError(
      "Managed local AI request timed out",
      { statusCode: 408 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Stop runtime" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stop runtime" }));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Reconciling stop")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      refreshed.resolve(status({ installed: true, state: "installed" }));
      await refreshed.promise;
    });

    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
    expect(screen.queryByText("Reconciling stop")).not.toBeInTheDocument();
  });

  it("keeps stop reconciliation locked through an intermediate stopping receipt", async () => {
    vi.useFakeTimers();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValueOnce(status({
        installed: true,
        state: "stopping",
        managed_process: true,
        teardown: { state: "stopping", mode: "graceful", active_inferences: 1 },
      }))
      .mockResolvedValueOnce(status({
        installed: true,
        state: "installed",
        managed_process: false,
        teardown: { state: "stopped", mode: "graceful", active_inferences: 0 },
      }));
    localAi.stop.mockRejectedValueOnce(new LocalAiApiError(
      "Managed local AI request timed out",
      { statusCode: 408 },
    ));
    renderOllama();

    const stopButton = await vi.waitFor(() => screen.getByRole("button", { name: "Stop runtime" }));
    fireEvent.click(stopButton);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Stop runtime" }));

    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Reconciling stop")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh runtime status" })).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(3));
    expect(screen.queryByText("Reconciling stop")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled();
  });

  it.each([
    {
      label: "starting",
      runtime: status({
        installed: true,
        state: "starting",
        managed_process: true,
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "start", state: "running" },
      }),
    },
    {
      label: "pulling a model",
      runtime: status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
        model_pull: { model: "qwen3:8b", status: "pulling", completed: 1, total: 10 },
      }),
    },
  ])("offers confirmed cancellation while $label", async ({ runtime }) => {
    const stop = deferred<LocalAiStatus>();
    localAi.getStatus.mockResolvedValue(runtime);
    localAi.stop.mockReturnValue(stop.promise);
    renderOllama();

    const cancelButton = await screen.findByRole("button", { name: "Cancel local AI operation" });
    expect(cancelButton).not.toBeDisabled();
    fireEvent.click(cancelButton);

    expect(await screen.findByText("Cancel the local AI operation?")).toBeInTheDocument();
    expect(localAi.stop).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel operation" }));
    expect(localAi.stop).toHaveBeenCalledWith(runtime.operation?.id);

    await act(async () => {
      stop.resolve(status({
        installed: true,
        state: "installed",
        teardown: { state: "stopped", mode: "forced", active_inferences: 1 },
      }));
      await stop.promise;
    });
    expect(await screen.findByText(/Teardown mode: forced\. Active inferences: 1\./i)).toBeInTheDocument();
  });

  it("cancels only the operation captured when the confirmation dialog opened", async () => {
    const operationA = status({
      installed: true,
      state: "starting",
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "start", state: "running" },
    });
    const operationB = status({
      installed: true,
      state: "starting",
      managed_process: true,
      operation: { id: OPERATION_B, admission_id: ADMISSION_B, kind: "start", state: "running" },
    });
    localAi.getStatus.mockResolvedValueOnce(operationA).mockResolvedValue(operationB);
    localAi.stop.mockResolvedValue(status({
      installed: true,
      state: "installed",
      teardown: { state: "stopped", mode: "graceful", active_inferences: 0 },
    }));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel local AI operation" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status", hidden: true }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel operation" }));

    await waitFor(() => expect(localAi.stop).toHaveBeenCalledWith(OPERATION_A));
    expect(localAi.stop).not.toHaveBeenCalledWith(OPERATION_B);
  });

  it("hides superseded model progress while cancellation is pending", async () => {
    const stop = deferred<LocalAiStatus>();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: { model: "qwen3:8b", status: "pulling", completed: 500, total: 1_000 },
    }));
    localAi.stop.mockReturnValue(stop.promise);
    renderOllama();

    const progressbar = await screen.findByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).toHaveAttribute("aria-valuenow", "50");
    fireEvent.click(screen.getByRole("button", { name: "Cancel local AI operation" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel operation" }));

    await waitFor(() => expect(progressbar).not.toHaveAttribute("aria-valuenow"));
    expect(progressbar).toHaveAttribute("aria-valuetext", "Stopping in progress");
    expect(screen.getByRole("button", { name: "Refresh runtime status" })).toBeDisabled();

    await act(async () => {
      stop.resolve(status({
        installed: true,
        state: "installed",
        teardown: { state: "stopped", mode: "graceful", active_inferences: 0 },
      }));
      await stop.promise;
    });
  });

  it("forces a new status generation when cancellation fails during an older poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stalePoll = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "starting",
        managed_process: true,
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "start", state: "running" },
      }))
      .mockImplementationOnce(() => stalePoll.promise)
      .mockResolvedValue(status({
        installed: true,
        state: "installed",
        teardown: { state: "stopped", mode: "graceful", active_inferences: 0 },
      }));
    localAi.stop.mockRejectedValueOnce(new Error("stop acknowledgement timed out"));
    renderOllama();

    const cancel = await screen.findByRole("button", { name: "Cancel local AI operation" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    fireEvent.click(cancel);
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole(
      "button",
      { name: "Cancel operation" },
    ));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(3));
  });

  it.each(["install", "update", "repair"] as const)(
    "allows a confirmed %s cancellation before an owned child exists",
    async (kind) => {
      localAi.getStatus.mockResolvedValue(status({
        installed: kind !== "install",
        state: "downloading",
        managed_process: false,
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind, state: "running" },
      }));
      localAi.stop.mockResolvedValue(status({
        installed: kind !== "install",
        state: kind === "install" ? "not_installed" : "installed",
        teardown: { state: "stopped", mode: null, active_inferences: 0 },
      }));
      renderOllama();

      fireEvent.click(await screen.findByRole("button", { name: "Cancel local AI operation" }));
      expect(localAi.stop).not.toHaveBeenCalled();
      fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole(
        "button",
        { name: "Cancel operation" },
      ));

      await waitFor(() => expect(localAi.stop).toHaveBeenCalledWith(OPERATION_A));
      expect(await screen.findByText(/Local AI operation cancelled.*Teardown mode: none.*Active inferences: 0/i))
        .toBeInTheDocument();
    },
  );

  it("does not activate from ready status and uses the hydrated model for explicit activation", async () => {
    const staleModel = "qwen3:8b";
    const model = trustedModel(staleModel);
    const lockedAlias = model.inference_model as string;
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([model]);

    const view = renderOllama({
      model: staleModel,
      onProviderChange,
      providerActivationRequired: true,
    });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(onProviderChange).not.toHaveBeenCalled();

    view.rerender(
      <LLMSection
        settings={{
          provider: "ollama",
          host: "http://127.0.0.1:11434",
          model: lockedAlias,
          apiKey: "",
        }}
        onChange={vi.fn()}
        onProviderChange={onProviderChange}
        providerActivationRequired
      />,
    );
    const activate = screen.getByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
    fireEvent.click(activate);

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "ollama",
      "",
      lockedAlias,
    ));
  });

  it("keeps explicit managed activation busy until the provider transaction succeeds", async () => {
    const activation = deferred<void>();
    const onProviderChange = vi.fn(() => activation.promise);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([trustedModel()]);

    renderOllama({ onProviderChange, providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
    fireEvent.click(activate);

    expect(screen.getByText("Activating provider")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: "Local AI operation progress" })).not.toBeInTheDocument();

    activation.resolve();
    await waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
  });

  it.each([
    ["the selected model is absent", []],
    ["the selected model has no accepted digest", [{ name: "qwen3:8b", digest: "b".repeat(64) }]],
    ["an accepted mutable tag has no locked inference alias", [{
      name: "qwen3:8b",
      digest: "b".repeat(64),
      accepted_digest: "b".repeat(64),
      digest_drift: false,
    }]],
    ["the selected model has digest drift", [{
      name: "qwen3:8b",
      digest: "b".repeat(64),
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    }]],
    ["the locked alias encodes a different digest", [{
      name: "qwen3:8b",
      inference_model: `flinttrade/sha256-${"a".repeat(64)}:locked`,
      digest: "b".repeat(64),
      accepted_digest: "b".repeat(64),
      digest_drift: false,
    }]],
  ])("blocks managed activation when %s", async (_label, models) => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue(models);
    renderOllama({ onProviderChange, providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalled());
    expect(activate).toBeDisabled();
    fireEvent.click(activate);
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("blocks managed activation while model acceptance is pending", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      model_pull: {
        model: "qwen3:8b",
        status: "success",
        completed: 1,
        total: 1,
        acceptance_required: true,
      },
    }));
    localAi.listModels.mockResolvedValue([trustedModel()]);
    renderOllama({ onProviderChange, providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalled());
    expect(activate).toBeDisabled();
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("does not activate a provider while an asynchronous model pull is still running", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.pullModel.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: { model: "qwen3:8b", status: "pulling", completed: 0, total: 0 },
    }));
    renderOllama({ onProviderChange, providerActivationRequired: true });

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.pullModel).toHaveBeenCalledTimes(1));
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("offers a retry when managed activation persistence fails", async () => {
    const onProviderChange = vi.fn()
      .mockRejectedValueOnce(new Error("workspace locked"))
      .mockResolvedValueOnce(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([trustedModel()]);

    renderOllama({ onProviderChange, providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
    fireEvent.click(activate);
    expect(await screen.findByText("workspace locked")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry activation" });
    await waitFor(() => expect(retry).not.toBeDisabled());
    fireEvent.click(retry);

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("workspace locked")).not.toBeInTheDocument());
  });

  it("collects a replacement credential before switching away from managed Ollama", async () => {
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.stop.mockResolvedValue(status({ installed: true, state: "installed" }));
    renderOllama({ onChange, onProviderChange });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(onProviderChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("LLM provider API key")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-openai-replacement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "openai",
      "",
      "gpt-4o-mini",
      "sk-openai-replacement",
    ));
    expect(onChange).not.toHaveBeenCalledWith("provider", "openai");
    expect(localAi.stop).not.toHaveBeenCalled();
  });

  it("reports provider saving separately from managed-runtime progress", async () => {
    const providerSave = deferred<void>();
    const onProviderChange = vi.fn(() => providerSave.promise);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    renderOllama({ onProviderChange });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-openai-replacement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    expect(screen.getByText("Saving provider")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: "Local AI operation progress" })).not.toBeInTheDocument();

    await act(async () => {
      providerSave.resolve();
      await providerSave.promise;
    });
  });

  it("keeps the configured managed runtime visible while another provider remains an uncommitted draft", async () => {
    const onProviderChange = vi.fn().mockRejectedValue(new Error("provider transaction failed"));
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    renderOllama({ onProviderChange });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(screen.getByLabelText("Managed Ollama runtime")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-openai-replacement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    expect(await screen.findByText("provider transaction failed")).toBeInTheDocument();
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(3));
    expect(screen.getByLabelText("Managed Ollama runtime")).toBeInTheDocument();
  });

  it("allows a credentialled provider switch without touching an externally owned Ollama process", async () => {
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      state: "ready",
      ready: true,
      external_process: true,
    }));
    localAi.stop.mockResolvedValue(status({
      state: "ready",
      ready: true,
      external_process: true,
    }));
    renderOllama({ onChange, onProviderChange });

    expect(await screen.findByText("External server")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-openai-replacement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "openai",
      "",
      "gpt-4o-mini",
      "sk-openai-replacement",
    ));
    expect(localAi.stop).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("never performs an out-of-band stop while applying a provider draft", async () => {
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.stop.mockRejectedValue(new Error("managed stop timed out"));
    renderOllama({ onChange, onProviderChange });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-openai-replacement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "openai",
      "",
      "gpt-4o-mini",
      "sk-openai-replacement",
    ));
    expect(localAi.stop).not.toHaveBeenCalled();
    expect(screen.queryByText(/managed stop timed out/i)).not.toBeInTheDocument();
  });

  it("surfaces the selected installed model state and full accepted digest", async () => {
    const digest = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef";
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      size: 5_000_000_000,
      digest,
      accepted_digest: digest,
      digest_drift: false,
    }]);
    renderOllama();

    expect(await screen.findByText("Model installed")).toBeInTheDocument();
    expect(screen.getByText("Accepted digest")).toBeInTheDocument();
    expect(screen.getByText(digest, { selector: "code" })).toBeInTheDocument();
    expect(screen.queryByText(/mutable-tag drift detected/i)).not.toBeInTheDocument();
  });

  it("persists the accepted inference alias when an installed mutable model is selected", async () => {
    const model = trustedModel();
    const onChange = vi.fn();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([model]);
    renderOllama({ model: "unselected:latest", onChange });

    fireEvent.click(await screen.findByRole("combobox", { name: "Installed Ollama model" }));
    fireEvent.click(await screen.findByRole("option", { name: "qwen3:8b (verified)" }));

    expect(onChange).toHaveBeenCalledWith("model", model.inference_model);
    expect(onChange).not.toHaveBeenCalledWith("model", "qwen3:8b");
  });

  it("does not offer a model pull for an installed digest-locked alias", async () => {
    const digest = "b".repeat(64);
    const lockedAlias = `flinttrade/sha256-${digest}:locked`;
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: lockedAlias,
      digest,
      accepted_digest: digest,
      digest_drift: false,
      locked_alias: true,
    }]);
    renderOllama({ model: lockedAlias });

    expect(await screen.findByText("Model installed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pull model" })).not.toBeInTheDocument();
  });

  it("protects the effective locked alias while the readable source tag is displayed", async () => {
    const model = trustedModel();
    const lockedAlias = model.inference_model as string;
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([
      model,
      {
        name: lockedAlias,
        digest: model.digest,
        accepted_digest: model.accepted_digest,
        digest_drift: false,
        locked_alias: true,
      },
    ]);
    renderOllama({ model: "qwen3:8b" });

    expect(await screen.findByText("Model installed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `Delete ${lockedAlias}` })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete qwen3:8b" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pull model" })).not.toBeInTheDocument();
  });

  it("treats an omitted tag and :latest as the same model for readiness and deletion protection", async () => {
    const model = trustedModel("qwen3:latest");
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([model, { name: "other:latest" }]);
    renderOllama({ model: "qwen3", providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
    expect(screen.queryByRole("button", { name: "Delete qwen3:latest" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete other:latest" })).toBeInTheDocument();
  });

  it("scopes pending digest acceptance to aliases of the selected model", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      model_pull: {
        model: "other:latest",
        status: "success",
        completed: 100,
        total: 100,
        acceptance_required: true,
      },
    }));
    localAi.listModels.mockResolvedValue([trustedModel("qwen3:latest")]);
    renderOllama({ model: "qwen3", providerActivationRequired: true });

    const activate = await screen.findByRole("button", { name: "Activate managed Ollama" });
    await waitFor(() => expect(activate).not.toBeDisabled());
  });

  it("distinguishes the accepted digest from the live digest when a mutable tag drifts", async () => {
    const acceptedDigest = "a".repeat(64);
    const currentDigest = "b".repeat(64);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: acceptedDigest,
      digest_drift: true,
    }]);
    renderOllama();

    expect(await screen.findByText("Accepted digest")).toBeInTheDocument();
    expect(screen.getByText(acceptedDigest)).toBeInTheDocument();
    expect(screen.getByText("Current digest")).toBeInTheDocument();
    expect(screen.getByText(currentDigest)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/mutable-tag drift detected/i);
  });

  it("requires exact confirmation before accepting a changed model digest", async () => {
    const acceptedDigest = "a".repeat(64);
    const currentDigest = "b".repeat(64);
    const lockedAlias = `flinttrade/sha256-${currentDigest}:locked`;
    const onChange = vi.fn();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: acceptedDigest,
      digest_drift: true,
    }]);
    localAi.acceptModelDigest.mockResolvedValue({
      accepted: true,
      model: lockedAlias,
      source_model: "qwen3:8b",
      digest: currentDigest,
    });
    renderOllama({ onChange });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    expect(await screen.findByText("Accept this model digest?")).toBeInTheDocument();
    expect(screen.getAllByText(currentDigest, { selector: "code" })).toHaveLength(2);
    expect(localAi.acceptModelDigest).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Accept exact digest" }));

    await waitFor(() => expect(localAi.acceptModelDigest).toHaveBeenCalledWith(
      "qwen3:8b",
      currentDigest,
      ADMISSION_A,
    ));
    expect(onChange).toHaveBeenCalledWith("model", lockedAlias);
  });

  it("rejects digest acceptance when inventory changes after the dialog opens", async () => {
    const reviewedDigest = "b".repeat(64);
    const replacementDigest = "c".repeat(64);
    const model: LocalAiModel = {
      name: "qwen3:8b",
      digest: reviewedDigest,
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    };
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([model]);
    const view = renderOllama({ onChange, onProviderChange });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(reviewedDigest);

    model.digest = replacementDigest;
    view.rerender(
      <LLMSection
        settings={{
          provider: "ollama",
          host: "http://127.0.0.1:11434",
          model: "qwen3:8b",
          apiKey: "",
        }}
        onChange={onChange}
        onProviderChange={onProviderChange}
      />,
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent(reviewedDigest);

    fireEvent.click(screen.getByRole("button", { name: "Accept exact digest" }));

    expect(await screen.findByText(/inventory changed.*review the current digest/i)).toBeInTheDocument();
    expect(localAi.acceptModelDigest).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not apply a valid-looking digest receipt for a different confirmed digest", async () => {
    const acceptedDigest = "a".repeat(64);
    const currentDigest = "b".repeat(64);
    const wrongDigest = "c".repeat(64);
    const onChange = vi.fn();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: acceptedDigest,
      digest_drift: true,
    }]);
    localAi.acceptModelDigest.mockResolvedValue({
      accepted: true,
      model: `flinttrade/sha256-${wrongDigest}:locked`,
      source_model: "qwen3:8b",
      digest: wrongDigest,
    });
    renderOllama({ onChange });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));

    expect(await screen.findByText(/unverified operation response/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
  });

  it("commits a digest-derived model inside pending managed activation", async () => {
    const currentDigest = "b".repeat(64);
    const lockedAlias = `flinttrade/sha256-${currentDigest}:locked`;
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels
      .mockResolvedValueOnce([{
        name: "qwen3:8b",
        digest: currentDigest,
        accepted_digest: "a".repeat(64),
        digest_drift: true,
      }])
      .mockResolvedValue([{
        name: lockedAlias,
        digest: currentDigest,
        accepted_digest: currentDigest,
        digest_drift: false,
        locked_alias: true,
      }]);
    localAi.acceptModelDigest.mockResolvedValue({
      accepted: true,
      model: lockedAlias,
      source_model: "qwen3:8b",
      digest: currentDigest,
    });
    renderOllama({ onChange, onProviderChange, providerActivationRequired: true });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "ollama",
      "",
      lockedAlias,
    ));
    expect(onChange).not.toHaveBeenCalledWith("model", lockedAlias);
  });

  it("retries failed managed activation with the accepted digest-derived model", async () => {
    const currentDigest = "c".repeat(64);
    const lockedAlias = `flinttrade/sha256-${currentDigest}:locked`;
    const onProviderChange = vi.fn()
      .mockRejectedValueOnce(new Error("workspace locked"))
      .mockResolvedValueOnce(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels
      .mockResolvedValueOnce([{
        name: "qwen3:8b",
        digest: currentDigest,
        accepted_digest: "a".repeat(64),
        digest_drift: true,
      }])
      .mockResolvedValue([{
        name: lockedAlias,
        digest: currentDigest,
        accepted_digest: currentDigest,
        digest_drift: false,
        locked_alias: true,
      }]);
    localAi.acceptModelDigest.mockResolvedValue({
      accepted: true,
      model: lockedAlias,
      source_model: "qwen3:8b",
      digest: currentDigest,
    });
    renderOllama({ onProviderChange, providerActivationRequired: true });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));
    expect(await screen.findByText("workspace locked")).toBeInTheDocument();

    const retry = screen.getByRole("button", { name: "Retry activation" });
    await waitFor(() => expect(retry).not.toBeDisabled());
    fireEvent.click(retry);
    await waitFor(() => expect(onProviderChange).toHaveBeenCalledTimes(2));
    expect(onProviderChange).toHaveBeenLastCalledWith("ollama", "", lockedAlias);
  });

  it("marks an installed mutable tag unverifiable when the backend omits its digest", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", size: 5_000_000_000 }]);
    renderOllama();

    expect(await screen.findByText("Model installed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/digest unavailable.*mutable tag/i);
  });

  it("surfaces a model inventory failure", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockRejectedValue(new Error("model inventory unavailable"));
    renderOllama();

    expect(await screen.findByRole("alert")).toHaveTextContent("model inventory unavailable");
    expect(screen.queryByRole("button", { name: "Reset model trust state" })).not.toBeInTheDocument();
  });

  it("keeps a model inventory alert mounted across status polls", async () => {
    vi.useFakeTimers();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: { model: "qwen3:8b", status: "pulling", completed: 1, total: 10 },
    }));
    localAi.listModels.mockRejectedValue(new Error("model inventory unavailable"));
    renderOllama();

    const alert = await vi.waitFor(() => screen.getByRole("alert"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(localAi.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert")).toBe(alert);
    expect(alert).toHaveTextContent("model inventory unavailable");
    vi.useRealTimers();
  });

  it("requires explicit confirmation before resetting invalid model trust metadata", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels
      .mockRejectedValueOnce(new Error("managed Ollama model digest state is invalid"))
      .mockResolvedValueOnce([]);
    renderOllama();

    expect(await screen.findByRole("alert")).toHaveTextContent(/model digest state is invalid/i);
    fireEvent.click(screen.getByRole("button", { name: "Reset model trust state" }));
    expect(await screen.findByText("Reset model trust state?")).toBeInTheDocument();
    expect(screen.getByText(/does not delete Ollama model blobs/i)).toBeInTheDocument();
    expect(localAi.resetModelDigests).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Reset trust metadata" }));

    await waitFor(() => expect(localAi.resetModelDigests).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(3));
  });

  it("shows a real busy state while manually refreshing runtime status", async () => {
    const refresh = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status())
      .mockImplementationOnce(() => refresh.promise);
    renderOllama();

    expect(await screen.findByText("Not installed")).toBeInTheDocument();
    const refreshButton = screen.getByRole("button", { name: "Refresh runtime status" });
    fireEvent.click(refreshButton);

    expect(refreshButton).toBeDisabled();
    expect(screen.getByRole("progressbar", { name: "Local AI operation progress" })).toBeInTheDocument();

    refresh.resolve(status({ installed: true, state: "installed" }));
    await waitFor(() => expect(refreshButton).not.toBeDisabled());
  });

  it("tests the selected managed model through real backend inference admission", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    llmApi.testConnection.mockResolvedValue({
      status: "success",
      data: { provider: "ollama", model: "qwen3:8b" },
    });
    renderOllama();

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => expect(llmApi.testConnection).toHaveBeenCalledWith({
      provider: "ollama",
      host: "",
      model: "qwen3:8b",
    }));
    expect(await screen.findByText(/Connection successful.*ollama.*qwen3:8b/i)).toBeInTheDocument();
  });

  it("keeps operation polling single-flight when a status request exceeds the interval", async () => {
    vi.useFakeTimers();
    const slowPoll = deferred<LocalAiStatus>();
    const running = status({
      installed: true,
      state: "downloading",
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "install", state: "running" },
    });
    const ready = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    });
    localAi.getStatus
      .mockResolvedValueOnce(running)
      .mockImplementationOnce(() => slowPoll.promise)
      .mockResolvedValueOnce(ready);

    renderOllama();
    await vi.waitFor(() => expect(screen.getByText("Installing")).toBeInTheDocument());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(5000);
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      slowPoll.resolve(running);
      await Promise.resolve();
    });

    await vi.advanceTimersByTimeAsync(999);
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(3));
    await vi.waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
    vi.useRealTimers();
  });

  it("keeps status polling while slow model inventory remains single-flight", async () => {
    vi.useFakeTimers();
    const inventory = deferred<Array<{ name: string }>>();
    const pulling = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: { model: "qwen3:8b", status: "pulling", completed: 500, total: 1000 },
    });
    localAi.getStatus.mockResolvedValue(pulling);
    localAi.listModels.mockImplementationOnce(() => inventory.promise).mockResolvedValue([]);

    renderOllama();
    await vi.waitFor(() => expect(screen.getByText("Pulling model")).toBeInTheDocument());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(localAi.getStatus).toHaveBeenCalledTimes(6);
    expect(localAi.listModels).toHaveBeenCalledTimes(1);

    await act(async () => {
      inventory.resolve([]);
      await inventory.promise;
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await vi.waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(7));
    await vi.waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(2));
    vi.useRealTimers();
  });

  it("locks provider and model controls for the full runtime operation", async () => {
    const pull = deferred<LocalAiStatus>();
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel.mockImplementationOnce(() => pull.promise);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    expect(screen.getByRole("combobox", { name: "LLM provider" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Installed Ollama model" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();

    pull.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "pull_model",
        state: "succeeded",
        result: pullResult(),
      },
    }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "LLM provider" })).not.toBeDisabled());
  });

  it("does not offer cancellation until the backend acknowledges the exact operation", async () => {
    const install = deferred<LocalAiStatus>();
    localAi.install.mockImplementationOnce(() => install.promise);
    renderOllama();

    expect(await screen.findByText("Not installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install runtime" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download and install" }));

    expect(screen.queryByRole("button", { name: "Cancel local AI operation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop runtime" })).not.toBeInTheDocument();

    await act(async () => {
      install.resolve(status({
        installed: false,
        state: "downloading",
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "install", state: "running" },
      }));
      await install.promise;
    });

    expect(await screen.findByRole("button", { name: "Cancel local AI operation" })).toBeInTheDocument();
  });

  it("keeps an ambiguous mutation locked across unrelated status and retries the same admission", async () => {
    const unrelatedStatus = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: null,
    });
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValueOnce(unrelatedStatus)
      .mockResolvedValueOnce(unrelatedStatus)
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "succeeded",
          result: pullResult(),
        },
      }));
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel
      .mockRejectedValueOnce(new Error("operation acknowledgement timed out"))
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "running",
        },
      }));
    renderOllama();

    await waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Pull model" }));
    fireEvent.click(screen.getByRole("button", { name: "Download model" }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));

    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop runtime" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel local AI operation" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.pullModel).toHaveBeenCalledTimes(1);
    expect(localAi.pullModel).toHaveBeenNthCalledWith(1, "qwen3:8b", ADMISSION_A);

    await waitFor(() => expect(localAi.pullModel).toHaveBeenCalledTimes(2), { timeout: 4_000 });
    expect(localAi.pullModel).toHaveBeenNthCalledWith(2, "qwen3:8b", ADMISSION_A);
    expect(screen.getByRole("button", { name: "Cancel local AI operation" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await waitFor(
      () => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled(),
      { timeout: 4_000 },
    );
    expect(screen.queryByRole("button", { name: "Cancel local AI operation" })).not.toBeInTheDocument();
  });

  it("retries the same admission while reconciliation status reads are failing", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockRejectedValue(new Error("runtime status unavailable"));
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel
      .mockRejectedValueOnce(new Error("operation acknowledgement timed out"))
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "running",
        },
      }));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(screen.getByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    await waitFor(() => expect(localAi.pullModel).toHaveBeenCalledTimes(2), { timeout: 4_000 });
    expect(localAi.pullModel).toHaveBeenNthCalledWith(1, "qwen3:8b", ADMISSION_A);
    expect(localAi.pullModel).toHaveBeenNthCalledWith(2, "qwen3:8b", ADMISSION_A);
  });

  it("refreshes stale status after a definitive client rejection before unlocking controls", async () => {
    const refreshed = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => refreshed.promise);
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "another operation is already running",
      { statusCode: 409 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    await waitFor(() => expect(screen.getByText("another operation is already running")).toBeInTheDocument());
    expect(screen.getByText("Refreshing status")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      refreshed.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }));
      await refreshed.promise;
    });

    expect(screen.getByText("another operation is already running")).toBeInTheDocument();
    expect(screen.queryByText("Refreshing status")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled();
  });

  it("retains reconciliation after a server error until the matching receipt is visible", async () => {
    const reconciliation = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => reconciliation.promise);
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "managed runtime write failed",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));

    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      reconciliation.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "failed",
          error: "model pull failed",
        },
      }));
      await reconciliation.promise;
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
  });

  it("replaces stale model inventory and clears acknowledgement errors after cancellation", async () => {
    const staleInventory = deferred<LocalAiModel[]>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "cancelled",
        },
      }));
    localAi.listModels
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => staleInventory.promise)
      .mockResolvedValue([trustedModel()]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "model pull acknowledgement timed out",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("Local AI operation cancelled.")).toBeInTheDocument();
    expect(screen.queryByText("model pull acknowledgement timed out")).not.toBeInTheDocument();
    expect(await screen.findByText("Model installed")).toBeInTheDocument();

    await act(async () => {
      staleInventory.resolve([]);
      await staleInventory.promise;
    });
    expect(screen.getByText("Model installed")).toBeInTheDocument();
  });

  it("keeps controls locked while duplicate cancelled receipts share one inventory replacement", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mutationReceipt = deferred<LocalAiStatus>();
    const pollingReceipt = deferred<LocalAiStatus>();
    const staleInventory = deferred<LocalAiModel[]>();
    const authoritativeInventory = deferred<LocalAiModel[]>();
    const unexpectedDuplicateInventory = deferred<LocalAiModel[]>();
    const cancelled = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "pull_model",
        state: "cancelled",
      },
    });
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => pollingReceipt.promise);
    localAi.listModels
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => staleInventory.promise)
      .mockImplementationOnce(() => authoritativeInventory.promise)
      .mockImplementation(() => unexpectedDuplicateInventory.promise);
    localAi.pullModel.mockImplementationOnce(() => mutationReceipt.promise);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      pollingReceipt.resolve(cancelled);
      mutationReceipt.resolve(cancelled);
      await Promise.resolve();
    });

    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      authoritativeInventory.resolve([trustedModel()]);
      await authoritativeInventory.promise;
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
    expect(localAi.listModels).toHaveBeenCalledTimes(3);

    await act(async () => {
      staleInventory.resolve([]);
      await staleInventory.promise;
    });
    expect(screen.getByText("Model installed")).toBeInTheDocument();
  });

  it("ignores a late mutation failure after polling proves cancellation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mutationReceipt = deferred<LocalAiStatus>();
    const pollingReceipt = deferred<LocalAiStatus>();
    const staleInventory = deferred<LocalAiModel[]>();
    const authoritativeInventory = deferred<LocalAiModel[]>();
    const cancelled = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "pull_model",
        state: "cancelled",
      },
    });
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => pollingReceipt.promise);
    localAi.listModels
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => staleInventory.promise)
      .mockImplementationOnce(() => authoritativeInventory.promise);
    localAi.pullModel.mockImplementationOnce(() => mutationReceipt.promise);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
      pollingReceipt.resolve(cancelled);
      await Promise.resolve();
    });
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      mutationReceipt.reject(new LocalAiApiError("late acknowledgement conflict", { statusCode: 409 }));
      await Promise.resolve();
    });
    expect(screen.queryByText("late acknowledgement conflict")).not.toBeInTheDocument();
    expect(screen.getByText("Local AI operation cancelled.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.listModels).toHaveBeenCalledTimes(3);

    await act(async () => {
      authoritativeInventory.resolve([trustedModel()]);
      staleInventory.resolve([]);
      await Promise.all([authoritativeInventory.promise, staleInventory.promise]);
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
    expect(screen.getByText("Model installed")).toBeInTheDocument();
  });

  it("ignores a late mutation response after polling proves failure", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mutationReceipt = deferred<LocalAiStatus>();
    const pollingReceipt = deferred<LocalAiStatus>();
    const staleInventory = deferred<LocalAiModel[]>();
    const authoritativeInventory = deferred<LocalAiModel[]>();
    const failed = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "pull_model",
        state: "failed",
        error: "model pull failed after partial download",
      },
    });
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => pollingReceipt.promise)
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }));
    localAi.listModels
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => staleInventory.promise)
      .mockImplementationOnce(() => authoritativeInventory.promise);
    localAi.pullModel.mockImplementationOnce(() => mutationReceipt.promise);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
      pollingReceipt.resolve(failed);
      await Promise.resolve();
    });
    await waitFor(() => expect(localAi.listModels).toHaveBeenCalledTimes(3));

    await act(async () => {
      authoritativeInventory.resolve([]);
      staleInventory.resolve([]);
      await Promise.all([authoritativeInventory.promise, staleInventory.promise]);
    });
    expect(screen.getByText("model pull failed after partial download")).toBeInTheDocument();
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      mutationReceipt.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }));
      await mutationReceipt.promise;
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByText("model pull failed after partial download")).toBeInTheDocument();
  });

  it("surfaces an indeterminate receipt instead of treating it as success", async () => {
    const reconciliation = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => reconciliation.promise);
    localAi.listModels.mockResolvedValue([{ name: "qwen3:8b", digest: "b".repeat(64) }]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "managed runtime receipt unavailable",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));

    await act(async () => {
      reconciliation.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "indeterminate",
          error: "Managed Ollama operation outcome is unknown",
        },
      }));
      await reconciliation.promise;
    });

    await waitFor(() => expect(screen.getByText("Managed Ollama operation outcome is unknown")).toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "LLM provider" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    const pullButton = screen.getByRole("button", { name: "Pull model" });
    expect(pullButton).toBeDisabled();
    fireEvent.click(pullButton);
    expect(localAi.pullModel).toHaveBeenCalledTimes(1);
  });

  it("requires exact operator acknowledgement before clearing an older unknown-outcome block", async () => {
    const unresolved = {
      id: OPERATION_A,
      admission_id: ADMISSION_A,
      kind: "pull_model" as const,
      state: "indeterminate" as const,
      finished_at: 2,
      error: "Managed Ollama operation outcome is unknown",
    };
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_B,
        admission_id: ADMISSION_B,
        kind: "start",
        state: "succeeded",
      },
      unresolved_operation: unresolved,
    }));
    localAi.listModels.mockResolvedValue([]);
    renderOllama();

    const review = await screen.findByRole("button", { name: "Review unknown outcome" });
    expect(screen.getByRole("combobox", { name: "LLM provider" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    fireEvent.click(review);

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(`${OPERATION_A} / ${ADMISSION_A}`)).toBeInTheDocument();
    expect(within(dialog).getByText(/will not replay the unknown operation/i)).toBeInTheDocument();
    expect(localAi.reconcileOperation).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Acknowledge unknown outcome" }));

    await waitFor(() => expect(localAi.reconcileOperation).toHaveBeenCalledWith(OPERATION_A, ADMISSION_A));
    expect(await screen.findByText(/original admission remains consumed and will not be retried/i))
      .toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
    expect(localAi.pullModel).not.toHaveBeenCalled();
  });

  it.each([
    ["failed", "durable model pull failed"],
    ["indeterminate", "durable model pull outcome is unknown"],
  ] as const)("preserves a durable %s receipt diagnostic across manual refresh", async (stateValue, error) => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "pull_model",
        state: stateValue,
        error,
      },
    }));
    localAi.listModels.mockResolvedValue([]);
    renderOllama();

    expect(await screen.findByText(error)).toBeInTheDocument();
    if (stateValue === "indeterminate") {
      expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    }

    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText(error)).toBeInTheDocument();
  });

  it("keeps an honest reason when an operation-less refresh retains an indeterminate block", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "indeterminate",
          error: "durable model pull outcome is unknown",
        },
      }))
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: null,
      }));
    localAi.listModels.mockResolvedValue([]);
    renderOllama();

    expect(await screen.findByText("durable model pull outcome is unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Local AI operation outcome is unknown")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
  });

  it("does not misclassify a status without an operation receipt as a direct result", async () => {
    const responseWithoutOperation = status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }) as Partial<LocalAiStatus>;
    delete responseWithoutOperation.operation;
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.pullModel.mockResolvedValue(responseWithoutOperation);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.pullModel).toHaveBeenCalledWith("qwen3:8b", ADMISSION_A));
    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.createAdmissionId).toHaveBeenCalledTimes(1);
  });

  it("keeps the admission locked when a successful response has no recognised schema", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([]);
    localAi.pullModel.mockResolvedValueOnce({});
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    expect(await screen.findByText(/unverified operation response/i)).toBeInTheDocument();
    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.createAdmissionId).toHaveBeenCalledTimes(1);
    expect(localAi.pullModel).toHaveBeenCalledTimes(1);
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);
  });

  it("does not complete model deletion from a prune-shaped receipt", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([
      { name: "qwen3:8b", size: 5_000_000_000 },
      { name: "other:latest", size: 2_000_000_000 },
    ]);
    localAi.deleteModel.mockResolvedValueOnce({ deleted: [], pruned: ["other:latest"] });
    renderOllama({ model: "qwen3:8b" });

    fireEvent.click(await screen.findByRole("button", { name: "Delete other:latest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete model" }));

    expect(await screen.findByText(/unverified operation response/i)).toBeInTheDocument();
    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(localAi.deleteModel).toHaveBeenCalledTimes(1);
  });

  it("rejects a same-admission durable receipt for a different operation kind", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValue(status({
        installed: true,
        state: "starting",
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "start",
          state: "running",
        },
      }));
    localAi.listModels.mockResolvedValue([]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "model pull acknowledgement timed out",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    expect(await screen.findByText(/receipt for the wrong operation/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Cancel local AI operation" })).not.toBeInTheDocument();
  });

  it("rejects a same-admission pull receipt for another model", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "pull_model",
          state: "succeeded",
          result: pullResult("other:latest", "c".repeat(64)),
        },
      }));
    localAi.listModels.mockResolvedValue([]);
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "model pull acknowledgement timed out",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    expect(await screen.findByText(/unverified durable receipt/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
  });

  it("rejects a same-admission durable digest receipt for a different digest", async () => {
    const currentDigest = "b".repeat(64);
    const wrongDigest = "c".repeat(64);
    const onChange = vi.fn();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValue(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "accept_model_digest",
          state: "succeeded",
          result: {
            accepted: true,
            model: `flinttrade/sha256-${wrongDigest}:locked`,
            source_model: "qwen3:8b",
            digest: wrongDigest,
          },
        },
      }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    }]);
    localAi.acceptModelDigest.mockRejectedValueOnce(new LocalAiApiError(
      "digest acceptance acknowledgement timed out",
      { statusCode: 500 },
    ));
    renderOllama({ onChange });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));

    expect(await screen.findByText(/unverified durable receipt/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
  });

  it("keeps model controls locked until digest acceptance reconciliation finishes", async () => {
    const currentDigest = "b".repeat(64);
    const lockedAlias = `flinttrade/sha256-${currentDigest}:locked`;
    const acceptance = deferred<{
      accepted: boolean;
      model: string;
      source_model: string;
      digest: string;
    }>();
    const reconciliation = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => reconciliation.promise);
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    }]);
    localAi.acceptModelDigest.mockImplementationOnce(() => acceptance.promise);
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      acceptance.resolve({
        accepted: true,
        model: lockedAlias,
        source_model: "qwen3:8b",
        digest: currentDigest,
      });
      await acceptance.promise;
    });
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    reconciliation.resolve(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled());
  });

  it("does not activate Ollama when digest acceptance resolves after unmount", async () => {
    const currentDigest = "b".repeat(64);
    const acceptance = deferred<{
      accepted: boolean;
      model: string;
      source_model: string;
      digest: string;
    }>();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    }]);
    localAi.acceptModelDigest.mockReturnValue(acceptance.promise);
    const view = renderOllama({ onProviderChange, providerActivationRequired: true });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));
    view.unmount();

    await act(async () => {
      acceptance.resolve({
        accepted: true,
        model: `flinttrade/sha256-${currentDigest}:locked`,
        source_model: "qwen3:8b",
        digest: currentDigest,
      });
      await acceptance.promise;
    });

    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("recovers a timed-out digest acceptance from the matching durable receipt result", async () => {
    const currentDigest = "b".repeat(64);
    const lockedAlias = `flinttrade/sha256-${currentDigest}:locked`;
    const receipt = deferred<LocalAiStatus>();
    const onChange = vi.fn();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockImplementationOnce(() => receipt.promise);
    localAi.listModels.mockResolvedValueOnce([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: "a".repeat(64),
      digest_drift: true,
    }]).mockResolvedValue([trustedModel("qwen3:8b", currentDigest)]);
    localAi.acceptModelDigest.mockRejectedValueOnce(new Error("acceptance acknowledgement timed out"));
    renderOllama({ onChange });

    fireEvent.click(await screen.findByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept exact digest" }));
    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Reconciling operation")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();

    await act(async () => {
      receipt.resolve(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "accept_model_digest",
          state: "succeeded",
          result: {
            accepted: true,
            model: lockedAlias,
            source_model: "qwen3:8b",
            digest: currentDigest,
          },
        },
      }));
      await receipt.promise;
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("model", lockedAlias));
    expect(localAi.acceptModelDigest).toHaveBeenCalledWith("qwen3:8b", currentDigest, ADMISSION_A);
    expect(screen.queryByText("Reconciling operation")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).not.toBeDisabled();
  });

  it("hides Start when an installed but unready Ollama server is externally owned", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "installed",
      ready: false,
      external_process: true,
    }));
    renderOllama();

    expect(await screen.findByText("External server")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start runtime" })).not.toBeInTheDocument();
  });

  it("reports a ready model pull truthfully with accessible determinate progress", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: { model: "qwen3:8b", status: "pulling", completed: 500, total: 1000 },
    }));
    renderOllama();

    expect(await screen.findByRole("status")).toHaveTextContent("Pulling model");
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    const progressbar = screen.getByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).toHaveAttribute("aria-valuemin", "0");
    expect(progressbar).toHaveAttribute("aria-valuemax", "100");
    expect(progressbar).toHaveAttribute("aria-valuenow", "50");
    expect(progressbar).toHaveAttribute("aria-valuetext", expect.stringMatching(/500 B.*1000 B/i));
  });

  it("announces a zero-total model pull as indeterminate progress", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "pull_model", state: "running" },
      model_pull: {
        model: "qwen3:8b",
        status: "starting",
        completed: 0,
        total: 0,
      },
    }));
    renderOllama();

    const progressbar = await screen.findByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).not.toHaveAttribute("aria-valuenow");
    expect(progressbar).toHaveAttribute("aria-valuetext", "Pulling model in progress");
    expect(screen.queryByText(/unknown size/i)).not.toBeInTheDocument();
  });

  it("shows status as unavailable instead of checking forever after the initial request fails", async () => {
    localAi.getStatus.mockRejectedValueOnce(new Error("authenticated session required"));
    renderOllama();

    expect(await screen.findByRole("alert")).toHaveTextContent("authenticated session required");
    expect(screen.getByRole("status")).toHaveTextContent("Unavailable");
    expect(screen.queryByText("Checking")).not.toBeInTheDocument();
  });

  it("retains idle status but disables new runtime mutations while status is stale", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status())
      .mockRejectedValueOnce(new Error("runtime status unavailable"));
    renderOllama();

    expect(await screen.findByText("Not installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("runtime status unavailable"));

    expect(screen.getByText("Not installed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install runtime" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh runtime status" })).not.toBeDisabled();
    expect(screen.getByRole("combobox", { name: "LLM provider" })).not.toBeDisabled();
  });

  it("does not expose terminal operation bytes as live progress during refresh", async () => {
    const refresh = deferred<LocalAiStatus>();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "installed",
        downloaded_bytes: 500,
        download_total_bytes: 1_000,
        operation: {
          id: OPERATION_A,
          admission_id: ADMISSION_A,
          kind: "update",
          state: "succeeded",
        },
      }))
      .mockImplementationOnce(() => refresh.promise);
    renderOllama();

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime status" }));

    const progressbar = screen.getByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).not.toHaveAttribute("aria-valuenow");
    expect(progressbar).toHaveAttribute("aria-valuetext", "Refreshing status in progress");

    await act(async () => {
      refresh.resolve(status({ installed: true, state: "installed" }));
      await refresh.promise;
    });
  });

  it("ignores stale progress payloads for a different running operation kind", async () => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "starting",
      downloaded_bytes: 500,
      download_total_bytes: 1_000,
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind: "start",
        state: "running",
      },
      model_pull: {
        model: "qwen3:8b",
        status: "pulling",
        completed: 500,
        total: 1_000,
      },
    }));
    renderOllama();

    const progressbar = await screen.findByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).not.toHaveAttribute("aria-valuenow");
    expect(progressbar).toHaveAttribute("aria-valuetext", "Starting in progress");
  });

  it.each([
    ["rollback", "Rolling back"],
    ["uninstall", "Uninstalling"],
    ["accept_model_digest", "Accepting model digest"],
    ["reset_model_digests", "Resetting model trust state"],
    ["delete_model", "Deleting model"],
    ["prune_models", "Pruning model aliases"],
    ["provider_transition", "Changing provider"],
  ] as const)("labels a running %s operation precisely", async (kind, label) => {
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "installed",
      operation: {
        id: OPERATION_A,
        admission_id: ADMISSION_A,
        kind,
        state: "running",
      },
    }));
    renderOllama();

    const progressbar = await screen.findByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).toHaveAttribute("aria-valuetext", `${label} in progress`);
  });

  it("ignores same-kind progress from a different admission", async () => {
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
      }))
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: {
          id: OPERATION_B,
          admission_id: ADMISSION_B,
          kind: "pull_model",
          state: "running",
        },
        model_pull: {
          model: "qwen3:8b",
          status: "pulling",
          completed: 500,
          total: 1_000,
        },
      }));
    localAi.pullModel.mockRejectedValueOnce(new LocalAiApiError(
      "model pull acknowledgement timed out",
      { statusCode: 500 },
    ));
    renderOllama();

    fireEvent.click(await screen.findByRole("button", { name: "Pull model" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download model" }));

    await waitFor(() => expect(localAi.getStatus).toHaveBeenCalledTimes(2));
    const progressbar = screen.getByRole("progressbar", { name: "Local AI operation progress" });
    expect(progressbar).not.toHaveAttribute("aria-valuenow");
    expect(progressbar).toHaveAttribute("aria-valuetext", "Reconciling operation in progress");
    expect(screen.queryByRole("button", { name: "Cancel local AI operation" })).not.toBeInTheDocument();
  });

  it("surfaces the bounded backend reason and correlation diagnostic", async () => {
    localAi.getStatus.mockRejectedValueOnce(new Error(
      "Managed local AI is unavailable on this platform Reason: unsupported linux/riscv64. "
      + "Diagnostic ID: local_0123456789abcdef.",
    ));
    renderOllama();

    expect(await screen.findByRole("alert")).toHaveTextContent("Reason: unsupported linux/riscv64");
    expect(screen.getByRole("alert")).toHaveTextContent("Diagnostic ID: local_0123456789abcdef");
  });

  it("retains a live operation and retries failed polls until the server confirms it is terminal", async () => {
    vi.useFakeTimers();
    localAi.getStatus
      .mockResolvedValueOnce(status({
        installed: true,
        state: "downloading",
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "install", state: "running" },
      }))
      .mockRejectedValueOnce(new Error("runtime status unavailable"))
      .mockResolvedValueOnce(status({
        installed: true,
        state: "ready",
        ready: true,
        managed_process: true,
        operation: { id: OPERATION_A, admission_id: ADMISSION_A, kind: "install", state: "succeeded" },
      }));
    renderOllama();

    await vi.waitFor(() => expect(screen.getByText("Installing")).toBeInTheDocument());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await vi.waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("runtime status unavailable"));
    expect(screen.getByRole("status")).toHaveTextContent("Installing");
    expect(screen.getByRole("progressbar", { name: "Local AI operation progress" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel local AI operation" })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(localAi.getStatus).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    await vi.waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
    expect(localAi.getStatus).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("progressbar", { name: "Local AI operation progress" })).not.toBeInTheDocument();
  });

  it("surfaces bounded processor, runtime-log, and model-drift diagnostics", async () => {
    const longProcessor = `GPU ${"x".repeat(400)}`;
    const longLogError = `log unavailable ${"y".repeat(400)}`;
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
      inference_processor: longProcessor,
      log_error: longLogError,
      model_digest_drift: {
        "qwen3:latest": { accepted: "a".repeat(64), current: "b".repeat(64) },
      },
    }));
    renderOllama();

    const processor = await screen.findByText(/Inference processor GPU/i);
    const logError = screen.getByText(/Runtime log diagnostic log unavailable/i);
    expect(processor.textContent?.length).toBeLessThanOrEqual(240);
    expect(logError.textContent?.length).toBeLessThanOrEqual(280);
    expect(screen.getByText(/Digest drift reported for qwen3:latest/i)).toBeInTheDocument();
  });
});

describe("LLMSection provider configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    llmApi.testConnection.mockResolvedValue({
      status: "success",
      data: { provider: "grok", model: "grok-3-mini" },
    });
  });

  it("locks provider, model, and credential edits until hydration completes", () => {
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o-mini", apiKey: "" }}
        hydrationState="loading"
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("combobox", { name: "LLM provider" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(screen.getByLabelText("LLM provider API key")).toBeDisabled();
  });

  it("uses the selected provider's model default instead of carrying the previous model", async () => {
    renderOllama();

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(screen.getByRole("textbox", { name: "LLM model name" })).toHaveValue("gpt-4o-mini");
    expect(screen.getByRole("textbox", { name: "LLM model name" }))
      .toHaveAttribute("placeholder", "gpt-4o-mini");
  });

  it("requires a nonblank Custom model and associates the error with its field", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    renderOllama({ onProviderChange });

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));
    fireEvent.change(screen.getByLabelText("LLM host URL"), {
      target: { value: "https://custom.example.test/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    const model = screen.getByRole("textbox", { name: "LLM model name" });
    const error = screen.getByText("Model is required");
    expect(model).toHaveValue("");
    expect(model).toHaveAttribute("aria-invalid", "true");
    expect(model).toHaveAttribute("aria-describedby", "llm-settings-model-error");
    expect(error).toHaveAttribute("id", "llm-settings-model-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(onProviderChange).not.toHaveBeenCalled();
  });

  it("renders the persisted Claude Code OAuth auth marker as the active choice", () => {
    render(
      <LLMSection
        settings={{
          provider: "anthropic",
          authMode: "claude-code-oauth",
          host: "",
          model: "claude-3-5-haiku-20241022",
          apiKey: "",
        }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("combobox", { name: "LLM provider" })).toHaveTextContent("Claude Code (OAuth)");
    expect(screen.getByText(/Claude Code OAuth credential/i)).toBeInTheDocument();
  });

  it("commits Claude Code OAuth as Anthropic plus a separate auth marker", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o-mini", apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={onProviderChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Claude Code (OAuth)" }));
    fireEvent.change(screen.getByLabelText("Claude Code OAuth credential"), {
      target: { value: "oauth-credential" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "anthropic",
      "",
      "claude-3-5-haiku-20241022",
      "oauth-credential",
      "claude-code-oauth",
    ));
  });

  it.each(["Hermes (Nous)", "Custom Endpoint"])(
    "does not retain the managed Ollama host when selecting %s",
    async (providerName) => {
      const onProviderChange = vi.fn().mockResolvedValue(undefined);
      renderOllama({ onProviderChange });

      fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
      fireEvent.click(await screen.findByRole("option", { name: providerName }));

      expect(screen.getByLabelText("LLM host URL")).toHaveValue("");
      expect(onProviderChange).not.toHaveBeenCalled();
    },
  );

  it("validates a required host before committing a provider change", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    renderOllama({ onProviderChange });

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));
    expect(screen.getByText("Host URL is required for Custom Endpoint")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("LLM host URL"), {
      target: { value: "http://127.0.0.1:9000" },
    });
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "custom-secret" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "LLM model name" }), {
      target: { value: "custom-model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "custom",
      "http://127.0.0.1:9000",
      "custom-model",
      "custom-secret",
    ));
  });

  it("keeps host-based credentials in the draft and applies them atomically", async () => {
    const applyProvider = deferred<void>();
    const onProviderChange = vi.fn(() => applyProvider.promise);
    const view = renderOllama({ onProviderChange });

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Custom Endpoint" }));

    expect(screen.getByLabelText("LLM host URL")).toBeInTheDocument();
    expect(screen.getByLabelText("LLM provider API key")).toHaveValue("");

    fireEvent.change(screen.getByLabelText("LLM host URL"), {
      target: { value: "http://127.0.0.1:9000" },
    });
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "custom-secret" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "LLM model name" }), {
      target: { value: "custom-model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));
    expect(screen.getByLabelText("LLM provider API key")).toBeDisabled();
    expect(onProviderChange).toHaveBeenCalledWith(
      "custom",
      "http://127.0.0.1:9000",
      "custom-model",
      "custom-secret",
    );

    applyProvider.resolve();
    await act(async () => {
      await applyProvider.promise;
    });
    view.rerender(
      <LLMSection
        settings={{
          provider: "custom",
          host: "http://127.0.0.1:9000",
          model: "qwen3:8b",
          apiKey: "",
        }}
        onChange={vi.fn()}
        onProviderChange={onProviderChange}
      />,
    );

    expect(await screen.findByLabelText("LLM provider API key")).toBeInTheDocument();
  });

  it("retains a failed setup provider target and credential for an explicit retry", async () => {
    const onProviderChange = vi.fn()
      .mockRejectedValueOnce(new Error("workspace locked"))
      .mockResolvedValueOnce(undefined);
    const onChange = vi.fn();
    const view = render(
      <LLMSection
        settings={{
          provider: "custom",
          host: "http://127.0.0.1:9000",
          model: "private-model",
          apiKey: "",
        }}
        onChange={onChange}
        onProviderChange={onProviderChange}
        providerActivationRequired
      />,
    );

    expect(onProviderChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "custom-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Activate provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "custom",
      "http://127.0.0.1:9000",
      "private-model",
      "custom-secret",
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent("workspace locked");
    view.rerender(
      <LLMSection
        settings={{
          provider: "openai",
          host: "",
          model: "gpt-4o",
          apiKey: "",
        }}
        onChange={onChange}
        onProviderChange={onProviderChange}
        providerActivationRequired
      />,
    );

    expect(screen.getByRole("combobox", { name: "LLM provider" })).toHaveTextContent("Custom Endpoint");
    expect(screen.getByLabelText("LLM provider API key")).toHaveValue("custom-secret");
    fireEvent.click(screen.getByRole("button", { name: "Retry provider setup" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledTimes(2));
    expect(onProviderChange).toHaveBeenLastCalledWith(
      "custom",
      "http://127.0.0.1:9000",
      "private-model",
      "custom-secret",
    );
  });

  it("activates a no-key Hermes setup only once under StrictMode", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    render(
      <StrictMode>
        <LLMSection
          settings={{
            provider: "hermes",
            host: "http://127.0.0.1:8000",
            model: "hermes-3",
            apiKey: "",
          }}
          onChange={vi.fn()}
          onProviderChange={onProviderChange}
          providerActivationRequired
        />
      </StrictMode>,
    );

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledTimes(1));
    expect(onProviderChange).toHaveBeenCalledWith(
      "hermes",
      "http://127.0.0.1:8000",
      "hermes-3",
    );
  });

  it("keeps model edits inside a provider draft until its transaction succeeds", async () => {
    const providerChange = deferred<void>();
    const onChange = vi.fn();
    const onProviderChange = vi.fn(() => providerChange.promise);
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o", apiKey: "secret" }}
        onChange={onChange}
        onProviderChange={onProviderChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "LLM provider" }));
    fireEvent.click(await screen.findByRole("option", { name: "Anthropic" }));
    fireEvent.change(screen.getByRole("textbox", { name: "LLM model name" }), {
      target: { value: "claude-3-5-haiku" },
    });
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-ant-replacement" },
    });

    expect(onChange).not.toHaveBeenCalledWith("model", "claude-3-5-haiku");
    expect(onProviderChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply provider" }));

    expect(screen.getByLabelText("LLM provider API key")).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "LLM model name" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "LLM provider" })).toBeDisabled();
    expect(onProviderChange).toHaveBeenCalledWith(
      "anthropic",
      "",
      "claude-3-5-haiku",
      "sk-ant-replacement",
    );

    providerChange.resolve();
    await act(async () => {
      await providerChange.promise;
    });
  });

  it("turns an active Custom host edit into a credential-isolated provider draft", () => {
    const onChange = vi.fn();
    render(
      <LLMSection
        settings={{
          provider: "custom",
          host: "http://127.0.0.1:9000",
          model: "private-model",
          apiKey: "",
        }}
        onChange={onChange}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.change(screen.getByLabelText("LLM host URL"), { target: { value: "   " } });

    expect(onChange).not.toHaveBeenCalledWith("host", "   ");
    expect(screen.getByLabelText("LLM provider API key")).toHaveValue("");
    expect(screen.getByRole("alert")).toHaveTextContent("Host URL is required for Custom Endpoint");
  });

  it("tests Grok through the backend client without browser-fetching the provider", async () => {
    const browserFetch = vi.spyOn(globalThis, "fetch");
    render(
      <LLMSection
        settings={{ provider: "grok", host: "", model: "grok-3-mini", apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => expect(llmApi.testConnection).toHaveBeenCalledWith({
      provider: "grok",
      host: "",
      model: "grok-3-mini",
    }));
    expect(browserFetch).not.toHaveBeenCalled();
    expect(await screen.findByText(/Connection successful.*grok.*grok-3-mini/i)).toBeInTheDocument();
    browserFetch.mockRestore();
  });

  it("invalidates an in-flight connection result when the visible model changes", async () => {
    const connection = deferred<{
      status: "success";
      data: { provider: string; model: string };
    }>();
    const onChange = vi.fn();
    llmApi.testConnection.mockImplementationOnce(() => connection.promise);
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o", apiKey: "sk-openai" }}
        onChange={onChange}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));
    fireEvent.change(screen.getByRole("textbox", { name: "LLM model name" }), {
      target: { value: "gpt-4.1" },
    });
    await act(async () => {
      connection.resolve({ status: "success", data: { provider: "openai", model: "gpt-4o" } });
      await connection.promise;
    });

    expect(onChange).toHaveBeenCalledWith("model", "gpt-4.1");
    expect(screen.queryByText(/Connection successful/i)).not.toBeInTheDocument();
  });

  it("clears a successful connection result when the active API key changes", async () => {
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o", apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));
    expect(await screen.findByText(/Connection successful/i)).toHaveAttribute("role", "status");

    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-replacement" },
    });
    expect(screen.queryByText(/Connection successful/i)).not.toBeInTheDocument();
  });

  it("invalidates and supersedes an in-flight connection test when the runtime stops", async () => {
    const connection = deferred<{ status: "success"; data: { provider: string; model: string } }>();
    llmApi.testConnection.mockReturnValue(connection.promise);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    renderOllama();

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));
    await waitFor(() => expect(llmApi.testConnection).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Stop runtime" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stop runtime" }));

    await act(async () => {
      connection.resolve({ status: "success", data: { provider: "ollama", model: "qwen3:8b" } });
      await connection.promise;
    });
    expect(screen.queryByText(/Connection successful/i)).not.toBeInTheDocument();
  });

  it("invalidates a successful connection result before accepting a changed model digest", async () => {
    const currentDigest = "c".repeat(64);
    localAi.getStatus.mockResolvedValue(status({
      installed: true,
      state: "ready",
      ready: true,
      managed_process: true,
    }));
    localAi.listModels.mockResolvedValue([{
      name: "qwen3:8b",
      digest: currentDigest,
      accepted_digest: "b".repeat(64),
      digest_drift: true,
    }]);
    llmApi.testConnection.mockResolvedValue({
      status: "success",
      data: { provider: "ollama", model: "qwen3:8b" },
    });
    renderOllama();

    expect(await screen.findByText(/Mutable-tag drift detected/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));
    expect(await screen.findByText(/Connection successful/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept current model digest" }));
    fireEvent.click(screen.getByRole("button", { name: "Accept exact digest" }));

    expect(screen.queryByText(/Connection successful/i)).not.toBeInTheDocument();
  });

  it("keeps an active API key local until Replace credential is explicitly invoked", async () => {
    const onChange = vi.fn();
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    const onDraftStateChange = vi.fn();
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o-mini", apiKey: "" }}
        onChange={onChange}
        onProviderChange={onProviderChange}
        onDraftStateChange={onDraftStateChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "sk-replacement" },
    });

    expect(onChange).not.toHaveBeenCalledWith("apiKey", expect.anything());
    expect(onProviderChange).not.toHaveBeenCalled();
    expect(onDraftStateChange).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Replace credential" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "openai",
      "",
      "gpt-4o-mini",
      "sk-replacement",
    ));
    expect(screen.getByLabelText("LLM provider API key")).toHaveValue("");
    await waitFor(() => expect(onDraftStateChange).toHaveBeenLastCalledWith(false));
  });

  it("requires confirmation before removing the active credential", async () => {
    const onCredentialRemove = vi.fn().mockResolvedValue(undefined);
    render(
      <LLMSection
        settings={{ provider: "openai", host: "", model: "gpt-4o-mini", apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
        credentialConfigured
        credentialLast4="live"
        onCredentialRemove={onCredentialRemove}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove credential" }));
    expect(screen.getByText("Remove stored LLM credential?")).toBeInTheDocument();
    expect(onCredentialRemove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Remove stored credential" }));
    await waitFor(() => expect(onCredentialRemove).toHaveBeenCalledTimes(1));
  });

  it("tests a Custom host draft without sending the active destination's credential", async () => {
    render(
      <LLMSection
        settings={{
          provider: "custom",
          host: "https://old.example.test/v1",
          model: "private-model",
          apiKey: "old-secret",
        }}
        onChange={vi.fn()}
        onProviderChange={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.change(screen.getByLabelText("LLM host URL"), {
      target: { value: "https://new.example.test/v1" },
    });
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "new-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => expect(llmApi.testConnection).toHaveBeenCalledWith({
      provider: "custom",
      host: "https://new.example.test/v1",
      model: "private-model",
      apiKey: "new-secret",
    }));
    expect(llmApi.testConnection).not.toHaveBeenCalledWith(expect.objectContaining({
      apiKey: "old-secret",
    }));
  });

  it("collects a cloud setup credential before the authenticated provider transaction", async () => {
    const onProviderChange = vi.fn().mockResolvedValue(undefined);
    render(
      <LLMSection
        settings={{ provider: "grok", host: "", model: "grok-3-mini", apiKey: "" }}
        onChange={vi.fn()}
        onProviderChange={onProviderChange}
        providerActivationRequired
      />,
    );

    expect(onProviderChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("LLM provider API key"), {
      target: { value: "xai-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Activate provider" }));

    await waitFor(() => expect(onProviderChange).toHaveBeenCalledWith(
      "grok",
      "",
      "grok-3-mini",
      "xai-secret",
    ));
  });
});
