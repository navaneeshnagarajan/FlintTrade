export type BootstrapStatus = "idle" | "running" | "ready" | "failed";
export type BootstrapPhase =
  | "idle"
  | "preparing"
  | "checking-source"
  | "cloning-source"
  | "installing-tools"
  | "syncing-python"
  | "syncing-javascript"
  | "building-terminal"
  | "starting-backend"
  | "cancelled"
  | "complete"
  | "failed";

export interface BootstrapSnapshot {
  attempt: number;
  failure: string | null;
  heartbeatAt: number;
  message: string;
  phase: BootstrapPhase;
  progress: number | null;
  status: BootstrapStatus;
}

export type UpdateKind = "source" | "shell";
export type UpdateStatus = "idle" | "checking" | "unavailable" | "available" | "applying" | "complete" | "failed";
export type ActiveUpdateStatus = Extract<UpdateStatus, "checking" | "applying">;

export interface UpdateSnapshot {
  attempt: number;
  failure: string | null;
  heartbeatAt: number;
  kind: UpdateKind;
  message: string;
  progress: number | null;
  status: UpdateStatus;
  version: string | null;
}

export interface BackendState {
  port: number | null;
  status: "stopped" | "starting" | "ready" | "failed";
  url: string | null;
}

type Listener<T> = (snapshot: Readonly<T>) => void;

function createSnapshotStore<T extends object>(initial: T) {
  let snapshot: Readonly<T> = Object.freeze({ ...initial });
  const listeners = new Set<Listener<T>>();

  return {
    getSnapshot(): Readonly<T> {
      return snapshot;
    },
    publish(patch: Partial<T>): Readonly<T> {
      snapshot = Object.freeze({ ...snapshot, ...patch });
      for (const listener of listeners) {
        try {
          listener(snapshot);
        } catch {
          // State transitions are authoritative; a broken renderer subscriber must not roll them back.
        }
      }
      return snapshot;
    },
    subscribe(listener: Listener<T>): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function createBootstrapState(initial?: Partial<BootstrapSnapshot>) {
  const state = createSnapshotStore<BootstrapSnapshot>({
    attempt: 0,
    failure: null,
    heartbeatAt: Date.now(),
    message: "Waiting to start",
    phase: "idle",
    progress: null,
    status: "idle",
    ...initial,
  });

  const publishForAttempt = (
    attempt: number,
    patch: Partial<Omit<BootstrapSnapshot, "attempt">>,
  ): boolean => {
    const current = state.getSnapshot();
    if (attempt !== current.attempt || current.status !== "running") return false;
    state.publish({ ...patch, heartbeatAt: Date.now() });
    return true;
  };

  return {
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    begin(message: string, phase: BootstrapPhase = "preparing"): number {
      const attempt = state.getSnapshot().attempt + 1;
      state.publish({
        attempt,
        failure: null,
        heartbeatAt: Date.now(),
        message,
        phase,
        progress: 0,
        status: "running",
      });
      return attempt;
    },
    cancel(attempt: number): boolean {
      if (state.getSnapshot().status !== "running") return false;
      return publishForAttempt(attempt, {
        failure: "Bootstrap cancelled.",
        message: "Bootstrap cancelled",
        phase: "cancelled",
        status: "failed",
      });
    },
    complete(attempt: number, message = "Ready"): boolean {
      return publishForAttempt(attempt, {
        failure: null,
        message,
        phase: "complete",
        progress: 100,
        status: "ready",
      });
    },
    fail(attempt: number, failure: string): boolean {
      return publishForAttempt(attempt, {
        failure,
        message: failure,
        phase: "failed",
        status: "failed",
      });
    },
    failClosed(attempt: number, failure: string): boolean {
      const current = state.getSnapshot();
      if (
        current.attempt !== attempt ||
        (current.status !== "running" && !(current.status === "failed" && current.phase === "cancelled"))
      ) {
        return false;
      }
      state.publish({
        failure,
        heartbeatAt: Date.now(),
        message: failure,
        phase: "failed",
        status: "failed",
      });
      return true;
    },
    publishForAttempt,
    retry(): boolean {
      if (state.getSnapshot().status !== "failed") return false;
      const attempt = state.getSnapshot().attempt + 1;
      state.publish({
        attempt,
        failure: null,
        heartbeatAt: Date.now(),
        message: "Retrying bootstrap",
        phase: "preparing",
        progress: 0,
        status: "running",
      });
      return true;
    },
  };
}

export function createUpdateState(kind: UpdateKind) {
  const state = createSnapshotStore<UpdateSnapshot>({
    attempt: 0,
    failure: null,
    heartbeatAt: Date.now(),
    kind,
    message: "No update check has run",
    progress: null,
    status: "idle",
    version: null,
  });

  const publishForAttempt = (
    attempt: number,
    patch: Partial<Pick<UpdateSnapshot, "message" | "progress" | "version">>,
  ): boolean => {
    const current = state.getSnapshot();
    if (attempt !== current.attempt || (current.status !== "checking" && current.status !== "applying")) {
      return false;
    }
    state.publish({ ...patch, heartbeatAt: Date.now() });
    return true;
  };

  const finishAttempt = (
    attempt: number,
    patch: Partial<Omit<UpdateSnapshot, "attempt" | "heartbeatAt" | "kind">>,
  ): boolean => {
    const current = state.getSnapshot();
    if (attempt !== current.attempt || (current.status !== "checking" && current.status !== "applying")) {
      return false;
    }
    state.publish({ ...patch, heartbeatAt: Date.now() });
    return true;
  };

  return {
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    available(attempt: number, version: string, message = "Update available"): boolean {
      return finishAttempt(attempt, {
        failure: null,
        message,
        progress: null,
        status: "available",
        version,
      });
    },
    begin(status: ActiveUpdateStatus, message: string, version: string | null = null): number {
      const attempt = state.getSnapshot().attempt + 1;
      state.publish({
        attempt,
        failure: null,
        heartbeatAt: Date.now(),
        message,
        progress: status === "applying" ? 0 : null,
        status,
        version,
      });
      return attempt;
    },
    complete(attempt: number, message = "Update complete"): boolean {
      return finishAttempt(attempt, {
        failure: null,
        message,
        progress: 100,
        status: "complete",
      });
    },
    fail(attempt: number, failure: string): boolean {
      return finishAttempt(attempt, {
        failure,
        message: failure,
        status: "failed",
      });
    },
    publishForAttempt,
    unavailable(attempt: number, message: string): boolean {
      return finishAttempt(attempt, {
        failure: null,
        message,
        progress: null,
        status: "unavailable",
        version: null,
      });
    },
  };
}
