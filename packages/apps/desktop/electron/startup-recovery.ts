import type { BootstrapResult } from "./bootstrap";
import type { createBootstrapState } from "./state";

type BootstrapState = ReturnType<typeof createBootstrapState>;

interface BootstrapController {
  cancel(): Promise<boolean>;
  retry(): Promise<BootstrapResult>;
  shutdown(timeoutMs?: number): Promise<void>;
  start(): Promise<BootstrapResult>;
}

interface StartupRecovery {
  cancel(): boolean;
  recover(signal: AbortSignal): Promise<{ status: "idle" | "promoted" | "rolled-back" }>;
  settleForQuit(): Promise<void>;
}

export interface StartupRecoveryControllerOptions {
  bootstrap: BootstrapController;
  heartbeatIntervalMs?: number;
  recovery: StartupRecovery;
  state: BootstrapState;
}

type StartupStage = "bootstrap" | "idle" | "recovery" | "recovery-failed";

const RECOVERY_FAILURE = "Source update recovery failed. Retry recovery or inspect the private desktop log.";
const RECOVERY_MESSAGE = "Reconciling interrupted source updates";
export const STARTUP_RECOVERY_HEARTBEAT_INTERVAL_MS = 4_000;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function createStartupRecoveryController(options: StartupRecoveryControllerOptions): BootstrapController {
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? STARTUP_RECOVERY_HEARTBEAT_INTERVAL_MS;
  if (!Number.isSafeInteger(heartbeatIntervalMs) || heartbeatIntervalMs <= 0) {
    throw new Error("Startup recovery heartbeat interval must be a positive safe integer.");
  }
  let stage: StartupStage = "idle";
  let recoveryAttempt = 0;
  let recoveryAbort: AbortController | null = null;
  let current: Promise<BootstrapResult> | null = null;
  let shutdownSettlement: Promise<void> | null = null;
  let shuttingDown = false;

  const shutdownResult = (): BootstrapResult => ({
    error: "Source update recovery is shutting down.",
    ok: false,
  });

  const settleShutdown = (): Promise<void> => {
    if (shutdownSettlement) return shutdownSettlement;
    let attempt: Promise<void>;
    attempt = (async () => {
      if (current) await current;
      await options.recovery.settleForQuit();
    })().catch((error: unknown) => {
      if (shutdownSettlement === attempt) shutdownSettlement = null;
      throw error;
    });
    shutdownSettlement = attempt;
    return attempt;
  };

  const runRecovery = (retry: boolean): Promise<BootstrapResult> => {
    if (shuttingDown) return Promise.resolve(shutdownResult());
    if (current) return current;
    let attempt: number;
    if (retry) {
      if (!options.state.retry()) {
        return Promise.resolve({ error: "Source update recovery is not retryable.", ok: false });
      }
      attempt = options.state.getSnapshot().attempt;
      options.state.publishForAttempt(attempt, {
        message: "Retrying interrupted source update recovery",
        phase: "checking-source",
        progress: null,
      });
    } else {
      attempt = options.state.begin(RECOVERY_MESSAGE, "checking-source");
    }
    recoveryAttempt = attempt;
    const abort = new AbortController();
    recoveryAbort = abort;
    stage = "recovery";
    const running = (async (): Promise<BootstrapResult> => {
      try {
        const heartbeat = setInterval(() => {
          if (!abort.signal.aborted) {
            options.state.publishForAttempt(attempt, {
              message: RECOVERY_MESSAGE,
              phase: "checking-source",
              progress: null,
            });
          }
        }, heartbeatIntervalMs);
        heartbeat.unref?.();
        let outcome: Awaited<ReturnType<StartupRecovery["recover"]>>;
        try {
          outcome = await options.recovery.recover(abort.signal);
        } finally {
          clearInterval(heartbeat);
        }
        if (abort.signal.aborted && outcome.status === "idle") {
          throw abort.signal.reason ?? new DOMException("Source update recovery was cancelled.", "AbortError");
        }
      } catch (error) {
        const snapshot = options.state.getSnapshot();
        const cancelled = isAbort(error) ||
          (snapshot.attempt === attempt && snapshot.status === "failed" && snapshot.phase === "cancelled");
        if (cancelled) {
          options.state.cancel(attempt);
          stage = "recovery-failed";
          return { cancelled: true, error: "Source update recovery was cancelled.", ok: false };
        }
        options.state.fail(attempt, RECOVERY_FAILURE);
        stage = "recovery-failed";
        return { error: RECOVERY_FAILURE, ok: false };
      }
      const snapshot = options.state.getSnapshot();
      if (snapshot.attempt !== attempt || snapshot.status !== "running") {
        stage = "recovery-failed";
        return { cancelled: true, error: "Source update recovery was cancelled.", ok: false };
      }
      stage = "bootstrap";
      return options.bootstrap.start();
    })();
    current = running;
    const clear = (): void => {
      if (current === running) current = null;
      if (recoveryAbort === abort) recoveryAbort = null;
    };
    void running.then(clear, clear);
    return running;
  };

  return {
    async cancel(): Promise<boolean> {
      if (stage !== "recovery") return options.bootstrap.cancel();
      recoveryAbort?.abort(new DOMException("Source update recovery was cancelled.", "AbortError"));
      const operationCancelled = options.recovery.cancel();
      if (current) await current;
      const snapshot = options.state.getSnapshot();
      const stateCancelled = snapshot.attempt === recoveryAttempt &&
        snapshot.status === "failed" &&
        snapshot.phase === "cancelled";
      return stateCancelled || operationCancelled;
    },
    retry(): Promise<BootstrapResult> {
      if (shuttingDown) return Promise.resolve(shutdownResult());
      if (stage === "bootstrap") return options.bootstrap.retry();
      if (stage === "recovery-failed") return runRecovery(true);
      if (stage === "idle") return runRecovery(false);
      return current ?? Promise.resolve({ error: "Source update recovery is already running.", ok: false });
    },
    async shutdown(timeoutMs?: number): Promise<void> {
      shuttingDown = true;
      recoveryAbort?.abort(new DOMException("Source update recovery is shutting down.", "AbortError"));
      const boundedTimeoutMs = timeoutMs ?? 10_000;
      const settlement = (async () => {
        await options.bootstrap.shutdown(boundedTimeoutMs);
        await settleShutdown();
      })();
      let timeout: NodeJS.Timeout | undefined;
      return Promise.race([
        settlement,
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error("Source update recovery did not settle before quit.")),
            boundedTimeoutMs,
          );
          timeout.unref?.();
        }),
      ]).finally(() => {
        if (timeout) clearTimeout(timeout);
      });
    },
    start(): Promise<BootstrapResult> {
      if (shuttingDown) return Promise.resolve(shutdownResult());
      if (stage === "bootstrap") return options.bootstrap.start();
      if (stage === "recovery-failed") {
        return Promise.resolve({ error: RECOVERY_FAILURE, ok: false });
      }
      return runRecovery(false);
    },
  };
}
