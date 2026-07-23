import { createHash, randomUUID } from "node:crypto";
import os from "node:os";
import path from "node:path";

import type { BootstrapDependencies, BootstrapToolManifest } from "./bootstrap";
import { candidatePythonPath } from "./candidate-health";
import { createSafeDirectoryRemover } from "./safe-directory-removal";
import { createSourceCandidateStager } from "./source-candidate";
import { isSourceOperationLeaseRetentionError, type SourceOperationCoordinator } from "./source-operation";
import { createNodeSourcePromotionFileSystem, createSourcePromotion } from "./source-promotion";
import { createSourceUpdateIdentityDependencies } from "./source-update-identity";
import {
  FLINTTRADE_SOURCE_REPOSITORY,
  createDurableSourceUpdaterEventRecorder,
  createNodeSourceUpdaterCleanup,
  createNodeSourceUpdaterHealth,
  createRuntimeSourceUpdaterOperationLease,
  createSourceUpdaterProvenance,
  createSourceUpdaterRevisionResolver,
  type RuntimeSourceUpdaterOperationLease,
} from "./source-update-io";
import { createSourceUpdater, type SourceUpdater, type SourceUpdaterLifecycle } from "./source-updater";
import type { DesktopPaths } from "./paths";
import { sourceContentIdentityKey } from "./source-provenance";
import type { createUpdateState } from "./state";
import {
  createWindowsSourceFilesystemBoundary,
  type WindowsSourceFilesystemBoundary,
} from "./windows-source-filesystem";

type SourceUpdateState = ReturnType<typeof createUpdateState>;

const WINDOWS_RECLAMATION_PRESERVE_CODES = new Set([
  "ALIASED_PATH",
  "DIRECTORY_CHANGED",
  "EBUSY",
  "PATH_ESCAPE",
  "RECLAMATION_BUDGET_EXCEEDED",
  "REPARSE_POINT",
  "UNEXPECTED_ENTRY_TYPE",
]);

function isPathWithin(parent: string, child: string, platform: NodeJS.Platform): boolean {
  const comparisonParent = platform === "win32" ? parent.toLowerCase() : parent;
  const comparisonChild = platform === "win32" ? child.toLowerCase() : child;
  const relative = path.relative(comparisonParent, comparisonChild);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function assertCanonicalIsolationSeparated(
  isolationRoot: string,
  sourceRoot: string,
  workspace: string,
  platform: NodeJS.Platform,
): void {
  if (
    isPathWithin(isolationRoot, sourceRoot, platform) ||
    isPathWithin(sourceRoot, isolationRoot, platform) ||
    isPathWithin(isolationRoot, workspace, platform) ||
    isPathWithin(workspace, isolationRoot, platform)
  ) {
    throw new Error("Source update isolation root must not overlap the managed source or backend workspace.");
  }
}

async function canonicalProspectivePath(
  fileSystem: BootstrapDependencies["fileSystem"],
  target: string,
): Promise<string> {
  let ancestor = path.resolve(target);
  const missing: string[] = [];
  for (;;) {
    if (await fileSystem.existsNoFollow(ancestor)) {
      return path.resolve(await fileSystem.realpath(ancestor), ...missing);
    }
    const parent = path.dirname(ancestor);
    if (parent === ancestor) {
      throw new Error("Source update path has no existing canonical ancestor.");
    }
    missing.unshift(path.basename(ancestor));
    ancestor = parent;
  }
}

export interface SourceUpdateRuntimeOptions {
  arch: string;
  bootIdentity: string;
  bootstrapResources: string;
  coordinator: SourceOperationCoordinator;
  dependencies: BootstrapDependencies;
  isolationRoot?: string;
  lifecycle: SourceUpdaterLifecycle;
  manifest: BootstrapToolManifest;
  paths: DesktopPaths;
  platform: NodeJS.Platform;
  singletonAuthorised: boolean;
  state: SourceUpdateState;
  windowsSourceFilesystem?: WindowsSourceFilesystemBoundary;
  windowsSourceFilesystemHelperSha256?: string;
  windowsSourceFilesystemHelper?: string;
}

export interface SourceUpdateRuntime {
  cancelRecovery(): boolean;
  isolationRoot: string;
  operationLease: RuntimeSourceUpdaterOperationLease;
  prepare(): Promise<void>;
  settleForQuit(): Promise<void>;
  updater: SourceUpdater;
}

export function sourceUpdateIsolationRoot(
  workspace: string,
  temporaryDirectory = os.tmpdir(),
): string {
  if (!path.isAbsolute(workspace) || !path.isAbsolute(temporaryDirectory)) {
    throw new Error("Source update workspace and temporary root must be absolute paths.");
  }
  const identity = createHash("sha256").update(path.resolve(workspace)).digest("hex").slice(0, 20);
  return path.join(path.resolve(temporaryDirectory), `flinttrade-source-health-${identity}`);
}

export function createSourceUpdateRuntime(options: SourceUpdateRuntimeOptions): SourceUpdateRuntime {
  const isolationRoot = path.resolve(options.isolationRoot ?? sourceUpdateIsolationRoot(options.paths.workspace));
  const operationLease = createRuntimeSourceUpdaterOperationLease({
    bootIdentity: options.bootIdentity,
    dependencies: options.dependencies,
    singletonAuthorised: options.singletonAuthorised,
    sourceRoot: options.paths.sourceRoot,
  });
  const windowsSourceFilesystem = options.platform === "win32"
    ? options.windowsSourceFilesystem ?? createWindowsSourceFilesystemBoundary({
        dependencies: options.dependencies,
        expectedHelperSha256: options.windowsSourceFilesystemHelperSha256 ?? "",
        helper: options.windowsSourceFilesystemHelper ?? "",
        operationLease,
      })
    : undefined;
  const sourceUpdateIdentityDependencies = createSourceUpdateIdentityDependencies({
    dependencies: options.dependencies,
    operationLease,
    platform: options.platform,
    ...(windowsSourceFilesystem ? { windowsSourceFilesystem } : {}),
  });
  const safeRemove = options.platform === "win32"
    ? async ({ expected, quarantine, target }: {
        expected: { nativeIdentity?: string };
        quarantine: string;
        target: string;
      }): Promise<{ status: "quarantined" | "removed" }> => {
        if (!windowsSourceFilesystem || !expected.nativeIdentity) {
          throw new Error("Windows source cleanup requires an exact native directory identity.");
        }
        await windowsSourceFilesystem.quarantineDirectory({
          expectedNativeIdentity: expected.nativeIdentity,
          quarantine,
          target,
        });
        try {
          await windowsSourceFilesystem.removeQuarantinedDirectory({
            expectedNativeIdentity: expected.nativeIdentity,
            quarantine,
          });
          return { status: "removed" };
        } catch (error) {
          if (isSourceOperationLeaseRetentionError(error)) throw error;
          if (WINDOWS_RECLAMATION_PRESERVE_CODES.has((error as NodeJS.ErrnoException).code ?? "")) {
            const retained = await windowsSourceFilesystem.inspectDirectory(quarantine);
            if (retained.status === "present" && retained.nativeIdentity === expected.nativeIdentity) {
              return { status: "quarantined" };
            }
          }
          throw error;
        }
      }
    : createSafeDirectoryRemover({
        bootstrapResources: options.bootstrapResources,
        dependencies: options.dependencies,
        operationLease,
        platform: options.platform,
        pythonExecutable: candidatePythonPath(options.paths.activeSource),
      });
  const promotionFileSystem = createNodeSourcePromotionFileSystem({
    platform: options.platform,
    promoteAbsent: options.dependencies.fileSystem.promoteAbsent,
    safeRemove,
    ...(windowsSourceFilesystem ? { windows: windowsSourceFilesystem } : {}),
  });
  const cleanup = createNodeSourceUpdaterCleanup({
    fileSystem: promotionFileSystem,
    isolationRoot,
    platform: options.platform,
    safeRemovalSupported: options.platform !== "win32" || promotionFileSystem.supportsDurableWindowsMutations === true,
    sourceRoot: options.paths.sourceRoot,
    workspace: options.paths.workspace,
  });
  const healthOptions = {
    dependencies: options.dependencies,
    isolationRoot,
    sourceRoot: options.paths.sourceRoot,
    workspace: options.paths.workspace,
  };
  const provenance = createSourceUpdaterProvenance({
    bootstrapResources: options.bootstrapResources,
    dependencies: sourceUpdateIdentityDependencies,
    expected: {
      archiveOrigin: new URL(FLINTTRADE_SOURCE_REPOSITORY.archiveBaseUrl).origin,
      branch: FLINTTRADE_SOURCE_REPOSITORY.branch,
      gitOrigin: FLINTTRADE_SOURCE_REPOSITORY.gitOrigin,
      packageManager: options.manifest.pnpm.packageManager,
      packageName: "flinttrade-monorepo",
      toolchain: {
        node: options.manifest.node.version,
        pnpm: options.manifest.pnpm.version,
        uv: options.manifest.uv.version,
      },
    },
    platform: options.platform,
    sourceRoot: options.paths.sourceRoot,
  });
  const promotion = createSourcePromotion({
    fileSystem: promotionFileSystem,
    lifecycle: {
      bootActive: (input) => options.lifecycle.bootActive(input),
      isAvailable: () => options.lifecycle.isAvailable?.() ?? true,
      async stopActive(activePath) {
        if (path.resolve(activePath) !== path.resolve(options.paths.activeSource)) {
          throw new Error("Source promotion can stop only the exact managed active backend.");
        }
        await operationLease.assertHeld();
        let stopped = false;
        await options.lifecycle.drainCurrent({
          onBackendStopped() {
            if (stopped) throw new Error("Source promotion lifecycle reported duplicate backend stop proof.");
            stopped = true;
          },
          signal: new AbortController().signal,
        });
        if (!stopped) throw new Error("Source promotion lifecycle did not prove the booted backend stopped.");
        await operationLease.assertHeld();
      },
      async validateActiveContent(activePath, expectedContentIdentity) {
        await operationLease.assertHeld();
        const identity = await provenance.validate({
          disallowedAliases: [],
          signal: new AbortController().signal,
          sourcePath: activePath,
        });
        await operationLease.assertHeld();
        return sourceContentIdentityKey(identity) === expectedContentIdentity;
      },
    },
    onBoundary: () => operationLease.assertHeld(),
    platform: options.platform,
    sourceRoot: options.paths.sourceRoot,
  });
  const candidateStager = createSourceCandidateStager({
    bootstrap: {
      arch: options.arch,
      bootIdentity: options.bootIdentity,
      bootstrapResources: options.bootstrapResources,
      dependencies: sourceUpdateIdentityDependencies,
      manifest: options.manifest,
      paths: options.paths,
      platform: options.platform,
      singletonAuthorised: options.singletonAuthorised,
    },
    operationLease,
  });
  const updater = createSourceUpdater({
    activeSource: options.paths.activeSource,
    candidateStager,
    cleanup,
    coordinator: options.coordinator,
    events: createDurableSourceUpdaterEventRecorder({
      dependencies: options.dependencies,
      isolationRoot,
      logs: options.paths.logs,
      sourceRoot: options.paths.sourceRoot,
      workspace: options.paths.workspace,
    }),
    health: createNodeSourceUpdaterHealth(healthOptions),
    isolationRoot,
    lifecycle: options.lifecycle,
    operationLease,
    promotion,
    provenance,
    revisionResolver: createSourceUpdaterRevisionResolver({
      dependencies: options.dependencies,
      platform: options.platform,
    }),
    sourceRoot: options.paths.sourceRoot,
    state: options.state,
    platform: options.platform,
    redactedPaths: [options.paths.workspace, options.paths.logs],
    uuid: randomUUID,
  });

  return {
    async settleForQuit(): Promise<void> {
      await operationLease.settleForQuit();
      const lease = operationLease.getSnapshot();
      if (lease.state !== "idle" && lease.state !== "process-exit-required") {
        throw new Error("The source-operation lease is neither durably idle nor retained until process exit; quit remains fail-closed.");
      }
    },
    cancelRecovery: () => options.coordinator.cancelActive("startup-recovery"),
    isolationRoot,
    operationLease,
    async prepare(): Promise<void> {
      const assertProspectiveSeparation = async (): Promise<void> => {
        const [canonicalIsolation, canonicalSource, canonicalWorkspace] = await Promise.all([
          canonicalProspectivePath(options.dependencies.fileSystem, isolationRoot),
          canonicalProspectivePath(options.dependencies.fileSystem, options.paths.sourceRoot),
          canonicalProspectivePath(options.dependencies.fileSystem, options.paths.workspace),
        ]);
        assertCanonicalIsolationSeparated(
          canonicalIsolation,
          canonicalSource,
          canonicalWorkspace,
          options.platform,
        );
      };

      // Resolve through every existing ancestor before creating anything. This rejects a
      // lexical temporary path whose intermediate symlink enters either managed tree.
      await assertProspectiveSeparation();
      await options.dependencies.fileSystem.preparePrivateTree(options.paths.workspace, [], []);
      await options.dependencies.fileSystem.preparePrivateTree(
        path.dirname(options.paths.sourceRoot),
        [path.basename(options.paths.sourceRoot)],
        [],
      );
      // The preceding preparation may have materialised previously absent ancestors.
      // Re-prove separation immediately before creating the health-isolation root.
      await assertProspectiveSeparation();
      await options.dependencies.fileSystem.preparePrivateTree(isolationRoot, [], []);
      const [canonicalIsolation, canonicalSource, canonicalWorkspace] = await Promise.all([
        options.dependencies.fileSystem.realpath(isolationRoot),
        options.dependencies.fileSystem.realpath(options.paths.sourceRoot),
        options.dependencies.fileSystem.realpath(options.paths.workspace),
      ]);
      assertCanonicalIsolationSeparated(
        canonicalIsolation,
        canonicalSource,
        canonicalWorkspace,
        options.platform,
      );
    },
    updater,
  };
}
