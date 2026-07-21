export type SourceOperationKind = "bootstrap" | "startup-recovery" | "update-apply" | "update-check";

export type SourceOperationLeaseRetentionPolicy = "command-containment" | "process-exit-required";

export interface SourceOperationLeaseRetentionErrorOptions extends ErrorOptions {
  retentionPolicy?: SourceOperationLeaseRetentionPolicy;
}

export class SourceOperationLeaseRetentionError extends Error {
  readonly retentionPolicy: SourceOperationLeaseRetentionPolicy;

  constructor(message: string, options?: SourceOperationLeaseRetentionErrorOptions) {
    super(message, options);
    this.name = "SourceOperationLeaseRetentionError";
    this.retentionPolicy = options?.retentionPolicy ?? "command-containment";
  }
}

export function isSourceOperationLeaseRetentionError(
  error: unknown,
): error is SourceOperationLeaseRetentionError {
  return error instanceof SourceOperationLeaseRetentionError;
}

export interface SourceOperationLeaseProof {
  assertHeld(): Promise<void>;
  target: string;
}

interface QueuedOperation<T> {
  abort: AbortController;
  externalSignal?: AbortSignal;
  kind: SourceOperationKind;
  reject(error: unknown): void;
  resolve(value: T): void;
  run(signal: AbortSignal): Promise<T>;
}

function cancellation(message: string): DOMException {
  return new DOMException(message, "AbortError");
}

export interface SourceOperationCoordinator {
  cancelActive(kind?: SourceOperationKind): boolean;
  getSnapshot(): Readonly<{ active: SourceOperationKind | null; queued: number; shuttingDown: boolean }>;
  run<T>(kind: SourceOperationKind, externalSignal: AbortSignal | undefined, work: (signal: AbortSignal) => Promise<T>): Promise<T>;
  shutdown(timeoutMs?: number): Promise<void>;
}

export function createSourceOperationCoordinator(): SourceOperationCoordinator {
  const queue: Array<QueuedOperation<unknown>> = [];
  let active: QueuedOperation<unknown> | null = null;
  let shutdownSettlement: Promise<void> | null = null;
  let shuttingDown = false;
  const drainWaiters = new Set<() => void>();

  const notifyDrained = (): void => {
    if (active || queue.length > 0) return;
    for (const resolve of drainWaiters) resolve();
    drainWaiters.clear();
  };

  const removeQueued = (operation: QueuedOperation<unknown>): boolean => {
    const index = queue.indexOf(operation);
    if (index < 0) return false;
    queue.splice(index, 1);
    return true;
  };

  const pump = (): void => {
    if (active || shuttingDown) {
      notifyDrained();
      return;
    }
    const operation = queue.shift();
    if (!operation) {
      notifyDrained();
      return;
    }
    active = operation;
    const onExternalAbort = (): void => operation.abort.abort(operation.externalSignal?.reason);
    operation.externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
    if (operation.externalSignal?.aborted) onExternalAbort();
    let execution: Promise<unknown>;
    try {
      if (operation.abort.signal.aborted) {
        throw operation.abort.signal.reason ?? cancellation("Source operation was cancelled.");
      }
      execution = operation.run(operation.abort.signal);
    } catch (error) {
      execution = Promise.reject(error);
    }
    void execution
      .then(operation.resolve, operation.reject)
      .finally(() => {
        operation.externalSignal?.removeEventListener("abort", onExternalAbort);
        if (active === operation) active = null;
        pump();
      });
  };

  const run = <T>(
    kind: SourceOperationKind,
    externalSignal: AbortSignal | undefined,
    work: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> => {
    if (shuttingDown) return Promise.reject(new Error("Source operation coordinator is shutting down."));
    if (externalSignal?.aborted) return Promise.reject(cancellation("Source operation was cancelled before it started."));
    return new Promise<T>((resolve, reject) => {
      const operation: QueuedOperation<T> = {
        abort: new AbortController(),
        ...(externalSignal ? { externalSignal } : {}),
        kind,
        reject,
        resolve,
        run: work,
      };
      const onQueuedAbort = (): void => {
        if (!removeQueued(operation as QueuedOperation<unknown>)) return;
        reject(cancellation("Queued source operation was cancelled."));
        notifyDrained();
      };
      externalSignal?.addEventListener("abort", onQueuedAbort, { once: true });
      const settle = <V>(callback: (value: V) => void) => (value: V): void => {
        externalSignal?.removeEventListener("abort", onQueuedAbort);
        callback(value);
      };
      operation.resolve = settle(resolve);
      operation.reject = settle(reject);
      queue.push(operation as QueuedOperation<unknown>);
      pump();
    });
  };

  const waitUntilDrained = (): Promise<void> => {
    if (!active && queue.length === 0) return Promise.resolve();
    return new Promise((resolve) => drainWaiters.add(resolve));
  };

  return {
    cancelActive(kind): boolean {
      if (!active || (kind && active.kind !== kind) || active.abort.signal.aborted) return false;
      active.abort.abort(cancellation("Source operation was cancelled."));
      return true;
    },
    getSnapshot: () => Object.freeze({ active: active?.kind ?? null, queued: queue.length, shuttingDown }),
    run,
    shutdown(timeoutMs = 10_000): Promise<void> {
      if (!shutdownSettlement) {
        shuttingDown = true;
        active?.abort.abort(cancellation("Source operation coordinator is shutting down."));
        for (const operation of queue.splice(0)) {
          operation.reject(new Error("Source operation coordinator is shutting down."));
        }
        shutdownSettlement = waitUntilDrained();
        notifyDrained();
      }
      let timeout: NodeJS.Timeout | undefined;
      return Promise.race([
        shutdownSettlement,
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error("Source operation coordinator did not settle before shutdown.")),
            timeoutMs,
          );
          timeout.unref?.();
        }),
      ]).finally(() => {
        if (timeout) clearTimeout(timeout);
      });
    },
  };
}
