import path from "node:path";

import type { BackendDrainResult } from "./backend-drain";
import { SourceOperationLeaseRetentionError } from "./source-operation";
import type { createBackendState } from "./state";

type BackendStateStore = ReturnType<typeof createBackendState>;

export interface RuntimeRunningBackend {
  applicationPid: number | null;
  attempt: number;
  drain(): Promise<BackendDrainResult>;
  guardianPid: number;
  launchToken: string;
  port: number;
  recordPath: string;
  url: string;
}

export interface RuntimeBackendSupervisor {
  cancelCurrent(): Promise<void>;
  getState(): Readonly<{ stoppedSafe: boolean }>;
  start(): Promise<RuntimeRunningBackend>;
}

export interface BackendRuntimeOptions {
  activeSource: string;
  onFailure?(error: Error): Promise<void> | void;
  onReady?(backend: RuntimeRunningBackend): Promise<void> | void;
  onStopped?(): Promise<void> | void;
  platform?: NodeJS.Platform;
  state: BackendStateStore;
  supervisor: RuntimeBackendSupervisor;
}

interface ActiveBackend {
  backend: RuntimeRunningBackend;
  stateAttempt: number;
}

function processExitRetention(message: string, cause?: unknown): SourceOperationLeaseRetentionError {
  return new SourceOperationLeaseRetentionError(message, {
    ...(cause === undefined ? {} : { cause }),
    retentionPolicy: "process-exit-required",
  });
}

function exactStoppedProof(result: BackendDrainResult): boolean {
  return result.outcome === "clean"
    && result.recordRemovalSafe
    && result.childExited
    && (result.proof === "cleanup-complete" || result.proof === "pending-exit-ack");
}

function errorStoppedSafe(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "stoppedSafe" in error
    && (error as { stoppedSafe?: unknown }).stoppedSafe === true;
}

function cancellationReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("Source backend lifecycle was cancelled.", "AbortError");
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error("Backend lifecycle failed.", { cause: value });
}

function observe(callback: (() => Promise<void> | void) | undefined): void {
  if (!callback) return;
  try {
    void Promise.resolve(callback()).catch(() => undefined);
  } catch {
    // Window and recovery observers cannot change backend process authority.
  }
}

/** Joins supervisor evidence to the stricter quit and source-promotion contracts. */
export function createBackendRuntime(options: BackendRuntimeOptions) {
  const platform = options.platform ?? process.platform;
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const normalisePath = (value: string): string => {
    const resolved = pathApi.resolve(value);
    return platform === "win32" ? resolved.toLowerCase() : resolved;
  };
  const expectedActiveSource = normalisePath(options.activeSource);
  let current: ActiveBackend | null = null;
  let starting: Promise<RuntimeRunningBackend> | null = null;
  let startCancellation: AbortController | null = null;

  const settle = async (target: ActiveBackend): Promise<void> => {
    let result: BackendDrainResult;
    try {
      result = await target.backend.drain();
    } catch (error) {
      options.state.fail(target.stateAttempt);
      observe(options.onFailure ? () => options.onFailure!(asError(error)) : undefined);
      throw processExitRetention(
        "Backend cleanup did not produce exact finalised stopped proof.",
        error,
      );
    }
    if (!exactStoppedProof(result)) {
      options.state.fail(target.stateAttempt);
      observe(options.onFailure
        ? () => options.onFailure!(new Error("Backend cleanup remained ambiguous."))
        : undefined);
      throw processExitRetention(
        "Backend cleanup remained ambiguous; Electron quit and source mutation are blocked.",
      );
    }
    if (current === target) current = null;
    options.state.stopped(target.stateAttempt);
    observe(options.onStopped);
  };

  const start = (): Promise<RuntimeRunningBackend> => {
    if (starting) return Promise.reject(new Error("The managed backend is already starting."));
    const cancellation = new AbortController();
    const operation = (async (): Promise<RuntimeRunningBackend> => {
      if (current) {
        if (options.state.getSnapshot().status !== "failed") {
          throw new Error("The managed backend is already running.");
        }
        // An unexpected-exit callback revokes renderer authority immediately,
        // then retry joins the closed guardian's exact cleanup/finalisation proof
        // before allowing a successor attempt.
        await settle(current);
      }
      if (cancellation.signal.aborted) {
        throw Object.assign(new Error("Backend start was cancelled before successor launch."), {
          stoppedSafe: true,
        });
      }
      const stateAttempt = options.state.begin();
      try {
        const backend = await options.supervisor.start();
        const target = { backend, stateAttempt };
        current = target;
        let published: boolean;
        try {
          published = options.state.ready(stateAttempt, backend.port);
        } catch (error) {
          await settle(target);
          throw Object.assign(new Error("Backend readiness returned an invalid loopback origin.", { cause: error }), {
            stoppedSafe: true,
          });
        }
        if (!published) {
          await settle(target);
          throw Object.assign(new Error("A stale backend attempt reached readiness and was stopped."), {
            stoppedSafe: true,
          });
        }
        observe(options.onReady ? () => options.onReady!(backend) : undefined);
        return backend;
      } catch (error) {
        options.state.fail(stateAttempt);
        observe(options.onFailure ? () => options.onFailure!(asError(error)) : undefined);
        throw error;
      }
    })();
    starting = operation;
    startCancellation = cancellation;
    const clear = (): void => {
      if (starting === operation) starting = null;
      if (startCancellation === cancellation) startCancellation = null;
    };
    void operation.then(clear, clear);
    return operation;
  };

  const cancelStarting = async (): Promise<boolean> => {
    const operation = starting;
    if (!operation) return false;
    startCancellation?.abort(new DOMException("Backend start was cancelled.", "AbortError"));
    try {
      await options.supervisor.cancelCurrent();
      await operation.catch(() => undefined);
    } catch (error) {
      throw processExitRetention("Backend startup cancellation did not produce exact stopped proof.", error);
    }
    if (current) {
      await settle(current);
      return true;
    }
    if (!options.supervisor.getState().stoppedSafe) {
      throw processExitRetention("Backend startup cancellation left unresolved cleanup authority.");
    }
    return true;
  };

  const drainForQuit = async (): Promise<void> => {
    await cancelStarting();
    const target = current;
    if (!target) {
      if (options.supervisor.getState().stoppedSafe) return;
      throw processExitRetention("Backend supervisor cleanup is unresolved; Electron quit is blocked.");
    }
    await settle(target);
  };

  const sourceLifecycle = {
    async bootActive(input: { activePath: string; onBackendStopped(): void }): Promise<boolean> {
      if (normalisePath(input.activePath) !== expectedActiveSource) {
        throw new Error("Backend boot is permitted only from the exact managed active source.");
      }
      try {
        await start();
        return true;
      } catch (error) {
        if (errorStoppedSafe(error)) {
          input.onBackendStopped();
          return false;
        }
        throw processExitRetention(
          "Backend start failed without exact stopped and recovery-record proof.",
          error,
        );
      }
    },
    async drainCurrent(input: { onBackendStopped(): void; signal: AbortSignal }): Promise<void> {
      if (input.signal.aborted) throw cancellationReason(input.signal);
      const target = current;
      if (!target) {
        if (!options.supervisor.getState().stoppedSafe) {
          throw processExitRetention("Backend supervisor cleanup is unresolved; source mutation is blocked.");
        }
        input.onBackendStopped();
        if (input.signal.aborted) throw cancellationReason(input.signal);
        return;
      }
      await settle(target);
      input.onBackendStopped();
      if (input.signal.aborted) throw cancellationReason(input.signal);
    },
    isAvailable: () => true,
  };

  return {
    cancelStarting,
    drainForQuit,
    getRunning: (): RuntimeRunningBackend | null => current?.backend ?? null,
    markUnexpectedExit(): void {
      if (!current || !options.state.fail(current.stateAttempt)) return;
      observe(options.onFailure
        ? () => options.onFailure!(new Error("The trading engine stopped unexpectedly."))
        : undefined);
    },
    sourceLifecycle,
    start,
  };
}
