import { randomUUID } from "node:crypto"
import { constants } from "node:fs"
import { lstat, open, realpath, rename, unlink } from "node:fs/promises"
import path from "node:path"

import type { FileSystemIdentity } from "./bootstrap"
import { SourceOperationLeaseRetentionError, isSourceOperationLeaseRetentionError } from "./source-operation"

export const ACTIVE_SOURCE_NAME = "FlintTrade"
export const LAST_KNOWN_GOOD_NAME = "FlintTrade.last-known-good"
export const JOURNAL_NAME = ".flinttrade-source-promotion.json"
export const CANDIDATE_SOURCE_PREFIX = "FlintTrade.update-"
export const FAILED_SOURCE_PREFIX = "FlintTrade.failed-"
export const STALE_SOURCE_QUARANTINE_PREFIX = ".FlintTrade.stale-quarantine-"
export const CLEANUP_QUARANTINE_PREFIX = ".FlintTrade.cleanup-quarantine-"

const UUID_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
const CANDIDATE_NAME_PATTERN = new RegExp(`^${CANDIDATE_SOURCE_PREFIX}(${UUID_PATTERN})$`)
const QUARANTINE_NAME_PATTERN = new RegExp(`^${STALE_SOURCE_QUARANTINE_PREFIX}(${UUID_PATTERN})$`)
const DISPOSABLE_SOURCE_NAME_PATTERN = new RegExp(
  `^(?:${CANDIDATE_SOURCE_PREFIX}(${UUID_PATTERN})(?:\\.candidate-([1-9][0-9]*)(\\.unpack)?)?|source-update-(${UUID_PATTERN}))$`,
)
const CLEANUP_QUARANTINE_NAME_PATTERN = new RegExp(
  `^\\.FlintTrade\\.cleanup-quarantine-(?:candidate|isolation|staging-(?:candidate|unpack)-[1-9][0-9]*)-${UUID_PATTERN}$`,
)

const JOURNAL_PHASES = [
  "prepared",
  "prune-lkg-before",
  "prune-lkg-after",
  "active-to-lkg-before",
  "active-to-lkg-after",
  "candidate-to-active-before",
  "candidate-to-active-after",
  "promoted-boot-before",
  "promoted-boot-after",
  "failed-displacement-before",
  "failed-displacement-after",
  "lkg-rollback-before",
  "lkg-rollback-after",
  "rollback-boot-before",
  "rollback-boot-after",
  "completion-before",
  "outcome-pending",
] as const

type JournalPhase = (typeof JOURNAL_PHASES)[number]
type BootResult = "not-attempted" | "failed" | "succeeded"
type TerminalOutcome = "promoted" | "rolled-back"

export type PromotionBoundary =
  | "journal:prepared"
  | "prune-lkg:before"
  | "prune-lkg:mutated"
  | "prune-lkg:after"
  | "active-to-lkg:before"
  | "active-to-lkg:mutated"
  | "active-to-lkg:after"
  | "candidate-to-active:before"
  | "candidate-to-active:mutated"
  | "candidate-to-active:after"
  | "promoted-boot:before"
  | "promoted-boot:after"
  | "failed-displacement:before"
  | "failed-displacement:mutated"
  | "failed-displacement:after"
  | "lkg-rollback:before"
  | "lkg-rollback:mutated"
  | "lkg-rollback:after"
  | "rollback-boot:before"
  | "rollback-boot:after"
  | "completion:before"
  | "completion:after"

export const SUCCESS_CRASH_BOUNDARIES = [
  "journal:prepared",
  "prune-lkg:before",
  "prune-lkg:mutated",
  "prune-lkg:after",
  "active-to-lkg:before",
  "active-to-lkg:mutated",
  "active-to-lkg:after",
  "candidate-to-active:before",
  "candidate-to-active:mutated",
  "candidate-to-active:after",
  "promoted-boot:before",
  "promoted-boot:after",
  "completion:before",
  "completion:after",
] as const satisfies readonly PromotionBoundary[]

export const ROLLBACK_CRASH_BOUNDARIES = [
  "journal:prepared",
  "active-to-lkg:before",
  "active-to-lkg:mutated",
  "active-to-lkg:after",
  "candidate-to-active:before",
  "candidate-to-active:mutated",
  "candidate-to-active:after",
  "promoted-boot:before",
  "promoted-boot:after",
  "failed-displacement:before",
  "failed-displacement:mutated",
  "failed-displacement:after",
  "lkg-rollback:before",
  "lkg-rollback:mutated",
  "lkg-rollback:after",
  "rollback-boot:before",
  "rollback-boot:after",
  "completion:before",
  "completion:after",
] as const satisfies readonly PromotionBoundary[]

export interface DirectorySnapshot {
  canonicalPath: string
  dev: number
  ino: number
}

/**
 * Filesystem operations used by source promotion. Implementations must inspect
 * directories without following a final-component alias and must make
 * writeJournalAtomic durable before resolving. removeJournal acknowledges an
 * already-durable terminal event: it must reject before unlink on failure, but
 * must not reject after unlink has succeeded. An unflushed deletion can only
 * resurrect a recoverable outcome-pending journal after a crash.
 */
export interface SourcePromotionFileSystem {
  inspectDirectory(target: string): Promise<DirectorySnapshot | null>
  readJournal(target: string): Promise<string | null>
  writeJournalAtomic(target: string, contents: string): Promise<void>
  removeJournal(target: string): Promise<void>
  renameDirectory(source: string, destination: string, expected: DirectorySnapshot): Promise<void>
  removeDirectory(target: string, expected: DirectorySnapshot): Promise<void>
  quarantineAndRemoveDirectory(target: string, quarantine: string, expected: DirectorySnapshot): Promise<void>
  syncDirectory(target: string): Promise<void>
  delay(milliseconds: number): Promise<void>
}

export interface NodeSourcePromotionFileSystemOptions {
  platform?: NodeJS.Platform
  safeRemove?: (request: {
    expected: DirectorySnapshot
    quarantine: string
    target: string
  }) => Promise<void>
  testHooks?: {
    durability?: (
      event: "directory-sync-unavailable-windows" | "directory-synced" | "journal-file-synced",
      target: string,
    ) => void
    mutationProof?: (
      strategy: "posix-pinned-handle" | "windows-stable-stat",
      operation: "rename",
    ) => void
    adversarial?: (
      event: "rename-before-mutation" | "rename-after-mutation",
      paths: { destination: string; source: string },
    ) => Promise<void> | void
  }
}

export interface SourcePromotionLifecycle {
  /**
   * Report whether the long-lived lifecycle needed to validate and boot source
   * trees is available. Omission means available for compatibility with
   * contained test lifecycles.
   */
  isAvailable?(): boolean
  /**
   * Prove that the exact managed active path still has the opaque content
   * identity journalled for the tree which is about to execute. A false result
   * is a mismatch; an exception is a validation failure. Neither permits boot.
   */
  validateActiveContent(activePath: string, expectedContentIdentity: string): Promise<boolean>
  /**
   * Start and health-prove the exact active backend. An unhealthy result or
   * rejection is safe to act on only after synchronously publishing stopped
   * proof through onBackendStopped.
   */
  bootActive(input: {
    activePath: string
    onBackendStopped(): void
  }): Promise<boolean>
  /** Stop the just-booted active backend before any rollback mutation. */
  stopActive(activePath: string): Promise<void>
}

export interface SourcePromotionRequest {
  candidateContentIdentity: string
  candidateDirectoryIdentity: FileSystemIdentity
  candidatePath: string
  originalActiveContentIdentity: string
  originalActiveDirectoryIdentity: FileSystemIdentity
}

export interface SourcePromotionOptions {
  fileSystem: SourcePromotionFileSystem
  lifecycle: SourcePromotionLifecycle
  onBoundary?: (boundary: PromotionBoundary) => Promise<void> | void
  platform?: NodeJS.Platform
  retry?: {
    attempts?: number
    delayMs?: number
  }
  sourceRoot: string
}

export type CompletedPromotionOutcome =
  | {
      active: DirectorySnapshot
      lastKnownGood: DirectorySnapshot
      promotionId: string
      status: "promoted"
    }
  | {
      active: DirectorySnapshot
      failed: DirectorySnapshot
      promotionId: string
      status: "rolled-back"
    }

export type PromotionOutcome =
  | { status: "idle" }
  | CompletedPromotionOutcome

interface BoundIdentity {
  dev: number
  ino: number
}

interface PromotionJournal {
  candidate: BoundIdentity
  candidateContentIdentity: string
  candidateName: string
  failedName: string
  operationId: string
  originalActive: BoundIdentity
  originalActiveContentIdentity: string
  outcome: TerminalOutcome | null
  phase: JournalPhase
  promotedBoot: BootResult
  quarantineName: string
  rollbackBoot: BootResult
  schemaVersion: 3
  staleLastKnownGood: BoundIdentity | null
}

interface PromotionPaths {
  active: string
  candidate: string
  failed: string
  journal: string
  lastKnownGood: string
  quarantine: string
  root: string
}

interface RecoveryEvidence {
  active: DirectorySnapshot | null
  candidate: DirectorySnapshot | null
  failed: DirectorySnapshot | null
  lastKnownGood: DirectorySnapshot | null
  quarantine: DirectorySnapshot | null
}

type DestructiveStep = "active-to-lkg" | "candidate-to-active" | "failed-displacement" | "lkg-rollback" | "prune-lkg"

const PHASES = new Set<string>(JOURNAL_PHASES)
const BOOT_RESULTS = new Set<string>(["not-attempted", "failed", "succeeded"])
const WINDOWS_RETRIABLE_CODES = new Set(["EACCES", "EBUSY", "EPERM"])

export class SourcePromotionError extends Error {
  readonly code: string

  constructor(code: string, message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = "SourcePromotionError"
    this.code = code
  }
}

export function createSourcePromotion(options: SourcePromotionOptions) {
  return new SourcePromotionController(options)
}

class SourcePromotionController {
  readonly paths: Omit<PromotionPaths, "candidate" | "failed" | "quarantine">

  private readonly fileSystem: SourcePromotionFileSystem
  private readonly lifecycle: SourcePromotionLifecycle
  private readonly onBoundary: (boundary: PromotionBoundary) => Promise<void> | void
  private readonly platform: NodeJS.Platform
  private readonly retryAttempts: number
  private readonly retryDelayMs: number

  constructor(options: SourcePromotionOptions) {
    const root = path.resolve(options.sourceRoot)
    this.paths = {
      active: path.join(root, ACTIVE_SOURCE_NAME),
      journal: path.join(root, JOURNAL_NAME),
      lastKnownGood: path.join(root, LAST_KNOWN_GOOD_NAME),
      root,
    }
    this.fileSystem = options.fileSystem
    this.lifecycle = options.lifecycle
    this.onBoundary = options.onBoundary ?? (() => undefined)
    this.platform = options.platform ?? process.platform
    this.retryAttempts = positiveInteger(options.retry?.attempts, 3, "retry.attempts")
    this.retryDelayMs = nonNegativeInteger(options.retry?.delayMs, 25, "retry.delayMs")
  }

  /**
   * Fail before candidate staging or backend drain when this process cannot
   * provide the durability and lifecycle guarantees required by promotion.
   */
  assertReady(): void {
    this.requireSupportedDurability()
    this.requireLifecycleAvailable()
  }

  async promote(request: SourcePromotionRequest): Promise<PromotionOutcome> {
    this.assertReady()
    const paths = this.pathsForCandidate(request.candidatePath)
    const originalActiveContentIdentity = requireContentIdentity(
      request.originalActiveContentIdentity,
      "original active content identity",
    )
    const candidateContentIdentity = requireContentIdentity(
      request.candidateContentIdentity,
      "candidate content identity",
    )
    const originalActiveDirectoryIdentity = requireBoundIdentity(
      request.originalActiveDirectoryIdentity,
      "original active directory identity",
    )
    const candidateDirectoryIdentity = requireBoundIdentity(
      request.candidateDirectoryIdentity,
      "candidate directory identity",
    )
    if ((await this.fileSystem.readJournal(paths.journal)) !== null) {
      throw new SourcePromotionError(
        "RECOVERY_REQUIRED",
        `Promotion journal already exists at ${paths.journal}; recover it before starting another promotion`,
      )
    }

    const root = await this.requireManagedRoot()
    const originalActive = await this.requireDirectory(paths.active, root, "active source")
    const candidate = await this.requireDirectory(paths.candidate, root, "candidate source")
    if (!matches(originalActive, originalActiveDirectoryIdentity)) {
      throw new SourcePromotionError(
        "IDENTITY_MISMATCH",
        "The active source no longer has the directory identity validated before promotion",
      )
    }
    if (!matches(candidate, candidateDirectoryIdentity)) {
      throw new SourcePromotionError(
        "IDENTITY_MISMATCH",
        "The candidate source no longer has the directory identity captured during staging",
      )
    }
    this.assertDifferentIdentity(originalActive, candidate, "active source and candidate source")
    const staleLastKnownGood = await this.optionalDirectory(paths.lastKnownGood, root, "last-known-good source")
    if (staleLastKnownGood) {
      this.assertDifferentIdentity(originalActive, staleLastKnownGood, "active source and last-known-good source")
      this.assertDifferentIdentity(candidate, staleLastKnownGood, "candidate source and last-known-good source")
    }
    await this.requireMissing(paths.failed, root, "failed forensic destination")
    await this.requireMissing(paths.quarantine, root, "stale-source quarantine destination")

    const operationId = operationIdFromCandidateName(path.basename(paths.candidate))
    const journal: PromotionJournal = {
      candidate: identityOf(candidate),
      candidateContentIdentity,
      candidateName: path.basename(paths.candidate),
      failedName: path.basename(paths.failed),
      operationId,
      originalActive: identityOf(originalActive),
      originalActiveContentIdentity,
      outcome: null,
      phase: "prepared",
      promotedBoot: "not-attempted",
      quarantineName: path.basename(paths.quarantine),
      rollbackBoot: "not-attempted",
      schemaVersion: 3,
      staleLastKnownGood: staleLastKnownGood ? identityOf(staleLastKnownGood) : null,
    }

    await this.persist(journal)
    await this.reach("journal:prepared")

    if (staleLastKnownGood) {
      await this.pruneStaleLastKnownGood(paths, root, journal, originalActive, candidate, staleLastKnownGood)
    }
    await this.moveActiveToLastKnownGood(paths, root, journal, originalActive, candidate)
    await this.moveCandidateToActive(paths, root, journal, originalActive, candidate)
    return this.bootPromotedOrRollback(paths, root, journal)
  }

  async recover(): Promise<PromotionOutcome> {
    const contents = await this.fileSystem.readJournal(this.paths.journal)
    if (contents === null) return { status: "idle" }
    this.requireSupportedDurability()
    this.requireLifecycleAvailable()

    const journal = parseJournal(contents)
    const paths = this.pathsForJournal(journal)
    const root = await this.requireManagedRoot()
    const evidence = await this.collectRecoveryEvidence(paths, root, journal)

    if (journal.outcome !== null) {
      return this.captureCompletedOutcome(paths, root, journal, journal.outcome)
    }

    if (journal.promotedBoot === "failed") {
      if (
        matches(evidence.active, journal.candidate) &&
        matches(evidence.lastKnownGood, journal.originalActive) &&
        evidence.candidate === null &&
        evidence.failed === null &&
        evidence.quarantine === null
      ) {
        await this.displaceFailedPromotion(paths, root, journal)
        await this.restoreLastKnownGood(paths, root, journal)
        return this.bootRollback(paths, root, journal)
      }
      if (
        evidence.active === null &&
        matches(evidence.lastKnownGood, journal.originalActive) &&
        evidence.candidate === null &&
        matches(evidence.failed, journal.candidate) &&
        evidence.quarantine === null
      ) {
        await this.restoreLastKnownGood(paths, root, journal)
        return this.bootRollback(paths, root, journal)
      }
      if (
        matches(evidence.active, journal.originalActive) &&
        evidence.lastKnownGood === null &&
        evidence.candidate === null &&
        matches(evidence.failed, journal.candidate) &&
        evidence.quarantine === null
      ) {
        return this.bootRollback(paths, root, journal)
      }
      return this.ambiguous("A durably failed promoted candidate is not in a valid rollback arrangement")
    }

    if (matches(evidence.active, journal.originalActive) && matches(evidence.candidate, journal.candidate)) {
      if (evidence.failed) this.ambiguous("Failed evidence exists before the candidate has moved")
      const staleLastKnownGood = evidence.lastKnownGood ?? evidence.quarantine
      if (evidence.lastKnownGood && evidence.quarantine) {
        this.ambiguous("The stale last-known-good identity appears at both its role and quarantine paths")
      }
      if (staleLastKnownGood) {
        if (!journal.staleLastKnownGood || !matches(staleLastKnownGood, journal.staleLastKnownGood)) {
          this.ambiguous("The last-known-good path does not contain the journalled stale identity")
        }
        await this.pruneStaleLastKnownGood(
          paths,
          root,
          journal,
          evidence.active,
          evidence.candidate,
          staleLastKnownGood,
        )
      }
      await this.moveActiveToLastKnownGood(paths, root, journal, evidence.active, evidence.candidate)
      await this.moveCandidateToActive(paths, root, journal, evidence.active, evidence.candidate)
      return this.bootPromotedOrRollback(paths, root, journal)
    }

    if (
      evidence.active === null &&
      matches(evidence.lastKnownGood, journal.originalActive) &&
      matches(evidence.candidate, journal.candidate) &&
      evidence.failed === null &&
      evidence.quarantine === null
    ) {
      await this.moveCandidateToActive(paths, root, journal, evidence.lastKnownGood, evidence.candidate)
      return this.bootPromotedOrRollback(paths, root, journal)
    }

    if (
      matches(evidence.active, journal.candidate) &&
      matches(evidence.lastKnownGood, journal.originalActive) &&
      evidence.candidate === null &&
      evidence.failed === null &&
      evidence.quarantine === null
    ) {
      return this.bootPromotedOrRollback(paths, root, journal)
    }

    return this.ambiguous("Journalled source identities are not in a recoverable arrangement")
  }

  /**
   * Remove an outcome-pending journal only after its caller has durably
   * recorded the matching terminal event. Identity and operation checks make
   * stale or forged acknowledgements non-mutating.
   */
  async acknowledge(outcome: CompletedPromotionOutcome): Promise<void> {
    const promotionId = requireOperationId(outcome.promotionId, "promotion acknowledgement")
    const contents = await this.fileSystem.readJournal(this.paths.journal)
    if (contents === null) {
      throw new SourcePromotionError(
        "ACKNOWLEDGEMENT_STALE",
        `No pending promotion journal exists for acknowledgement ${promotionId}`,
      )
    }
    this.requireSupportedDurability()
    const journal = parseJournal(contents)
    if (journal.operationId !== promotionId || journal.outcome !== outcome.status || journal.phase !== "outcome-pending") {
      throw new SourcePromotionError(
        "ACKNOWLEDGEMENT_MISMATCH",
        "Promotion acknowledgement does not match the durable outcome-pending journal",
      )
    }
    const paths = this.pathsForJournal(journal)
    const root = await this.requireManagedRoot()
    await this.captureCompletedOutcome(paths, root, journal, journal.outcome)
    await this.fileSystem.removeJournal(this.paths.journal)
  }

  private pathsForCandidate(candidatePath: string): PromotionPaths {
    const resolvedCandidate = path.resolve(candidatePath)
    const candidateName = path.basename(resolvedCandidate)
    if (!sameCanonicalPath(path.dirname(resolvedCandidate), this.paths.root, this.platform) || !CANDIDATE_NAME_PATTERN.test(candidateName)) {
      throw new SourcePromotionError(
        "INVALID_CANDIDATE",
        `Candidate must be a UUID-named direct sibling under ${this.paths.root}`,
      )
    }
    const operationId = operationIdFromCandidateName(candidateName)
    return {
      ...this.paths,
      candidate: resolvedCandidate,
      failed: path.join(this.paths.root, `${FAILED_SOURCE_PREFIX}${operationId}`),
      quarantine: path.join(this.paths.root, `${STALE_SOURCE_QUARANTINE_PREFIX}${operationId}`),
    }
  }

  private pathsForJournal(journal: PromotionJournal): PromotionPaths {
    const candidate = path.join(this.paths.root, journal.candidateName)
    const failed = path.join(this.paths.root, journal.failedName)
    const quarantine = path.join(this.paths.root, journal.quarantineName)
    if (
      !sameCanonicalPath(path.dirname(candidate), this.paths.root, this.platform) ||
      !sameCanonicalPath(path.dirname(failed), this.paths.root, this.platform) ||
      !sameCanonicalPath(path.dirname(quarantine), this.paths.root, this.platform) ||
      journal.candidateName !== `${CANDIDATE_SOURCE_PREFIX}${journal.operationId}` ||
      journal.failedName !== `${FAILED_SOURCE_PREFIX}${journal.operationId}` ||
      journal.quarantineName !== `${STALE_SOURCE_QUARANTINE_PREFIX}${journal.operationId}`
    ) {
      throw new SourcePromotionError("INVALID_JOURNAL", "Journal contains an invalid source-directory name")
    }
    return { ...this.paths, candidate, failed, quarantine }
  }

  private async requireManagedRoot(): Promise<DirectorySnapshot> {
    const root = await this.fileSystem.inspectDirectory(this.paths.root)
    if (!root) throw new SourcePromotionError("SOURCE_ROOT_MISSING", `Managed source root is missing: ${this.paths.root}`)
    validateSnapshot(root, "managed source root")
    if (!sameCanonicalPath(root.canonicalPath, this.paths.root, this.platform)) {
      throw new SourcePromotionError("PATH_ALIAS", `Managed source root is not canonical: ${this.paths.root}`)
    }
    return root
  }

  private async optionalDirectory(
    target: string,
    root: DirectorySnapshot,
    label: string,
  ): Promise<DirectorySnapshot | null> {
    this.assertManagedPath(target)
    const snapshot = await this.fileSystem.inspectDirectory(target)
    if (!snapshot) return null
    validateSnapshot(snapshot, label)
    if (!sameCanonicalPath(snapshot.canonicalPath, target, this.platform)) {
      throw new SourcePromotionError("PATH_ALIAS", `${label} is not canonical at ${target}`)
    }
    if (snapshot.dev !== root.dev) {
      throw new SourcePromotionError("CROSS_DEVICE", `${label} is not on the managed source volume`)
    }
    return snapshot
  }

  private async requireDirectory(target: string, root: DirectorySnapshot, label: string): Promise<DirectorySnapshot> {
    const snapshot = await this.optionalDirectory(target, root, label)
    if (!snapshot) throw new SourcePromotionError("DIRECTORY_MISSING", `${label} is missing at ${target}`)
    return snapshot
  }

  private async requireExpected(
    target: string,
    root: DirectorySnapshot,
    expected: BoundIdentity,
    label: string,
  ): Promise<DirectorySnapshot> {
    const snapshot = await this.requireDirectory(target, root, label)
    if (!matches(snapshot, expected)) {
      throw new SourcePromotionError("IDENTITY_MISMATCH", `${label} changed identity at ${target}`)
    }
    return snapshot
  }

  private async requireMissing(target: string, root: DirectorySnapshot, label: string): Promise<void> {
    if (await this.optionalDirectory(target, root, label)) {
      throw new SourcePromotionError("DESTINATION_OCCUPIED", `${label} is already occupied at ${target}`)
    }
  }

  private assertDifferentIdentity(first: DirectorySnapshot, second: DirectorySnapshot, label: string): void {
    if (sameIdentity(first, second)) {
      throw new SourcePromotionError("IDENTITY_ALIAS", `${label} resolve to the same directory identity`)
    }
  }

  private async collectRecoveryEvidence(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
  ): Promise<RecoveryEvidence> {
    const active = await this.optionalDirectory(paths.active, root, "active source")
    const lastKnownGood = await this.optionalDirectory(paths.lastKnownGood, root, "last-known-good source")
    const candidate = await this.optionalDirectory(paths.candidate, root, "candidate source")
    const failed = await this.optionalDirectory(paths.failed, root, "failed forensic source")
    const quarantine = await this.optionalDirectory(paths.quarantine, root, "stale-source quarantine")

    this.requireAllowedIdentity(active, [journal.originalActive, journal.candidate], "active source")
    this.requireAllowedIdentity(
      lastKnownGood,
      journal.staleLastKnownGood ? [journal.originalActive, journal.staleLastKnownGood] : [journal.originalActive],
      "last-known-good source",
    )
    this.requireAllowedIdentity(candidate, [journal.candidate], "candidate source")
    this.requireAllowedIdentity(failed, [journal.candidate], "failed forensic source")
    this.requireAllowedIdentity(
      quarantine,
      journal.staleLastKnownGood ? [journal.staleLastKnownGood] : [],
      "stale-source quarantine",
    )

    const present = [active, lastKnownGood, candidate, failed, quarantine].filter(
      (snapshot): snapshot is DirectorySnapshot => snapshot !== null,
    )
    if (new Set(present.map(identityKey)).size !== present.length) {
      this.ambiguous("One directory identity appears at more than one managed role")
    }
    if (present.filter((snapshot) => matches(snapshot, journal.originalActive)).length !== 1) {
      this.ambiguous("The original active identity is missing or duplicated")
    }
    if (present.filter((snapshot) => matches(snapshot, journal.candidate)).length !== 1) {
      this.ambiguous("The candidate identity is missing or duplicated")
    }
    if (
      journal.staleLastKnownGood &&
      present.filter((snapshot) => matches(snapshot, journal.staleLastKnownGood!)).length > 1
    ) {
      this.ambiguous("The stale last-known-good identity is duplicated")
    }
    return { active, candidate, failed, lastKnownGood, quarantine }
  }

  private requireAllowedIdentity(
    snapshot: DirectorySnapshot | null,
    allowed: readonly BoundIdentity[],
    label: string,
  ): void {
    if (snapshot && !allowed.some((identity) => matches(snapshot, identity))) {
      this.ambiguous(`${label} contains an identity not bound by the journal`)
    }
  }

  private async pruneStaleLastKnownGood(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
    originalActive: DirectorySnapshot,
    candidate: DirectorySnapshot,
    staleLastKnownGood: DirectorySnapshot,
  ): Promise<void> {
    await this.destructive(
      journal,
      "prune-lkg",
      "prune-lkg-before",
      "prune-lkg-after",
      async () => {
        await this.requireExpected(paths.active, root, originalActive, "active source")
        await this.requireExpected(paths.candidate, root, candidate, "candidate source")
        const atRole = await this.optionalDirectory(paths.lastKnownGood, root, "stale last-known-good source")
        const atQuarantine = await this.optionalDirectory(paths.quarantine, root, "stale-source quarantine")
        if (atRole && atQuarantine) {
          throw new SourcePromotionError(
            "AMBIGUOUS_EVIDENCE",
            "The stale last-known-good source appears at both its role and quarantine paths",
          )
        }
        const current = atRole ?? atQuarantine
        if (!matches(current, staleLastKnownGood)) {
          throw new SourcePromotionError(
            "IDENTITY_MISMATCH",
            "The stale last-known-good source changed identity before quarantine removal",
          )
        }
      },
      () => this.removeExpected(paths.lastKnownGood, paths.quarantine, root, staleLastKnownGood),
    )
  }

  private async moveActiveToLastKnownGood(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
    originalActive: DirectorySnapshot,
    candidate: DirectorySnapshot,
  ): Promise<void> {
    await this.destructive(
      journal,
      "active-to-lkg",
      "active-to-lkg-before",
      "active-to-lkg-after",
      async () => {
        await this.requireExpected(paths.active, root, originalActive, "active source")
        await this.requireExpected(paths.candidate, root, candidate, "candidate source")
        await this.requireMissing(paths.lastKnownGood, root, "last-known-good destination")
      },
      () => this.renameExpected(paths.active, paths.lastKnownGood, root, originalActive),
    )
  }

  private async moveCandidateToActive(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
    originalActive: DirectorySnapshot,
    candidate: DirectorySnapshot,
  ): Promise<void> {
    await this.destructive(
      journal,
      "candidate-to-active",
      "candidate-to-active-before",
      "candidate-to-active-after",
      async () => {
        await this.requireExpected(paths.lastKnownGood, root, originalActive, "last-known-good source")
        await this.requireExpected(paths.candidate, root, candidate, "candidate source")
        await this.requireMissing(paths.active, root, "active destination")
      },
      () => this.renameExpected(paths.candidate, paths.active, root, candidate),
    )
  }

  private async bootPromotedOrRollback(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
  ): Promise<PromotionOutcome> {
    await this.requireExpected(paths.active, root, journal.candidate, "promoted active source")
    await this.requireExpected(paths.lastKnownGood, root, journal.originalActive, "last-known-good source")
    const promoted = await this.bootWithJournal(paths, journal, "promoted")
    if (promoted) {
      try {
        return await this.complete(journal, "promoted", async () => {
          const active = await this.requireExpected(paths.active, root, journal.candidate, "promoted active source")
          const lastKnownGood = await this.requireExpected(
            paths.lastKnownGood,
            root,
            journal.originalActive,
            "last-known-good source",
          )
          return { active, lastKnownGood, promotionId: journal.operationId, status: "promoted" }
        })
      } catch (error) {
        this.retainLiveBoot("promoted", error)
      }
    }

    await this.displaceFailedPromotion(paths, root, journal)
    await this.restoreLastKnownGood(paths, root, journal)
    return this.bootRollback(paths, root, journal)
  }

  private async displaceFailedPromotion(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
  ): Promise<void> {
    await this.destructive(
      journal,
      "failed-displacement",
      "failed-displacement-before",
      "failed-displacement-after",
      async () => {
        await this.requireExpected(paths.active, root, journal.candidate, "failed promoted source")
        await this.requireExpected(paths.lastKnownGood, root, journal.originalActive, "last-known-good source")
        await this.requireMissing(paths.failed, root, "failed forensic destination")
      },
      () => this.renameExpected(paths.active, paths.failed, root, journal.candidate),
    )
  }

  private async restoreLastKnownGood(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
  ): Promise<void> {
    await this.destructive(
      journal,
      "lkg-rollback",
      "lkg-rollback-before",
      "lkg-rollback-after",
      async () => {
        await this.requireExpected(paths.lastKnownGood, root, journal.originalActive, "last-known-good source")
        await this.requireExpected(paths.failed, root, journal.candidate, "failed forensic source")
        await this.requireMissing(paths.active, root, "active rollback destination")
      },
      () => this.renameExpected(paths.lastKnownGood, paths.active, root, journal.originalActive),
    )
  }

  private async bootRollback(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
  ): Promise<PromotionOutcome> {
    await this.requireExpected(paths.active, root, journal.originalActive, "rolled-back active source")
    await this.requireExpected(paths.failed, root, journal.candidate, "failed forensic source")
    const rolledBack = await this.bootWithJournal(paths, journal, "rollback")
    if (!rolledBack) {
      throw new SourcePromotionError(
        "ROLLBACK_BOOT_FAILED",
        `The promoted source and restored last-known-good source both failed to boot; evidence is retained under ${paths.root}`,
      )
    }
    try {
      return await this.complete(journal, "rolled-back", async () => {
        const active = await this.requireExpected(paths.active, root, journal.originalActive, "rolled-back active source")
        const failed = await this.requireExpected(paths.failed, root, journal.candidate, "failed forensic source")
        return { active, failed, promotionId: journal.operationId, status: "rolled-back" }
      })
    } catch (error) {
      this.retainLiveBoot("rollback", error)
    }
  }

  private retainLiveBoot(kind: "promoted" | "rollback", error: unknown): never {
    if (isSourceOperationLeaseRetentionError(error) && error.retentionPolicy === "process-exit-required") throw error
    throw new SourceOperationLeaseRetentionError(
      `The ${kind} backend is live but promotion finalisation failed; same-process recovery is blocked`,
      { cause: error, retentionPolicy: "process-exit-required" },
    )
  }

  private async bootWithJournal(
    paths: PromotionPaths,
    journal: PromotionJournal,
    kind: "promoted" | "rollback",
  ): Promise<boolean> {
    const beforePhase = kind === "promoted" ? "promoted-boot-before" : "rollback-boot-before"
    const afterPhase = kind === "promoted" ? "promoted-boot-after" : "rollback-boot-after"
    const beforeBoundary = kind === "promoted" ? "promoted-boot:before" : "rollback-boot:before"
    const afterBoundary = kind === "promoted" ? "promoted-boot:after" : "rollback-boot:after"
    const expectedContentIdentity =
      kind === "promoted" ? journal.candidateContentIdentity : journal.originalActiveContentIdentity
    await this.persist(journal, beforePhase)
    await this.reach(beforeBoundary)
    try {
      await this.validateActiveContent(paths.active, expectedContentIdentity, kind)
    } catch (error) {
      if (isSourceOperationLeaseRetentionError(error)) throw error
      if (kind === "promoted") journal.promotedBoot = "failed"
      else journal.rollbackBoot = "failed"
      await this.persist(journal, afterPhase)
      await this.reach(afterBoundary)
      if (kind === "promoted") return false
      throw error
    }
    let succeeded = false
    let backendStopped = false
    let postBootValidationFailure: unknown
    try {
      succeeded = await this.lifecycle.bootActive({
        activePath: paths.active,
        onBackendStopped: () => {
          if (backendStopped) throw new Error(`The ${kind} backend reported duplicate stopped proof`)
          backendStopped = true
        },
      })
    } catch (error) {
      if (isSourceOperationLeaseRetentionError(error)) {
        if (backendStopped) throw error
        this.retainLiveBoot(kind, error)
      }
      if (!backendStopped) {
        throw new SourceOperationLeaseRetentionError(
          `The ${kind} backend boot rejected without proving that its process stopped`,
          { cause: error, retentionPolicy: "process-exit-required" },
        )
      }
      succeeded = false
    }
    if (succeeded && backendStopped) {
      succeeded = false
      postBootValidationFailure = new SourcePromotionError(
        "INVALID_LIFECYCLE_PROOF",
        `The ${kind} backend reported both live readiness and stopped proof`,
      )
    }
    if (!succeeded && !backendStopped) {
      throw new SourceOperationLeaseRetentionError(
        `The ${kind} backend was unhealthy without proving that its process stopped`,
        { retentionPolicy: "process-exit-required" },
      )
    }
    if (succeeded) {
      try {
        await this.validateActiveContent(paths.active, expectedContentIdentity, kind)
      } catch (error) {
        if (isSourceOperationLeaseRetentionError(error)) this.retainLiveBoot(kind, error)
        try {
          await this.lifecycle.stopActive(paths.active)
        } catch (stopFailure) {
          throw new SourceOperationLeaseRetentionError(
            `The ${kind} backend source changed after boot and backend containment could not be re-proven; recovery mutation is blocked`,
            {
              cause: new AggregateError(
                [error, stopFailure],
                `The ${kind} backend source changed after boot and the backend could not be stopped safely`,
              ),
              retentionPolicy: "process-exit-required",
            },
          )
        }
        backendStopped = true
        succeeded = false
        postBootValidationFailure = error
      }
    }
    if (kind === "promoted") journal.promotedBoot = succeeded ? "succeeded" : "failed"
    else journal.rollbackBoot = succeeded ? "succeeded" : "failed"
    try {
      await this.persist(journal, afterPhase)
      await this.reach(afterBoundary)
    } catch (error) {
      if (!succeeded) throw error
      this.retainLiveBoot(kind, error)
    }
    if (postBootValidationFailure !== undefined && kind === "rollback") {
      throw postBootValidationFailure
    }
    return succeeded
  }

  private async validateActiveContent(
    activePath: string,
    expectedContentIdentity: string,
    kind: "promoted" | "rollback",
  ): Promise<void> {
    let valid: boolean
    try {
      valid = await this.lifecycle.validateActiveContent(activePath, expectedContentIdentity)
    } catch (error) {
      if (isSourceOperationLeaseRetentionError(error)) throw error
      throw new SourcePromotionError(
        "CONTENT_IDENTITY_VALIDATION_FAILED",
        `Could not validate the ${kind} active source content identity; the journal and source evidence are retained`,
        { cause: error },
      )
    }
    if (!valid) {
      throw new SourcePromotionError(
        "CONTENT_IDENTITY_MISMATCH",
        `The ${kind} active source does not match its journalled content identity; the journal and source evidence are retained`,
      )
    }
  }

  private async destructive(
    journal: PromotionJournal,
    step: DestructiveStep,
    beforePhase: JournalPhase,
    afterPhase: JournalPhase,
    validate: () => Promise<void>,
    mutate: () => Promise<void>,
  ): Promise<void> {
    await this.persist(journal, beforePhase)
    await this.reach(`${step}:before`)
    await validate()
    await mutate()
    await this.fileSystem.syncDirectory(this.paths.root)
    await this.reach(`${step}:mutated`)
    await this.persist(journal, afterPhase)
    await this.reach(`${step}:after`)
  }

  private async complete<Outcome extends CompletedPromotionOutcome>(
    journal: PromotionJournal,
    status: TerminalOutcome,
    captureOutcome: () => Promise<Outcome>,
  ): Promise<Outcome> {
    await this.persist(journal, "completion-before")
    await this.reach("completion:before")
    await this.fileSystem.syncDirectory(this.paths.root)
    const outcome = await captureOutcome()
    journal.outcome = status
    await this.persist(journal, "outcome-pending")
    await this.reach("completion:after")
    return outcome
  }

  private async captureCompletedOutcome(
    paths: PromotionPaths,
    root: DirectorySnapshot,
    journal: PromotionJournal,
    status: TerminalOutcome,
  ): Promise<CompletedPromotionOutcome> {
    if (journal.phase !== "outcome-pending") {
      throw new SourcePromotionError("INVALID_JOURNAL", "A terminal promotion outcome is not outcome-pending")
    }
    if (status === "promoted") {
      const active = await this.requireExpected(paths.active, root, journal.candidate, "promoted active source")
      const lastKnownGood = await this.requireExpected(
        paths.lastKnownGood,
        root,
        journal.originalActive,
        "last-known-good source",
      )
      await this.requireMissing(paths.candidate, root, "candidate source")
      await this.requireMissing(paths.failed, root, "failed forensic source")
      await this.requireMissing(paths.quarantine, root, "stale-source quarantine")
      return { active, lastKnownGood, promotionId: journal.operationId, status }
    }

    const active = await this.requireExpected(paths.active, root, journal.originalActive, "rolled-back active source")
    const failed = await this.requireExpected(paths.failed, root, journal.candidate, "failed forensic source")
    await this.requireMissing(paths.candidate, root, "candidate source")
    await this.requireMissing(paths.lastKnownGood, root, "last-known-good source")
    await this.requireMissing(paths.quarantine, root, "stale-source quarantine")
    return { active, failed, promotionId: journal.operationId, status }
  }

  private async persist(journal: PromotionJournal, phase?: JournalPhase): Promise<void> {
    if (phase) journal.phase = phase
    await this.fileSystem.writeJournalAtomic(this.paths.journal, `${JSON.stringify(journal)}\n`)
    await this.fileSystem.syncDirectory(this.paths.root)
  }

  private async renameExpected(
    source: string,
    destination: string,
    root: DirectorySnapshot,
    expected: BoundIdentity,
  ): Promise<void> {
    this.assertManagedPath(source)
    this.assertManagedPath(destination)
    for (let attempt = 1; attempt <= this.retryAttempts; attempt += 1) {
      await this.requireExpected(source, root, expected, "rename source")
      await this.requireMissing(destination, root, "rename destination")
      try {
        await this.fileSystem.renameDirectory(source, destination, {
          canonicalPath: source,
          dev: expected.dev,
          ino: expected.ino,
        })
        return
      } catch (error) {
        if (!this.isRetriableWindowsError(error) || attempt === this.retryAttempts) {
          throw new SourcePromotionError(
            "RENAME_FAILED",
            `Could not rename ${source} to ${destination} after ${attempt} attempt(s)`,
            { cause: error },
          )
        }
        const sourceAfter = await this.optionalDirectory(source, root, "rename source")
        const destinationAfter = await this.optionalDirectory(destination, root, "rename destination")
        if (!sourceAfter && matches(destinationAfter, expected)) return
        if (!matches(sourceAfter, expected) || destinationAfter) {
          throw new SourcePromotionError(
            "AMBIGUOUS_EVIDENCE",
            `Rename outcome is ambiguous for ${source} and ${destination}`,
            { cause: error },
          )
        }
        await this.fileSystem.delay(this.retryDelayMs)
      }
    }
  }

  private async removeExpected(
    target: string,
    quarantine: string,
    root: DirectorySnapshot,
    expected: DirectorySnapshot,
  ): Promise<void> {
    this.assertManagedPath(target)
    this.assertManagedPath(quarantine)
    for (let attempt = 1; attempt <= this.retryAttempts; attempt += 1) {
      const atTarget = await this.optionalDirectory(target, root, "stale last-known-good source")
      const atQuarantine = await this.optionalDirectory(quarantine, root, "stale-source quarantine")
      if (atTarget && atQuarantine) {
        throw new SourcePromotionError(
          "AMBIGUOUS_EVIDENCE",
          "Stale last-known-good evidence exists at both its role and quarantine paths",
        )
      }
      const current = atTarget ?? atQuarantine
      if (!matches(current, expected)) {
        throw new SourcePromotionError(
          "IDENTITY_MISMATCH",
          "Stale last-known-good identity changed before quarantine removal",
        )
      }
      try {
        await this.fileSystem.quarantineAndRemoveDirectory(target, quarantine, current)
        return
      } catch (error) {
        if (isSourceOperationLeaseRetentionError(error)) throw error
        if (!this.isRetriableWindowsError(error) || attempt === this.retryAttempts) {
          throw new SourcePromotionError(
            "REMOVE_FAILED",
            `Could not remove stale last-known-good source after ${attempt} attempt(s)`,
            { cause: error },
          )
        }
        const targetAfter = await this.optionalDirectory(target, root, "stale last-known-good source")
        const quarantineAfter = await this.optionalDirectory(quarantine, root, "stale-source quarantine")
        if (!targetAfter && !quarantineAfter) return
        if (
          (targetAfter && quarantineAfter) ||
          !matches(targetAfter ?? quarantineAfter, expected)
        ) {
          throw new SourcePromotionError("AMBIGUOUS_EVIDENCE", "Stale last-known-good identity changed during removal")
        }
        await this.fileSystem.delay(this.retryDelayMs)
      }
    }
  }

  private isRetriableWindowsError(error: unknown): boolean {
    return (
      this.platform === "win32" &&
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      typeof error.code === "string" &&
      WINDOWS_RETRIABLE_CODES.has(error.code)
    )
  }

  private requireSupportedDurability(): void {
    if (this.platform === "win32") {
      throw new SourcePromotionError(
        "UNSUPPORTED_DURABILITY",
        "Source promotion is disabled on Windows because Node cannot durably flush directory-entry mutations",
      )
    }
  }

  private requireLifecycleAvailable(): void {
    let available: boolean
    try {
      available = this.lifecycle.isAvailable?.() ?? true
    } catch (error) {
      throw new SourcePromotionError(
        "LIFECYCLE_UNAVAILABLE",
        "Could not prove that the source-promotion lifecycle is available",
        { cause: error },
      )
    }
    if (!available) {
      throw new SourcePromotionError(
        "LIFECYCLE_UNAVAILABLE",
        "Source promotion requires an available long-lived backend lifecycle",
      )
    }
  }

  private assertManagedPath(target: string): void {
    const resolved = path.resolve(target)
    const name = path.basename(resolved)
    const allowed =
      name === ACTIVE_SOURCE_NAME ||
      name === LAST_KNOWN_GOOD_NAME ||
      name === JOURNAL_NAME ||
      CANDIDATE_NAME_PATTERN.test(name) ||
      QUARANTINE_NAME_PATTERN.test(name) ||
      new RegExp(`^${FAILED_SOURCE_PREFIX}${UUID_PATTERN}$`).test(name)
    if (!sameCanonicalPath(path.dirname(resolved), this.paths.root, this.platform) || !allowed) {
      throw new SourcePromotionError("PATH_OUTSIDE_SOURCE_ROOT", `Refusing mutation outside the managed source root: ${target}`)
    }
  }

  private async reach(boundary: PromotionBoundary): Promise<void> {
    await this.onBoundary(boundary)
  }

  private ambiguous(message: string): never {
    throw new SourcePromotionError("AMBIGUOUS_EVIDENCE", `${message}; no recovery mutation was attempted`)
  }
}

const MAX_JOURNAL_BYTES = 128 * 1024
const MAX_CONTENT_IDENTITY_BYTES = 8 * 1024

/**
 * Production filesystem boundary for source promotion. It rejects final-path
 * links and unstable identities, durably replaces the journal through a
 * same-directory temporary file, and verifies directory identities on both
 * sides of every rename/remove operation.
 */
export function createNodeSourcePromotionFileSystem(
  options: NodeSourcePromotionFileSystemOptions = {},
): SourcePromotionFileSystem {
  const platform = options.platform ?? process.platform
  const durability = options.testHooks?.durability ?? (() => undefined)
  const mutationProof = options.testHooks?.mutationProof ?? (() => undefined)
  const adversarial = options.testHooks?.adversarial ?? (() => undefined)

  const noFollowOpenFlags = (base: number, directory = false): number => {
    if (platform === "win32") return base
    return base | constants.O_NOFOLLOW | (directory ? constants.O_DIRECTORY : 0)
  }

  const missing = (error: unknown): boolean =>
    error instanceof Error && "code" in error && (error as NodeJS.ErrnoException).code === "ENOENT"

  const stableLstat = async (target: string, kind: "directory" | "journal"): Promise<Awaited<ReturnType<typeof lstat>>> => {
    const first = await lstat(target)
    if (first.isSymbolicLink()) throw new Error(`Refusing a symbolic-link ${kind} path: ${target}`)
    if (kind === "directory" ? !first.isDirectory() : !first.isFile()) {
      throw new Error(`Expected a no-follow ${kind} path: ${target}`)
    }
    const second = await lstat(target)
    if (
      second.isSymbolicLink() ||
      (kind === "directory" ? !second.isDirectory() : !second.isFile()) ||
      first.dev !== second.dev ||
      first.ino !== second.ino
    ) {
      throw new Error(`${kind} identity changed during no-follow inspection: ${target}`)
    }
    return second
  }

  const inspectDirectory = async (target: string): Promise<DirectorySnapshot | null> => {
    let metadata: Awaited<ReturnType<typeof lstat>>
    try {
      metadata = await stableLstat(target, "directory")
    } catch (error) {
      if (missing(error)) return null
      throw error
    }
    const canonicalPath = await realpath(target)
    const finalMetadata = await stableLstat(target, "directory")
    if (metadata.dev !== finalMetadata.dev || metadata.ino !== finalMetadata.ino) {
      throw new Error(`Directory identity changed while resolving its canonical path: ${target}`)
    }
    return { canonicalPath, dev: Number(metadata.dev), ino: Number(metadata.ino) }
  }

  const syncDirectory = async (target: string): Promise<void> => {
    const expected = await inspectDirectory(target)
    if (!expected) throw new Error(`Cannot durably sync a missing directory: ${target}`)
    if (platform === "win32") {
      // Node does not expose a supported durable directory flush on Windows.
      // Journal file contents are flushed before replacement; recovery remains
      // evidence-driven, but callers must not claim power-loss directory-sync proof.
      durability("directory-sync-unavailable-windows", target)
      return
    }
    const handle = await open(target, noFollowOpenFlags(constants.O_RDONLY, true))
    try {
      const opened = await handle.stat()
      if (!opened.isDirectory() || opened.dev !== expected.dev || opened.ino !== expected.ino) {
        throw new Error(`Directory identity changed before durable sync: ${target}`)
      }
      await handle.sync()
      durability("directory-synced", target)
    } finally {
      await handle.close()
    }
  }

  const readJournal = async (target: string): Promise<string | null> => {
    let expected: Awaited<ReturnType<typeof lstat>>
    try {
      expected = await stableLstat(target, "journal")
    } catch (error) {
      if (missing(error)) return null
      throw error
    }
    if (expected.size > MAX_JOURNAL_BYTES) throw new Error(`Promotion journal exceeds ${MAX_JOURNAL_BYTES} bytes`)
    const handle = await open(target, noFollowOpenFlags(constants.O_RDONLY))
    try {
      const opened = await handle.stat()
      if (!opened.isFile() || opened.dev !== expected.dev || opened.ino !== expected.ino) {
        throw new Error(`Promotion journal identity changed before read: ${target}`)
      }
      const contents = await handle.readFile({ encoding: "utf8" })
      const finalMetadata = await stableLstat(target, "journal")
      if (finalMetadata.dev !== opened.dev || finalMetadata.ino !== opened.ino) {
        throw new Error(`Promotion journal identity changed during read: ${target}`)
      }
      return contents
    } finally {
      await handle.close()
    }
  }

  const writeJournalAtomic = async (target: string, contents: string): Promise<void> => {
    if (Buffer.byteLength(contents) > MAX_JOURNAL_BYTES) {
      throw new Error(`Promotion journal exceeds ${MAX_JOURNAL_BYTES} bytes`)
    }
    try {
      await stableLstat(target, "journal")
    } catch (error) {
      if (!missing(error)) throw error
    }
    const parent = path.dirname(target)
    const temporary = path.join(parent, `.${path.basename(target)}.${randomUUID()}.tmp`)
    const handle = await open(temporary, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY, 0o600)
    let renamed = false
    try {
      await handle.writeFile(contents, { encoding: "utf8" })
      await handle.sync()
      durability("journal-file-synced", temporary)
      await handle.close()
      await rename(temporary, target)
      renamed = true
      await stableLstat(target, "journal")
      await syncDirectory(parent)
    } finally {
      if (!renamed) {
        await handle.close().catch(() => undefined)
        await unlink(temporary).catch((error: unknown) => {
          if (!missing(error)) throw error
        })
      }
    }
  }

  const removeJournal = async (target: string): Promise<void> => {
    const expected = await stableLstat(target, "journal")
    const handle = await open(target, noFollowOpenFlags(constants.O_RDONLY))
    let removed = false
    try {
      const opened = await handle.stat()
      const finalMetadata = await stableLstat(target, "journal")
      if (
        !opened.isFile() ||
        opened.dev !== expected.dev ||
        opened.ino !== expected.ino ||
        finalMetadata.dev !== opened.dev ||
        finalMetadata.ino !== opened.ino
      ) {
        throw new Error(`Promotion journal identity changed before removal: ${target}`)
      }
      await unlink(target)
      removed = true
    } finally {
      if (removed) await handle.close().catch(() => undefined)
      else await handle.close()
    }
    try {
      await syncDirectory(path.dirname(target))
    } catch {
      // Unlink is the completion commit point. If this directory flush did not
      // become durable, a crash may resurrect the completion-before journal;
      // recovery can safely validate and complete that outcome again.
    }
  }

  const renameDirectory = async (
    source: string,
    destination: string,
    expected: DirectorySnapshot,
  ): Promise<void> => {
    const sourceBefore = await inspectDirectory(source)
    if (!sourceBefore || !sameIdentity(sourceBefore, expected)) {
      throw new Error(`Rename source identity does not match the journalled directory: ${source}`)
    }
    if (await inspectDirectory(destination)) throw new Error(`Rename destination already exists: ${destination}`)

    const restoreUnexpectedDestination = async (observed: DirectorySnapshot | null): Promise<void> => {
      if (!observed) return
      const [sourceNow, destinationNow] = await Promise.all([
        inspectDirectory(source),
        inspectDirectory(destination),
      ])
      if (sourceNow || !destinationNow || !sameIdentity(destinationNow, observed)) return
      try {
        await rename(destination, source)
        const [restored, destinationAfterRestore] = await Promise.all([
          inspectDirectory(source),
          inspectDirectory(destination),
        ])
        if (!restored || !sameIdentity(restored, observed) || destinationAfterRestore) {
          throw new Error("restored path did not retain the observed identity")
        }
        await syncDirectory(path.dirname(source))
      } catch (error) {
        throw new Error(
          `Rename identity mismatch could not be safely restored; evidence is preserved at ${source} and ${destination}`,
          { cause: error },
        )
      }
    }

    if (platform === "win32") {
      // Holding a directory handle across MoveFileEx can itself cause a sharing
      // violation. Recheck the no-follow identity immediately before rename and
      // prove the moved identity afterwards; the controller supplies bounded
      // EPERM/EACCES/EBUSY retries without remove-around-rename.
      const immediatelyBefore = await inspectDirectory(source)
      if (!immediatelyBefore || !sameIdentity(immediatelyBefore, expected)) {
        throw new Error(`Rename source identity changed before mutation: ${source}`)
      }
      await adversarial("rename-before-mutation", { destination, source })
      const [sourceAtMutation, destinationAtMutation] = await Promise.all([
        inspectDirectory(source),
        inspectDirectory(destination),
      ])
      if (!sourceAtMutation || !sameIdentity(sourceAtMutation, expected) || destinationAtMutation) {
        throw new Error(`Rename paths changed immediately before mutation: ${source}`)
      }
      mutationProof("windows-stable-stat", "rename")
      await rename(source, destination)
      await adversarial("rename-after-mutation", { destination, source })
      const [sourceAfter, destinationAfter] = await Promise.all([
        inspectDirectory(source),
        inspectDirectory(destination),
      ])
      if (
        sourceAfter ||
        !destinationAfter ||
        !sameIdentity(destinationAfter, expected)
      ) {
        await restoreUnexpectedDestination(destinationAfter)
        throw new Error(`Rename result does not preserve the expected directory identity: ${source}`)
      }
      return
    }

    const handle = await open(source, noFollowOpenFlags(constants.O_RDONLY, true))
    try {
      const opened = await handle.stat()
      if (!opened.isDirectory() || opened.dev !== expected.dev || opened.ino !== expected.ino) {
        throw new Error(`Rename source identity changed before mutation: ${source}`)
      }
      await adversarial("rename-before-mutation", { destination, source })
      const [sourceAtMutation, destinationAtMutation] = await Promise.all([
        inspectDirectory(source),
        inspectDirectory(destination),
      ])
      if (!sourceAtMutation || !sameIdentity(sourceAtMutation, expected) || destinationAtMutation) {
        throw new Error(`Rename paths changed immediately before mutation: ${source}`)
      }
      mutationProof("posix-pinned-handle", "rename")
      await rename(source, destination)
      await adversarial("rename-after-mutation", { destination, source })
      const [sourceAfter, destinationAfter, pinnedAfter] = await Promise.all([
        inspectDirectory(source),
        inspectDirectory(destination),
        handle.stat(),
      ])
      if (
        sourceAfter ||
        !destinationAfter ||
        !sameIdentity(destinationAfter, expected) ||
        pinnedAfter.dev !== expected.dev ||
        pinnedAfter.ino !== expected.ino
      ) {
        await restoreUnexpectedDestination(destinationAfter)
        throw new Error(`Rename result does not preserve the expected directory identity: ${source}`)
      }
    } finally {
      await handle.close()
    }
  }

  const quarantineAndRemoveDirectory = async (
    target: string,
    quarantine: string,
    expected: DirectorySnapshot,
  ): Promise<void> => {
    const parent = path.dirname(target)
    if (
      path.dirname(quarantine) !== parent ||
      (
        !QUARANTINE_NAME_PATTERN.test(path.basename(quarantine)) &&
        !CLEANUP_QUARANTINE_NAME_PATTERN.test(path.basename(quarantine))
      ) ||
      target === quarantine
    ) {
      throw new Error(`Removal quarantine is not a unique confined sibling of ${target}`)
    }
    const [targetBefore, quarantineBefore] = await Promise.all([
      inspectDirectory(target),
      inspectDirectory(quarantine),
    ])
    if (targetBefore && quarantineBefore) {
      throw new Error(`Removal evidence exists at both ${target} and ${quarantine}`)
    }
    if (targetBefore && !sameIdentity(targetBefore, expected)) {
      throw new Error(`Removal target identity does not match the journalled directory: ${target}`)
    }
    if (quarantineBefore && !sameIdentity(quarantineBefore, expected)) {
      throw new Error(`Removal quarantine identity does not match the journalled directory: ${quarantine}`)
    }
    if (!targetBefore && !quarantineBefore) {
      throw new Error(`Removal target and quarantine are both missing: ${target}`)
    }
    if (!options.safeRemove) {
      throw new Error("Identity-bound directory deletion requires the managed safe-removal helper.")
    }
    await options.safeRemove({ expected, quarantine, target })
    const [targetAfter, quarantineAfter] = await Promise.all([
      inspectDirectory(target),
      inspectDirectory(quarantine),
    ])
    if (targetAfter || quarantineAfter) {
      throw new Error("Managed safe-removal helper returned before both confined directory names were absent.")
    }
    await syncDirectory(parent)
  }

  const removeDirectory = async (target: string, expected: DirectorySnapshot): Promise<void> => {
    const match = DISPOSABLE_SOURCE_NAME_PATTERN.exec(path.basename(target))
    if (!match) {
      throw new Error("Managed directory cleanup requires a UUID-bound candidate or health-isolation name.")
    }
    const operationId = (match[1] ?? match[4])?.toLowerCase()
    if (!operationId) throw new Error("Managed directory cleanup path is missing its UUID identity.")
    const kind = match[4]
      ? "isolation"
      : match[2]
        ? `staging-${match[3] ? "unpack" : "candidate"}-${match[2]}`
        : "candidate"
    const quarantine = path.join(
      path.dirname(target),
      `${CLEANUP_QUARANTINE_PREFIX}${kind}-${operationId}`,
    )
    const [targetBefore, quarantineBefore] = await Promise.all([
      inspectDirectory(target),
      inspectDirectory(quarantine),
    ])
    // A retry after a helper completed but before the caller observed success
    // is idempotent. A helper interrupted after quarantine rename resumes from
    // the same UUID-derived name instead of leaking an untracked random tree.
    if (!targetBefore && !quarantineBefore) return
    await quarantineAndRemoveDirectory(target, quarantine, expected)
  }

  return {
    delay: (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
    inspectDirectory,
    quarantineAndRemoveDirectory,
    readJournal,
    removeDirectory,
    removeJournal,
    renameDirectory,
    syncDirectory,
    writeJournalAtomic,
  }
}

function parseJournal(contents: string): PromotionJournal {
  let value: unknown
  try {
    value = JSON.parse(contents)
  } catch (error) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal is not valid JSON", { cause: error })
  }
  if (!isRecord(value)) throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal must be an object")

  const operationId = value.operationId
  const candidateName = value.candidateName
  const failedName = value.failedName
  const quarantineName = value.quarantineName
  const phase = value.phase
  const promotedBoot = value.promotedBoot
  const rollbackBoot = value.rollbackBoot
  const outcome = value.outcome
  if (
    value.schemaVersion !== 3 ||
    typeof operationId !== "string" ||
    !new RegExp(`^${UUID_PATTERN}$`).test(operationId) ||
    candidateName !== `${CANDIDATE_SOURCE_PREFIX}${operationId}` ||
    failedName !== `${FAILED_SOURCE_PREFIX}${operationId}` ||
    quarantineName !== `${STALE_SOURCE_QUARANTINE_PREFIX}${operationId}` ||
    typeof phase !== "string" ||
    !PHASES.has(phase) ||
    typeof promotedBoot !== "string" ||
    !BOOT_RESULTS.has(promotedBoot) ||
    typeof rollbackBoot !== "string" ||
    !BOOT_RESULTS.has(rollbackBoot) ||
    !(outcome === null || outcome === "promoted" || outcome === "rolled-back") ||
    !isContentIdentity(value.originalActiveContentIdentity) ||
    !isContentIdentity(value.candidateContentIdentity) ||
    !isIdentity(value.originalActive) ||
    !isIdentity(value.candidate) ||
    !(value.staleLastKnownGood === null || isIdentity(value.staleLastKnownGood))
  ) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal has an invalid schema")
  }

  const journal = value as unknown as PromotionJournal
  if (sameIdentity(journal.originalActive, journal.candidate)) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal aliases active and candidate identities")
  }
  if (
    journal.staleLastKnownGood &&
    (sameIdentity(journal.staleLastKnownGood, journal.originalActive) ||
      sameIdentity(journal.staleLastKnownGood, journal.candidate))
  ) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal aliases the stale last-known-good identity")
  }
  if (journal.rollbackBoot !== "not-attempted" && journal.promotedBoot !== "failed") {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal records rollback without a promoted boot failure")
  }
  if ((journal.phase === "outcome-pending") !== (journal.outcome !== null)) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promotion journal has an inconsistent terminal outcome phase")
  }
  if (journal.outcome === "promoted" && journal.promotedBoot !== "succeeded") {
    throw new SourcePromotionError("INVALID_JOURNAL", "Promoted outcome is not backed by a successful promoted boot")
  }
  if (
    journal.outcome === "rolled-back" &&
    (journal.promotedBoot !== "failed" || journal.rollbackBoot !== "succeeded")
  ) {
    throw new SourcePromotionError("INVALID_JOURNAL", "Rolled-back outcome is not backed by a successful rollback boot")
  }
  return journal
}

function requireOperationId(value: unknown, label: string): string {
  if (typeof value !== "string" || !new RegExp(`^${UUID_PATTERN}$`).test(value)) {
    throw new SourcePromotionError("INVALID_OPERATION_ID", `Invalid ${label} identifier`)
  }
  return value.toLowerCase()
}

function requireContentIdentity(value: unknown, label: string): string {
  if (!isContentIdentity(value)) {
    throw new SourcePromotionError(
      "INVALID_CONTENT_IDENTITY",
      `The ${label} must be a non-empty opaque string no larger than ${MAX_CONTENT_IDENTITY_BYTES} bytes`,
    )
  }
  return value
}

function requireBoundIdentity(value: unknown, label: string): BoundIdentity {
  if (
    typeof value !== "object" ||
    value === null ||
    !("dev" in value) ||
    !Number.isSafeInteger(value.dev) ||
    (value.dev as number) < 0 ||
    !("ino" in value) ||
    !Number.isSafeInteger(value.ino) ||
    (value.ino as number) < 0
  ) {
    throw new SourcePromotionError("INVALID_DIRECTORY_IDENTITY", `Invalid ${label}`)
  }
  return { dev: value.dev as number, ino: value.ino as number }
}

function isContentIdentity(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && Buffer.byteLength(value) <= MAX_CONTENT_IDENTITY_BYTES
}

function operationIdFromCandidateName(candidateName: string): string {
  const match = CANDIDATE_NAME_PATTERN.exec(candidateName)
  if (!match) throw new SourcePromotionError("INVALID_CANDIDATE", `Invalid candidate directory name: ${candidateName}`)
  return match[1]!.toLowerCase()
}

function identityOf(snapshot: DirectorySnapshot): BoundIdentity {
  return { dev: snapshot.dev, ino: snapshot.ino }
}

function identityKey(identity: BoundIdentity): string {
  return `${identity.dev}:${identity.ino}`
}

function matches(snapshot: DirectorySnapshot | null, identity: BoundIdentity): snapshot is DirectorySnapshot {
  return snapshot !== null && sameIdentity(snapshot, identity)
}

function sameIdentity(first: BoundIdentity, second: BoundIdentity): boolean {
  return first.dev === second.dev && first.ino === second.ino
}

function validateSnapshot(snapshot: DirectorySnapshot, label: string): void {
  if (
    typeof snapshot.canonicalPath !== "string" ||
    !Number.isSafeInteger(snapshot.dev) ||
    snapshot.dev < 0 ||
    !Number.isSafeInteger(snapshot.ino) ||
    snapshot.ino < 0
  ) {
    throw new SourcePromotionError("INVALID_IDENTITY", `${label} returned an invalid directory identity`)
  }
}

function sameCanonicalPath(left: string, right: string, platform: NodeJS.Platform): boolean {
  const comparable = (target: string): string => {
    let normalised = path.normalize(target)
    if (platform !== "win32") return normalised
    if (normalised.startsWith("\\\\?\\UNC\\")) normalised = `\\\\${normalised.slice(8)}`
    else if (normalised.startsWith("\\\\?\\")) normalised = normalised.slice(4)
    return normalised.toLowerCase()
  }
  return comparable(left) === comparable(right)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isIdentity(value: unknown): value is BoundIdentity {
  return (
    isRecord(value) &&
    Number.isSafeInteger(value.dev) &&
    Number(value.dev) >= 0 &&
    Number.isSafeInteger(value.ino) &&
    Number(value.ino) >= 0
  )
}

function positiveInteger(value: number | undefined, fallback: number, label: string): number {
  const resolved = value ?? fallback
  if (!Number.isSafeInteger(resolved) || resolved < 1) {
    throw new SourcePromotionError("INVALID_OPTIONS", `${label} must be a positive integer`)
  }
  return resolved
}

function nonNegativeInteger(value: number | undefined, fallback: number, label: string): number {
  const resolved = value ?? fallback
  if (!Number.isSafeInteger(resolved) || resolved < 0) {
    throw new SourcePromotionError("INVALID_OPTIONS", `${label} must be a non-negative integer`)
  }
  return resolved
}
