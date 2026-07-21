import { spawn } from "node:child_process"
import { once } from "node:events"
import { lstat, mkdtemp, mkdir, readFile, readdir, realpath, rename, rm, symlink, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { build } from "esbuild"
import { describe, expect, it } from "vitest"

import { SourceOperationLeaseRetentionError } from "./source-operation"

import {
  ACTIVE_SOURCE_NAME,
  CANDIDATE_SOURCE_PREFIX,
  CLEANUP_QUARANTINE_PREFIX,
  FAILED_SOURCE_PREFIX,
  JOURNAL_NAME,
  LAST_KNOWN_GOOD_NAME,
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
const SOURCE_ROOT = "/managed/flinttrade-source"
const WORKSPACE_ROOT = "/private/workspace/FlintTrade"
const ORIGINAL_ACTIVE_CONTENT_IDENTITY = "git-tree:original-active"
const CANDIDATE_CONTENT_IDENTITY = "git-tree:candidate"

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

type Call =
  | { kind: "delay"; milliseconds: number }
  | { kind: "remove-directory"; target: string }
  | { kind: "remove-journal"; target: string }
  | { kind: "rename"; destination: string; source: string }
  | { kind: "sync"; target: string }
  | { kind: "write-journal"; phase: string; target: string }

class FakeFileSystem implements SourcePromotionFileSystem {
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
  journalRemoved = false

  constructor() {
    this.directories.set(SOURCE_ROOT, directory(SOURCE_ROOT, 1))
  }

  addDirectory(target: string, ino: number, options: Partial<DirectorySnapshot> = {}): void {
    this.directories.set(target, {
      ...directory(target, ino),
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
    expect(target).toBe(path.join(SOURCE_ROOT, JOURNAL_NAME))
    return this.journal
  }

  async writeJournalAtomic(target: string, contents: string): Promise<void> {
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
    this.journal = null
    this.journalRemoved = true
  }

  async renameDirectory(source: string, destination: string, expected: DirectorySnapshot): Promise<void> {
    this.calls.push({ kind: "rename", source, destination })
    const key = `${source}->${destination}`
    const failures = this.renameFailures.get(key)
    if (failures?.length) {
      const error = new Error(`simulated ${failures[0]}`) as NodeJS.ErrnoException
      error.code = failures.shift()
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

  async quarantineAndRemoveDirectory(
    target: string,
    quarantine: string,
    expected: DirectorySnapshot,
  ): Promise<void> {
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
    this.directories.delete(quarantine)
  }

  async removeDirectory(target: string, expected: DirectorySnapshot): Promise<void> {
    this.calls.push({ kind: "remove-directory", target })
    const entry = this.directories.get(target)
    if (!entry || entry.dev !== expected.dev || entry.ino !== expected.ino) {
      throw new Error(`identity changed before removal: ${target}`)
    }
    this.directories.delete(target)
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

function directory(canonicalPath: string, ino: number, dev = 7): DirectorySnapshot {
  return { canonicalPath, dev, ino }
}

function fixture(options: { staleLastKnownGood?: boolean } = {}) {
  const fileSystem = new FakeFileSystem()
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
    ["remove-directory", "remove-journal", "rename", "write-journal"].includes(call.kind),
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
      if (call.kind === "remove-journal") {
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
    expect(fileSystem.calls.at(-1)).toEqual({ kind: "remove-journal", target: path.join(SOURCE_ROOT, JOURNAL_NAME) })
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
    const removalsBefore = fileSystem.calls.filter((call) => call.kind === "remove-journal").length

    await expect(controller.acknowledge({
      ...outcome,
      promotionId: "123e4567-e89b-42d3-a456-426614174001",
    })).rejects.toMatchObject({ code: "ACKNOWLEDGEMENT_MISMATCH" })
    expect(fileSystem.journal).not.toBeNull()
    expect(fileSystem.calls.filter((call) => call.kind === "remove-journal")).toHaveLength(removalsBefore)
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
    const fileSystem = createNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

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

  it("durably replaces and removes a no-follow journal", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-io-")))
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const externalFile = path.join(temporaryRoot, "external-journal")
    const events: Array<{ event: string; target: string }> = []
    const fileSystem = createNodeSourcePromotionFileSystem({
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

      await writeFile(externalFile, "foreign\n", { mode: 0o600 })
      await symlink(externalFile, journalPath)
      await expect(fileSystem.readJournal(journalPath)).rejects.toThrow(/symbolic-link|no-follow/i)
      await expect(fileSystem.writeJournalAtomic(journalPath, "replacement\n")).rejects.toThrow(/symbolic-link|no-follow/i)
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("does not reject a completed removal after the journal has been unlinked", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-remove-")))
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    let failPostUnlinkSync = false
    const fileSystem = createNodeSourcePromotionFileSystem({
      testHooks: {
        durability: (event) => {
          if (failPostUnlinkSync && event === "directory-synced") {
            throw new Error("simulated post-unlink sync reporting failure")
          }
        },
      },
    })

    try {
      await fileSystem.writeJournalAtomic(journalPath, "completion-before\n")
      failPostUnlinkSync = true

      await expect(fileSystem.removeJournal(journalPath)).resolves.toBeUndefined()
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
    const fileSystem = createNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

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

  it("removes only exact positive-attempt bootstrap staging directory names", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-staging-removal-")))
    const quarantines: string[] = []
    const fileSystem = createNodeSourcePromotionFileSystem({
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
        await expect(fileSystem.removeDirectory(target, expected)).resolves.toBeUndefined()
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
    const fileSystem = createNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

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
    const fileSystem = createNodeSourcePromotionFileSystem({ safeRemove: testOnlySafeRemove })

    try {
      await mkdir(target)
      await writeFile(path.join(target, "expected.txt"), "journalled stale tree")
      const expected = await fileSystem.inspectDirectory(target)
      if (!expected) throw new Error("test removal identity is missing")

      await fileSystem.quarantineAndRemoveDirectory(target, quarantine, expected)

      expect(await fileSystem.inspectDirectory(target)).toBeNull()
      expect(await fileSystem.inspectDirectory(quarantine)).toBeNull()
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true })
    }
  })

  it("restores a replacement moved by a rename race and preserves the expected tree as evidence", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-rename-race-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const capturedExpected = path.join(temporaryRoot, "captured-expected")
    let injected = false
    const fileSystem = createNodeSourcePromotionFileSystem({
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

  it("uses Windows stat proofs without unsupported directory fsync or held mutation handles", async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-promotion-windows-")))
    const source = path.join(temporaryRoot, "source")
    const destination = path.join(temporaryRoot, `FlintTrade.update-${OPERATION_ID}`)
    const journalPath = path.join(temporaryRoot, JOURNAL_NAME)
    const durabilityEvents: string[] = []
    const mutationProofs: string[] = []
    const fileSystem = createNodeSourcePromotionFileSystem({
      platform: "win32",
      testHooks: {
        durability: (event) => durabilityEvents.push(event),
        mutationProof: (strategy, operation) => mutationProofs.push(`${strategy}:${operation}`),
      },
    })

    try {
      await fileSystem.writeJournalAtomic(journalPath, "windows\n")
      expect(await fileSystem.readJournal(journalPath)).toBe("windows\n")
      expect(durabilityEvents).toEqual(["journal-file-synced", "directory-sync-unavailable-windows"])

      await mkdir(source)
      const expected = await fileSystem.inspectDirectory(source)
      if (!expected) throw new Error("test source identity is missing")
      await fileSystem.renameDirectory(source, destination, expected)
      await expect(fileSystem.removeDirectory(destination, expected)).rejects.toThrow(/safe-removal helper/i)
      await fileSystem.syncDirectory(temporaryRoot)

      expect(mutationProofs).toEqual(["windows-stable-stat:rename"])
      expect(durabilityEvents.at(-1)).toBe("directory-sync-unavailable-windows")
      expect(await fileSystem.inspectDirectory(destination)).toMatchObject({ dev: expected.dev, ino: expected.ino })
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
      const fileSystem = createNodeSourcePromotionFileSystem()

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
              import { createNodeSourcePromotionFileSystem, createSourcePromotion } from "./source-promotion"

              const [mode, sourceRoot, candidatePath] = process.argv.slice(2)
              const fileSystem = createNodeSourcePromotionFileSystem()
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
