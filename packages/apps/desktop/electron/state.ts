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
  currentVersion: string | null;
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

/** Attempt-bound publication store for the authority-bearing loopback origin. */
export function createBackendState() {
  const state = createSnapshotStore<BackendState>({ port: null, status: "stopped", url: null });
  let attempt = 0;

  const activeAttempt = (candidate: number): boolean => candidate === attempt;
  const activeStatus = (): boolean => {
    const status = state.getSnapshot().status;
    return status === "starting" || status === "ready";
  };

  return {
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    begin(): number {
      attempt += 1;
      state.publish({ port: null, status: "starting", url: null });
      return attempt;
    },
    fail(candidate: number): boolean {
      if (!activeAttempt(candidate) || !activeStatus()) return false;
      state.publish({ port: null, status: "failed", url: null });
      return true;
    },
    ready(candidate: number, port: number): boolean {
      if (!activeAttempt(candidate) || state.getSnapshot().status !== "starting") return false;
      if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
        throw new RangeError("Backend state port must be an integer from 1 to 65535.");
      }
      state.publish({
        port,
        status: "ready",
        url: `http://127.0.0.1:${port}`,
      });
      return true;
    },
    stopped(candidate: number): boolean {
      if (!activeAttempt(candidate) || !activeStatus()) return false;
      state.publish({ port: null, status: "stopped", url: null });
      return true;
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
  const nextHeartbeatAt = (): number => Math.max(Date.now(), state.getSnapshot().heartbeatAt + 1);

  const publishForAttempt = (
    attempt: number,
    patch: Partial<Omit<BootstrapSnapshot, "attempt">>,
  ): boolean => {
    const current = state.getSnapshot();
    if (attempt !== current.attempt || current.status !== "running") return false;
    state.publish({ ...patch, heartbeatAt: nextHeartbeatAt() });
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
        heartbeatAt: nextHeartbeatAt(),
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
        heartbeatAt: nextHeartbeatAt(),
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
        heartbeatAt: nextHeartbeatAt(),
        message: "Retrying bootstrap",
        phase: "preparing",
        progress: 0,
        status: "running",
      });
      return true;
    },
  };
}

export function createUpdateState(kind: UpdateKind, currentVersion: string | null = null) {
  const state = createSnapshotStore<UpdateSnapshot>({
    attempt: 0,
    currentVersion,
    failure: null,
    heartbeatAt: Date.now(),
    kind,
    message: "No update check has run",
    progress: null,
    status: "idle",
    version: null,
  });
  const nextHeartbeatAt = (): number => Math.max(Date.now(), state.getSnapshot().heartbeatAt + 1);

  const publishForAttempt = (
    attempt: number,
    patch: Partial<Pick<UpdateSnapshot, "message" | "progress" | "version">>,
  ): boolean => {
    const current = state.getSnapshot();
    if (attempt !== current.attempt || (current.status !== "checking" && current.status !== "applying")) {
      return false;
    }
    state.publish({ ...patch, heartbeatAt: nextHeartbeatAt() });
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
    state.publish({ ...patch, heartbeatAt: nextHeartbeatAt() });
    return true;
  };

  return {
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    /**
     * Seed the known current version before any check has run, so the UI reports
     * the real installed revision instead of "Not reported" on first open. Only
     * applied while idle so it never overrides an in-flight or completed check.
     */
    noteCurrentVersion(currentVersion: string): boolean {
      const current = state.getSnapshot();
      if (current.status !== "idle" || current.currentVersion === currentVersion) return false;
      state.publish({ currentVersion, heartbeatAt: nextHeartbeatAt() });
      return true;
    },
    available(
      attempt: number,
      version: string,
      message = "Update available",
      currentVersion: string | null = state.getSnapshot().currentVersion,
    ): boolean {
      return finishAttempt(attempt, {
        currentVersion,
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
        heartbeatAt: nextHeartbeatAt(),
        message,
        progress: status === "applying" ? 0 : null,
        status,
        version,
      });
      return attempt;
    },
    complete(attempt: number, message = "Update complete"): boolean {
      const current = state.getSnapshot();
      return finishAttempt(attempt, {
        currentVersion: current.version,
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
    unavailable(
      attempt: number,
      message: string,
      currentVersion: string | null = state.getSnapshot().currentVersion,
    ): boolean {
      return finishAttempt(attempt, {
        currentVersion,
        failure: null,
        message,
        progress: null,
        status: "unavailable",
        version: null,
      });
    },
  };
}
