import { access, lstat, mkdir, mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import type { BootstrapDependencies, BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies } from "./bootstrap-io";
import { createSourceOperationCoordinator } from "./source-operation";
import { createNodeSourcePromotionFileSystem } from "./source-promotion";
import { SOURCE_CLEANUP_INVENTORY_NAME, createNodeSourceUpdaterCleanup } from "./source-update-io";
import { createSourceUpdateRuntime, sourceUpdateIsolationRoot } from "./source-update-runtime";
import { createUpdateState } from "./state";

const manifest = {
  node: { assets: {}, version: "22.23.1" },
  pnpm: { integrity: "sha512-test", packageManager: "pnpm@10.34.5+sha512.test", version: "10.34.5" },
  schemaVersion: 1,
  uv: { assets: {}, version: "0.11.16" },
} as unknown as BootstrapToolManifest;

describe("source update runtime composition", () => {
  const roots: string[] = [];

  afterEach(async () => {
    await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
  });

  it("derives a stable private temporary root without exposing the workspace path", () => {
    const workspace = path.join(path.sep, "Users", "person", ".flinttrade");
    const temporary = path.join(path.sep, "private", "tmp");
    const first = sourceUpdateIsolationRoot(workspace, temporary);

    expect(first).toBe(sourceUpdateIsolationRoot(workspace, temporary));
    expect(path.dirname(first)).toBe(temporary);
    expect(first).not.toContain("person");
    expect(first).toMatch(/flinttrade-source-health-[0-9a-f]{20}$/);
  });

  it("composes the Linux workspace/src layout, prepares roots, and requires an idle lease before quit", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-"));
    roots.push(root);
    const workspace = path.join(root, ".flinttrade");
    const sourceRoot = path.join(workspace, "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const preparePrivateTree = vi.fn(async () => undefined);
    const dependencies = {
      command: { operationLeaseTarget, run: vi.fn() },
      download: { file: vi.fn(), text: vi.fn() },
      extractArchive: vi.fn(),
      fileSystem: {
        existsNoFollow: vi.fn(async () => true),
        preparePrivateTree,
        realpath: vi.fn(async (target: string) => target),
      },
    } as unknown as BootstrapDependencies;
    const coordinator = createSourceOperationCoordinator();
    const runtime = createSourceUpdateRuntime({
      arch: "x64",
      bootIdentity: "linux:boot",
      bootstrapResources: path.join(root, "resources"),
      coordinator,
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(workspace, "tools"),
        workspace,
      },
      platform: "linux",
      singletonAuthorised: true,
      state: createUpdateState("source"),
    });

    await runtime.prepare();
    expect(preparePrivateTree).toHaveBeenNthCalledWith(1, workspace, [], []);
    expect(preparePrivateTree).toHaveBeenNthCalledWith(2, workspace, ["src"], []);
    expect(preparePrivateTree).toHaveBeenNthCalledWith(3, path.join(root, "health"), [], []);
    expect(preparePrivateTree).toHaveBeenCalledTimes(3);
    expect(runtime.operationLease.getSnapshot()).toEqual({ kind: null, state: "idle" });
    expect(runtime.cancelRecovery()).toBe(false);
    await expect(runtime.settleForQuit()).resolves.toBeUndefined();
  });

  it("retries a retained lease release on each quit attempt after the coordinator is terminal", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-release-retry-"));
    roots.push(root);
    const workspace = path.join(root, ".flinttrade");
    const sourceRoot = path.join(workspace, "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const nodeDependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
    let releaseAttempts = 0;
    const dependencies = {
      ...nodeDependencies,
      fileSystem: {
        ...nodeDependencies.fileSystem,
        async acquireOperationLock(input) {
          const release = await nodeDependencies.fileSystem.acquireOperationLock(input);
          return async () => {
            await release();
            if (releaseAttempts++ < 2) throw new Error("transient retained release failure");
          };
        },
      },
    } satisfies BootstrapDependencies;
    const coordinator = createSourceOperationCoordinator();
    const runtime = createSourceUpdateRuntime({
      arch: process.arch,
      bootIdentity: "linux:release-retry",
      bootstrapResources: path.join(root, "resources"),
      coordinator,
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(workspace, "tools"),
        workspace,
      },
      platform: process.platform,
      singletonAuthorised: true,
      state: createUpdateState("source"),
    });
    await runtime.prepare();
    const release = await runtime.operationLease.acquire({
      kind: "update-check",
      signal: new AbortController().signal,
    });

    await expect(release()).rejects.toThrow("transient retained release failure");
    expect(runtime.operationLease.getSnapshot()).toEqual({ kind: "update-check", state: "release-failed" });
    await coordinator.shutdown();

    await expect(runtime.settleForQuit()).rejects.toThrow("transient retained release failure");
    expect(runtime.operationLease.getSnapshot()).toEqual({ kind: "update-check", state: "release-failed" });

    await expect(runtime.settleForQuit()).resolves.toBeUndefined();
    expect(runtime.operationLease.getSnapshot()).toEqual({ kind: null, state: "idle" });
    expect(releaseAttempts).toBe(3);
  });

  it("keeps quit fail-closed until retained command containment is re-proven", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-containment-reproof-"));
    roots.push(root);
    const workspace = path.join(root, ".flinttrade");
    const sourceRoot = path.join(workspace, "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const nodeDependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
    const reconcileOperationContainment = vi.fn()
      .mockRejectedValueOnce(new Error("recorded process remains alive"))
      .mockResolvedValueOnce(undefined);
    const dependencies = {
      ...nodeDependencies,
      command: { ...nodeDependencies.command, reconcileOperationContainment },
    } satisfies BootstrapDependencies;
    const coordinator = createSourceOperationCoordinator();
    const runtime = createSourceUpdateRuntime({
      arch: process.arch,
      bootIdentity: "runtime:containment-reproof",
      bootstrapResources: path.join(root, "resources"),
      coordinator,
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(workspace, "tools"),
        workspace,
      },
      platform: process.platform,
      singletonAuthorised: true,
      state: createUpdateState("source"),
    });
    await runtime.prepare();
    await runtime.operationLease.acquire({
      kind: "update-apply",
      signal: new AbortController().signal,
    });
    expect(runtime.operationLease.retainForContainment("command-containment")).toBe(true);
    await coordinator.shutdown();

    await expect(runtime.settleForQuit()).rejects.toThrow("recorded process remains alive");
    expect(runtime.operationLease.getSnapshot()).toEqual({
      kind: "update-apply",
      state: "containment-unproved",
    });
    await expect(access(operationLeaseTarget)).resolves.toBeUndefined();

    await expect(runtime.settleForQuit()).resolves.toBeUndefined();
    expect(runtime.operationLease.getSnapshot()).toEqual({ kind: null, state: "idle" });
    await expect(access(operationLeaseTarget)).rejects.toThrow();
    expect(reconcileOperationContainment).toHaveBeenCalledTimes(2);
  });

  it("permits quit while preserving a process-exit lease without containment reconciliation", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-process-exit-"));
    roots.push(root);
    const workspace = path.join(root, ".flinttrade");
    const sourceRoot = path.join(workspace, "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    const nodeDependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
    const reconcileOperationContainment = vi.fn(async () => undefined);
    const dependencies = {
      ...nodeDependencies,
      command: { ...nodeDependencies.command, reconcileOperationContainment },
    } satisfies BootstrapDependencies;
    const coordinator = createSourceOperationCoordinator();
    const runtime = createSourceUpdateRuntime({
      arch: process.arch,
      bootIdentity: "runtime:process-exit",
      bootstrapResources: path.join(root, "resources"),
      coordinator,
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(workspace, "tools"),
        workspace,
      },
      platform: process.platform,
      singletonAuthorised: true,
      state: createUpdateState("source"),
    });
    await runtime.prepare();
    const release = await runtime.operationLease.acquire({
      kind: "update-apply",
      signal: new AbortController().signal,
    });
    expect(runtime.operationLease.retainForContainment("process-exit-required")).toBe(true);
    await coordinator.shutdown();

    await expect(runtime.settleForQuit()).resolves.toBeUndefined();
    expect(runtime.operationLease.getSnapshot()).toEqual({
      kind: "update-apply",
      state: "process-exit-required",
    });
    await expect(access(operationLeaseTarget)).resolves.toBeUndefined();
    await expect(runtime.operationLease.acquire({
      kind: "startup-recovery",
      signal: new AbortController().signal,
    })).rejects.toThrow("already active in this runtime");
    await expect(release()).rejects.toThrow("release capability is stale");
    expect(reconcileOperationContainment).not.toHaveBeenCalled();
  });

  it("creates a clean macOS-style source parent and permits journal-less recovery without a lifecycle", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-clean-mac-"));
    roots.push(root);
    const home = path.join(root, "home");
    const applicationSupport = path.join(home, "Library", "Application Support");
    const workspace = path.join(applicationSupport, "flinttrade");
    const sourceHome = path.join(home, ".flinttrade");
    const sourceRoot = path.join(sourceHome, "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    await mkdir(applicationSupport, { recursive: true });
    const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
    const runtime = createSourceUpdateRuntime({
      arch: process.arch,
      bootIdentity: "darwin:clean-boot",
      bootstrapResources: path.join(root, "resources"),
      coordinator: createSourceOperationCoordinator(),
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
        isAvailable: () => false,
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(sourceHome, "tools"),
        workspace,
      },
      platform: "darwin",
      singletonAuthorised: true,
      state: createUpdateState("source"),
    });

    await runtime.prepare();

    await expect(access(workspace)).resolves.toBeUndefined();
    await expect(access(sourceHome)).resolves.toBeUndefined();
    await expect(access(sourceRoot)).resolves.toBeUndefined();
    await expect(runtime.updater.recover()).resolves.toEqual({ status: "idle" });
  });

  it("permits clean Windows journal-less startup recovery", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-clean-windows-"));
    roots.push(root);
    const workspace = path.join(root, "AppData", "Roaming", "flinttrade");
    const sourceRoot = path.join(root, ".flinttrade", "src");
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    await mkdir(path.dirname(workspace), { recursive: true });
    const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
    const runtime = createSourceUpdateRuntime({
      arch: "x64",
      bootIdentity: "win32:clean-boot",
      bootstrapResources: path.join(root, "resources"),
      coordinator: createSourceOperationCoordinator(),
      dependencies,
      isolationRoot: path.join(root, "health"),
      lifecycle: {
        bootActive: vi.fn(async () => true),
        drainCurrent: vi.fn(async () => undefined),
        isAvailable: () => false,
      },
      manifest,
      paths: {
        activeSource: path.join(sourceRoot, "FlintTrade"),
        logs: path.join(workspace, "logs"),
        sourceRoot,
        toolsRoot: path.join(root, ".flinttrade", "tools"),
        workspace,
      },
      platform: "win32",
      singletonAuthorised: true,
      state: createUpdateState("source"),
      windowsSourceFilesystem: {
        commitJournal: vi.fn(async () => undefined),
        inspectDirectory: vi.fn(async () => ({ status: "missing" as const })),
        inspectJournal: vi.fn(async () => ({ status: "missing" as const })),
        quarantineDirectory: vi.fn(async () => ({ status: "quarantined" as const })),
        removeQuarantinedDirectory: vi.fn(async () => ({ status: "removed" as const })),
        removeJournal: vi.fn(async () => undefined),
        renameDirectory: vi.fn(async () => undefined),
      },
    });

    await runtime.prepare();

    await expect(runtime.updater.recover()).resolves.toEqual({ status: "idle" });
  });

  it.skipIf(process.platform === "win32")(
    "rejects an isolation root whose intermediate alias enters the active checkout before creating health state",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-isolation-alias-"));
      roots.push(root);
      const workspace = path.join(root, "workspace");
      const sourceRoot = path.join(root, "managed-source");
      const activeSource = path.join(sourceRoot, "FlintTrade");
      const activeEnvironment = path.join(activeSource, ".venv");
      const healthParent = path.join(activeEnvironment, "nested");
      const temporaryRoot = path.join(root, "temporary");
      const alias = path.join(temporaryRoot, "alias");
      const isolationRoot = path.join(alias, "nested", "health");
      const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
      await mkdir(workspace, { recursive: true });
      await mkdir(healthParent, { recursive: true });
      await mkdir(temporaryRoot, { recursive: true });
      await symlink(activeEnvironment, alias, "dir");
      const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
      const runtime = createSourceUpdateRuntime({
        arch: process.arch,
        bootIdentity: `${process.platform}:isolation-alias`,
        bootstrapResources: path.join(root, "resources"),
        coordinator: createSourceOperationCoordinator(),
        dependencies,
        isolationRoot,
        lifecycle: {
          bootActive: vi.fn(async () => true),
          drainCurrent: vi.fn(async () => undefined),
          isAvailable: () => false,
        },
        manifest,
        paths: {
          activeSource,
          logs: path.join(workspace, "logs"),
          sourceRoot,
          toolsRoot: path.join(workspace, "tools"),
          workspace,
        },
        platform: process.platform,
        singletonAuthorised: true,
        state: createUpdateState("source"),
      });

      await expect(runtime.prepare()).rejects.toThrow(/isolation.*overlap/i);
      await expect(access(path.join(healthParent, "health"))).rejects.toThrow();
    },
  );

  it.skipIf(process.platform === "win32")(
    "recreates an absent deterministic isolation root before fresh-runtime cleanup recovery",
    async () => {
      const root = await mkdtemp(path.join(tmpdir(), "flinttrade-source-runtime-isolation-recovery-"));
      roots.push(root);
      const workspace = path.join(root, ".flinttrade");
      const sourceRoot = path.join(workspace, "src");
      const isolationRoot = sourceUpdateIsolationRoot(workspace, root);
      const operationId = "12345678-1234-4123-8123-123456789abc";
      const isolationPath = path.join(isolationRoot, `source-update-${operationId}`);
      await mkdir(sourceRoot, { mode: 0o700, recursive: true });
      await mkdir(isolationPath, { mode: 0o700, recursive: true });
      const isolationMetadata = await lstat(isolationPath);
      const retainedCleanup = createNodeSourceUpdaterCleanup({
        isolationRoot,
        platform: process.platform,
        safeRemovalSupported: true,
        sourceRoot,
        workspace,
      });
      await retainedCleanup.inventoryOwnedPaths({
        isolation: {
          identity: { dev: isolationMetadata.dev, ino: isolationMetadata.ino },
          isolationPath,
        },
      });
      const inventoryPath = path.join(sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);
      await expect(access(inventoryPath)).resolves.toBeUndefined();

      await rm(isolationRoot, { recursive: true });
      await expect(access(isolationRoot)).rejects.toThrow();

      const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
      const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
      const runtime = createSourceUpdateRuntime({
        arch: process.arch,
        bootIdentity: `${process.platform}:fresh-isolation-recovery`,
        bootstrapResources: path.join(root, "resources"),
        coordinator: createSourceOperationCoordinator(),
        dependencies,
        isolationRoot,
        lifecycle: {
          bootActive: vi.fn(async () => true),
          drainCurrent: vi.fn(async () => undefined),
          isAvailable: () => false,
        },
        manifest,
        paths: {
          activeSource: path.join(sourceRoot, "FlintTrade"),
          logs: path.join(workspace, "logs"),
          sourceRoot,
          toolsRoot: path.join(workspace, "tools"),
          workspace,
        },
        platform: process.platform,
        singletonAuthorised: true,
        state: createUpdateState("source"),
      });

      await runtime.prepare();
      const recreatedRoot = await lstat(isolationRoot);
      expect(recreatedRoot.isDirectory()).toBe(true);
      expect(recreatedRoot.isSymbolicLink()).toBe(false);
      expect(recreatedRoot.mode & 0o777).toBe(0o700);
      await expect(runtime.updater.recover()).resolves.toEqual({ status: "idle" });
      await expect(createNodeSourcePromotionFileSystem().readJournal(inventoryPath)).resolves.toBeNull();
      await expect(access(inventoryPath)).resolves.toBeUndefined();
      await expect(lstat(isolationRoot)).resolves.toMatchObject({ ino: recreatedRoot.ino });
    },
  );
});
