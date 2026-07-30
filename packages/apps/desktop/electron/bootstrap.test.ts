import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { once } from "node:events";
import {
  access,
  appendFile,
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  symlink,
  utimes,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { build } from "esbuild";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

import {
  BOOTSTRAP_MARKER,
  SOURCE_INPUTS_RECORD,
  createFirstRunBootstrap,
  type BootstrapBoundary,
  type BootstrapDependencies,
  type BootstrapToolManifest,
  type CommandInvocation,
} from "./bootstrap";
import { createNodeBootstrapDependencies, setDurabilityFsyncForTesting } from "./bootstrap-io";
import { createBootstrapQuitGate } from "./bootstrap-shutdown";
import { SourceOperationLeaseRetentionError } from "./source-operation";
import { createBootstrapState } from "./state";

// This suite pays ~45-60 fsync barriers per controller.start() through the
// durable-log and promotion paths, ~90 starts per run. No assertion here
// depends on data surviving a kernel crash (killed fixture processes keep
// the page cache), so the raw syscalls are disabled — writes, identity
// re-checks and every testHook still run. The bundled crash fixtures run in
// their own processes with their own module instance, where the flag stays
// at its production default.
setDurabilityFsyncForTesting(false);

// Crash-fixture bundles are memoised per variant: esbuild-bundling
// bootstrap-io plus its tar/yauzl dependency trees costs seconds, and the
// output is identical for every test that requests the same variant.
const crashFixtureBundles = new Map<string, Promise<string>>();
let crashFixtureBundleRoot: Promise<string> | undefined;

async function crashFixtureBundle(variant: string, make: (outfile: string) => Promise<unknown>): Promise<string> {
  let bundle = crashFixtureBundles.get(variant);
  if (!bundle) {
    bundle = (async () => {
      crashFixtureBundleRoot ??= mkdtemp(path.join(tmpdir(), "flinttrade-crash-fixture-bundles-"));
      const outfile = path.join(await crashFixtureBundleRoot, `${variant}.mjs`);
      await make(outfile);
      return outfile;
    })();
    crashFixtureBundles.set(variant, bundle);
  }
  return bundle;
}

afterAll(async () => {
  if (crashFixtureBundleRoot) await rm(await crashFixtureBundleRoot, { force: true, recursive: true });
});

const revision = "a".repeat(40);
const nodeBytes = Buffer.from("pinned node archive");
const uvBytes = Buffer.from("pinned uv archive");
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
const manifest: BootstrapToolManifest = {
  schemaVersion: 1,
  generatedFrom: {
    node: {
      sha256: "1".repeat(64),
      signature: {
        fingerprint: "890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4",
        keySha256: "3".repeat(64),
        sha256: "4".repeat(64),
        url: "https://nodejs.org/dist/v22.23.1/SHASUMS256.txt.sig",
      },
      url: "https://nodejs.org/dist/v22.23.1/SHASUMS256.txt",
    },
    uv: { sha256: "2".repeat(64), url: "https://github.com/astral-sh/uv/releases/download/0.11.16/sha256.sum" },
  },
  node: {
    version: "22.23.1",
    assets: {
      "darwin-arm64": {
        archive: "tar.gz",
        executable: "node-v22.23.1-darwin-arm64/bin/node",
        sha256: sha256(nodeBytes),
        url: "https://nodejs.org/dist/v22.23.1/node-v22.23.1-darwin-arm64.tar.gz",
      },
      "win32-x64": {
        archive: "zip",
        executable: "node-v22.23.1-win-x64/node.exe",
        sha256: sha256(nodeBytes),
        url: "https://nodejs.org/dist/v22.23.1/node-v22.23.1-win-x64.zip",
      },
    },
  },
  pnpm: { integrity: "sha512-test", packageManager: "pnpm@9.15.0+sha512.test", version: "9.15.0" },
  uv: {
    version: "0.11.16",
    assets: {
      "darwin-arm64": {
        archive: "tar.gz",
        executable: "uv-aarch64-apple-darwin/uv",
        sha256: sha256(uvBytes),
        url: "https://github.com/astral-sh/uv/releases/download/0.11.16/uv-aarch64-apple-darwin.tar.gz",
      },
      "win32-x64": {
        archive: "zip",
        // Flat on purpose: uv's Windows zip has uv.exe at the archive root,
        // unlike its Unix tarballs (and unlike Node, which nests on every
        // platform). This fixture previously mirrored the manifest's incorrect
        // nested path, so it agreed with the bug instead of catching it.
        executable: "uv.exe",
        sha256: sha256(uvBytes),
        url: "https://github.com/astral-sh/uv/releases/download/0.11.16/uv-x86_64-pc-windows-msvc.zip",
      },
    },
  },
};

const scratchRoots: string[] = [];

async function exists(target: string): Promise<boolean> {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function writeRepositoryShape(
  root: string,
  git: boolean,
  platform: "darwin" | "win32" = "darwin",
  origin = "https://github.com/navaneeshnagarajan/FlintTrade.git",
): Promise<void> {
  await mkdir(path.join(root, "packages", "apps", "terminal"), { recursive: true });
  if (git) {
    const gitDirectory = path.join(root, ".git");
    await mkdir(path.join(gitDirectory, "info"), { recursive: true });
    await mkdir(path.join(gitDirectory, "objects", "info"), { recursive: true });
    await mkdir(path.join(gitDirectory, "refs", "heads"), { recursive: true });
    await writeFile(path.join(gitDirectory, "HEAD"), "ref: refs/heads/main\n");
    await writeFile(path.join(gitDirectory, "refs", "heads", "main"), `${revision}\n`);
    await writeFile(path.join(gitDirectory, "index"), "fixture-index\n");
    await writeFile(
      path.join(gitDirectory, "config"),
      `[core]\n\trepositoryformatversion = 0\n\tfilemode = ${platform !== "win32"}\n\tbare = false\n\tlogallrefupdates = true\n[remote "origin"]\n\turl = ${origin}\n\tfetch = +refs/heads/main:refs/remotes/origin/main\n\ttagOpt = --no-tags\n[branch "main"]\n\tremote = origin\n\tmerge = refs/heads/main\n`,
    );
  }
  await writeFile(
    path.join(root, "package.json"),
    JSON.stringify({ name: "flinttrade-monorepo", packageManager: "pnpm@9.15.0+sha512.test" }),
  );
  for (const file of ["pyproject.toml", "uv.lock", "pnpm-lock.yaml"]) await writeFile(path.join(root, file), file);
  await writeFile(path.join(root, "packages", "apps", "terminal", "package.json"), '{"name":"@flinttrade/terminal"}');
}

async function crashLeaseOwner(input: {
  candidate: string;
  lock: string;
  promoteTo?: string;
  root: string;
}): Promise<void> {
  const bootstrapIo = path.resolve(import.meta.dirname, "bootstrap-io.ts");
  const output = await crashFixtureBundle("lease-crash", (outfile) => build({
    banner: {
      js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
    },
    bundle: true,
    format: "esm",
    outfile,
    platform: "node",
    stdin: {
      contents: `
        import { createNodeBootstrapDependencies } from ${JSON.stringify(bootstrapIo)};
        import { rename } from "node:fs/promises";
        const [lock, candidate, promoteTo] = process.argv.slice(2);
        const fileSystem = createNodeBootstrapDependencies(process.platform).fileSystem;
        const release = await fileSystem.acquireOperationLock({
          bootIdentity: "crash-fixture",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target: lock,
        });
        if (promoteTo) {
          await rename(candidate, promoteTo);
        }
        process.stdout.write("ready\\n");
        void release;
        setInterval(() => {}, 1_000);
      `,
      resolveDir: import.meta.dirname,
      sourcefile: "lease-crash-fixture.ts",
    },
    target: "node22",
  }));
  const child = spawn(
    process.execPath,
    [output, input.lock, input.candidate, ...(input.promoteTo ? [input.promoteTo] : [])],
    {
    stdio: ["ignore", "pipe", "inherit"],
    },
  );
  await Promise.race([
    once(child.stdout!, "data"),
    once(child, "close").then(([code]) => {
      throw new Error(`Lease crash fixture exited before READY with code ${String(code)}.`);
    }),
    once(child, "error").then(([error]) => {
      throw error;
    }),
    new Promise<never>((_resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Lease crash fixture did not reach READY.")), 3_000);
      timer.unref?.();
    }),
  ]);
  child.kill("SIGKILL");
  await once(child, "close");
}

async function crashDuringLeasePublication(input: {
  lock: string;
  root: string;
  stage: "after-write" | "before-open";
}): Promise<void> {
  const bootstrapIo = path.resolve(import.meta.dirname, "bootstrap-io.ts");
  const output = await crashFixtureBundle(`lease-publication-crash-${input.stage}`, (outfile) => build({
    banner: {
      js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
    },
    bundle: true,
    format: "esm",
    outfile,
    platform: "node",
    stdin: {
      contents: `
        import { createNodeBootstrapDependencies } from ${JSON.stringify(bootstrapIo)};
        const [lock] = process.argv.slice(2);
        const wanted = ${JSON.stringify(input.stage)};
        const fileSystem = createNodeBootstrapDependencies(process.platform, {
          testHooks: {
            leaseOwnerWriteChunkBytes: 1,
            async onLeaseOwnerPublication(stage, bytesWritten) {
              if (stage === wanted && (stage !== "after-write" || bytesWritten === 1)) {
                process.stdout.write("ready\\n");
                await new Promise(() => {});
              }
            },
          },
        }).fileSystem;
        await fileSystem.acquireOperationLock({
          bootIdentity: "publication-crash-fixture",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target: lock,
        });
      `,
      resolveDir: import.meta.dirname,
      sourcefile: "lease-publication-crash-fixture.ts",
    },
    target: "node22",
  }));
  const child = spawn(process.execPath, [output, input.lock], { stdio: ["ignore", "pipe", "inherit"] });
  await Promise.race([
    once(child.stdout!, "data"),
    once(child, "close").then(([code]) => {
      throw new Error(`Lease publication fixture exited before READY with code ${String(code)}.`);
    }),
    once(child, "error").then(([error]) => {
      throw error;
    }),
    new Promise<never>((_resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Lease publication fixture did not reach READY.")), 3_000);
      timer.unref?.();
    }),
  ]);
  child.kill("SIGKILL");
  await once(child, "close");
}

async function crashBootstrapCommandOwner(input: {
  lock: string;
  marker: string;
  root: string;
}): Promise<void> {
  const bootstrapIo = path.resolve(import.meta.dirname, "bootstrap-io.ts");
  const targetScript = [
    "const {spawn}=require('node:child_process');",
    "const escaped=spawn(process.execPath,['-e',\"process.on('SIGTERM',()=>{});process.stdout.write('ready\\\\n');setTimeout(()=>require('node:fs').writeFileSync(process.argv[1],'survived'),1500);setInterval(()=>{},1000)\",process.argv[1]],{detached:true,stdio:['ignore','pipe','ignore']});",
    "escaped.stdout.once('data',()=>process.stdout.write('target-ready\\n'));",
    "escaped.unref();",
    "setInterval(()=>{},1000);",
  ].join("");
  const output = await crashFixtureBundle("command-owner-crash", (outfile) => build({
    banner: {
      js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
    },
    bundle: true,
    format: "esm",
    outfile,
    platform: "node",
    stdin: {
      contents: `
        import { createNodeBootstrapDependencies } from ${JSON.stringify(bootstrapIo)};
        const [lock, marker] = process.argv.slice(2);
        const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget: lock });
        const release = await dependencies.fileSystem.acquireOperationLock({
          bootIdentity: "command-owner-crash",
          ownerPid: process.pid,
          singletonAuthorised: true,
          target: lock,
        });
        const target = ${JSON.stringify(targetScript)};
        const result = await dependencies.command.run({
          args: ["-e", target, marker],
          command: process.execPath,
          onOutput(line) {
            if (line === "target-ready") process.stdout.write("READY\\n");
          },
          timeoutMs: 30_000,
        });
        await release();
        process.exit(result.contained ? result.exitCode : 125);
      `,
      resolveDir: import.meta.dirname,
      sourcefile: "command-owner-crash-fixture.ts",
    },
    target: "node22",
  }));
  const child = spawn(process.execPath, [output, input.lock, input.marker], {
    stdio: ["ignore", "pipe", "inherit"],
  });
  await Promise.race([
    once(child.stdout!, "data"),
    once(child, "close").then(([code]) => {
      throw new Error(`Command-owner crash fixture exited before READY with code ${String(code)}.`);
    }),
    once(child, "error").then(([error]) => {
      throw error;
    }),
    new Promise<never>((_resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Command-owner crash fixture did not reach READY.")), 5_000);
      timer.unref?.();
    }),
  ]);
  child.kill("SIGKILL");
  await once(child, "close");
}

interface FixtureOptions {
  addedArchiveSource?: boolean;
  abortArchiveKind?: "tar.gz" | "zip";
  badArchiveShape?: boolean;
  badUvChecksum?: boolean;
  boundary?: BootstrapBoundary;
  commandRejection?: "git-probe";
  destinationAppearance?: "empty-directory" | "file" | "non-empty-directory" | "symlink";
  expectedRevision?: string;
  finalLogFailure?: "once" | "permanent";
  gitAvailable?: boolean;
  gitCloneFailure?: boolean;
  realGitInspection?: boolean;
  gitOrigin?: string;
  realGitSwapFilter?: boolean;
  holdPythonSync?: boolean;
  holdLockRelease?: boolean;
  logFailure?: "permanent" | "transient";
  metadataRevision?: string;
  nonIgnoredUntracked?: boolean;
  outputLogFailure?: boolean;
  outputSecrets?: boolean;
  platform?: "darwin" | "win32";
  realAppendParentSyncFailure?: boolean;
  realDurableDirectorySyncFailure?: boolean;
  releaseFailure?: "once" | "permanent";
  realReleaseFailureStage?: "directory-remove" | "directory-sync" | "owner-unlink" | "parent-sync";
  rootAliasAtBoundary?: boolean;
  spuriousAbortError?: boolean;
  sourceMutationAtBoundary?: "after-marker" | "before-rename";
  toolPromotionFailure?: "after";
  toolMarkerWriteFailure?: "once";
  toolReservedMarker?: "file";
  touchTrackedDuringBuild?: boolean;
  mutateTrackedDuringBuild?: boolean;
  uncontainedOnAbort?: boolean;
  onExtract?: BootstrapDependencies["extractArchive"];
  virtualEnvironment?: "missing" | "nonrelocatable" | "relocatable";
}

async function fixture(options: FixtureOptions = {}) {
  const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-test-"));
  scratchRoots.push(root);
  const sourceRoot = path.join(root, "source");
  const activeSource = path.join(sourceRoot, "FlintTrade");
  const calls: CommandInvocation[] = [];
  const downloads: string[] = [];
  const downloadDestinations: string[] = [];
  const builtCandidates: string[] = [];
  const extractionDestinations: string[] = [];
  let currentCandidate: string | undefined;
  let releasePythonSync: (() => void) | undefined;
  const pythonSyncHeld = new Promise<void>((resolve) => {
    releasePythonSync = resolve;
  });
  let releaseLockCleanup!: () => void;
  const lockCleanupHeld = new Promise<void>((resolve) => {
    releaseLockCleanup = resolve;
  });
  let appendFailures = 0;
  let outputLogFailed = false;
  let toolMarkerWriteFailures = 0;
  let toolPromotionFailures = 0;
  let buildMutated = false;
  const gitExploitFilter = path.join(root, "bootstrap-swap-filter.sh");
  const gitExploitCanary = `${gitExploitFilter}.called`;
  let finalLogFailures = 0;
  let releaseFailures = 0;
  let realReleaseFailures = 0;
  let realAppendParentSyncFailures = 0;
  let realDurableDirectorySyncFailures = 0;
  let markArchiveExtractionStarted!: () => void;
  const archiveExtractionStarted = new Promise<void>((resolve) => {
    markArchiveExtractionStarted = resolve;
  });
  const platform = options.platform ?? "darwin";
  const useRealGitInspection =
    options.realGitInspection === true ||
    options.realGitSwapFilter === true ||
    options.touchTrackedDuringBuild === true;
  const target = platform === "win32" ? "win32-x64" : "darwin-arm64";
  const nodeDependencies = createNodeBootstrapDependencies(platform, {
    operationLeaseTarget: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"),
    testHooks: {
      beforeAppendParentSync() {
        if (options.realAppendParentSyncFailure && realAppendParentSyncFailures++ === 0) {
          throw new Error("real durable-log parent sync failed");
        }
      },
      beforeDurableDirectorySync(_target, kind) {
        if (
          kind === "directory" &&
          options.realDurableDirectorySyncFailure &&
          realDurableDirectorySyncFailures++ === 0
        ) {
          throw new Error("real durable-log directory sync failed");
        }
      },
      beforeLeaseReleaseStage(stage) {
        if (stage === options.realReleaseFailureStage && realReleaseFailures++ === 0) {
          throw new Error(`real lease ${stage} failed`);
        }
      },
      async testAtomicPromote(source, destination) {
        try {
          await lstat(destination);
          const error = new Error("Promotion destination already exists; refusing to replace it.") as NodeJS.ErrnoException;
          error.code = "EEXIST";
          throw error;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
        await rename(source, destination);
      },
      async testNativeDirectoryIdentity() {
        return "0000000000000001:00000000000000000000000000000001";
      },
    },
  });

  const dependencies: BootstrapDependencies = {
    command: {
      operationLeaseTarget: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"),
      reconcileOperationContainment: nodeDependencies.command.reconcileOperationContainment,
      ...(platform === "win32"
        ? { windowsPowerShell: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" }
        : {}),
      async run(invocation) {
        const result = await (async () => {
        calls.push(invocation);
        if (invocation.command === "git" && invocation.args[0] === "--version") {
          if (options.commandRejection === "git-probe") {
            throw new Error("command runner rejected without a containment result");
          }
          return options.gitAvailable === false
            ? { contained: true, exitCode: 127, stderr: "git missing", stdout: "" }
            : { contained: true, exitCode: 0, stderr: "", stdout: "git version 2.50.1\n" };
        }
        if (invocation.command === "git" && invocation.args[0] === "clone") {
          const candidate = invocation.args.at(-1)!;
          if (options.gitCloneFailure) {
            await mkdir(candidate, { recursive: true });
            await writeFile(path.join(candidate, "foreign-sentinel"), "preserve");
            return { contained: true, exitCode: 1, stderr: "clone failed", stdout: "" };
          }
          if (useRealGitInspection) {
            await writeRepositoryShape(candidate, false, platform);
            await writeFile(
              path.join(candidate, ".gitignore"),
              ".venv/\nnode_modules/\npackages/apps/terminal/dist/\n",
            );
            if (options.realGitSwapFilter) {
              await writeFile(path.join(candidate, ".gitattributes"), "uv.lock filter=swapped\n");
            }
            const run = (args: string[]): void => {
              const result = spawnSync("git", args, {
                cwd: candidate,
                encoding: "utf8",
                env: { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" },
              });
              if (result.error) throw result.error;
              if (result.status !== 0) throw new Error(result.stderr);
            };
            run(["init", "--initial-branch=main"]);
            run(["add", "--", "."]);
            run(["-c", "user.name=FlintTrade Test", "-c", "user.email=flinttrade@example.invalid", "commit", "-m", "fixture"]);
            run(["remote", "add", "origin", options.gitOrigin ?? "https://github.com/navaneeshnagarajan/FlintTrade.git"]);
            run(["config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main"]);
            run(["config", "remote.origin.tagOpt", "--no-tags"]);
            run(["config", "branch.main.remote", "origin"]);
            run(["config", "branch.main.merge", "refs/heads/main"]);
            if (options.realGitSwapFilter) {
              await writeFile(gitExploitFilter, "#!/bin/sh\n: > \"$0.called\"\ncat\n");
              await chmod(gitExploitFilter, 0o755);
            }
          } else {
            await writeRepositoryShape(
              candidate,
              true,
              platform,
              options.gitOrigin ?? "https://github.com/navaneeshnagarajan/FlintTrade.git",
            );
          }
          return { contained: true, exitCode: 0, stderr: "", stdout: "" };
        }
        const gitOperationIndex = path.basename(invocation.command) === "git"
          ? invocation.args.findIndex((argument) =>
              ["config", "diff-index", "ls-files", "rev-parse", "status"].includes(argument),
            )
          : -1;
        const gitOperation = gitOperationIndex >= 0 ? invocation.args.slice(gitOperationIndex) : [];
        if (useRealGitInspection && gitOperationIndex >= 0) {
          const candidate = invocation.cwd;
          const cleanlinessCommand = options.realGitSwapFilter === true &&
            gitOperation[0] === "status";
          const configPath = candidate ? path.join(candidate, ".git", "config") : "";
          const attributesPath = candidate ? path.join(candidate, ".git", "info", "attributes") : "";
          const safeConfig = cleanlinessCommand ? await readFile(configPath, "utf8") : null;
          if (safeConfig !== null) {
            await writeFile(configPath, `${safeConfig}\n[filter "swapped"]\n\tclean = ${gitExploitFilter}\n`);
            await writeFile(attributesPath, "uv.lock filter=swapped\n");
          }
          try {
            const result = spawnSync(invocation.command, invocation.args, {
              ...(invocation.cwd ? { cwd: invocation.cwd } : {}),
              encoding: "utf8",
              env: { ...process.env, ...invocation.env },
            });
            if (result.error) throw result.error;
            return {
              contained: true,
              exitCode: result.status ?? 1,
              stderr: result.stderr,
              stdout: result.stdout,
            };
          } finally {
            if (safeConfig !== null) {
              await writeFile(configPath, safeConfig);
              await rm(attributesPath, { force: true });
            }
          }
        }
        if (gitOperation[0] === "config") {
          const entries = [
            ["core.repositoryformatversion", "0"],
            ["core.filemode", String(platform !== "win32")],
            ["core.bare", "false"],
            ["core.logallrefupdates", "true"],
            ["remote.origin.url", options.gitOrigin ?? "https://github.com/navaneeshnagarajan/FlintTrade.git"],
            ["remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main"],
            ["remote.origin.tagopt", "--no-tags"],
            ["branch.main.remote", "origin"],
            ["branch.main.merge", "refs/heads/main"],
          ];
          return {
            contained: true,
            exitCode: 0,
            stderr: "",
            stdout: entries.map(([key, value]) => `${key}\n${value}\0`).join(""),
          };
        }
        if (gitOperation[0] === "rev-parse") {
          return { contained: true, exitCode: 0, stderr: "", stdout: `${revision}\n` };
        }
        if (gitOperation[0] === "ls-files" && gitOperation.includes("-v")) {
          return { contained: true, exitCode: 0, stderr: "", stdout: "H package.json\0H uv.lock\0" };
        }
        if (gitOperation[0] === "ls-files" && gitOperation.includes("--others")) {
          return {
            contained: true,
            exitCode: 0,
            stderr: "",
            stdout: options.nonIgnoredUntracked ? "injected.py\0" : "",
          };
        }
        if (gitOperation[0] === "diff-index") {
          return {
            contained: true,
            exitCode: 0,
            stderr: "",
            stdout: "",
          };
        }
        if (gitOperation[0] === "status") {
          return {
            contained: true,
            exitCode: 0,
            stderr: "",
            stdout: buildMutated ? "1 .M N... 100644 100644 100644 fixture fixture uv.lock\0" : "",
          };
        }
        // Tool probes are matched on the executable's basename, never on a
        // substring of its absolute path. Every fixture root is an mkdtemp
        // directory, so a random six-character suffix containing "uv" used to
        // make an unanchored `command.includes("uv")` matcher claim the Node
        // probe and answer it with uv's version string. That is ~1 in 700
        // fixtures (measured over 20,000 mkdtemp samples), so roughly 1 in 10
        // full-suite runs went red on a different — and always innocent —
        // test, reported as "The verified Node executable reported an
        // unexpected version" on commits touching no desktop code at all.
        // Every matcher is evaluated rather than short-circuited so that a
        // future overlap fails loudly here instead of letting source order
        // silently decide which tool's version string a probe receives.
        const toolName = path.basename(invocation.command).replace(/\.exe$/i, "");
        const versionProbe = invocation.args.at(-1) === "--version";
        const toolProbes = [
          {
            name: "uv --version",
            matches: toolName === "uv" && versionProbe && invocation.args.length === 1,
            stdout: "uv 0.11.16 (135a36367 2026-05-21 aarch64-apple-darwin)\n",
          },
          {
            name: "node --version",
            matches: toolName === "node" && versionProbe && invocation.args.length === 1,
            stdout: "v22.23.1\n",
          },
          {
            name: "node <corepack.js> --version",
            matches: toolName === "node" && versionProbe && invocation.args.length > 1,
            stdout: "0.34.6\n",
          },
        ].filter((probe) => probe.matches);
        // The production code turns any rejected command into a generic
        // containment message, so the reason is echoed to the console too —
        // otherwise a stub defect reads as an unrelated bootstrap failure.
        const failStub = (message: string): never => {
          console.error(`bootstrap.test.ts fixture stub: ${message}`);
          throw new Error(message);
        };
        if (toolProbes.length > 1) {
          failStub(
            `Overlapping fixture stubs ${toolProbes.map((probe) => probe.name).join(" and ")} both claim ` +
              `${invocation.command} ${invocation.args.join(" ")}; make them mutually exclusive.`,
          );
        }
        if (toolProbes[0]) {
          if (toolProbes[0].name.includes("corepack") && !/(?:^|[\\/])corepack\.js$/.test(invocation.args[0] ?? "")) {
            failStub(
              `The Corepack probe stub was handed ${invocation.args[0]}, which is not the confined corepack.js path.`,
            );
          }
          return { contained: true, exitCode: 0, stderr: "", stdout: toolProbes[0].stdout };
        }
        if (/^pytest(?:\.exe)?$/.test(path.basename(invocation.command))) {
          const environmentRoot = path.dirname(path.dirname(invocation.command));
          const configuration = await readFile(path.join(environmentRoot, "pyvenv.cfg"), "utf8");
          return configuration.includes("relocatable = true")
            ? { contained: true, exitCode: 0, stderr: "", stdout: "pytest 8.3.5\n" }
            : { contained: true, exitCode: 1, stderr: "virtual environment is not relocatable", stdout: "" };
        }
        if (invocation.command === "/bin/sh" || invocation.args.includes("-File")) {
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-python\t48\tInstalling managed Python 3.12", "stdout");
          if (options.uncontainedOnAbort) {
            await new Promise<void>((resolve) => {
              if (invocation.signal?.aborted) resolve();
              else invocation.signal?.addEventListener("abort", () => resolve(), { once: true });
            });
            return { contained: false, exitCode: 130, stderr: "descendant containment was not proved", stdout: "" };
          }
          if (options.holdPythonSync) await pythonSyncHeld;
          if (options.mutateTrackedDuringBuild) {
            buildMutated = true;
            await writeFile(path.join(invocation.args[1]!, "uv.lock"), "mutated");
          }
          if (options.touchTrackedDuringBuild) {
            const candidateIndex = invocation.args.includes("-Candidate")
              ? invocation.args.indexOf("-Candidate") + 1
              : 1;
            const futureMtime = new Date(Date.now() + 60_000);
            await utimes(path.join(invocation.args[candidateIndex]!, "uv.lock"), futureMtime, futureMtime);
          }
          if (options.realGitSwapFilter) {
            const candidateIndex = invocation.args.includes("-Candidate") ? invocation.args.indexOf("-Candidate") + 1 : 1;
            const uvLock = path.join(invocation.args[candidateIndex]!, "uv.lock");
            await writeFile(uvLock, await readFile(uvLock, "utf8"));
          }
          if (options.addedArchiveSource) {
            const candidateIndex = invocation.args.includes("-Candidate") ? invocation.args.indexOf("-Candidate") + 1 : 1;
            await writeFile(path.join(invocation.args[candidateIndex]!, "injected.py"), "print('injected')\n");
          }
          if (options.outputSecrets) {
            invocation.onOutput?.(
              'GITHUB_TOKEN=github-canary OPENAI_API_KEY=openai-canary AWS_SECRET_ACCESS_KEY=aws-canary BROKER_ACCESS_TOKEN=broker-canary Authorization: Basic dXNlcjpwYXNz Authorization: Bearer bearer-canary {"GITHUB_TOKEN":"json-github-canary","OPENAI_API_KEY": "json-openai-canary","password":"json-password-canary"} ACCESS_TOKEN=compact-one-canary;CLIENT_SECRET=compact-two-canary',
              "stdout",
            );
          }
          const candidateIndex = invocation.args.includes("-Candidate") ? invocation.args.indexOf("-Candidate") + 1 : 1;
          const candidate = invocation.args[candidateIndex]!;
          currentCandidate = candidate;
          builtCandidates.push(candidate);
          const frontendDist = path.join(candidate, "packages", "apps", "terminal", "dist");
          await mkdir(frontendDist, { recursive: true });
          await writeFile(path.join(frontendDist, "index.html"), "<!doctype html><title>FlintTrade</title>\n");
          const virtualEnvironment = options.virtualEnvironment ?? "relocatable";
          if (virtualEnvironment !== "missing") {
            const scripts = path.join(candidate, ".venv", platform === "win32" ? "Scripts" : "bin");
            const pytest = path.join(scripts, platform === "win32" ? "pytest.exe" : "pytest");
            await mkdir(scripts, { recursive: true });
            await writeFile(
              path.join(candidate, ".venv", "pyvenv.cfg"),
              virtualEnvironment === "relocatable" ? "relocatable = true\n" : `home = ${candidate}/managed-python\n`,
            );
            await writeFile(pytest, platform === "win32" ? "pytest launcher" : "#!/bin/sh\nexit 0\n");
            if (platform !== "win32") await chmod(pytest, 0o755);
          }
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-javascript\t68\tInstalling pnpm 9.15.0 dependencies", "stdout");
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tbuilding-terminal\t84\tBuilding the terminal for production", "stdout");
          return { contained: true, exitCode: 0, stderr: "", stdout: "" };
        }
        if (options.holdPythonSync && invocation.args[0] === "sync") {
          await pythonSyncHeld;
          return { contained: true, exitCode: 0, stderr: "", stdout: "late worker output" };
        }
        return { contained: true, exitCode: 0, stderr: "", stdout: "" };
        })();
        return { ...result, stderrTruncated: false, stdoutTruncated: false };
      },
    },
    download: {
      async file(url, destination) {
        downloads.push(url);
        downloadDestinations.push(destination);
        const bytes = url.includes("uv-") ? (options.badUvChecksum ? Buffer.from("tampered") : uvBytes) : nodeBytes;
        await mkdir(path.dirname(destination), { recursive: true });
        await writeFile(destination, bytes);
        return {
          bytes: bytes.length,
          finalUrl: url,
          origin: new URL(url).origin,
          sha256: sha256(bytes),
        };
      },
      async text(url) {
        const content = JSON.stringify({ sha: options.metadataRevision ?? revision });
        return {
          bytes: Buffer.byteLength(content),
          content,
          finalUrl: url,
          origin: new URL(url).origin,
          sha256: sha256(Buffer.from(content)),
        };
      },
    },
    extractArchive:
      options.onExtract ??
      (async ({ archive, destination, kind, signal, stripExpectedRoot }) => {
        extractionDestinations.push(destination);
        if (options.spuriousAbortError) {
          const error = new Error("Dependency raised an unrelated AbortError");
          error.name = "AbortError";
          throw error;
        }
        if (kind === options.abortArchiveKind) {
          markArchiveExtractionStarted();
          await new Promise<never>((_resolve, reject) => {
            const onAbort = () => {
              const error = new Error("Archive extraction aborted");
              error.name = "AbortError";
              reject(error);
            };
            if (signal.aborted) onAbort();
            else signal.addEventListener("abort", onAbort, { once: true });
          });
        }
        const name = path.basename(archive);
        if (name.startsWith("uv-")) {
          const executable = path.join(destination, manifest.uv.assets[target]!.executable);
          await mkdir(path.dirname(executable), { recursive: true });
          await writeFile(executable, "uv");
          await chmod(executable, 0o755);
          if (options.toolReservedMarker === "file") {
            await writeFile(path.join(destination, ".flinttrade-tool-verified.json"), "archive-controlled");
          }
          return [manifest.uv.assets[target]!.executable];
        }
        if (name.startsWith("node-")) {
          const executable = path.join(destination, manifest.node.assets[target]!.executable);
          await mkdir(path.dirname(executable), { recursive: true });
          await writeFile(executable, "node");
          await chmod(executable, 0o755);
          const corepack =
            platform === "win32"
              ? path.join(destination, "node-v22.23.1-win-x64", "node_modules", "corepack", "dist", "corepack.js")
              : path.join(
                  destination,
                  "node-v22.23.1-darwin-arm64",
                  "lib",
                  "node_modules",
                  "corepack",
                  "dist",
                  "corepack.js",
                );
          await mkdir(path.dirname(corepack), { recursive: true });
          await writeFile(corepack, "corepack");
          return [manifest.node.assets[target]!.executable, path.relative(destination, corepack)];
        }
        const extracted = stripExpectedRoot ? destination : path.join(destination, `FlintTrade-${revision}`);
        await writeRepositoryShape(extracted, false);
        if (options.badArchiveShape) await rm(path.join(extracted, "uv.lock"));
        return [
          `FlintTrade-${revision}`,
          `FlintTrade-${revision}/package.json`,
          `FlintTrade-${revision}/pyproject.toml`,
          `FlintTrade-${revision}/uv.lock`,
          `FlintTrade-${revision}/pnpm-lock.yaml`,
        ];
      }),
    fileSystem: {
      ...nodeDependencies.fileSystem,
      acquireOperationLock: async (target) => {
        const release = await nodeDependencies.fileSystem.acquireOperationLock(target);
        return async () => {
          if (options.holdLockRelease) await lockCleanupHeld;
          await release();
          if (
            options.releaseFailure === "permanent" ||
            (options.releaseFailure === "once" && releaseFailures++ === 0)
          ) {
            throw new Error("operation lease release failed");
          }
        };
      },
      appendText: async (target, content) => {
        if (options.logFailure === "permanent" || (options.logFailure === "transient" && appendFailures++ === 0)) {
          throw new Error("transient log write failed");
        }
        if (options.outputLogFailure && !outputLogFailed && content.includes("stdout: FLINTTRADE_BOOTSTRAP_PHASE")) {
          outputLogFailed = true;
          throw new Error("output log write failed");
        }
        if (
          content.includes('"phase":"complete"') &&
          (options.finalLogFailure === "permanent" ||
            (options.finalLogFailure === "once" && finalLogFailures++ === 0))
        ) {
          throw new Error("final log write failed");
        }
        await nodeDependencies.fileSystem.appendText(target, content);
      },
      promoteAbsent: async (source, destination, identity) => {
        await nodeDependencies.fileSystem.promoteAbsent(source, destination, identity);
        if (
          options.toolPromotionFailure === "after" &&
          destination.includes(`${path.sep}tools${path.sep}uv${path.sep}`) &&
          toolPromotionFailures++ === 0
        ) {
          throw new Error("interrupted immediately after atomic tool promotion");
        }
      },
      writeTextAbsent: async (target, content) => {
        if (
          path.basename(target) === ".flinttrade-tool-verified.json" &&
          options.toolMarkerWriteFailure === "once" &&
          toolMarkerWriteFailures++ === 0
        ) {
          await nodeDependencies.fileSystem.writeTextAbsent(target, '{"schemaVersion":');
          throw new Error("interrupted tool verification marker write");
        }
        await nodeDependencies.fileSystem.writeTextAbsent(target, content);
      },
    },
  };
  const state = createBootstrapState();
  const controller = createFirstRunBootstrap({
    arch: platform === "win32" ? "x64" : "arm64",
    bootIdentity: "test-boot",
    bootstrapResources: path.resolve(import.meta.dirname, "..", "resources", "bootstrap"),
    dependencies,
    ...(options.expectedRevision ? { expectedRevision: options.expectedRevision } : {}),
    heartbeatIntervalMs: 5,
    manifest,
    ...(options.boundary ||
    options.destinationAppearance ||
    options.rootAliasAtBoundary ||
    options.sourceMutationAtBoundary
      ? {
          onPromotionBoundary: async (boundary: BootstrapBoundary) => {
            if (boundary === options.boundary) throw new Error(`interrupted at ${boundary}`);
            if (!currentCandidate) throw new Error("Promotion boundary ran without a current bootstrap candidate.");
            if (boundary === options.sourceMutationAtBoundary) {
              await writeFile(path.join(currentCandidate, "uv.lock"), `mutated at ${boundary}`);
              buildMutated = true;
            }
            if (boundary === "before-rename" && options.rootAliasAtBoundary) {
              await rename(currentCandidate, `${activeSource}.candidate-real`);
              await symlink(`${activeSource}.candidate-real`, currentCandidate);
            }
            if (boundary === "before-rename" && options.destinationAppearance) {
              if (options.destinationAppearance === "file") await writeFile(activeSource, "external");
              if (options.destinationAppearance === "symlink") await symlink(root, activeSource);
              if (options.destinationAppearance.includes("directory")) await mkdir(activeSource);
              if (options.destinationAppearance === "non-empty-directory") {
                await writeFile(path.join(activeSource, "external"), "external");
              }
            }
          },
        }
      : {}),
    paths: {
      activeSource,
      logs: path.join(root, "workspace", "logs"),
      sourceRoot,
      toolsRoot: path.join(root, "tools"),
      workspace: path.join(root, "workspace"),
    },
    platform,
    singletonAuthorised: true,
    state,
  });
  return {
    activeSource,
    archiveExtractionStarted,
    builtCandidates,
    calls,
    controller,
    dependencies,
    downloadDestinations,
    downloads,
    extractionDestinations,
    gitExploitCanary,
    releaseLockCleanup,
    releasePythonSync: releasePythonSync!,
    root,
    state,
  };
}

afterEach(async () => {
  await Promise.all(scratchRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("first-run source bootstrap", () => {
  it("builds a Git candidate with frozen locks and promotes only the commit-bound result", async () => {
    const test = await fixture();
    const result = await test.controller.start();

    expect(result).toMatchObject({ ok: true, provenance: "git", revision });
    expect(test.state.getSnapshot()).toMatchObject({ phase: "complete", progress: 100, status: "ready" });
    const marker = JSON.parse(await readFile(path.join(test.activeSource, ".git", BOOTSTRAP_MARKER), "utf8"));
    expect(marker).toMatchObject({
      frontendOutputEntryCount: 1,
      gitTree: revision,
      packageManager: manifest.pnpm.packageManager,
      provenance: "git",
      revision,
      schemaVersion: 3,
    });
    expect(marker.frontendOutputDigest).toMatch(/^[0-9a-f]{64}$/);
    expect(marker.frontendOutputIndexSha256).toMatch(/^[0-9a-f]{64}$/);
    const buildCall = test.calls.find((call) => call.command === "/bin/sh");
    expect(buildCall?.args[0]).toMatch(/resources\/bootstrap\/flinttrade-bootstrap\.sh$/);
    expect(buildCall?.args[1]).toMatch(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/);
    expect(buildCall?.args.at(-1)).toBe("9.15.0");
    expect(buildCall?.args.some((argument) => argument.endsWith("corepack.js"))).toBe(true);
    expect(test.calls.some((call) => call.command.endsWith("corepack.cmd"))).toBe(false);
    expect(test.calls.some((call) => /cargo/i.test([call.command, ...call.args].join(" ")))).toBe(false);
  });

  it.runIf(process.platform !== "win32")(
    "validates an attached symbolic HEAD through the isolated packaged Git common directory",
    async () => {
      const test = await fixture({ realGitInspection: true });

      await expect(test.controller.start()).resolves.toMatchObject({
        ok: true,
        provenance: "git",
        revision: expect.stringMatching(/^[0-9a-f]{40}$/),
      });
      const inspection = test.calls.find(
        (call) => call.args.includes("rev-parse") && call.args.includes("HEAD") && call.env?.GIT_COMMON_DIR,
      );
      expect(inspection?.env).toMatchObject({
        GIT_COMMON_DIR: path.resolve(import.meta.dirname, "..", "resources", "bootstrap", "git-common"),
        GIT_INDEX_FILE: expect.stringContaining(`${path.sep}.git${path.sep}index`),
        GIT_OBJECT_DIRECTORY: expect.stringContaining(`${path.sep}.git${path.sep}objects`),
      });
    },
  );

  it.runIf(process.platform !== "win32")(
    "does not execute config and info-attribute controls swapped into a bootstrap candidate",
    async () => {
      const test = await fixture({ realGitSwapFilter: true });

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/metadata|config|identity|changed/i),
        ok: false,
      });
      expect(await exists(test.gitExploitCanary)).toBe(false);
      expect(await exists(test.activeSource)).toBe(false);
    },
  );

  it("proves the relocatable virtual-environment entry point before and after promotion", async () => {
    const test = await fixture();

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });

    const probes = test.calls
      .filter((call) => /^pytest(?:\.exe)?$/.test(path.basename(call.command)))
      .map((call) => call.command);
    expect(probes).toEqual([
      path.join(test.builtCandidates[0]!, ".venv", "bin", "pytest"),
      path.join(test.activeSource, ".venv", "bin", "pytest"),
    ]);
  });

  it.each(["darwin", "win32"] as const)(
    "refuses to promote a non-relocatable %s virtual environment",
    async (platform) => {
      const test = await fixture({ platform, virtualEnvironment: "nonrelocatable" });

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/relocat|virtual environment/i),
        ok: false,
      });
      expect(await exists(test.activeSource)).toBe(false);
    },
  );

  it("falls back to a commit-pinned GitHub archive and validates its repository shape", async () => {
    const test = await fixture({ gitAvailable: false });
    const result = await test.controller.start();

    expect(result).toMatchObject({ ok: true, provenance: "github-archive", revision });
    expect(test.downloads).toContain(`https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip/${revision}`);
    expect(test.downloads.some((url) => url.endsWith("/main.zip"))).toBe(false);
    const marker = JSON.parse(await readFile(path.join(test.activeSource, BOOTSTRAP_MARKER), "utf8"));
    expect(marker).toMatchObject({ provenance: "github-archive", revision });
  });

  it("preserves a partial failed-clone directory and falls back through a fresh candidate", async () => {
    const test = await fixture({ gitCloneFailure: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: true,
      provenance: "github-archive",
      revision,
    });
    const clone = test.calls.find((call) => call.command === "git" && call.args[0] === "clone");
    const partialCandidate = clone?.args.at(-1);
    expect(partialCandidate).toMatch(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/);
    expect(test.builtCandidates[0]).toMatch(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/);
    expect(test.builtCandidates[0]).not.toBe(partialCandidate);
    expect(await readFile(path.join(partialCandidate!, "foreign-sentinel"), "utf8")).toBe("preserve");
  });

  it("checks out the exact requested revision before building an update candidate", async () => {
    const test = await fixture({ expectedRevision: revision });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, provenance: "git", revision });
    expect(test.calls).toContainEqual(
      expect.objectContaining({
        args: ["checkout", "--detach", revision],
        command: "git",
        cwd: expect.stringMatching(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/),
      }),
    );
  });

  it("uses an already resolved exact revision for archive update acquisition", async () => {
    const test = await fixture({
      expectedRevision: revision,
      gitAvailable: false,
      metadataRevision: "b".repeat(40),
    });

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: true,
      provenance: "github-archive",
      revision,
    });
    expect(test.downloads).toContain(`https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip/${revision}`);
  });

  it("falls back to archive acquisition on Windows when Git is unavailable", async () => {
    const test = await fixture({ gitAvailable: false, platform: "win32" });

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: true,
      provenance: "github-archive",
      revision,
    });
    expect(test.downloads).toContain(`https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip/${revision}`);
    expect(await exists(test.activeSource)).toBe(true);
  });

  it("rejects an archive whose extracted repository shape is incomplete", async () => {
    const test = await fixture({ badArchiveShape: true, gitAvailable: false });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: false, error: expect.stringContaining("uv.lock") });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it("rejects a Git checkout whose origin does not match the public repository", async () => {
    const test = await fixture({ gitOrigin: "https://example.test/not-flinttrade.git" });

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: false,
      error: "The Git checkout has an inexact remote.origin.url setting.",
    });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it("rejects a tool checksum mismatch before extraction or active-path mutation", async () => {
    const extract = vi.fn<BootstrapDependencies["extractArchive"]>();
    const test = await fixture({ badUvChecksum: true, onExtract: extract });
    const result = await test.controller.start();

    expect(result.ok).toBe(false);
    expect(result.error).toContain("checksum");
    expect(extract).not.toHaveBeenCalled();
    expect(await exists(test.activeSource)).toBe(false);
  });

  it("fails closed when the required archive extractor is unavailable", async () => {
    const test = await fixture({
      onExtract: async () => {
        throw new Error("tar capability probe failed");
      },
    });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: false, error: "tar capability probe failed" });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it.each<BootstrapBoundary>(["before-marker", "after-marker", "before-rename", "after-rename"])(
    "survives interruption at the %s promotion boundary",
    async (boundary) => {
      const test = await fixture({ boundary });
      const result = await test.controller.start();

      expect(result).toMatchObject({ ok: false, error: `interrupted at ${boundary}` });
      expect(await exists(test.activeSource)).toBe(boundary === "after-rename");
      if (boundary === "after-rename") {
        await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
        expect(
          test.calls.some(
            (call) => call.command === path.join(test.activeSource, ".venv", "bin", "pytest"),
          ),
        ).toBe(true);
      }
    },
  );

  it.each(["file", "symlink", "empty-directory", "non-empty-directory"] as const)(
    "fails closed when a destination %s appears at the exact promotion boundary",
    async (destinationAppearance) => {
      const test = await fixture({ destinationAppearance });

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/already exists|refusing to replace/i),
        ok: false,
      });
      expect(await exists(test.builtCandidates[0]!)).toBe(true);
    },
  );

  it("preserves unowned bootstrap lookalikes while a fresh unique attempt succeeds", async () => {
    const test = await fixture();
    const foreignLookalikes = [
      `${test.activeSource}.candidate-7`,
      `${test.activeSource}.candidate-8.unpack`,
      `${test.activeSource}.candidate-9-${randomUUID()}`,
      `${test.activeSource}.candidate-10-${randomUUID()}.unpack-${randomUUID()}`,
      path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64.extracting-9"),
      path.join(
        test.root,
        "tools",
        "uv",
        "0.11.16",
        `darwin-arm64.extracting-10-${randomUUID()}`,
      ),
      path.join(
        test.root,
        "tools",
        ".downloads",
        "uv-aarch64-apple-darwin.tar.gz.download-987-123e4567-e89b-42d3-a456-426614174000",
      ),
      path.join(
        test.root,
        "source",
        ".downloads",
        `FlintTrade-${revision}.zip.download-987-123e4567-e89b-42d3-a456-426614174000`,
      ),
      path.join(test.root, "tools", ".downloads", ".flinttrade-archive-snapshot-Ab12z9"),
      path.join(test.root, "source", ".downloads", ".flinttrade-archive-snapshot-Zz90aB"),
    ];
    for (const target of foreignLookalikes) {
      await mkdir(target, { recursive: true });
      await writeFile(path.join(target, "foreign-sentinel"), "preserve");
    }
    const foreign = `${test.activeSource}.candidate-alias`;
    await mkdir(foreign);
    const completedArchive = path.join(test.root, "source", ".downloads", `FlintTrade-${revision}.zip`);
    const foreignSnapshot = path.join(test.root, "source", ".downloads", ".flinttrade-archive-snapshot-too-long");
    const foreignSourceTemporary = path.join(
      test.root,
      "source",
      ".downloads",
      "foreign-not-an-asset.download-987-123e4567-e89b-42d3-a456-426614174000",
    );
    const foreignToolTemporary = path.join(
      test.root,
      "tools",
      ".downloads",
      "foreign-not-an-asset.download-987-123e4567-e89b-42d3-a456-426614174000",
    );
    await writeFile(completedArchive, "complete");
    await mkdir(foreignSnapshot);
    await mkdir(foreignSourceTemporary);
    await mkdir(foreignToolTemporary);

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    for (const target of foreignLookalikes) {
      expect(await readFile(path.join(target, "foreign-sentinel"), "utf8")).toBe("preserve");
    }
    expect(test.builtCandidates[0]).toMatch(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/);
    expect(foreignLookalikes).not.toContain(test.builtCandidates[0]);
    expect(
      test.extractionDestinations
        .filter((target) => target.includes(".extracting-"))
        .every((target) => /\.extracting-1-[0-9a-f-]{36}$/.test(target)),
    ).toBe(true);
    expect(await exists(foreign)).toBe(true);
    expect(await exists(completedArchive)).toBe(true);
    expect(await exists(foreignSnapshot)).toBe(true);
    expect(await exists(foreignSourceTemporary)).toBe(true);
    expect(await exists(foreignToolTemporary)).toBe(true);
  });

  it.each(["darwin", "win32"] as const)(
    "bounds retained first-run attempts on %s without deleting foreign lookalikes",
    async (platform) => {
      const test = await fixture({ platform, virtualEnvironment: "nonrelocatable" });
      const foreignId = "123e4567-e89b-42d3-a456-426614174000";
      const foreignCandidate = `${test.activeSource}.candidate-99-${foreignId}`;
      const foreignSnapshot = path.join(
        test.root,
        "source",
        ".downloads",
        ".flinttrade-archive-snapshot-Ab12z9",
      );
      await mkdir(foreignCandidate, { recursive: true });
      await mkdir(foreignSnapshot, { recursive: true });
      await writeFile(path.join(foreignCandidate, "foreign-sentinel"), "candidate-foreign");
      await writeFile(path.join(foreignSnapshot, "foreign-sentinel"), "snapshot-foreign");

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/relocat|virtual environment/i),
        ok: false,
      });
      await expect(test.controller.retry()).resolves.toMatchObject({
        error: expect.stringMatching(/relocat|virtual environment/i),
        ok: false,
      });
      await expect(test.controller.retry()).resolves.toMatchObject({
        error: expect.stringMatching(/relocat|virtual environment/i),
        ok: false,
      });
      const allocatedBeforeLimit = {
        builds: test.builtCandidates.length,
        downloads: test.downloadDestinations.length,
        extractions: test.extractionDestinations.length,
      };

      await expect(test.controller.retry()).resolves.toMatchObject({
        error: expect.stringMatching(/retained first-run attempt limit|explicit purge/i),
        ok: false,
      });
      expect({
        builds: test.builtCandidates.length,
        downloads: test.downloadDestinations.length,
        extractions: test.extractionDestinations.length,
      }).toEqual(allocatedBeforeLimit);
      expect(
        (await test.dependencies.fileSystem.listNames(
          path.join(test.root, "source", ".flinttrade-bootstrap-retained-attempts"),
        )).filter((name) => /^attempt-[1-3]\.json$/.test(name)),
      ).toHaveLength(3);
      expect(await readFile(path.join(foreignCandidate, "foreign-sentinel"), "utf8")).toBe(
        "candidate-foreign",
      );
      expect(await readFile(path.join(foreignSnapshot, "foreign-sentinel"), "utf8")).toBe(
        "snapshot-foreign",
      );
    },
  );

  it("fails closed on a foreign retained-attempt ledger alias without touching its target", async () => {
    const test = await fixture();
    const sourceRoot = path.join(test.root, "source");
    const foreignLedger = path.join(test.root, "foreign-retained-attempts");
    const ledger = path.join(sourceRoot, ".flinttrade-bootstrap-retained-attempts");
    await mkdir(sourceRoot, { recursive: true });
    await mkdir(foreignLedger);
    await writeFile(path.join(foreignLedger, "sentinel"), "foreign-retention-evidence\n");
    await symlink(foreignLedger, ledger, "dir");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/no-follow directory|private root|retained first-run attempt/i),
      ok: false,
    });
    expect(test.builtCandidates).toHaveLength(0);
    expect(test.downloadDestinations).toHaveLength(0);
    expect(test.extractionDestinations).toHaveLength(0);
    expect(await readFile(path.join(foreignLedger, "sentinel"), "utf8")).toBe("foreign-retention-evidence\n");
    expect((await lstat(ledger)).isSymbolicLink()).toBe(true);
  });

  it("honours retained attempts from a prior process before allocating new bootstrap paths", async () => {
    const test = await fixture();
    const ledger = path.join(test.root, "source", ".flinttrade-bootstrap-retained-attempts");
    await mkdir(ledger, { recursive: true });
    for (let index = 1; index <= 3; index += 1) {
      const operationId = `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
      await writeFile(
        path.join(ledger, `attempt-${index}.json`),
        `${JSON.stringify({ operationId, schemaVersion: 1, slot: index })}\n`,
        { mode: 0o600 },
      );
    }

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/retained first-run attempt limit|explicit purge/i),
      ok: false,
    });
    expect(test.builtCandidates).toHaveLength(0);
    expect(test.downloadDestinations).toHaveLength(0);
    expect(test.extractionDestinations).toHaveLength(0);
  });

  it("does not apply the first-run retention budget to an exact-revision update candidate build", async () => {
    const test = await fixture({ expectedRevision: revision });
    const sourceRoot = path.join(test.root, "source");
    const ledger = path.join(sourceRoot, ".flinttrade-bootstrap-retained-attempts");
    const operationIds = Array.from(
      { length: 3 },
      (_value, index) => `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    );
    await mkdir(ledger, { recursive: true });
    for (const [index, operationId] of operationIds.entries()) {
      const slot = index + 1;
      await writeFile(
        path.join(ledger, `attempt-${slot}.json`),
        `${JSON.stringify({ operationId, schemaVersion: 1, slot })}\n`,
        { mode: 0o600 },
      );
    }

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    expect((await test.dependencies.fileSystem.listNames(ledger)).sort()).toEqual(
      operationIds.map((_operationId, index) => `attempt-${index + 1}.json`),
    );
  });

  it("leaves canonical foreign archive files byte-for-byte unchanged while downloading unique assets", async () => {
    const test = await fixture({ gitAvailable: false });
    const sourceDownloads = path.join(test.root, "source", ".downloads");
    const toolDownloads = path.join(test.root, "tools", ".downloads");
    const sourceArchive = path.join(sourceDownloads, `FlintTrade-${revision}.zip`);
    const uvArchive = path.join(toolDownloads, path.basename(new URL(manifest.uv.assets["darwin-arm64"]!.url).pathname));
    const nodeArchive = path.join(
      toolDownloads,
      path.basename(new URL(manifest.node.assets["darwin-arm64"]!.url).pathname),
    );
    await mkdir(sourceDownloads, { recursive: true });
    await mkdir(toolDownloads, { recursive: true });
    await writeFile(sourceArchive, "foreign-source");
    await writeFile(uvArchive, "foreign-uv");
    await writeFile(nodeArchive, "foreign-node");

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, provenance: "github-archive" });

    expect(await readFile(sourceArchive, "utf8")).toBe("foreign-source");
    expect(await readFile(uvArchive, "utf8")).toBe("foreign-uv");
    expect(await readFile(nodeArchive, "utf8")).toBe("foreign-node");
    expect(test.downloadDestinations).toHaveLength(3);
    expect(test.downloadDestinations).not.toContain(sourceArchive);
    expect(test.downloadDestinations).not.toContain(uvArchive);
    expect(test.downloadDestinations).not.toContain(nodeArchive);
    expect(test.downloadDestinations.every((target) => /\.bootstrap-1-[0-9a-f-]{36}$/.test(target))).toBe(true);
  });

  it("restarts after a killed lease owner dies before promotion", async () => {
    const test = await fixture();
    const lock = path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock");
    const staleCandidate = `${test.activeSource}.candidate-41`;
    await mkdir(path.dirname(lock), { recursive: true });
    await mkdir(staleCandidate);
    await crashLeaseOwner({ candidate: staleCandidate, lock, root: test.root });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    expect(await exists(staleCandidate)).toBe(true);
    expect(await exists(test.activeSource)).toBe(true);
  }, 15_000);

  it.runIf(process.platform !== "win32")(
    "drains an old command tree including an escaped session before immediate stale-lease restart",
    async () => {
      const test = await fixture();
      const lock = path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock");
      const marker = path.join(test.root, "old-command-survived");
      await mkdir(path.dirname(lock), { recursive: true });
      await crashBootstrapCommandOwner({ lock, marker, root: test.root });

      const release = await test.dependencies.fileSystem.acquireOperationLock({
        bootIdentity: "restart-after-command-owner-crash",
        ownerPid: process.pid,
        singletonAuthorised: true,
        target: lock,
      });
      await release();
      await new Promise((resolve) => setTimeout(resolve, 1_650));
      await expect(access(marker)).rejects.toThrow();
    },
    15_000,
  );

  it("restarts after a killed lease owner dies after promotion but before release", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    const lock = path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock");
    const candidate = `${test.activeSource}.candidate-99`;
    await rename(test.activeSource, candidate);
    await crashLeaseOwner({ candidate, lock, promoteTo: test.activeSource, root: test.root });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);
    expect(await exists(test.activeSource)).toBe(true);
  }, 15_000);

  it.each(["before-open", "after-write"] as const)(
    "recovers after a killed lease owner dies %s during owner publication",
    async (stage) => {
      const test = await fixture();
      const lock = path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock");
      await mkdir(path.dirname(lock), { recursive: true });
      await crashDuringLeasePublication({ lock, root: test.root, stage });

      await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
      expect(await exists(test.activeSource)).toBe(true);
    },
    15_000,
  );

  it("cancels a running attempt and prevents its stale worker from promoting", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.some((call) => call.command === "/bin/sh")).toBe(true),
      { timeout: 15_000 },
    );
    const cancellation = test.controller.cancel();
    expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });
    test.releasePythonSync();
    await expect(cancellation).resolves.toBe(true);
    await first;
    const retry = test.controller.retry();
    await retry;

    expect(test.state.getSnapshot().attempt).toBe(2);
    expect(test.state.getSnapshot().status).toBe("ready");
    expect(await exists(test.activeSource)).toBe(true);
    expect(test.builtCandidates).toHaveLength(2);
    expect(new Set(test.builtCandidates).size).toBe(2);
    expect(test.builtCandidates[0]).toMatch(/FlintTrade\.candidate-1-[0-9a-f-]{36}$/);
    expect(test.builtCandidates[1]).toMatch(/FlintTrade\.candidate-2-[0-9a-f-]{36}$/);
    expect(await exists(test.builtCandidates[0]!)).toBe(true);
  });

  it("serialises an immediate retry behind cancelled-attempt process and lock settlement", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1),
      { timeout: 15_000 },
    );

    const cancellation = test.controller.cancel();
    const retry = test.controller.retry();
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);

    test.releasePythonSync();
    await expect(cancellation).resolves.toBe(true);
    await first;
    await expect(retry).resolves.toMatchObject({ ok: true });
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(2);
  });

  it("writes redacted durable failure logs", async () => {
    const test = await fixture({
      onExtract: async () => {
        throw new Error(
          "download failed at https://user:secret@example.test/tool?token=private api_key=canary Bearer bearer-canary",
        );
      },
    });
    await test.controller.start();
    const logs = await readFile(path.join(test.root, "workspace", "logs", "desktop-bootstrap.jsonl"), "utf8");

    expect(logs).toContain("<redacted-url>");
    expect(logs).not.toContain("secret");
    expect(logs).not.toContain("private");
    expect(logs).not.toContain("canary");
  });

  it("redacts source, workspace, candidate, tool and extended Windows path spellings from durable logs", async () => {
    const test = await fixture({ platform: "win32" });
    const sourceRoot = path.join(test.root, "source");
    const workspace = path.join(test.root, "workspace");
    const toolsRoot = path.join(test.root, "tools");
    const candidate = `${test.activeSource}.candidate-private`;
    test.dependencies.extractArchive = async () => {
      const upperWorkspace = workspace.toUpperCase();
      throw new Error(
        `private paths ${sourceRoot} ${workspace} ${candidate} ${toolsRoot} \\\\?\\${upperWorkspace}`,
      );
    };

    await expect(test.controller.start()).resolves.toMatchObject({ ok: false });
    const logs = await readFile(path.join(workspace, "logs", "desktop-bootstrap.jsonl"), "utf8");

    for (const privatePath of [sourceRoot, workspace, candidate, toolsRoot]) {
      expect(logs.toLowerCase()).not.toContain(privatePath.toLowerCase());
    }
    expect(logs).toContain("<source-root>");
    expect(logs).toContain("<workspace>");
    expect(logs).toContain("<tools-root>");
  });

  it("rejects an existing checkout whose HEAD no longer matches its completion marker", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.revision = "b".repeat(40);
    await writeFile(markerPath, JSON.stringify(marker));

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: false,
      error: "The Git HEAD does not match the explicit expected revision.",
    });
  });

  it("rejects a symlinked Git completion marker even when its JSON is otherwise valid", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const externalMarker = path.join(test.root, "external-completion-marker.json");
    await writeFile(externalMarker, await readFile(markerPath));
    await rm(markerPath);
    await symlink(externalMarker, markerPath);

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/no-follow regular file/i),
      ok: false,
    });
    expect(await readFile(externalMarker, "utf8")).toContain('"schemaVersion":3');
  });

  it("boots an existing checkout built with an older valid pinned toolchain", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.node = "22.22.0";
    marker.pnpm = "9.14.4";
    marker.uv = "0.10.0";
    marker.packageManager = "pnpm@9.14.4+sha512.legacy";
    await writeFile(markerPath, JSON.stringify(marker));
    const packagePath = path.join(test.activeSource, "package.json");
    const packageMetadata = JSON.parse(await readFile(packagePath, "utf8"));
    packageMetadata.packageManager = marker.packageManager;
    await writeFile(packagePath, JSON.stringify(packageMetadata));

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
  });

  it("boots a valid legacy marker so the source updater can rebuild it", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    for (const field of [
      "frontendOutputDigest",
      "frontendOutputEntryCount",
      "frontendOutputIndexSha256",
      "packageManager",
    ]) delete marker[field];
    marker.schemaVersion = 2;
    await writeFile(markerPath, JSON.stringify(marker));

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
  });

  it.each(["missing", "mutated"] as const)("rejects %s bound terminal output on an existing install", async (mode) => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const index = path.join(test.activeSource, "packages", "apps", "terminal", "dist", "index.html");
    if (mode === "missing") await rm(index);
    else await writeFile(index, "<!doctype html><title>Mutated</title>\n");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/terminal|output|index|marker/i),
      ok: false,
    });
  });

  it("rejects a completion marker with an invalid recorded tool version", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.pnpm = "not-a-version";
    await writeFile(markerPath, JSON.stringify(marker));

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/valid pinned tool version/i),
      ok: false,
    });
  });

  it("rejects an aliased existing active checkout outside the managed source root", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const outside = path.join(test.root, "outside-active-source");
    await rename(test.activeSource, outside);
    await symlink(outside, test.activeSource);

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/alias|no-follow|managed source|symbolic/i),
      ok: false,
    });
  });

  it("invokes Corepack JavaScript from the exact verified target layout", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const corepackArgument = test.calls
      .find((call) => call.command === "/bin/sh")
      ?.args.find((argument) => argument.endsWith("corepack.js"));

    expect(corepackArgument).toBe(
      path.join(
        test.root,
        "tools",
        "node",
        "22.23.1",
        "darwin-arm64",
        "node-v22.23.1-darwin-arm64",
        "lib",
        "node_modules",
        "corepack",
        "dist",
        "corepack.js",
      ),
    );
  });

  it("fails closed without deleting a pre-existing unverified tool root", async () => {
    const test = await fixture();
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const sentinel = path.join(installRoot, "foreign-sentinel");
    await mkdir(installRoot, { recursive: true });
    await writeFile(sentinel, "foreign");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/existing uv tool state.*preserved/i),
      ok: false,
    });
    expect(await readFile(sentinel, "utf8")).toBe("foreign");
    expect(await exists(path.join(installRoot, ".flinttrade-tool-verified.json"))).toBe(false);
  });

  it("fails closed and preserves a tool whose installed tree and marker were modified together", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const executable = path.join(installRoot, manifest.uv.assets["darwin-arm64"]!.executable);
    const markerPath = path.join(installRoot, ".flinttrade-tool-verified.json");
    await writeFile(executable, "tampered");
    await chmod(executable, 0o755);
    const forgedTree = await test.dependencies.fileSystem.snapshotSourceTree(installRoot);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.treeDigest = forgedTree.digest;
    marker.executableSha256 = forgedTree.entries.find((entry) => entry.path.endsWith("/uv"))?.sha256;
    const forgedMarker = JSON.stringify(marker);
    await writeFile(markerPath, forgedMarker);
    await rm(test.activeSource, { recursive: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/existing uv tool state.*preserved/i),
      ok: false,
    });

    expect(await readFile(executable, "utf8")).toBe("tampered");
    expect(await readFile(markerPath, "utf8")).toBe(forgedMarker);
  });

  it("fails closed and preserves a tool whose verification marker is a symlink", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const markerPath = path.join(installRoot, ".flinttrade-tool-verified.json");
    const externalMarker = path.join(test.root, "external-tool-marker.json");
    await writeFile(externalMarker, await readFile(markerPath));
    await rm(markerPath);
    await symlink(externalMarker, markerPath);
    await rm(test.activeSource, { recursive: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/existing uv tool state.*preserved/i),
      ok: false,
    });

    expect((await lstat(markerPath)).isSymbolicLink()).toBe(true);
    expect(await readFile(externalMarker, "utf8")).toContain('"schemaVersion":2');
  });

  it("keeps a partial marker write inside an unpromoted candidate and succeeds on retry", async () => {
    const test = await fixture({ toolMarkerWriteFailure: "once" });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const markerPath = path.join(installRoot, ".flinttrade-tool-verified.json");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/interrupted tool verification marker write/i),
      ok: false,
    });
    expect(await exists(installRoot)).toBe(false);
    expect(await exists(markerPath)).toBe(false);

    await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
    expect(JSON.parse(await readFile(markerPath, "utf8"))).toMatchObject({
      archiveSha256: manifest.uv.assets["darwin-arm64"]!.sha256,
      schemaVersion: 2,
      version: manifest.uv.version,
    });
  });

  it("rejects an archive that claims FlintTrade's reserved internal tool marker", async () => {
    const test = await fixture({ toolReservedMarker: "file" });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/reserved verification marker/i),
      ok: false,
    });
    expect(await exists(installRoot)).toBe(false);
  });

  it("retries cleanly when the marker-bearing tool root was promoted before interruption", async () => {
    const test = await fixture({ toolPromotionFailure: "after" });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const markerPath = path.join(installRoot, ".flinttrade-tool-verified.json");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/interrupted immediately after atomic tool promotion/i),
      ok: false,
    });
    expect(await exists(installRoot)).toBe(true);
    expect(JSON.parse(await readFile(markerPath, "utf8"))).toMatchObject({
      schemaVersion: 2,
      version: manifest.uv.version,
    });

    await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
  });

  it("accepts the exact legacy sibling marker used by pre-release tool installs", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const internalMarker = path.join(installRoot, ".flinttrade-tool-verified.json");
    const legacyMarker = `${installRoot}.flinttrade-tool-verified.json`;
    await rename(internalMarker, legacyMarker);
    await rm(test.activeSource, { recursive: true });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    expect(JSON.parse(await readFile(legacyMarker, "utf8"))).toMatchObject({
      schemaVersion: 2,
      version: manifest.uv.version,
    });
  });

  it("fails closed and preserves an altered tool root whose verification marker is missing", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const executable = path.join(installRoot, manifest.uv.assets["darwin-arm64"]!.executable);
    const markerPath = path.join(installRoot, ".flinttrade-tool-verified.json");
    const originalExecutable = await readFile(executable);
    await rm(markerPath);
    await writeFile(executable, "altered");
    await chmod(executable, 0o755);
    await rm(test.activeSource, { recursive: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/existing uv tool state.*preserved/i),
      ok: false,
    });
    expect(await readFile(executable)).not.toEqual(originalExecutable);
    expect(await readFile(executable, "utf8")).toBe("altered");
    expect(await exists(markerPath)).toBe(false);
  });

  it("fails a Git build hook which mutates a tracked source input", async () => {
    const test = await fixture({ mutateTrackedDuringBuild: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "The Git checkout has tracked worktree changes.",
      ok: false,
    });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it.runIf(process.platform !== "win32")(
    "accepts a Git build hook which changes only a tracked source input mtime",
    async () => {
      const test = await fixture({ touchTrackedDuringBuild: true });

      await expect(test.controller.start()).resolves.toMatchObject({
        ok: true,
        provenance: "git",
        revision: expect.stringMatching(/^[0-9a-f]{40}$/),
      });
      expect(await exists(test.activeSource)).toBe(true);
    },
  );

  it.each(["tar.gz", "zip"] as const)(
    "classifies a mid-%s archive AbortError as cancellation",
    async (abortArchiveKind) => {
      const test = await fixture({ abortArchiveKind, gitAvailable: abortArchiveKind === "zip" ? false : true });
      const running = test.controller.start();
      await test.archiveExtractionStarted;
      const cancellation = test.controller.cancel();

      await expect(running).resolves.toMatchObject({ cancelled: true, ok: false });
      await expect(cancellation).resolves.toBe(true);
      expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });
      const logs = await readFile(path.join(test.root, "workspace", "logs", "desktop-bootstrap.jsonl"), "utf8");
      expect(logs).toContain('"phase":"cancelled"');
    },
  );

  it("treats an unrelated dependency AbortError as a retryable failure", async () => {
    const test = await fixture({ spuriousAbortError: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      cancelled: false,
      error: "Dependency raised an unrelated AbortError",
      ok: false,
    });
    expect(test.state.getSnapshot()).toMatchObject({
      failure: "Dependency raised an unrelated AbortError",
      phase: "failed",
      status: "failed",
    });
    const logs = await readFile(path.join(test.root, "workspace", "logs", "desktop-bootstrap.jsonl"), "utf8");
    expect(logs).toContain('"phase":"failed"');
  });

  it("rejects a non-ignored untracked Git input while permitting ignored generated output", async () => {
    const test = await fixture({ nonIgnoredUntracked: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/untracked|clean|changes/i),
      ok: false,
    });
    const untrackedCall = test.calls.find(
      (call) => path.basename(call.command) === "git" && call.args.includes("--others"),
    );
    expect(untrackedCall?.args).toContain("--exclude-standard");
    expect(untrackedCall?.args).not.toContain("--untracked-files=no");
    expect(await exists(test.activeSource)).toBe(false);
  });

  it("fails an archive build hook which mutates an original source input", async () => {
    const test = await fixture({ gitAvailable: false, mutateTrackedDuringBuild: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "An archive source input changed during the build.",
      ok: false,
    });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it("rejects a source file added to an archive candidate during the build", async () => {
    const test = await fixture({ addedArchiveSource: true, gitAvailable: false });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/added|source input|changed/i),
      ok: false,
    });
    expect(await exists(test.activeSource)).toBe(false);
  });

  it.each(["after-marker", "before-rename"] as const)(
    "revalidates source content after the %s asynchronous boundary",
    async (sourceMutationAtBoundary) => {
      const test = await fixture({ sourceMutationAtBoundary });

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/changed|binding|clean|tracked|untracked/i),
        ok: false,
      });
      expect(await exists(test.activeSource)).toBe(false);
      expect(await readFile(path.join(test.builtCandidates[0]!, "uv.lock"), "utf8")).toContain("mutated at");
    },
  );

  it("rejects a no-follow candidate root alias at the final promotion boundary", async () => {
    const test = await fixture({ rootAliasAtBoundary: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/alias|symbolic|candidate|directory/i),
      ok: false,
    });
    expect(await exists(test.activeSource)).toBe(false);
    expect(await exists(`${test.activeSource}.candidate-real`)).toBe(true);
  });

  it("binds archive, source-input and frontend output identities into marker v3", async () => {
    const test = await fixture({ gitAvailable: false });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const marker = JSON.parse(await readFile(path.join(test.activeSource, BOOTSTRAP_MARKER), "utf8"));
    const sourceInputs = JSON.parse(await readFile(path.join(test.activeSource, SOURCE_INPUTS_RECORD), "utf8"));

    expect(marker).toMatchObject({
      archiveFinalOrigin: "https://codeload.github.com",
      archiveSha256: sha256(nodeBytes),
      provenance: "github-archive",
      frontendOutputEntryCount: 1,
      packageManager: manifest.pnpm.packageManager,
      schemaVersion: 3,
      sourceInputDigest: sourceInputs.digest,
    });
    expect(marker.frontendOutputDigest).toMatch(/^[0-9a-f]{64}$/);
    expect(marker.frontendOutputIndexSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(marker.sourceInputRecordSha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it("revalidates original archive source inputs on an existing install", async () => {
    const test = await fixture({ gitAvailable: false });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    await writeFile(path.join(test.activeSource, "uv.lock"), "mutated after install");

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "Archive-backed source inputs changed after bootstrap.",
      ok: false,
    });
  });

  it("rejects an archive marker whose claimed final origin is not the configured archive origin", async () => {
    const test = await fixture({ gitAvailable: false });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.archiveFinalOrigin = "https://example.test";
    await writeFile(markerPath, JSON.stringify(marker));

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/final origin/i),
      ok: false,
    });
  });

  it("returns a stable failed result for a permanent durable-log failure", async () => {
    const test = await fixture({ logFailure: "permanent" });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "Durable bootstrap log failed: transient log write failed",
      ok: false,
    });
    expect(test.state.getSnapshot().status).toBe("failed");
  });

  it("recovers logging and succeeds when retry follows one transient append failure", async () => {
    const test = await fixture({ logFailure: "transient" });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: false });

    await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
    expect(test.state.getSnapshot().status).toBe("ready");
  });

  it("supervises an output-time log failure without an unhandled rejection", async () => {
    const test = await fixture({ outputLogFailure: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "Durable bootstrap log failed: output log write failed",
      ok: false,
    });
  });

  it("uses a managed private home/config plane for every tool and build command", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const managedRoot = path.join(test.root, "tools", "bootstrap-user");

    expect(test.calls.length).toBeGreaterThan(0);
    for (const call of test.calls) {
      const hardenedGitInspection =
        path.basename(call.command) === "git" && call.args.includes("--no-replace-objects");
      expect(call.env).toMatchObject({
        GIT_CONFIG_GLOBAL: hardenedGitInspection ? "/dev/null" : path.join(managedRoot, "gitconfig"),
        HOME: path.join(managedRoot, "home"),
        NPM_CONFIG_USERCONFIG: path.join(managedRoot, "npmrc"),
        USERPROFILE: path.join(managedRoot, "home"),
        UV_CONFIG_FILE: path.join(managedRoot, "uv.toml"),
        XDG_CONFIG_HOME: path.join(managedRoot, "xdg-config"),
      });
    }
  });

  it.each(["root", "config"] as const)("rejects a managed bootstrap-user %s symlink", async (kind) => {
    const test = await fixture();
    const tools = path.join(test.root, "tools");
    const managed = path.join(tools, "bootstrap-user");
    await mkdir(tools, { recursive: true });
    if (kind === "root") {
      await symlink(test.root, managed);
    } else {
      await mkdir(managed);
      const outside = path.join(test.root, "outside-config");
      await writeFile(outside, "canary");
      await symlink(outside, path.join(managed, "gitconfig"));
    }

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/bootstrap-user|no-follow|symbolic/i),
      ok: false,
    });
    expect(test.calls).toHaveLength(0);
  });

  it.each(["source", "tools"] as const)("rejects an aliased %s download root without deleting outside data", async (kind) => {
    const test = await fixture();
    const parent = kind === "source" ? path.join(test.root, "source") : path.join(test.root, "tools");
    const outside = path.join(test.root, `outside-${kind}-downloads`);
    const sentinel = path.join(outside, "asset.download-987-123e4567-e89b-42d3-a456-426614174000");
    await mkdir(parent, { recursive: true });
    await mkdir(outside);
    await writeFile(sentinel, "outside");
    await symlink(outside, path.join(parent, ".downloads"));

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringMatching(/no-follow|bootstrap-user|directory/i),
      ok: false,
    });
    expect(await readFile(sentinel, "utf8")).toBe("outside");
  });

  it.each(["corepack", "python", "uv-cache"] as const)(
    "rejects an aliased shared tool root %s without touching outside data",
    async (toolRoot) => {
      const test = await fixture();
      const tools = path.join(test.root, "tools");
      const outside = path.join(test.root, `outside-${toolRoot}`);
      const sentinel = path.join(outside, "sentinel");
      await mkdir(tools, { recursive: true });
      await mkdir(outside);
      await writeFile(sentinel, "outside");
      await symlink(outside, path.join(tools, toolRoot));

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/no-follow|bootstrap-user|directory/i),
        ok: false,
      });
      expect(await readFile(sentinel, "utf8")).toBe("outside");
    },
  );

  it("redacts prefixed secret names and complete Basic/Bearer credentials in actual durable output", async () => {
    const test = await fixture({ outputSecrets: true });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const logs = await readFile(path.join(test.root, "workspace", "logs", "desktop-bootstrap.jsonl"), "utf8");

    for (const canary of [
      "github-canary",
      "openai-canary",
      "aws-canary",
      "broker-canary",
      "dXNlcjpwYXNz",
      "bearer-canary",
      "json-github-canary",
      "json-openai-canary",
      "json-password-canary",
      "compact-one-canary",
      "compact-two-canary",
    ]) {
      expect(logs).not.toContain(canary);
    }
    expect(logs).toContain("<redacted>");
  });

  it("uses the trusted absolute Windows PowerShell launcher even with an empty or canary PATH", async () => {
    const test = await fixture({ platform: "win32" });
    const result = await test.controller.start();
    expect(result.error).toBeUndefined();
    expect(result).toMatchObject({ ok: true });
    const buildCall = test.calls.find((call) => call.args.includes("-File"));

    expect(buildCall?.command).toBe("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe");
    expect(buildCall?.command).not.toContain("canary");
    expect(path.win32.isAbsolute(buildCall?.command ?? "")).toBe(true);
    expect(
      test.calls.some(
        (call) => call.command === path.join(test.activeSource, ".venv", "Scripts", "pytest.exe"),
      ),
    ).toBe(true);
  });

  it.each([
    ["final durable append", { finalLogFailure: "once" as const }, "final log write failed"],
    ["operation lease release", { releaseFailure: "once" as const }, "operation lease release failed"],
  ])("publishes readiness only after %s succeeds and retry validates the promoted source", async (_label, options, error) => {
    const test = await fixture(options);
    const first = await test.controller.start();

    expect(first).toMatchObject({ error: expect.stringContaining(error), ok: false });
    expect(test.state.getSnapshot()).toMatchObject({ status: "failed" });
    expect(await exists(test.activeSource)).toBe(true);
    await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
    expect(test.state.getSnapshot()).toMatchObject({ phase: "complete", status: "ready" });
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);
  });

  it.each(["owner-unlink", "directory-sync", "directory-remove", "parent-sync"] as const)(
    "resumes the exact operation-lease release closure after a %s failure",
    async (stage) => {
      const test = await fixture({ realReleaseFailureStage: stage });

      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringContaining(`real lease ${stage} failed`),
        ok: false,
      });
      expect(test.state.getSnapshot()).toMatchObject({ status: "failed" });
      expect(await exists(test.activeSource)).toBe(true);

      await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
      expect(test.state.getSnapshot()).toMatchObject({ phase: "complete", status: "ready" });
      expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);
    },
  );

  it("keeps a throwing readiness subscriber outside the bootstrap result path", async () => {
    const test = await fixture();
    test.state.subscribe((snapshot) => {
      if (snapshot.status === "ready") throw new Error("renderer broadcast failed");
    });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true, revision });
    expect(test.state.getSnapshot()).toMatchObject({ phase: "complete", status: "ready" });
  });

  it("fails before readiness when the first durable-log parent sync fails", async () => {
    const test = await fixture({ realAppendParentSyncFailure: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringContaining("real durable-log parent sync failed"),
      ok: false,
    });
    expect(test.state.getSnapshot()).toMatchObject({ status: "failed" });
  });

  it("fails before readiness when the absent durable-log directory chain cannot be synced", async () => {
    const test = await fixture({ realDurableDirectorySyncFailure: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: expect.stringContaining("real durable-log directory sync failed"),
      ok: false,
    });
    expect(test.state.getSnapshot()).toMatchObject({ status: "failed" });
    await expect(test.controller.retry()).resolves.toMatchObject({ ok: true, revision });
    expect(test.state.getSnapshot()).toMatchObject({ phase: "complete", status: "ready" });
  });

  it("makes shutdown terminal and joins a queued retry before resolving", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1),
      { timeout: 15_000 },
    );
    const cancellation = test.controller.cancel();
    const retry = test.controller.retry();
    const shutdown = test.controller.shutdown();

    test.releasePythonSync();
    await expect(Promise.all([first, cancellation, shutdown])).resolves.toBeDefined();
    await expect(retry).resolves.toMatchObject({ error: expect.stringMatching(/shutting down|shutdown/i), ok: false });
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);
    await expect(test.controller.start()).resolves.toMatchObject({ error: expect.stringMatching(/shutting down|shutdown/i), ok: false });
    await expect(test.controller.retry()).resolves.toMatchObject({ error: expect.stringMatching(/shutting down|shutdown/i), ok: false });
  });

  it("latches unproved containment over cancellation, keeps the lease and blocks quit or retry", async () => {
    const test = await fixture({ uncontainedOnAbort: true });
    const running = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1),
      { timeout: 15_000 },
    );

    const cancellation = test.controller.cancel();
    await expect(running).resolves.toMatchObject({
      containmentFailed: true,
      error: expect.stringMatching(/containment.*not be proven|restart is blocked/i),
      ok: false,
    });
    await expect(cancellation).resolves.toBe(true);
    expect(await exists(path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock"))).toBe(true);
    await expect(test.controller.retry()).resolves.toMatchObject({
      containmentFailed: true,
      error: expect.stringMatching(/containment.*not be proven|restart is blocked/i),
      ok: false,
    });
    await expect(test.controller.start()).resolves.toMatchObject({
      containmentFailed: true,
      error: expect.stringMatching(/containment.*not be proven|restart is blocked/i),
      ok: false,
    });
    expect(test.state.getSnapshot()).toMatchObject({
      failure: expect.stringMatching(/containment.*not be proven|restart is blocked/i),
      message: expect.stringMatching(/containment.*not be proven|restart is blocked/i),
      phase: "failed",
      status: "failed",
    });
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);

    const app = { quit: vi.fn() };
    const gate = createBootstrapQuitGate(app, test.controller, 100);
    await expect(gate.requestQuit()).rejects.toThrow(/containment.*not be proven|restart is blocked/i);
    expect(app.quit).not.toHaveBeenCalled();
  });

  it("retains the operation lease when the command runner rejects without a containment result", async () => {
    const test = await fixture({ commandRejection: "git-probe" });

    await expect(test.controller.start()).resolves.toMatchObject({
      containmentFailed: true,
      error: expect.stringMatching(/command.*reject|containment.*not be proven/i),
      ok: false,
    });
    expect(await exists(path.join(test.root, "source", ".flinttrade-bootstrap-operation.lock"))).toBe(true);
    await expect(test.controller.shutdown(100)).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
  });

  it("keeps an immediate start joined to a cancelling attempt through shutdown", async () => {
    const test = await fixture({ holdPythonSync: true });
    const running = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1),
      { timeout: 15_000 },
    );

    const cancellation = test.controller.cancel();
    const restarted = test.controller.start();
    const shutdown = test.controller.shutdown();
    expect(restarted).toBe(running);

    test.releasePythonSync();
    await expect(Promise.all([running, restarted, cancellation, shutdown])).resolves.toBeDefined();
    expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1);
    expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });
  });

  it("allows a later bounded shutdown wait after stubborn bootstrap work settles", async () => {
    const test = await fixture({ holdPythonSync: true });
    const running = test.controller.start();
    await vi.waitFor(
      () => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1),
      { timeout: 15_000 },
    );
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    try {
      const shutdown = test.controller.shutdown(20).catch((error: unknown) => error);
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(unhandled).not.toHaveBeenCalled();

      test.releasePythonSync();
      await running;
      await expect(shutdown).resolves.toBeInstanceOf(Error);
      await expect(test.controller.shutdown(100)).resolves.toBeUndefined();
      await expect(test.controller.start()).resolves.toMatchObject({
        error: expect.stringMatching(/shutting down/i),
        ok: false,
      });
    } finally {
      process.off("unhandledRejection", unhandled);
      test.releasePythonSync();
    }
  });

  it("shutdown awaits in-flight lock cleanup before readiness can become terminal", async () => {
    const test = await fixture({ holdLockRelease: true });
    const running = test.controller.start();
    await vi.waitFor(() => expect(exists(test.activeSource)).resolves.toBe(true), { timeout: 15_000 });
    expect(test.state.getSnapshot().status).toBe("running");
    let shutdownSettled = false;
    const shutdown = test.controller.shutdown().then(() => {
      shutdownSettled = true;
    });
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(shutdownSettled).toBe(false);

    test.releaseLockCleanup();
    const [result] = await Promise.all([running, shutdown]);
    expect(result).toMatchObject({ cancelled: true, ok: false });
    expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });
    expect(shutdownSettled).toBe(true);
  });
});
