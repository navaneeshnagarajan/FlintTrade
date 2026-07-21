import { createHash } from "node:crypto";
import {
  access,
  appendFile,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BOOTSTRAP_MARKER,
  createFirstRunBootstrap,
  type BootstrapBoundary,
  type BootstrapDependencies,
  type BootstrapToolManifest,
  type CommandInvocation,
} from "./bootstrap";
import { createBootstrapState } from "./state";

const revision = "a".repeat(40);
const nodeBytes = Buffer.from("pinned node archive");
const uvBytes = Buffer.from("pinned uv archive");
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
const manifest: BootstrapToolManifest = {
  schemaVersion: 1,
  generatedFrom: {
    node: { sha256: "1".repeat(64), url: "https://nodejs.org/dist/v22.23.1/SHASUMS256.txt" },
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
  gitAvailable?: boolean;
  gitOrigin?: string;
  holdPythonSync?: boolean;
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
        if (invocation.command === "node") return { exitCode: 127, stderr: "node missing", stdout: "" };
        if (invocation.args[0] === "--version" && invocation.command.includes("uv")) {
          return { exitCode: 0, stderr: "", stdout: "uv 0.11.16 (135a36367 2026-05-21 aarch64-apple-darwin)\n" };
        }
        if (invocation.args[0] === "--version" && path.basename(invocation.command) === "node") {
          return { exitCode: 0, stderr: "", stdout: "v22.23.1\n" };
        }
        if (invocation.args[0] === "--version" && path.basename(invocation.command) === "corepack") {
          return { exitCode: 0, stderr: "", stdout: "0.34.6\n" };
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
      },
      async text() {
        return JSON.stringify({ sha: revision });
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
          return [manifest.uv.assets["darwin-arm64"]!.executable];
        }
        if (name.startsWith("node-")) {
          const executable = path.join(destination, manifest.node.assets["darwin-arm64"]!.executable);
          await mkdir(path.dirname(executable), { recursive: true });
          await writeFile(executable, "node");
          const corepack = path.join(path.dirname(executable), "corepack");
          await writeFile(corepack, "corepack");
          return [manifest.node.assets["darwin-arm64"]!.executable, path.relative(destination, corepack)];
        }
        const extracted = path.join(destination, `FlintTrade-${revision}`);
        await writeRepositoryShape(extracted, false);
        if (options.badArchiveShape) await rm(path.join(extracted, "uv.lock"));
        return [
          `FlintTrade-${revision}/package.json`,
          `FlintTrade-${revision}/pyproject.toml`,
          `FlintTrade-${revision}/uv.lock`,
          `FlintTrade-${revision}/pnpm-lock.yaml`,
        ];
      }),
    fileSystem: {
      appendText: (target, content) => appendFile(target, content),
      exists,
      mkdir: (target) => mkdir(target, { recursive: true }),
      readText: (target) => readFile(target, "utf8"),
      realpath,
      remove: (target) => rm(target, { force: true, recursive: true }),
      rename,
      sha256: async (target) => sha256(await readFile(target)),
      writeTextAtomic: async (target, content) => {
        const temporary = `${target}.tmp`;
        await mkdir(path.dirname(target), { recursive: true });
        await writeFile(temporary, content);
        await rename(temporary, target);
      },
    },
  };
  const state = createBootstrapState();
  const controller = createFirstRunBootstrap({
    arch: "arm64",
    dependencies,
    heartbeatIntervalMs: 5,
    manifest,
    ...(options.boundary
      ? {
          onPromotionBoundary: async (boundary: BootstrapBoundary) => {
            if (boundary === options.boundary) throw new Error(`interrupted at ${boundary}`);
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
  return { activeSource, calls, controller, dependencies, downloads, releasePythonSync: releasePythonSync!, root, state };
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
    expect(marker).toMatchObject({ provenance: "git", revision, schemaVersion: 1 });
    expect(test.calls.map((call) => call.args)).toContainEqual([
      "sync",
      "--frozen",
      "--all-packages",
      "--no-install-package",
      "flinttrade-ticks",
    ]);
    expect(test.calls.map((call) => call.args)).toContainEqual(["pnpm", "install", "--frozen-lockfile"]);
    expect(test.calls.map((call) => call.args)).toContainEqual([
      "pnpm",
      "--filter",
      "@flinttrade/terminal",
      "build",
    ]);
    const syncCall = test.calls.find((call) => call.args[0] === "sync");
    expect(syncCall?.env).toMatchObject({
      COREPACK_DEFAULT_TO_LATEST: "0",
      COREPACK_HOME: path.join(test.root, "tools", "corepack"),
      UV_CACHE_DIR: path.join(test.root, "tools", "uv-cache"),
      UV_NO_EDITABLE: "1",
      UV_PYTHON: "3.12",
      UV_PYTHON_INSTALL_DIR: path.join(test.root, "tools", "python"),
    });
    const corepackProbe = test.calls.find(
      (call) => path.basename(call.command) === "corepack" && call.args[0] === "--version",
    );
    expect(corepackProbe?.env?.PATH).toMatch(
      new RegExp(`^${path.join(test.root, "tools", "node", "22.23.1", "darwin-arm64")}`),
    );
    expect(test.calls.some((call) => /cargo/i.test([call.command, ...call.args].join(" ")))).toBe(false);
  });

  it("falls back to a commit-pinned GitHub archive and validates its repository shape", async () => {
    const test = await fixture({ gitAvailable: false });
    const result = await test.controller.start();

    expect(result).toMatchObject({ ok: true, provenance: "github-archive", revision });
    expect(test.downloads).toContain(`https://github.com/navaneeshnagarajan/FlintTrade/archive/${revision}.zip`);
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

  it("cancels a running attempt and prevents its stale worker from promoting", async () => {
    const test = await fixture({ holdPythonSync: true });
    const first = test.controller.start();
    await vi.waitFor(() => expect(test.calls.some((call) => call.args[0] === "sync")).toBe(true));
    expect(test.controller.cancel()).toBe(true);
    expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });

    const retry = test.controller.retry();
    test.releasePythonSync();
    await first;
    await retry;

    expect(test.state.getSnapshot().attempt).toBe(2);
    expect(test.state.getSnapshot().status).toBe("ready");
    expect(await exists(test.activeSource)).toBe(true);
  });

  it("writes redacted durable failure logs", async () => {
    const test = await fixture({
      onExtract: async () => {
        throw new Error("download failed at https://user:secret@example.test/tool?token=private");
      },
    });
    await test.controller.start();
    const logs = await readFile(path.join(test.root, "workspace", "logs", "desktop-bootstrap.jsonl"), "utf8");

    expect(logs).toContain("<redacted-url>");
    expect(logs).not.toContain("secret");
    expect(logs).not.toContain("private");
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
});
