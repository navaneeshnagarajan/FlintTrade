import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { redactBootstrapText, type BootstrapDependencies, type FileSystemIdentity } from "./bootstrap";
import {
  CandidateHealthLeaseRetentionError,
  assertCandidateRepositoryEnvironmentAbsent,
  candidatePythonPath,
  createCandidateHealthEnvironment,
  proveCandidateHealth,
  type CandidateHealthOptions,
  type CandidateHealthPingBoundary,
  type CandidateHealthProof,
} from "./candidate-health";
import {
  SourceOperationLeaseRetentionError,
  isSourceOperationLeaseRetentionError,
  type SourceOperationKind,
  type SourceOperationLeaseProof,
} from "./source-operation";
import {
  ACTIVE_SOURCE_NAME,
  CANDIDATE_SOURCE_PREFIX,
  CLEANUP_QUARANTINE_PREFIX,
  LAST_KNOWN_GOOD_NAME,
  STALE_SOURCE_QUARANTINE_PREFIX,
  createNodeSourcePromotionFileSystem,
  type DirectoryCleanupOutcome,
  type SourcePromotionFileSystem,
} from "./source-promotion";
import {
  resolveExactSourceRevision,
  validateActiveSourceProvenance,
  type ActiveSourceIdentity,
  type ExactSourceRevision,
  type ExpectedSourceProvenance,
  type SourceProvenanceRequest,
  type SourceRevisionRepository,
  type SourceRevisionRequest,
} from "./source-provenance";
import type {
  SourceUpdateEvent,
  SourceUpdaterCleanupBoundary,
  SourceUpdaterCleanupKind,
  SourceUpdaterOwnedCleanupPaths,
  SourceUpdaterEventRecorder,
  SourceUpdaterHealthBoundary,
  SourceUpdaterOperationLease,
  SourceUpdaterProvenanceBoundary,
  SourceUpdaterRevisionBoundary,
} from "./source-updater";
import { WINDOWS_NATIVE_IDENTITY_PATTERN } from "./windows-source-filesystem";

const OPERATION_LEASE_NAME = ".flinttrade-bootstrap-operation.lock";
const UPDATE_LOG_NAME = "desktop-source-update.jsonl";
export const SOURCE_CLEANUP_INVENTORY_NAME = ".flinttrade-source-cleanup.json";
const MAX_SOURCE_CLEANUP_ENTRIES = 64;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const UUID_V4_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const UPDATE_CANDIDATE_PATTERN = /^FlintTrade\.update-([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i;
const UPDATE_ISOLATION_PATTERN = /^source-update-([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i;

const SOURCE_OPERATION_KINDS = new Set<SourceOperationKind>([
  "bootstrap",
  "startup-recovery",
  "update-apply",
  "update-check",
]);
const EVENT_OPERATIONS = new Set<SourceOperationKind>([
  "startup-recovery",
  "update-apply",
  "update-check",
]);
const EVENT_PHASES = new Set<SourceUpdateEvent["phase"]>([
  "apply-started",
  "check-started",
  "failed",
  "promoted",
  "recovery-complete",
  "recovery-started",
  "rolled-back",
  "update-available",
  "update-unavailable",
]);

export const FLINTTRADE_SOURCE_REPOSITORY: Readonly<SourceRevisionRepository> = Object.freeze({
  archiveAllowedHosts: Object.freeze(["codeload.github.com"]),
  archiveBaseUrl: "https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip",
  branch: "main",
  commitMetadataUrl: "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/commits/main",
  gitOrigin: "https://github.com/navaneeshnagarajan/FlintTrade.git",
  metadataAllowedHosts: Object.freeze(["api.github.com"]),
});

type LeaseState =
  | "acquiring"
  | "containment-unproved"
  | "held"
  | "idle"
  | "ownership-lost"
  | "process-exit-required"
  | "release-failed"
  | "releasing";

interface RuntimeLeaseOwnership {
  bootIdentity: string;
  dev: number;
  ino: number;
  operationId: string;
  ownerPid: number;
}

interface RetainedLeaseRelease {
  generation: number;
  release(): Promise<void>;
  settlement: Promise<void> | null;
  settled: boolean;
}

export interface RuntimeSourceUpdaterOperationLease extends SourceUpdaterOperationLease, SourceOperationLeaseProof {
  getSnapshot(): Readonly<{ kind: SourceOperationKind | null; state: LeaseState }>;
  settleForQuit(): Promise<void>;
}

export interface RuntimeSourceUpdaterOperationLeaseOptions {
  bootIdentity: string;
  dependencies: Pick<BootstrapDependencies, "command" | "fileSystem">;
  ownerPid?: number;
  singletonAuthorised: boolean;
  sourceRoot: string;
}

export interface DurableSourceUpdaterEventRecorderOptions {
  dependencies: Pick<BootstrapDependencies, "fileSystem">;
  isolationRoot: string;
  logs: string;
  platform?: NodeJS.Platform;
  sourceRoot: string;
  workspace: string;
}

export interface NodeSourceUpdaterCleanupOptions {
  fileSystem?: SourcePromotionFileSystem;
  isolationRoot: string;
  platform?: NodeJS.Platform;
  safeRemovalSupported?: boolean;
  sourceRoot: string;
  workspace: string;
}

type CandidateHealthImplementation = (options: CandidateHealthOptions) => Promise<CandidateHealthProof>;

export interface NodeSourceUpdaterHealthOptions {
  dependencies: Pick<BootstrapDependencies, "command" | "fileSystem">;
  isolationRoot: string;
  ping?: CandidateHealthPingBoundary;
  pingIntervalMs?: number;
  prove?: CandidateHealthImplementation;
  sourceRoot: string;
  timeoutMs?: number;
  workspace: string;
}

export interface NodeSourcePromotionHealthLifecycleOptions extends NodeSourceUpdaterHealthOptions {
  cleanup: SourceUpdaterCleanupBoundary;
  operationLease: SourceOperationLeaseProof;
  uuid?: () => string;
}

export interface SourcePromotionBootLifecycle {
  bootActive(input: { activePath: string; onBackendStopped(): void }): Promise<boolean>;
}

type ProvenanceImplementation = (request: SourceProvenanceRequest) => Promise<ActiveSourceIdentity>;

export interface SourceUpdaterProvenanceOptions {
  bootstrapResources: string;
  dependencies: Pick<BootstrapDependencies, "command" | "fileSystem">;
  expected: ExpectedSourceProvenance;
  platform: NodeJS.Platform;
  sourceRoot: string;
  validate?: ProvenanceImplementation;
}

type RevisionImplementation = (request: SourceRevisionRequest) => Promise<ExactSourceRevision>;

export interface SourceUpdaterRevisionResolverOptions {
  dependencies: Pick<BootstrapDependencies, "command" | "download">;
  platform: NodeJS.Platform;
  resolve?: RevisionImplementation;
}

function cancellation(message: string): DOMException {
  return new DOMException(message, "AbortError");
}

function samePath(left: string, right: string, platform: NodeJS.Platform = process.platform): boolean {
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function replacePrivatePath(
  value: string,
  privatePath: string,
  replacement: string,
  platform: NodeJS.Platform,
): string {
  const variants = [...new Set([
    privatePath,
    privatePath.replaceAll("\\", "/"),
    privatePath.replaceAll("/", "\\"),
  ])].sort((left, right) => right.length - left.length);
  return variants.reduce((current, variant) => {
    if (!variant) return current;
    if (platform !== "win32") return current.split(variant).join(replacement);
    const needle = variant.toLowerCase();
    const lowered = current.toLowerCase();
    let cursor = 0;
    let result = "";
    for (;;) {
      const index = lowered.indexOf(needle, cursor);
      if (index < 0) return result + current.slice(cursor);
      result += current.slice(cursor, index) + replacement;
      cursor = index + variant.length;
    }
  }, value);
}

function isWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function requireAbsoluteRoot(target: string, label: string): string {
  if (!path.isAbsolute(target)) throw new Error(`${label} must be an absolute path.`);
  return path.resolve(target);
}

function assertSeparated(left: string, right: string, label: string): void {
  if (isWithin(left, right) || isWithin(right, left)) throw new Error(`${label} must not overlap.`);
}

function assertManagedSourceWorkspaceRelationship(
  sourceRoot: string,
  workspace: string,
  platform: NodeJS.Platform = process.platform,
): void {
  if (!isWithin(sourceRoot, workspace) && !isWithin(workspace, sourceRoot)) return;
  if (samePath(sourceRoot, path.join(workspace, "src"), platform)) return;
  throw new Error("Managed source and workspace may overlap only at the platform workspace's exact src child.");
}

function exactCandidateName(operationId: string): string {
  if (!UUID_V4_PATTERN.test(operationId)) throw new Error("Source update operation identity must be a UUID v4.");
  return `${CANDIDATE_SOURCE_PREFIX}${operationId}`;
}

async function readRuntimeLeaseOwnership(
  fileSystem: BootstrapDependencies["fileSystem"],
  target: string,
  bootIdentity: string,
  ownerPid: number,
): Promise<RuntimeLeaseOwnership> {
  const identity = await fileSystem.directoryIdentity(target);
  let owner: unknown;
  try {
    owner = JSON.parse(await fileSystem.readTextNoFollow(path.join(target, "owner.json"))) as unknown;
  } catch (error) {
    throw new Error("Source updater operation lease owner proof is unreadable.", { cause: error });
  }
  if (
    typeof owner !== "object" ||
    owner === null ||
    !("bootIdentity" in owner) ||
    owner.bootIdentity !== bootIdentity ||
    !("ownerPid" in owner) ||
    owner.ownerPid !== ownerPid ||
    !("operationId" in owner) ||
    typeof owner.operationId !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(owner.operationId)
  ) {
    throw new Error("Source updater operation lease owner proof does not match this runtime.");
  }
  const finalIdentity = await fileSystem.directoryIdentity(target);
  if (identity.dev !== finalIdentity.dev || identity.ino !== finalIdentity.ino) {
    throw new Error("Source updater operation lease identity changed during ownership proof.");
  }
  return { bootIdentity, dev: identity.dev, ino: identity.ino, operationId: owner.operationId, ownerPid };
}

export function createRuntimeSourceUpdaterOperationLease(
  options: RuntimeSourceUpdaterOperationLeaseOptions,
): RuntimeSourceUpdaterOperationLease {
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const target = path.join(sourceRoot, OPERATION_LEASE_NAME);
  if (options.dependencies.command.operationLeaseTarget !== target) {
    throw new Error("Source updater command containment must use the exact shared operation lease target.");
  }
  if (!options.singletonAuthorised) {
    throw new Error("Source updater operation lease requires explicit application-singleton authority.");
  }
  if (!options.bootIdentity.trim()) throw new Error("Source updater operation lease requires a boot identity.");
  const ownerPid = options.ownerPid ?? process.pid;
  if (!Number.isSafeInteger(ownerPid) || ownerPid <= 0) {
    throw new Error("Source updater operation lease requires a positive owner PID.");
  }

  let state: LeaseState = "idle";
  let kind: SourceOperationKind | null = null;
  let generation = 0;
  let ownership: RuntimeLeaseOwnership | null = null;
  let retainedRelease: RetainedLeaseRelease | null = null;
  let containmentSettlement: Promise<void> | null = null;

  const settleRetainedRelease = (retained: RetainedLeaseRelease): Promise<void> => {
    if (retainedRelease !== retained || generation !== retained.generation) {
      return Promise.reject(new Error("Source updater operation lease retained release capability is stale."));
    }
    if (retained.settled) return Promise.resolve();
    if (retained.settlement) return retained.settlement;
    state = "releasing";
    let settlement: Promise<void>;
    settlement = (async () => {
      try {
        await retained.release();
      } catch (error) {
        state = "release-failed";
        throw error;
      }
      retained.settled = true;
      retainedRelease = null;
      state = "idle";
      kind = null;
      ownership = null;
    })().finally(() => {
      if (retained.settlement === settlement) retained.settlement = null;
    });
    retained.settlement = settlement;
    return settlement;
  };

  const assertHeld = async (): Promise<void> => {
    if (
      state === "containment-unproved" ||
      state === "process-exit-required" ||
      state === "release-failed" ||
      state === "ownership-lost"
    ) {
      throw new SourceOperationLeaseRetentionError(
        "Source updater operation lease cannot prove ownership in its current state.",
        {
          retentionPolicy: state === "process-exit-required"
            ? "process-exit-required"
            : "command-containment",
        },
      );
    }
    if (state !== "held" || !ownership) {
      throw new Error("Source updater operation lease is not held by this runtime capability.");
    }
    try {
      const current = await readRuntimeLeaseOwnership(
        options.dependencies.fileSystem,
        target,
        options.bootIdentity,
        ownerPid,
      );
      if (
        current.dev !== ownership.dev ||
        current.ino !== ownership.ino ||
        current.operationId !== ownership.operationId
      ) {
        throw new Error("Source updater operation lease ownership changed after acquisition.");
      }
    } catch (error) {
      state = "ownership-lost";
      throw new SourceOperationLeaseRetentionError(
        "Source updater operation lease cannot prove current runtime ownership.",
        { cause: error },
      );
    }
  };

  return {
    async acquire(input) {
      if (!SOURCE_OPERATION_KINDS.has(input.kind)) throw new Error("Source updater operation kind is invalid.");
      if (state === "release-failed" && retainedRelease) {
        await settleRetainedRelease(retainedRelease);
      }
      if (state !== "idle") throw new Error("Source updater operation lease is already active in this runtime.");
      if (input.signal.aborted) throw cancellation("Source operation was cancelled before lease acquisition.");
      state = "acquiring";
      kind = input.kind;
      const acquiredGeneration = ++generation;
      let underlyingRelease: (() => Promise<void>) | null = null;
      try {
        underlyingRelease = await options.dependencies.fileSystem.acquireOperationLock({
          bootIdentity: options.bootIdentity,
          ownerPid,
          singletonAuthorised: options.singletonAuthorised,
          target,
        });
      } catch (error) {
        if (generation === acquiredGeneration) {
          state = "idle";
          kind = null;
          ownership = null;
        }
        throw error;
      }

      if (input.signal.aborted) {
        const retained = {
          generation: acquiredGeneration,
          release: underlyingRelease,
          settlement: null,
          settled: false,
        } satisfies RetainedLeaseRelease;
        retainedRelease = retained;
        try {
          await settleRetainedRelease(retained);
        } catch (error) {
          throw new AggregateError(
            [cancellation("Source operation was cancelled during lease acquisition."), error],
            "Cancelled source operation lease could not be durably released.",
          );
        }
        throw cancellation("Source operation was cancelled during lease acquisition.");
      }

      try {
        ownership = await readRuntimeLeaseOwnership(
          options.dependencies.fileSystem,
          target,
          options.bootIdentity,
          ownerPid,
        );
      } catch (proofFailure) {
        const retained = {
          generation: acquiredGeneration,
          release: underlyingRelease,
          settlement: null,
          settled: false,
        } satisfies RetainedLeaseRelease;
        retainedRelease = retained;
        try {
          await settleRetainedRelease(retained);
        } catch (releaseFailure) {
          throw new AggregateError(
            [proofFailure, releaseFailure],
            "Source operation lease ownership proof and durable release both failed.",
          );
        }
        throw proofFailure;
      }

      state = "held";
      const retained = {
        generation: acquiredGeneration,
        release: underlyingRelease,
        settlement: null,
        settled: false,
      } satisfies RetainedLeaseRelease;
      retainedRelease = retained;
      const release = (): Promise<void> => {
        if (retained.settled) return Promise.resolve();
        if (
          generation !== acquiredGeneration ||
          (state !== "held" && state !== "ownership-lost" && state !== "release-failed")
        ) {
          return Promise.reject(new Error("Source updater operation lease release capability is stale."));
        }
        return settleRetainedRelease(retained);
      };
      return release;
    },
    assertHeld,
    getSnapshot: () => Object.freeze({ kind, state }),
    retainForContainment(policy): boolean {
      const canUpgradeUnprovedOwnership =
        policy === "process-exit-required" &&
        (state === "ownership-lost" || state === "containment-unproved");
      const canRetainHeldOwnership = state === "held" && ownership !== null;
      if (
        (!canRetainHeldOwnership && !canUpgradeUnprovedOwnership) ||
        !retainedRelease ||
        retainedRelease.settled ||
        retainedRelease.generation !== generation
      ) {
        return false;
      }
      state = policy === "process-exit-required" ? "process-exit-required" : "containment-unproved";
      return true;
    },
    settleForQuit(): Promise<void> {
      if (containmentSettlement) return containmentSettlement;
      if (state === "process-exit-required") {
        // The long-lived backend is intentionally left parent-bound. Keep the
        // durable lease and release capability unreachable until this process
        // dies; the next boot may then reclaim the stale owner and journal.
        return Promise.resolve();
      }
      if (state === "containment-unproved" && retainedRelease) {
        const retained = retainedRelease;
        let settlement: Promise<void>;
        settlement = (async () => {
          await options.dependencies.command.reconcileOperationContainment();
          if (
            state !== "containment-unproved" ||
            retainedRelease !== retained ||
            generation !== retained.generation
          ) {
            throw new Error("Source updater containment-retained lease capability changed during reconciliation.");
          }
          await settleRetainedRelease(retained);
        })().finally(() => {
          if (containmentSettlement === settlement) containmentSettlement = null;
        });
        containmentSettlement = settlement;
        return settlement;
      }
      if (state === "release-failed" && retainedRelease) {
        return settleRetainedRelease(retainedRelease);
      }
      if (state === "releasing" && retainedRelease?.settlement) return retainedRelease.settlement;
      return Promise.resolve();
    },
    target,
  };
}

function validateEvent(event: Readonly<SourceUpdateEvent>): void {
  if (!Number.isSafeInteger(event.attempt) || event.attempt <= 0) {
    throw new Error("Source update event attempt must be a positive safe integer.");
  }
  if (!EVENT_OPERATIONS.has(event.operation) || !EVENT_PHASES.has(event.phase)) {
    throw new Error("Source update event has an invalid operation or phase.");
  }
  if (event.revision !== null && !COMMIT_PATTERN.test(event.revision)) {
    throw new Error("Source update event revision must be an exact lowercase Git revision.");
  }
  if (event.promotionId !== null && !UUID_V4_PATTERN.test(event.promotionId)) {
    throw new Error("Source update event promotion identity must be a UUID v4.");
  }
  const terminalPromotion = event.phase === "promoted" || event.phase === "rolled-back";
  if (terminalPromotion !== (event.promotionId !== null)) {
    throw new Error("Only terminal promotion events may carry the required promotion identity.");
  }
  if (typeof event.message !== "string" || !event.message.trim()) {
    throw new Error("Source update event message must not be empty.");
  }
}

export function createDurableSourceUpdaterEventRecorder(
  options: DurableSourceUpdaterEventRecorderOptions,
): SourceUpdaterEventRecorder {
  const platform = options.platform ?? process.platform;
  const workspace = requireAbsoluteRoot(options.workspace, "The workspace");
  const logs = requireAbsoluteRoot(options.logs, "The source update log directory");
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const isolationRoot = requireAbsoluteRoot(options.isolationRoot, "The health isolation root");
  if (!isWithin(workspace, logs) || samePath(workspace, logs)) {
    throw new Error("Source update events must use a private log directory within the workspace.");
  }
  assertSeparated(logs, sourceRoot, "Source update logs and managed source");
  assertSeparated(logs, isolationRoot, "Source update logs and health isolation");
  const target = path.join(logs, UPDATE_LOG_NAME);
  let queue = Promise.resolve();

  return {
    record(event) {
      validateEvent(event);
      const replacePrivatePaths = (value: string): string => {
        const withoutSource = replacePrivatePath(value, sourceRoot, "<source-root>", platform);
        const withoutIsolation = replacePrivatePath(
          withoutSource,
          isolationRoot,
          "<health-isolation>",
          platform,
        );
        return replacePrivatePath(withoutIsolation, workspace, "<workspace>", platform);
      };
      const safeEvent: SourceUpdateEvent = {
        attempt: event.attempt,
        message: replacePrivatePaths(redactBootstrapText(event.message)),
        operation: event.operation,
        phase: event.phase,
        promotionId: event.promotionId,
        revision: event.revision,
      };
      const append = queue.then(async () => {
        await options.dependencies.fileSystem.ensureDurableDirectory(logs, workspace);
        // A leading separator keeps the next record parseable even if an older
        // append failed after a partial write. JSONL readers ignore blank lines.
        await options.dependencies.fileSystem.appendText(target, `\n${JSON.stringify(safeEvent)}\n`);
      });
      queue = append.catch(() => undefined);
      return append;
    },
  };
}

export function createNodeSourceUpdaterCleanup(
  options: NodeSourceUpdaterCleanupOptions,
): SourceUpdaterCleanupBoundary {
  const platform = options.platform ?? process.platform;
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const isolationRoot = requireAbsoluteRoot(options.isolationRoot, "The health isolation root");
  const workspace = requireAbsoluteRoot(options.workspace, "The workspace");
  assertSeparated(sourceRoot, isolationRoot, "Managed source and health isolation roots");
  assertManagedSourceWorkspaceRelationship(sourceRoot, workspace, platform);
  assertSeparated(isolationRoot, workspace, "Health isolation and workspace roots");
  const fileSystem = options.fileSystem ?? createNodeSourcePromotionFileSystem({ platform });
  const safeRemovalSupported = options.safeRemovalSupported ?? (
    platform !== "win32" || fileSystem.supportsDurableWindowsMutations === true
  );
  const inventoryPath = path.join(sourceRoot, SOURCE_CLEANUP_INVENTORY_NAME);

  type ReservedCleanupEntry = Readonly<{
    inventoryVersion: 2;
    kind: SourceUpdaterCleanupKind;
    operationId: string;
    state: "reserved";
  }>;
  type OwnedCleanupEntry = Readonly<{
    dev: number;
    ino: number;
    nativeIdentity?: string;
    inventoryVersion: 1 | 2;
    kind: SourceUpdaterCleanupKind;
    operationId: string;
    state: "owned" | "preserved";
  }>;
  type CleanupEntry = ReservedCleanupEntry | OwnedCleanupEntry;
  type CleanupLocation = Readonly<{
    expectedName: string;
    label: string;
    quarantineName: string;
    root: string;
    target: string;
  }>;

  const cleanupKinds = new Set<SourceUpdaterCleanupKind>([
    "candidate",
    "isolation",
    "staging-candidate",
    "staging-unpack",
  ]);

  const assertReady = (): void => {
    if (!safeRemovalSupported) {
      throw new Error(
        "Source update apply is unavailable on Windows until identity-bound native directory cleanup is installed.",
      );
    }
  };

  const requireIdentity = (
    identity: Readonly<{ dev: number; ino: number }>,
    label: string,
  ): Readonly<{ dev: number; ino: number }> => {
    if (
      !identity ||
      !Number.isSafeInteger(identity.dev) ||
      identity.dev < 0 ||
      !Number.isSafeInteger(identity.ino) ||
      identity.ino < 0
    ) {
      throw new Error(`Refusing cleanup without a captured ${label} directory identity.`);
    }
    return { dev: identity.dev, ino: identity.ino };
  };

  const requireOperationId = (value: string): string => {
    if (
      typeof value !== "string" ||
      value !== value.toLowerCase() ||
      !UUID_V4_PATTERN.test(value)
    ) {
      throw new Error("Source cleanup operation ID must be a canonical lowercase UUID v4.");
    }
    return value;
  };

  const requireKinds = (values: readonly SourceUpdaterCleanupKind[]): SourceUpdaterCleanupKind[] => {
    if (!Array.isArray(values)) throw new Error("Source cleanup kinds must be an array.");
    const kinds = values.map((kind) => {
      if (!cleanupKinds.has(kind)) throw new Error("Source cleanup reservation has an invalid path kind.");
      return kind;
    });
    if (new Set(kinds).size !== kinds.length) {
      throw new Error("Source cleanup reservation contains duplicate path kinds.");
    }
    return kinds;
  };

  const cleanupLocation = (
    kind: SourceUpdaterCleanupKind,
    operationId: string,
    inventoryVersion: 1 | 2 = 2,
  ): CleanupLocation => {
    const legacyQuarantineName = `${STALE_SOURCE_QUARANTINE_PREFIX}${operationId}`;
    if (kind === "candidate") {
      const expectedName = exactCandidateName(operationId);
      return {
        expectedName,
        label: "candidate",
        quarantineName: inventoryVersion === 1
          ? legacyQuarantineName
          : `${CLEANUP_QUARANTINE_PREFIX}candidate-${operationId}`,
        root: sourceRoot,
        target: path.join(sourceRoot, expectedName),
      };
    }
    if (kind === "isolation") {
      const expectedName = `source-update-${operationId}`;
      return {
        expectedName,
        label: "isolation",
        quarantineName: inventoryVersion === 1
          ? legacyQuarantineName
          : `${CLEANUP_QUARANTINE_PREFIX}isolation-${operationId}`,
        root: isolationRoot,
        target: path.join(isolationRoot, expectedName),
      };
    }
    const expectedName = `${exactCandidateName(operationId)}.candidate-1${kind === "staging-unpack" ? ".unpack" : ""}`;
    const quarantineKind = kind === "staging-unpack" ? "staging-unpack-1" : "staging-candidate-1";
    return {
      expectedName,
      label: "bootstrap staging",
      quarantineName: `${CLEANUP_QUARANTINE_PREFIX}${quarantineKind}-${operationId}`,
      root: sourceRoot,
      target: path.join(sourceRoot, expectedName),
    };
  };

  const candidateEntry = (input: {
    candidatePath: string;
    identity: FileSystemIdentity;
    operationId: string;
  }): OwnedCleanupEntry => {
    const operationId = requireOperationId(input.operationId);
    const expectedName = exactCandidateName(operationId);
    const expectedPath = path.join(sourceRoot, expectedName);
    if (!path.isAbsolute(input.candidatePath) || !samePath(path.resolve(input.candidatePath), expectedPath, platform)) {
      throw new Error("Refusing cleanup outside the exact owned candidate path.");
    }
    return {
      ...requireIdentity(input.identity, "candidate"),
      inventoryVersion: 2,
      kind: "candidate",
      operationId,
      state: "owned",
    };
  };

  const isolationEntry = (input: {
    identity: FileSystemIdentity;
    isolationPath: string;
  }): OwnedCleanupEntry => {
    const resolved = path.resolve(input.isolationPath);
    const match = UPDATE_ISOLATION_PATTERN.exec(path.basename(resolved));
    if (!path.isAbsolute(input.isolationPath) || !match || !samePath(path.dirname(resolved), isolationRoot, platform)) {
      throw new Error("Refusing cleanup outside the exact owned isolation path.");
    }
    const operationId = requireOperationId(match[1]!);
    if (!samePath(resolved, path.join(isolationRoot, `source-update-${operationId}`), platform)) {
      throw new Error("Refusing cleanup outside the canonical owned isolation path.");
    }
    return {
      ...requireIdentity(input.identity, "isolation"),
      inventoryVersion: 2,
      kind: "isolation",
      operationId,
      state: "owned",
    };
  };

  const stagingEntry = (input: NonNullable<SourceUpdaterOwnedCleanupPaths["staging"]>[number]): OwnedCleanupEntry => {
    if (input.kind !== "staging-candidate" && input.kind !== "staging-unpack") {
      throw new Error("Refusing cleanup with an invalid bootstrap staging kind.");
    }
    const operationId = requireOperationId(input.operationId);
    const baseName = `${exactCandidateName(operationId)}.candidate-1`;
    const expectedName = input.kind === "staging-unpack" ? `${baseName}.unpack` : baseName;
    const expectedPath = path.join(sourceRoot, expectedName);
    if (!path.isAbsolute(input.stagingPath) || !samePath(path.resolve(input.stagingPath), expectedPath, platform)) {
      throw new Error("Refusing cleanup outside the exact owned bootstrap staging path.");
    }
    return {
      ...requireIdentity(input.identity, "bootstrap staging"),
      inventoryVersion: 2,
      kind: input.kind,
      operationId,
      state: "owned",
    };
  };

  const parseInventory = (contents: string): CleanupEntry[] => {
    let value: unknown;
    try {
      value = JSON.parse(contents);
    } catch (error) {
      throw new Error("Source cleanup inventory is not valid JSON.", { cause: error });
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Source cleanup inventory must be an object.");
    }
    const record = value as Record<string, unknown>;
    if (
      (record.schemaVersion !== 1 && record.schemaVersion !== 2) ||
      !Array.isArray(record.entries) ||
      record.entries.length > MAX_SOURCE_CLEANUP_ENTRIES ||
      Object.keys(record).length !== 2 ||
      !Object.hasOwn(record, "entries") ||
      !Object.hasOwn(record, "schemaVersion")
    ) {
      throw new Error("Source cleanup inventory has an invalid schema.");
    }
    const entries = record.entries.map((entry): CleanupEntry => {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
        throw new Error("Source cleanup inventory entry must be an object.");
      }
      const candidate = entry as Record<string, unknown>;
      if (
        !cleanupKinds.has(candidate.kind as SourceUpdaterCleanupKind) ||
        typeof candidate.operationId !== "string" ||
        candidate.operationId !== candidate.operationId.toLowerCase() ||
        !UUID_V4_PATTERN.test(candidate.operationId)
      ) {
        throw new Error("Source cleanup inventory entry is invalid.");
      }
      const common = {
        kind: candidate.kind as SourceUpdaterCleanupKind,
        operationId: candidate.operationId,
      };
      if (
        record.schemaVersion === 1 &&
        candidate.kind !== "candidate" &&
        candidate.kind !== "isolation"
      ) {
        throw new Error("Source cleanup v1 inventory has an invalid path kind.");
      }
      if (record.schemaVersion === 2 && candidate.state === "reserved") {
        if (
          Object.keys(candidate).length !== 3 ||
          !Object.hasOwn(candidate, "kind") ||
          !Object.hasOwn(candidate, "operationId") ||
          !Object.hasOwn(candidate, "state")
        ) {
          throw new Error("Source cleanup inventory reservation is invalid.");
        }
        return { ...common, inventoryVersion: 2, state: "reserved" };
      }
      if (
        (record.schemaVersion === 2 && candidate.state !== "owned" && candidate.state !== "preserved") ||
        Object.keys(candidate).length !== (record.schemaVersion === 1 ? 4 : platform === "win32" ? 6 : 5) ||
        !Object.hasOwn(candidate, "dev") ||
        !Object.hasOwn(candidate, "ino") ||
        !Object.hasOwn(candidate, "kind") ||
        !Object.hasOwn(candidate, "operationId") ||
        (record.schemaVersion === 2 && !Object.hasOwn(candidate, "state")) ||
        !Number.isSafeInteger(candidate.dev) ||
        (candidate.dev as number) < 0 ||
        !Number.isSafeInteger(candidate.ino) ||
        (candidate.ino as number) < 0 ||
        (platform === "win32" &&
          (typeof candidate.nativeIdentity !== "string" ||
            !WINDOWS_NATIVE_IDENTITY_PATTERN.test(candidate.nativeIdentity))) ||
        (platform !== "win32" && Object.hasOwn(candidate, "nativeIdentity"))
      ) {
        throw new Error("Source cleanup inventory ownership entry is invalid.");
      }
      return {
        ...common,
        dev: candidate.dev as number,
        ino: candidate.ino as number,
        inventoryVersion: record.schemaVersion === 1 ? 1 : 2,
        ...(platform === "win32" ? { nativeIdentity: candidate.nativeIdentity as string } : {}),
        state: record.schemaVersion === 1 ? "owned" : candidate.state as "owned" | "preserved",
      };
    });
    if (
      new Set(entries.map((entry) => `${entry.kind}:${entry.operationId}`)).size !== entries.length ||
      new Set(
        entries
          .filter((entry): entry is OwnedCleanupEntry => entry.state !== "reserved")
          .map((entry) => entry.nativeIdentity ?? `${entry.dev}:${entry.ino}`),
      ).size !== entries.filter((entry) => entry.state !== "reserved").length
    ) {
      throw new Error("Source cleanup inventory contains duplicate ownership evidence.");
    }
    return entries;
  };

  const persistInventory = async (entries: readonly CleanupEntry[]): Promise<void> => {
    if (entries.length === 0) {
      await fileSystem.removeJournal(inventoryPath);
      return;
    }
    if (entries.some((entry) => entry.inventoryVersion !== 2)) {
      throw new Error("Source cleanup v1 inventory must be replayed before v2 inventory mutation.");
    }
    const serialisedEntries = entries.map((entry) => entry.state === "reserved"
      ? { kind: entry.kind, operationId: entry.operationId, state: entry.state }
      : {
          dev: entry.dev,
          ino: entry.ino,
          kind: entry.kind,
          ...(entry.nativeIdentity ? { nativeIdentity: entry.nativeIdentity } : {}),
          operationId: entry.operationId,
          state: entry.state,
        });
    await fileSystem.writeJournalAtomic(
      inventoryPath,
      `${JSON.stringify({ entries: serialisedEntries, schemaVersion: 2 })}\n`,
    );
  };

  const readInventory = async (): Promise<Readonly<{ entries: CleanupEntry[]; present: boolean }>> => {
    const contents = await fileSystem.readJournal(inventoryPath);
    return contents === null
      ? { entries: [], present: false }
      : { entries: parseInventory(contents), present: true };
  };

  const inspectEntry = async (entry: CleanupEntry): Promise<Readonly<{
    quarantine: Awaited<ReturnType<SourcePromotionFileSystem["inspectDirectory"]>>;
    target: Awaited<ReturnType<SourcePromotionFileSystem["inspectDirectory"]>>;
  }>> => {
    const location = cleanupLocation(entry.kind, entry.operationId, entry.inventoryVersion);
    const rootIdentity = await fileSystem.inspectDirectory(location.root);
    if (!rootIdentity) throw new Error(`The managed ${location.label} root is missing.`);
    const quarantinePath = path.join(location.root, location.quarantineName);
    const [target, quarantine] = await Promise.all([
      fileSystem.inspectDirectory(location.target),
      fileSystem.inspectDirectory(quarantinePath),
    ]);
    if (target && quarantine) {
      throw new Error(`Source cleanup evidence is ambiguous for ${entry.kind}:${entry.operationId}.`);
    }
    if (
      target &&
      !samePath(target.canonicalPath, path.join(rootIdentity.canonicalPath, location.expectedName), platform)
    ) {
      throw new Error(`The owned ${location.label} path has a foreign canonical identity.`);
    }
    if (
      quarantine &&
      !samePath(quarantine.canonicalPath, path.join(rootIdentity.canonicalPath, location.quarantineName), platform)
    ) {
      throw new Error(`The owned ${location.label} quarantine has a foreign canonical identity.`);
    }
    if (entry.state === "reserved" && quarantine) {
      throw new Error("A reserved source cleanup path has unexpected quarantine evidence.");
    }
    if (entry.state === "preserved" && target) {
      throw new Error("A preserved source cleanup entry unexpectedly reappeared at its managed target.");
    }
    const observed = target ?? quarantine;
    if (
      entry.state !== "reserved" &&
      observed &&
      (observed.dev !== entry.dev ||
        observed.ino !== entry.ino ||
        (platform === "win32" && observed.nativeIdentity !== entry.nativeIdentity))
    ) {
      throw new Error(`The owned ${location.label} path no longer has its captured directory identity.`);
    }
    return { quarantine, target };
  };

  const validateEntries = async (entries: readonly CleanupEntry[]): Promise<void> => {
    const observedIdentities = new Set<string>();
    for (const entry of entries) {
      const observed = await inspectEntry(entry);
      const present = observed.target ?? observed.quarantine;
      if (!present) continue;
      const identity = present.nativeIdentity ?? `${present.dev}:${present.ino}`;
      if (observedIdentities.has(identity)) {
        throw new Error("Source cleanup inventory aliases one observed directory identity across entries.");
      }
      observedIdentities.add(identity);
    }
  };

  const removeExact = async (
    target: string,
    root: string,
    expectedName: string,
    label: string,
    expectedIdentity: Readonly<{ dev: number; ino: number; nativeIdentity?: string }>,
  ): Promise<DirectoryCleanupOutcome> => {
    requireIdentity(expectedIdentity, label);
    const resolved = path.resolve(target);
    const expected = path.join(root, expectedName);
    if (!path.isAbsolute(target) || !samePath(resolved, expected, platform)) {
      throw new Error(`Refusing cleanup outside the exact owned ${label} path.`);
    }
    const rootIdentity = await fileSystem.inspectDirectory(root);
    if (!rootIdentity) throw new Error(`The managed ${label} root is missing.`);
    const identity = await fileSystem.inspectDirectory(resolved);
    if (
      identity &&
      (identity.dev !== expectedIdentity.dev ||
        identity.ino !== expectedIdentity.ino ||
        (platform === "win32" && identity.nativeIdentity !== expectedIdentity.nativeIdentity))
    ) {
      throw new Error(`The owned ${label} path no longer has its captured directory identity.`);
    }
    const expectedCanonical = path.join(rootIdentity.canonicalPath, expectedName);
    if (identity && !samePath(identity.canonicalPath, expectedCanonical, platform)) {
      throw new Error(`The owned ${label} path has a foreign canonical identity.`);
    }
    return fileSystem.removeDirectory(resolved, {
      canonicalPath: expectedCanonical,
      dev: expectedIdentity.dev,
      ino: expectedIdentity.ino,
      ...(expectedIdentity.nativeIdentity ? { nativeIdentity: expectedIdentity.nativeIdentity } : {}),
    });
  };

  const removeEntry = async (entry: OwnedCleanupEntry): Promise<DirectoryCleanupOutcome> => {
    const location = cleanupLocation(entry.kind, entry.operationId, entry.inventoryVersion);
    if (entry.inventoryVersion === 1) {
      const observed = await inspectEntry(entry);
      if (!observed.target && !observed.quarantine) return { status: "removed" };
      const rootIdentity = await fileSystem.inspectDirectory(location.root);
      if (!rootIdentity) throw new Error(`The managed ${location.label} root is missing.`);
      return fileSystem.settleDirectory(
        location.target,
        path.join(location.root, location.quarantineName),
        {
          canonicalPath: path.join(rootIdentity.canonicalPath, location.expectedName),
          dev: entry.dev,
          ino: entry.ino,
          ...(entry.nativeIdentity ? { nativeIdentity: entry.nativeIdentity } : {}),
        },
      );
    }
    return removeExact(
      location.target,
      location.root,
      location.expectedName,
      location.label,
      entry,
    );
  };

  const settleEntries = async (
    selected: ReadonlySet<string> | null,
  ): Promise<void> => {
    const inventory = await readInventory();
    let remaining = inventory.entries;
    await validateEntries(remaining);
    if (remaining.some((entry) => entry.state === "preserved")) {
      const retained: CleanupEntry[] = [];
      for (const entry of remaining) {
        if (entry.state !== "preserved") {
          retained.push(entry);
          continue;
        }
        const observed = await inspectEntry(entry);
        if (observed.quarantine) retained.push(entry);
      }
      if (retained.length !== remaining.length) {
        remaining = retained;
        await persistInventory(remaining);
      }
    }
    if (remaining.length === 0) {
      if (inventory.present) await persistInventory([]);
      return;
    }
    if (remaining.some((entry) => entry.inventoryVersion === 1)) {
      if (selected !== null) {
        throw new Error("Source cleanup v1 inventory must be fully recovered before selected removal.");
      }
      let preserved = false;
      for (const entry of remaining) {
        if (entry.state !== "owned") throw new Error("Source cleanup v1 inventory cannot contain reservations.");
        const outcome = await removeEntry(entry);
        preserved ||= outcome.status === "quarantined";
      }
      if (!preserved) await persistInventory([]);
      return;
    }
    const pendingKeys = remaining
      .map((entry) => `${entry.kind}:${entry.operationId}`)
      .filter((key) => selected === null || selected.has(key));
    for (const key of pendingKeys) {
      const index = remaining.findIndex((entry) => `${entry.kind}:${entry.operationId}` === key);
      if (index < 0) continue;
      let entry = remaining[index]!;
      if (entry.state === "reserved") {
        const observed = await inspectEntry(entry);
        if (!observed.target) {
          remaining = remaining.filter((_, candidateIndex) => candidateIndex !== index);
          await persistInventory(remaining);
          continue;
        }
        entry = {
          dev: observed.target.dev,
          ino: observed.target.ino,
          inventoryVersion: 2,
          kind: entry.kind,
          ...(observed.target.nativeIdentity ? { nativeIdentity: observed.target.nativeIdentity } : {}),
          operationId: entry.operationId,
          state: "owned",
        };
        remaining = remaining.map((candidate, candidateIndex) => candidateIndex === index ? entry : candidate);
        await persistInventory(remaining);
      }
      const outcome = await removeEntry(entry);
      remaining = outcome.status === "quarantined"
        ? remaining.map((candidate, candidateIndex) => candidateIndex === index
          ? { ...entry, state: "preserved" as const }
          : candidate)
        : remaining.filter((_, candidateIndex) => candidateIndex !== index);
      await persistInventory(remaining);
    }
  };

  const replayInventory = async (): Promise<void> => {
    const inventory = await readInventory();
    if (inventory.entries.length === 0) {
      if (inventory.present) await persistInventory([]);
      return;
    }
    assertReady();
    await validateEntries(inventory.entries);
    await settleEntries(null);
  };

  const entriesForInput = (
    input: Parameters<SourceUpdaterCleanupBoundary["removeOwnedPaths"]>[0],
  ): OwnedCleanupEntry[] => {
    const entries = [
      ...(input.candidate ? [candidateEntry(input.candidate)] : []),
      ...(input.isolation ? [isolationEntry(input.isolation)] : []),
      ...(input.staging ?? []).map(stagingEntry),
    ];
    if (entries.some((entry) => entry.operationId !== entries[0]?.operationId)) {
      throw new Error("Owned-path cleanup evidence must belong to the same update attempt.");
    }
    if (new Set(entries.map((entry) => entry.kind)).size !== entries.length) {
      throw new Error("Owned-path cleanup evidence contains duplicate path kinds.");
    }
    if (new Set(entries.map((entry) => entry.nativeIdentity ?? `${entry.dev}:${entry.ino}`)).size !== entries.length) {
      throw new Error("Owned-path cleanup evidence aliases one directory identity.");
    }
    return entries;
  };

  const reserveOwnedPaths: SourceUpdaterCleanupBoundary["reserveOwnedPaths"] = async ({
    kinds: values,
    operationId: value,
  }) => {
    assertReady();
    const operationId = requireOperationId(value);
    const kinds = requireKinds(values);
    if (kinds.length === 0) return;
    const existing = (await readInventory()).entries;
    await validateEntries(existing);
    if (existing.some((entry) => entry.inventoryVersion === 1)) {
      throw new Error("Source cleanup v1 inventory must be recovered before reserving new paths.");
    }
    const merged = [...existing];
    for (const kind of kinds) {
      const prior = merged.find((entry) => entry.kind === kind && entry.operationId === operationId);
      if (prior) continue;
      const reservation: ReservedCleanupEntry = {
        inventoryVersion: 2,
        kind,
        operationId,
        state: "reserved",
      };
      const observed = await inspectEntry(reservation);
      if (observed.target || observed.quarantine) {
        throw new Error(`Refusing to reserve an existing source cleanup path: ${kind}.`);
      }
      merged.push(reservation);
    }
    if (merged.length > MAX_SOURCE_CLEANUP_ENTRIES) {
      throw new Error("Source cleanup inventory exceeds its bounded entry limit.");
    }
    if (merged.length === existing.length) return;
    await persistInventory(merged);
  };

  const inventoryOwnedPaths: SourceUpdaterCleanupBoundary["inventoryOwnedPaths"] = async (input) => {
    assertReady();
    const capturedEntries = entriesForInput(input);
    if (capturedEntries.length === 0) return;
    const existing = (await readInventory()).entries;
    const entries = await Promise.all(capturedEntries.map(async (entry): Promise<OwnedCleanupEntry> => {
      if (platform !== "win32") return entry;
      const prior = existing.find(
        (candidate) => candidate.kind === entry.kind && candidate.operationId === entry.operationId,
      );
      if (prior && prior.state !== "reserved") {
        if (
          prior.dev !== entry.dev ||
          prior.ino !== entry.ino ||
          !WINDOWS_NATIVE_IDENTITY_PATTERN.test(prior.nativeIdentity ?? "")
        ) {
          throw new Error("Pending Windows source cleanup ownership changed identity.");
        }
        return { ...entry, nativeIdentity: prior.nativeIdentity!, state: prior.state };
      }
      const location = cleanupLocation(entry.kind, entry.operationId, entry.inventoryVersion);
      const [rootIdentity, observed] = await Promise.all([
        fileSystem.inspectDirectory(location.root),
        fileSystem.inspectDirectory(location.target),
      ]);
      if (!rootIdentity || !observed) {
        throw new Error("Windows source cleanup ownership cannot be published without present native evidence.");
      }
      if (
        observed.dev !== entry.dev ||
        observed.ino !== entry.ino ||
        !WINDOWS_NATIVE_IDENTITY_PATTERN.test(observed.nativeIdentity ?? "") ||
        !samePath(
          observed.canonicalPath,
          path.join(rootIdentity.canonicalPath, location.expectedName),
          platform,
        )
      ) {
        throw new Error("Windows source cleanup ownership changed before native identity publication.");
      }
      return { ...entry, nativeIdentity: observed.nativeIdentity! };
    }));
    await validateEntries(existing);
    if (existing.some((entry) => entry.inventoryVersion === 1)) {
      throw new Error("Source cleanup v1 inventory must be recovered before publishing new ownership.");
    }
    let changed = false;
    const merged = [...existing];
    for (const entry of entries) {
      const index = merged.findIndex(
        (candidate) => candidate.kind === entry.kind && candidate.operationId === entry.operationId,
      );
      if (index >= 0) {
        const prior = merged[index]!;
        if (prior.state !== "reserved") {
          if (
            prior.dev !== entry.dev ||
            prior.ino !== entry.ino ||
            prior.nativeIdentity !== entry.nativeIdentity
          ) {
            throw new Error("Pending source cleanup ownership changed identity.");
          }
          continue;
        }
        merged[index] = entry;
        changed = true;
        continue;
      }
      merged.push(entry);
      changed = true;
    }
    if (merged.length > MAX_SOURCE_CLEANUP_ENTRIES) {
      throw new Error("Source cleanup inventory exceeds its bounded entry limit.");
    }
    const owned = merged.filter((entry): entry is OwnedCleanupEntry => entry.state !== "reserved");
    if (new Set(owned.map((entry) => entry.nativeIdentity ?? `${entry.dev}:${entry.ino}`)).size !== owned.length) {
      throw new Error("Source cleanup inventory aliases one directory identity across entries.");
    }
    await validateEntries(merged);
    if (changed) await persistInventory(merged);
  };

  const validateRecovery: SourceUpdaterCleanupBoundary["validateRecovery"] = async () => {
    const inventory = await readInventory();
    if (inventory.entries.length === 0) return;
    assertReady();
    await validateEntries(inventory.entries);
  };

  const removeReservedPaths: SourceUpdaterCleanupBoundary["removeReservedPaths"] = async ({
    kinds: values,
    operationId: value,
  }) => {
    assertReady();
    const operationId = requireOperationId(value);
    const kinds = requireKinds(values);
    if (kinds.length === 0) return;
    await settleEntries(new Set(kinds.map((kind) => `${kind}:${operationId}`)));
  };

  const removeOwnedPaths: SourceUpdaterCleanupBoundary["removeOwnedPaths"] = async (input) => {
    assertReady();
    const entries = entriesForInput(input);
    if (entries.length === 0) return;
    await inventoryOwnedPaths(input);
    await removeReservedPaths({
      kinds: entries.map((entry) => entry.kind),
      operationId: entries[0]!.operationId,
    });
  };

  return {
    assertReady,
    inventoryOwnedPaths,
    recover: replayInventory,
    removeReservedPaths,
    removeOwnedPaths,
    removeOwnedCandidate({ candidatePath, identity, operationId }) {
      return removeOwnedPaths({ candidate: { candidatePath, identity, operationId } });
    },
    removeIsolation({ identity, isolationPath }) {
      return removeOwnedPaths({ isolation: { identity, isolationPath } });
    },
    reserveOwnedPaths,
    validateRecovery,
  };
}

function exactHealthPaths(
  sourceRoot: string,
  isolationRoot: string,
  candidateRoot: string,
  isolation: CandidateHealthOptions["isolation"],
): string {
  const candidate = path.resolve(candidateRoot);
  const match = UPDATE_CANDIDATE_PATTERN.exec(path.basename(candidate));
  if (!path.isAbsolute(candidateRoot) || !match || !samePath(path.dirname(candidate), sourceRoot)) {
    throw new Error("Candidate health requires an exact managed UUID candidate path.");
  }
  const isolationPath = path.join(isolationRoot, `source-update-${match[1]}`);
  const expected = {
    flinttradeHome: path.join(isolationPath, "flinttrade-home"),
    home: path.join(isolationPath, "home"),
    workspace: path.join(isolationPath, "workspace"),
  };
  for (const key of ["flinttradeHome", "home", "workspace"] as const) {
    if (!path.isAbsolute(isolation[key]) || !samePath(path.resolve(isolation[key]), expected[key])) {
      throw new Error("Candidate health isolation is not bound to the exact update UUID.");
    }
  }
  return isolationPath;
}

async function provePreparedSourceHealth(
  options: NodeSourceUpdaterHealthOptions,
  sourcePath: string,
  isolationPath: string,
  isolation: CandidateHealthOptions["isolation"],
  onIsolationPrepared: (identity: FileSystemIdentity) => Promise<void> | void,
  signal?: AbortSignal,
): Promise<CandidateHealthProof & { isolationIdentity: FileSystemIdentity }> {
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");
  await assertCandidateRepositoryEnvironmentAbsent(sourcePath);
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");
  await options.dependencies.fileSystem.preparePrivateTree(options.isolationRoot, [], []);
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");

  const isolationFileSystem = createNodeSourcePromotionFileSystem();
  const rootIdentity = await isolationFileSystem.inspectDirectory(options.isolationRoot);
  if (!rootIdentity) {
    throw new Error("Candidate health isolation root must be an exact no-follow directory.");
  }
  try {
    await mkdir(isolationPath, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("Candidate health isolation already exists; refusing planted or stale evidence.");
    }
    throw error;
  }

  let isolationSnapshot;
  try {
    isolationSnapshot = await isolationFileSystem.inspectDirectory(isolationPath);
  } catch (error) {
    throw new CandidateHealthLeaseRetentionError(
      "Exclusively created candidate health isolation could not be identity-proven.",
      error,
    );
  }
  const expectedCanonical = path.join(rootIdentity.canonicalPath, path.basename(isolationPath));
  if (!isolationSnapshot || !samePath(isolationSnapshot.canonicalPath, expectedCanonical)) {
    throw new CandidateHealthLeaseRetentionError(
      "Exclusively created candidate health isolation has a foreign canonical identity.",
    );
  }
  const isolationIdentity = { dev: isolationSnapshot.dev, ino: isolationSnapshot.ino };
  await onIsolationPrepared(isolationIdentity);

  await options.dependencies.fileSystem.preparePrivateTree(
    isolationPath,
    ["home", "flinttrade-home", "workspace"],
    [],
  );
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");

  const assertIsolationHeld = async (): Promise<void> => {
    let current;
    try {
      current = await isolationFileSystem.inspectDirectory(isolationPath);
    } catch (error) {
      throw new CandidateHealthLeaseRetentionError(
        "Candidate health isolation identity could not be re-proven.",
        error,
      );
    }
    if (
      !current ||
      current.dev !== isolationIdentity.dev ||
      current.ino !== isolationIdentity.ino ||
      !samePath(current.canonicalPath, expectedCanonical)
    ) {
      throw new CandidateHealthLeaseRetentionError("Candidate health isolation identity changed after creation.");
    }
  };
  await assertIsolationHeld();
  await assertCandidateRepositoryEnvironmentAbsent(sourcePath);
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");
  let provisioned;
  try {
    provisioned = await options.dependencies.command.run({
      args: ["-m", "flinttrade_core.cli", "init", "--provision-master-password"],
      command: candidatePythonPath(sourcePath),
      cwd: sourcePath,
      env: createCandidateHealthEnvironment({ candidateRoot: sourcePath, isolation }),
      inheritEnvironment: false,
      ...(signal ? { signal } : {}),
      timeoutMs: options.timeoutMs ?? 180_000,
    });
  } catch (error) {
    throw new CandidateHealthLeaseRetentionError(
      "Candidate workspace provisioning process-tree cleanup could not be proven.",
      error,
    );
  }
  if (!provisioned.contained) {
    throw new CandidateHealthLeaseRetentionError(
      "Candidate workspace provisioning process-tree cleanup could not be proven.",
    );
  }
  if (signal?.aborted) throw cancellation("Candidate health preparation was cancelled.");
  if (provisioned.exitCode !== 0) {
    throw new Error(`Candidate workspace provisioning failed (exit ${provisioned.exitCode}).`);
  }
  await assertIsolationHeld();
  const prove = options.prove ?? proveCandidateHealth;
  const proof = await prove({
    candidateRoot: sourcePath,
    isolation,
    ...(options.ping ? { ping: options.ping } : {}),
    ...(options.pingIntervalMs === undefined ? {} : { pingIntervalMs: options.pingIntervalMs }),
    process: options.dependencies.command,
    ...(signal ? { signal } : {}),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  });
  await assertIsolationHeld();
  return { ...proof, isolationIdentity };
}

export function createNodeSourceUpdaterHealth(options: NodeSourceUpdaterHealthOptions): SourceUpdaterHealthBoundary {
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const isolationRoot = requireAbsoluteRoot(options.isolationRoot, "The health isolation root");
  const workspace = requireAbsoluteRoot(options.workspace, "The workspace");
  assertSeparated(sourceRoot, isolationRoot, "Managed source and health isolation roots");
  assertManagedSourceWorkspaceRelationship(sourceRoot, workspace);
  assertSeparated(isolationRoot, workspace, "Health isolation and workspace roots");
  const leaseTarget = path.join(sourceRoot, OPERATION_LEASE_NAME);
  if (options.dependencies.command.operationLeaseTarget !== leaseTarget) {
    throw new Error("Candidate health command containment must use the exact shared operation lease target.");
  }

  return {
    async prove(input) {
      if (input.signal.aborted) throw cancellation("Candidate health preparation was cancelled.");
      const isolationPath = exactHealthPaths(sourceRoot, isolationRoot, input.candidateRoot, input.isolation);
      return provePreparedSourceHealth(
        options,
        input.candidateRoot,
        isolationPath,
        input.isolation,
        input.onIsolationPrepared,
        input.signal,
      );
    },
  };
}

export function createNodeSourcePromotionHealthLifecycle(
  options: NodeSourcePromotionHealthLifecycleOptions,
): SourcePromotionBootLifecycle {
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const isolationRoot = requireAbsoluteRoot(options.isolationRoot, "The health isolation root");
  const workspace = requireAbsoluteRoot(options.workspace, "The workspace");
  const activeSource = path.join(sourceRoot, ACTIVE_SOURCE_NAME);
  assertSeparated(sourceRoot, isolationRoot, "Managed source and health isolation roots");
  assertManagedSourceWorkspaceRelationship(sourceRoot, workspace);
  assertSeparated(isolationRoot, workspace, "Health isolation and workspace roots");
  const leaseTarget = path.join(sourceRoot, OPERATION_LEASE_NAME);
  if (
    options.dependencies.command.operationLeaseTarget !== leaseTarget ||
    !samePath(options.operationLease.target, leaseTarget)
  ) {
    throw new Error("Promoted health proof must use the exact shared operation lease target.");
  }
  const uuid = options.uuid ?? randomUUID;

  return {
    async bootActive({ activePath, onBackendStopped }) {
      if (!path.isAbsolute(activePath) || !samePath(path.resolve(activePath), activeSource)) {
        throw new Error("Promoted health proof requires the exact managed active source.");
      }
      const assertMutationLease = async (): Promise<void> => {
        try {
          await options.operationLease.assertHeld();
        } catch (error) {
          if (isSourceOperationLeaseRetentionError(error)) throw error;
          throw new SourceOperationLeaseRetentionError(
            "Promoted health proof lost the shared source-operation lease.",
            { cause: error },
          );
        }
      };
      await assertMutationLease();
      const operationId = uuid();
      if (
        typeof operationId !== "string" ||
        operationId !== operationId.toLowerCase() ||
        !UUID_V4_PATTERN.test(operationId)
      ) {
        throw new Error("Promoted health isolation identity must be a canonical lowercase UUID v4.");
      }
      const isolationPath = path.join(isolationRoot, `source-update-${operationId}`);
      const isolation = {
        flinttradeHome: path.join(isolationPath, "flinttrade-home"),
        home: path.join(isolationPath, "home"),
        workspace: path.join(isolationPath, "workspace"),
      };
      await options.cleanup.reserveOwnedPaths({ kinds: ["isolation"], operationId });
      let healthy = false;
      let isolationIdentity: FileSystemIdentity | undefined;
      try {
        const proof = await provePreparedSourceHealth(
          options,
          activeSource,
          isolationPath,
          isolation,
          async (identity) => {
            await options.cleanup.inventoryOwnedPaths({
              isolation: { identity, isolationPath },
            });
            isolationIdentity = identity;
          },
        );
        await assertMutationLease();
        healthy = samePath(path.resolve(proof.candidateRoot), activeSource) &&
          isolationIdentity !== undefined &&
          proof.isolationIdentity.dev === isolationIdentity.dev &&
          proof.isolationIdentity.ino === isolationIdentity.ino &&
          Number.isSafeInteger(proof.port) && proof.port >= 1 && proof.port <= 65_535;
      } catch (error) {
        if (isSourceOperationLeaseRetentionError(error)) {
          if (isolationIdentity) {
            try {
              await options.cleanup.inventoryOwnedPaths({
                isolation: { identity: isolationIdentity, isolationPath },
              });
            } catch (inventoryFailure) {
              throw new SourceOperationLeaseRetentionError(
                "Promoted health containment remains unresolved and isolation cleanup inventory could not be made durable.",
                {
                  cause: new AggregateError([error, inventoryFailure]),
                  retentionPolicy: error.retentionPolicy,
                },
              );
            }
          }
          throw error;
        }
      }
      if (isolationIdentity) {
        await options.cleanup.removeIsolation({ identity: isolationIdentity, isolationPath });
      } else {
        await options.cleanup.removeReservedPaths({ kinds: ["isolation"], operationId });
      }
      if (!healthy) onBackendStopped();
      return healthy;
    },
  };
}

function managedSourcePath(sourceRoot: string, sourcePath: string, platform: NodeJS.Platform): string {
  if (!path.isAbsolute(sourcePath)) throw new Error("Source provenance requires an exact managed absolute target.");
  const resolved = path.resolve(sourcePath);
  if (samePath(resolved, path.join(sourceRoot, ACTIVE_SOURCE_NAME), platform)) return resolved;
  if (samePath(path.dirname(resolved), sourceRoot, platform) && UPDATE_CANDIDATE_PATTERN.test(path.basename(resolved))) {
    return resolved;
  }
  throw new Error("Source provenance requires the exact managed active or UUID candidate target.");
}

export function createSourceUpdaterProvenance(
  options: SourceUpdaterProvenanceOptions,
): SourceUpdaterProvenanceBoundary {
  const sourceRoot = requireAbsoluteRoot(options.sourceRoot, "The source root");
  const validate = options.validate ?? validateActiveSourceProvenance;
  const candidateAliases = async (): Promise<Map<string, string>> => {
    const aliases = new Map<string, string>();
    for (const name of await options.dependencies.fileSystem.listNames(sourceRoot)) {
      if (!UPDATE_CANDIDATE_PATTERN.test(name)) continue;
      const candidate = path.join(sourceRoot, name);
      aliases.set(options.platform === "win32" ? candidate.toLowerCase() : candidate, candidate);
    }
    return aliases;
  };

  return {
    async validate(input) {
      if (input.signal.aborted) throw cancellation("Source provenance validation was cancelled.");
      const sourcePath = managedSourcePath(sourceRoot, input.sourcePath, options.platform);
      const aliases = new Map<string, string>();
      const addAlias = (candidate: string): void => {
        if (!path.isAbsolute(candidate)) throw new Error("Source provenance aliases must be absolute managed paths.");
        const resolved = path.resolve(candidate);
        const name = path.basename(resolved);
        const managed =
          samePath(resolved, path.join(sourceRoot, ACTIVE_SOURCE_NAME), options.platform) ||
          samePath(resolved, path.join(sourceRoot, LAST_KNOWN_GOOD_NAME), options.platform) ||
          (samePath(path.dirname(resolved), sourceRoot, options.platform) && UPDATE_CANDIDATE_PATTERN.test(name));
        if (!managed) throw new Error("Source provenance alias is not an exact managed update path.");
        if (samePath(resolved, sourcePath, options.platform)) return;
        aliases.set(options.platform === "win32" ? resolved.toLowerCase() : resolved, resolved);
      };
      for (const alias of input.disallowedAliases) addAlias(alias);
      addAlias(path.join(sourceRoot, LAST_KNOWN_GOOD_NAME));
      if (!samePath(sourcePath, path.join(sourceRoot, ACTIVE_SOURCE_NAME), options.platform)) {
        addAlias(path.join(sourceRoot, ACTIVE_SOURCE_NAME));
      }
      const scannedAliases = await candidateAliases();
      for (const alias of scannedAliases.values()) addAlias(alias);
      if (input.signal.aborted) throw cancellation("Source provenance validation was cancelled.");
      const identity = await validate({
        activeSource: sourcePath,
        bootstrapResources: options.bootstrapResources,
        dependencies: {
          command: options.dependencies.command,
          fileSystem: options.dependencies.fileSystem,
        },
        disallowedAliases: [...aliases.values()],
        expected: options.expected,
        platform: options.platform,
        signal: input.signal,
        sourceRoot,
      });
      if (input.signal.aborted) throw cancellation("Source provenance validation was cancelled.");
      const finalAliases = await candidateAliases();
      if (
        finalAliases.size !== scannedAliases.size ||
        [...scannedAliases.keys()].some((candidate) => !finalAliases.has(candidate))
      ) {
        throw new Error("Managed source aliases changed during provenance validation.");
      }
      if (input.signal.aborted) throw cancellation("Source provenance validation was cancelled.");
      return identity;
    },
  };
}

export function createSourceUpdaterRevisionResolver(
  options: SourceUpdaterRevisionResolverOptions,
): SourceUpdaterRevisionBoundary {
  const resolve = options.resolve ?? resolveExactSourceRevision;
  return {
    resolve(signal) {
      return resolve({
        dependencies: options.dependencies,
        platform: options.platform,
        repository: FLINTTRADE_SOURCE_REPOSITORY,
        signal,
      });
    },
  };
}
