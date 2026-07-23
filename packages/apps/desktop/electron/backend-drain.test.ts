import { describe, expect, it, vi } from "vitest";

import {
  BackendDrain,
  DEFAULT_BACKEND_DRAIN_TIMING,
  FORCE_EXIT_COMMAND,
  SHUTDOWN_COMMAND,
  type BackendDrainEvidence,
  type BackendDrainEvidenceBoundary,
} from "./backend-drain";

const TOKEN = "a".repeat(64);
const OTHER_TOKEN = "b".repeat(64);
const FAST_TIMING = { containmentMs: 5, forceMs: 5, gracefulMs: 5 } as const;

interface Waiter {
  afterRevision: number;
  reject(error: unknown): void;
  resolve(): void;
  signal: AbortSignal;
}

class EvidenceFixture implements BackendDrainEvidenceBoundary {
  private state: BackendDrainEvidence = {
    childExited: false,
    cleanupTokens: [],
    containmentExited: false,
    pendingExitAcks: [],
    revision: 0,
  };
  private readonly waiters: Waiter[] = [];

  snapshot(): BackendDrainEvidence {
    return this.state;
  }

  waitForChange(afterRevision: number, signal: AbortSignal): Promise<void> {
    if (this.state.revision !== afterRevision) return Promise.resolve();
    if (signal.aborted) return Promise.reject(signal.reason);
    return new Promise<void>((resolve, reject) => {
      const waiter = { afterRevision, reject, resolve, signal };
      this.waiters.push(waiter);
      signal.addEventListener("abort", () => {
        this.remove(waiter);
        reject(signal.reason);
      }, { once: true });
    });
  }

  publish(update: Partial<Omit<BackendDrainEvidence, "revision">>): void {
    this.state = { ...this.state, ...update, revision: this.state.revision + 1 };
    for (const waiter of [...this.waiters]) {
      if (waiter.afterRevision !== this.state.revision) {
        this.remove(waiter);
        waiter.resolve();
      }
    }
  }

  private remove(waiter: Waiter): void {
    const index = this.waiters.indexOf(waiter);
    if (index >= 0) this.waiters.splice(index, 1);
  }
}

function createDrain(input: {
  applicationPid?: number | null;
  evidence?: EvidenceFixture;
  forceContainment?: () => Promise<void>;
  timing?: { containmentMs: number; forceMs: number; gracefulMs: number };
} = {}) {
  const evidence = input.evidence ?? new EvidenceFixture();
  const writes: string[] = [];
  const forceContainment = vi.fn(input.forceContainment ?? (async () => undefined));
  const drain = new BackendDrain({
    applicationPid: input.applicationPid === undefined ? 4321 : input.applicationPid,
    evidence,
    forceContainment,
    launchToken: TOKEN,
    async writeStdin(command) {
      writes.push(command);
    },
  }, input.timing ?? FAST_TIMING);
  return { drain, evidence, forceContainment, writes };
}

describe("backend drain", () => {
  it("uses the parity deadline budget", () => {
    expect(DEFAULT_BACKEND_DRAIN_TIMING).toEqual({
      containmentMs: 1_000,
      forceMs: 7_000,
      gracefulMs: 302_000,
    });
    expect(Object.values(DEFAULT_BACKEND_DRAIN_TIMING).reduce((sum, value) => sum + value, 0)).toBe(310_000);
  });

  it("returns one idempotent promise and completes on exact cleanup plus child-exit proof", async () => {
    const { drain, evidence, writes, forceContainment } = createDrain();
    const first = drain.drain();
    const second = drain.drain();

    expect(second).toBe(first);
    expect(writes).toEqual([SHUTDOWN_COMMAND]);
    evidence.publish({ cleanupTokens: [TOKEN] });
    await Promise.resolve();
    evidence.publish({ childExited: true });

    await expect(first).resolves.toMatchObject({
      childExited: true,
      outcome: "clean",
      phase: "graceful",
      proof: "cleanup-complete",
      recordRemovalSafe: true,
    });
    expect(writes).toEqual([SHUTDOWN_COMMAND]);
    expect(forceContainment).not.toHaveBeenCalled();
  });

  it("accepts exact pending-exit ACK plus child exit only before application PID confirmation", async () => {
    const { drain, evidence } = createDrain({ applicationPid: null });
    const result = drain.drain();
    evidence.publish({
      childExited: true,
      pendingExitAcks: [{ reason: "promotion-failed", token: TOKEN }],
    });

    await expect(result).resolves.toMatchObject({
      outcome: "clean",
      proof: "pending-exit-ack",
      recordRemovalSafe: true,
    });
  });

  it("ignores wrong tokens and a pending ACK for a confirmed application", async () => {
    const evidence = new EvidenceFixture();
    const { drain, writes, forceContainment } = createDrain({
      evidence,
      forceContainment: async () => {
        evidence.publish({ childExited: true, containmentExited: true });
      },
    });
    evidence.publish({
      cleanupTokens: [OTHER_TOKEN],
      pendingExitAcks: [{ reason: "force-exit", token: TOKEN }],
    });

    await expect(drain.drain()).resolves.toMatchObject({
      childExited: true,
      containmentExited: true,
      outcome: "contained",
      proof: null,
      recordRemovalSafe: false,
    });
    expect(writes).toEqual([SHUTDOWN_COMMAND, FORCE_EXIT_COMMAND]);
    expect(forceContainment).toHaveBeenCalledTimes(1);
  });

  it("escalates graceful to force and then allows only a bounded containment opportunity", async () => {
    const evidence = new EvidenceFixture();
    const { drain, writes, forceContainment } = createDrain({ evidence });
    let settled = false;
    const result = drain.drain().finally(() => {
      settled = true;
    });
    let microtaskRan = false;
    queueMicrotask(() => {
      microtaskRan = true;
    });

    await Promise.resolve();
    expect(microtaskRan).toBe(true);
    expect(settled).toBe(false);
    await expect(result).resolves.toMatchObject({
      outcome: "unresolved",
      phase: "containment",
      recordRemovalSafe: false,
    });
    expect(writes).toEqual([SHUTDOWN_COMMAND, FORCE_EXIT_COMMAND]);
    expect(forceContainment).toHaveBeenCalledTimes(1);
  });

  it("skips a long phase when its stdin write fails and still requests containment", async () => {
    const evidence = new EvidenceFixture();
    const writes: string[] = [];
    const forceContainment = vi.fn(async () => {
      evidence.publish({ childExited: true, containmentExited: true });
    });
    const drain = new BackendDrain({
      applicationPid: 4321,
      evidence,
      forceContainment,
      launchToken: TOKEN,
      async writeStdin(command) {
        writes.push(command);
        throw new Error("pipe closed");
      },
    }, { containmentMs: 20, forceMs: 20, gracefulMs: 20_000 });

    await expect(drain.drain()).resolves.toMatchObject({ outcome: "contained", recordRemovalSafe: false });
    expect(writes).toEqual([SHUTDOWN_COMMAND, FORCE_EXIT_COMMAND]);
    expect(forceContainment).toHaveBeenCalledTimes(1);
  });

  it("bounds hung stdin writes and a hung containment request", async () => {
    const evidence = new EvidenceFixture();
    const writes: string[] = [];
    const forceContainment = vi.fn(() => new Promise<void>(() => undefined));
    const drain = new BackendDrain({
      applicationPid: 4321,
      evidence,
      forceContainment,
      launchToken: TOKEN,
      writeStdin(command) {
        writes.push(command);
        return new Promise<void>(() => undefined);
      },
    }, FAST_TIMING);

    await expect(drain.drain()).resolves.toMatchObject({
      outcome: "unresolved",
      phase: "containment",
      recordRemovalSafe: false,
    });
    expect(writes).toEqual([SHUTDOWN_COMMAND, FORCE_EXIT_COMMAND]);
    expect(forceContainment).toHaveBeenCalledTimes(1);
  });
});
