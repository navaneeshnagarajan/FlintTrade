import path from "node:path";

import { redactBootstrapText } from "./bootstrap";
import type { CandidateHealthIsolation, CandidateHealthProof } from "./candidate-health";
import type { SourceCandidateOwnedPath, SourceCandidateStager } from "./source-candidate";
import type { FileSystemIdentity } from "./bootstrap";
import {
  SourceOperationLeaseRetentionError,
  isSourceOperationLeaseRetentionError,
  type SourceOperationCoordinator,
  type SourceOperationKind,
  type SourceOperationLeaseRetentionPolicy,
} from "./source-operation";
import {
  ACTIVE_SOURCE_NAME,
  CANDIDATE_SOURCE_PREFIX,
  LAST_KNOWN_GOOD_NAME,
  type CompletedPromotionOutcome,
  type PromotionOutcome,
  type SourcePromotionRequest,
} from "./source-promotion";
import {
  sourceContentIdentityKey,
  type ActiveSourceIdentity,
  type ExactSourceRevision,
} from "./source-provenance";
import type { createUpdateState, UpdateSnapshot } from "./state";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const UUID_V4_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const OPERATION_LEASE_NAME = ".flinttrade-bootstrap-operation.lock";
export const SOURCE_UPDATE_HEARTBEAT_INTERVAL_MS = 4_000;

type SourceUpdateState = ReturnType<typeof createUpdateState>;
type UpdateOperationKind = Extract<SourceOperationKind, "update-apply" | "update-check">;
type UpdateActiveStatus = "applying" | "checking";

export interface SourceUpdaterProvenanceBoundary {
  /**
   * Validate repository shape, marker/content identity, origin, cleanliness,
   * all managed candidate/LKG aliases and repository-root `.env` absence for
   * this exact source path. `disallowedAliases` is the caller's minimum set;
   * the boundary remains responsible for any other managed candidate aliases.
   */
  validate(input: {
    disallowedAliases: readonly string[];
    signal: AbortSignal;
    sourcePath: string;
  }): Promise<ActiveSourceIdentity>;
}

export interface SourceUpdaterRevisionBoundary {
  resolve(signal: AbortSignal): Promise<ExactSourceRevision>;
}

export interface SourceUpdaterHealthBoundary {
  prove(input: {
    candidateRoot: string;
    isolation: CandidateHealthIsolation;
    /** Await durable ownership immediately after exclusive no-follow isolation creation. */
    onIsolationPrepared(identity: FileSystemIdentity): Promise<void> | void;
    signal: AbortSignal;
  }): Promise<CandidateHealthProof & { isolationIdentity: FileSystemIdentity }>;
}

export interface SourceUpdaterLifecycle {
  /**
   * Start and health-prove the long-lived backend for this exact active tree.
   * An unhealthy result or rejection is safe to act on only after the boundary
   * synchronously publishes exact stopped proof through onBackendStopped.
   */
  bootActive(input: {
    activePath: string;
    onBackendStopped(): void;
  }): Promise<boolean>;
  /**
   * Drain the current backend. The boundary must publish the point at which
   * the backend is known stopped before doing any further fallible work. A
   * rejection before that callback guarantees the backend is still running.
   */
  drainCurrent(input: {
    onBackendStopped(): void;
    signal: AbortSignal;
  }): Promise<void>;
  /** Task 3 scaffolds may explicitly report that the Task 4 backend lifecycle is unavailable. */
  isAvailable?(): boolean;
}

export interface SourceUpdaterPromotionBoundary {
  acknowledge(outcome: CompletedPromotionOutcome): Promise<void>;
  /** Fail synchronously before staging or drain when promotion cannot be made durable. */
  assertReady(): void;
  promote(request: SourcePromotionRequest): Promise<PromotionOutcome>;
  recover(): Promise<PromotionOutcome>;
}

export type SourceUpdaterCleanupKind =
  | "candidate"
  | "isolation"
  | "staging-candidate"
  | "staging-unpack";

export interface SourceUpdaterOwnedCleanupPaths {
  candidate?: { candidatePath: string; identity: FileSystemIdentity; operationId: string };
  isolation?: { identity: FileSystemIdentity; isolationPath: string };
  staging?: readonly {
    identity: FileSystemIdentity;
    kind: Extract<SourceCandidateOwnedPath["kind"], "staging-candidate" | "staging-unpack">;
    operationId: string;
    stagingPath: string;
  }[];
}

export interface SourceUpdaterCleanupBoundary {
  /** Fail synchronously before staging when identity-bound cleanup is unavailable. */
  assertReady(): void;
  /** Durably reserve exact UUID-bound names before any owned directory is created. */
  reserveOwnedPaths(input: {
    kinds: readonly SourceUpdaterCleanupKind[];
    operationId: string;
  }): Promise<void>;
  /** Validate every pending cleanup entry without mutating the filesystem or inventory. */
  validateRecovery(): Promise<void>;
  /** Settle and remove only the selected durable reservations. */
  removeReservedPaths(input: {
    kinds: readonly SourceUpdaterCleanupKind[];
    operationId: string;
  }): Promise<void>;
  /** Durably inventory and remove all owned paths as one crash-replayable batch. */
  removeOwnedPaths(input: SourceUpdaterOwnedCleanupPaths): Promise<void>;
  /** Persist ownership only; never delete while process containment is unresolved. */
  inventoryOwnedPaths(input: SourceUpdaterOwnedCleanupPaths): Promise<void>;
  /** Replay a previously inventoried cleanup batch on a fresh runtime. */
  recover(): Promise<void>;
  /**
   * Remove only a candidate whose identity is proven to belong to this UUID
   * attempt. A missing or foreign/pre-existing identity must be preserved.
   */
  removeOwnedCandidate(input: {
    candidatePath: string;
    identity: FileSystemIdentity;
    operationId: string;
  }): Promise<void>;
  /** Remove only the exact disposable isolation whose identity was captured at creation. */
  removeIsolation(input: { identity: FileSystemIdentity; isolationPath: string }): Promise<void>;
}

export interface SourceUpdaterOperationLease {
  acquire(input: {
    kind: SourceOperationKind;
    signal: AbortSignal;
  }): Promise<() => Promise<void>>;
  assertHeld(): Promise<void>;
  /** Retain the current release capability under the requested containment policy. */
  retainForContainment(policy: SourceOperationLeaseRetentionPolicy): boolean;
  target: string;
}

export type SourceUpdateEventPhase =
  | "apply-started"
  | "check-started"
  | "failed"
  | "promoted"
  | "recovery-complete"
  | "recovery-started"
  | "rolled-back"
  | "update-available"
  | "update-unavailable";

export interface SourceUpdateEvent {
  attempt: number;
  message: string;
  operation: SourceOperationKind;
  phase: SourceUpdateEventPhase;
  /** Stable journal operation identity for idempotent terminal-outcome replay. */
  promotionId: string | null;
  revision: string | null;
}

export interface SourceUpdaterEventRecorder {
  /** Resolve only after the redacted event is durably recorded. */
  record(event: Readonly<SourceUpdateEvent>): Promise<void>;
}

export interface SourceUpdaterOptions {
  activeSource: string;
  candidateStager: SourceCandidateStager;
  cleanup: SourceUpdaterCleanupBoundary;
  coordinator: SourceOperationCoordinator;
  events: SourceUpdaterEventRecorder;
  health: SourceUpdaterHealthBoundary;
  heartbeatIntervalMs?: number;
  isolationRoot: string;
  lifecycle: SourceUpdaterLifecycle;
  operationLease: SourceUpdaterOperationLease;
  promotion: SourceUpdaterPromotionBoundary;
  provenance: SourceUpdaterProvenanceBoundary;
  revisionResolver: SourceUpdaterRevisionBoundary;
  /** Additional private roots whose spelling must never reach public update state. */
  redactedPaths?: readonly string[];
  sourceRoot: string;
  state: SourceUpdateState;
  platform?: NodeJS.Platform;
  uuid(): string;
}

export interface SourceUpdater {
  apply(signal?: AbortSignal): Promise<Readonly<UpdateSnapshot>>;
  cancel(kind?: "apply" | "check"): boolean;
  check(signal?: AbortSignal): Promise<Readonly<UpdateSnapshot>>;
  recover(signal?: AbortSignal): Promise<PromotionOutcome>;
}

interface CheckedUpdate {
  active: ActiveSourceIdentity;
  revision: string;
}

interface OwnedApplyPaths {
  candidate: string;
  candidateIdentity?: FileSystemIdentity;
  isolation: string;
  isolationEnvironment: CandidateHealthIsolation;
  isolationIdentity?: FileSystemIdentity;
  operationId: string;
  staging: Array<{
    identity: FileSystemIdentity;
    kind: Extract<SourceCandidateOwnedPath["kind"], "staging-candidate" | "staging-unpack">;
    path: string;
  }>;
}

class StaleSourceUpdateError extends Error {
  constructor() {
    super("A newer source update attempt superseded this worker.");
    this.name = "StaleSourceUpdateError";
  }
}

function exactRevision(value: unknown, label: string): string {
  if (typeof value !== "string" || !COMMIT_PATTERN.test(value)) {
    throw new Error(`${label} must be an exact lowercase 40-character Git revision.`);
  }
  return value;
}

function samePath(left: string, right: string): boolean {
  return process.platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function isWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function identityKey(identity: ActiveSourceIdentity): string {
  return JSON.stringify(
    identity.provenance === "git"
      ? {
          canonicalPath: path.resolve(identity.canonicalPath),
          contentIdentity: identity.contentIdentity,
          directoryIdentity: identity.directoryIdentity,
          provenance: identity.provenance,
          revision: identity.revision,
        }
      : {
          archiveFinalOrigin: identity.archiveFinalOrigin,
          archiveSha256: identity.archiveSha256,
          canonicalPath: path.resolve(identity.canonicalPath),
          contentIdentity: identity.contentIdentity,
          directoryIdentity: identity.directoryIdentity,
          provenance: identity.provenance,
          revision: identity.revision,
        },
  );
}

function sameIdentity(left: ActiveSourceIdentity, right: ActiveSourceIdentity): boolean {
  return identityKey(left) === identityKey(right);
}

function sameDirectoryIdentity(left: FileSystemIdentity, right: FileSystemIdentity): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function cancellation(message: string): DOMException {
  return new DOMException(message, "AbortError");
}

function assertSignal(signal: AbortSignal): void {
  if (signal.aborted) throw cancellation("Source update operation was cancelled.");
}

function validateConfiguration(options: SourceUpdaterOptions): {
  activeSource: string;
  isolationRoot: string;
  lastKnownGood: string;
  sourceRoot: string;
} {
  if (!path.isAbsolute(options.sourceRoot) || !path.isAbsolute(options.isolationRoot)) {
    throw new Error("Source update roots must be absolute paths.");
  }
  const sourceRoot = path.resolve(options.sourceRoot);
  const isolationRoot = path.resolve(options.isolationRoot);
  const activeSource = path.resolve(options.activeSource);
  const expectedActive = path.join(sourceRoot, ACTIVE_SOURCE_NAME);
  if (!samePath(activeSource, expectedActive)) {
    throw new Error("The source updater active path must be the exact managed active sibling.");
  }
  if (isWithin(sourceRoot, isolationRoot) || isWithin(isolationRoot, sourceRoot)) {
    throw new Error("Candidate health isolation and managed source roots must not overlap.");
  }
  const expectedLease = path.join(sourceRoot, OPERATION_LEASE_NAME);
  if (
    typeof options.operationLease.assertHeld !== "function" ||
    !path.isAbsolute(options.operationLease.target) ||
    !samePath(path.resolve(options.operationLease.target), expectedLease)
  ) {
    throw new Error("Source update commands must use the exact shared bootstrap operation lease.");
  }
  return {
    activeSource,
    isolationRoot,
    lastKnownGood: path.join(sourceRoot, LAST_KNOWN_GOOD_NAME),
    sourceRoot,
  };
}

export function createSourceUpdater(options: SourceUpdaterOptions): SourceUpdater {
  const paths = validateConfiguration(options);
  const platform = options.platform ?? process.platform;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? SOURCE_UPDATE_HEARTBEAT_INTERVAL_MS;
  if (!Number.isSafeInteger(heartbeatIntervalMs) || heartbeatIntervalMs <= 0) {
    throw new Error("Source update heartbeat interval must be a positive safe integer.");
  }
  const usedOperationIds = new Set<string>();
  let checkedUpdate: CheckedUpdate | null = null;
  let recoveryAttempt = 0;

  const redactPrivatePath = (value: string, target: string, replacement: string): string => {
    const variants = [...new Set([
      target,
      target.replaceAll("\\", "/"),
      target.replaceAll("/", "\\"),
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
  };

  const privatePaths = [
    [paths.sourceRoot, "<source-root>"],
    [paths.isolationRoot, "<health-isolation>"],
    ...(options.redactedPaths ?? []).map((target) => [path.resolve(target), "<private-path>"] as const),
  ] as const;

  const sanitise = (error: unknown): string => {
    const raw = error instanceof Error ? error.message : String(error);
    return privatePaths.reduce(
      (value, [target, replacement]) => redactPrivatePath(value, target, replacement),
      redactBootstrapText(raw),
    );
  };

  const assertCurrentAttempt = (attempt: number, status: UpdateActiveStatus): void => {
    const snapshot = options.state.getSnapshot();
    if (snapshot.attempt !== attempt || snapshot.status !== status) throw new StaleSourceUpdateError();
  };

  const assertAttempt = (
    attempt: number,
    status: UpdateActiveStatus,
    signal: AbortSignal,
  ): void => {
    assertSignal(signal);
    assertCurrentAttempt(attempt, status);
  };

  const runWithHeartbeat = async <T>(
    attempt: number,
    status: UpdateActiveStatus,
    signal: AbortSignal,
    message: string,
    progress: number | null,
    work: () => Promise<T>,
  ): Promise<T> => {
    assertAttempt(attempt, status, signal);
    options.state.publishForAttempt(attempt, { message, progress });
    const timer = setInterval(() => {
      if (!signal.aborted) options.state.publishForAttempt(attempt, { message, progress });
    }, heartbeatIntervalMs);
    timer.unref?.();
    try {
      return await work();
    } finally {
      clearInterval(timer);
    }
  };

  const recordAuthoritativeOutcome = async (
    attempt: number,
    event: Omit<SourceUpdateEvent, "attempt">,
  ): Promise<void> => {
    assertCurrentAttempt(attempt, "applying");
    await options.events.record({ ...event, attempt });
    assertCurrentAttempt(attempt, "applying");
  };

  const recordTerminalAttempt = async (
    attempt: number,
    status: UpdateActiveStatus,
    event: Omit<SourceUpdateEvent, "attempt">,
  ): Promise<void> => {
    assertCurrentAttempt(attempt, status);
    await options.events.record({ ...event, attempt });
    assertCurrentAttempt(attempt, status);
  };

  const recordAttempt = async (
    attempt: number,
    status: UpdateActiveStatus,
    signal: AbortSignal,
    event: Omit<SourceUpdateEvent, "attempt">,
  ): Promise<void> => {
    assertAttempt(attempt, status, signal);
    await options.events.record({ ...event, attempt });
    assertAttempt(attempt, status, signal);
  };

  const recordRecovery = async (
    attempt: number,
    signal: AbortSignal,
    event: Omit<SourceUpdateEvent, "attempt">,
  ): Promise<void> => {
    assertSignal(signal);
    await options.events.record({ ...event, attempt });
    assertSignal(signal);
  };

  const recordAuthoritativeRecovery = async (
    attempt: number,
    event: Omit<SourceUpdateEvent, "attempt">,
  ): Promise<void> => {
    await options.events.record({ ...event, attempt });
  };

  const retainLiveBackendUntilProcessExit = (message: string, error: unknown): never => {
    if (
      isSourceOperationLeaseRetentionError(error) &&
      error.retentionPolicy === "process-exit-required"
    ) {
      throw error;
    }
    throw new SourceOperationLeaseRetentionError(message, {
      cause: error,
      retentionPolicy: "process-exit-required",
    });
  };

  const withOperationLease = async <T>(
    kind: SourceOperationKind,
    signal: AbortSignal,
    work: () => Promise<T>,
  ): Promise<T> => {
    assertSignal(signal);
    const release = await options.operationLease.acquire({ kind, signal });
    let result: T | undefined;
    let workFailure: unknown;
    try {
      await options.operationLease.assertHeld();
      assertSignal(signal);
      result = await work();
    } catch (error) {
      workFailure = error;
    }
    if (isSourceOperationLeaseRetentionError(workFailure)) {
      // Command containment is unresolved. Releasing this filesystem lease
      // would admit another source mutation while the old tree may be alive.
      options.operationLease.retainForContainment(workFailure.retentionPolicy);
      throw workFailure;
    }
    try {
      await release();
    } catch (releaseFailure) {
      if (workFailure !== undefined) {
        throw new AggregateError([workFailure, releaseFailure], "Source operation and lease release both failed.");
      }
      throw releaseFailure;
    }
    if (workFailure !== undefined) throw workFailure;
    return result as T;
  };

  const failAttempt = async (
    attempt: number,
    status: UpdateActiveStatus,
    signal: AbortSignal,
    operation: UpdateOperationKind,
    error: unknown,
  ): Promise<Readonly<UpdateSnapshot>> => {
    const snapshot = options.state.getSnapshot();
    if (snapshot.attempt !== attempt || snapshot.status !== status) return snapshot;
    const message = error instanceof DOMException && error.name === "AbortError"
      ? "Source update was cancelled."
      : sanitise(error);
    try {
      await recordTerminalAttempt(attempt, status, {
        message,
        operation,
        phase: "failed",
        promotionId: null,
        revision: snapshot.version,
      });
    } catch {
      // The original failure remains authoritative; stale attempts cannot publish.
    }
    options.state.fail(attempt, message);
    return options.state.getSnapshot();
  };

  const nextOwnedPaths = (): OwnedApplyPaths => {
    const operationId = options.uuid();
    if (
      !UUID_V4_PATTERN.test(operationId) ||
      operationId !== operationId.toLowerCase() ||
      usedOperationIds.has(operationId)
    ) {
      throw new Error("Source update candidate identity must be a unique canonical lowercase UUID v4.");
    }
    usedOperationIds.add(operationId);
    const candidate = path.join(paths.sourceRoot, `${CANDIDATE_SOURCE_PREFIX}${operationId}`);
    const isolation = path.join(paths.isolationRoot, `source-update-${operationId}`);
    return {
      candidate,
      isolation,
      isolationEnvironment: {
        flinttradeHome: path.join(isolation, "flinttrade-home"),
        home: path.join(isolation, "home"),
        workspace: path.join(isolation, "workspace"),
      },
      operationId,
      staging: [],
    };
  };

  const ownedCleanupPaths = (
    owned: OwnedApplyPaths,
    removeCandidate: boolean,
  ): SourceUpdaterOwnedCleanupPaths => ({
    ...(removeCandidate && owned.candidateIdentity
      ? {
          candidate: {
            candidatePath: owned.candidate,
            identity: owned.candidateIdentity,
            operationId: owned.operationId,
          },
        }
      : {}),
    ...(owned.isolationIdentity
      ? { isolation: { identity: owned.isolationIdentity, isolationPath: owned.isolation } }
      : {}),
    ...(owned.staging.length > 0
      ? {
          staging: owned.staging.map((entry) => ({
            identity: entry.identity,
            kind: entry.kind,
            operationId: owned.operationId,
            stagingPath: entry.path,
          })),
        }
      : {}),
  });

  const cleanupOwned = async (
    owned: OwnedApplyPaths,
    removeCandidate: boolean,
  ): Promise<void> => {
    await options.cleanup.removeReservedPaths({
      kinds: [
        ...(removeCandidate ? ["candidate" as const] : []),
        "isolation",
        "staging-candidate",
        "staging-unpack",
      ],
      operationId: owned.operationId,
    });
  };

  const check = (externalSignal?: AbortSignal): Promise<Readonly<UpdateSnapshot>> =>
    options.coordinator.run("update-check", externalSignal, async (signal) => {
      const attempt = options.state.begin("checking", "Checking for a source update");
      checkedUpdate = null;
      try {
        const result = await withOperationLease("update-check", signal, async () => {
          await recordAttempt(attempt, "checking", signal, {
            message: "Checking the trusted source revision",
            operation: "update-check",
            phase: "check-started",
            promotionId: null,
            revision: null,
          });
          const active = await runWithHeartbeat(
            attempt,
            "checking",
            signal,
            "Validating the active source",
            null,
            () => options.provenance.validate({
              disallowedAliases: [paths.lastKnownGood],
              signal,
              sourcePath: paths.activeSource,
            }),
          );
          assertAttempt(attempt, "checking", signal);
          exactRevision(active.revision, "The active source revision");
          const latest = await runWithHeartbeat(
            attempt,
            "checking",
            signal,
            "Resolving the trusted source revision",
            null,
            () => options.revisionResolver.resolve(signal),
          );
          assertAttempt(attempt, "checking", signal);
          const revision = exactRevision(latest.revision, "The latest source revision");
          const available = revision !== active.revision;
          await recordAttempt(attempt, "checking", signal, {
            message: available ? "A source update is available" : "The source is current",
            operation: "update-check",
            phase: available ? "update-available" : "update-unavailable",
            promotionId: null,
            revision,
          });
          return { active, available, revision };
        });
        assertAttempt(attempt, "checking", signal);
        if (!result.available) {
          options.state.unavailable(
            attempt,
            `Source ${result.revision.slice(0, 12)} is current`,
            result.active.revision,
          );
          return options.state.getSnapshot();
        }
        if (options.state.available(
          attempt,
          result.revision,
          `Source ${result.revision.slice(0, 12)} is available`,
          result.active.revision,
        )) {
          checkedUpdate = { active: result.active, revision: result.revision };
        }
        return options.state.getSnapshot();
      } catch (error) {
        return failAttempt(attempt, "checking", signal, "update-check", error);
      }
    });

  const apply = (externalSignal?: AbortSignal): Promise<Readonly<UpdateSnapshot>> =>
    options.coordinator.run("update-apply", externalSignal, async (signal) => {
      const prior = options.state.getSnapshot();
      const selection = checkedUpdate;
      if (prior.status !== "available") return prior;
      const attempt = options.state.begin("applying", "Preparing the checked source update", prior.version);
      checkedUpdate = null;
      let promotionStarted = false;
      let backendDrained = false;
      let restartAttempted = false;
      let restartOriginalAfterDrain: ((originalFailure: unknown) => Promise<void>) | null = null;
      try {
        if (!(options.lifecycle.isAvailable?.() ?? true)) {
          throw new Error("Source update apply requires an available backend guardian lifecycle.");
        }
        options.cleanup.assertReady();
        options.promotion.assertReady();
        if (!selection || prior.version !== selection.revision) {
          throw new Error("No exact checked source revision is ready to apply.");
        }
        const revision = exactRevision(selection.revision, "The source update revision");
        const outcome = await withOperationLease("update-apply", signal, async () => {
          await options.cleanup.validateRecovery();
          const priorRecovery = await runWithHeartbeat(
            attempt,
            "applying",
            signal,
            "Reconciling any interrupted source promotion",
            0,
            () => options.promotion.recover(),
          );
          if (priorRecovery.status !== "idle") {
            try {
              await recordAuthoritativeOutcome(attempt, {
                message: "A prior source promotion was reconciled; run a fresh update check",
                operation: "update-apply",
                phase: priorRecovery.status,
                promotionId: priorRecovery.promotionId,
                revision: null,
              });
              await options.promotion.acknowledge(priorRecovery);
            } catch (error) {
              retainLiveBackendUntilProcessExit(
                "A recovered backend is live but its promotion journal could not be acknowledged; same-process recovery is blocked.",
                error,
              );
            }
            await options.cleanup.recover();
            throw new Error("A prior source promotion was reconciled; run a fresh update check before applying.");
          }
          await options.cleanup.recover();
          assertAttempt(attempt, "applying", signal);
          const owned = nextOwnedPaths();
          let applyFailure: unknown;
          let ownedReservationsSettled = false;
          try {
            await options.cleanup.reserveOwnedPaths({
              kinds: ["candidate", "isolation", "staging-candidate", "staging-unpack"],
              operationId: owned.operationId,
            });
            await recordAttempt(attempt, "applying", signal, {
              message: "Staging the checked source revision",
              operation: "update-apply",
              phase: "apply-started",
              promotionId: null,
              revision,
            });
            const initialActive = await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Revalidating the active source",
              5,
              () => options.provenance.validate({
                disallowedAliases: [paths.lastKnownGood, owned.candidate],
                signal,
                sourcePath: paths.activeSource,
              }),
            );
            restartOriginalAfterDrain = async (originalFailure: unknown): Promise<void> => {
              restartAttempted = true;
              let backendStopped = false;
              let restartLive = false;
              try {
                await options.operationLease.assertHeld();
                const current = await options.provenance.validate({
                  disallowedAliases: [paths.lastKnownGood, owned.candidate],
                  signal: new AbortController().signal,
                  sourcePath: paths.activeSource,
                });
                if (!sameIdentity(current, initialActive)) {
                  throw new Error("The original active source changed after drain; it cannot be restarted safely.");
                }
                let restarted = false;
                try {
                  restarted = await options.lifecycle.bootActive({
                    activePath: paths.activeSource,
                    onBackendStopped() {
                      if (backendStopped) throw new Error("The original backend restart reported duplicate stopped proof.");
                      backendStopped = true;
                    },
                  });
                } catch (bootFailure) {
                  if (isSourceOperationLeaseRetentionError(bootFailure)) {
                    if (backendStopped) throw bootFailure;
                    throw new SourceOperationLeaseRetentionError(
                      "The original backend restart lost containment without proving that its process stopped.",
                      { cause: bootFailure, retentionPolicy: "process-exit-required" },
                    );
                  }
                  if (!backendStopped) {
                    throw new SourceOperationLeaseRetentionError(
                      "The original backend restart failed without proving that its process stopped.",
                      { cause: bootFailure, retentionPolicy: "process-exit-required" },
                    );
                  }
                  throw bootFailure;
                }
                if (restarted && backendStopped) {
                  throw new Error("The original backend restart reported both live readiness and stopped proof.");
                }
                if (!restarted) {
                  if (!backendStopped) {
                    throw new SourceOperationLeaseRetentionError(
                      "The original backend restart was unhealthy without proving that its process stopped.",
                      { retentionPolicy: "process-exit-required" },
                    );
                  }
                  throw new Error("The original active backend failed to restart after the update was refused.");
                }
                restartLive = true;
                await options.operationLease.assertHeld();
                backendDrained = false;
              } catch (restartFailure) {
                if (restartLive) {
                  if (
                    isSourceOperationLeaseRetentionError(restartFailure) &&
                    restartFailure.retentionPolicy === "process-exit-required"
                  ) {
                    throw restartFailure;
                  }
                  throw new SourceOperationLeaseRetentionError(
                    "The original backend is live but restart finalisation failed; same-process source work is blocked.",
                    { cause: restartFailure, retentionPolicy: "process-exit-required" },
                  );
                }
                if (isSourceOperationLeaseRetentionError(restartFailure)) throw restartFailure;
                throw new AggregateError(
                  [originalFailure, restartFailure],
                  "The source update failed after drain and the original backend could not be restored safely.",
                );
              }
            };
            assertAttempt(attempt, "applying", signal);
            if (!sameIdentity(initialActive, selection.active)) {
              throw new Error("The active source changed after the update check; run a fresh check.");
            }
            const staged = await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Staging and building the exact source revision",
              15,
              () => options.candidateStager.stage({
                destination: owned.candidate,
                async onOwnedPathPrepared(prepared) {
                  const expectedPath = prepared.kind === "candidate"
                    ? owned.candidate
                    : prepared.kind === "staging-candidate"
                      ? `${owned.candidate}.candidate-1`
                      : `${owned.candidate}.candidate-1.unpack`;
                  if (
                    !path.isAbsolute(prepared.path) ||
                    !samePath(path.resolve(prepared.path), expectedPath) ||
                    !Number.isSafeInteger(prepared.identity.dev) ||
                    prepared.identity.dev < 0 ||
                    !Number.isSafeInteger(prepared.identity.ino) ||
                    prepared.identity.ino < 0
                  ) {
                    throw new SourceOperationLeaseRetentionError(
                      "Source candidate staging published invalid owned-path evidence.",
                    );
                  }
                  const identity = { dev: prepared.identity.dev, ino: prepared.identity.ino };
                  const priorIdentities = [
                    ...(owned.candidateIdentity ? [owned.candidateIdentity] : []),
                    ...owned.staging.map((entry) => entry.identity),
                  ];
                  if (priorIdentities.some((prior) => sameDirectoryIdentity(prior, identity))) {
                    throw new SourceOperationLeaseRetentionError(
                      "Source candidate staging published duplicate directory ownership.",
                    );
                  }
                  if (prepared.kind === "candidate") {
                    if (owned.candidateIdentity) {
                      throw new SourceOperationLeaseRetentionError(
                        "Source candidate staging published duplicate candidate ownership.",
                      );
                    }
                    await options.cleanup.inventoryOwnedPaths({
                      candidate: {
                        candidatePath: owned.candidate,
                        identity,
                        operationId: owned.operationId,
                      },
                    });
                    owned.candidateIdentity = identity;
                    return;
                  }
                  if (owned.staging.some((entry) => entry.kind === prepared.kind)) {
                    throw new SourceOperationLeaseRetentionError(
                      "Source candidate staging published duplicate bootstrap-path ownership.",
                    );
                  }
                  await options.cleanup.inventoryOwnedPaths({
                    staging: [{
                      identity,
                      kind: prepared.kind,
                      operationId: owned.operationId,
                      stagingPath: prepared.path,
                    }],
                  });
                  owned.staging.push({ identity, kind: prepared.kind, path: prepared.path });
                },
                revision,
                signal,
              }),
            );
            if (
              !samePath(path.resolve(staged.path), owned.candidate) ||
              !Number.isSafeInteger(staged.identity.dev) ||
              staged.identity.dev < 0 ||
              !Number.isSafeInteger(staged.identity.ino) ||
              staged.identity.ino < 0 ||
              exactRevision(staged.revision, "The staged source revision") !== revision ||
              !owned.candidateIdentity ||
              !sameDirectoryIdentity(owned.candidateIdentity, staged.identity)
            ) {
              throw new Error("The staged source candidate does not match the exact requested revision.");
            }
            owned.candidateIdentity = staged.identity;
            await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Settling bootstrap staging ownership",
              35,
              () => options.cleanup.removeReservedPaths({
                kinds: ["staging-candidate", "staging-unpack"],
                operationId: owned.operationId,
              }),
            );
            owned.staging.length = 0;
            // The awaited ownership callback durably upgrades the reservation
            // before the stager can return; its result must reconfirm that
            // exact identity before any cancellation observation.
            assertAttempt(attempt, "applying", signal);
            const candidate = await options.provenance.validate({
              disallowedAliases: [paths.activeSource, paths.lastKnownGood],
              signal,
              sourcePath: owned.candidate,
            });
            assertAttempt(attempt, "applying", signal);
            if (
              !samePath(path.resolve(candidate.canonicalPath), owned.candidate) ||
              !sameDirectoryIdentity(candidate.directoryIdentity, staged.identity) ||
              exactRevision(candidate.revision, "The candidate source revision") !== revision ||
              candidate.provenance !== staged.provenance
            ) {
              throw new Error("The completed candidate failed exact source revalidation.");
            }
            const proof = await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Proving the staged candidate in isolation",
              45,
              () => options.health.prove({
                candidateRoot: owned.candidate,
                isolation: owned.isolationEnvironment,
                async onIsolationPrepared(identity) {
                  if (
                    owned.isolationIdentity ||
                    !Number.isSafeInteger(identity.dev) ||
                    identity.dev < 0 ||
                    !Number.isSafeInteger(identity.ino) ||
                    identity.ino < 0
                  ) {
                    throw new SourceOperationLeaseRetentionError(
                      "Candidate health isolation ownership proof is invalid or duplicated.",
                    );
                  }
                  const preparedIdentity = { dev: identity.dev, ino: identity.ino };
                  await options.cleanup.inventoryOwnedPaths({
                    isolation: { identity: preparedIdentity, isolationPath: owned.isolation },
                  });
                  owned.isolationIdentity = preparedIdentity;
                },
                signal,
              }),
            );
            assertAttempt(attempt, "applying", signal);
            if (
              !samePath(path.resolve(proof.candidateRoot), owned.candidate) ||
              !owned.isolationIdentity ||
              proof.isolationIdentity.dev !== owned.isolationIdentity.dev ||
              proof.isolationIdentity.ino !== owned.isolationIdentity.ino ||
              !Number.isSafeInteger(proof.port) ||
              proof.port < 1 ||
              proof.port > 65_535
            ) {
              throw new Error("Candidate health proof is not bound to the exact staged source.");
            }
            await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Removing the contained health isolation",
              60,
              () => options.cleanup.removeReservedPaths({
                kinds: ["isolation"],
                operationId: owned.operationId,
              }),
            );
            delete owned.isolationIdentity;
            const healthyCandidate = await options.provenance.validate({
              disallowedAliases: [paths.activeSource, paths.lastKnownGood],
              signal,
              sourcePath: owned.candidate,
            });
            assertAttempt(attempt, "applying", signal);
            if (!sameIdentity(healthyCandidate, candidate)) {
              throw new Error("The candidate source changed during its health proof; refusing backend drain.");
            }
            const finalActive = await options.provenance.validate({
              disallowedAliases: [paths.lastKnownGood, owned.candidate],
              signal,
              sourcePath: paths.activeSource,
            });
            assertAttempt(attempt, "applying", signal);
            if (!sameIdentity(finalActive, initialActive)) {
              throw new Error("The active source changed before backend drain; refusing promotion.");
            }
            await options.operationLease.assertHeld();
            assertAttempt(attempt, "applying", signal);
            await runWithHeartbeat(
              attempt,
              "applying",
              signal,
              "Draining the active backend",
              70,
              () => options.lifecycle.drainCurrent({
                onBackendStopped() {
                  if (backendDrained) {
                    throw new Error("The backend drain reported a duplicate stopped transition.");
                  }
                  backendDrained = true;
                },
                signal,
              }),
            );
            if (!backendDrained) {
              throw new Error("The backend drain completed without proving that the backend stopped.");
            }
            assertAttempt(attempt, "applying", signal);
            const postDrainActive = await options.provenance.validate({
              disallowedAliases: [paths.lastKnownGood, owned.candidate],
              signal,
              sourcePath: paths.activeSource,
            });
            const postDrainCandidate = await options.provenance.validate({
              disallowedAliases: [paths.activeSource, paths.lastKnownGood],
              signal,
              sourcePath: owned.candidate,
            });
            assertAttempt(attempt, "applying", signal);
            if (
              !sameIdentity(postDrainActive, initialActive) ||
              !sameIdentity(postDrainCandidate, candidate) ||
              !sameDirectoryIdentity(postDrainCandidate.directoryIdentity, staged.identity)
            ) {
              throw new Error("Source identity changed during backend drain; refusing promotion.");
            }
            await options.operationLease.assertHeld();
            assertAttempt(attempt, "applying", signal);
            promotionStarted = true;
            let promotionOutcome: PromotionOutcome;
            try {
              promotionOutcome = await runWithHeartbeat(
                attempt,
                "applying",
                signal,
                "Promoting the verified source candidate",
                85,
                () => options.promotion.promote({
                  candidateContentIdentity: sourceContentIdentityKey(candidate),
                  candidateDirectoryIdentity: staged.identity,
                  candidatePath: owned.candidate,
                  originalActiveContentIdentity: sourceContentIdentityKey(initialActive),
                  originalActiveDirectoryIdentity: initialActive.directoryIdentity,
                }),
              );
            } catch (promotionFailure) {
              if (isSourceOperationLeaseRetentionError(promotionFailure)) throw promotionFailure;
              await options.operationLease.assertHeld();
              let recovered: PromotionOutcome;
              try {
                recovered = await options.promotion.recover();
              } catch (recoveryFailure) {
                if (isSourceOperationLeaseRetentionError(recoveryFailure)) throw recoveryFailure;
                throw new AggregateError(
                  [promotionFailure, recoveryFailure],
                  "Source promotion failed and could not be reconciled safely; recovery evidence is retained.",
                );
              }
              if (recovered.status === "idle") {
                promotionStarted = false;
                await restartOriginalAfterDrain(promotionFailure);
                throw promotionFailure;
              }
              promotionOutcome = recovered;
            }
            if (promotionOutcome.status === "idle") {
              throw new Error("Source promotion returned no completed update outcome.");
            }
            backendDrained = false;
            try {
              await recordAuthoritativeOutcome(attempt, {
                message: promotionOutcome.status === "promoted"
                  ? "Source update promoted successfully"
                  : "Source update rolled back to the last-known-good source",
                operation: "update-apply",
                phase: promotionOutcome.status === "promoted" ? "promoted" : "rolled-back",
                promotionId: promotionOutcome.promotionId,
                revision,
              });
              // Promotion is already terminal. Retire the now-absent candidate
              // reservation without allowing late UI cancellation to overwrite
              // the authoritative outcome; keep the journal until this succeeds.
              await options.cleanup.removeReservedPaths({
                kinds: ["candidate"],
                operationId: owned.operationId,
              });
              ownedReservationsSettled = true;
              await options.promotion.acknowledge(promotionOutcome);
            } catch (error) {
              retainLiveBackendUntilProcessExit(
                "The promoted backend is live but its promotion journal could not be acknowledged; same-process recovery is blocked.",
                error,
              );
            }
            return promotionOutcome;
          } catch (error) {
            let settledFailure = error;
            if (
              backendDrained &&
              !promotionStarted &&
              !restartAttempted &&
              restartOriginalAfterDrain !== null &&
              !isSourceOperationLeaseRetentionError(error)
            ) {
              try {
                await restartOriginalAfterDrain(error);
              } catch (restartFailure) {
                settledFailure = restartFailure;
              }
            }
            applyFailure = settledFailure;
            throw settledFailure;
          } finally {
            if (ownedReservationsSettled) {
              // Candidate, isolation and staging reservations were all retired
              // before acknowledgement. Do not introduce a new fallible read
              // after the terminal promotion journal has been deleted.
            } else if (isSourceOperationLeaseRetentionError(applyFailure)) {
              // The uncontained tree may still hold files in both owned paths.
              // Inventory their exact identities without deleting them, then
              // preserve the lease until quit can re-prove containment.
              try {
                await options.cleanup.inventoryOwnedPaths(
                  ownedCleanupPaths(owned, !promotionStarted),
                );
              } catch (inventoryFailure) {
                throw new SourceOperationLeaseRetentionError(
                  "Source containment remains unresolved and owned-path cleanup inventory could not be made durable.",
                  {
                    cause: new AggregateError([applyFailure, inventoryFailure]),
                    retentionPolicy: applyFailure.retentionPolicy,
                  },
                );
              }
              throw applyFailure;
            } else {
              try {
                await cleanupOwned(owned, !promotionStarted);
              } catch (cleanupFailure) {
                if (isSourceOperationLeaseRetentionError(cleanupFailure)) throw cleanupFailure;
                if (applyFailure !== undefined) {
                  throw new Error(`${sanitise(applyFailure)} Owned-path cleanup also failed.`, {
                    cause: new AggregateError([applyFailure, cleanupFailure]),
                  });
                }
                throw cleanupFailure;
              }
            }
          }
        });
        assertCurrentAttempt(attempt, "applying");
        if (outcome.status === "promoted") {
          options.state.complete(attempt, `Source ${revision.slice(0, 12)} is active`);
        } else if (outcome.status === "rolled-back") {
          options.state.fail(
            attempt,
            "Source update failed after promotion; the last-known-good source was restored.",
          );
        }
        return options.state.getSnapshot();
      } catch (error) {
        return failAttempt(attempt, "applying", signal, "update-apply", error);
      }
    });

  const recover = (externalSignal?: AbortSignal): Promise<PromotionOutcome> =>
    options.coordinator.run("startup-recovery", externalSignal, async (signal) => {
      const attempt = ++recoveryAttempt;
      try {
        return await withOperationLease("startup-recovery", signal, async () => {
          await recordRecovery(attempt, signal, {
            message: "Reconciling the source promotion journal",
            operation: "startup-recovery",
            phase: "recovery-started",
            promotionId: null,
            revision: null,
          });
          await options.operationLease.assertHeld();
          assertSignal(signal);
          await options.cleanup.validateRecovery();
          await options.operationLease.assertHeld();
          assertSignal(signal);
          const outcome = await options.promotion.recover();
          if (outcome.status === "idle") assertSignal(signal);
          if (outcome.status === "idle") {
            await recordAuthoritativeRecovery(attempt, {
              message: "Source promotion recovery completed with idle status",
              operation: "startup-recovery",
              phase: "recovery-complete",
              promotionId: null,
              revision: null,
            });
            await options.operationLease.assertHeld();
            assertSignal(signal);
            await options.cleanup.recover();
          } else {
            try {
              await recordAuthoritativeRecovery(attempt, {
                message: `Source promotion recovery replayed a ${outcome.status} outcome`,
                operation: "startup-recovery",
                phase: outcome.status,
                promotionId: outcome.promotionId,
                revision: null,
              });
              await options.promotion.acknowledge(outcome);
            } catch (error) {
              retainLiveBackendUntilProcessExit(
                "The recovered backend is live but its promotion journal could not be acknowledged; same-process recovery is blocked.",
                error,
              );
            }
            // The completed promotion is authoritative even when cancellation
            // arrives while its now-stale cleanup reservations are retired.
            await options.cleanup.recover();
          }
          return outcome;
        });
      } catch (error) {
        try {
          await recordAuthoritativeRecovery(attempt, {
            message: sanitise(error),
            operation: "startup-recovery",
            phase: "failed",
            promotionId: null,
            revision: null,
          });
        } catch {
          // Preserve the promotion/recovery error and never publish raw detail.
        }
        throw error;
      }
    });

  return {
    apply,
    cancel(kind): boolean {
      const active = options.coordinator.getSnapshot().active;
      const target = kind === "apply"
        ? "update-apply"
        : kind === "check"
          ? "update-check"
          : active === "update-apply" || active === "update-check"
            ? active
            : null;
      return target === null ? false : options.coordinator.cancelActive(target);
    },
    check,
    recover,
  };
}
