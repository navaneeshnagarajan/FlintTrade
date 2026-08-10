import { spawn } from "node:child_process"
import { once } from "node:events"
import { lstat, mkdtemp, mkdir, readFile, readdir, realpath, rename, rm, symlink, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { build } from "esbuild"
import { describe, expect, it } from "vitest"

import { SourceOperationLeaseRetentionError } from "./source-operation"
import type { WindowsSourceFilesystemBoundary } from "./windows-source-filesystem"

import {
  ACTIVE_SOURCE_NAME,
  CANDIDATE_SOURCE_PREFIX,
  CLEANUP_QUARANTINE_PREFIX,
  FAILED_SOURCE_PREFIX,
  JOURNAL_NAME,
  LAST_KNOWN_GOOD_NAME,
  PRESERVED_QUARANTINE_INVENTORY_NAME,
  ROLLBACK_CRASH_BOUNDARIES,
  STALE_SOURCE_QUARANTINE_PREFIX,
  SUCCESS_CRASH_BOUNDARIES,
  SourcePromotionError,
  createNodeSourcePromotionFileSystem,
  createSourcePromotion,
  type DirectorySnapshot,
  type CompletedPromotionOutcome,
  type NodeSourcePromotionFileSystemOptions,
  type PromotionBoundary,
  type SourcePromotionFileSystem,
  type SourcePromotionLifecycle,
} from "./source-promotion"

const OPERATION_ID = "123e4567-e89b-42d3-a456-426614174000"
const SECOND_OPERATION_ID = "223e4567-e89b-42d3-a456-426614174001"
const SOURCE_ROOT = "/managed/flinttrade-source"
const WORKSPACE_ROOT = "/private/workspace/FlintTrade"
const ORIGINAL_ACTIVE_CONTENT_IDENTITY = "git-tree:original-active"
const CANDIDATE_CONTENT_IDENTITY = "git-tree:candidate"

async function testOnlyPromoteAbsent(
  source: string,
  destination: string,
  expected: { dev: number; ino: number },
): Promise<void> {
  const sourceMetadata = await lstat(source)
  if (!sourceMetadata.isDirectory() || sourceMetadata.dev !== expected.dev || sourceMetadata.ino !== expected.ino) {
    throw new Error("test no-replace promotion source identity mismatch")
  }
  try {
    await lstat(destination)
    throw Object.assign(new Error("test no-replace promotion destination already exists"), { code: "EEXIST" })
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error
  }
  await rename(source, destination)
}

function createTestNodeSourcePromotionFileSystem(
  options: NodeSourcePromotionFileSystemOptions = {},
): SourcePromotionFileSystem {
  return createNodeSourcePromotionFileSystem({
    ...options,
    ...((options.platform ?? process.platform) === "win32"
      ? {}
      : { promoteAbsent: options.promoteAbsent ?? testOnlyPromoteAbsent }),
  })
}

const testOnlySafeRemove: NonNullable<NodeSourcePromotionFileSystemOptions["safeRemove"]> = async ({
  expected,
  quarantine,
  target,
}) => {
  const optionalIdentity = async (entry: string) => {
    try {
      const metadata = await lstat(entry)
      return metadata.isDirectory() ? { dev: metadata.dev, ino: metadata.ino } : null
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null
      throw error
    }
  }
  const [atTarget, atQuarantine] = await Promise.all([
    optionalIdentity(target),
    optionalIdentity(quarantine),
  ])
  if ((atTarget === null) === (atQuarantine === null)) throw new Error("ambiguous test removal evidence")
  const selected = atTarget ?? atQuarantine!
  if (selected.dev !== expected.dev || selected.ino !== expected.ino) {
    throw new Error("test removal identity mismatch")
  }
  if (atTarget) await rename(target, quarantine)
  await rm(quarantine, { recursive: true })
}

function testWindowsFilesystemBoundary(): WindowsSourceFilesystemBoundary {
  const inspect = async (target: string) => {
    try {
      const metadata = await lstat(target)
      if (!metadata.isDirectory() || metadata.isSymbolicLink()) throw new Error("invalid test directory")
      return {
        nativeIdentity: `${metadata.dev.toString(16).padStart(16, "0")}:${metadata.ino.toString(16).padStart(32, "0")}`,
        status: "present" as const,
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { status: "missing" as const }
      throw error
    }
  }
  return {
    async commitJournal({ target, temporary }) {
      await rename(temporary, target)
    },
    inspectDirectory: inspect,
    async inspectJournal(target) {
      try {
        const contents = await readFile(target)
        const metadata = await lstat(target)
        const { createHash } = await import("node:crypto")
        return {
          location: "target" as const,
          nativeIdentity: `${metadata.dev.toString(16).padStart(16, "0")}:${metadata.ino.toString(16).padStart(32, "0")}`,
          sha256: createHash("sha256").update(contents).digest("hex"),
          status: "journal-present" as const,
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return { status: "missing" as const }
        throw error
      }
    },
    async quarantineDirectory({ expectedNativeIdentity, quarantine, target }) {
      const atTarget = await inspect(target)
      const atQuarantine = await inspect(quarantine)
      if ((atTarget.status === "present") === (atQuarantine.status === "present")) {
        throw new Error("ambiguous Windows removal fixture")
      }
      const selected = atTarget.status === "present" ? atTarget : atQuarantine
      if (selected.status !== "present" || selected.nativeIdentity !== expectedNativeIdentity) {
        throw new Error("Windows removal fixture identity mismatch")
      }
      if (atTarget.status === "present") await rename(target, quarantine)
      return { status: "quarantined" as const }
    },
    async removeQuarantinedDirectory({ expectedNativeIdentity, quarantine }) {
      const atQuarantine = await inspect(quarantine)
      if (atQuarantine.status !== "present" || atQuarantine.nativeIdentity !== expectedNativeIdentity) {
        throw new Error("Windows removal fixture identity mismatch")
      }
      await rm(quarantine, { recursive: true })
      return { status: "removed" as const }
    },
    async removeJournal({ target }) {
      await rm(`${target}.previous`, { force: true })
      await rm(target, { force: true })
    },
    async renameDirectory({ destination, expectedNativeIdentity, source }) {
      const before = await inspect(source)
      if (before.status !== "present" || before.nativeIdentity !== expectedNativeIdentity) {
        throw new Error("Windows rename fixture identity mismatch")
      }
      await rename(source, destination)
    },
  }
}

type Call =
  | { kind: "compact-journal"; target: string }
  | { kind: "delay"; milliseconds: number }
  | { kind: "remove-directory"; target: string }
  | { kind: "remove-journal"; target: string }
  | { kind: "rename"; destination: string; source: string }
  | { kind: "sync"; target: string }
  | { kind: "write-journal"; phase: string; target: string }

class FakeFileSystem implements SourcePromotionFileSystem {
  readonly supportsDurableWindowsMutations: boolean
  readonly calls: Call[] = []
  readonly directories = new Map<string, DirectorySnapshot>()
  readonly renameFailures = new Map<string, string[]>()
  failInspectionAfterJournalRemoval = false
  failJournalSyncPhaseOnce: string | null = null
  failJournalWritePhaseOnce: string | null = null
  failOnceAfterQuarantine = false
  failSyncAfterJournalRemoval = false
  removeFailure: unknown = null
  journal: string | null = null
  preservedInventory: string | null = null
  journalRemoved = false

  constructor(windows = false) {
    this.supportsDurableWindowsMutations = windows
    this.directories.set(SOURCE_ROOT, directory(SOURCE_ROOT, 1, 7, windows))
  }

  addDirectory(target: string, ino: number, options: Partial<DirectorySnapshot> = {}): void {
    this.directories.set(target, {
      ...directory(target, ino, 7, this.supportsDurableWindowsMutations),
      ...options,
    })
  }

  failRename(source: string, destination: string, ...codes: string[]): void {
    this.renameFailures.set(`${source}->${destination}`, [...codes])
  }

  async inspectDirectory(target: string): Promise<DirectorySnapshot | null> {
    if (this.failInspectionAfterJournalRemoval && this.journalRemoved) {
      throw new Error(`inspection attempted after journal removal: ${target}`)
    }
    return this.directories.get(target) ?? null
  }

  async readJournal(target: string): Promise<string | null> {
    if (target === path.join(SOURCE_ROOT, JOURNAL_NAME)) return this.journal
    expect(target).toBe(path.join(SOURCE_ROOT, PRESERVED_QUARANTINE_INVENTORY_NAME))
    return this.preservedInventory
  }

  async writeJournalAtomic(target: string, contents: string): Promise<void> {
    if (target === path.join(SOURCE_ROOT, PRESERVED_QUARANTINE_INVENTORY_NAME)) {
      this.preservedInventory = contents
      return
    }
    expect(target).toBe(path.join(SOURCE_ROOT, JOURNAL_NAME))
    const parsed = JSON.parse(contents) as { phase: string }
    this.calls.push({ kind: "write-journal", phase: parsed.phase, target })
    if (this.failJournalWritePhaseOnce === parsed.phase) {
      this.failJournalWritePhaseOnce = null
      throw new Error(`simulated journal write failure at ${parsed.phase}`)
    }
    this.journal = contents
  }

  async removeJournal(target: string): Promise<void> {
    this.calls.push({ kind: "remove-journal", target })
    if (target === path.join(SOURCE_ROOT, PRESERVED_QUARANTINE_INVENTORY_NAME)) {
      this.preservedInventory = null
      return
    }
    expect(target).toBe(path.join(SOURCE_ROOT, JOURNAL_NAME))
    this.journal = null
    this.journalRemoved = true
  }

  async compactJournal(target: string): Promise<void> {
    this.calls.push({ kind: "compact-journal", target })
    expect(target).toBe(path.join(SOURCE_ROOT, JOURNAL_NAME))
    this.journal = null
    this.journalRemoved = true
  }

  async renameDirectory(source: string, destination: string, expected: DirectorySnapshot): Promise<void> {
    this.calls.push({ kind: "rename", source, destination })
    const key = `${source}->${destination}`
    const failures = this.renameFailures.get(key)
    if (failures?.length) {
      const failure = failures.shift()
      if (failure === undefined) {
        throw new Error(`missing simulated rename failure for ${key}`)
      }
      const error = new Error(`simulated ${failure}`) as NodeJS.ErrnoException
      error.code = failure
      throw error
    }

    const entry = this.directories.get(source)
    if (!entry) {
      throw Object.assign(new Error(`missing source: ${source}`), { code: "ENOENT" })
    }
    if (entry.dev !== expected.dev || entry.ino !== expected.ino) {
      throw new Error(`identity changed before rename: ${source}`)
    }
    if (this.directories.has(destination)) {
      throw Object.assign(new Error(`occupied destination: ${destination}`), { code: "EEXIST" })
    }
    this.directories.delete(source)
    this.directories.set(destination, { ...entry, canonicalPath: destination })
  }

  async settleDirectory(
    target: string,
    quarantine: string,
    expected: DirectorySnapshot,
  ): Promise<{ quarantine: DirectorySnapshot; status: "quarantined" } | { status: "removed" }> {
    this.calls.push({ kind: "remove-directory", target })
    if (this.removeFailure) throw this.removeFailure
    const atTarget = this.directories.get(target)
    const atQuarantine = this.directories.get(quarantine)
    if (atTarget && atQuarantine) throw new Error(`duplicate removal evidence: ${target}`)
    const entry = atTarget ?? atQuarantine
    if (!entry || entry.dev !== expected.dev || entry.ino !== expected.ino) {
      throw new Error(`identity changed before removal: ${target}`)
    }
    if (atTarget) {
      this.directories.delete(target)
      this.directories.set(quarantine, { ...entry, canonicalPath: quarantine })
      if (this.failOnceAfterQuarantine) {
        this.failOnceAfterQuarantine = false
        throw new Error("simulated crash after quarantine rename")
      }
    }
    if (this.supportsDurableWindowsMutations) {
      const preserved = this.directories.get(quarantine)
      if (!preserved) throw new Error(`missing preserved quarantine: ${quarantine}`)
      return { quarantine: preserved, status: "quarantined" }
    }
    this.directories.delete(quarantine)
    return { status: "removed" }
  }

  async removeDirectory(target: string, expected: DirectorySnapshot): Promise<{ status: "removed" }> {
    this.calls.push({ kind: "remove-directory", target })
    const entry = this.directories.get(target)
    if (!entry || entry.dev !== expected.dev || entry.ino !== expected.ino) {
      throw new Error(`identity changed before removal: ${target}`)
    }
    this.directories.delete(target)
    return { status: "removed" }
  }

  async syncDirectory(target: string): Promise<void> {
    this.calls.push({ kind: "sync", target })
    const journalPhase = this.journal === null ? null : (JSON.parse(this.journal) as { phase: string }).phase
    if (this.failJournalSyncPhaseOnce === journalPhase) {
      this.failJournalSyncPhaseOnce = null
      throw new Error(`simulated journal sync failure at ${journalPhase}`)
    }
    if (this.failSyncAfterJournalRemoval && this.journalRemoved) {
      throw new Error(`sync attempted after journal removal: ${target}`)
    }
  }

  async delay(milliseconds: number): Promise<void> {
    this.calls.push({ kind: "delay", milliseconds })
  }
}

function directory(canonicalPath: string, ino: number, dev = 7, windows = false): DirectorySnapshot {
  return {
    canonicalPath,
    dev,
    ino,
    ...(windows ? { nativeIdentity: `${dev.toString(16).padStart(16, "0")}:${ino.toString(16).padStart(32, "0")}` } : {}),
  }
}

function fixture(options: { staleLastKnownGood?: boolean; windows?: boolean } = {}) {
  const fileSystem = new FakeFileSystem(options.windows)
  const activePath = path.join(SOURCE_ROOT, ACTIVE_SOURCE_NAME)
  const candidatePath = path.join(SOURCE_ROOT, `FlintTrade.update-${OPERATION_ID}`)
  const failedPath = path.join(SOURCE_ROOT, `${FAILED_SOURCE_PREFIX}${OPERATION_ID}`)
  const lastKnownGoodPath = path.join(SOURCE_ROOT, LAST_KNOWN_GOOD_NAME)
  fileSystem.addDirectory(activePath, 2)
  fileSystem.addDirectory(candidatePath, 3)
  if (options.staleLastKnownGood) fileSystem.addDirectory(lastKnownGoodPath, 4)
  return { activePath, candidatePath, failedPath, fileSystem, lastKnownGoodPath }
}

function promotionRequest(
  candidatePath: string,
  directoryIdentities = {
    candidate: { dev: 7, ino: 3 },
    originalActive: { dev: 7, ino: 2 },
  },
) {
  return {
    candidateContentIdentity: CANDIDATE_CONTENT_IDENTITY,
    candidateDirectoryIdentity: directoryIdentities.candidate,
    candidatePath,
    originalActiveContentIdentity: ORIGINAL_ACTIVE_CONTENT_IDENTITY,
    originalActiveDirectoryIdentity: directoryIdentities.originalActive,
  }
}

function identityAwareLifecycle(
  fileSystem: FakeFileSystem,
  activePath: string,
  candidateIno: number,
  options: { failRollback?: boolean } = {},
): SourcePromotionLifecycle & { boots: string[] } {
  const boots: string[] = []
  return {
    boots,
    async stopActive() {
      return undefined
    },
    async validateActiveContent() {
      return true
    },
    async bootActive({ activePath: target, onBackendStopped }) {
      boots.push(target)
      const active = await fileSystem.inspectDirectory(activePath)
      const healthy = active?.ino === candidateIno ? false : !options.failRollback
      if (!healthy) onBackendStopped()
      return healthy
    },
  }
}

function alwaysHealthyLifecycle(): SourcePromotionLifecycle & {
  boots: string[]
  validations: Array<{ expectedContentIdentity: string; target: string }>
} {
  const boots: string[] = []
  const validations: Array<{ expectedContentIdentity: string; target: string }> = []
  return {
    boots,
    validations,
    async stopActive() {
      return undefined
    },
    async validateActiveContent(target, expectedContentIdentity) {
      validations.push({ expectedContentIdentity, target })
      return true
    },
    async bootActive({ activePath: target }) {
      boots.push(target)
      return true
    },
  }
}

function crashingAt(boundary: PromotionBoundary, mutate?: () => void) {
  return async (reached: PromotionBoundary): Promise<void> => {
    if (reached !== boundary) return
    mutate?.()
    throw new Error(`simulated crash at ${boundary}`)
  }
}

function mutationCalls(fileSystem: FakeFileSystem): Call[] {
  return fileSystem.calls.filter((call) =>
    ["compact-journal", "remove-directory", "remove-journal", "rename", "write-journal"].includes(call.kind),
  )
}

async function acknowledge(
  controller: ReturnType<typeof createSourcePromotion>,
  outcome: CompletedPromotionOutcome,
): Promise<void> {
  await controller.acknowledge(outcome)
}

describe("source promotion", () => {
  it("promotes a UUID candidate and retains exactly one identity-bound LKG", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture({
      staleLastKnownGood: true,
    })
    const lifecycle = alwaysHealthyLifecycle()
    const controller = createSourcePromotion({ fileSystem, lifecycle, sourceRoot: SOURCE_ROOT })

    const outcome = await controller.promote(promotionRequest(candidatePath))
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" })

    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ dev: 7, ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ dev: 7, ino: 2 })
    expect(await fileSystem.inspectDirectory(candidatePath)).toBeNull()
    expect(fileSystem.journal).not.toBeNull()
    expect(lifecycle.validations).toEqual([
      { expectedContentIdentity: CANDIDATE_CONTENT_IDENTITY, target: activePath },
      { expectedContentIdentity: CANDIDATE_CONTENT_IDENTITY, target: activePath },
    ])
    expect(lifecycle.boots).toEqual([activePath])
    expect(fileSystem.calls.filter((call) => call.kind === "remove-directory")).toEqual([
      { kind: "remove-directory", target: lastKnownGoodPath },
    ])
    if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
    await acknowledge(controller, outcome)
    expect(fileSystem.journal).toBeNull()

    for (const call of fileSystem.calls) {
      for (const value of Object.values(call)) {
        if (typeof value === "string") expect(value).not.toContain(WORKSPACE_ROOT)
      }
    }
  })

  it("durably binds both opaque content identities before the first directory mutation", async () => {
    const { candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: crashingAt("journal:prepared"),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")
    expect(fileSystem.journal).not.toBeNull()
    expect(JSON.parse(fileSystem.journal!)).toMatchObject({
      candidateContentIdentity: CANDIDATE_CONTENT_IDENTITY,
      originalActiveContentIdentity: ORIGINAL_ACTIVE_CONTENT_IDENTITY,
      outcome: null,
      quarantineName: `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`,
      schemaVersion: 3,
    })
    expect(fileSystem.calls.filter((call) => call.kind === "rename")).toEqual([])
  })

  it.each([
    ["original active", { originalActiveContentIdentity: "" }],
    ["candidate", { candidateContentIdentity: "" }],
  ])("rejects an invalid %s content identity before mutation", async (_label, override) => {
    const { candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote({ ...promotionRequest(candidatePath), ...override })).rejects.toMatchObject({
      code: "INVALID_CONTENT_IDENTITY",
    })
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it.each([
    ["original active", { originalActiveDirectoryIdentity: { dev: 7, ino: 99 } }],
    ["candidate", { candidateDirectoryIdentity: { dev: 7, ino: 99 } }],
  ])("rejects a replaced %s directory before journal or mutation", async (_label, override) => {
    const { candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote({ ...promotionRequest(candidatePath), ...override })).rejects.toMatchObject({
      code: "IDENTITY_MISMATCH",
    })
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it.each([
    // A win32 candidate with no native File-ID fails closed at the identity
    // boundary; one with a present-but-wrong native File-ID fails the capture
    // comparison. Both are rejected before any journal write or mutation.
    ["missing", { dev: 7, ino: 3 }, "INVALID_DIRECTORY_IDENTITY"],
    [
      "different",
      { dev: 7, ino: 3, nativeIdentity: "0000000000000007:00000000000000000000000000000063" },
      "IDENTITY_MISMATCH",
    ],
  ] as const)("rejects a %s captured Windows candidate native identity before journal or mutation", async (
    _label,
    capturedCandidate,
    expectedCode,
  ) => {
    const { activePath, candidatePath, fileSystem } = fixture({ windows: true })
    const originalActive = await fileSystem.inspectDirectory(activePath)
    if (!originalActive?.nativeIdentity) throw new Error("test Windows active identity is missing")
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath, {
      candidate: capturedCandidate,
      originalActive,
    }))).rejects.toMatchObject({ code: expectedCode })
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it.each([
    ["outside the managed root", "/tmp/FlintTrade.update-123e4567-e89b-42d3-a456-426614174000"],
    ["without a UUID suffix", path.join(SOURCE_ROOT, "FlintTrade.update-latest")],
    ["with a non-canonical uppercase UUID", path.join(SOURCE_ROOT, `FlintTrade.update-${OPERATION_ID.toUpperCase()}`)],
    ["with the failed-directory prefix", path.join(SOURCE_ROOT, `${FAILED_SOURCE_PREFIX}${OPERATION_ID}`)],
  ])("rejects a candidate %s before mutation", async (_label, candidatePath) => {
    const { fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(SourcePromotionError)
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it.each([
    ["different device", { dev: 8 }],
    ["non-canonical alias", { canonicalPath: "/aliased/candidate" }],
  ])("rejects a candidate on a %s before mutation", async (_label, replacement) => {
    const { candidatePath, fileSystem } = fixture()
    fileSystem.addDirectory(candidatePath, 3, replacement)
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(SourcePromotionError)
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it("rejects active/candidate identity aliasing before mutation", async () => {
    const { candidatePath, fileSystem } = fixture()
    fileSystem.addDirectory(candidatePath, 2)
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(SourcePromotionError)
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it("prunes a stale LKG only while the original active identity remains intact", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture({
      staleLastKnownGood: true,
    })
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: async (boundary) => {
        if (boundary === "prune-lkg:before") {
          fileSystem.addDirectory(activePath, 99)
        }
      },
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({ code: "IDENTITY_MISMATCH" })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 4 })
    expect(fileSystem.calls.some((call) => call.kind === "remove-directory")).toBe(false)
    expect(fileSystem.journal).not.toBeNull()
  })

  it("recovers a stale LKG whose identity-bound quarantine rename completed before a crash", async () => {
    const { candidatePath, fileSystem, lastKnownGoodPath } = fixture({ staleLastKnownGood: true })
    const quarantinePath = path.join(SOURCE_ROOT, `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`)
    fileSystem.failOnceAfterQuarantine = true
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toMatchObject({ code: "REMOVE_FAILED" })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toBeNull()
    expect(await fileSystem.inspectDirectory(quarantinePath)).toMatchObject({ ino: 4 })
    expect(fileSystem.journal).not.toBeNull()

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    const outcome = await recovering.recover()
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" })
    expect(await fileSystem.inspectDirectory(quarantinePath)).toBeNull()
    if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
    await acknowledge(recovering, outcome)
  })

  it("propagates safe-removal containment loss without wrapping it as recoverable", async () => {
    const { candidatePath, fileSystem, lastKnownGoodPath } = fixture({ staleLastKnownGood: true })
    const containmentFailure = new SourceOperationLeaseRetentionError("safe remover remains uncontained")
    fileSystem.removeFailure = containmentFailure
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBe(containmentFailure)
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 4 })
    expect(fileSystem.journal).not.toBeNull()
  })

  it("syncs the journal before and the managed root after every destructive boundary", async () => {
    const { candidatePath, fileSystem } = fixture({ staleLastKnownGood: true })
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    const outcome = await controller.promote(promotionRequest(candidatePath))
    if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
    await acknowledge(controller, outcome)

    for (const [index, call] of fileSystem.calls.entries()) {
      if (call.kind === "write-journal") {
        expect(fileSystem.calls[index + 1]).toEqual({ kind: "sync", target: SOURCE_ROOT })
      }
      if (["remove-directory", "rename"].includes(call.kind)) {
        expect(fileSystem.calls[index - 1]).toEqual({ kind: "sync", target: SOURCE_ROOT })
        expect(fileSystem.calls[index + 1]).toEqual({ kind: "sync", target: SOURCE_ROOT })
      }
      if (call.kind === "compact-journal") {
        expect(fileSystem.calls[index - 1]).toEqual({ kind: "sync", target: SOURCE_ROOT })
        expect(index).toBe(fileSystem.calls.length - 1)
      }
    }
  })

  it.each([
    ["promoted", (_fileSystem: FakeFileSystem, _activePath: string) => alwaysHealthyLifecycle()],
    [
      "rolled-back",
      (fileSystem: FakeFileSystem, activePath: string) => identityAwareLifecycle(fileSystem, activePath, 3),
    ],
  ] as const)("keeps a completed %s outcome replayable until it is acknowledged", async (
    status,
    createLifecycle,
  ) => {
    const { activePath, candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: createLifecycle(fileSystem, activePath),
      sourceRoot: SOURCE_ROOT,
    })
    fileSystem.failInspectionAfterJournalRemoval = true
    fileSystem.failSyncAfterJournalRemoval = true

    const outcome = await controller.promote(promotionRequest(candidatePath))
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status })
    expect(fileSystem.journal).not.toBeNull()
    if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
    await acknowledge(controller, outcome)
    expect(fileSystem.journal).toBeNull()
    expect(fileSystem.calls.at(-1)).toEqual({ kind: "compact-journal", target: path.join(SOURCE_ROOT, JOURNAL_NAME) })
  })

  it("replays an outcome-pending journal without validating or rebooting the completed tree", async () => {
    const { candidatePath, fileSystem } = fixture()
    const promoting = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    const promoted = await promoting.promote(promotionRequest(candidatePath))
    expect(fileSystem.journal).not.toBeNull()
    expect(JSON.parse(fileSystem.journal!)).toMatchObject({
      operationId: OPERATION_ID,
      outcome: "promoted",
      phase: "outcome-pending",
    })

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async bootActive() {
          throw new Error("completed outcome must not reboot")
        },
        async stopActive() {
          throw new Error("completed outcome must not stop a backend")
        },
        async validateActiveContent() {
          throw new Error("completed outcome must not revalidate executable content")
        },
      },
      sourceRoot: SOURCE_ROOT,
    })
    await expect(recovering.recover()).resolves.toEqual(promoted)
    expect(fileSystem.journal).not.toBeNull()
    if (promoted.status === "idle") throw new Error("promotion unexpectedly returned idle")
    await acknowledge(recovering, promoted)
    expect(fileSystem.journal).toBeNull()
  })

  it("refuses a stale or status-mismatched acknowledgement without removing the journal", async () => {
    const { candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    const outcome = await controller.promote(promotionRequest(candidatePath))
    if (outcome.status !== "promoted") throw new Error("promotion unexpectedly failed")
    const clearsBefore = fileSystem.calls.filter((call) => call.kind === "compact-journal").length

    await expect(controller.acknowledge({
      ...outcome,
      promotionId: "123e4567-e89b-42d3-a456-426614174001",
    })).rejects.toMatchObject({ code: "ACKNOWLEDGEMENT_MISMATCH" })
    expect(fileSystem.journal).not.toBeNull()
    expect(fileSystem.calls.filter((call) => call.kind === "compact-journal")).toHaveLength(clearsBefore)
  })

  it.each(SUCCESS_CRASH_BOUNDARIES)("recovers a healthy promotion after a crash at %s", async (boundary) => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture({
      staleLastKnownGood: true,
    })
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: crashingAt(boundary),
      sourceRoot: SOURCE_ROOT,
    })

    const promotion = expect(crashing.promote(promotionRequest(candidatePath))).rejects
    if (["promoted-boot:after", "completion:before", "completion:after"].includes(boundary)) {
      await promotion.toBeInstanceOf(SourceOperationLeaseRetentionError)
    } else {
      await promotion.toThrow(`simulated crash at ${boundary}`)
    }

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    const outcome = await recovering.recover()
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" })
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
    expect(fileSystem.journal).not.toBeNull()
    if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
    await acknowledge(recovering, outcome)
    expect(fileSystem.journal).toBeNull()
  })

  it.each([
    ["mismatch", false],
    ["validator error", new Error("content validator unavailable")],
  ] as const)(
    "rolls back without executing the promoted tree after a recovered content %s",
    async (_label, validationResult) => {
      const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
      const crashing = createSourcePromotion({
        fileSystem,
        lifecycle: alwaysHealthyLifecycle(),
        onBoundary: crashingAt("candidate-to-active:after"),
        sourceRoot: SOURCE_ROOT,
      })
      await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")

      const mutationsBefore = mutationCalls(fileSystem).length
      const boots: string[] = []
      const validations: Array<{ expectedContentIdentity: string; target: string }> = []
      const recovering = createSourcePromotion({
        fileSystem,
        lifecycle: {
          async validateActiveContent(target, expectedContentIdentity) {
            validations.push({ expectedContentIdentity, target })
            if (expectedContentIdentity === CANDIDATE_CONTENT_IDENTITY) {
              if (validationResult instanceof Error) throw validationResult
              return validationResult
            }
            return true
          },
          async bootActive({ activePath: target }) {
            boots.push(target)
            return true
          },
          async stopActive() {
            return undefined
          },
        },
        sourceRoot: SOURCE_ROOT,
      })

      const outcome = await recovering.recover()
      expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
      expect(validations).toEqual([
        { expectedContentIdentity: CANDIDATE_CONTENT_IDENTITY, target: activePath },
        { expectedContentIdentity: ORIGINAL_ACTIVE_CONTENT_IDENTITY, target: activePath },
        { expectedContentIdentity: ORIGINAL_ACTIVE_CONTENT_IDENTITY, target: activePath },
      ])
      expect(boots).toEqual([activePath])
      expect(mutationCalls(fileSystem).length).toBeGreaterThan(mutationsBefore)
      expect(fileSystem.journal).not.toBeNull()
      if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
      await acknowledge(recovering, outcome)
      expect(fileSystem.journal).toBeNull()
      expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
      expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toBeNull()
    },
  )

  it("stops and rolls back when promoted content changes during a successful boot", async () => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture()
    let candidateValidations = 0
    const boots: string[] = []
    const stops: string[] = []
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async validateActiveContent(_target, expectedContentIdentity) {
          if (expectedContentIdentity !== CANDIDATE_CONTENT_IDENTITY) return true
          candidateValidations += 1
          return candidateValidations === 1
        },
        async bootActive({ activePath: target }) {
          boots.push(target)
          return true
        },
        async stopActive(target) {
          stops.push(target)
        },
      },
      sourceRoot: SOURCE_ROOT,
    })

    const outcome = await controller.promote(promotionRequest(candidatePath))

    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
    expect(candidateValidations).toBe(2)
    expect(boots).toEqual([activePath, activePath])
    expect(stops).toEqual([activePath])
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
  })

  it("stops and retains evidence when restored content changes during rollback boot", async () => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture()
    let originalValidations = 0
    let bootAttempt = 0
    const stops: string[] = []
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async validateActiveContent(_target, expectedContentIdentity) {
          if (expectedContentIdentity !== ORIGINAL_ACTIVE_CONTENT_IDENTITY) return true
          originalValidations += 1
          return originalValidations === 1
        },
        async bootActive({ onBackendStopped }) {
          bootAttempt += 1
          const healthy = bootAttempt === 2
          if (!healthy) onBackendStopped()
          return healthy
        },
        async stopActive(target) {
          stops.push(target)
        },
      },
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({
      code: "CONTENT_IDENTITY_MISMATCH",
    })
    expect(originalValidations).toBe(2)
    expect(stops).toEqual([activePath])
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
    expect(fileSystem.journal).not.toBeNull()
  })

  it("retains the lease and forbids recovery mutation when a changed booted tree cannot be stopped", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    let validations = 0
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async validateActiveContent() {
          validations += 1
          return validations === 1
        },
        async bootActive() {
          return true
        },
        async stopActive() {
          throw new Error("backend stop proof unavailable")
        },
      },
      sourceRoot: SOURCE_ROOT,
    })
    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    )

    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
    expect(fileSystem.journal).not.toBeNull()
    expect(mutationCalls(fileSystem)).not.toEqual(expect.arrayContaining([
      expect.objectContaining({
        destination: expect.stringContaining(`${FAILED_SOURCE_PREFIX}${OPERATION_ID}`),
        source: activePath,
      }),
    ]))
  })

  it("validates the restored original content identity before rollback boot", async () => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture()
    const validations: Array<{ expectedContentIdentity: string; target: string }> = []
    const boots: string[] = []
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async validateActiveContent(target, expectedContentIdentity) {
          validations.push({ expectedContentIdentity, target })
          return expectedContentIdentity === CANDIDATE_CONTENT_IDENTITY
        },
        async bootActive({ activePath: target, onBackendStopped }) {
          boots.push(target)
          onBackendStopped()
          return false
        },
        async stopActive() {
          return undefined
        },
      },
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({
      code: "CONTENT_IDENTITY_MISMATCH",
    })
    expect(validations).toEqual([
      { expectedContentIdentity: CANDIDATE_CONTENT_IDENTITY, target: activePath },
      { expectedContentIdentity: ORIGINAL_ACTIVE_CONTENT_IDENTITY, target: activePath },
    ])
    expect(boots).toEqual([activePath])
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
    expect(fileSystem.journal).not.toBeNull()
  })

  it("displaces a failed promoted tree, restores the LKG, and keeps failed evidence", async () => {
    const { activePath, candidatePath, failedPath, fileSystem, lastKnownGoodPath } = fixture()
    const lifecycle = identityAwareLifecycle(fileSystem, activePath, 3)
    const controller = createSourcePromotion({ fileSystem, lifecycle, sourceRoot: SOURCE_ROOT })

    const outcome = await controller.promote(promotionRequest(candidatePath))
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })

    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toBeNull()
    expect(fileSystem.journal).not.toBeNull()
    expect(lifecycle.boots).toEqual([activePath, activePath])
    if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
    await acknowledge(controller, outcome)
    expect(fileSystem.journal).toBeNull()
  })

  it.each([
    ["promoted", "write", "promoted-boot-after", "promoted-boot-before", "not-attempted", 3],
    ["promoted", "sync", "promoted-boot-after", "promoted-boot-after", "succeeded", 3],
    ["rollback", "write", "rollback-boot-after", "rollback-boot-before", "not-attempted", 2],
    ["rollback", "sync", "rollback-boot-after", "rollback-boot-after", "succeeded", 2],
  ] as const)(
    "retains same-process mutation authority after a successful %s boot journal %s failure",
    async (kind, failurePoint, afterPhase, durablePhase, durableResult, bootedIdentity) => {
      const { activePath, candidatePath, fileSystem } = fixture()
      const bootIdentities: number[] = []
      const lifecycle: SourcePromotionLifecycle = {
        async bootActive({ onBackendStopped }) {
          const active = await fileSystem.inspectDirectory(activePath)
          if (!active) throw new Error("active source missing during boot")
          bootIdentities.push(active.ino)
          const healthy = kind === "promoted" || active.ino !== 3
          if (!healthy) onBackendStopped()
          return healthy
        },
        async stopActive() {
          throw new Error("an undurable successful boot must remain under retained lease authority")
        },
        async validateActiveContent() {
          return true
        },
      }
      if (failurePoint === "write") fileSystem.failJournalWritePhaseOnce = afterPhase
      else fileSystem.failJournalSyncPhaseOnce = afterPhase
      const controller = createSourcePromotion({ fileSystem, lifecycle, sourceRoot: SOURCE_ROOT })

      await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(
        SourceOperationLeaseRetentionError,
      )
      expect(JSON.parse(fileSystem.journal!)).toMatchObject({
        phase: durablePhase,
        ...(kind === "promoted"
          ? { promotedBoot: durableResult }
          : { promotedBoot: "failed", rollbackBoot: durableResult }),
      })

      // A genuinely fresh runtime starts only after the old parent-bound
      // guardian is gone, so it must perform exactly one new boot regardless
      // of whether the failed durability call left before/after bytes visible.
      const recoveryBootIdentities: number[] = []
      const recovering = createSourcePromotion({
        fileSystem,
        lifecycle: {
          async bootActive() {
            const active = await fileSystem.inspectDirectory(activePath)
            if (!active) throw new Error("active source missing during recovery boot")
            recoveryBootIdentities.push(active.ino)
            return true
          },
          async stopActive() {
            return undefined
          },
          async validateActiveContent() {
            return true
          },
        },
        sourceRoot: SOURCE_ROOT,
      })
      const outcome = await recovering.recover()
      expect(outcome).toMatchObject({ status: kind === "promoted" ? "promoted" : "rolled-back" })
      expect(recoveryBootIdentities).toEqual([bootedIdentity])
      expect(bootIdentities).toEqual(kind === "promoted" ? [3] : [3, 2])
    },
  )

  it.each([
    ["promoted", "promoted-boot:after"],
    ["promoted", "completion:before"],
    ["promoted", "completion:after"],
    ["rolled-back", "rollback-boot:after"],
  ] as const)("retains same-process authority when a live %s backend cannot be finalised", async (status, boundary) => {
    const { activePath, candidatePath, fileSystem } = fixture()
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: status === "promoted"
        ? alwaysHealthyLifecycle()
        : identityAwareLifecycle(fileSystem, activePath, 3),
      onBoundary: crashingAt(boundary),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    )
  })

  it("retains the promoted tree and journal when boot containment cannot be proved", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const containmentFailure = new SourceOperationLeaseRetentionError("boot tree remains uncontained")
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        bootActive: async () => { throw containmentFailure },
        stopActive: async () => undefined,
        validateActiveContent: async () => true,
      },
      sourceRoot: SOURCE_ROOT,
    })

    const error = await controller.promote(promotionRequest(candidatePath)).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError)
    expect((error as SourceOperationLeaseRetentionError).retentionPolicy).toBe("process-exit-required")
    expect((error as Error).cause).toBe(containmentFailure)
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
    expect(fileSystem.journal).not.toBeNull()
    expect(mutationCalls(fileSystem)).not.toContainEqual(expect.objectContaining({
      source: activePath,
      destination: expect.stringContaining(`${FAILED_SOURCE_PREFIX}${OPERATION_ID}`),
    }))
  })

  it("upgrades a weaker containment error after live boot to process-exit retention", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const commandContainment = new SourceOperationLeaseRetentionError("post-boot inspection remains uncontained")
    let validations = 0
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async bootActive() {
          return true
        },
        async stopActive() {
          throw new Error("live backend must remain parent-bound")
        },
        async validateActiveContent() {
          validations += 1
          if (validations === 2) throw commandContainment
          return true
        },
      },
      sourceRoot: SOURCE_ROOT,
    })

    const error = await controller.promote(promotionRequest(candidatePath)).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError)
    expect((error as SourceOperationLeaseRetentionError).retentionPolicy).toBe("process-exit-required")
    expect((error as Error).cause).toBe(commandContainment)
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
  })

  it("upgrades a weaker after-boot boundary error to process-exit retention", async () => {
    const { candidatePath, fileSystem } = fixture()
    const commandContainment = new SourceOperationLeaseRetentionError("lease reproof command remains uncontained")
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary(boundary) {
        if (boundary === "promoted-boot:after") throw commandContainment
      },
      sourceRoot: SOURCE_ROOT,
    })

    const error = await controller.promote(promotionRequest(candidatePath)).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError)
    expect((error as SourceOperationLeaseRetentionError).retentionPolicy).toBe("process-exit-required")
    expect((error as Error).cause).toBe(commandContainment)
  })

  it.each(["false", "rejection"] as const)(
    "retains the promoted tree when an unsuccessful boot has no stopped proof (%s)",
    async (failure) => {
      const { activePath, candidatePath, failedPath, fileSystem, lastKnownGoodPath } = fixture()
      const controller = createSourcePromotion({
        fileSystem,
        lifecycle: {
          async bootActive() {
            if (failure === "rejection") throw new Error("readiness registration failed")
            return false
          },
          async stopActive() {
            return undefined
          },
          async validateActiveContent() {
            return true
          },
        },
        sourceRoot: SOURCE_ROOT,
      })

      const error = await controller.promote(promotionRequest(candidatePath)).catch((caught: unknown) => caught)
      expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError)
      expect((error as SourceOperationLeaseRetentionError & { retentionPolicy?: string }).retentionPolicy).toBe(
        "process-exit-required",
      )
      expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
      expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
      expect(await fileSystem.inspectDirectory(failedPath)).toBeNull()
    },
  )

  it("retains the promoted tree, journal, and lease-retention error when content validation is uncontained", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const containmentFailure = new SourceOperationLeaseRetentionError("content validation tree remains uncontained")
    const boots: string[] = []
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async bootActive({ activePath: target }) {
          boots.push(target)
          return true
        },
        async stopActive() {
          return undefined
        },
        validateActiveContent: async () => { throw containmentFailure },
      },
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toBe(containmentFailure)
    expect(boots).toEqual([])
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
    expect(fileSystem.journal).not.toBeNull()
  })

  it("does not reboot a candidate whose promoted boot failure is already durable", async () => {
    const { activePath, candidatePath, fileSystem } = fixture()
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      onBoundary: crashingAt("failed-displacement:before"),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")

    const recoveryBootIdentities: number[] = []
    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: {
        async validateActiveContent() {
          return true
        },
        async bootActive() {
          const active = await fileSystem.inspectDirectory(activePath)
          if (!active) throw new Error("active source missing during recovery boot")
          recoveryBootIdentities.push(active.ino)
          return true
        },
        async stopActive() {
          return undefined
        },
      },
      sourceRoot: SOURCE_ROOT,
    })

    const outcome = await recovering.recover()
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
    expect(recoveryBootIdentities).toEqual([2])
    if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
    await acknowledge(recovering, outcome)
  })

  it("retains evidence when a durable promoted failure is paired with a reverted directory layout", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      onBoundary: crashingAt("failed-displacement:before"),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")

    const failedCandidate = fileSystem.directories.get(activePath)
    const originalActive = fileSystem.directories.get(lastKnownGoodPath)
    if (!failedCandidate || !originalActive) throw new Error("durable failure fixture is incomplete")
    fileSystem.directories.delete(activePath)
    fileSystem.directories.delete(lastKnownGoodPath)
    fileSystem.directories.set(activePath, { ...originalActive, canonicalPath: activePath })
    fileSystem.directories.set(candidatePath, { ...failedCandidate, canonicalPath: candidatePath })
    const before = mutationCalls(fileSystem).length

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(recovering.recover()).rejects.toMatchObject({ code: "AMBIGUOUS_EVIDENCE" })
    expect(mutationCalls(fileSystem)).toHaveLength(before)
    expect(fileSystem.journal).not.toBeNull()
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(candidatePath)).toMatchObject({ ino: 3 })
  })

  it.each(ROLLBACK_CRASH_BOUNDARIES)("recovers rollback after a crash at %s", async (boundary) => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture()
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      onBoundary: crashingAt(boundary),
      sourceRoot: SOURCE_ROOT,
    })

    const promotion = expect(crashing.promote(promotionRequest(candidatePath))).rejects
    if (["rollback-boot:after", "completion:before", "completion:after"].includes(boundary)) {
      await promotion.toBeInstanceOf(SourceOperationLeaseRetentionError)
    } else {
      await promotion.toThrow(`simulated crash at ${boundary}`)
    }

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      sourceRoot: SOURCE_ROOT,
    })
    const outcome = await recovering.recover()
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
    expect(fileSystem.journal).not.toBeNull()
    if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
    await acknowledge(recovering, outcome)
    expect(fileSystem.journal).toBeNull()
  })

  it("retains the journal and both trees when the rollback boot also fails", async () => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3, { failRollback: true }),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({ code: "ROLLBACK_BOOT_FAILED" })
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
    expect(fileSystem.journal).not.toBeNull()

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    const outcome = await recovering.recover()
    expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
    expect(fileSystem.journal).not.toBeNull()
    if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
    await acknowledge(recovering, outcome)
    expect(fileSystem.journal).toBeNull()
  })

  it("retains ambiguous evidence and refuses all recovery mutations", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: crashingAt("active-to-lkg:after"),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")
    fileSystem.addDirectory(lastKnownGoodPath, 77)
    const before = mutationCalls(fileSystem).length

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(recovering.recover()).rejects.toMatchObject({ code: "AMBIGUOUS_EVIDENCE" })
    expect(mutationCalls(fileSystem)).toHaveLength(before)
    expect(await fileSystem.inspectDirectory(activePath)).toBeNull()
    expect(await fileSystem.inspectDirectory(candidatePath)).toMatchObject({ ino: 3 })
    expect(fileSystem.journal).not.toBeNull()
  })

  it("fails Windows promotion before journal or tree mutation when directory durability cannot be proved", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({
      code: "UNSUPPORTED_DURABILITY",
    })
    expect(fileSystem.journal).toBeNull()
    expect(fileSystem.calls).toEqual([])
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(candidatePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toBeNull()
  })

  it("returns idle on Windows without a journal but rejects a retained journal before parsing or mutation", async () => {
    const { fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.recover()).resolves.toEqual({ status: "idle" })
    fileSystem.journal = "not json"
    await expect(controller.recover()).rejects.toMatchObject({ code: "UNSUPPORTED_DURABILITY" })
    expect(fileSystem.journal).toBe("not json")
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it("retries locked Windows native renames and journals exact file IDs", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture({ windows: true })
    const originalActive = await fileSystem.inspectDirectory(activePath)
    const candidate = await fileSystem.inspectDirectory(candidatePath)
    if (!originalActive?.nativeIdentity || !candidate?.nativeIdentity) {
      throw new Error("test Windows promotion identities are missing")
    }
    fileSystem.failRename(activePath, lastKnownGoodPath, "EBUSY", "EACCES")
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      retry: { attempts: 3, delayMs: 0 },
      sourceRoot: SOURCE_ROOT,
    })

    const outcome = await controller.promote(promotionRequest(candidatePath, { candidate, originalActive }))
    expect(outcome).toMatchObject({ status: "promoted" })
    expect(fileSystem.calls.filter((call) => call.kind === "delay")).toHaveLength(2)
    expect(JSON.parse(fileSystem.journal!)).toMatchObject({
      candidate: { nativeIdentity: "0000000000000007:00000000000000000000000000000003" },
      originalActive: { nativeIdentity: "0000000000000007:00000000000000000000000000000002" },
    })
  })

  it("recovers Windows handle-bound evidence after a crash during candidate promotion", async () => {
    const { activePath, candidatePath, fileSystem, lastKnownGoodPath } = fixture({ windows: true })
    const originalActive = await fileSystem.inspectDirectory(activePath)
    const candidate = await fileSystem.inspectDirectory(candidatePath)
    if (!originalActive?.nativeIdentity || !candidate?.nativeIdentity) {
      throw new Error("test Windows promotion identities are missing")
    }
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: crashingAt("candidate-to-active:mutated"),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath, { candidate, originalActive }))).rejects.toThrow(
      /simulated crash/i,
    )

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })
    await expect(recovering.recover()).resolves.toMatchObject({ status: "promoted" })
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 3 })
    expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: 2 })
  })

  it("recovers a Windows promoted-boot failure and completes identity-bound rollback", async () => {
    const { activePath, candidatePath, failedPath, fileSystem } = fixture({ windows: true })
    const originalActive = await fileSystem.inspectDirectory(activePath)
    const candidate = await fileSystem.inspectDirectory(candidatePath)
    if (!originalActive?.nativeIdentity || !candidate?.nativeIdentity) {
      throw new Error("test Windows promotion identities are missing")
    }
    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      onBoundary: crashingAt("failed-displacement:mutated"),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath, { candidate, originalActive }))).rejects.toThrow(
      /simulated crash/i,
    )

    const recovering = createSourcePromotion({
      fileSystem,
      lifecycle: identityAwareLifecycle(fileSystem, activePath, 3),
      platform: "win32",
      sourceRoot: SOURCE_ROOT,
    })
    await expect(recovering.recover()).resolves.toMatchObject({ status: "rolled-back" })
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(failedPath)).toMatchObject({ ino: 3 })
  })

  it.each([
    "not json",
    JSON.stringify({ schemaVersion: 1, phase: "invented" }),
  ])("rejects a malformed journal without mutation", async (journal) => {
    const { fileSystem } = fixture()
    fileSystem.journal = journal
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.recover()).rejects.toMatchObject({ code: "INVALID_JOURNAL" })
    expect(mutationCalls(fileSystem)).toEqual([])
  })

  it("returns idle without touching the filesystem when no journal exists", async () => {
    const { fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.recover()).resolves.toEqual({ status: "idle" })
    expect(fileSystem.calls).toEqual([])
  })

  it("rejects promotion before reads or mutation when the long-lived lifecycle is unavailable", async () => {
    const { activePath, candidatePath, fileSystem } = fixture()
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: {
        ...alwaysHealthyLifecycle(),
        isAvailable: () => false,
      },
      sourceRoot: SOURCE_ROOT,
    })

    await expect(controller.promote(promotionRequest(candidatePath))).rejects.toMatchObject({
      code: "LIFECYCLE_UNAVAILABLE",
    })
    expect(fileSystem.calls).toEqual([])
    expect(fileSystem.journal).toBeNull()
    expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: 2 })
    expect(await fileSystem.inspectDirectory(candidatePath)).toMatchObject({ ino: 3 })
  })

  it("returns idle without a lifecycle but retains a pending journal without parsing or mutation", async () => {
    const { candidatePath, fileSystem } = fixture()
    const unavailable = createSourcePromotion({
      fileSystem,
      lifecycle: {
        ...alwaysHealthyLifecycle(),
        isAvailable: () => false,
      },
      sourceRoot: SOURCE_ROOT,
    })
    await expect(unavailable.recover()).resolves.toEqual({ status: "idle" })

    const crashing = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      onBoundary: crashingAt("journal:prepared"),
      sourceRoot: SOURCE_ROOT,
    })
    await expect(crashing.promote(promotionRequest(candidatePath))).rejects.toThrow("simulated crash")
    const pendingJournal = fileSystem.journal
    const mutationsBefore = mutationCalls(fileSystem)

    await expect(unavailable.recover()).rejects.toMatchObject({ code: "LIFECYCLE_UNAVAILABLE" })
    expect(fileSystem.journal).toBe(pendingJournal)
    expect(mutationCalls(fileSystem)).toEqual(mutationsBefore)
  })
})

describe("production Node promotion filesystem", () => {
  it("restores the verified original when promoted tracked content changes without replacing the directory", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-content-")))
    const activePath = path.join(temporaryRoot, ACTIVE_SOURCE_NAME)
    const candidatePath = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const lastKnownGoodPath = path.join(temporaryRoot, LAST_KNOWN_GOOD_NAME)
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const fileSystem = createTestNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

    try {
      await mkdir(activePath)
      await mkdir(candidatePath)
      await writeFile(path.join(activePath, "tracked.txt"), ORIGINAL_ACTIVE_CONTENT_IDENTITY)
      await writeFile(path.join(candidatePath, "tracked.txt"), CANDIDATE_CONTENT_IDENTITY)
      const originalActive = await fileSystem.inspectDirectory(activePath)
      const originalCandidate = await fileSystem.inspectDirectory(candidatePath)
      if (!originalActive || !originalCandidate) throw new Error("content-binding fixture identities are missing")
      const crashing = createSourcePromotion({
        fileSystem,
        lifecycle: alwaysHealthyLifecycle(),
        onBoundary: crashingAt("candidate-to-active:after"),
        sourceRoot: temporaryRoot,
      })
      await expect(crashing.promote(promotionRequest(candidatePath, {
        candidate: originalCandidate,
        originalActive,
      }))).rejects.toThrow("simulated crash")

      const promotedIdentity = await fileSystem.inspectDirectory(activePath)
      const originalIdentity = await fileSystem.inspectDirectory(lastKnownGoodPath)
      const journalBefore = await fileSystem.readJournal(journalPath)
      if (!promotedIdentity || !originalIdentity || !journalBefore) {
        throw new Error("crashed content-binding fixture is incomplete")
      }
      await writeFile(path.join(activePath, "tracked.txt"), "tampered-without-directory-replacement")
      expect(await fileSystem.inspectDirectory(activePath)).toMatchObject(promotedIdentity)
      const boots: string[] = []
      const recovering = createSourcePromotion({
        fileSystem,
        lifecycle: {
          async validateActiveContent(target, expectedContentIdentity) {
            return (await readFile(path.join(target, "tracked.txt"), "utf8")) === expectedContentIdentity
          },
          async bootActive({ activePath: target }) {
            boots.push(target)
            return true
          },
          async stopActive() {
            return undefined
          },
        },
        sourceRoot: temporaryRoot,
      })

      const outcome = await recovering.recover()
      expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" })
      expect(boots).toEqual([activePath])
      expect(await fileSystem.readJournal(journalPath)).not.toBeNull()
      if (outcome.status === "idle") throw new Error("recovery unexpectedly returned idle")
      await acknowledge(recovering, outcome)
      expect(await fileSystem.readJournal(journalPath)).toBeNull()
      expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({
        dev: originalIdentity.dev,
        ino: originalIdentity.ino,
      })
      expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toBeNull()
      expect(await fileSystem.inspectDirectory(candidatePath)).toBeNull()
      await expect(readFile(path.join(activePath, "tracked.txt"), "utf8")).resolves.toBe(
        ORIGINAL_ACTIVE_CONTENT_IDENTITY,
      )
      const failedEntries = await readdir(temporaryRoot)
      const failedName = failedEntries.find((entry) => entry.startsWith("FlintTrade.failed-"))
      expect(failedName).toBeTruthy()
      await expect(readFile(path.join(temporaryRoot, failedName!, "tracked.txt"), "utf8")).resolves.toBe(
        "tampered-without-directory-replacement",
      )
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("durably appends values and a tombstone without following a foreign logical path", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-io-")))
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const externalFile = path.join(temporaryRoot, "external-journal")
    const events: Array<{ event: string; target: string }> = []
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      testHooks: {
        durability: (event, target) => events.push({ event, target }),
      },
    })

    try {
      await fileSystem.writeJournalAtomic(journalPath, "first\n")
      expect(await fileSystem.readJournal(journalPath)).toBe("first\n")
      expect(events.slice(0, 2).map(({ event }) => event)).toEqual(["journal-file-synced", "directory-synced"])

      await fileSystem.writeJournalAtomic(journalPath, "second\n")
      expect(await fileSystem.readJournal(journalPath)).toBe("second\n")
      await fileSystem.removeJournal(journalPath)
      expect(await fileSystem.readJournal(journalPath)).toBeNull()

      const foreignJournalPath = path.join(temporaryRoot, ".foreign-journal")
      await writeFile(externalFile, "foreign\n", { mode: 0o600 })
      await symlink(externalFile, foreignJournalPath)
      await expect(fileSystem.readJournal(foreignJournalPath)).rejects.toThrow(/owner-private|no-follow/i)
      await expect(fileSystem.writeJournalAtomic(foreignJournalPath, "replacement\n")).rejects.toThrow(
        /owner-private|no-follow/i,
      )
      expect(await readFile(externalFile, "utf8")).toBe("foreign\n")
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("fails closed on a tombstone sync reporting error but recovers the durable tombstone", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-remove-")))
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    let failTombstoneSync = false
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      testHooks: {
        durability: (event) => {
          if (failTombstoneSync && event === "directory-synced") {
            throw new Error("simulated tombstone sync reporting failure")
          }
        },
      },
    })

    try {
      await fileSystem.writeJournalAtomic(journalPath, "completion-before\n")
      failTombstoneSync = true

      await expect(fileSystem.removeJournal(journalPath)).rejects.toThrow("simulated tombstone sync reporting failure")
      await expect(fileSystem.readJournal(journalPath)).resolves.toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("pins identities across directory rename and removal", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-identity-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const alias = path.join(temporaryRoot, "alias")
    const fileSystem = createTestNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

    try {
      await mkdir(source)
      const expected = await fileSystem.inspectDirectory(source)
      expect(expected).not.toBeNull()
      if (!expected) throw new Error("test source identity is missing")

      await expect(
        fileSystem.renameDirectory(source, destination, { ...expected, ino: expected.ino + 1 }),
      ).rejects.toThrow(/identity/i)
      expect(await fileSystem.inspectDirectory(source)).toMatchObject({ dev: expected.dev, ino: expected.ino })

      await fileSystem.renameDirectory(source, destination, expected)
      expect(await fileSystem.inspectDirectory(source)).toBeNull()
      expect(await fileSystem.inspectDirectory(destination)).toMatchObject({ dev: expected.dev, ino: expected.ino })

      await expect(
        fileSystem.removeDirectory(destination, { ...expected, ino: expected.ino + 1 }),
      ).rejects.toThrow(/identity/i)
      expect(await fileSystem.inspectDirectory(destination)).toMatchObject({ ino: expected.ino })
      await fileSystem.removeDirectory(destination, expected)
      expect(await fileSystem.inspectDirectory(destination)).toBeNull()

      await mkdir(source)
      await symlink(source, alias, "dir")
      await expect(fileSystem.inspectDirectory(alias)).rejects.toThrow(/symbolic-link|no-follow/i)
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it.runIf(process.platform !== "win32")(
    "preserves the candidate and a foreign destination inserted at the native no-replace boundary",
    async () => {
      const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-final-race-")))
      const source = path.join(temporaryRoot, "source")
      const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
      let injected = false
      const fileSystem = createTestNodeSourcePromotionFileSystem({
        async promoteAbsent(from, to, expected) {
          if (!injected) {
            injected = true
            await mkdir(to)
            await writeFile(path.join(to, "foreign.txt"), "foreign destination")
          }
          await testOnlyPromoteAbsent(from, to, expected)
        },
      })

      try {
        await mkdir(source)
        await writeFile(path.join(source, "candidate.txt"), "journalled candidate")
        const expected = await fileSystem.inspectDirectory(source)
        if (!expected) throw new Error("test source identity is missing")

        await expect(fileSystem.renameDirectory(source, destination, expected)).rejects.toMatchObject({ code: "EEXIST" })
        await expect(readFile(path.join(source, "candidate.txt"), "utf8")).resolves.toBe("journalled candidate")
        await expect(readFile(path.join(destination, "foreign.txt"), "utf8")).resolves.toBe("foreign destination")
      } finally {
        await rm(temporaryRoot, { force: true, recursive: true })
      }
    },
  )

  it.runIf(process.platform !== "win32")(
    "preserves all three trees when the restoration destination appears at the native no-replace boundary",
    async () => {
      const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-restore-race-")))
      const source = path.join(temporaryRoot, "source")
      const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
      const capturedExpected = path.join(temporaryRoot, "captured-expected")
      let restoreInjected = false
      const fileSystem = createTestNodeSourcePromotionFileSystem({
        async promoteAbsent(from, to, expected) {
          if (from === destination && to === source && !restoreInjected) {
            restoreInjected = true
            await mkdir(source)
            await writeFile(path.join(source, "foreign-source.txt"), "foreign restoration destination")
          }
          await testOnlyPromoteAbsent(from, to, expected)
        },
        testHooks: {
          async adversarial(event, paths) {
            if (event !== "rename-after-mutation") return
            await rename(paths.destination, capturedExpected)
            await mkdir(paths.destination)
            await writeFile(path.join(paths.destination, "replacement.txt"), "unbound replacement")
          },
        },
      })

      try {
        await mkdir(source)
        await writeFile(path.join(source, "expected.txt"), "journalled source")
        const expected = await fileSystem.inspectDirectory(source)
        if (!expected) throw new Error("test rename identity is missing")

        await expect(fileSystem.renameDirectory(source, destination, expected)).rejects.toThrow(/safely restored/i)
        await expect(readFile(path.join(source, "foreign-source.txt"), "utf8")).resolves.toBe(
          "foreign restoration destination",
        )
        await expect(readFile(path.join(destination, "replacement.txt"), "utf8")).resolves.toBe(
          "unbound replacement",
        )
        await expect(readFile(path.join(capturedExpected, "expected.txt"), "utf8")).resolves.toBe(
          "journalled source",
        )
      } finally {
        await rm(temporaryRoot, { force: true, recursive: true })
      }
    },
  )

  it("removes only exact positive-attempt bootstrap staging directory names", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-staging-removal-")))
    const quarantines: string[] = []
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      safeRemove: async (request) => {
        quarantines.push(path.basename(request.quarantine))
        await testOnlySafeRemove(request)
      },
    })

    try {
      for (const suffix of [".candidate-1", ".candidate-42.unpack"]) {
        const target = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}${suffix}`)
        await mkdir(target)
        const expected = await fileSystem.inspectDirectory(target)
        if (!expected) throw new Error("test staging identity is missing")
        await expect(fileSystem.removeDirectory(target, expected)).resolves.toEqual({ status: "removed" })
        expect(await fileSystem.inspectDirectory(target)).toBeNull()
      }
      expect(quarantines).toEqual([
        `${CLEANUP_QUARANTINE_PREFIX}staging-candidate-1-${OPERATION_ID}`,
        `${CLEANUP_QUARANTINE_PREFIX}staging-unpack-42-${OPERATION_ID}`,
      ])

      for (const suffix of [
        ".candidate-0",
        ".candidate-01",
        ".candidate-1.extra",
        ".candidate-1.unpack.extra",
      ]) {
        const target = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}${suffix}`)
        await mkdir(target)
        const expected = await fileSystem.inspectDirectory(target)
        if (!expected) throw new Error("test near-miss staging identity is missing")
        await expect(fileSystem.removeDirectory(target, expected)).rejects.toThrow(/UUID-bound candidate/i)
        expect(await fileSystem.inspectDirectory(target)).toMatchObject({ ino: expected.ino })
      }
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("keeps ordinary candidate cleanup quarantine distinct from promotion evidence", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-cleanup-quarantine-")))
    const candidate = path.join(temporaryRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`)
    const promotionQuarantine = path.join(temporaryRoot, `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`)
    const cleanupQuarantine = path.join(
      temporaryRoot,
      `${CLEANUP_QUARANTINE_PREFIX}candidate-${OPERATION_ID}`,
    )
    const fileSystem = createTestNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

    try {
      await mkdir(candidate)
      await mkdir(promotionQuarantine)
      await writeFile(path.join(promotionQuarantine, "journal.txt"), "retain promotion evidence")
      const expected = await fileSystem.inspectDirectory(candidate)
      if (!expected) throw new Error("test candidate identity is missing")

      await fileSystem.removeDirectory(candidate, expected)

      expect(await fileSystem.inspectDirectory(candidate)).toBeNull()
      expect(await fileSystem.inspectDirectory(cleanupQuarantine)).toBeNull()
      await expect(readFile(path.join(promotionQuarantine, "journal.txt"), "utf8")).resolves.toBe(
        "retain promotion evidence",
      )
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("removes the exact bound quarantine through the managed deletion boundary", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-quarantine-remove-")))
    const target = path.join(temporaryRoot, LAST_KNOWN_GOOD_NAME)
    const quarantine = path.join(temporaryRoot, `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`)
    const fileSystem = createTestNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

    try {
      await mkdir(target)
      await writeFile(path.join(target, "expected.txt"), "journalled stale tree")
      const expected = await fileSystem.inspectDirectory(target)
      if (!expected) throw new Error("test removal identity is missing")

      await expect(fileSystem.settleDirectory(target, quarantine, expected)).resolves.toEqual({ status: "removed" })

      expect(await fileSystem.inspectDirectory(target)).toBeNull()
      expect(await fileSystem.inspectDirectory(quarantine)).toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it.runIf(process.platform !== "win32")(
    "preserves the target and a foreign quarantine inserted at the native no-replace boundary",
    async () => {
      const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-quarantine-final-race-")))
      const target = path.join(temporaryRoot, LAST_KNOWN_GOOD_NAME)
      const quarantine = path.join(temporaryRoot, `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`)
      let safeRemoveCalls = 0
      const fileSystem = createTestNodeSourcePromotionFileSystem({
        async promoteAbsent(from, to, expected) {
          await mkdir(to)
          await writeFile(path.join(to, "foreign.txt"), "foreign quarantine")
          await testOnlyPromoteAbsent(from, to, expected)
        },
        safeRemove: async (request) => {
          safeRemoveCalls += 1
          await testOnlySafeRemove(request)
        },
      })

      try {
        await mkdir(target)
        await writeFile(path.join(target, "expected.txt"), "journalled stale tree")
        const expected = await fileSystem.inspectDirectory(target)
        if (!expected) throw new Error("test removal identity is missing")

        await expect(fileSystem.settleDirectory(target, quarantine, expected)).rejects.toMatchObject({ code: "EEXIST" })
        expect(safeRemoveCalls).toBe(0)
        await expect(readFile(path.join(target, "expected.txt"), "utf8")).resolves.toBe("journalled stale tree")
        await expect(readFile(path.join(quarantine, "foreign.txt"), "utf8")).resolves.toBe("foreign quarantine")
      } finally {
        await rm(temporaryRoot, { force: true, recursive: true })
      }
    },
  )

  it("restores a replacement moved by a rename race and preserves the expected tree as evidence", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-rename-race-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const capturedExpected = path.join(temporaryRoot, "captured-expected")
    let injected = false
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      testHooks: {
        async adversarial(event, paths) {
          if (event !== "rename-after-mutation" || injected) return
          injected = true
          await rename(paths.destination, capturedExpected)
          await mkdir(paths.destination)
          await writeFile(path.join(paths.destination, "replacement.txt"), "unbound replacement")
        },
      },
    })

    try {
      await mkdir(source)
      await writeFile(path.join(source, "expected.txt"), "journalled source")
      const expected = await fileSystem.inspectDirectory(source)
      if (!expected) throw new Error("test rename identity is missing")

      await expect(fileSystem.renameDirectory(source, destination, expected)).rejects.toThrow(/identity/i)
      await expect(readFile(path.join(source, "replacement.txt"), "utf8")).resolves.toBe("unbound replacement")
      await expect(readFile(path.join(capturedExpected, "expected.txt"), "utf8")).resolves.toBe("journalled source")
      expect(await fileSystem.inspectDirectory(destination)).toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("preserves native Windows identities through the composed promotion controller boundary", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-windows-controller-")))
    const activePath = path.join(temporaryRoot, ACTIVE_SOURCE_NAME)
    const candidatePath = path.join(temporaryRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`)
    const windows = testWindowsFilesystemBoundary()
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      platform: "win32",
      safeRemove: async ({ expected, quarantine, target }) => {
        if (!expected.nativeIdentity) throw new Error("test native identity is missing")
        return windows.quarantineDirectory({
          expectedNativeIdentity: expected.nativeIdentity,
          quarantine,
          target,
        })
      },
      windows,
    })

    try {
      await mkdir(activePath)
      await mkdir(candidatePath)
      const originalActive = await fileSystem.inspectDirectory(activePath)
      const candidate = await fileSystem.inspectDirectory(candidatePath)
      if (!originalActive || !candidate) throw new Error("test Windows controller identities are missing")
      const controller = createSourcePromotion({
        fileSystem,
        lifecycle: alwaysHealthyLifecycle(),
        platform: "win32",
        sourceRoot: temporaryRoot,
      })

      const outcome = await controller.promote(promotionRequest(candidatePath, {
        candidate,
        originalActive,
      }))
      expect(outcome).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" })
      if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
      await acknowledge(controller, outcome)
      expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({
        nativeIdentity: candidate.nativeIdentity,
      })
      expect(await fileSystem.readJournal(path.join(temporaryRoot, JOURNAL_NAME))).toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("tracks preserved Windows stale trees, recovers idempotently, and permits a later promotion", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-windows-preserved-")))
    const activePath = path.join(temporaryRoot, ACTIVE_SOURCE_NAME)
    const lastKnownGoodPath = path.join(temporaryRoot, LAST_KNOWN_GOOD_NAME)
    const preservedInventoryPath = path.join(temporaryRoot, PRESERVED_QUARANTINE_INVENTORY_NAME)
    const windows = testWindowsFilesystemBoundary()
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      platform: "win32",
      safeRemove: async ({ expected, quarantine, target }) => {
        if (!expected.nativeIdentity) throw new Error("test native identity is missing")
        return windows.quarantineDirectory({
          expectedNativeIdentity: expected.nativeIdentity,
          quarantine,
          target,
        })
      },
      windows,
    })
    const controller = createSourcePromotion({
      fileSystem,
      lifecycle: alwaysHealthyLifecycle(),
      platform: "win32",
      sourceRoot: temporaryRoot,
    })

    const promoteCandidate = async (operationId: string) => {
      const candidatePath = path.join(temporaryRoot, `${CANDIDATE_SOURCE_PREFIX}${operationId}`)
      await mkdir(candidatePath)
      const [candidate, originalActive] = await Promise.all([
        fileSystem.inspectDirectory(candidatePath),
        fileSystem.inspectDirectory(activePath),
      ])
      if (!candidate || !originalActive) throw new Error("test Windows promotion identity is missing")
      const outcome = await controller.promote({
        candidateContentIdentity: `git-tree:${operationId}`,
        candidateDirectoryIdentity: candidate,
        candidatePath,
        originalActiveContentIdentity: `git-tree:active-${operationId}`,
        originalActiveDirectoryIdentity: originalActive,
      })
      if (outcome.status === "idle") throw new Error("promotion unexpectedly returned idle")
      await controller.acknowledge(outcome)
      return outcome
    }

    try {
      await mkdir(activePath)
      await mkdir(lastKnownGoodPath)
      await writeFile(path.join(lastKnownGoodPath, "ordinary.txt"), "first preserved stale tree")

      const first = await promoteCandidate(OPERATION_ID)
      expect(first).toMatchObject({
        preservedQuarantine: expect.objectContaining({ nativeIdentity: expect.any(String) }),
        status: "promoted",
      })
      const firstQuarantine = path.join(temporaryRoot, `${STALE_SOURCE_QUARANTINE_PREFIX}${OPERATION_ID}`)
      await expect(readFile(path.join(firstQuarantine, "ordinary.txt"), "utf8")).resolves.toBe(
        "first preserved stale tree",
      )
      await expect(controller.recover()).resolves.toEqual({ status: "idle" })

      const second = await promoteCandidate(SECOND_OPERATION_ID)
      expect(second).toMatchObject({ status: "promoted" })
      const inventory = JSON.parse(await readFile(preservedInventoryPath, "utf8")) as {
        entries: Array<{ operationId: string; quarantineName: string }>;
      }
      expect(inventory.entries).toEqual([
        expect.objectContaining({ operationId: OPERATION_ID }),
        expect.objectContaining({ operationId: SECOND_OPERATION_ID }),
      ])

      await rm(firstQuarantine, { force: true, recursive: true })
      await expect(controller.recover()).resolves.toEqual({ status: "idle" })
      const afterManualPurge = JSON.parse(await readFile(preservedInventoryPath, "utf8")) as {
        entries: Array<{ operationId: string }>;
      }
      expect(afterManualPurge.entries).toEqual([
        expect.objectContaining({ operationId: SECOND_OPERATION_ID }),
      ])
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("uses exact Windows file IDs and native handle-bound mutations without held Node mutation handles", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-windows-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const durabilityEvents: string[] = []
    const mutationProofs: string[] = []
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      platform: "win32",
      safeRemove: async ({ expected, quarantine, target }) => {
        if (!expected.nativeIdentity) throw new Error("test native identity is missing")
        return testWindowsFilesystemBoundary().quarantineDirectory({
          expectedNativeIdentity: expected.nativeIdentity,
          quarantine,
          target,
        })
      },
      testHooks: {
        durability: (event) => durabilityEvents.push(event),
        mutationProof: (strategy, operation) => mutationProofs.push(`${strategy}:${operation}`),
      },
      windows: testWindowsFilesystemBoundary(),
    })

    try {
      await fileSystem.writeJournalAtomic(journalPath, "windows\n")
      expect(await fileSystem.readJournal(journalPath)).toBe("windows\n")
      expect(durabilityEvents).toEqual(["journal-file-synced", "windows-native-parent-flushed"])

      await mkdir(source)
      const expected = await fileSystem.inspectDirectory(source)
      if (!expected) throw new Error("test source identity is missing")
      await fileSystem.renameDirectory(source, destination, expected)
      await fileSystem.removeDirectory(destination, expected)
      await fileSystem.syncDirectory(temporaryRoot)

      expect(mutationProofs).toEqual(["windows-native-file-id:rename"])
      expect(durabilityEvents.at(-1)).toBe("windows-native-parent-flushed")
      expect(await fileSystem.inspectDirectory(destination)).toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("preserves a moved Windows journal temporary and a foreign pathname replacement after commit refusal", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-windows-journal-refusal-")))
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const authenticatedTemporary = path.join(temporaryRoot, "authenticated-temporary-held")
    const base = testWindowsFilesystemBoundary()
    let temporaryPath: string | undefined
    const windows: WindowsSourceFilesystemBoundary = {
      ...base,
      async commitJournal({ temporary }) {
        temporaryPath = temporary
        await rename(temporary, authenticatedTemporary)
        await writeFile(temporary, "foreign temporary replacement\n")
        throw new Error("simulated native journal commit refusal")
      },
    }
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      platform: "win32",
      windows,
    })

    try {
      await expect(fileSystem.writeJournalAtomic(journalPath, "authenticated journal\n")).rejects.toThrow(
        /commit refusal/i,
      )
      expect(temporaryPath).toBeDefined()
      await expect(readFile(authenticatedTemporary, "utf8")).resolves.toBe("authenticated journal\n")
      await expect(readFile(temporaryPath!, "utf8")).resolves.toBe("foreign temporary replacement\n")
      await expect(lstat(journalPath)).rejects.toMatchObject({ code: "ENOENT" })
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("uses native no-replace restoration and preserves a late Windows source plus foreign destination", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-windows-rename-anomaly-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const capturedExpected = path.join(temporaryRoot, "captured-expected")
    const nativeRenames: Array<Parameters<WindowsSourceFilesystemBoundary["renameDirectory"]>[0]> = []
    const base = testWindowsFilesystemBoundary()
    const windows: WindowsSourceFilesystemBoundary = {
      ...base,
      async renameDirectory(input) {
        nativeRenames.push(input)
        if (nativeRenames.length === 2) {
          await mkdir(input.destination)
          await writeFile(path.join(input.destination, "late.txt"), "late source occupant")
          const error = new Error("native no-replace destination occupied") as NodeJS.ErrnoException
          error.code = "DESTINATION_OCCUPIED"
          throw error
        }
        await base.renameDirectory(input)
      },
    }
    let injected = false
    const fileSystem = createTestNodeSourcePromotionFileSystem({
      platform: "win32",
      testHooks: {
        async adversarial(event, paths) {
          if (event !== "rename-after-mutation" || injected) return
          injected = true
          await rename(paths.destination, capturedExpected)
          await mkdir(paths.destination)
          await writeFile(path.join(paths.destination, "foreign.txt"), "foreign destination")
        },
      },
      windows,
    })

    try {
      await mkdir(source)
      await writeFile(path.join(source, "expected.txt"), "journalled source")
      const expected = await fileSystem.inspectDirectory(source)
      if (!expected?.nativeIdentity) throw new Error("test native source identity is missing")

      await expect(fileSystem.renameDirectory(source, destination, expected)).rejects.toThrow(/safely restored/i)
      expect(nativeRenames).toHaveLength(2)
      expect(nativeRenames[1]).toMatchObject({
        destination: source,
        source: destination,
      })
      const foreign = await base.inspectDirectory(destination)
      expect(foreign).toMatchObject({ status: "present" })
      if (foreign.status !== "present") throw new Error("foreign destination fixture disappeared")
      expect(nativeRenames[1]?.expectedNativeIdentity).toBe(foreign.nativeIdentity)
      await expect(readFile(path.join(source, "late.txt"), "utf8")).resolves.toBe("late source occupant")
      await expect(readFile(path.join(destination, "foreign.txt"), "utf8")).resolves.toBe("foreign destination")
      await expect(readFile(path.join(capturedExpected, "expected.txt"), "utf8")).resolves.toBe(
        "journalled source",
      )
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it.runIf(process.platform !== "win32")(
    "recovers in a fresh process after SIGKILL at a durable rename failpoint",
    async () => {
      const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-crash-")))
      const activePath = path.join(temporaryRoot, ACTIVE_SOURCE_NAME)
      const candidatePath = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
      const lastKnownGoodPath = path.join(temporaryRoot, LAST_KNOWN_GOOD_NAME)
      const fixturePath = path.join(temporaryRoot, "promotion-crash-fixture.mjs")
      const fileSystem = createTestNodeSourcePromotionFileSystem()

      try {
        await mkdir(activePath)
        await mkdir(candidatePath)
        const originalActive = await fileSystem.inspectDirectory(activePath)
        const originalCandidate = await fileSystem.inspectDirectory(candidatePath)
        if (!originalActive || !originalCandidate) throw new Error("test checkout identities are missing")

        const sourceDirectory = path.dirname(fileURLToPath(import.meta.url))
        await build({
          bundle: true,
          format: "esm",
          outfile: fixturePath,
          platform: "node",
          stdin: {
            contents: `
              import { lstat, rename } from "node:fs/promises"
              import { createNodeSourcePromotionFileSystem, createSourcePromotion } from "./source-promotion"

              const [mode, sourceRoot, candidatePath] = process.argv.slice(2)
              const fileSystem = createNodeSourcePromotionFileSystem({
                promoteAbsent: async (source, destination, expected) => {
                  const metadata = await lstat(source)
                  if (metadata.dev !== expected.dev || metadata.ino !== expected.ino) {
                    throw new Error("fixture no-replace identity mismatch")
                  }
                  try {
                    await lstat(destination)
                    throw Object.assign(new Error("fixture destination exists"), { code: "EEXIST" })
                  } catch (error) {
                    if (error.code !== "ENOENT") throw error
                  }
                  await rename(source, destination)
                },
              })
              const controller = createSourcePromotion({
                fileSystem,
                lifecycle: {
                  bootActive: async () => true,
                  validateActiveContent: async () => true,
                },
                sourceRoot,
                onBoundary: async (boundary) => {
                  if (mode === "crash" && boundary === "candidate-to-active:mutated") {
                    process.kill(process.pid, "SIGKILL")
                    await new Promise(() => undefined)
                  }
                },
              })
              const outcome = mode === "crash"
                ? await controller.promote({
                    candidateContentIdentity: "git-tree:candidate",
                    candidateDirectoryIdentity: await fileSystem.inspectDirectory(candidatePath),
                    candidatePath,
                    originalActiveContentIdentity: "git-tree:original-active",
                    originalActiveDirectoryIdentity: await fileSystem.inspectDirectory(
                      sourceRoot + "/FlintTrade",
                    ),
                  })
                : await controller.recover()
              process.stdout.write(JSON.stringify(outcome))
            `,
            loader: "ts",
            resolveDir: sourceDirectory,
            sourcefile: "promotion-crash-fixture.ts",
          },
          target: "node22",
        })

        const crashed = await runSubprocess(fixturePath, ["crash", temporaryRoot, candidatePath])
        expect(crashed.code).toBeNull()
        expect(crashed.signal).toBe("SIGKILL")
        expect(crashed.stderr).toBe("")
        expect(await fileSystem.readJournal(path.join(temporaryRoot, JOURNAL_NAME))).not.toBeNull()
        expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({
          dev: originalCandidate.dev,
          ino: originalCandidate.ino,
        })
        expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({
          dev: originalActive.dev,
          ino: originalActive.ino,
        })

        const recovered = await runSubprocess(fixturePath, ["recover", temporaryRoot, candidatePath])
        expect(recovered).toMatchObject({ code: 0, signal: null, stderr: "" })
        const recoveredOutcome = JSON.parse(recovered.stdout) as CompletedPromotionOutcome
        expect(recoveredOutcome).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" })
        expect(await fileSystem.readJournal(path.join(temporaryRoot, JOURNAL_NAME))).not.toBeNull()
        expect(await fileSystem.inspectDirectory(activePath)).toMatchObject({ ino: originalCandidate.ino })
        expect(await fileSystem.inspectDirectory(lastKnownGoodPath)).toMatchObject({ ino: originalActive.ino })
        expect(await fileSystem.inspectDirectory(candidatePath)).toBeNull()

        const replaying = createSourcePromotion({
          fileSystem,
          lifecycle: alwaysHealthyLifecycle(),
          sourceRoot: temporaryRoot,
        })
        await expect(replaying.recover()).resolves.toEqual(recoveredOutcome)
        await replaying.acknowledge(recoveredOutcome)
        expect(await fileSystem.readJournal(path.join(temporaryRoot, JOURNAL_NAME))).toBeNull()
      } finally {
        await rm(temporaryRoot, { force: true, recursive: true })
      }
    },
    20_000,
  )
})

async function runSubprocess(
  fixturePath: string,
  arguments_: readonly string[],
): Promise<{ code: number | null; signal: NodeJS.Signals | null; stderr: string; stdout: string }> {
  const child = spawn(process.execPath, [fixturePath, ...arguments_], {
    env: { PATH: process.env.PATH },
    stdio: ["ignore", "pipe", "pipe"],
  })
  child.stdout.setEncoding("utf8")
  child.stderr.setEncoding("utf8")
  let stdout = ""
  let stderr = ""
  child.stdout.on("data", (chunk: string) => {
    stdout += chunk
  })
  child.stderr.on("data", (chunk: string) => {
    stderr += chunk
  })
  const [code, signal] = (await once(child, "exit")) as [number | null, NodeJS.Signals | null]
  return { code, signal, stderr, stdout }
}
