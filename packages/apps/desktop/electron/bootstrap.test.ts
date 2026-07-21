import { createHash } from "node:crypto";
import {
  access,
  appendFile,
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BOOTSTRAP_MARKER,
  SOURCE_INPUTS_RECORD,
  createFirstRunBootstrap,
  type BootstrapBoundary,
  type BootstrapDependencies,
  type BootstrapToolManifest,
  type CommandInvocation,
} from "./bootstrap";
import { createNodeBootstrapDependencies } from "./bootstrap-io";
import { createBootstrapState } from "./state";

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

async function writeRepositoryShape(root: string, git: boolean): Promise<void> {
  await mkdir(path.join(root, "packages", "apps", "terminal"), { recursive: true });
  if (git) await mkdir(path.join(root, ".git"), { recursive: true });
  await writeFile(
    path.join(root, "package.json"),
    JSON.stringify({ name: "flinttrade-monorepo", packageManager: "pnpm@9.15.0+sha512.test" }),
  );
  for (const file of ["pyproject.toml", "uv.lock", "pnpm-lock.yaml"]) await writeFile(path.join(root, file), file);
  await writeFile(path.join(root, "packages", "apps", "terminal", "package.json"), '{"name":"@flinttrade/terminal"}');
}

interface FixtureOptions {
  badArchiveShape?: boolean;
  badUvChecksum?: boolean;
  boundary?: BootstrapBoundary;
  destinationAppearance?: "empty-directory" | "file" | "non-empty-directory" | "symlink";
  gitAvailable?: boolean;
  gitOrigin?: string;
  holdPythonSync?: boolean;
  holdLockRelease?: boolean;
  logFailure?: "permanent" | "transient";
  outputLogFailure?: boolean;
  mutateTrackedDuringBuild?: boolean;
  onExtract?: BootstrapDependencies["extractArchive"];
}

async function fixture(options: FixtureOptions = {}) {
  const root = await mkdtemp(path.join(tmpdir(), "flinttrade-bootstrap-test-"));
  scratchRoots.push(root);
  const sourceRoot = path.join(root, "source");
  const activeSource = path.join(sourceRoot, "FlintTrade");
  const calls: CommandInvocation[] = [];
  const downloads: string[] = [];
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
  let buildMutated = false;
  const nodeDependencies = createNodeBootstrapDependencies("darwin");

  const dependencies: BootstrapDependencies = {
    command: {
      async run(invocation) {
        calls.push(invocation);
        if (invocation.command === "git" && invocation.args[0] === "--version") {
          return options.gitAvailable === false
            ? { exitCode: 127, stderr: "git missing", stdout: "" }
            : { exitCode: 0, stderr: "", stdout: "git version 2.50.1\n" };
        }
        if (invocation.command === "git" && invocation.args[0] === "clone") {
          await writeRepositoryShape(invocation.args.at(-1)!, true);
          return { exitCode: 0, stderr: "", stdout: "" };
        }
        if (path.basename(invocation.command) === "git" && invocation.args[0] === "rev-parse") {
          return { exitCode: 0, stderr: "", stdout: `${revision}\n` };
        }
        if (path.basename(invocation.command) === "git" && invocation.args[0] === "remote") {
          return {
            exitCode: 0,
            stderr: "",
            stdout: `${options.gitOrigin ?? "https://github.com/navaneeshnagarajan/FlintTrade.git"}\n`,
          };
        }
        if (path.basename(invocation.command) === "git" && invocation.args[0] === "status") {
          return { exitCode: 0, stderr: "", stdout: buildMutated ? " M uv.lock\n" : "" };
        }
        if (invocation.args[0] === "--version" && invocation.command.includes("uv")) {
          return { exitCode: 0, stderr: "", stdout: "uv 0.11.16 (135a36367 2026-05-21 aarch64-apple-darwin)\n" };
        }
        if (invocation.args[0] === "--version" && path.basename(invocation.command) === "node") {
          return { exitCode: 0, stderr: "", stdout: "v22.23.1\n" };
        }
        if (path.basename(invocation.command) === "node" && invocation.args.at(-1) === "--version") {
          return { exitCode: 0, stderr: "", stdout: "0.34.6\n" };
        }
        if (invocation.command === "/bin/sh") {
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-python\t48\tInstalling managed Python 3.12", "stdout");
          if (options.holdPythonSync) await pythonSyncHeld;
          if (options.mutateTrackedDuringBuild) {
            buildMutated = true;
            await writeFile(path.join(invocation.args[1]!, "uv.lock"), "mutated");
          }
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-javascript\t68\tInstalling pnpm 9.15.0 dependencies", "stdout");
          invocation.onOutput?.("FLINTTRADE_BOOTSTRAP_PHASE\tbuilding-terminal\t84\tBuilding the terminal for production", "stdout");
          return { exitCode: 0, stderr: "", stdout: "" };
        }
        if (options.holdPythonSync && invocation.args[0] === "sync") {
          await pythonSyncHeld;
          return { exitCode: 0, stderr: "", stdout: "late worker output" };
        }
        return { exitCode: 0, stderr: "", stdout: "" };
      },
    },
    download: {
      async file(url, destination) {
        downloads.push(url);
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
        const content = JSON.stringify({ sha: revision });
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
      (async ({ archive, destination }) => {
        const name = path.basename(archive);
        if (name.startsWith("uv-")) {
          const executable = path.join(destination, manifest.uv.assets["darwin-arm64"]!.executable);
          await mkdir(path.dirname(executable), { recursive: true });
          await writeFile(executable, "uv");
          await chmod(executable, 0o755);
          return [manifest.uv.assets["darwin-arm64"]!.executable];
        }
        if (name.startsWith("node-")) {
          const executable = path.join(destination, manifest.node.assets["darwin-arm64"]!.executable);
          await mkdir(path.dirname(executable), { recursive: true });
          await writeFile(executable, "node");
          await chmod(executable, 0o755);
          const corepack = path.join(
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
          return [manifest.node.assets["darwin-arm64"]!.executable, path.relative(destination, corepack)];
        }
        const extracted = path.join(destination, `FlintTrade-${revision}`);
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
        await appendFile(target, content);
      },
    },
  };
  const state = createBootstrapState();
  const controller = createFirstRunBootstrap({
    arch: "arm64",
    bootstrapResources: path.resolve(import.meta.dirname, "..", "resources", "bootstrap"),
    dependencies,
    heartbeatIntervalMs: 5,
    manifest,
    ...(options.boundary || options.destinationAppearance
      ? {
          onPromotionBoundary: async (boundary: BootstrapBoundary) => {
            if (boundary === options.boundary) throw new Error(`interrupted at ${boundary}`);
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
    platform: "darwin",
    state,
  });
  return {
    activeSource,
    calls,
    controller,
    dependencies,
    downloads,
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
    expect(marker).toMatchObject({ provenance: "git", revision, schemaVersion: 2, gitTree: revision });
    const buildCall = test.calls.find((call) => call.command === "/bin/sh");
    expect(buildCall?.args[0]).toMatch(/resources\/bootstrap\/flinttrade-bootstrap\.sh$/);
    expect(buildCall?.args[1]).toContain("FlintTrade.candidate-1");
    expect(buildCall?.args.at(-1)).toBe("9.15.0");
    expect(buildCall?.args.some((argument) => argument.endsWith("corepack.js"))).toBe(true);
    expect(test.calls.some((call) => call.command.endsWith("corepack.cmd"))).toBe(false);
    expect(test.calls.some((call) => /cargo/i.test([call.command, ...call.args].join(" ")))).toBe(false);
  });

  it("falls back to a commit-pinned GitHub archive and validates its repository shape", async () => {
    const test = await fixture({ gitAvailable: false });
    const result = await test.controller.start();

    expect(result).toMatchObject({ ok: true, provenance: "github-archive", revision });
    expect(test.downloads).toContain(`https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip/${revision}`);
    expect(test.downloads.some((url) => url.endsWith("/main.zip"))).toBe(false);
    const marker = JSON.parse(await readFile(path.join(test.activeSource, BOOTSTRAP_MARKER), "utf8"));
    expect(marker).toMatchObject({ provenance: "github-archive", revision });
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
      error: "Git provenance validation rejected the origin URL.",
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
      expect(await exists(`${test.activeSource}.candidate-1`)).toBe(true);
    },
  );

  it("cancels a running attempt and prevents its stale worker from promoting", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(() => expect(test.calls.some((call) => call.command === "/bin/sh")).toBe(true));
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
  });

  it("serialises an immediate retry behind cancelled-attempt process and lock settlement", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(() => expect(test.calls.filter((call) => call.command === "/bin/sh")).toHaveLength(1));

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

  it("rejects an existing checkout whose HEAD no longer matches its completion marker", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const markerPath = path.join(test.activeSource, ".git", BOOTSTRAP_MARKER);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.revision = "b".repeat(40);
    await writeFile(markerPath, JSON.stringify(marker));

    await expect(test.controller.start()).resolves.toMatchObject({
      ok: false,
      error: "The active Git checkout does not match its bootstrap provenance marker.",
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

  it("re-extracts a tool when its installed tree and mutable marker are modified together", async () => {
    const test = await fixture();
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const installRoot = path.join(test.root, "tools", "uv", "0.11.16", "darwin-arm64");
    const executable = path.join(installRoot, manifest.uv.assets["darwin-arm64"]!.executable);
    const markerPath = `${installRoot}.flinttrade-tool-verified.json`;
    await writeFile(executable, "tampered");
    await chmod(executable, 0o755);
    const forgedTree = await test.dependencies.fileSystem.snapshotSourceTree(installRoot);
    const marker = JSON.parse(await readFile(markerPath, "utf8"));
    marker.treeDigest = forgedTree.digest;
    marker.executableSha256 = forgedTree.entries.find((entry) => entry.path.endsWith("/uv"))?.sha256;
    await writeFile(markerPath, JSON.stringify(marker));
    await rm(test.activeSource, { recursive: true });

    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });

    expect(await readFile(executable, "utf8")).toBe("uv");
  });

  it("fails a Git build hook which mutates a tracked source input", async () => {
    const test = await fixture({ mutateTrackedDuringBuild: true });

    await expect(test.controller.start()).resolves.toMatchObject({
      error: "The Git candidate has tracked or index changes after its build.",
      ok: false,
    });
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

  it("binds archive digest, final origin and canonical source inputs into marker v2", async () => {
    const test = await fixture({ gitAvailable: false });
    await expect(test.controller.start()).resolves.toMatchObject({ ok: true });
    const marker = JSON.parse(await readFile(path.join(test.activeSource, BOOTSTRAP_MARKER), "utf8"));
    const sourceInputs = JSON.parse(await readFile(path.join(test.activeSource, SOURCE_INPUTS_RECORD), "utf8"));

    expect(marker).toMatchObject({
      archiveFinalOrigin: "https://codeload.github.com",
      archiveSha256: sha256(nodeBytes),
      provenance: "github-archive",
      schemaVersion: 2,
      sourceInputDigest: sourceInputs.digest,
    });
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

  it("shutdown awaits in-flight lock cleanup after the state is already terminal", async () => {
    const test = await fixture({ holdLockRelease: true });
    const running = test.controller.start();
    await vi.waitFor(() => expect(test.state.getSnapshot().status).toBe("ready"));
    let shutdownSettled = false;
    const shutdown = test.controller.shutdown().then(() => {
      shutdownSettled = true;
    });
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(shutdownSettled).toBe(false);

    test.releaseLockCleanup();
    await expect(Promise.all([running, shutdown])).resolves.toBeDefined();
    expect(shutdownSettled).toBe(true);
  });
});
