import { createHash } from "node:crypto";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  lstatSync,
  openSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { chmod, copyFile, lstat, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { createNodeBootstrapDependencies } from "./bootstrap-io";

const nativeTarget = process.platform === "darwin" ? "darwin-universal" : `linux-${process.arch}`;
const nativeRoot = path.resolve(import.meta.dirname, "..", "dist", "native", nativeTarget);
const nativeModule = path.join(nativeRoot, "flinttrade-fs-promoter.node");
const nativeManifest = path.join(nativeRoot, "flinttrade-fs-promoter.sha256.json");
const nativeAvailable = ["darwin", "linux"].includes(process.platform) &&
  existsSync(nativeModule) && existsSync(nativeManifest);
const nativeRequired = process.env.FLINTTRADE_REQUIRE_ATOMIC_PROMOTER === "1";
if (nativeRequired && !nativeAvailable) {
  throw new Error(`Required native atomic-promoter artifacts are missing under ${nativeRoot}.`);
}
const scratch: string[] = [];

type NativePromoterArguments = [string, string, string, string, string, string, string];

interface NativePromoterModule {
  promoteAbsent(
    parent: string,
    source: string,
    destination: string,
    expectedDev: string,
    expectedIno: string,
    expectedParentDev: string,
    expectedParentIno: string,
  ): void;
}

function helperDigest(): string {
  const manifest = JSON.parse(requireText(nativeManifest)) as Record<string, unknown>;
  if (
    manifest.schemaVersion !== 1 ||
    manifest.executable !== "flinttrade-fs-promoter.node" ||
    manifest.target !== nativeTarget ||
    typeof manifest.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256) ||
    Object.keys(manifest).sort().join(",") !== "executable,schemaVersion,sha256,target"
  ) {
    throw new Error("Atomic-promoter integration manifest is invalid.");
  }
  return manifest.sha256;
}

function requireText(target: string): string {
  return readFileSync(target, "utf8");
}

function loadNativeModuleFromDescriptor(): NativePromoterModule {
  const descriptor = openSync(nativeModule, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const loaded = { exports: {} } as NodeModule;
    process.dlopen(
      loaded,
      process.platform === "darwin" ? `/dev/fd/${descriptor}` : `/proc/self/fd/${descriptor}`,
    );
    return loaded.exports as NativePromoterModule;
  } finally {
    closeSync(descriptor);
  }
}

afterEach(async () => {
  await Promise.all(scratch.splice(0).map((target) => rm(target, { force: true, recursive: true })));
});

describe("native atomic no-replace promotion", () => {
  it.runIf(nativeAvailable)("rejects embedded NUL bytes in every path and identity argument", () => {
    const promoter = loadNativeModuleFromDescriptor();
    const labels = [
      "parent",
      "source",
      "destination",
      "source device",
      "source inode",
      "parent device",
      "parent inode",
    ];
    const valid: NativePromoterArguments = ["/", "candidate", "active", "1", "1", "1", "1"];
    for (let index = 0; index < valid.length; index += 1) {
      const injected = [...valid] as NativePromoterArguments;
      injected[index] = `${injected[index]}\0ignored`;
      expect(
        () => promoter.promoteAbsent(...injected),
        `${labels[index]} accepted an embedded NUL suffix`,
      ).toThrow(/arguments are invalid/i);
    }
  });

  it.runIf(nativeAvailable)("rejects an overlong parent without accepting a truncated UTF-8 prefix", () => {
    const promoter = loadNativeModuleFromDescriptor();
    expect(() => promoter.promoteAbsent(
      `/${"p".repeat(8_192)}`,
      "candidate",
      "active",
      "1",
      "1",
      "1",
      "1",
    )).toThrow(/arguments are invalid/i);
  });

  it.runIf(nativeAvailable)("promotes one exact directory through the platform-native exclusive syscall", async () => {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-native-promote-")));
    scratch.push(root);
    const source = path.join(root, "candidate");
    const destination = path.join(root, "active");
    await mkdir(source);
    await writeFile(path.join(source, "sentinel"), "candidate");
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      atomicPromotion: {
        expectedHelperSha256: helperDigest(),
        helper: await realpath(nativeModule),
        protocol: "posix",
      },
    });
    const identity = await dependencies.fileSystem.directoryIdentity(source);

    await expect(dependencies.fileSystem.promoteAbsent(source, destination, identity)).resolves.toBeUndefined();
    const promoted = await lstat(destination);
    expect({ dev: promoted.dev, ino: promoted.ino }).toEqual(identity);
    expect(await readFile(path.join(destination, "sentinel"), "utf8")).toBe("candidate");
    await expect(lstat(source)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it.runIf(nativeAvailable)("preserves both identities when a foreign destination wins the final race", async () => {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-native-promote-race-")));
    scratch.push(root);
    const source = path.join(root, "candidate");
    const destination = path.join(root, "active");
    await mkdir(source);
    await writeFile(path.join(source, "sentinel"), "candidate");
    let foreign: { dev: number; ino: number } | null = null;
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      atomicPromotion: {
        expectedHelperSha256: helperDigest(),
        helper: await realpath(nativeModule),
        protocol: "posix",
      },
      testHooks: {
        async beforeAtomicPromotion() {
          await mkdir(destination);
          await writeFile(path.join(destination, "sentinel"), "foreign");
          const identity = await lstat(destination);
          foreign = { dev: identity.dev, ino: identity.ino };
        },
      },
    });
    const candidate = await dependencies.fileSystem.directoryIdentity(source);

    await expect(dependencies.fileSystem.promoteAbsent(source, destination, candidate)).rejects.toThrow(/already exists/i);
    const candidateAfter = await lstat(source);
    const foreignAfter = await lstat(destination);
    expect({ dev: candidateAfter.dev, ino: candidateAfter.ino }).toEqual(candidate);
    expect({ dev: foreignAfter.dev, ino: foreignAfter.ino }).toEqual(foreign);
    expect(await readFile(path.join(source, "sentinel"), "utf8")).toBe("candidate");
    expect(await readFile(path.join(destination, "sentinel"), "utf8")).toBe("foreign");
  });

  it.runIf(nativeAvailable)("loads the build-bound module from its hashed descriptor across a pathname swap", async () => {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-native-module-swap-")));
    scratch.push(root);
    const helper = path.join(root, "promoter.node");
    const movedHelper = `${helper}.owned`;
    const foreign = Buffer.from("foreign native module replacement");
    await copyFile(nativeModule, helper);
    await chmod(helper, 0o555);
    const source = path.join(root, "candidate");
    const destination = path.join(root, "active");
    await mkdir(source);
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      atomicPromotion: {
        expectedHelperSha256: helperDigest(),
        helper,
        protocol: "posix",
      },
      testHooks: {
        afterAtomicPromotionModulePinned(target) {
          renameSync(target, movedHelper);
          writeFileSync(target, foreign, { mode: 0o555 });
        },
      },
    });
    const identity = await dependencies.fileSystem.directoryIdentity(source);

    await expect(dependencies.fileSystem.promoteAbsent(source, destination, identity)).resolves.toBeUndefined();
    expect(await readFile(helper)).toEqual(foreign);
    expect(createHash("sha256").update(await readFile(movedHelper)).digest("hex")).toBe(helperDigest());
    const promoted = await lstat(destination);
    expect({ dev: promoted.dev, ino: promoted.ino }).toEqual(identity);
  });

  it.runIf(nativeAvailable)("loads a private read-only snapshot across in-place mutation of the pinned module", async () => {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-native-module-in-place-")));
    scratch.push(root);
    const helper = path.join(root, "promoter.node");
    await copyFile(nativeModule, helper);
    await chmod(helper, 0o555);
    const before = await lstat(helper);
    const source = path.join(root, "candidate");
    const destination = path.join(root, "active");
    await mkdir(source);
    const foreign = Buffer.alloc(before.size, 0x41);
    const dependencies = createNodeBootstrapDependencies(process.platform, {
      atomicPromotion: {
        expectedHelperSha256: helperDigest(),
        helper,
        protocol: "posix",
      },
      testHooks: {
        afterAtomicPromotionModulePinned(target) {
          chmodSync(target, 0o755);
          writeFileSync(target, foreign, { mode: 0o555 });
          chmodSync(target, 0o555);
          const after = lstatSync(target);
          expect({ dev: after.dev, ino: after.ino }).toEqual({ dev: before.dev, ino: before.ino });
        },
      },
    });
    const identity = await dependencies.fileSystem.directoryIdentity(source);

    await expect(dependencies.fileSystem.promoteAbsent(source, destination, identity)).resolves.toBeUndefined();
    expect(await readFile(helper)).toEqual(foreign);
    const promoted = await lstat(destination);
    expect({ dev: promoted.dev, ino: promoted.ino }).toEqual(identity);
  });
});
