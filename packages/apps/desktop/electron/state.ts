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

export interface UpdateSnapshot {
  failure: string | null;
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
      for (const listener of listeners) listener(snapshot);
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
    if (attempt !== state.getSnapshot().attempt) return false;
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
    failure: null,
    kind,
    message: "No update check has run",
    progress: null,
    status: "idle",
    version: null,
  });
  return {
    getSnapshot: state.getSnapshot,
    subscribe: state.subscribe,
    publish(patch: Partial<Omit<UpdateSnapshot, "kind">>): Readonly<UpdateSnapshot> {
      return state.publish(patch);
    },
  };
}
