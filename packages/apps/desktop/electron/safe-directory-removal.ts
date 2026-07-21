import path from "node:path";

import type { BootstrapDependencies } from "./bootstrap";
import {
  SourceOperationLeaseRetentionError,
  isSourceOperationLeaseRetentionError,
  type SourceOperationLeaseProof,
} from "./source-operation";
import type { NodeSourcePromotionFileSystemOptions } from "./source-promotion";

const SAFE_REMOVAL_HELPER = "flinttrade-safe-rmtree.py";
const SAFE_REMOVAL_OK = '{"ok":true,"status":"removed"}';

export interface SafeDirectoryRemoverOptions {
  bootstrapResources: string;
  dependencies: Pick<BootstrapDependencies, "command" | "fileSystem">;
  operationLease: SourceOperationLeaseProof;
  platform: NodeJS.Platform;
  pythonExecutable: string;
  timeoutMs?: number;
}

function isWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

export function createSafeDirectoryRemover(
  options: SafeDirectoryRemoverOptions,
): NonNullable<NodeSourcePromotionFileSystemOptions["safeRemove"]> {
  if (!path.isAbsolute(options.bootstrapResources) || !path.isAbsolute(options.pythonExecutable)) {
    throw new Error("Safe directory removal requires absolute resource and Python paths.");
  }
  const timeoutMs = options.timeoutMs ?? 10 * 60_000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new Error("Safe directory removal timeout must be a positive safe integer.");
  }
  const helper = path.join(path.resolve(options.bootstrapResources), SAFE_REMOVAL_HELPER);

  return async ({ expected, quarantine, target }): Promise<void> => {
    if (options.platform === "win32") {
      throw new Error("Identity-bound recursive directory deletion is unavailable on Windows.");
    }
    if (
      !path.isAbsolute(target) ||
      !path.isAbsolute(quarantine) ||
      path.dirname(target) !== path.dirname(quarantine) ||
      path.basename(target) === path.basename(quarantine)
    ) {
      throw new Error("Safe directory removal requires distinct absolute same-parent names.");
    }
    if (
      !Number.isSafeInteger(expected.dev) ||
      expected.dev < 0 ||
      !Number.isSafeInteger(expected.ino) ||
      expected.ino < 0
    ) {
      throw new Error("Safe directory removal requires a valid captured directory identity.");
    }

    await options.operationLease.assertHeld();
    if (!(await options.dependencies.fileSystem.existsNoFollow(helper))) {
      throw new Error("Packaged safe directory removal helper is missing.");
    }
    const [canonicalResources, canonicalHelper, canonicalParent] = await Promise.all([
      options.dependencies.fileSystem.realpath(options.bootstrapResources),
      options.dependencies.fileSystem.realpath(helper),
      options.dependencies.fileSystem.realpath(path.dirname(target)),
    ]);
    if (!isWithin(canonicalResources, canonicalHelper) || path.dirname(canonicalHelper) !== canonicalResources) {
      throw new Error("Packaged safe directory removal helper escaped its resource root.");
    }
    if (!path.isAbsolute(canonicalParent)) {
      throw new Error("Safe directory removal parent did not canonicalise to an absolute path.");
    }

    let result: Awaited<ReturnType<BootstrapDependencies["command"]["run"]>>;
    try {
      result = await options.dependencies.command.run({
        args: [
          canonicalHelper,
          "--parent",
          canonicalParent,
          "--target",
          path.basename(target),
          "--quarantine",
          path.basename(quarantine),
          "--expected-dev",
          String(expected.dev),
          "--expected-ino",
          String(expected.ino),
        ],
        command: options.pythonExecutable,
        env: { PYTHONNOUSERSITE: "1" },
        inheritEnvironment: false,
        timeoutMs,
      });
    } catch (error) {
      if (isSourceOperationLeaseRetentionError(error)) throw error;
      throw new SourceOperationLeaseRetentionError(
        "Safe directory removal command rejected without proving process containment.",
        { cause: error },
      );
    }
    if (!result.contained) {
      throw new SourceOperationLeaseRetentionError(
        "Safe directory removal process containment could not be proven.",
      );
    }
    if (result.stdoutTruncated || result.stderrTruncated) {
      throw new Error("Safe directory removal returned truncated output.");
    }
    if (result.exitCode !== 0 || result.stderr !== "" || result.stdout.trim() !== SAFE_REMOVAL_OK) {
      throw new Error(`Safe directory removal failed with exit code ${result.exitCode}.`);
    }
    try {
      await options.operationLease.assertHeld();
    } catch (error) {
      throw new SourceOperationLeaseRetentionError(
        "The source-operation lease could not be re-proven after safe directory removal.",
        { cause: error },
      );
    }
  };
}
