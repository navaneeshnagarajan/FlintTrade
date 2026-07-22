import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { createSourceOperationCoordinator, SourceOperationLeaseRetentionError } from "./source-operation";
import {
  createSourceUpdater,
  SOURCE_UPDATE_HEARTBEAT_INTERVAL_MS,
  type SourceUpdaterOptions,
  type SourceUpdaterCleanupBoundary,
} from "./source-updater";
import { createUpdateState } from "./state";

const currentRevision = "a".repeat(40);
const latestRevision = "b".repeat(40);
const operationId = "123e4567-e89b-42d3-a456-426614174000";
const isolationIdentity = { dev: 1, ino: 4 };

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function fixture(configuration: {
  activeRequiresRebuild?: boolean;
  heartbeatIntervalMs?: number;
  latestRevision?: string;
  lifecycleAvailable?: boolean;
  platform?: NodeJS.Platform;
  redactedPaths?: readonly string[];
} = {}) {
  const sourceRoot = path.join(path.sep, "managed", "source");
  const isolationRoot = path.join(path.sep, "managed", "temporary-health");
  const activeSource = path.join(sourceRoot, "FlintTrade");
  const lastKnownGood = path.join(sourceRoot, "FlintTrade.last-known-good");
  const candidate = path.join(sourceRoot, `FlintTrade.update-${operationId}`);
  const isolation = path.join(isolationRoot, `source-update-${operationId}`);
  const trace: string[] = [];
  const state = createUpdateState("source");
  const coordinator = createSourceOperationCoordinator();
  const resolvedRevision = configuration.latestRevision ?? latestRevision;
  const activeIdentity = {
    canonicalPath: activeSource,
    contentIdentity: "1".repeat(40),
    directoryIdentity: { dev: 1, ino: 1 },
    provenance: "git" as const,
    requiresRebuild: configuration.activeRequiresRebuild ?? false,
    revision: currentRevision,
  };
  const candidateIdentity = {
    canonicalPath: candidate,
    contentIdentity: "2".repeat(40),
    directoryIdentity: { dev: 1, ino: 3 },
    provenance: "git" as const,
    requiresRebuild: false,
    revision: resolvedRevision,
  };
  let cleanup!: SourceUpdaterCleanupBoundary;
  let inventoriedCandidate: Parameters<SourceUpdaterCleanupBoundary["removeOwnedCandidate"]>[0] | undefined;
  let inventoriedIsolation: Parameters<SourceUpdaterCleanupBoundary["removeIsolation"]>[0] | undefined;
  cleanup = {
    assertReady: vi.fn(() => undefined),
    inventoryOwnedPaths: vi.fn(async (owned) => {
      if (owned.candidate) inventoriedCandidate = owned.candidate;
      if (owned.isolation) inventoriedIsolation = owned.isolation;
    }),
    reserveOwnedPaths: vi.fn(async () => undefined),
    recover: vi.fn(async () => undefined),
    removeOwnedCandidate: vi.fn(async ({ candidatePath }) => {
      trace.push(`cleanup-candidate:${candidatePath}`);
    }),
    removeIsolation: vi.fn(async ({ isolationPath }) => {
      trace.push(`cleanup-isolation:${isolationPath}`);
    }),
    removeOwnedPaths: vi.fn(async ({ candidate: ownedCandidate, isolation: ownedIsolation }) => {
      if (ownedCandidate) await cleanup.removeOwnedCandidate(ownedCandidate);
      if (ownedIsolation) await cleanup.removeIsolation(ownedIsolation);
    }),
    removeReservedPaths: vi.fn(async ({ kinds }) => {
      if (kinds.includes("candidate") && inventoriedCandidate) {
        await cleanup.removeOwnedCandidate(inventoriedCandidate);
        inventoriedCandidate = undefined;
      }
      if (kinds.includes("isolation") && inventoriedIsolation) {
        await cleanup.removeIsolation(inventoriedIsolation);
        inventoriedIsolation = undefined;
      }
    }),
    validateRecovery: vi.fn(async () => undefined),
  };
  const options: SourceUpdaterOptions = {
    activeSource,
    candidateStager: {
      stage: vi.fn(async ({ destination, onOwnedPathPrepared, revision }) => {
        trace.push("stage");
        await onOwnedPathPrepared({
          identity: { dev: 1, ino: 3 },
          kind: "candidate",
          path: destination,
        });
        return { identity: { dev: 1, ino: 3 }, path: destination, provenance: "git" as const, revision };
      }),
    },
    cleanup,
    coordinator,
    events: {
      record: vi.fn(async () => undefined),
    },
    health: {
      prove: vi.fn(async ({ candidateRoot, onIsolationPrepared }) => {
        trace.push("health");
        await onIsolationPrepared(isolationIdentity);
        return { candidateRoot, isolationIdentity, port: 43123 };
      }),
    },
    ...(configuration.heartbeatIntervalMs === undefined
      ? {}
      : { heartbeatIntervalMs: configuration.heartbeatIntervalMs }),
    isolationRoot,
    lifecycle: {
      bootActive: vi.fn(async ({ activePath }) => {
        trace.push(`boot-active:${activePath}`);
        return true;
      }),
      drainCurrent: vi.fn(async ({ onBackendStopped }) => {
        trace.push("drain");
        onBackendStopped();
      }),
      isAvailable: vi.fn(() => configuration.lifecycleAvailable ?? true),
    },
    operationLease: {
      acquire: vi.fn(async ({ kind }) => {
        trace.push(`lease:${kind}`);
        return async () => {
          trace.push(`release:${kind}`);
        };
      }),
      assertHeld: vi.fn(async () => {
        trace.push("lease-proof");
      }),
      retainForContainment: vi.fn((_policy) => {
        trace.push("retain-containment");
        return true;
      }),
      target: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"),
    },
    promotion: {
      acknowledge: vi.fn(async () => undefined),
      assertReady: vi.fn(() => undefined),
      promote: vi.fn(async () => {
        trace.push("promote");
        return {
          active: { canonicalPath: activeSource, dev: 1, ino: 3 },
          lastKnownGood: { canonicalPath: lastKnownGood, dev: 1, ino: 1 },
          promotionId: operationId,
          status: "promoted" as const,
        };
      }),
      recover: vi.fn(async () => ({ status: "idle" as const })),
    },
    provenance: {
      validate: vi.fn(async ({ sourcePath }) => {
        trace.push(sourcePath === activeSource ? "validate-active" : "validate-candidate");
        return sourcePath === activeSource ? activeIdentity : candidateIdentity;
      }),
    },
    revisionResolver: {
      resolve: vi.fn(async () => {
        trace.push("latest");
        return { provenance: "git" as const, revision: resolvedRevision };
      }),
    },
    ...(configuration.redactedPaths ? { redactedPaths: configuration.redactedPaths } : {}),
    sourceRoot,
    state,
    ...(configuration.platform ? { platform: configuration.platform } : {}),
    uuid: vi.fn(() => operationId),
  };
  const updater = createSourceUpdater(options);
  const prepare = async () => {
    await updater.check();
    trace.length = 0;
  };
  return {
    activeSource,
    candidate,
    coordinator,
    currentRevision,
    isolation,
    isolationRoot,
    lastKnownGood,
    latestRevision: resolvedRevision,
    operationId,
    options,
    prepare,
    sourceRoot,
    state,
    trace,
    updater,
  };
}

describe("source update orchestration", () => {
  it("keeps the production update heartbeat within the four-second acceptance bound", () => {
    expect(SOURCE_UPDATE_HEARTBEAT_INTERVAL_MS).toBeLessThanOrEqual(4_000);
  });

  it("checks an exact remote revision against a validated active source", async () => {
    const test = fixture();

    await expect(test.updater.check()).resolves.toMatchObject({
      currentVersion: currentRevision,
      failure: null,
      status: "available",
      version: latestRevision,
    });
    expect(test.trace).toEqual([
      "lease:update-check",
      "lease-proof",
      "validate-active",
      "latest",
      "release:update-check",
    ]);

    test.options.revisionResolver.resolve = vi.fn(async () => ({
      provenance: "git" as const,
      revision: currentRevision,
    }));
    await expect(test.updater.check()).resolves.toMatchObject({
      currentVersion: currentRevision,
      status: "unavailable",
      version: null,
    });
  });

  it("offers and stages a current-toolchain rebuild when the revision is unchanged", async () => {
    const test = fixture({ activeRequiresRebuild: true, latestRevision: currentRevision });

    await expect(test.updater.check()).resolves.toMatchObject({
      currentVersion: currentRevision,
      status: "available",
      version: currentRevision,
    });
    await expect(test.updater.apply()).resolves.toMatchObject({
      currentVersion: currentRevision,
      status: "complete",
      version: currentRevision,
    });
    expect(test.options.candidateStager.stage).toHaveBeenCalledWith(
      expect.objectContaining({ revision: currentRevision }),
    );
    expect(test.trace).toContain("drain");
    expect(test.trace).toContain("promote");
  });

  it("fails before lease acquisition or staging when safe cleanup is unavailable", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    vi.mocked(test.options.operationLease.acquire).mockClear();
    test.options.cleanup.assertReady = vi.fn(() => {
      throw new Error("Source update apply is unavailable on Windows until native cleanup is installed.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/unavailable on Windows/i),
      status: "failed",
    });
    expect(test.options.operationLease.acquire).not.toHaveBeenCalled();
    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("rejects a non-exact revision returned by the latest resolver", async () => {
    const test = fixture();
    test.options.revisionResolver.resolve = vi.fn(async () => ({ provenance: "git", revision: "main" } as never));

    await expect(test.updater.check()).resolves.toMatchObject({ status: "failed" });
    expect(test.state.getSnapshot().failure).toMatch(/40-character|revision/i);
  });

  it("rejects a non-canonical uppercase operation UUID before reserving or staging paths", async () => {
    const test = fixture();
    await test.prepare();
    test.options.uuid = vi.fn(() => operationId.toUpperCase());

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/canonical lowercase UUID v4/i),
      status: "failed",
    });
    expect(test.options.cleanup.reserveOwnedPaths).not.toHaveBeenCalled();
    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("revalidates the active and exact candidate before health, drain, and promotion", async () => {
    const test = fixture();
    await test.prepare();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: null,
      status: "complete",
      version: latestRevision,
    });
    expect(test.trace).toEqual([
      "lease:update-apply",
      "lease-proof",
      "validate-active",
      "stage",
      "validate-candidate",
      "health",
      `cleanup-isolation:${test.isolation}`,
      "validate-candidate",
      "validate-active",
      "lease-proof",
      "drain",
      "validate-active",
      "validate-candidate",
      "lease-proof",
      "promote",
      `cleanup-candidate:${test.candidate}`,
      "release:update-apply",
    ]);
    expect(test.options.candidateStager.stage).toHaveBeenCalledWith({
      destination: test.candidate,
      onOwnedPathPrepared: expect.any(Function),
      revision: latestRevision,
      signal: expect.any(AbortSignal),
    });
    expect(test.options.cleanup.reserveOwnedPaths).toHaveBeenCalledWith({
      kinds: ["candidate", "isolation", "staging-candidate", "staging-unpack"],
      operationId,
    });
    expect(vi.mocked(test.options.cleanup.reserveOwnedPaths).mock.invocationCallOrder[0]!).toBeLessThan(
      vi.mocked(test.options.candidateStager.stage).mock.invocationCallOrder[0]!,
    );
    expect(test.options.operationLease.assertHeld).toHaveBeenCalledTimes(4);
    expect(test.options.provenance.validate).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({
        disallowedAliases: [test.activeSource, test.lastKnownGood],
        sourcePath: test.candidate,
      }),
    );
    expect(test.options.health.prove).toHaveBeenCalledWith({
      candidateRoot: test.candidate,
      isolation: {
        flinttradeHome: path.join(test.isolation, "flinttrade-home"),
        home: path.join(test.isolation, "home"),
        workspace: path.join(test.isolation, "workspace"),
      },
      onIsolationPrepared: expect.any(Function),
      signal: expect.any(AbortSignal),
    });
    const terminalEventCall = vi.mocked(test.options.events.record).mock.calls.findIndex(
      ([event]) => event.phase === "promoted" && event.promotionId === operationId,
    );
    expect(terminalEventCall).toBeGreaterThanOrEqual(0);
    expect(vi.mocked(test.options.events.record).mock.invocationCallOrder[terminalEventCall]!).toBeLessThan(
      vi.mocked(test.options.promotion.acknowledge).mock.invocationCallOrder[0]!,
    );
    expect(test.options.promotion.acknowledge).toHaveBeenCalledWith(
      expect.objectContaining({ promotionId: operationId, status: "promoted" }),
    );
  });

  it("keeps Windows staging and health proof ahead of backend drain and native promotion", async () => {
    const test = fixture({ platform: "win32" });
    await test.prepare();

    await expect(test.updater.apply()).resolves.toMatchObject({ failure: null, status: "complete" });
    const at = (event: string) => test.trace.indexOf(event);
    expect(at("stage")).toBeGreaterThanOrEqual(0);
    expect(at("stage")).toBeLessThan(at("health"));
    expect(at("health")).toBeLessThan(at("drain"));
    expect(at("drain")).toBeLessThan(at("promote"));
    expect(test.options.cleanup.inventoryOwnedPaths).toHaveBeenCalled();
    expect(test.options.operationLease.assertHeld).toHaveBeenCalledTimes(4);
  });

  it("retains a completed promotion journal when its terminal event cannot be made durable", async () => {
    const test = fixture();
    await test.prepare();
    vi.mocked(test.options.events.record).mockImplementation(async (event) => {
      if (event.phase === "promoted") throw new Error("durable terminal event append failed");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/promotion journal could not be acknowledged/i),
      status: "failed",
    });

    expect(test.options.promotion.promote).toHaveBeenCalledOnce();
    expect(test.options.promotion.acknowledge).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.trace).not.toContain("release:update-apply");
  });

  it("does not reopen settled cleanup after acknowledging a terminal promotion", async () => {
    const test = fixture();
    await test.prepare();
    const settle = test.options.cleanup.removeReservedPaths;
    let settlementCalls = 0;
    test.options.cleanup.removeReservedPaths = vi.fn(async (input) => {
      settlementCalls += 1;
      if (settlementCalls === 4) {
        throw new Error("redundant post-ack cleanup read failed");
      }
      await settle(input);
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: null,
      status: "complete",
      version: latestRevision,
    });
    expect(test.options.cleanup.removeReservedPaths).toHaveBeenCalledTimes(3);
    expect(test.options.promotion.acknowledge).toHaveBeenCalledOnce();
  });

  it("reconciles an older retained promotion before events, staging, health, or drain", async () => {
    const test = fixture();
    await test.prepare();
    const eventCount = vi.mocked(test.options.events.record).mock.calls.length;
    test.options.promotion.recover = vi.fn(async () => ({
      active: { canonicalPath: test.activeSource, dev: 7, ino: 8 },
      lastKnownGood: { canonicalPath: test.lastKnownGood, dev: 7, ino: 9 },
      promotionId: operationId,
      status: "promoted" as const,
    }));

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/prior source promotion.*fresh update check/i),
      status: "failed",
    });

    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(vi.mocked(test.options.cleanup.validateRecovery).mock.invocationCallOrder[0]!).toBeLessThan(
      vi.mocked(test.options.promotion.recover).mock.invocationCallOrder[0]!,
    );
    expect(vi.mocked(test.options.promotion.recover).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(test.options.events.record).mock.invocationCallOrder[eventCount]!,
    );
    const applyEvents = vi.mocked(test.options.events.record).mock.calls.slice(eventCount).map(([event]) => event);
    expect(applyEvents[0]).toMatchObject({
      phase: "promoted",
      promotionId: operationId,
      revision: null,
    });
    expect(test.options.promotion.acknowledge).toHaveBeenCalledWith(
      expect.objectContaining({ promotionId: operationId, status: "promoted" }),
    );
    expect(applyEvents).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ phase: "promoted", revision: latestRevision }),
      expect.objectContaining({ phase: "rolled-back", revision: latestRevision }),
    ]));
  });

  it("fails an unavailable backend lifecycle before recovery, staging, health, or drain", async () => {
    const test = fixture({ lifecycleAvailable: false });
    await test.prepare();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/backend guardian lifecycle/i),
      status: "failed",
    });

    expect(test.options.promotion.recover).not.toHaveBeenCalled();
    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("fails unsupported promotion durability before recovery, staging, health, or drain", async () => {
    const test = fixture();
    await test.prepare();
    test.options.promotion.assertReady = vi.fn(() => {
      throw new Error("Source promotion durability is unavailable on this platform.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/durability.*unavailable/i),
      status: "failed",
    });

    expect(test.options.promotion.recover).not.toHaveBeenCalled();
    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("shares coordinator exclusivity with bootstrap and acquires the filesystem lease only when active", async () => {
    const test = fixture();
    const blocker = deferred<void>();
    const bootstrap = test.coordinator.run("bootstrap", undefined, async () => blocker.promise);

    const checking = test.updater.check();
    await vi.waitFor(() => expect(test.coordinator.getSnapshot()).toMatchObject({ active: "bootstrap", queued: 1 }));
    expect(test.updater.cancel()).toBe(false);
    expect(test.options.operationLease.acquire).not.toHaveBeenCalled();
    expect(test.options.revisionResolver.resolve).not.toHaveBeenCalled();

    blocker.resolve();
    await bootstrap;
    await checking;
    expect(test.options.operationLease.acquire).toHaveBeenCalledOnce();
    expect(test.trace.at(-1)).toBe("release:update-check");
  });

  it("prevents a stale attempt from staging, draining, promoting, or publishing", async () => {
    const test = fixture();
    await test.prepare();
    vi.mocked(test.options.provenance.validate).mockImplementationOnce(async () => {
      test.state.begin("checking", "Newer check");
      return {
        canonicalPath: test.activeSource,
        contentIdentity: "1".repeat(40),
        directoryIdentity: { dev: 1, ino: 1 },
        provenance: "git",
        revision: currentRevision,
      };
    });
    const eventCount = vi.mocked(test.options.events.record).mock.calls.length;

    await test.updater.apply();

    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(vi.mocked(test.options.events.record).mock.calls).toHaveLength(eventCount + 1);
    expect(test.state.getSnapshot()).toMatchObject({ message: "Newer check", status: "checking" });
  });

  it("refreshes the public heartbeat while a long candidate build is still running", async () => {
    const test = fixture({ heartbeatIntervalMs: 5 });
    await test.prepare();
    const stageGate = deferred<void>();
    const originalStage = test.options.candidateStager.stage;
    test.options.candidateStager.stage = vi.fn(async (input) => {
      await stageGate.promise;
      return originalStage(input);
    });
    const stagingSnapshots: number[] = [];
    const unsubscribe = test.state.subscribe((snapshot) => {
      if (snapshot.message === "Staging and building the exact source revision") {
        stagingSnapshots.push(snapshot.heartbeatAt);
      }
    });

    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.options.candidateStager.stage).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(stagingSnapshots.length).toBeGreaterThanOrEqual(2));
    stageGate.resolve();
    await expect(applying).resolves.toMatchObject({ status: "complete" });
    unsubscribe();
    expect(new Set(stagingSnapshots).size).toBeGreaterThanOrEqual(2);
  });

  it("cancels during health without allowing drain and cleans only its owned pre-promotion paths", async () => {
    const test = fixture();
    await test.prepare();
    test.options.health.prove = vi.fn(
      async ({ onIsolationPrepared, signal }: Parameters<SourceUpdaterOptions["health"]["prove"]>[0]) => {
        await onIsolationPrepared(isolationIdentity);
        return new Promise<never>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")), { once: true });
        });
      },
    );

    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.options.health.prove).toHaveBeenCalledOnce());
    expect(test.updater.cancel("apply")).toBe(true);
    await expect(applying).resolves.toMatchObject({ status: "failed" });

    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0]).toMatchObject({
      message: "Source update was cancelled.",
      phase: "failed",
      revision: latestRevision,
    });
  });

  it("captures and cleans a valid staged candidate when cancellation wins at stage completion", async () => {
    const test = fixture();
    await test.prepare();
    const staged = deferred<{
      identity: { dev: number; ino: number };
      path: string;
      provenance: "git";
      revision: string;
    }>();
    let stageInput: Parameters<typeof test.options.candidateStager.stage>[0] | undefined;
    test.options.candidateStager.stage = vi.fn((input) => {
      stageInput = input;
      return staged.promise;
    });

    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.options.candidateStager.stage).toHaveBeenCalledOnce());
    expect(test.updater.cancel("apply")).toBe(true);
    await stageInput?.onOwnedPathPrepared({
      identity: { dev: 1, ino: 3 },
      kind: "candidate",
      path: test.candidate,
    });
    staged.resolve({
      identity: { dev: 1, ino: 3 },
      path: test.candidate,
      provenance: "git",
      revision: latestRevision,
    });

    await expect(applying).resolves.toMatchObject({ status: "failed" });
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("restarts the original backend when cancellation arrives after drain proved it stopped", async () => {
    const test = fixture();
    await test.prepare();
    test.options.lifecycle.drainCurrent = vi.fn(({ onBackendStopped, signal }) => {
      onBackendStopped();
      return new Promise<never>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    });

    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.options.lifecycle.drainCurrent).toHaveBeenCalledOnce());
    expect(test.updater.cancel("apply")).toBe(true);

    await expect(applying).resolves.toMatchObject({
      failure: "Source update was cancelled.",
      status: "failed",
    });
    expect(test.options.lifecycle.bootActive).toHaveBeenCalledOnce();
    expect(test.options.lifecycle.bootActive).toHaveBeenCalledWith({
      activePath: test.activeSource,
      onBackendStopped: expect.any(Function),
    });
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("fails closed on dirty or foreign active provenance before candidate acquisition", async () => {
    const test = fixture();
    await test.prepare();
    vi.mocked(test.options.provenance.validate).mockRejectedValueOnce(
      new Error("The active Git checkout has tracked, index or nonignored untracked changes."),
    );

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.candidateStager.stage).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("rejects candidate revision drift and cleans candidate and isolation before promotion", async () => {
    const test = fixture();
    await test.prepare();
    vi.mocked(test.options.provenance.validate)
      .mockResolvedValueOnce({
        canonicalPath: test.activeSource,
        contentIdentity: "1".repeat(40),
        directoryIdentity: { dev: 1, ino: 1 },
        provenance: "git",
        revision: currentRevision,
      })
      .mockResolvedValueOnce({
        canonicalPath: test.candidate,
        contentIdentity: "2".repeat(40),
        directoryIdentity: { dev: 1, ino: 3 },
        provenance: "git",
        revision: "c".repeat(40),
      });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
    expect(test.options.cleanup.removeIsolation).not.toHaveBeenCalled();
  });

  it("preserves an unowned candidate when staging rejects before returning an identity", async () => {
    const test = fixture();
    await test.prepare();
    test.options.candidateStager.stage = vi.fn(async () => {
      throw new Error("Candidate destination already exists; refusing to replace forensic evidence.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).not.toHaveBeenCalled();
    expect(test.options.cleanup.inventoryOwnedPaths).not.toHaveBeenCalled();
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("cleans exact bootstrap staging ownership after a contained build failure", async () => {
    const test = fixture();
    await test.prepare();
    test.options.candidateStager.stage = vi.fn(async (
      input: Parameters<typeof test.options.candidateStager.stage>[0],
    ) => {
      await input.onOwnedPathPrepared?.({
        identity: { dev: 1, ino: 30 },
        kind: "staging-candidate",
        path: `${test.candidate}.candidate-1`,
      });
      await input.onOwnedPathPrepared?.({
        identity: { dev: 1, ino: 31 },
        kind: "staging-unpack",
        path: `${test.candidate}.candidate-1.unpack`,
      });
      throw new Error("Candidate build failed.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.cleanup.inventoryOwnedPaths).toHaveBeenNthCalledWith(1, {
      staging: [{
        identity: { dev: 1, ino: 30 },
        kind: "staging-candidate",
        operationId,
        stagingPath: `${test.candidate}.candidate-1`,
      }],
    });
    expect(test.options.cleanup.inventoryOwnedPaths).toHaveBeenNthCalledWith(2, {
      staging: [{
        identity: { dev: 1, ino: 31 },
        kind: "staging-unpack",
        operationId,
        stagingPath: `${test.candidate}.candidate-1.unpack`,
      }],
    });
    expect(test.options.cleanup.removeReservedPaths).toHaveBeenCalledWith({
      kinds: ["candidate", "isolation", "staging-candidate", "staging-unpack"],
      operationId,
    });
    expect(test.options.cleanup.removeOwnedPaths).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("retains the outer filesystem lease when candidate command containment is unproved", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.candidateStager.stage = vi.fn(async (
      input: Parameters<typeof test.options.candidateStager.stage>[0],
    ) => {
      await input.onOwnedPathPrepared?.({
        identity: { dev: 1, ino: 30 },
        kind: "staging-candidate",
        path: `${test.candidate}.candidate-1`,
      });
      throw new SourceOperationLeaseRetentionError("Candidate command containment is unresolved.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.trace).toContain("lease:update-apply");
    expect(test.trace).toContain("retain-containment");
    expect(test.trace).not.toContain("release:update-apply");
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).not.toHaveBeenCalled();
    expect(test.options.cleanup.inventoryOwnedPaths).toHaveBeenCalledWith({
      staging: [{
        identity: { dev: 1, ino: 30 },
        kind: "staging-candidate",
        operationId,
        stagingPath: `${test.candidate}.candidate-1`,
      }],
    });
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("preserves a candidate when the staged result fails validation before ownership is accepted", async () => {
    const test = fixture();
    await test.prepare();
    test.options.candidateStager.stage = vi.fn(async () => ({
      identity: { dev: 1, ino: 3 },
      path: test.candidate,
      provenance: "git" as const,
      revision: "c".repeat(40),
    }));

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.provenance.validate).toHaveBeenCalledTimes(2);
    expect(test.options.health.prove).not.toHaveBeenCalled();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
  });

  it("fails a rejected health proof before drain and performs bounded pre-promotion cleanup", async () => {
    const test = fixture();
    await test.prepare();
    test.options.health.prove = vi.fn(async ({ onIsolationPrepared }) => {
      await onIsolationPrepared(isolationIdentity);
      throw new Error("candidate ping failed");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("retains the lease immediately when candidate cleanup containment is unresolved", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.health.prove = vi.fn(async ({ onIsolationPrepared }) => {
      await onIsolationPrepared(isolationIdentity);
      throw new Error("candidate ping failed");
    });
    test.options.cleanup.removeOwnedCandidate = vi.fn(async () => {
      throw new SourceOperationLeaseRetentionError("safe remover containment is unresolved");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.trace).toContain("retain-containment");
    expect(test.trace).not.toContain("release:update-apply");
    expect(test.options.cleanup.removeIsolation).not.toHaveBeenCalled();
  });

  it("retains the lease when pre-promotion isolation cleanup containment is unresolved", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.cleanup.removeIsolation = vi.fn(async () => {
      throw new SourceOperationLeaseRetentionError("isolation remover containment is unresolved");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(test.options.promotion.acknowledge).not.toHaveBeenCalled();
    expect(test.trace).toContain("retain-containment");
    expect(test.trace).not.toContain("release:update-apply");
  });

  it("preserves the captured isolation and outer lease when health containment is unresolved", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.health.prove = vi.fn(async ({ onIsolationPrepared }) => {
      await onIsolationPrepared(isolationIdentity);
      throw new SourceOperationLeaseRetentionError("Candidate health containment is unresolved.");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.trace).toContain("lease:update-apply");
    expect(test.trace).toContain("retain-containment");
    expect(test.trace).not.toContain("release:update-apply");
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).not.toHaveBeenCalled();
    expect(test.options.cleanup.inventoryOwnedPaths).toHaveBeenCalledWith({
      candidate: {
        candidatePath: test.candidate,
        identity: { dev: 1, ino: 3 },
        operationId,
      },
      isolation: {
        identity: isolationIdentity,
        isolationPath: test.isolation,
      },
    });
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("rejects a health proof whose returned isolation identity does not match creation", async () => {
    const test = fixture();
    await test.prepare();
    test.options.health.prove = vi.fn(async ({ candidateRoot, onIsolationPrepared }) => {
      await onIsolationPrepared(isolationIdentity);
      return { candidateRoot, isolationIdentity: { dev: 1, ino: 999 }, port: 43123 };
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("refuses drain when candidate A is replaced by candidate B after health", async () => {
    const test = fixture();
    await test.prepare();
    let candidateValidationCount = 0;
    test.options.provenance.validate = vi.fn(async ({ sourcePath }) => {
      if (sourcePath === test.activeSource) {
        return {
          canonicalPath: test.activeSource,
          contentIdentity: "1".repeat(40),
          directoryIdentity: { dev: 1, ino: 1 },
          provenance: "git" as const,
          revision: currentRevision,
        };
      }

      candidateValidationCount += 1;
      const replacement = candidateValidationCount > 1;
      return {
        canonicalPath: test.candidate,
        contentIdentity: (replacement ? "3" : "2").repeat(40),
        directoryIdentity: { dev: 1, ino: replacement ? 30 : 3 },
        provenance: "git" as const,
        revision: latestRevision,
      };
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/candidate source changed during its health proof/i),
      status: "failed",
    });

    expect(candidateValidationCount).toBe(2);
    expect(test.options.health.prove).toHaveBeenCalledOnce();
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
  });

  it("refuses drain when the bound terminal output changes during candidate health", async () => {
    const test = fixture();
    await test.prepare();
    let candidateValidationCount = 0;
    test.options.provenance.validate = vi.fn(async ({ sourcePath }) => {
      if (sourcePath === test.activeSource) {
        return {
          canonicalPath: test.activeSource,
          contentIdentity: "1".repeat(40),
          directoryIdentity: { dev: 1, ino: 1 },
          provenance: "git" as const,
          revision: currentRevision,
        };
      }
      candidateValidationCount += 1;
      return {
        buildIdentity: {
          frontendOutputDigest: (candidateValidationCount > 1 ? "4" : "3").repeat(64),
          markerSchemaVersion: 3 as const,
          packageManager: "pnpm@9.15.0+sha512.fixture",
          toolchain: { node: "22.23.1", pnpm: "9.15.0", uv: "0.11.16" },
        },
        canonicalPath: test.candidate,
        contentIdentity: "2".repeat(40),
        directoryIdentity: { dev: 1, ino: 3 },
        provenance: "git" as const,
        requiresRebuild: false,
        revision: latestRevision,
      };
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/candidate source changed during its health proof/i),
      status: "failed",
    });
    expect(candidateValidationCount).toBe(2);
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("reports rollback as a stable failure and preserves evidence after promotion begins", async () => {
    const test = fixture();
    await test.prepare();
    test.options.promotion.promote = vi.fn(async () => ({
      active: { canonicalPath: test.activeSource, dev: 1, ino: 1 },
      failed: { canonicalPath: path.join(test.sourceRoot, `FlintTrade.failed-${operationId}`), dev: 1, ino: 2 },
      promotionId: operationId,
      status: "rolled-back" as const,
    }));

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/last-known-good.*restored/i),
      status: "failed",
    });
    expect(test.options.cleanup.removeReservedPaths).toHaveBeenCalledWith({
      kinds: ["candidate"],
      operationId,
    });
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("restarts the unchanged active backend after a post-drain promotion preflight failure", async () => {
    const test = fixture();
    await test.prepare();
    test.options.promotion.promote = vi.fn(async () => {
      throw new Error("rollback failed https://user:secret@example.invalid/private");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.not.stringContaining("secret"),
      status: "failed",
    });
    expect(test.state.getSnapshot().failure).toContain("<redacted-credentials>");
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0].message).not.toContain("secret");
    expect(test.options.promotion.recover).toHaveBeenCalledTimes(2);
    expect(test.options.lifecycle.bootActive).toHaveBeenCalledWith({
      activePath: test.activeSource,
      onBackendStopped: expect.any(Function),
    });
    expect(test.options.cleanup.removeOwnedCandidate).toHaveBeenCalledWith({
      candidatePath: test.candidate,
      identity: { dev: 1, ino: 3 },
      operationId,
    });
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("retains process-exit authority when the drained original restart lacks stopped proof", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.promotion.promote = vi.fn(async () => {
      throw new Error("promotion preflight failed");
    });
    test.options.lifecycle.bootActive = vi.fn(async () => false);

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });

    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.trace).not.toContain("release:update-apply");
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
  });

  it("upgrades weak restart containment when no stopped proof was published", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.promotion.promote = vi.fn(async () => {
      throw new Error("promotion preflight failed");
    });
    test.options.lifecycle.bootActive = vi.fn(async () => {
      throw new SourceOperationLeaseRetentionError("restart command containment remains unresolved");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });

    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.trace).not.toContain("release:update-apply");
  });

  it("upgrades weak lease reproof after a successful original restart", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.promotion.promote = vi.fn(async () => {
      throw new Error("promotion preflight failed");
    });
    const commandContainment = new SourceOperationLeaseRetentionError(
      "restart finalisation command containment remains unresolved",
    );
    let restartLive = false;
    test.options.lifecycle.bootActive = vi.fn(async () => {
      restartLive = true;
      return true;
    });
    test.options.operationLease.assertHeld = vi.fn(async () => {
      if (restartLive) throw commandContainment;
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });

    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.trace).not.toContain("release:update-apply");
  });

  it("retains process-exit authority until a live promotion journal is acknowledged", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    const commandContainment = new SourceOperationLeaseRetentionError(
      "promoted event command containment remains unresolved",
    );
    test.options.events.record = vi.fn(async (event) => {
      if (event.phase === "promoted") throw commandContainment;
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });

    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.options.promotion.acknowledge).not.toHaveBeenCalled();
    expect(test.trace).not.toContain("release:update-apply");
  });

  it("retains evidence and does not execute a tree when post-drain promotion recovery is ambiguous", async () => {
    const test = fixture();
    await test.prepare();
    test.options.promotion.promote = vi.fn(async () => {
      throw new Error("promotion mutation failed");
    });
    test.options.promotion.recover = vi.fn()
      .mockResolvedValueOnce({ status: "idle" })
      .mockRejectedValueOnce(new Error("journal evidence is ambiguous"));

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringMatching(/could not be reconciled safely/i),
      status: "failed",
    });
    expect(test.options.lifecycle.bootActive).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("retains the lease and skips recovery when the promoted backend stop is unproved", async () => {
    const test = fixture();
    await test.prepare();
    test.trace.length = 0;
    test.options.promotion.promote = vi.fn(async () => {
      throw new SourceOperationLeaseRetentionError("promoted backend containment remains unresolved");
    });

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });

    expect(test.options.promotion.recover).toHaveBeenCalledOnce();
    expect(test.trace).toContain("retain-containment");
    expect(test.trace).not.toContain("release:update-apply");
    expect(test.options.cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(test.options.cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: isolationIdentity,
      isolationPath: test.isolation,
    });
  });

  it("keeps a completed promotion authoritative when cancellation arrives during the irreversible step", async () => {
    const test = fixture();
    await test.prepare();
    const promoted = deferred<Awaited<ReturnType<SourceUpdaterOptions["promotion"]["promote"]>>>();
    test.options.promotion.promote = vi.fn(() => promoted.promise);
    const controller = new AbortController();

    const applying = test.updater.apply(controller.signal);
    await vi.waitFor(() => expect(test.options.promotion.promote).toHaveBeenCalledOnce());
    controller.abort();
    promoted.resolve({
      active: { canonicalPath: test.activeSource, dev: 1, ino: 3 },
      lastKnownGood: { canonicalPath: test.lastKnownGood, dev: 1, ino: 1 },
      promotionId: operationId,
      status: "promoted",
    });

    await expect(applying).resolves.toMatchObject({ failure: null, status: "complete", version: latestRevision });
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0]).toMatchObject({
      phase: "promoted",
      revision: latestRevision,
    });
    expect(test.options.lifecycle.bootActive).not.toHaveBeenCalled();
  });

  it("redacts mixed-separator and extended private roots case-insensitively on Windows", async () => {
    const privateWorkspace = path.join(path.sep, "Users", "Person", "Private Workspace");
    const test = fixture({ platform: "win32", redactedPaths: [privateWorkspace] });
    await test.prepare();
    test.options.promotion.promote = vi.fn(async () => {
      const extendedWindowsSpelling = `\\\\?\\${privateWorkspace.replaceAll("/", "\\").toUpperCase()}`;
      throw new Error(`append failed below ${extendedWindowsSpelling}`);
    });

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: expect.stringContaining("<private-path>"),
      status: "failed",
    });
    expect(test.state.getSnapshot().failure?.toLowerCase()).not.toContain("person");
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0].message.toLowerCase()).not.toContain("person");
  });

  it("revalidates active immediately before drain and refuses drain if it changed or became stale", async () => {
    const test = fixture();
    await test.prepare();
    vi.mocked(test.options.provenance.validate).mockImplementationOnce(async ({ sourcePath }) => ({
      canonicalPath: sourcePath,
      contentIdentity: "1".repeat(40),
      directoryIdentity: { dev: 1, ino: sourcePath === test.activeSource ? 1 : 3 },
      provenance: "git",
      revision: currentRevision,
    })).mockImplementationOnce(async ({ sourcePath }) => ({
      canonicalPath: sourcePath,
      contentIdentity: "2".repeat(40),
      directoryIdentity: { dev: 1, ino: sourcePath === test.activeSource ? 1 : 3 },
      provenance: "git",
      revision: currentRevision,
    }));

    await expect(test.updater.apply()).resolves.toMatchObject({ status: "failed" });
    expect(test.options.lifecycle.drainCurrent).not.toHaveBeenCalled();
    expect(test.options.promotion.promote).not.toHaveBeenCalled();
  });

  it("delegates recovery under startup-recovery coordination and the same filesystem lease", async () => {
    const test = fixture();
    vi.mocked(test.options.promotion.recover).mockImplementationOnce(async () => {
      expect(test.coordinator.getSnapshot().active).toBe("startup-recovery");
      test.trace.push("recover");
      return { status: "idle" };
    });

    await expect(test.updater.recover()).resolves.toEqual({ status: "idle" });
    expect(test.trace).toEqual([
      "lease:startup-recovery",
      "lease-proof",
      "lease-proof",
      "lease-proof",
      "recover",
      "lease-proof",
      "release:startup-recovery",
    ]);
  });

  it("keeps a completed startup recovery authoritative when cancellation arrives during reconciliation", async () => {
    const test = fixture();
    const recovered = deferred<Awaited<ReturnType<SourceUpdaterOptions["promotion"]["recover"]>>>();
    test.options.promotion.recover = vi.fn(() => recovered.promise);
    const controller = new AbortController();

    const recovery = test.updater.recover(controller.signal);
    await vi.waitFor(() => expect(test.options.promotion.recover).toHaveBeenCalledOnce());
    controller.abort();
    recovered.resolve({
      active: { canonicalPath: test.activeSource, dev: 1, ino: 3 },
      lastKnownGood: { canonicalPath: test.lastKnownGood, dev: 1, ino: 1 },
      promotionId: operationId,
      status: "promoted",
    });

    await expect(recovery).resolves.toMatchObject({ status: "promoted" });
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0]).toMatchObject({
      operation: "startup-recovery",
      phase: "promoted",
      promotionId: operationId,
    });
    expect(test.options.promotion.acknowledge).toHaveBeenCalledWith(
      expect.objectContaining({ promotionId: operationId, status: "promoted" }),
    );
  });

  it("retains process-exit authority until a recovered live journal is acknowledged", async () => {
    const test = fixture();
    test.options.promotion.recover = vi.fn(async () => ({
      active: { canonicalPath: test.activeSource, dev: 1, ino: 3 },
      lastKnownGood: { canonicalPath: test.lastKnownGood, dev: 1, ino: 1 },
      promotionId: operationId,
      status: "promoted" as const,
    }));
    const commandContainment = new SourceOperationLeaseRetentionError(
      "recovery event command containment remains unresolved",
    );
    test.options.events.record = vi.fn(async (event) => {
      if (event.phase === "promoted") throw commandContainment;
    });

    await expect(test.updater.recover()).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);

    expect(test.options.operationLease.retainForContainment).toHaveBeenCalledWith("process-exit-required");
    expect(test.options.promotion.acknowledge).not.toHaveBeenCalled();
    expect(test.trace).not.toContain("release:startup-recovery");
  });

  it("durably records cancellation when journal-less startup recovery is still reversible", async () => {
    const test = fixture();
    const recovered = deferred<{ status: "idle" }>();
    test.options.promotion.recover = vi.fn(() => recovered.promise);
    const controller = new AbortController();

    const recovery = test.updater.recover(controller.signal);
    await vi.waitFor(() => expect(test.options.promotion.recover).toHaveBeenCalledOnce());
    controller.abort();
    recovered.resolve({ status: "idle" });

    await expect(recovery).rejects.toMatchObject({ name: "AbortError" });
    expect(vi.mocked(test.options.events.record).mock.calls.at(-1)?.[0]).toMatchObject({
      operation: "startup-recovery",
      phase: "failed",
    });
  });

  it("never passes the live workspace to source mutation boundaries", async () => {
    const test = fixture();
    const liveWorkspace = path.join(path.sep, "Users", "person", ".flinttrade", "workspace");
    await test.prepare();

    await test.updater.apply();

    const mutations = [
      ...vi.mocked(test.options.candidateStager.stage).mock.calls,
      ...vi.mocked(test.options.cleanup.removeOwnedCandidate).mock.calls,
      ...vi.mocked(test.options.cleanup.removeIsolation).mock.calls,
      ...vi.mocked(test.options.promotion.promote).mock.calls,
    ];
    expect(JSON.stringify(mutations)).not.toContain(liveWorkspace);
    expect(vi.mocked(test.options.promotion.promote).mock.invocationCallOrder[0]).toBeGreaterThan(
      vi.mocked(test.options.lifecycle.drainCurrent).mock.invocationCallOrder[0]!,
    );
  });
});
