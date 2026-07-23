import { createHash } from "node:crypto";
import { mkdtemp, mkdir, open, readFile, realpath, readdir, rename, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { createNodeBootstrapDependencies } from "./bootstrap-io";
import {
  ACTIVE_SOURCE_NAME,
  CANDIDATE_SOURCE_PREFIX,
  CLEANUP_QUARANTINE_PREFIX,
  FAILED_SOURCE_PREFIX,
  JOURNAL_NAME,
  LAST_KNOWN_GOOD_NAME,
  createNodeSourcePromotionFileSystem,
  createSourcePromotion,
  type NodeSourcePromotionFileSystemOptions,
  type SourcePromotionLifecycle,
} from "./source-promotion";
import { createWindowsSourceFilesystemBoundary, type WindowsSourceFilesystemBoundary } from "./windows-source-filesystem";

const OPERATION_ID = "123e4567-e89b-42d3-a456-426614174000";
const DESKTOP_ROOT = path.resolve(import.meta.dirname, "..");
const NATIVE_ROOT = path.join(DESKTOP_ROOT, "dist", "native", "win32-x64");
const SOURCE_FILESYSTEM_HELPER = path.join(NATIVE_ROOT, "flinttrade-source-fs.exe");
const SOURCE_FILESYSTEM_DIGEST = path.join(NATIVE_ROOT, "flinttrade-source-fs.sha256.json");
const JOB_SUPERVISOR = path.join(NATIVE_ROOT, "flinttrade-job-supervisor.exe");

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

async function temporarySourceRoot(label: string): Promise<string> {
  const root = await realpath(await mkdtemp(path.join(tmpdir(), `flinttrade-windows-source-fs-${label}-`)));
  roots.push(root);
  return root;
}

async function helperDigest(): Promise<string> {
  const manifest = JSON.parse(await readFile(SOURCE_FILESYSTEM_DIGEST, "utf8")) as Record<string, unknown>;
  if (
    Object.keys(manifest).sort().join(",") !== "executable,schemaVersion,sha256" ||
    manifest.executable !== "flinttrade-source-fs.exe" ||
    manifest.schemaVersion !== 1 ||
    typeof manifest.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256)
  ) {
    throw new Error("Windows integration fixture helper digest is invalid.");
  }
  return manifest.sha256;
}

async function runRawSourceFilesystem(args: string[]) {
  const dependencies = createNodeBootstrapDependencies("win32", {
    windowsJobSupervisor: JOB_SUPERVISOR,
  });
  return dependencies.command.run({
    args: ["--source-fs", "1", ...args],
    command: SOURCE_FILESYSTEM_HELPER,
    env: {},
    expectedExecutableSha256: await helperDigest(),
    inheritEnvironment: false,
    timeoutMs: 30_000,
  });
}

async function realBoundary(
  sourceRoot: string,
  digest?: string,
  beforeCommand?: (command: string, args: readonly string[]) => Promise<void>,
): Promise<WindowsSourceFilesystemBoundary> {
  const dependencies = createNodeBootstrapDependencies("win32", {
    windowsJobSupervisor: JOB_SUPERVISOR,
  });
  const boundaryDependencies = beforeCommand
    ? {
        ...dependencies,
        command: {
          ...dependencies.command,
          async run(request: Parameters<typeof dependencies.command.run>[0]) {
            await beforeCommand(request.args[2] ?? "", request.args);
            return dependencies.command.run(request);
          },
        },
      }
    : dependencies;
  return createWindowsSourceFilesystemBoundary({
    dependencies: boundaryDependencies,
    expectedHelperSha256: digest ?? await helperDigest(),
    helper: SOURCE_FILESYSTEM_HELPER,
    operationLease: {
      async assertHeld() {
        return undefined;
      },
      target: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"),
    },
    timeoutMs: 30_000,
  });
}

function productionFileSystem(
  windows: WindowsSourceFilesystemBoundary,
  testHooks?: NodeSourcePromotionFileSystemOptions["testHooks"],
) {
  return createNodeSourcePromotionFileSystem({
    platform: "win32",
    safeRemove: async ({ expected, quarantine, target }) => {
      if (!expected.nativeIdentity) throw new Error("Windows integration cleanup identity is missing.");
      await windows.quarantineDirectory({
        expectedNativeIdentity: expected.nativeIdentity,
        quarantine,
        target,
      });
      return windows.removeQuarantinedDirectory({
        expectedNativeIdentity: expected.nativeIdentity,
        quarantine,
      });
    },
    ...(testHooks ? { testHooks } : {}),
    windows,
  });
}

function lifecycle(boot: (target: string) => Promise<boolean>): SourcePromotionLifecycle {
  return {
    bootActive: async ({ activePath }) => boot(activePath),
    async stopActive() {
      return undefined;
    },
    async validateActiveContent(target, expectedContentIdentity) {
      return (await readFile(path.join(target, "identity.txt"), "utf8")) === expectedContentIdentity;
    },
  };
}

async function requestFor(fileSystem: ReturnType<typeof productionFileSystem>, root: string) {
  const activePath = path.join(root, ACTIVE_SOURCE_NAME);
  const candidatePath = path.join(root, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`);
  const originalActiveDirectoryIdentity = await fileSystem.inspectDirectory(activePath);
  const candidateDirectoryIdentity = await fileSystem.inspectDirectory(candidatePath);
  if (!originalActiveDirectoryIdentity || !candidateDirectoryIdentity) {
    throw new Error("Windows integration promotion identities are missing.");
  }
  return {
    candidateContentIdentity: "candidate",
    candidateDirectoryIdentity,
    candidatePath,
    originalActiveContentIdentity: "original",
    originalActiveDirectoryIdentity,
  };
}

describe.skipIf(process.platform !== "win32")("compiled Windows source filesystem integration", () => {
  it("composes the packaged helper through promotion, journal replacement, rollback and removal flushes", async () => {
    const promotedRoot = await temporarySourceRoot("promote");
    const promotedBoundary = await realBoundary(promotedRoot);
    const promotedFileSystem = productionFileSystem(promotedBoundary);
    await mkdir(path.join(promotedRoot, ACTIVE_SOURCE_NAME));
    await mkdir(path.join(promotedRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`));
    await writeFile(path.join(promotedRoot, ACTIVE_SOURCE_NAME, "identity.txt"), "original");
    await writeFile(path.join(promotedRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`, "identity.txt"), "candidate");
    const promoting = createSourcePromotion({
      fileSystem: promotedFileSystem,
      lifecycle: lifecycle(async () => true),
      sourceRoot: promotedRoot,
    });

    const promoted = await promoting.promote(await requestFor(promotedFileSystem, promotedRoot));
    expect(promoted).toMatchObject({ promotionId: OPERATION_ID, status: "promoted" });
    if (promoted.status === "idle") throw new Error("Windows integration promotion returned idle.");
    await promoting.acknowledge(promoted);
    expect(await promotedFileSystem.readJournal(path.join(promotedRoot, JOURNAL_NAME))).toBeNull();
    expect(await readFile(path.join(promotedRoot, ACTIVE_SOURCE_NAME, "identity.txt"), "utf8")).toBe("candidate");
    expect(await readdir(promotedRoot)).toContain(LAST_KNOWN_GOOD_NAME);

    const rolledBackRoot = await temporarySourceRoot("rollback");
    const rolledBackBoundary = await realBoundary(rolledBackRoot);
    const rolledBackFileSystem = productionFileSystem(rolledBackBoundary);
    await mkdir(path.join(rolledBackRoot, ACTIVE_SOURCE_NAME));
    await mkdir(path.join(rolledBackRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`));
    await writeFile(path.join(rolledBackRoot, ACTIVE_SOURCE_NAME, "identity.txt"), "original");
    await writeFile(path.join(rolledBackRoot, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`, "identity.txt"), "candidate");
    const rollingBack = createSourcePromotion({
      fileSystem: rolledBackFileSystem,
      lifecycle: lifecycle(async (target) => (await readFile(path.join(target, "identity.txt"), "utf8")) === "original"),
      sourceRoot: rolledBackRoot,
    });

    const rolledBack = await rollingBack.promote(await requestFor(rolledBackFileSystem, rolledBackRoot));
    expect(rolledBack).toMatchObject({ promotionId: OPERATION_ID, status: "rolled-back" });
    if (rolledBack.status === "idle") throw new Error("Windows integration rollback returned idle.");
    await rollingBack.acknowledge(rolledBack);
    expect(await rolledBackFileSystem.readJournal(path.join(rolledBackRoot, JOURNAL_NAME))).toBeNull();
    expect(await readFile(path.join(rolledBackRoot, ACTIVE_SOURCE_NAME, "identity.txt"), "utf8")).toBe("original");
    expect((await readdir(rolledBackRoot)).some((entry) => entry.startsWith(FAILED_SOURCE_PREFIX))).toBe(true);
  });

  it("rejects a reparse swap and reclaims an exact quarantine without traversing its reparse child", async () => {
    const root = await temporarySourceRoot("adversarial");
    const boundary = await realBoundary(root);
    const external = await temporarySourceRoot("external");
    await writeFile(path.join(external, "retain.txt"), "outside quarantine");

    const source = path.join(root, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`);
    const destination = path.join(root, ACTIVE_SOURCE_NAME);
    const held = path.join(root, "held-exact-source");
    await mkdir(source);
    const swapFileSystem = productionFileSystem(boundary, {
      async adversarial(event, paths) {
        if (event !== "rename-before-mutation") return;
        await rename(paths.source, held);
        await symlink(external, paths.source, "junction");
      },
    });
    const expectedSwap = await swapFileSystem.inspectDirectory(source);
    if (!expectedSwap) throw new Error("Windows reparse-swap fixture identity is missing.");

    await expect(swapFileSystem.renameDirectory(source, destination, expectedSwap)).rejects.toThrow();
    expect(await readFile(path.join(external, "retain.txt"), "utf8")).toBe("outside quarantine");
    expect(await swapFileSystem.inspectDirectory(held)).toMatchObject({ nativeIdentity: expectedSwap.nativeIdentity });
    await rm(source, { force: true });
    await rm(held, { force: true, recursive: true });

    const candidate = path.join(root, `${CANDIDATE_SOURCE_PREFIX}${OPERATION_ID}`);
    const quarantine = path.join(root, `${CLEANUP_QUARANTINE_PREFIX}candidate-${OPERATION_ID}`);
    await mkdir(path.join(candidate, "nested"), { recursive: true });
    await writeFile(path.join(candidate, "nested", "ordinary.txt"), "owned before settlement");
    await symlink(external, path.join(candidate, "external-junction"), "junction");
    let injected = false;
    const fileSystem = createNodeSourcePromotionFileSystem({
      platform: "win32",
      safeRemove: async ({ expected: cleanupExpected, quarantine: cleanupQuarantine, target }) => {
        if (!cleanupExpected.nativeIdentity) throw new Error("Windows cleanup fixture identity is missing.");
        if (!injected) {
          injected = true;
          await rename(
            path.join(target, "nested", "ordinary.txt"),
            path.join(target, "nested", "owned-held.txt"),
          );
          await writeFile(path.join(target, "nested", "ordinary.txt"), "foreign replacement");
          await mkdir(path.join(target, "foreign-tree"));
          await writeFile(path.join(target, "foreign-tree", "late.txt"), "late ordinary child");
        }
        await boundary.quarantineDirectory({
          expectedNativeIdentity: cleanupExpected.nativeIdentity,
          quarantine: cleanupQuarantine,
          target,
        });
        return boundary.removeQuarantinedDirectory({
          expectedNativeIdentity: cleanupExpected.nativeIdentity,
          quarantine: cleanupQuarantine,
        });
      },
      windows: boundary,
    });
    const expected = await fileSystem.inspectDirectory(candidate);
    if (!expected?.nativeIdentity) throw new Error("Windows cleanup fixture identity is missing.");

    await expect(fileSystem.removeDirectory(candidate, expected)).resolves.toMatchObject({ status: "removed" });
    expect(await fileSystem.inspectDirectory(candidate)).toBeNull();
    expect(await fileSystem.inspectDirectory(quarantine)).toBeNull();
    await expect(fileSystem.removeDirectory(candidate, expected)).resolves.toMatchObject({ status: "removed" });
    expect(await readFile(path.join(external, "retain.txt"), "utf8")).toBe("outside quarantine");
  });

  it("refuses late journal target and sidecar swaps without deleting the foreign entries", async () => {
    const root = await temporarySourceRoot("journal-swap");
    const target = path.join(root, JOURNAL_NAME);
    const previous = `${target}.previous`;
    const temporary = `${target}.tmp`;
    const heldTarget = path.join(root, "trusted-target-held.json");
    let mutation: "commit-previous" | "commit-target" | "remove-previous" | "remove-target" | null = "commit-target";
    const boundary = await realBoundary(root, undefined, async (command) => {
      if (command === "commit-journal" && mutation === "commit-target") {
        mutation = null;
        await rename(target, heldTarget);
        await writeFile(target, "foreign target\n");
      } else if (command === "commit-journal" && mutation === "commit-previous") {
        mutation = null;
        await writeFile(previous, "late foreign previous\n");
      } else if (command === "remove-journal" && mutation === "remove-previous") {
        mutation = null;
        await writeFile(previous, "late foreign previous\n");
      } else if (command === "remove-journal" && mutation === "remove-target") {
        mutation = null;
        await writeFile(target, "late foreign target\n");
      }
    });

    await writeFile(target, "trusted target\n");
    await writeFile(temporary, "replacement journal\n");
    await expect(boundary.commitJournal({
      sha256: createHash("sha256").update("replacement journal\n").digest("hex"),
      target,
      temporary,
    })).rejects.toThrow();
    expect(await readFile(target, "utf8")).toBe("foreign target\n");
    expect(await readFile(heldTarget, "utf8")).toBe("trusted target\n");
    expect(await readFile(temporary, "utf8")).toBe("replacement journal\n");

    await Promise.all([
      rm(target, { force: true }),
      rm(heldTarget, { force: true }),
      rm(temporary, { force: true }),
    ]);
    await writeFile(target, "trusted removal target\n");
    await writeFile(previous, "foreign pre-existing previous\n");
    await writeFile(temporary, "replacement after foreign sidecar\n");
    mutation = null;
    await expect(boundary.commitJournal({
      sha256: createHash("sha256").update("replacement after foreign sidecar\n").digest("hex"),
      target,
      temporary,
    })).rejects.toThrow(/previous sidecar.*refusing to adopt or delete/i);
    await expect(boundary.removeJournal({ target })).rejects.toThrow(/previous sidecar.*refusing to adopt or delete/i);
    expect(await readFile(target, "utf8")).toBe("trusted removal target\n");
    expect(await readFile(previous, "utf8")).toBe("foreign pre-existing previous\n");
    expect(await readFile(temporary, "utf8")).toBe("replacement after foreign sidecar\n");

    await rm(previous, { force: true });
    mutation = "commit-previous";
    await expect(boundary.commitJournal({
      sha256: createHash("sha256").update("replacement after foreign sidecar\n").digest("hex"),
      target,
      temporary,
    })).rejects.toThrow();
    expect(await readFile(target, "utf8")).toBe("trusted removal target\n");
    expect(await readFile(previous, "utf8")).toBe("late foreign previous\n");
    expect(await readFile(temporary, "utf8")).toBe("replacement after foreign sidecar\n");

    await rm(previous, { force: true });
    mutation = "remove-previous";
    await expect(boundary.removeJournal({ target })).rejects.toThrow();
    expect(await readFile(target, "utf8")).toBe("trusted removal target\n");
    expect(await readFile(previous, "utf8")).toBe("late foreign previous\n");

    await Promise.all([
      rm(target, { force: true }),
      rm(previous, { force: true }),
      rm(temporary, { force: true }),
    ]);
    mutation = "remove-target";
    await expect(boundary.removeJournal({ target })).rejects.toThrow();
    expect(await readFile(target, "utf8")).toBe("late foreign target\n");
  });

  it("denies concurrent writers on the temporary, target and reserved previous journal entries", async () => {
    const root = await temporarySourceRoot("journal-writer-sharing");
    const target = path.join(root, JOURNAL_NAME);
    const previous = `${target}.previous`;
    const temporary = `${target}.tmp`;
    const boundary = await realBoundary(root);
    const first = "first journal\n";
    const second = "second journal\n";

    await writeFile(temporary, first);
    const temporaryWriter = await open(temporary, "r+");
    try {
      await expect(boundary.commitJournal({
        sha256: createHash("sha256").update(first).digest("hex"),
        target,
        temporary,
      })).rejects.toMatchObject({ code: "EBUSY" });
    } finally {
      await temporaryWriter.close();
    }
    await expect(readFile(target, "utf8")).rejects.toMatchObject({ code: "ENOENT" });
    expect(await readFile(temporary, "utf8")).toBe(first);

    await boundary.commitJournal({
      sha256: createHash("sha256").update(first).digest("hex"),
      target,
      temporary,
    });
    expect(await readFile(target, "utf8")).toBe(first);
    await expect(readFile(previous, "utf8")).rejects.toMatchObject({ code: "ENOENT" });

    await writeFile(temporary, second);
    const targetWriter = await open(target, "r+");
    try {
      await expect(boundary.commitJournal({
        sha256: createHash("sha256").update(second).digest("hex"),
        target,
        temporary,
      })).rejects.toMatchObject({ code: "EBUSY" });
      await expect(boundary.removeJournal({ target })).rejects.toMatchObject({ code: "EBUSY" });
    } finally {
      await targetWriter.close();
    }
    expect(await readFile(target, "utf8")).toBe(first);
    expect(await readFile(temporary, "utf8")).toBe(second);

    await boundary.commitJournal({
      sha256: createHash("sha256").update(second).digest("hex"),
      target,
      temporary,
    });
    expect(await readFile(target, "utf8")).toBe(second);
    await expect(readFile(previous, "utf8")).rejects.toMatchObject({ code: "ENOENT" });
    await boundary.removeJournal({ target });
    await expect(readFile(target, "utf8")).rejects.toMatchObject({ code: "ENOENT" });

    await writeFile(previous, "foreign previous journal\n");
    const previousWriter = await open(previous, "r+");
    try {
      const refused = await runRawSourceFilesystem([
        "remove-journal", "--parent", root, "--target", path.basename(target),
        "--target-identity", "missing", "--target-sha256", "missing",
        "--previous-identity", "missing", "--previous-sha256", "missing",
      ]);
      expect(refused).toMatchObject({ contained: true, exitCode: 75, stderr: "" });
      expect(JSON.parse(refused.stdout)).toMatchObject({ code: "LOCKED", ok: false });
    } finally {
      await previousWriter.close();
    }
    expect(await readFile(previous, "utf8")).toBe("foreign previous journal\n");
  });

  it("refuses a helper whose exact opened executable does not match the build digest", async () => {
    const root = await temporarySourceRoot("digest");
    await mkdir(path.join(root, ACTIVE_SOURCE_NAME));
    const boundary = await realBoundary(root, "00".repeat(32));

    await expect(boundary.inspectDirectory(path.join(root, ACTIVE_SOURCE_NAME))).rejects.toThrow();
  });
});
