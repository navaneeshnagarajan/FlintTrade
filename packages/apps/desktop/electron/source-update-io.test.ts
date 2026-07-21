import { lstat, mkdtemp, mkdir, readFile, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { createNodeBootstrapDependencies } from "./bootstrap-io";
import type { BootstrapDependencies } from "./bootstrap";
import { SourceOperationLeaseRetentionError, isSourceOperationLeaseRetentionError } from "./source-operation";
import {
  CLEANUP_QUARANTINE_PREFIX,
  STALE_SOURCE_QUARANTINE_PREFIX,
  createNodeSourcePromotionFileSystem,
  type NodeSourcePromotionFileSystemOptions,
} from "./source-promotion";
import {
  FLINTTRADE_SOURCE_REPOSITORY,
  SOURCE_CLEANUP_INVENTORY_NAME,
  createDurableSourceUpdaterEventRecorder,
  createNodeSourceUpdaterCleanup,
  createNodeSourceUpdaterHealth,
  createNodeSourcePromotionHealthLifecycle,
  createRuntimeSourceUpdaterOperationLease,
  createSourceUpdaterProvenance,
  createSourceUpdaterRevisionResolver,
} from "./source-update-io";
import type { ActiveSourceIdentity, ExactSourceRevision } from "./source-provenance";
import type { SourceUpdateEvent } from "./source-updater";

const operationId = "12345678-1234-4123-8123-123456789abc";
const nestedOperationId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const revision = "a".repeat(40);

const testOnlySafeRemove: NonNullable<NodeSourcePromotionFileSystemOptions["safeRemove"]> = async ({
  expected,
  quarantine,
  target,
}) => {
  const optionalIdentity = async (entry: string) => {
    try {
      const metadata = await lstat(entry);
      return metadata.isDirectory() ? { dev: metadata.dev, ino: metadata.ino } : null;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  };
  const [atTarget, atQuarantine] = await Promise.all([
    optionalIdentity(target),
    optionalIdentity(quarantine),
  ]);
  if ((atTarget === null) === (atQuarantine === null)) throw new Error("ambiguous test removal evidence");
  const selected = atTarget ?? atQuarantine!;
  if (selected.dev !== expected.dev || selected.ino !== expected.ino) {
    throw new Error("test removal identity mismatch");
  }
  if (atTarget) await rename(target, quarantine);
  await rm(quarantine, { recursive: true });
};

function cleanupFileSystem() {
  return createNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove });
}

function leaseFileSystem(acquireOperationLock: BootstrapDependencies["fileSystem"]["acquireOperationLock"]) {
  return {
    acquireOperationLock,
    directoryIdentity: vi.fn(async () => ({ dev: 1, ino: 2 })),
    readTextNoFollow: vi.fn(async () => `${JSON.stringify({
      bootIdentity: "darwin:boot-1",
      operationId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      ownerPid: 4321,
    })}\n`),
  } as unknown as BootstrapDependencies["fileSystem"];
}

describe("source update production I/O", () => {
  const temporaryRoots: string[] = [];

  afterEach(async () => {
    await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
  });

  async function temporaryLayout() {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-update-io-"));
    temporaryRoots.push(root);
    const sourceRoot = path.join(root, "source");
    const isolationRoot = path.join(root, "isolation");
    const workspace = path.join(root, "workspace");
    const logs = path.join(workspace, "logs");
    await Promise.all([sourceRoot, isolationRoot, workspace].map((target) => mkdir(target, { recursive: true })));
    return { isolationRoot, logs, root, sourceRoot, workspace };
  }

  it("binds the runtime lease to singleton, boot, PID and the exact shared target", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const releaseUnderlying = vi.fn(async () => undefined);
    const acquireOperationLock = vi.fn(async () => releaseUnderlying);
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem: leaseFileSystem(acquireOperationLock),
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });

    await expect(lease.assertHeld()).rejects.toThrow(/not held/i);
    const release = await lease.acquire({ kind: "update-check", signal: new AbortController().signal });
    expect(acquireOperationLock).toHaveBeenCalledWith({
      bootIdentity: "darwin:boot-1",
      ownerPid: 4321,
      singletonAuthorised: true,
      target,
    });
    await expect(lease.assertHeld()).resolves.toBeUndefined();
    expect(lease.getSnapshot()).toEqual({ kind: "update-check", state: "held" });
    await release();
    await release();
    expect(releaseUnderlying).toHaveBeenCalledOnce();
    await expect(lease.assertHeld()).rejects.toThrow(/not held/i);
  });

  it("keeps an unreleased capability held, fails closed on release failure, and supports a retry", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const releaseUnderlying = vi.fn()
      .mockRejectedValueOnce(new Error("parent fsync failed"))
      .mockResolvedValueOnce(undefined);
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem: leaseFileSystem(vi.fn(async () => releaseUnderlying)),
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });

    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "held" });
    await expect(lease.acquire({ kind: "update-check", signal: new AbortController().signal })).rejects.toThrow(/already/i);
    await expect(release()).rejects.toThrow("parent fsync failed");
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "release-failed" });
    await expect(lease.assertHeld()).rejects.toThrow(/cannot prove/i);
    await expect(release()).resolves.toBeUndefined();
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("re-proves retained command containment before releasing the same runtime lease", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const events: string[] = [];
    const releaseUnderlying = vi.fn(async () => {
      events.push("release");
    });
    const reconcileOperationContainment = vi.fn()
      .mockImplementationOnce(async () => {
        events.push("reproof-failed");
        throw new Error("recorded child remains alive");
      })
      .mockImplementationOnce(async () => {
        events.push("reproof-succeeded");
      });
    const dependencies = {
      command: { operationLeaseTarget: target, reconcileOperationContainment },
      fileSystem: leaseFileSystem(vi.fn(async () => releaseUnderlying)),
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });

    expect(lease.retainForContainment("command-containment")).toBe(true);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "containment-unproved" });
    await expect(lease.assertHeld()).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    await expect(release()).rejects.toThrow(/stale/i);
    expect(releaseUnderlying).not.toHaveBeenCalled();
    const firstReproof = lease.settleForQuit();
    expect(lease.settleForQuit()).toBe(firstReproof);
    await expect(firstReproof).rejects.toThrow("recorded child remains alive");
    expect(releaseUnderlying).not.toHaveBeenCalled();
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "containment-unproved" });

    await expect(lease.settleForQuit()).resolves.toBeUndefined();
    expect(events).toEqual(["reproof-failed", "reproof-succeeded", "release"]);
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("keeps a process-exit-required lease unreacquirable across quit settlement", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const releaseUnderlying = vi.fn(async () => undefined);
    const reconcileOperationContainment = vi.fn(async () => undefined);
    const dependencies = {
      command: { operationLeaseTarget: target, reconcileOperationContainment },
      fileSystem: leaseFileSystem(vi.fn(async () => releaseUnderlying)),
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });

    expect(lease.retainForContainment("process-exit-required")).toBe(true);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "process-exit-required" });
    await expect(lease.settleForQuit()).resolves.toBeUndefined();
    const heldError = await lease.assertHeld().catch((error: unknown) => error);
    expect(heldError).toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect((heldError as SourceOperationLeaseRetentionError).retentionPolicy).toBe("process-exit-required");
    await expect(lease.acquire({ kind: "startup-recovery", signal: new AbortController().signal })).rejects.toThrow(
      /already active/i,
    );
    await expect(release()).rejects.toThrow(/stale/i);
    expect(reconcileOperationContainment).not.toHaveBeenCalled();
    expect(releaseUnderlying).not.toHaveBeenCalled();
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "process-exit-required" });
  });

  it("upgrades lost ownership to process-exit retention when a backend became live", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const releaseUnderlying = vi.fn(async () => undefined);
    const reconcileOperationContainment = vi.fn(async () => undefined);
    const fileSystem = leaseFileSystem(vi.fn(async () => releaseUnderlying));
    const readTextNoFollow = vi.mocked(fileSystem.readTextNoFollow);
    const dependencies = {
      command: { operationLeaseTarget: target, reconcileOperationContainment },
      fileSystem,
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });
    readTextNoFollow.mockResolvedValueOnce(`${JSON.stringify({
      bootIdentity: "darwin:boot-1",
      operationId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      ownerPid: 4321,
    })}\n`);

    await expect(lease.assertHeld()).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "ownership-lost" });
    expect(lease.retainForContainment("process-exit-required")).toBe(true);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "process-exit-required" });
    await expect(lease.settleForQuit()).resolves.toBeUndefined();
    await expect(release()).rejects.toThrow(/stale/i);
    expect(reconcileOperationContainment).not.toHaveBeenCalled();
    expect(releaseUnderlying).not.toHaveBeenCalled();
  });

  it("reconciles a discarded normal release failure before the next acquisition", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const events: string[] = [];
    const firstRelease = vi.fn()
      .mockImplementationOnce(async () => {
        events.push("first-release-failed");
        throw new Error("parent fsync failed");
      })
      .mockImplementationOnce(async () => {
        events.push("first-release-reconciled");
      });
    const secondRelease = vi.fn(async () => {
      events.push("second-release");
    });
    const acquireOperationLock = vi.fn()
      .mockImplementationOnce(async () => firstRelease)
      .mockImplementationOnce(async () => {
        events.push("second-acquire");
        return secondRelease;
      });
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem: leaseFileSystem(acquireOperationLock),
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const discardedRelease = await lease.acquire({
      kind: "update-check",
      signal: new AbortController().signal,
    });
    await expect(discardedRelease()).rejects.toThrow("parent fsync failed");

    const nextRelease = await lease.acquire({
      kind: "update-check",
      signal: new AbortController().signal,
    });

    expect(events).toEqual([
      "first-release-failed",
      "first-release-reconciled",
      "second-acquire",
    ]);
    await expect(discardedRelease()).resolves.toBeUndefined();
    await nextRelease();
    expect(secondRelease).toHaveBeenCalledOnce();
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("fails assertHeld when the durable owner proof no longer belongs to this runtime", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const releaseUnderlying = vi.fn(async () => undefined);
    const fileSystem = leaseFileSystem(vi.fn(async () => releaseUnderlying));
    const dependencies = { command: { operationLeaseTarget: target }, fileSystem } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });
    vi.mocked(fileSystem.readTextNoFollow).mockResolvedValueOnce(`${JSON.stringify({
      bootIdentity: "darwin:foreign-boot",
      operationId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      ownerPid: 9999,
    })}\n`);

    await expect(lease.assertHeld()).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "ownership-lost" });
    await expect(release()).resolves.toBeUndefined();
  });

  it("releases a capability acquired after cancellation and never publishes it as held", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    let settle!: (release: () => Promise<void>) => void;
    const releaseUnderlying = vi.fn(async () => undefined);
    const acquireOperationLock = vi.fn(() => new Promise<() => Promise<void>>((resolve) => { settle = resolve; }));
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem: leaseFileSystem(acquireOperationLock),
    } as unknown as BootstrapDependencies;
    const controller = new AbortController();
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const acquiring = lease.acquire({ kind: "update-check", signal: controller.signal });
    controller.abort();
    settle(releaseUnderlying);

    await expect(acquiring).rejects.toMatchObject({ name: "AbortError" });
    expect(releaseUnderlying).toHaveBeenCalledOnce();
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("retries a cancelled acquisition's retained release before acquiring a new underlying lease", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const events: string[] = [];
    let settle!: (release: () => Promise<void>) => void;
    const releaseCancelled = vi.fn()
      .mockImplementationOnce(async () => {
        events.push("release-cancelled-failed");
        throw new Error("cancel release fsync failed");
      })
      .mockImplementationOnce(async () => {
        events.push("release-cancelled-retried");
      });
    const releaseNext = vi.fn(async () => {
      events.push("release-next");
    });
    const acquireOperationLock = vi.fn()
      .mockImplementationOnce(() => new Promise<() => Promise<void>>((resolve) => {
        events.push("acquire-cancelled");
        settle = resolve;
      }))
      .mockImplementationOnce(async () => {
        events.push("acquire-next");
        return releaseNext;
      });
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem: leaseFileSystem(acquireOperationLock),
    } as unknown as BootstrapDependencies;
    const controller = new AbortController();
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });
    const cancelledAcquire = lease.acquire({ kind: "update-check", signal: controller.signal });
    controller.abort();
    settle(releaseCancelled);

    await expect(cancelledAcquire).rejects.toThrow("could not be durably released");
    expect(lease.getSnapshot()).toEqual({ kind: "update-check", state: "release-failed" });

    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });
    expect(events).toEqual([
      "acquire-cancelled",
      "release-cancelled-failed",
      "release-cancelled-retried",
      "acquire-next",
    ]);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "held" });
    await release();
    await release();
    expect(releaseCancelled).toHaveBeenCalledTimes(2);
    expect(releaseNext).toHaveBeenCalledOnce();
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("retries a failed ownership proof's retained release before acquiring a new underlying lease", async () => {
    const layout = await temporaryLayout();
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const events: string[] = [];
    const releaseUnproven = vi.fn()
      .mockImplementationOnce(async () => {
        events.push("release-unproven-failed");
        throw new Error("proof release fsync failed");
      })
      .mockImplementationOnce(async () => {
        events.push("release-unproven-retried");
      });
    const releaseNext = vi.fn(async () => {
      events.push("release-next");
    });
    const acquireOperationLock = vi.fn()
      .mockImplementationOnce(async () => {
        events.push("acquire-unproven");
        return releaseUnproven;
      })
      .mockImplementationOnce(async () => {
        events.push("acquire-next");
        return releaseNext;
      });
    const fileSystem = leaseFileSystem(acquireOperationLock);
    vi.mocked(fileSystem.readTextNoFollow)
      .mockResolvedValueOnce(`${JSON.stringify({ operationId: "not-owned" })}\n`)
      .mockResolvedValueOnce(`${JSON.stringify({
        bootIdentity: "darwin:boot-1",
        operationId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        ownerPid: 4321,
      })}\n`);
    const dependencies = {
      command: { operationLeaseTarget: target },
      fileSystem,
    } as unknown as BootstrapDependencies;
    const lease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: "darwin:boot-1",
      dependencies,
      ownerPid: 4321,
      singletonAuthorised: true,
      sourceRoot: layout.sourceRoot,
    });

    await expect(lease.acquire({ kind: "update-check", signal: new AbortController().signal }))
      .rejects.toThrow("ownership proof and durable release both failed");
    expect(lease.getSnapshot()).toEqual({ kind: "update-check", state: "release-failed" });

    const release = await lease.acquire({ kind: "update-apply", signal: new AbortController().signal });
    expect(events).toEqual([
      "acquire-unproven",
      "release-unproven-failed",
      "release-unproven-retried",
      "acquire-next",
    ]);
    expect(lease.getSnapshot()).toEqual({ kind: "update-apply", state: "held" });
    await release();
    expect(releaseUnproven).toHaveBeenCalledTimes(2);
    expect(releaseNext).toHaveBeenCalledOnce();
    expect(lease.getSnapshot()).toEqual({ kind: null, state: "idle" });
  });

  it("durably appends redacted JSONL to the private log and surfaces durability failure", async () => {
    const layout = await temporaryLayout();
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const recorder = createDurableSourceUpdaterEventRecorder({ dependencies, ...layout });
    await recorder.record({
      attempt: 2,
      message: `Bearer top-secret from ${layout.sourceRoot}`,
      operation: "update-check",
      phase: "failed",
      promotionId: null,
      revision,
    });
    const line = await readFile(path.join(layout.logs, "desktop-source-update.jsonl"), "utf8");
    expect(JSON.parse(line)).toMatchObject({ attempt: 2, message: expect.stringContaining("<redacted>") });
    expect(line).not.toContain("top-secret");
    expect(line).not.toContain(layout.sourceRoot);

    const failed = createDurableSourceUpdaterEventRecorder({
      dependencies: {
        fileSystem: {
          appendText: vi.fn(async () => { throw new Error("fsync failed"); }),
          ensureDurableDirectory: vi.fn(async () => undefined),
        },
      } as unknown as BootstrapDependencies,
      ...layout,
    });
    await expect(failed.record({
      attempt: 3,
      message: "safe",
      operation: "update-apply",
      phase: "failed",
      promotionId: null,
      revision: null,
    })).rejects.toThrow("fsync failed");
  });

  it("whitelists event fields and redacts mixed-separator extended Windows paths", async () => {
    const layout = await temporaryLayout();
    const dependencies = createNodeBootstrapDependencies(process.platform);
    const recorder = createDurableSourceUpdaterEventRecorder({
      dependencies,
      platform: "win32",
      ...layout,
    });
    const event = {
      attempt: 4,
      message: [
        `Failure below \\\\?\\${layout.sourceRoot.replaceAll("/", "\\").toUpperCase()}`,
        layout.isolationRoot.toUpperCase(),
        layout.workspace.replaceAll("/", "\\").toUpperCase(),
      ].join(" "),
      operation: "update-check",
      phase: "failed",
      promotionId: null,
      revision,
      token: "must-not-be-persisted",
    } satisfies SourceUpdateEvent & { token: string };

    await recorder.record(event);

    const line = await readFile(path.join(layout.logs, "desktop-source-update.jsonl"), "utf8");
    const persisted = JSON.parse(line) as Record<string, unknown>;
    expect(persisted).toEqual({
      attempt: 4,
      message: "Failure below \\\\?\\<source-root> <health-isolation> <workspace>",
      operation: "update-check",
      phase: "failed",
      promotionId: null,
      revision,
    });
    expect(line).not.toContain("must-not-be-persisted");
    expect(line.toLowerCase()).not.toContain(layout.sourceRoot.toLowerCase());
    for (const privateRoot of [layout.sourceRoot, layout.isolationRoot, layout.workspace]) {
      expect(line.toLowerCase()).not.toContain(privateRoot.replaceAll("/", "\\").toLowerCase());
    }
  });

  it("removes only exact identity-proven UUID candidate and isolation directories", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    await Promise.all([mkdir(candidate), mkdir(isolation)]);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    const candidateMetadata = await lstat(candidate);
    const isolationMetadata = await lstat(isolation);

    await cleanup.removeOwnedCandidate({
      candidatePath: candidate,
      identity: { dev: candidateMetadata.dev, ino: candidateMetadata.ino },
      operationId,
    });
    await cleanup.removeIsolation({
      identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
      isolationPath: isolation,
    });
    await expect(readFile(candidate)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(readFile(isolation)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(cleanup.removeOwnedCandidate({
      candidatePath: path.join(layout.sourceRoot, "FlintTrade"),
      identity: { dev: 1, ino: 2 },
      operationId,
    })).rejects.toThrow(/exact owned candidate/i);
    await expect(cleanup.removeIsolation({
      identity: { dev: 1, ino: 2 },
      isolationPath: layout.workspace,
    })).rejects.toThrow(/exact owned isolation/i);
  });

  it("durably inventories and replays exact bootstrap staging directories", async () => {
    const layout = await temporaryLayout();
    const stagingCandidate = path.join(
      layout.sourceRoot,
      `FlintTrade.update-${operationId}.candidate-1`,
    );
    const stagingUnpack = `${stagingCandidate}.unpack`;
    await Promise.all([mkdir(stagingCandidate), mkdir(stagingUnpack)]);
    const candidateMetadata = await lstat(stagingCandidate);
    const unpackMetadata = await lstat(stagingUnpack);
    const retainedRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });

    await retainedRuntime.inventoryOwnedPaths({
      staging: [
        {
          identity: { dev: candidateMetadata.dev, ino: candidateMetadata.ino },
          kind: "staging-candidate",
          operationId,
          stagingPath: stagingCandidate,
        },
        {
          identity: { dev: unpackMetadata.dev, ino: unpackMetadata.ino },
          kind: "staging-unpack",
          operationId,
          stagingPath: stagingUnpack,
        },
      ],
    });
    await expect(lstat(stagingCandidate)).resolves.toMatchObject({ ino: candidateMetadata.ino });
    await expect(lstat(stagingUnpack)).resolves.toMatchObject({ ino: unpackMetadata.ino });

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover();

    for (const removed of [
      stagingCandidate,
      stagingUnpack,
      path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME),
    ]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("rejects bootstrap staging cleanup path near-misses before inventory mutation", async () => {
    const layout = await temporaryLayout();
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    const wrongAttempt = path.join(
      layout.sourceRoot,
      `FlintTrade.update-${operationId}.candidate-2`,
    );
    await mkdir(wrongAttempt);
    const metadata = await lstat(wrongAttempt);

    await expect(cleanup.removeOwnedPaths({
      staging: [{
        identity: { dev: metadata.dev, ino: metadata.ino },
        kind: "staging-candidate",
        operationId,
        stagingPath: wrongAttempt,
      }],
    })).rejects.toThrow(/exact owned bootstrap staging path/i);
    await expect(cleanup.removeOwnedPaths({
      staging: [{
        identity: { dev: metadata.dev, ino: metadata.ino },
        kind: "candidate" as "staging-candidate",
        operationId,
        stagingPath: wrongAttempt,
      }],
    })).rejects.toThrow(/invalid bootstrap staging kind/i);
    await expect(lstat(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME))).rejects.toMatchObject({
      code: "ENOENT",
    });
    await expect(lstat(wrongAttempt)).resolves.toMatchObject({ ino: metadata.ino });
  });

  it("durably reserves every exact UUID-bound cleanup name without persisting a path", async () => {
    const layout = await temporaryLayout();
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    const kinds = ["candidate", "staging-candidate", "staging-unpack", "isolation"] as const;

    await cleanup.reserveOwnedPaths({ kinds, operationId });

    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    const beforeValidation = await readFile(inventoryPath, "utf8");
    expect(JSON.parse(beforeValidation)).toEqual({
      entries: kinds.map((kind) => ({ kind, operationId, state: "reserved" })),
      schemaVersion: 2,
    });
    expect(beforeValidation).not.toContain(layout.sourceRoot);
    expect(beforeValidation).not.toContain(layout.isolationRoot);

    await cleanup.validateRecovery();
    expect(await readFile(inventoryPath, "utf8")).toBe(beforeValidation);
  });

  it("drops absent reservations safely when a fresh runtime recovers before creation", async () => {
    const layout = await temporaryLayout();
    const kinds = ["candidate", "staging-candidate", "staging-unpack", "isolation"] as const;
    await createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() })
      .reserveOwnedPaths({ kinds, operationId });

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover();

    await expect(lstat(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("upgrades a fresh-runtime reservation durably before invoking the safe remover", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const stagingCandidate = `${candidate}.candidate-1`;
    const stagingUnpack = `${stagingCandidate}.unpack`;
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const kinds = ["candidate", "staging-candidate", "staging-unpack", "isolation"] as const;
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    await createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() })
      .reserveOwnedPaths({ kinds, operationId });
    await Promise.all([candidate, stagingCandidate, stagingUnpack, isolation].map((target) => mkdir(target)));
    const candidateMetadata = await lstat(candidate);
    const interruption = new SourceOperationLeaseRetentionError("simulated crash after ownership upgrade");
    const interruptedFileSystem = createNodeSourcePromotionFileSystem({
      safeRemove: async (request) => {
        const inventory = JSON.parse(await readFile(inventoryPath, "utf8")) as {
          entries: Array<Record<string, unknown>>;
          schemaVersion: number;
        };
        expect(inventory.schemaVersion).toBe(2);
        expect(inventory.entries[0]).toEqual({
          dev: candidateMetadata.dev,
          ino: candidateMetadata.ino,
          kind: "candidate",
          operationId,
          state: "owned",
        });
        expect(request.target).toBe(candidate);
        throw interruption;
      },
    });

    await expect(
      createNodeSourceUpdaterCleanup({ ...layout, fileSystem: interruptedFileSystem }).recover(),
    ).rejects.toBe(interruption);
    const retained = JSON.parse(await readFile(inventoryPath, "utf8")) as {
      entries: Array<Record<string, unknown>>;
    };
    expect(retained.entries.map((entry) => entry.state)).toEqual([
      "owned",
      "reserved",
      "reserved",
      "reserved",
    ]);

    const quarantines: string[] = [];
    const freshRuntime = createNodeSourceUpdaterCleanup({
      ...layout,
      fileSystem: createNodeSourcePromotionFileSystem({
        safeRemove: async (request) => {
          quarantines.push(path.basename(request.quarantine));
          await testOnlySafeRemove(request);
        },
      }),
    });
    await freshRuntime.recover();
    expect(quarantines).toEqual([
      `${CLEANUP_QUARANTINE_PREFIX}candidate-${operationId}`,
      `${CLEANUP_QUARANTINE_PREFIX}staging-candidate-1-${operationId}`,
      `${CLEANUP_QUARANTINE_PREFIX}staging-unpack-1-${operationId}`,
      `${CLEANUP_QUARANTINE_PREFIX}isolation-${operationId}`,
    ]);
    for (const removed of [candidate, stagingCandidate, stagingUnpack, isolation, inventoryPath]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("upgrades a reservation from published ownership and removes only selected kinds", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await cleanup.reserveOwnedPaths({ kinds: ["candidate", "isolation"], operationId });
    await Promise.all([mkdir(candidate), mkdir(isolation)]);
    const candidateMetadata = await lstat(candidate);
    await cleanup.inventoryOwnedPaths({
      candidate: {
        candidatePath: candidate,
        identity: { dev: candidateMetadata.dev, ino: candidateMetadata.ino },
        operationId,
      },
    });
    expect(JSON.parse(await readFile(inventoryPath, "utf8"))).toMatchObject({
      entries: [
        { dev: candidateMetadata.dev, ino: candidateMetadata.ino, kind: "candidate", state: "owned" },
        { kind: "isolation", state: "reserved" },
      ],
      schemaVersion: 2,
    });

    await cleanup.removeReservedPaths({ kinds: ["candidate"], operationId });
    await expect(lstat(candidate)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(isolation)).resolves.toBeDefined();
    expect(JSON.parse(await readFile(inventoryPath, "utf8"))).toMatchObject({
      entries: [{ kind: "isolation", state: "reserved" }],
    });

    await createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() }).recover();
    await expect(lstat(isolation)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(inventoryPath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("refuses to reserve a pre-existing name and never claims it as owned", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    await mkdir(candidate);
    const metadata = await lstat(candidate);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });

    await expect(cleanup.reserveOwnedPaths({ kinds: ["candidate"], operationId }))
      .rejects.toThrow(/refusing to reserve an existing/i);
    await expect(lstat(candidate)).resolves.toMatchObject({ ino: metadata.ino });
    await expect(lstat(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("fails closed when an owned reservation is replaced before selected removal", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await cleanup.reserveOwnedPaths({ kinds: ["candidate"], operationId });
    await mkdir(candidate);
    const original = await lstat(candidate);
    await cleanup.inventoryOwnedPaths({
      candidate: {
        candidatePath: candidate,
        identity: { dev: original.dev, ino: original.ino },
        operationId,
      },
    });
    await rm(candidate, { recursive: true });
    await mkdir(candidate);
    const replacement = await lstat(candidate);
    const inventoryBefore = await readFile(inventoryPath, "utf8");

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await expect(freshRuntime.validateRecovery()).rejects.toThrow(/captured directory identity/i);
    await expect(freshRuntime.removeReservedPaths({ kinds: ["candidate"], operationId }))
      .rejects.toThrow(/captured directory identity/i);
    expect(await readFile(inventoryPath, "utf8")).toBe(inventoryBefore);
    await expect(lstat(candidate)).resolves.toMatchObject({ ino: replacement.ino });
    expect(replacement.ino).not.toBe(original.ino);
  });

  it("fails read-only validation on ambiguous, non-directory, and non-strict reservation evidence", async () => {
    const ambiguousLayout = await temporaryLayout();
    const ambiguousInventory = path.join(ambiguousLayout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    const candidate = path.join(ambiguousLayout.sourceRoot, `FlintTrade.update-${operationId}`);
    const quarantine = path.join(
      ambiguousLayout.sourceRoot,
      `${CLEANUP_QUARANTINE_PREFIX}candidate-${operationId}`,
    );
    const ambiguousCleanup = createNodeSourceUpdaterCleanup({
      ...ambiguousLayout,
      fileSystem: cleanupFileSystem(),
    });
    await ambiguousCleanup.reserveOwnedPaths({ kinds: ["candidate"], operationId });
    await Promise.all([mkdir(candidate), mkdir(quarantine)]);
    const ambiguousBefore = await readFile(ambiguousInventory, "utf8");
    await expect(ambiguousCleanup.validateRecovery()).rejects.toThrow(/ambiguous/i);
    expect(await readFile(ambiguousInventory, "utf8")).toBe(ambiguousBefore);
    await expect(lstat(candidate)).resolves.toBeDefined();
    await expect(lstat(quarantine)).resolves.toBeDefined();

    const fileLayout = await temporaryLayout();
    const staging = path.join(
      fileLayout.sourceRoot,
      `FlintTrade.update-${operationId}.candidate-1`,
    );
    const fileCleanup = createNodeSourceUpdaterCleanup({ ...fileLayout, fileSystem: cleanupFileSystem() });
    await fileCleanup.reserveOwnedPaths({ kinds: ["staging-candidate"], operationId });
    await writeFile(staging, "foreign");
    await expect(fileCleanup.validateRecovery()).rejects.toThrow(/no-follow directory/i);
    expect(await readFile(staging, "utf8")).toBe("foreign");

    const strictLayout = await temporaryLayout();
    const strictInventory = path.join(strictLayout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    const invalid = `${JSON.stringify({
      entries: [{
        kind: "candidate",
        operationId,
        path: path.join(strictLayout.sourceRoot, `FlintTrade.update-${operationId}`),
        state: "reserved",
      }],
      schemaVersion: 2,
    })}\n`;
    await writeFile(strictInventory, invalid);
    await expect(
      createNodeSourceUpdaterCleanup({ ...strictLayout, fileSystem: cleanupFileSystem() }).validateRecovery(),
    ).rejects.toThrow(/reservation is invalid/i);
    expect(await readFile(strictInventory, "utf8")).toBe(invalid);
  });

  it("rejects non-canonical uppercase UUID evidence without orphaning its exact path", async () => {
    const layout = await temporaryLayout();
    const uppercaseOperationId = operationId.toUpperCase();
    const uppercaseCandidate = path.join(
      layout.sourceRoot,
      `FlintTrade.update-${uppercaseOperationId}`,
    );
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    await mkdir(uppercaseCandidate);
    const candidateMetadata = await lstat(uppercaseCandidate);
    const invalidInventory = `${JSON.stringify({
      entries: [{ kind: "candidate", operationId: uppercaseOperationId, state: "reserved" }],
      schemaVersion: 2,
    })}\n`;
    await writeFile(inventoryPath, invalidInventory);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });

    await expect(cleanup.validateRecovery()).rejects.toThrow(/inventory entry is invalid/i);
    expect(await readFile(inventoryPath, "utf8")).toBe(invalidInventory);
    await expect(lstat(uppercaseCandidate)).resolves.toMatchObject({ ino: candidateMetadata.ino });

    await rm(inventoryPath);
    const uppercaseIsolation = path.join(
      layout.isolationRoot,
      `source-update-${uppercaseOperationId}`,
    );
    await mkdir(uppercaseIsolation);
    const isolationMetadata = await lstat(uppercaseIsolation);
    await expect(cleanup.removeIsolation({
      identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
      isolationPath: uppercaseIsolation,
    })).rejects.toThrow(/canonical lowercase UUID v4/i);
    await expect(lstat(uppercaseIsolation)).resolves.toMatchObject({ ino: isolationMetadata.ino });
    await expect(cleanup.reserveOwnedPaths({ kinds: ["candidate"], operationId: uppercaseOperationId }))
      .rejects.toThrow(/canonical lowercase UUID v4/i);
  });

  it("reads a v1 owned inventory and replays it through the v2 cleanup engine", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    await mkdir(candidate);
    const metadata = await lstat(candidate);
    await writeFile(inventoryPath, `${JSON.stringify({
      entries: [{ dev: metadata.dev, ino: metadata.ino, kind: "candidate", operationId }],
      schemaVersion: 1,
    })}\n`);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });

    await cleanup.validateRecovery();
    await cleanup.recover();

    await expect(lstat(candidate)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(inventoryPath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("replays v1 ownership after the legacy quarantine rename and rejects non-v1 kinds", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const legacyQuarantine = path.join(
      layout.sourceRoot,
      `${STALE_SOURCE_QUARANTINE_PREFIX}${operationId}`,
    );
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const legacyIsolationQuarantine = path.join(
      layout.isolationRoot,
      `${STALE_SOURCE_QUARANTINE_PREFIX}${operationId}`,
    );
    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    await Promise.all([mkdir(candidate), mkdir(isolation)]);
    const metadata = await lstat(candidate);
    const isolationMetadata = await lstat(isolation);
    await Promise.all([
      rename(candidate, legacyQuarantine),
      rename(isolation, legacyIsolationQuarantine),
    ]);
    await writeFile(inventoryPath, `${JSON.stringify({
      entries: [
        { dev: metadata.dev, ino: metadata.ino, kind: "candidate", operationId },
        { dev: isolationMetadata.dev, ino: isolationMetadata.ino, kind: "isolation", operationId },
      ],
      schemaVersion: 1,
    })}\n`);

    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await cleanup.validateRecovery();
    await cleanup.recover();
    await expect(lstat(legacyQuarantine)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(legacyIsolationQuarantine)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(inventoryPath)).rejects.toMatchObject({ code: "ENOENT" });

    await writeFile(inventoryPath, `${JSON.stringify({
      entries: [{ dev: metadata.dev, ino: metadata.ino, kind: "staging-candidate", operationId }],
      schemaVersion: 1,
    })}\n`);
    await expect(cleanup.validateRecovery()).rejects.toThrow(/v1 inventory has an invalid path kind/i);
  });

  it("marks Windows apply unavailable before any cleanup mutation is needed", async () => {
    const layout = await temporaryLayout();
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, platform: "win32" });

    expect(() => cleanup.assertReady()).toThrow(/unavailable on Windows.*identity-bound/i);
  });

  it("permits journal-less Windows startup recovery but blocks pending directory cleanup", async () => {
    const layout = await temporaryLayout();
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, platform: "win32" });

    await expect(cleanup.validateRecovery()).resolves.toBeUndefined();
    await expect(cleanup.recover()).resolves.toBeUndefined();

    const inventoryPath = path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
    await writeFile(inventoryPath, `${JSON.stringify({
      entries: [{ kind: "candidate", operationId, state: "reserved" }],
      schemaVersion: 2,
    })}\n`);
    await expect(cleanup.validateRecovery()).rejects.toThrow(/unavailable on Windows.*identity-bound/i);
    await expect(cleanup.recover()).rejects.toThrow(/unavailable on Windows.*identity-bound/i);
  });

  it("resumes deterministic candidate cleanup after the quarantine rename", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const quarantine = path.join(
      layout.sourceRoot,
      `${CLEANUP_QUARANTINE_PREFIX}candidate-${operationId}`,
    );
    await mkdir(candidate);
    const metadata = await lstat(candidate);
    await rename(candidate, quarantine);
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    const request = {
      candidatePath: candidate,
      identity: { dev: metadata.dev, ino: metadata.ino },
      operationId,
    };

    await cleanup.removeOwnedCandidate(request);
    await expect(lstat(candidate)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(quarantine)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(cleanup.removeOwnedCandidate(request)).resolves.toBeUndefined();
  });

  it("replays a durable multi-path cleanup inventory in a fresh runtime", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const quarantine = path.join(
      layout.sourceRoot,
      `${CLEANUP_QUARANTINE_PREFIX}candidate-${operationId}`,
    );
    await Promise.all([mkdir(candidate), mkdir(isolation)]);
    const candidateMetadata = await lstat(candidate);
    const isolationMetadata = await lstat(isolation);
    let interrupted = false;
    const interruptedFileSystem = createNodeSourcePromotionFileSystem({
      safeRemove: async (request) => {
        if (!interrupted) {
          interrupted = true;
          await rename(request.target, request.quarantine);
          throw new SourceOperationLeaseRetentionError("simulated contained-remover interruption");
        }
        await testOnlySafeRemove(request);
      },
    });
    const firstRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: interruptedFileSystem });

    await expect(firstRuntime.removeOwnedPaths?.({
      candidate: {
        candidatePath: candidate,
        identity: { dev: candidateMetadata.dev, ino: candidateMetadata.ino },
        operationId,
      },
      isolation: {
        identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
        isolationPath: isolation,
      },
    })).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    await expect(lstat(quarantine)).resolves.toMatchObject({ ino: candidateMetadata.ino });
    await expect(lstat(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME))).resolves.toBeDefined();

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover?.();

    for (const removed of [candidate, quarantine, isolation, path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME)]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("replays inventory-only containment evidence after a fresh runtime starts", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    await Promise.all([mkdir(candidate), mkdir(isolation)]);
    const candidateMetadata = await lstat(candidate);
    const isolationMetadata = await lstat(isolation);
    const retainedRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });

    await retainedRuntime.inventoryOwnedPaths({
      candidate: {
        candidatePath: candidate,
        identity: { dev: candidateMetadata.dev, ino: candidateMetadata.ino },
        operationId,
      },
      isolation: {
        identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
        isolationPath: isolation,
      },
    });
    await expect(lstat(candidate)).resolves.toBeDefined();
    await expect(lstat(isolation)).resolves.toBeDefined();

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover();

    for (const removed of [candidate, isolation, path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME)]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("merges nested promoted-health and apply isolation inventories before fresh-runtime replay", async () => {
    const layout = await temporaryLayout();
    const applyIsolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const promotedIsolation = path.join(layout.isolationRoot, `source-update-${nestedOperationId}`);
    const promotedQuarantine = path.join(
      layout.isolationRoot,
      `${CLEANUP_QUARANTINE_PREFIX}isolation-${nestedOperationId}`,
    );
    await Promise.all([mkdir(applyIsolation), mkdir(promotedIsolation)]);
    const applyMetadata = await lstat(applyIsolation);
    const promotedMetadata = await lstat(promotedIsolation);
    const interruptedFileSystem = createNodeSourcePromotionFileSystem({
      safeRemove: async (request) => {
        await rename(request.target, request.quarantine);
        throw new SourceOperationLeaseRetentionError("promoted-health remover containment is unresolved");
      },
    });
    const retainedRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: interruptedFileSystem });

    await expect(retainedRuntime.removeIsolation({
      identity: { dev: promotedMetadata.dev, ino: promotedMetadata.ino },
      isolationPath: promotedIsolation,
    })).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    await retainedRuntime.inventoryOwnedPaths({
      isolation: {
        identity: { dev: applyMetadata.dev, ino: applyMetadata.ino },
        isolationPath: applyIsolation,
      },
    });
    await expect(lstat(promotedQuarantine)).resolves.toMatchObject({ ino: promotedMetadata.ino });
    await expect(lstat(applyIsolation)).resolves.toMatchObject({ ino: applyMetadata.ino });

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover();

    for (const removed of [
      applyIsolation,
      promotedIsolation,
      promotedQuarantine,
      path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME),
    ]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("inventories a later cleanup batch before replaying an ordinary failed quarantine", async () => {
    const layout = await temporaryLayout();
    const laterIsolation = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const blockedIsolation = path.join(layout.isolationRoot, `source-update-${nestedOperationId}`);
    const blockedQuarantine = path.join(
      layout.isolationRoot,
      `${CLEANUP_QUARANTINE_PREFIX}isolation-${nestedOperationId}`,
    );
    const laterQuarantine = path.join(
      layout.isolationRoot,
      `${CLEANUP_QUARANTINE_PREFIX}isolation-${operationId}`,
    );
    await Promise.all([mkdir(laterIsolation), mkdir(blockedIsolation)]);
    const laterMetadata = await lstat(laterIsolation);
    const blockedMetadata = await lstat(blockedIsolation);
    const failingFileSystem = createNodeSourcePromotionFileSystem({
      safeRemove: async (request) => {
        try {
          await rename(request.target, request.quarantine);
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
        throw new Error("simulated contained helper refusal");
      },
    });
    const retainedRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: failingFileSystem });

    await expect(retainedRuntime.removeIsolation({
      identity: { dev: blockedMetadata.dev, ino: blockedMetadata.ino },
      isolationPath: blockedIsolation,
    })).rejects.toThrow(/contained helper refusal/i);
    await expect(retainedRuntime.removeIsolation({
      identity: { dev: laterMetadata.dev, ino: laterMetadata.ino },
      isolationPath: laterIsolation,
    })).rejects.toThrow(/contained helper refusal/i);
    const inventory = JSON.parse(
      await readFile(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME), "utf8"),
    ) as { entries: Array<{ operationId: string }> };
    expect(inventory.entries.map((entry) => entry.operationId)).toEqual([
      nestedOperationId,
      operationId,
    ]);
    await expect(lstat(blockedQuarantine)).resolves.toMatchObject({ ino: blockedMetadata.ino });
    await expect(lstat(laterIsolation)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(lstat(laterQuarantine)).resolves.toMatchObject({ ino: laterMetadata.ino });

    const freshRuntime = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    await freshRuntime.recover();
    for (const removed of [
      blockedIsolation,
      blockedQuarantine,
      laterIsolation,
      laterQuarantine,
      path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME),
    ]) {
      await expect(lstat(removed)).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  it("refuses cleanup through a final alias and a parent alias", async () => {
    const layout = await temporaryLayout();
    const foreign = path.join(layout.root, "foreign");
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    await mkdir(foreign);
    await symlink(foreign, candidate, "dir");
    const cleanup = createNodeSourceUpdaterCleanup(layout);
    await expect(cleanup.removeOwnedCandidate({
      candidatePath: candidate,
      identity: { dev: 1, ino: 2 },
      operationId,
    })).rejects.toThrow(/symbolic-link/i);

    const aliasedIsolationRoot = path.join(layout.root, "isolation-alias");
    await symlink(layout.isolationRoot, aliasedIsolationRoot, "dir");
    const throughParentAlias = path.join(aliasedIsolationRoot, `source-update-${operationId}`);
    await mkdir(path.join(layout.isolationRoot, `source-update-${operationId}`));
    const aliasCleanup = createNodeSourceUpdaterCleanup({ ...layout, isolationRoot: aliasedIsolationRoot });
    const isolationMetadata = await lstat(path.join(layout.isolationRoot, `source-update-${operationId}`));
    await expect(aliasCleanup.removeIsolation({
      identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
      isolationPath: throughParentAlias,
    })).rejects.toThrow(/alias|canonical|symbolic-link/i);
  });

  it("preserves a foreign replacement at an otherwise exact owned candidate path", async () => {
    const layout = await temporaryLayout();
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    await mkdir(candidate);
    const original = await lstat(candidate);
    await rm(candidate, { recursive: true });
    await mkdir(candidate);
    const replacement = await lstat(candidate);
    const cleanup = createNodeSourceUpdaterCleanup(layout);

    await expect(cleanup.removeOwnedCandidate({
      candidatePath: candidate,
      identity: { dev: original.dev, ino: original.ino },
      operationId,
    })).rejects.toThrow(/captured directory identity/i);
    expect(replacement.ino).not.toBe(original.ino);
    await expect(lstat(candidate)).resolves.toMatchObject({ ino: replacement.ino });
  });

  it("preserves a foreign replacement at an otherwise exact owned isolation path", async () => {
    const layout = await temporaryLayout();
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    await mkdir(isolationPath);
    const original = await lstat(isolationPath);
    await rm(isolationPath, { recursive: true });
    await mkdir(isolationPath);
    const replacement = await lstat(isolationPath);
    const cleanup = createNodeSourceUpdaterCleanup(layout);

    await expect(cleanup.removeIsolation({
      identity: { dev: original.dev, ino: original.ino },
      isolationPath,
    })).rejects.toThrow(/captured directory identity/i);
    expect(replacement.ino).not.toBe(original.ino);
    await expect(lstat(isolationPath)).resolves.toMatchObject({ ino: replacement.ino });
  });

  it("refuses isolation cleanup when no captured identity is supplied at runtime", async () => {
    const layout = await temporaryLayout();
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    await mkdir(isolationPath);
    const cleanup = createNodeSourceUpdaterCleanup(layout);

    await expect(cleanup.removeIsolation({
      identity: undefined as never,
      isolationPath,
    })).rejects.toThrow(/without a captured isolation directory identity/i);
    await expect(lstat(isolationPath)).resolves.toMatchObject({ isDirectory: expect.any(Function) });
  });

  it("prepares exact private health directories before calling the contained health proof", async () => {
    const layout = await temporaryLayout();
    const candidateRoot = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolation = {
      flinttradeHome: path.join(isolationPath, "flinttrade-home"),
      home: path.join(isolationPath, "home"),
      workspace: path.join(isolationPath, "workspace"),
    };
    const preparePrivateTree = vi.fn(async () => undefined);
    const prepared = vi.fn();
    const prove = vi.fn(async () => ({ candidateRoot, port: 43210 }));
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const run = vi.fn(async () => ({ contained: true, exitCode: 0, stderr: "", stdout: "" }));
    const dependencies = {
      command: { operationLeaseTarget: target, run },
      fileSystem: { preparePrivateTree },
    } as unknown as BootstrapDependencies;
    const health = createNodeSourceUpdaterHealth({ dependencies, prove, ...layout });

    const proof = await health.prove({
      candidateRoot,
      isolation,
      onIsolationPrepared: prepared,
      signal: new AbortController().signal,
    });
    expect(proof).toEqual({
      candidateRoot,
      isolationIdentity: prepared.mock.calls[0]?.[0],
      port: 43210,
    });
    const isolationMetadata = await lstat(isolationPath);
    expect(proof.isolationIdentity).toEqual({ dev: isolationMetadata.dev, ino: isolationMetadata.ino });
    expect(preparePrivateTree).toHaveBeenNthCalledWith(1, layout.isolationRoot, [], []);
    expect(preparePrivateTree).toHaveBeenNthCalledWith(
      2,
      isolationPath,
      ["home", "flinttrade-home", "workspace"],
      [],
    );
    expect(run).toHaveBeenCalledWith(expect.objectContaining({
      args: ["-m", "flinttrade_core.cli", "init", "--provision-master-password"],
      command: process.platform === "win32"
        ? path.join(candidateRoot, ".venv", "Scripts", "python.exe")
        : path.join(candidateRoot, ".venv", "bin", "python"),
      cwd: candidateRoot,
      env: expect.objectContaining({
        FLINTTRADE_HOME: isolation.flinttradeHome,
        FLINTTRADE_WORKSPACE_DIR: isolation.workspace,
        HOME: isolation.home,
        PYTHONNOUSERSITE: "1",
      }),
      inheritEnvironment: false,
    }));
    expect(prove).toHaveBeenCalledWith(expect.objectContaining({
      candidateRoot,
      isolation,
      process: dependencies.command,
    }));
    expect(preparePrivateTree.mock.invocationCallOrder[0]).toBeLessThan(prove.mock.invocationCallOrder[0]!);
    expect(run.mock.invocationCallOrder[0]).toBeLessThan(prove.mock.invocationCallOrder[0]!);
  });

  it("refuses and preserves a planted isolation path before provisioning or health", async () => {
    const layout = await temporaryLayout();
    const candidateRoot = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolation = {
      flinttradeHome: path.join(isolationPath, "flinttrade-home"),
      home: path.join(isolationPath, "home"),
      workspace: path.join(isolationPath, "workspace"),
    };
    await mkdir(isolationPath);
    await writeFile(path.join(isolationPath, "planted"), "preserve\n");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const run = vi.fn();
    const prove = vi.fn();
    const dependencies = {
      command: { operationLeaseTarget: target, run },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const health = createNodeSourceUpdaterHealth({ dependencies, prove, ...layout });

    const prepared = vi.fn();
    await expect(health.prove({
      candidateRoot,
      isolation,
      onIsolationPrepared: prepared,
      signal: new AbortController().signal,
    })).rejects.toThrow(/already exists|planted|stale/i);
    expect(prepared).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(prove).not.toHaveBeenCalled();
    await expect(readFile(path.join(isolationPath, "planted"), "utf8")).resolves.toBe("preserve\n");
  });

  it("rejects a repository .env before provisioning and leaves no isolation path", async () => {
    const layout = await temporaryLayout();
    const candidateRoot = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolation = {
      flinttradeHome: path.join(isolationPath, "flinttrade-home"),
      home: path.join(isolationPath, "home"),
      workspace: path.join(isolationPath, "workspace"),
    };
    await mkdir(candidateRoot);
    await writeFile(path.join(candidateRoot, ".env"), "OPENAI_API_KEY=must-not-load\n");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const run = vi.fn();
    const prove = vi.fn();
    const dependencies = {
      command: { operationLeaseTarget: target, run },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const health = createNodeSourceUpdaterHealth({ dependencies, prove, ...layout });

    await expect(health.prove({
      candidateRoot,
      isolation,
      onIsolationPrepared: vi.fn(),
      signal: new AbortController().signal,
    })).rejects.toThrow(/forbidden.*\.env/i);
    expect(run).not.toHaveBeenCalled();
    expect(prove).not.toHaveBeenCalled();
    await expect(lstat(isolationPath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("fails before health on provisioning failure and retains the lease when containment is unproved", async () => {
    const layout = await temporaryLayout();
    const candidateRoot = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolation = {
      flinttradeHome: path.join(isolationPath, "flinttrade-home"),
      home: path.join(isolationPath, "home"),
      workspace: path.join(isolationPath, "workspace"),
    };
    const prove = vi.fn(async () => ({ candidateRoot, port: 43210 }));
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const run = vi.fn(async () => ({ contained: false, exitCode: 1, stderr: "private path", stdout: "" }));
    const dependencies = {
      command: { operationLeaseTarget: target, run },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const health = createNodeSourceUpdaterHealth({ dependencies, prove, ...layout });

    const prepared = vi.fn();
    const error = await health
      .prove({
        candidateRoot,
        isolation,
        onIsolationPrepared: prepared,
        signal: new AbortController().signal,
      })
      .catch((caught: unknown) => caught);
    expect(isSourceOperationLeaseRetentionError(error)).toBe(true);
    const isolationMetadata = await lstat(isolationPath);
    expect(prepared).toHaveBeenCalledWith({ dev: isolationMetadata.dev, ino: isolationMetadata.ino });
    expect(prove).not.toHaveBeenCalled();
  });

  it("publishes captured isolation ownership on ordinary provisioning failure for bounded cleanup", async () => {
    const layout = await temporaryLayout();
    const candidateRoot = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolation = {
      flinttradeHome: path.join(isolationPath, "flinttrade-home"),
      home: path.join(isolationPath, "home"),
      workspace: path.join(isolationPath, "workspace"),
    };
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const dependencies = {
      command: {
        operationLeaseTarget: target,
        run: vi.fn(async () => ({ contained: true, exitCode: 1, stderr: "failed", stdout: "" })),
      },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const health = createNodeSourceUpdaterHealth({ dependencies, prove: vi.fn(), ...layout });
    const prepared = vi.fn();

    await expect(health.prove({
      candidateRoot,
      isolation,
      onIsolationPrepared: prepared,
      signal: new AbortController().signal,
    })).rejects.toThrow(/provisioning failed/i);
    const identity = prepared.mock.calls[0]?.[0] as { dev: number; ino: number };
    const isolationMetadata = await lstat(isolationPath);
    expect(identity).toEqual({ dev: isolationMetadata.dev, ino: isolationMetadata.ino });

    await createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() })
      .removeIsolation({ identity, isolationPath });
    await expect(lstat(isolationPath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("health-proves the exact promoted active source and removes only its disposable isolation", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const assertHeld = vi.fn(async () => undefined);
    const cleanup = {
      assertReady: vi.fn(() => undefined),
      inventoryOwnedPaths: vi.fn(async () => undefined),
      recover: vi.fn(async () => undefined),
      removeIsolation: vi.fn(async () => undefined),
      removeOwnedCandidate: vi.fn(async () => undefined),
      removeOwnedPaths: vi.fn(async () => undefined),
      removeReservedPaths: vi.fn(async () => undefined),
      reserveOwnedPaths: vi.fn(async () => undefined),
      validateRecovery: vi.fn(async () => undefined),
    };
    const prove = vi.fn(async () => ({ candidateRoot: activeSource, port: 43210 }));
    const dependencies = {
      command: {
        operationLeaseTarget: target,
        run: vi.fn(async () => ({ contained: true, exitCode: 0, stderr: "", stdout: "" })),
      },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const lifecycle = createNodeSourcePromotionHealthLifecycle({
      cleanup,
      dependencies,
      operationLease: { assertHeld, target },
      prove,
      uuid: () => operationId,
      ...layout,
    });

    const onBackendStopped = vi.fn();
    await expect(lifecycle.bootActive({ activePath: activeSource, onBackendStopped })).resolves.toBe(true);
    expect(onBackendStopped).not.toHaveBeenCalled();
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    expect(prove).toHaveBeenCalledWith(expect.objectContaining({
      candidateRoot: activeSource,
      isolation: {
        flinttradeHome: path.join(isolationPath, "flinttrade-home"),
        home: path.join(isolationPath, "home"),
        workspace: path.join(isolationPath, "workspace"),
      },
    }));
    expect(cleanup.removeIsolation).toHaveBeenCalledWith({
      identity: expect.objectContaining({ dev: expect.any(Number), ino: expect.any(Number) }),
      isolationPath,
    });
    expect(cleanup.removeOwnedCandidate).not.toHaveBeenCalled();
    expect(assertHeld).toHaveBeenCalledTimes(2);
  });

  it("rejects a non-canonical promoted-health UUID before reserving or creating isolation", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const prove = vi.fn(async () => ({ candidateRoot: activeSource, port: 43210 }));
    const cleanup = createNodeSourceUpdaterCleanup({ ...layout, fileSystem: cleanupFileSystem() });
    const lifecycle = createNodeSourcePromotionHealthLifecycle({
      cleanup,
      dependencies: {
        command: {
          operationLeaseTarget: target,
          run: vi.fn(async () => ({ contained: true, exitCode: 0, stderr: "", stdout: "" })),
        },
        fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
      } as unknown as BootstrapDependencies,
      operationLease: { assertHeld: vi.fn(async () => undefined), target },
      prove,
      uuid: () => operationId.toUpperCase(),
      ...layout,
    });

    await expect(lifecycle.bootActive({
      activePath: activeSource,
      onBackendStopped: vi.fn(),
    })).rejects.toThrow(/canonical lowercase UUID v4/i);
    expect(prove).not.toHaveBeenCalled();
    await expect(lstat(path.join(layout.sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("preserves promoted health evidence and lease when process containment is unproved", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const cleanup = {
      assertReady: vi.fn(() => undefined),
      inventoryOwnedPaths: vi.fn(async () => undefined),
      recover: vi.fn(async () => undefined),
      removeIsolation: vi.fn(async () => undefined),
      removeOwnedCandidate: vi.fn(async () => undefined),
      removeOwnedPaths: vi.fn(async () => undefined),
      removeReservedPaths: vi.fn(async () => undefined),
      reserveOwnedPaths: vi.fn(async () => undefined),
      validateRecovery: vi.fn(async () => undefined),
    };
    const dependencies = {
      command: {
        operationLeaseTarget: target,
        run: vi.fn(async () => ({ contained: true, exitCode: 0, stderr: "", stdout: "" })),
      },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const containmentFailure = new SourceOperationLeaseRetentionError("uncontained");
    const lifecycle = createNodeSourcePromotionHealthLifecycle({
      cleanup,
      dependencies,
      operationLease: { assertHeld: vi.fn(async () => undefined), target },
      prove: vi.fn(async () => { throw containmentFailure; }),
      uuid: () => operationId,
      ...layout,
    });

    await expect(lifecycle.bootActive({
      activePath: activeSource,
      onBackendStopped: vi.fn(),
    })).rejects.toBe(containmentFailure);
    const isolationPath = path.join(layout.isolationRoot, `source-update-${operationId}`);
    const isolationMetadata = await lstat(isolationPath);
    expect(cleanup.inventoryOwnedPaths).toHaveBeenCalledWith({
      isolation: {
        identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
        isolationPath,
      },
    });
    expect(cleanup.removeIsolation).not.toHaveBeenCalled();
  });

  it("preserves containment and inventory failures when promoted health evidence cannot be journalled", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const target = path.join(layout.sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const inventoryFailure = new Error("inventory unavailable");
    const cleanup = {
      assertReady: vi.fn(() => undefined),
      inventoryOwnedPaths: vi.fn()
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(inventoryFailure),
      recover: vi.fn(async () => undefined),
      removeIsolation: vi.fn(async () => undefined),
      removeOwnedCandidate: vi.fn(async () => undefined),
      removeOwnedPaths: vi.fn(async () => undefined),
      removeReservedPaths: vi.fn(async () => undefined),
      reserveOwnedPaths: vi.fn(async () => undefined),
      validateRecovery: vi.fn(async () => undefined),
    };
    const dependencies = {
      command: {
        operationLeaseTarget: target,
        run: vi.fn(async () => ({ contained: true, exitCode: 0, stderr: "", stdout: "" })),
      },
      fileSystem: { preparePrivateTree: vi.fn(async () => undefined) },
    } as unknown as BootstrapDependencies;
    const containmentFailure = new SourceOperationLeaseRetentionError("uncontained");
    const lifecycle = createNodeSourcePromotionHealthLifecycle({
      cleanup,
      dependencies,
      operationLease: { assertHeld: vi.fn(async () => undefined), target },
      prove: vi.fn(async () => { throw containmentFailure; }),
      uuid: () => operationId,
      ...layout,
    });

    const error = await lifecycle.bootActive({
      activePath: activeSource,
      onBackendStopped: vi.fn(),
    }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect((error as Error).message).toMatch(/inventory could not be made durable/i);
    expect((error as Error).cause).toBeInstanceOf(AggregateError);
    expect(((error as Error).cause as AggregateError).errors).toEqual([containmentFailure, inventoryFailure]);
    expect(cleanup.inventoryOwnedPaths).toHaveBeenCalledTimes(2);
    expect(cleanup.removeIsolation).not.toHaveBeenCalled();
  });

  it("validates an exact managed target after scanning every update and LKG alias", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const candidate = path.join(layout.sourceRoot, `FlintTrade.update-${operationId}`);
    const other = path.join(layout.sourceRoot, "FlintTrade.update-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    const identity: ActiveSourceIdentity = {
      canonicalPath: activeSource,
      contentIdentity: "b".repeat(40),
      directoryIdentity: { dev: 1, ino: 2 },
      provenance: "git",
      revision,
    };
    const validate = vi.fn(async () => identity);
    const dependencies = {
      command: { run: vi.fn() },
      fileSystem: { listNames: vi.fn(async () => [path.basename(candidate), path.basename(other), "notes"]) },
    } as unknown as BootstrapDependencies;
    const provenance = createSourceUpdaterProvenance({
      bootstrapResources: path.join(layout.root, "bootstrap-resources"),
      dependencies,
      expected: {
        archiveOrigin: "https://codeload.github.com",
        branch: "main",
        gitOrigin: "https://github.com/navaneeshnagarajan/FlintTrade.git",
        packageManager: "pnpm@9.15.0",
        packageName: "flinttrade-monorepo",
        toolchain: { node: "22.23.1", pnpm: "9.15.0", uv: "0.11.16" },
      },
      platform: process.platform,
      sourceRoot: layout.sourceRoot,
      validate,
    });
    const signal = new AbortController().signal;
    await provenance.validate({
      disallowedAliases: [candidate],
      signal,
      sourcePath: activeSource,
    });
    expect(validate).toHaveBeenCalledWith(expect.objectContaining({
      activeSource,
      disallowedAliases: expect.arrayContaining([
        candidate,
        other,
        path.join(layout.sourceRoot, "FlintTrade.last-known-good"),
      ]),
      signal,
    }));
    await expect(provenance.validate({
      disallowedAliases: [],
      signal: new AbortController().signal,
      sourcePath: path.join(layout.sourceRoot, "foreign"),
    })).rejects.toThrow(/exact managed/i);
  });

  it("fails closed when the managed candidate alias set changes during provenance validation", async () => {
    const layout = await temporaryLayout();
    const activeSource = path.join(layout.sourceRoot, "FlintTrade");
    const first = `FlintTrade.update-${operationId}`;
    const appeared = "FlintTrade.update-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const identity: ActiveSourceIdentity = {
      canonicalPath: activeSource,
      contentIdentity: "b".repeat(40),
      directoryIdentity: { dev: 1, ino: 2 },
      provenance: "git",
      revision,
    };
    const dependencies = {
      command: { run: vi.fn() },
      fileSystem: {
        listNames: vi.fn()
          .mockResolvedValueOnce([first])
          .mockResolvedValueOnce([first, appeared]),
      },
    } as unknown as BootstrapDependencies;
    const provenance = createSourceUpdaterProvenance({
      bootstrapResources: path.join(layout.root, "bootstrap-resources"),
      dependencies,
      expected: {
        archiveOrigin: "https://codeload.github.com",
        branch: "main",
        gitOrigin: "https://github.com/navaneeshnagarajan/FlintTrade.git",
        packageManager: "pnpm@9.15.0",
        packageName: "flinttrade-monorepo",
        toolchain: { node: "22.23.1", pnpm: "9.15.0", uv: "0.11.16" },
      },
      platform: process.platform,
      sourceRoot: layout.sourceRoot,
      validate: vi.fn(async () => identity),
    });

    await expect(provenance.validate({
      disallowedAliases: [],
      signal: new AbortController().signal,
      sourcePath: activeSource,
    })).rejects.toThrow(/aliases changed/i);
  });

  it("resolves revisions through the fixed exact FlintTrade repository configuration", async () => {
    const layout = await temporaryLayout();
    const exact: ExactSourceRevision = { provenance: "git", revision };
    const resolve = vi.fn(async () => exact);
    const dependencies = { command: { run: vi.fn() }, download: { text: vi.fn() } } as unknown as BootstrapDependencies;
    const adapter = createSourceUpdaterRevisionResolver({ dependencies, platform: process.platform, resolve });
    const signal = new AbortController().signal;
    await expect(adapter.resolve(signal)).resolves.toEqual(exact);
    expect(resolve).toHaveBeenCalledWith({ dependencies, platform: process.platform, repository: FLINTTRADE_SOURCE_REPOSITORY, signal });
    expect(FLINTTRADE_SOURCE_REPOSITORY).toMatchObject({
      archiveAllowedHosts: ["codeload.github.com"],
      branch: "main",
      gitOrigin: "https://github.com/navaneeshnagarajan/FlintTrade.git",
      metadataAllowedHosts: ["api.github.com"],
    });
    expect(layout.root).toBeTruthy();
  });
});
