import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, cp, mkdir, mkdtemp, readFile, rename, rm, symlink, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BOOTSTRAP_MARKER,
  SOURCE_INPUTS_RECORD,
  type CommandInvocation,
  type SourceTreeIdentity,
} from "./bootstrap";
import { createNodeBootstrapDependencies } from "./bootstrap-io";
import { inspectHardenedGitCheckout } from "./git-source-inspection";
import {
  resolveExactSourceRevision,
  sourceContentIdentityKey,
  validateActiveSourceProvenance,
  type SourceProvenanceDependencies,
  type SourceProvenanceRequest,
  type SourceRevisionDependencies,
  type SourceRevisionRequest,
} from "./source-provenance";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const revision = "a".repeat(40);
const gitTree = "b".repeat(40);
const archiveSha256 = "c".repeat(64);
const gitOrigin = "https://github.com/navaneeshnagarajan/FlintTrade.git";
const archiveOrigin = "https://codeload.github.com";
const sourceRoot = "/managed/src";
const activeSource = path.join(sourceRoot, "FlintTrade");
const candidateSource = path.join(sourceRoot, "FlintTrade.update-12345678-1234-4123-8123-123456789abc");
const lastKnownGoodSource = path.join(sourceRoot, "FlintTrade.last-known-good");
const packageManager = "pnpm@9.15.0+sha512.fixture";
const toolchain = Object.freeze({ node: "22.23.1", pnpm: "9.15.0", uv: "0.11.16" });
const commitMetadataUrl = "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/commits/main";
const archiveBaseUrl = "https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip";
const bootstrapResources = path.resolve(import.meta.dirname, "..", "resources", "bootstrap");
const REQUIRED_REAL_GIT_PATHS = Object.freeze([
  "package.json",
  "pyproject.toml",
  "uv.lock",
  "pnpm-lock.yaml",
  "packages/apps/terminal/package.json",
]);
const realGitRoots: string[] = [];

afterEach(async () => {
  await Promise.all(realGitRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function gitTestEnvironment(root: string, overrides: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of ["COMSPEC", "PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "WINDIR"] as const) {
    if (process.env[key] !== undefined) environment[key] = process.env[key];
  }
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
  return {
    ...environment,
    GIT_CONFIG_GLOBAL: nullDevice,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_TERMINAL_PROMPT: "0",
    HOME: path.join(root, "home"),
    LC_ALL: "C",
    USERPROFILE: path.join(root, "home"),
    ...overrides,
  };
}

function runFixtureGit(root: string, cwd: string, args: readonly string[]): string {
  const result = spawnSync("git", args, {
    cwd,
    encoding: "utf8",
    env: gitTestEnvironment(root),
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Git fixture command failed (${String(result.status)}): ${result.stderr}`);
  }
  return result.stdout;
}

async function realGitFixture() {
  const root = await mkdtemp(path.join(tmpdir(), "flinttrade-provenance-git-test-"));
  realGitRoots.push(root);
  const sourceRoot = path.join(root, "source");
  const activeSource = path.join(sourceRoot, "FlintTrade");
  await mkdir(path.join(activeSource, "packages", "apps", "terminal"), { recursive: true });
  await mkdir(path.join(root, "home"));
  await writeFile(path.join(activeSource, "package.json"), `${JSON.stringify({
    name: "flinttrade-monorepo",
    packageManager,
  })}\n`);
  await writeFile(path.join(activeSource, "pyproject.toml"), "[project]\nname = \"flinttrade\"\n");
  await writeFile(path.join(activeSource, "uv.lock"), "version = 1\n");
  await writeFile(path.join(activeSource, "pnpm-lock.yaml"), "lockfileVersion: '9.0'\n");
  await writeFile(
    path.join(activeSource, "packages", "apps", "terminal", "package.json"),
    "{\"name\":\"@flinttrade/terminal\"}\n",
  );
  runFixtureGit(root, activeSource, ["init", "--initial-branch=main"]);
  runFixtureGit(root, activeSource, ["add", "--", "."]);
  runFixtureGit(root, activeSource, [
    "-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "fixture",
  ]);
  runFixtureGit(root, activeSource, ["remote", "add", "origin", gitOrigin]);
  runFixtureGit(root, activeSource, ["config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main"]);
  runFixtureGit(root, activeSource, ["config", "remote.origin.tagOpt", "--no-tags"]);
  runFixtureGit(root, activeSource, ["config", "branch.main.remote", "origin"]);
  runFixtureGit(root, activeSource, ["config", "branch.main.merge", "refs/heads/main"]);
  const installedRevision = runFixtureGit(root, activeSource, ["rev-parse", "HEAD"]).trim();
  const installedTree = runFixtureGit(root, activeSource, ["rev-parse", "HEAD^{tree}"]).trim();
  const markerPath = path.join(activeSource, ".git", BOOTSTRAP_MARKER);
  const writeMarker = async (overrides: Record<string, unknown> = {}): Promise<void> => {
    await writeFile(markerPath, `${JSON.stringify(gitMarker({
      gitTree: installedTree,
      revision: installedRevision,
      schemaVersion: 2,
      ...overrides,
    }))}\n`);
  };
  await writeMarker();

  const command = vi.fn(async (invocation: CommandInvocation) => {
    const result = spawnSync(invocation.command, invocation.args, {
      ...(invocation.cwd ? { cwd: invocation.cwd } : {}),
      encoding: "utf8",
      env: gitTestEnvironment(root, invocation.env),
    });
    if (result.error) throw result.error;
    return {
      contained: true,
      exitCode: result.status ?? 1,
      stderr: result.stderr,
      stderrTruncated: false,
      stdout: result.stdout,
      stdoutTruncated: false,
    };
  });
  const request: SourceProvenanceRequest = {
    activeSource,
    bootstrapResources,
    dependencies: {
      command: { run: command },
      fileSystem: createNodeBootstrapDependencies(process.platform).fileSystem,
    },
    disallowedAliases: [
      path.join(sourceRoot, "FlintTrade.last-known-good"),
      path.join(sourceRoot, "FlintTrade.update-12345678-1234-4123-8123-123456789abc"),
    ],
    expected: {
      archiveOrigin,
      branch: "main",
      gitOrigin,
      packageManager,
      packageName: "flinttrade-monorepo",
      toolchain,
    },
    platform: process.platform,
    signal: new AbortController().signal,
    sourceRoot,
  };
  return { activeSource, command, installedRevision, installedTree, request, root, writeMarker };
}

const sourceEntries: SourceTreeIdentity["entries"] = [
  { mode: 0o644, path: "package.json", sha256: "e".repeat(64), type: "file" },
  { mode: 0o644, path: "uv.lock", sha256: "f".repeat(64), type: "file" },
];
const sourceInputDigest = sha256(JSON.stringify(sourceEntries));
const sourceTree: SourceTreeIdentity = { digest: sourceInputDigest, entries: sourceEntries };
const frontendIndexSha256 = sha256("<!doctype html><title>FlintTrade</title>\n");
const frontendEntries: SourceTreeIdentity["entries"] = [
  { mode: 0o644, path: "index.html", sha256: frontendIndexSha256, type: "file" },
];
const frontendOutputDigest = sha256(JSON.stringify(frontendEntries));
const frontendTree: SourceTreeIdentity = { digest: frontendOutputDigest, entries: frontendEntries };
const currentBuildIdentity = {
  frontendOutputDigest,
  markerSchemaVersion: 3 as const,
  packageManager,
  toolchain,
};

function gitMarker(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const schemaVersion = overrides.schemaVersion ?? 3;
  const common = {
    completedAt: "2026-07-21T12:00:00.000Z",
    gitTree,
    node: toolchain.node,
    pnpm: toolchain.pnpm,
    provenance: "git",
    repository: gitOrigin,
    revision,
    uv: toolchain.uv,
  };
  return schemaVersion === 2
    ? { ...common, schemaVersion: 2, ...overrides }
    : {
        ...common,
        frontendOutputDigest,
        frontendOutputEntryCount: frontendEntries.length,
        frontendOutputIndexSha256: frontendIndexSha256,
        packageManager,
        schemaVersion: 3,
        ...overrides,
      };
}

function archiveMarker(recordSha256: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const schemaVersion = overrides.schemaVersion ?? 3;
  const common = {
    archiveFinalOrigin: archiveOrigin,
    archiveSha256,
    completedAt: "2026-07-21T12:00:00.000Z",
    node: toolchain.node,
    pnpm: toolchain.pnpm,
    provenance: "github-archive",
    repository: gitOrigin,
    revision,
    sourceInputDigest,
    sourceInputRecordSha256: recordSha256,
    uv: toolchain.uv,
  };
  return schemaVersion === 2
    ? { ...common, schemaVersion: 2, ...overrides }
    : {
        ...common,
        frontendOutputDigest,
        frontendOutputEntryCount: frontendEntries.length,
        frontendOutputIndexSha256: frontendIndexSha256,
        packageManager,
        schemaVersion: 3,
        ...overrides,
      };
}

interface FixtureOptions {
  activeRealpath?: string;
  alias?: "candidate" | "last-known-good";
  archiveRecordHash?: string;
  gitContained?: boolean;
  gitHead?: string;
  gitOrigin?: string;
  gitStatus?: string;
  gitTree?: string;
  frontendOutput?: "missing" | "mutated" | "valid";
  includeArchiveMarker?: boolean;
  includeEnvironmentFile?: boolean;
  includeEnvironmentSymlink?: boolean;
  includeGitMarker?: boolean;
  markerOverrides?: Record<string, unknown>;
  missingShapePath?: string;
  packageManagerPin?: string;
  packageName?: string;
  provenance?: "git" | "github-archive";
  verifyArchiveTree?: boolean;
}

function fixture(options: FixtureOptions = {}) {
  const controller = new AbortController();
  const provenance = options.provenance ?? "git";
  const sourceInputRecord = `${JSON.stringify(sourceTree)}\n`;
  const sourceInputRecordSha256 = sha256(sourceInputRecord);
  const gitMarkerPath = path.join(activeSource, ".git", BOOTSTRAP_MARKER);
  const archiveMarkerPath = path.join(activeSource, BOOTSTRAP_MARKER);
  const gitConfigPath = path.join(activeSource, ".git", "config");
  const gitDirectory = path.join(activeSource, ".git");
  const gitInfoPath = path.join(gitDirectory, "info");
  const gitObjectsPath = path.join(gitDirectory, "objects");
  const gitObjectInfoPath = path.join(gitObjectsPath, "info");
  const gitHeadPath = path.join(gitDirectory, "HEAD");
  const gitIndexPath = path.join(gitDirectory, "index");
  const gitRefsPath = path.join(gitDirectory, "refs");
  const gitHeadsPath = path.join(gitRefsPath, "heads");
  const gitMainRefPath = path.join(gitHeadsPath, "main");
  const sourceInputRecordPath = path.join(activeSource, SOURCE_INPUTS_RECORD);
  const packagePath = path.join(activeSource, "package.json");
  const configuredOrigin = options.gitOrigin ?? gitOrigin;
  const gitConfigEntries = [
    ["core.repositoryformatversion", "0"],
    ["core.filemode", "true"],
    ["core.bare", "false"],
    ["core.logallrefupdates", "true"],
    ["core.ignorecase", "true"],
    ["core.precomposeunicode", "true"],
    ["remote.origin.url", configuredOrigin],
    ["remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main"],
    ["remote.origin.tagopt", "--no-tags"],
    ["branch.main.remote", "origin"],
    ["branch.main.merge", "refs/heads/main"],
  ] as const;
  const texts = new Map<string, string>([
    [gitConfigPath, "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = true\n\tignorecase = true\n\tprecomposeunicode = true\n[remote \"origin\"]\n\turl = " + configuredOrigin + "\n\tfetch = +refs/heads/main:refs/remotes/origin/main\n\ttagOpt = --no-tags\n[branch \"main\"]\n\tremote = origin\n\tmerge = refs/heads/main\n"],
    [gitHeadPath, "ref: refs/heads/main\n"],
    [gitMainRefPath, `${options.gitHead ?? revision}\n`],
    [packagePath, `${JSON.stringify({
      name: options.packageName ?? "flinttrade-monorepo",
      packageManager: options.packageManagerPin ?? packageManager,
    })}\n`],
    [path.join(activeSource, "pyproject.toml"), "[project]\nname = \"flinttrade\"\n"],
    [path.join(activeSource, "uv.lock"), "version = 1\n"],
    [path.join(activeSource, "pnpm-lock.yaml"), "lockfileVersion: '9.0'\n"],
    [path.join(activeSource, "packages", "apps", "terminal", "package.json"), "{\"name\":\"@flinttrade/terminal\"}\n"],
  ]);
  const includeGitMarker = options.includeGitMarker ?? provenance === "git";
  const includeArchiveMarker = options.includeArchiveMarker ?? provenance === "github-archive";
  if (includeGitMarker) texts.set(gitMarkerPath, `${JSON.stringify(gitMarker(options.markerOverrides))}\n`);
  if (includeArchiveMarker) {
    texts.set(
      archiveMarkerPath,
      `${JSON.stringify(archiveMarker(sourceInputRecordSha256, options.markerOverrides))}\n`,
    );
    texts.set(sourceInputRecordPath, sourceInputRecord);
  }

  const existing = new Set<string>([
    sourceRoot,
    activeSource,
    gitDirectory,
    gitInfoPath,
    gitObjectsPath,
    gitObjectInfoPath,
    gitHeadPath,
    gitIndexPath,
    gitRefsPath,
    gitHeadsPath,
    gitMainRefPath,
    ...texts.keys(),
  ]);
  if (options.missingShapePath) existing.delete(path.join(activeSource, options.missingShapePath));
  if (options.includeEnvironmentFile) existing.add(path.join(activeSource, ".env"));

  const activeIdentity = { dev: 9, ino: 90 };
  const realpaths = new Map<string, string>([
    [sourceRoot, sourceRoot],
    [activeSource, options.activeRealpath ?? activeSource],
  ]);
  const identities = new Map<string, { dev: number; ino: number }>([
    [activeSource, activeIdentity],
    [gitDirectory, { dev: 9, ino: 91 }],
    [gitObjectsPath, { dev: 9, ino: 92 }],
    [gitRefsPath, { dev: 9, ino: 93 }],
    [gitHeadsPath, { dev: 9, ino: 94 }],
    [gitInfoPath, { dev: 9, ino: 99 }],
    [gitObjectInfoPath, { dev: 9, ino: 100 }],
  ]);
  if (options.alias) {
    const aliasPath = options.alias === "candidate" ? candidateSource : lastKnownGoodSource;
    existing.add(aliasPath);
    realpaths.set(aliasPath, activeSource);
    identities.set(aliasPath, activeIdentity);
  }

  const command = vi.fn<SourceProvenanceDependencies["command"]["run"]>(async (invocation) => {
    const commandIndex = invocation.args.findIndex((argument) =>
      ["config", "diff-index", "ls-files", "rev-parse", "status"].includes(argument),
    );
    const operation = invocation.args.slice(commandIndex).join(" ");
    const stdout =
      operation.startsWith("config --file ")
        ? gitConfigEntries.map(([key, value]) => `${key}\n${value}\0`).join("")
        : operation === "rev-parse HEAD"
        ? `${options.gitHead ?? revision}\n`
          : operation === `rev-parse ${revision}^{tree}`
          ? `${options.gitTree ?? gitTree}\n`
          : operation === "ls-files -v -z"
            ? "H package.json\0H pyproject.toml\0H uv.lock\0"
            : operation === "ls-files --others --exclude-standard -z"
              ? options.gitStatus?.startsWith("?? ")
                ? `${options.gitStatus.slice(3).replace(/\0$/, "")}\0`
                : ""
              : operation.startsWith("diff-index ")
                ? ""
              : operation.startsWith("status ")
                ? options.gitStatus?.startsWith(" M") ? options.gitStatus : ""
              : (() => {
                  throw new Error(`Unexpected Git command: ${operation}`);
                })();
    const exitCode =
      operation.startsWith("diff-index ") && options.gitStatus && !options.gitStatus.startsWith(" M") && !options.gitStatus.startsWith("?? ")
        ? 1
        : 0;
    return {
      contained: options.gitContained ?? true,
      exitCode,
      stderr: "",
      stderrTruncated: false,
      stdout,
      stdoutTruncated: false,
    };
  });
  const verifySourceTree = vi.fn<SourceProvenanceDependencies["fileSystem"]["verifySourceTree"]>(async () =>
    (options.verifyArchiveTree ?? true),
  );
  let frontendSnapshots = 0;
  const snapshotSourceTree = vi.fn<SourceProvenanceDependencies["fileSystem"]["snapshotSourceTree"]>(
    async () => {
      frontendSnapshots += 1;
      if (options.frontendOutput === "missing") throw new Error("terminal dist is missing");
      if (options.frontendOutput === "mutated" && frontendSnapshots > 1) {
        const entries: SourceTreeIdentity["entries"] = [
          { mode: 0o644, path: "index.html", sha256: "9".repeat(64), type: "file" },
        ];
        return { digest: sha256(JSON.stringify(entries)), entries };
      }
      return frontendTree;
    },
  );
  const nodeFileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;
  const isBootstrapResource = (target: string): boolean =>
    target === bootstrapResources || target.startsWith(`${bootstrapResources}${path.sep}`);
  const fileIdentities = new Map<string, { ctimeMs: number; dev: number; ino: number; mtimeMs: number; size: number }>([
    [gitConfigPath, { ctimeMs: 1, dev: 9, ino: 95, mtimeMs: 1, size: Buffer.byteLength(texts.get(gitConfigPath)!) }],
    [gitHeadPath, { ctimeMs: 1, dev: 9, ino: 96, mtimeMs: 1, size: Buffer.byteLength(texts.get(gitHeadPath)!) }],
    [gitIndexPath, { ctimeMs: 1, dev: 9, ino: 97, mtimeMs: 1, size: 1 }],
    [gitMainRefPath, { ctimeMs: 1, dev: 9, ino: 98, mtimeMs: 1, size: Buffer.byteLength(texts.get(gitMainRefPath)!) }],
  ]);
  const dependencies: SourceProvenanceDependencies = {
    command: { run: command },
    fileSystem: {
      directoryIdentity: async (target) => {
        if (isBootstrapResource(target)) return nodeFileSystem.directoryIdentity(target);
        const identity = identities.get(target);
        if (!identity) throw new Error(`Missing fixture identity for ${target}`);
        return identity;
      },
      directoryMetadata: async (target) => {
        if (isBootstrapResource(target) || target === path.join(bootstrapResources, "git-common")) {
          return nodeFileSystem.directoryMetadata(target);
        }
        const identity = identities.get(target);
        if (!identity) throw new Error(`Missing fixture directory metadata for ${target}`);
        return { ...identity, ctimeMs: 1, mtimeMs: 1, size: 1 };
      },
      exists: async (target) => existing.has(target),
      existsNoFollow: async (target) => {
        if (isBootstrapResource(target)) return nodeFileSystem.existsNoFollow(target);
        return existing.has(target) ||
          (options.includeEnvironmentSymlink === true && target === path.join(activeSource, ".env"));
      },
      fileIdentity: async (target) => {
        if (isBootstrapResource(target)) return nodeFileSystem.fileIdentity(target);
        const identity = fileIdentities.get(target);
        if (!identity) throw new Error(`Missing fixture file identity for ${target}`);
        return identity;
      },
      listNames: async (target) => {
        if (isBootstrapResource(target) || target === path.join(bootstrapResources, "git-common")) {
          return nodeFileSystem.listNames(target);
        }
        throw new Error(`Unexpected fixture directory listing for ${target}`);
      },
      readTextNoFollow: async (target) => {
        if (isBootstrapResource(target)) return nodeFileSystem.readTextNoFollow(target);
        const value = texts.get(target);
        if (value === undefined) throw new Error(`Missing fixture text for ${target}`);
        return value;
      },
      realpath: async (target) => {
        if (isBootstrapResource(target) || target === path.join(bootstrapResources, "git-common")) {
          return nodeFileSystem.realpath(target);
        }
        return realpaths.get(target) ?? target;
      },
      sha256: async (target) => {
        if (target !== sourceInputRecordPath) throw new Error(`Unexpected digest request for ${target}`);
        return options.archiveRecordHash ?? sourceInputRecordSha256;
      },
      snapshotSourceTree,
      verifySourceTree,
    },
  };
  const request: SourceProvenanceRequest = {
    activeSource,
    bootstrapResources,
    dependencies,
    disallowedAliases: [candidateSource, lastKnownGoodSource],
    expected: {
      archiveOrigin,
      branch: "main",
      gitOrigin,
      packageManager,
      packageName: "flinttrade-monorepo",
      toolchain,
    },
    platform: "darwin",
    signal: controller.signal,
    sourceRoot,
  };
  return { command, controller, dependencies, request, snapshotSourceTree, verifySourceTree };
}

describe("active source provenance", () => {
  it("derives a path-independent key bound to trusted source content", () => {
    const identity = {
      canonicalPath: activeSource,
      contentIdentity: gitTree,
      directoryIdentity: { dev: 9, ino: 90 },
      provenance: "git" as const,
      revision,
    };
    const relocated = {
      ...identity,
      canonicalPath: path.join(sourceRoot, "FlintTrade.last-known-good"),
      directoryIdentity: { dev: 9, ino: 91 },
    };

    expect(sourceContentIdentityKey(identity)).toBe(sourceContentIdentityKey(relocated));
    expect(sourceContentIdentityKey(identity)).toMatch(/^[0-9a-f]{64}$/);
    expect(sourceContentIdentityKey({ ...identity, contentIdentity: "d".repeat(40) }))
      .not.toBe(sourceContentIdentityKey(identity));
    const bound = { ...identity, buildIdentity: currentBuildIdentity };
    expect(sourceContentIdentityKey({
      ...bound,
      buildIdentity: { ...currentBuildIdentity, frontendOutputDigest: "8".repeat(64) },
    })).not.toBe(sourceContentIdentityKey(bound));
  });

  it("proves the exact Git marker, HEAD, tree, raw config, index flags and clean worktree", async () => {
    const test = fixture();

    await expect(validateActiveSourceProvenance(test.request)).resolves.toEqual({
      buildIdentity: currentBuildIdentity,
      canonicalPath: activeSource,
      contentIdentity: gitTree,
      directoryIdentity: { dev: 9, ino: 90 },
      provenance: "git",
      requiresRebuild: false,
      revision,
    });
    const gitDirectory = path.join(activeSource, ".git");
    const isolatedCommon = path.join(bootstrapResources, "git-common");
    const trustedCwd = path.dirname(process.execPath);
    const hardenedPrefix = [
      "--no-optional-locks",
      "--no-replace-objects",
      `--git-dir=${gitDirectory}`,
      `--work-tree=${activeSource}`,
      "-c",
      "core.bare=false",
      "-c",
      "core.fsmonitor=",
      "-c",
      "core.hooksPath=/dev/null",
      "-c",
      "core.excludesFile=/dev/null",
      "-c",
      "core.attributesFile=/dev/null",
      "-c",
      "core.filemode=true",
      "-c",
      "core.ignorecase=false",
      "-c",
      "core.symlinks=true",
      "-c",
      "core.precomposeunicode=true",
      "-c",
      "extensions.worktreeConfig=false",
    ];
    expect(test.command.mock.calls.map(([invocation]) => invocation.args)).toEqual([
      [
        "--no-optional-locks",
        "--no-replace-objects",
        "--git-dir=/dev/null",
        "config",
        "--file",
        path.join(gitDirectory, "config"),
        "--no-includes",
        "--null",
        "--list",
      ],
      [...hardenedPrefix, "rev-parse", "HEAD"],
      [...hardenedPrefix, "rev-parse", `${revision}^{tree}`],
      [...hardenedPrefix, "ls-files", "-v", "-z"],
      [...hardenedPrefix, "diff-index", "--cached", "--quiet", "--ignore-submodules=none", revision, "--"],
      [...hardenedPrefix, "status", "--porcelain=v2", "-z", "--untracked-files=no", "--ignore-submodules=none"],
      [...hardenedPrefix, "ls-files", "--others", "--exclude-standard", "-z"],
      [...hardenedPrefix, "rev-parse", "HEAD"],
    ]);
    const [configInvocation, ...activeInvocations] = test.command.mock.calls.map(([invocation]) => invocation);
    expect(configInvocation).toMatchObject({
      command: "git",
      cwd: trustedCwd,
      env: {
        GIT_ATTR_NOSYSTEM: "1",
        GIT_CEILING_DIRECTORIES: trustedCwd,
        GIT_CONFIG_GLOBAL: "/dev/null",
        GIT_CONFIG_NOSYSTEM: "1",
        GIT_CONFIG_SYSTEM: "/dev/null",
        GIT_NO_REPLACE_OBJECTS: "1",
        GIT_TERMINAL_PROMPT: "0",
      },
    });
    for (const invocation of activeInvocations) {
      expect(invocation).toMatchObject({
        command: "git",
        cwd: activeSource,
        env: {
          GIT_ATTR_NOSYSTEM: "1",
          GIT_CEILING_DIRECTORIES: activeSource,
          GIT_COMMON_DIR: isolatedCommon,
          GIT_CONFIG_GLOBAL: "/dev/null",
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_SYSTEM: "/dev/null",
          GIT_INDEX_FILE: path.join(gitDirectory, "index"),
          GIT_NO_REPLACE_OBJECTS: "1",
          GIT_OBJECT_DIRECTORY: path.join(gitDirectory, "objects"),
          GIT_TERMINAL_PROMPT: "0",
        },
      });
      expect(invocation.signal).toBe(test.controller.signal);
    }
    expect(configInvocation?.signal).toBe(test.controller.signal);
  });

  it("preserves a stable native directory identity in active-source provenance", async () => {
    const test = fixture();
    const nativeIdentity = "0000000000000009:0000000000000000000000000000005a";
    const directoryMetadata = test.dependencies.fileSystem.directoryMetadata;
    test.dependencies.fileSystem.directoryMetadata = async (target) => ({
      ...await directoryMetadata(target),
      nativeIdentity,
    });

    await expect(validateActiveSourceProvenance(test.request)).resolves.toMatchObject({
      directoryIdentity: { dev: 9, ino: 90, nativeIdentity },
    });
  });

  it("rejects missing or changed native identity across Node provenance metadata reads", async () => {
    const test = fixture();
    const directoryMetadata = test.dependencies.fileSystem.directoryMetadata;
    let activeReads = 0;
    test.dependencies.fileSystem.directoryMetadata = async (target) => {
      const metadata = await directoryMetadata(target);
      if (target !== activeSource) return metadata;
      activeReads += 1;
      return activeReads === 1
        ? { ...metadata, nativeIdentity: "0000000000000009:0000000000000000000000000000005a" }
        : metadata;
    };

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /aliased|changed|canonical inspection/i,
    );
  });

  it("retains the operation lease when an in-flight Git provenance command rejects during cancellation", async () => {
    const test = fixture();
    test.command.mockImplementationOnce((invocation) => new Promise((_resolve, reject) => {
      invocation.signal?.addEventListener("abort", () => reject(invocation.signal?.reason), { once: true });
    }));

    const validating = validateActiveSourceProvenance(test.request);
    await vi.waitFor(() => expect(test.command).toHaveBeenCalledOnce(), { timeout: 15_000 });
    test.controller.abort(new DOMException("cancelled", "AbortError"));

    await expect(validating).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(test.command.mock.calls[0]?.[0].signal).toBe(test.controller.signal);
    expect(test.command).toHaveBeenCalledOnce();
  });

  it("retains the operation lease when active Git inspection rejects without a containment result", async () => {
    const test = fixture();
    test.command.mockRejectedValueOnce(new Error("command runner rejected"));

    await expect(validateActiveSourceProvenance(test.request)).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    );
    expect(test.command).toHaveBeenCalledOnce();
  });

  it("rejects a dangling repository-root .env link that access-style existence misses", async () => {
    const test = fixture({ includeEnvironmentSymlink: true });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/repository-root \.env/i);
  });

  it.each([
    ["marker provenance", { provenance: "github-archive" }, /marker|provenance/i],
    ["marker repository", { repository: "https://example.test/foreign.git" }, /marker|repository|foreign/i],
    ["marker toolchain", { pnpm: "0.0.0" }, /marker|provenance|toolchain|tool version/i],
    ["extra marker field", { unexpected: true }, /marker|field/i],
  ] as const)("rejects an inexact Git %s", async (_label, markerOverrides, message) => {
    const test = fixture({ markerOverrides });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
  });

  it("boots a valid legacy completion marker but requires a current-toolchain rebuild", async () => {
    const oldPackageManager = "pnpm@9.14.4+sha512.legacy";
    const test = fixture({
      markerOverrides: {
        node: "22.22.0",
        pnpm: "9.14.4",
        schemaVersion: 2,
        uv: "0.10.0",
      },
      packageManagerPin: oldPackageManager,
    });

    await expect(validateActiveSourceProvenance(test.request)).resolves.toMatchObject({
      buildIdentity: {
        frontendOutputDigest: null,
        markerSchemaVersion: 2,
        packageManager: oldPackageManager,
        toolchain: { node: "22.22.0", pnpm: "9.14.4", uv: "0.10.0" },
      },
      requiresRebuild: true,
      revision,
    });
    expect(test.snapshotSourceTree).not.toHaveBeenCalled();
  });

  it("accepts an older valid bound build and marks it for a same-revision rebuild", async () => {
    const oldPackageManager = "pnpm@9.14.4+sha512.legacy";
    const test = fixture({
      markerOverrides: {
        node: "22.22.0",
        packageManager: oldPackageManager,
        pnpm: "9.14.4",
        uv: "0.10.0",
      },
      packageManagerPin: oldPackageManager,
    });

    await expect(validateActiveSourceProvenance(test.request)).resolves.toMatchObject({
      buildIdentity: {
        frontendOutputDigest,
        markerSchemaVersion: 3,
        packageManager: oldPackageManager,
      },
      requiresRebuild: true,
      revision,
    });
  });

  it.each([
    ["missing", "missing"],
    ["mutated", "mutated"],
  ] as const)("rejects %s terminal output before returning trusted provenance", async (_label, frontendOutput) => {
    const test = fixture({ frontendOutput });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/terminal|output|dist|identity/i);
  });

  it.each([
    ["HEAD", { gitHead: "1".repeat(40) }, /HEAD|revision|marker/i],
    ["tree", { gitTree: "2".repeat(40) }, /tree|content|marker/i],
  ] as const)("rejects a Git %s that disagrees with the marker", async (_label, differences, message) => {
    const test = fixture(differences);

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
  });

  it("rejects a Git origin other than the configured public repository", async () => {
    const test = fixture({ gitOrigin: "git@github.com:someone-else/FlintTrade.git" });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /origin|foreign|config|unexpected/i,
    );
  });

  it("reads the raw local origin without allowing url.insteadOf to forge the expected repository", async () => {
    const test = await realGitFixture();
    const foreignOrigin = "https://example.invalid/foreign.git";
    runFixtureGit(test.root, test.activeSource, ["remote", "set-url", "origin", foreignOrigin]);
    runFixtureGit(test.root, test.activeSource, ["config", `url.${gitOrigin}.insteadOf`, foreignOrigin]);
    expect(runFixtureGit(test.root, test.activeSource, ["remote", "get-url", "origin"]).trim()).toBe(gitOrigin);

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /origin|foreign|config|unexpected/i,
    );
  });

  it("does not let the inherited HOME global ignore file hide an untracked source input", async () => {
    const test = await realGitFixture();
    await mkdir(path.join(test.root, "home", ".config", "git"), { recursive: true });
    await writeFile(path.join(test.root, "home", ".config", "git", "ignore"), "hidden-source.py\n");
    await writeFile(path.join(test.activeSource, "hidden-source.py"), "print('hidden')\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /dirty|untracked|source|change/i,
    );
  });

  it("accepts mtime-only tracked files without rewriting the hardened Git index", async () => {
    const test = await realGitFixture();
    const fileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;
    const indexPath = path.join(test.activeSource, ".git", "index");
    const initialIndexIdentity = await fileSystem.fileIdentity(indexPath);
    const futureMtime = new Date(Date.now() + 60_000);
    await utimes(path.join(test.activeSource, "uv.lock"), futureMtime, futureMtime);

    await expect(validateActiveSourceProvenance(test.request)).resolves.toMatchObject({
      contentIdentity: test.installedTree,
      provenance: "git",
      revision: test.installedRevision,
    });
    await expect(fileSystem.fileIdentity(indexPath)).resolves.toEqual(initialIndexIdentity);
  });

  it("rejects a real tracked content change after invalidating the stat cache", async () => {
    const test = await realGitFixture();
    await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /tracked|worktree|dirty|change/i,
    );
  });

  it.runIf(process.platform !== "win32")(
    "detects a POSIX mode change even when local core.filemode is false",
    async () => {
      const test = await realGitFixture();
      runFixtureGit(test.root, test.activeSource, ["config", "core.filemode", "false"]);
      await chmod(path.join(test.activeSource, "package.json"), 0o755);

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /dirty|tracked|mode|change/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a symlinked .git directory before any Git command can follow it",
    async () => {
      const test = await realGitFixture();
      const gitDirectory = path.join(test.activeSource, ".git");
      const relocatedGitDirectory = path.join(test.root, "relocated-git-directory");
      await rename(gitDirectory, relocatedGitDirectory);
      await symlink(relocatedGitDirectory, gitDirectory, "dir");

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /\.git|symbolic|no-follow|canonical|directory/i,
      );
      expect(test.command).not.toHaveBeenCalled();
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a dirty flagged original index when a clean replacement .git is used only by Git commands",
    async () => {
      const test = await realGitFixture();
      const gitDirectory = path.join(test.activeSource, ".git");
      const cleanGitDirectory = path.join(test.root, "clean-command-git-directory");
      const displacedGitDirectory = path.join(test.root, "dirty-original-git-directory");
      await cp(gitDirectory, cleanGitDirectory, { recursive: true });

      const uvLock = path.join(test.activeSource, "uv.lock");
      await writeFile(uvLock, "version = 2\n");
      runFixtureGit(test.root, test.activeSource, ["add", "--", "uv.lock"]);
      await writeFile(uvLock, "version = 1\n");
      runFixtureGit(test.root, test.activeSource, ["update-index", "--assume-unchanged", "--", "uv.lock"]);
      expect(runFixtureGit(test.root, test.activeSource, ["ls-files", "-v", "--", "uv.lock"]))
        .toMatch(/^h /);
      expect(() => runFixtureGit(test.root, test.activeSource, [
        "diff-index", "--cached", "--quiet", "HEAD", "--", "uv.lock",
      ])).toThrow();

      // Refresh the clean replacement against the restored worktree so the
      // attack does not depend on Git's racy-clean stat-cache timing.
      await rename(gitDirectory, displacedGitDirectory);
      await rename(cleanGitDirectory, gitDirectory);
      runFixtureGit(test.root, test.activeSource, ["update-index", "--really-refresh"]);
      await rename(gitDirectory, cleanGitDirectory);
      await rename(displacedGitDirectory, gitDirectory);

      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        await rename(gitDirectory, displacedGitDirectory);
        await rename(cleanGitDirectory, gitDirectory);
        try {
          return await actualRun(invocation);
        } finally {
          await rename(gitDirectory, cleanGitDirectory);
          await rename(displacedGitDirectory, gitDirectory);
        }
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /metadata|directory|identity|changed/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a dirty original checkout when a clean replacement active root is used only by Git commands",
    async () => {
      const test = await realGitFixture();
      const sourceRoot = path.dirname(test.activeSource);
      const cleanActiveSource = path.join(sourceRoot, "FlintTrade.clean-command-source");
      const displacedActiveSource = path.join(sourceRoot, "FlintTrade.dirty-original-source");
      await rename(test.activeSource, cleanActiveSource);
      await cp(cleanActiveSource, test.activeSource, { recursive: true });
      await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");
      expect(() => runFixtureGit(test.root, test.activeSource, [
        "diff-files", "--quiet", "--", "uv.lock",
      ])).toThrow();

      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        await rename(test.activeSource, displacedActiveSource);
        await rename(cleanActiveSource, test.activeSource);
        try {
          return await actualRun(invocation);
        } finally {
          await rename(test.activeSource, cleanActiveSource);
          await rename(displacedActiveSource, test.activeSource);
        }
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /active source|directory|identity|changed/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "binds the checkout root inside direct hardened Git inspection",
    async () => {
      const test = await realGitFixture();
      const sourceRoot = path.dirname(test.activeSource);
      const cleanActiveSource = path.join(sourceRoot, "FlintTrade.clean-direct-inspection");
      const displacedActiveSource = path.join(sourceRoot, "FlintTrade.dirty-direct-inspection");
      await rename(test.activeSource, cleanActiveSource);
      await cp(cleanActiveSource, test.activeSource, { recursive: true });
      await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        await rename(test.activeSource, displacedActiveSource);
        await rename(cleanActiveSource, test.activeSource);
        try {
          return await actualRun(invocation);
        } finally {
          await rename(test.activeSource, cleanActiveSource);
          await rename(displacedActiveSource, test.activeSource);
        }
      });

      await expect(inspectHardenedGitCheckout({
        bootstrapResources,
        dependencies: test.request.dependencies,
        expected: {
          branch: "main",
          origin: gitOrigin,
          revision: test.installedRevision,
          tree: test.installedTree,
        },
        platform: process.platform,
        root: test.activeSource,
        signal: test.request.signal,
      })).rejects.toThrow(/checkout|directory|metadata|identity|changed/i);
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects info-exclude metadata changed only around untracked-source inspection",
    async () => {
      const test = await realGitFixture();
      const excludePath = path.join(test.activeSource, ".git", "info", "exclude");
      const safeExclude = await readFile(excludePath, "utf8");
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        if (!invocation.args.includes("--others")) return actualRun(invocation);
        await writeFile(excludePath, "# transient mutation\n");
        try {
          return await actualRun(invocation);
        } finally {
          await writeFile(excludePath, safeExclude);
        }
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /info|exclude|metadata|identity|changed/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects an object alternate inserted only around object inspection",
    async () => {
      const test = await realGitFixture();
      const alternatePath = path.join(test.activeSource, ".git", "objects", "info", "alternates");
      const externalObjects = path.join(test.root, "external-objects");
      await mkdir(externalObjects);
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        if (!invocation.args.some((argument) => argument.endsWith("^{tree}"))) {
          return actualRun(invocation);
        }
        await writeFile(alternatePath, `${externalObjects}\n`);
        try {
          return await actualRun(invocation);
        } finally {
          await rm(alternatePath, { force: true });
        }
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /object|alternate|metadata|identity|changed/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "reproves object metadata after the final Git command settles",
    async () => {
      const test = await realGitFixture();
      const alternatePath = path.join(test.activeSource, ".git", "objects", "info", "alternates");
      const externalObjects = path.join(test.root, "late-external-objects");
      await mkdir(externalObjects);
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      let headInspections = 0;
      test.command.mockImplementation(async (invocation) => {
        const result = await actualRun(invocation);
        if (invocation.args.at(-2) === "rev-parse" && invocation.args.at(-1) === "HEAD") {
          headInspections += 1;
          if (headInspections === 2) await writeFile(alternatePath, `${externalObjects}\n`);
        }
        return result;
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /object|alternate|metadata|identity|changed/i,
      );
      expect(headInspections).toBe(2);
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a packaged Git common root replaced only around untracked-source inspection",
    async () => {
      const test = await realGitFixture();
      const resourceRoot = path.join(test.root, "bootstrap-resources");
      const replacementRoot = path.join(test.root, "bootstrap-resources.replacement");
      const displacedRoot = path.join(test.root, "bootstrap-resources.displaced");
      await cp(bootstrapResources, resourceRoot, { recursive: true });
      await cp(resourceRoot, replacementRoot, { recursive: true });
      await mkdir(path.join(replacementRoot, "git-common", "info"));
      await writeFile(
        path.join(replacementRoot, "git-common", "info", "exclude"),
        "hidden-source.py\n",
      );
      await writeFile(path.join(test.activeSource, "hidden-source.py"), "print('hidden')\n");
      test.request.bootstrapResources = resourceRoot;
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        if (!invocation.args.includes("--others")) return actualRun(invocation);
        await rename(resourceRoot, displacedRoot);
        await rename(replacementRoot, resourceRoot);
        try {
          return await actualRun(invocation);
        } finally {
          await rename(resourceRoot, replacementRoot);
          await rename(displacedRoot, resourceRoot);
        }
      });

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /packaged|resource|common|directory|metadata|identity|changed/i,
      );
    },
  );

  it.runIf(process.platform !== "win32")(
    "rejects a symlinked active Git index before any Git command can follow it",
    async () => {
      const test = await realGitFixture();
      const indexPath = path.join(test.activeSource, ".git", "index");
      const externalIndex = path.join(test.root, "external-index");
      await rename(indexPath, externalIndex);
      await symlink(externalIndex, indexPath);

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /index|no-follow|regular file/i,
      );
      expect(test.command).not.toHaveBeenCalled();
    },
  );

  it.runIf(process.platform !== "win32")(
    "cannot execute a clean filter swapped into local config and info attributes during inspection",
    async () => {
      const test = await realGitFixture();
      const filter = path.join(test.root, "swap-filter.sh");
      const canary = `${filter}.called`;
      await writeFile(filter, "#!/bin/sh\n: > \"$0.called\"\ncat\n");
      await chmod(filter, 0o755);
      const configPath = path.join(test.activeSource, ".git", "config");
      const attributesPath = path.join(test.activeSource, ".git", "info", "attributes");
      const safeConfig = await readFile(configPath, "utf8");
      const hostileConfig = `${safeConfig}\n[filter \"swapped\"]\n\tclean = ${filter}\n`;
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => {
        const cleanlinessCommand = invocation.args.includes("status") || invocation.args.includes("diff-files");
        if (!cleanlinessCommand) return actualRun(invocation);
        await writeFile(configPath, hostileConfig);
        await writeFile(attributesPath, "uv.lock filter=swapped\n");
        try {
          return await actualRun(invocation);
        } finally {
          await writeFile(configPath, safeConfig);
          await rm(attributesPath, { force: true });
        }
      });
      // A future-dated index entry is deterministically racy-clean: Git must
      // inspect the unchanged content, while diff-files still exits clean.
      const uvLock = path.join(test.activeSource, "uv.lock");
      const racyMtime = new Date(Date.now() + 60_000);
      await utimes(uvLock, racyMtime, racyMtime);
      runFixtureGit(test.root, test.activeSource, ["add", "--", "uv.lock"]);
      const fileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;

      await writeFile(configPath, hostileConfig);
      await writeFile(attributesPath, "uv.lock filter=swapped\n");
      try {
        runFixtureGit(test.root, test.activeSource, ["diff-files", "--quiet", "--", "uv.lock"]);
        await expect(fileSystem.existsNoFollow(canary)).resolves.toBe(true);
      } finally {
        await writeFile(configPath, safeConfig);
        await rm(attributesPath, { force: true });
        await rm(canary, { force: true });
      }

      try {
        await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
          /metadata|config|identity|changed/i,
        );
      } finally {
        await expect(fileSystem.existsNoFollow(canary)).resolves.toBe(false);
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "disables a checkout-local fsmonitor command before inspecting worktree cleanliness",
    async () => {
      const test = await realGitFixture();
      const monitor = path.join(test.root, "hostile-fsmonitor.sh");
      const canary = `${monitor}.called`;
      await writeFile(monitor, "#!/bin/sh\n: > \"$0.called\"\nprintf 'fixture-token\\n'\n");
      await chmod(monitor, 0o755);
      runFixtureGit(test.root, test.activeSource, ["config", "core.fsmonitor", monitor]);

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
        /config|fsmonitor|executable|unexpected/i,
      );
      await expect(createNodeBootstrapDependencies(process.platform).fileSystem.existsNoFollow(canary)).resolves.toBe(false);
    },
  );

  it("pins worktree inspection to the managed active source despite checkout-local core.worktree", async () => {
    const test = await realGitFixture();
    const redirectedWorktree = path.join(test.root, "redirected-worktree");
    for (const relative of REQUIRED_REAL_GIT_PATHS) {
      const source = path.join(test.activeSource, ...relative.split("/"));
      const destination = path.join(redirectedWorktree, ...relative.split("/"));
      await mkdir(path.dirname(destination), { recursive: true });
      await cp(source, destination);
    }
    runFixtureGit(test.root, test.activeSource, ["config", "core.worktree", redirectedWorktree]);
    await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /config|worktree|unexpected|dirty|tracked|change/i,
    );
  });

  it.each([
    ["shared commondir metadata", ["commondir"], /commondir|shared|metadata/i],
    ["alternate object storage", ["objects", "info", "alternates"], /alternate|object|storage/i],
  ] as const)("rejects checkout-local %s before Git object inspection", async (_label, components, message) => {
    const test = await realGitFixture();
    const controlPath = path.join(test.activeSource, ".git", ...components);
    await mkdir(path.dirname(controlPath), { recursive: true });
    await writeFile(controlPath, "../hostile\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
    expect(test.command).not.toHaveBeenCalled();
  });

  it.each([
    ["shared commondir metadata", ["commondir"], /commondir|shared|metadata/i],
    ["alternate object storage", ["objects", "info", "alternates"], /alternate|object|storage/i],
  ] as const)("detects %s acquired during Git inspection", async (_label, components, message) => {
    const test = await realGitFixture();
    const controlPath = path.join(test.activeSource, ".git", ...components);
    const actualRun = test.command.getMockImplementation();
    if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
    test.command.mockImplementation(async (invocation) => {
      const result = await actualRun(invocation);
      if (invocation.args.includes("status")) {
        await mkdir(path.dirname(controlPath), { recursive: true });
        await writeFile(controlPath, "../hostile\n");
      }
      return result;
    });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
  });

  it("rejects active info-attributes rules outside the committed source tree", async () => {
    const test = await realGitFixture();
    await writeFile(path.join(test.activeSource, ".git", "info", "attributes"), "uv.lock filter=hostile\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/attributes|conversion|committed/i);
  });

  it("disables replacement refs before binding the active HEAD tree to its marker", async () => {
    const test = await realGitFixture();
    await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");
    runFixtureGit(test.root, test.activeSource, ["add", "--", "uv.lock"]);
    runFixtureGit(test.root, test.activeSource, [
      "-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "replacement",
    ]);
    const replacementRevision = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD"]).trim();
    const replacementTree = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD^{tree}"]).trim();
    runFixtureGit(test.root, test.activeSource, ["reset", "--hard", test.installedRevision]);
    runFixtureGit(test.root, test.activeSource, ["read-tree", "--reset", "-u", replacementRevision]);
    runFixtureGit(test.root, test.activeSource, ["replace", test.installedRevision, replacementRevision]);
    await test.writeMarker({ gitTree: replacementTree });
    expect(runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD^{tree}"]).trim()).toBe(replacementTree);

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/tree|content|marker/i);
  });

  it("rejects an attached branch ref changed after the selected revision was inspected", async () => {
    const test = await realGitFixture();
    await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");
    runFixtureGit(test.root, test.activeSource, ["add", "--", "uv.lock"]);
    runFixtureGit(test.root, test.activeSource, [
      "-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "other",
    ]);
    const otherRevision = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD"]).trim();
    runFixtureGit(test.root, test.activeSource, ["reset", "--hard", test.installedRevision]);
    const actualRun = test.command.getMockImplementation();
    if (!actualRun) throw new Error("Missing real Git fixture command implementation.");
    let branchChanged = false;
    test.command.mockImplementation(async (invocation) => {
      const result = await actualRun(invocation);
      if (!branchChanged && invocation.args.includes("status")) {
        branchChanged = true;
        runFixtureGit(test.root, test.activeSource, ["update-ref", "refs/heads/main", otherRevision]);
      }
      return result;
    });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(
      /HEAD|branch|loose.ref|changed|revision/i,
    );
    expect(branchChanged).toBe(true);
  });

  it.runIf(process.platform !== "win32")(
    "rejects an executable local clean filter before Git can invoke it during status",
    async () => {
      const test = await realGitFixture();
      const filter = path.join(test.root, "hostile-clean-filter.sh");
      const canary = `${filter}.called`;
      await writeFile(filter, "#!/bin/sh\n: > \"$0.called\"\ncat\n");
      await chmod(filter, 0o755);
      await writeFile(path.join(test.activeSource, ".gitattributes"), "uv.lock filter=hostile\n");
      runFixtureGit(test.root, test.activeSource, ["add", "--", ".gitattributes"]);
      runFixtureGit(test.root, test.activeSource, [
        "-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "attributes",
      ]);
      const currentRevision = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD"]).trim();
      const currentTree = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD^{tree}"]).trim();
      await test.writeMarker({ gitTree: currentTree, revision: currentRevision });
      runFixtureGit(test.root, test.activeSource, ["config", "filter.hostile.clean", filter]);

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/config|filter|executable/i);
      await expect(createNodeBootstrapDependencies(process.platform).fileSystem.existsNoFollow(canary)).resolves.toBe(false);
    },
  );

  it("rejects active info-exclude rules that can hide an untracked source file", async () => {
    const test = await realGitFixture();
    await writeFile(path.join(test.activeSource, ".git", "info", "exclude"), "hidden-source.py\n");
    await writeFile(path.join(test.activeSource, "hidden-source.py"), "print('hidden')\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/exclude|untracked|dirty/i);
  });

  it.each([
    ["assume-unchanged", "--assume-unchanged"],
    ["skip-worktree", "--skip-worktree"],
  ] as const)("rejects the %s index flag before it can hide a tracked change", async (_label, flag) => {
    const test = await realGitFixture();
    runFixtureGit(test.root, test.activeSource, ["update-index", flag, "--", "uv.lock"]);
    await writeFile(path.join(test.activeSource, "uv.lock"), "version = 2\n");

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/index|hidden|tracked|flag/i);
  });

  it.runIf(process.platform !== "win32")(
    "rejects a real aligned ls-files tail that truncates an initial assume-unchanged record",
    async () => {
      const test = await realGitFixture();
      const directory = path.join(test.activeSource, "zz-truncation");
      await mkdir(directory);
      const relativePaths = Array.from({ length: 4_097 }, (_unused, index) => {
        const prefix = `zz-truncation/${String(index).padStart(4, "0")}-`;
        return `${prefix}${"x".repeat(61 - prefix.length)}`;
      });
      expect(relativePaths.every((relative) => relative.length === 61)).toBe(true);
      for (let offset = 0; offset < relativePaths.length; offset += 128) {
        await Promise.all(relativePaths.slice(offset, offset + 128).map((relative) =>
          writeFile(path.join(test.activeSource, relative), "tracked\n"),
        ));
      }
      runFixtureGit(test.root, test.activeSource, ["add", "--", "zz-truncation"]);
      runFixtureGit(test.root, test.activeSource, [
        "-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "aligned-index",
      ]);
      const currentRevision = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD"]).trim();
      const currentTree = runFixtureGit(test.root, test.activeSource, ["rev-parse", "HEAD^{tree}"]).trim();
      await test.writeMarker({ gitTree: currentTree, revision: currentRevision });
      runFixtureGit(test.root, test.activeSource, ["update-index", "--assume-unchanged", "--", relativePaths[0]!]);
      const bounded = createNodeBootstrapDependencies(process.platform);
      const request: SourceProvenanceRequest = {
        ...test.request,
        dependencies: {
          command: { run: bounded.command.run },
          fileSystem: test.request.dependencies.fileSystem,
        },
      };

      await expect(validateActiveSourceProvenance(request)).rejects.toThrow(/truncat|incomplete|output/i);
    },
    30_000,
  );

  it.each(["stdoutTruncated", "stderrTruncated"] as const)(
    "rejects Git inspection when %s is reported",
    async (truncated) => {
      const test = fixture();
      const actualRun = test.command.getMockImplementation();
      if (!actualRun) throw new Error("Missing Git fixture command implementation.");
      test.command.mockImplementation(async (invocation) => ({
        ...await actualRun(invocation),
        [truncated]: true,
      }));

      await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/truncat|incomplete|output/i);
    },
  );

  it("retains the operation lease when active Git inspection cannot prove containment", async () => {
    const test = fixture({ gitContained: false });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    );
  });

  it.each([
    ["tracked change", " M uv.lock\0"],
    ["staged change", "A  local.patch\0"],
    ["nonignored untracked file", "?? local-notes.txt\0"],
  ])("rejects a dirty Git checkout with a %s", async (_label, gitStatus) => {
    const test = fixture({ gitStatus });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/dirty|tracked|untracked|change/i);
  });

  it("rejects a repository-root .env even when Git reports a clean checkout", async () => {
    const test = fixture({ includeEnvironmentFile: true });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/\.env|environment/i);
  });

  it.each([
    ["missing repository shape", { missingShapePath: "uv.lock" }, /uv\.lock|shape|foreign/i],
    ["foreign package identity", { packageName: "foreign-monorepo" }, /package|identity|foreign/i],
  ] as const)("rejects a %s", async (_label, differences, message) => {
    const test = fixture(differences);

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
  });

  it("rejects an unmarked or ambiguously marked active source", async () => {
    const unmarked = fixture({ includeGitMarker: false });
    await expect(validateActiveSourceProvenance(unmarked.request)).rejects.toThrow(/marker|foreign/i);

    const ambiguous = fixture({ includeArchiveMarker: true });
    await expect(validateActiveSourceProvenance(ambiguous.request)).rejects.toThrow(/marker|ambiguous|provenance/i);
  });

  it.each(["candidate", "last-known-good"] as const)("rejects an active source aliased to the %s path", async (alias) => {
    const test = fixture({ alias });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/alias|identity/i);
    expect(test.command).not.toHaveBeenCalled();
  });

  it("rejects an active source whose canonical path escapes the managed source root", async () => {
    const test = fixture({ activeRealpath: "/outside/FlintTrade" });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(/alias|managed|source root/i);
    expect(test.command).not.toHaveBeenCalled();
  });

  it("proves archive provenance from the exact marker, record digest and source-input identity", async () => {
    const test = fixture({ provenance: "github-archive" });

    await expect(validateActiveSourceProvenance(test.request)).resolves.toEqual({
      archiveFinalOrigin: archiveOrigin,
      archiveSha256,
      buildIdentity: currentBuildIdentity,
      canonicalPath: activeSource,
      contentIdentity: sourceInputDigest,
      directoryIdentity: { dev: 9, ino: 90 },
      provenance: "github-archive",
      requiresRebuild: false,
      revision,
    });
    expect(test.command).not.toHaveBeenCalled();
    expect(test.verifySourceTree).toHaveBeenCalledWith(
      activeSource,
      sourceTree,
      expect.arrayContaining([".venv", "packages/apps/terminal/dist"]),
      [BOOTSTRAP_MARKER, SOURCE_INPUTS_RECORD],
    );
  });

  it.each([
    ["foreign archive origin", { markerOverrides: { archiveFinalOrigin: "https://example.test" } }, /origin|archive/i],
    ["changed source-input record", { archiveRecordHash: "3".repeat(64) }, /record|digest|identity/i],
    ["changed source inputs", { verifyArchiveTree: false }, /source|content|identity|changed/i],
  ] as const)("rejects a %s", async (_label, differences, message) => {
    const test = fixture({ provenance: "github-archive", ...differences });

    await expect(validateActiveSourceProvenance(test.request)).rejects.toThrow(message);
  });
});

interface RevisionFixtureOptions {
  archiveAllowedHosts?: readonly string[];
  branch?: string;
  gitContained?: boolean;
  gitExitCode?: number;
  gitStderrTruncated?: boolean;
  gitStdout?: string;
  gitStdoutTruncated?: boolean;
  metadataContent?: string;
  metadataError?: Error;
  metadataFinalUrl?: string;
  metadataOrigin?: string;
  metadataSha256?: string;
}

function revisionFixture(options: RevisionFixtureOptions = {}) {
  const metadataContent = options.metadataContent ?? JSON.stringify({ sha: revision });
  const command = vi.fn<SourceRevisionDependencies["command"]["run"]>(async () => ({
    contained: options.gitContained ?? true,
    exitCode: options.gitExitCode ?? 0,
    stderr: options.gitExitCode ? "git unavailable" : "",
    stderrTruncated: options.gitStderrTruncated ?? false,
    stdout: options.gitStdout ?? `${revision}\trefs/heads/main\n`,
    stdoutTruncated: options.gitStdoutTruncated ?? false,
  }));
  const downloadText = vi.fn<SourceRevisionDependencies["download"]["text"]>(
    async (_url, _signal, _policy) => {
      if (options.metadataError) throw options.metadataError;
      const finalUrl = options.metadataFinalUrl ?? commitMetadataUrl;
      return {
        bytes: Buffer.byteLength(metadataContent),
        content: metadataContent,
        finalUrl,
        origin: options.metadataOrigin ?? new URL(finalUrl).origin,
        sha256: options.metadataSha256 ?? sha256(metadataContent),
      };
    },
  );
  const dependencies: SourceRevisionDependencies = {
    command: { run: command },
    download: { text: downloadText },
  };
  const controller = new AbortController();
  const request: SourceRevisionRequest = {
    dependencies,
    platform: "darwin",
    repository: {
      archiveAllowedHosts: options.archiveAllowedHosts ?? ["codeload.github.com"],
      archiveBaseUrl,
      branch: options.branch ?? "main",
      commitMetadataUrl,
      gitOrigin,
      metadataAllowedHosts: ["api.github.com"],
    },
    signal: controller.signal,
  };
  return { command, controller, downloadText, request };
}

describe("exact source revision resolution", () => {
  it("resolves one exact configured branch revision with a contained, sanitised Git invocation", async () => {
    const test = revisionFixture();

    await expect(resolveExactSourceRevision(test.request)).resolves.toEqual({ provenance: "git", revision });
    expect(test.command).toHaveBeenCalledOnce();
    expect(test.command).toHaveBeenCalledWith({
      args: [
        "--no-optional-locks",
        "--no-replace-objects",
        "--git-dir=/dev/null",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "ls-remote",
        "--exit-code",
        "--refs",
        gitOrigin,
        "refs/heads/main",
      ],
      command: "git",
      cwd: path.dirname(process.execPath),
      env: {
        GIT_CEILING_DIRECTORIES: path.dirname(process.execPath),
        GIT_CONFIG_GLOBAL: "/dev/null",
        GIT_CONFIG_NOSYSTEM: "1",
        GIT_CONFIG_SYSTEM: "/dev/null",
        GIT_TERMINAL_PROMPT: "0",
      },
      signal: test.controller.signal,
      timeoutMs: 30_000,
    });
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it.each([
    ["abbreviated object", `abc123\trefs/heads/main\n`],
    ["wrong ref", `${revision}\trefs/heads/other\n`],
    ["multiple results", `${revision}\trefs/heads/main\n${"1".repeat(40)}\trefs/heads/main\n`],
  ])("rejects a successful Git response with an inexact %s", async (_label, gitStdout) => {
    const test = revisionFixture({ gitStdout });

    await expect(resolveExactSourceRevision(test.request)).rejects.toThrow(/Git|revision|ref|exact/i);
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it.each(["stdout", "stderr"] as const)(
    "rejects a successful exact Git revision when %s was truncated",
    async (stream) => {
      const test = revisionFixture({
        ...(stream === "stdout" ? { gitStdoutTruncated: true } : { gitStderrTruncated: true }),
      });

      await expect(resolveExactSourceRevision(test.request)).rejects.toThrow(/truncat|incomplete|output/i);
      expect(test.downloadText).not.toHaveBeenCalled();
    },
  );

  it("falls back to trusted commit metadata and returns the commit-pinned archive identity", async () => {
    const redirectedMetadataUrl = "https://api.github.com/repository-metadata/resolved-main";
    const test = revisionFixture({ gitExitCode: 127, metadataFinalUrl: redirectedMetadataUrl });

    await expect(resolveExactSourceRevision(test.request)).resolves.toEqual({
      archiveOrigin,
      archiveUrl: `${archiveBaseUrl}/${revision}`,
      provenance: "github-archive",
      revision,
    });
    expect(test.downloadText).toHaveBeenCalledWith(
      commitMetadataUrl,
      test.controller.signal,
      expect.objectContaining({
        allowedHosts: ["api.github.com"],
        label: "FlintTrade source revision metadata",
        maxBytes: 1024 * 1024,
      }),
    );
  });

  it("does not downgrade a command-containment failure to the archive fallback", async () => {
    const test = revisionFixture({ gitContained: false, gitExitCode: 1 });

    const resolution = resolveExactSourceRevision(test.request);
    await expect(resolution).rejects.toThrow(/containment/i);
    await expect(resolution).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it("does not downgrade a rejected Git command runner to the archive fallback", async () => {
    const test = revisionFixture();
    test.command.mockRejectedValueOnce(new Error("command runner rejected"));

    await expect(resolveExactSourceRevision(test.request)).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    );
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it.each([
    [
      "foreign metadata redirect",
      { gitExitCode: 127, metadataFinalUrl: "https://example.test/commit", metadataOrigin: "https://example.test" },
      /metadata|origin|host|trusted/i,
    ],
    ["non-commit metadata", { gitExitCode: 127, metadataContent: "{\"sha\":\"abc123\"}" }, /commit|revision/i],
    ["metadata content mismatch", { gitExitCode: 127, metadataSha256: "4".repeat(64) }, /metadata|content/i],
    ["metadata transport failure", { gitExitCode: 127, metadataError: new Error("offline") }, /metadata|offline/i],
  ] as const)("fails closed after a %s", async (_label, differences, message) => {
    const test = revisionFixture(differences);

    await expect(resolveExactSourceRevision(test.request)).rejects.toThrow(message);
  });

  it("rejects an unsafe configured branch before invoking Git or metadata", async () => {
    const test = revisionFixture({ branch: "main --upload-pack=malicious" });

    await expect(resolveExactSourceRevision(test.request)).rejects.toThrow(/branch|ref/i);
    expect(test.command).not.toHaveBeenCalled();
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it("rejects an untrusted archive host before accepting metadata fallback", async () => {
    const test = revisionFixture({ archiveAllowedHosts: ["example.test"], gitExitCode: 127 });

    await expect(resolveExactSourceRevision(test.request)).rejects.toThrow(/archive|host|trusted/i);
    expect(test.downloadText).not.toHaveBeenCalled();
  });

  it("honours cancellation before any Git or metadata operation", async () => {
    const test = revisionFixture();
    test.controller.abort();

    await expect(resolveExactSourceRevision(test.request)).rejects.toMatchObject({ name: "AbortError" });
    expect(test.command).not.toHaveBeenCalled();
    expect(test.downloadText).not.toHaveBeenCalled();
  });
});
