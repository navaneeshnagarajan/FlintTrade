// Bootstrap orchestration shape adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import path from "node:path";

import type { DesktopPaths } from "./paths";
import type { BootstrapPhase, createBootstrapState } from "./state";

export const BOOTSTRAP_MARKER = ".flinttrade-bootstrap-complete.json";
const REPOSITORY_URL = "https://github.com/navaneeshnagarajan/FlintTrade.git";
const MAIN_COMMIT_URL = "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/commits/main";
const ARCHIVE_BASE_URL = "https://github.com/navaneeshnagarajan/FlintTrade/archive";
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;

export type BootstrapBoundary = "before-marker" | "after-marker" | "before-rename" | "after-rename";
export type BootstrapProvenance = "git" | "github-archive";

export interface ManifestAsset {
  archive: "tar.gz" | "zip";
  executable: string;
  sha256: string;
  url: string;
}

export interface BootstrapToolManifest {
  generatedFrom: {
    node: { sha256: string; url: string };
    uv: { sha256: string; url: string };
  };
  node: { assets: Record<string, ManifestAsset>; version: string };
  pnpm: { integrity: string; packageManager: string; version: string };
  schemaVersion: number;
  uv: { assets: Record<string, ManifestAsset>; version: string };
}

export interface CommandInvocation {
  args: string[];
  command: string;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  onOutput?: (line: string, stream: "stdout" | "stderr") => void;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface CommandResult {
  exitCode: number;
  stderr: string;
  stdout: string;
}

export interface BootstrapDependencies {
  command: { run(invocation: CommandInvocation): Promise<CommandResult> };
  download: {
    file(url: string, destination: string, signal: AbortSignal): Promise<void>;
    text(url: string, signal: AbortSignal): Promise<string>;
  };
  extractArchive(input: {
    archive: string;
    destination: string;
    kind: "tar.gz" | "zip";
    signal: AbortSignal;
  }): Promise<string[]>;
  fileSystem: {
    appendText(target: string, content: string): Promise<void>;
    exists(target: string): Promise<boolean>;
    mkdir(target: string): Promise<unknown>;
    readText(target: string): Promise<string>;
    realpath(target: string): Promise<string>;
    remove(target: string): Promise<void>;
    rename(source: string, destination: string): Promise<void>;
    sha256(target: string): Promise<string>;
    writeTextAtomic(target: string, content: string): Promise<void>;
  };
}

interface BootstrapOptions {
  arch: string;
  dependencies: BootstrapDependencies;
  heartbeatIntervalMs?: number;
  manifest: BootstrapToolManifest;
  onPromotionBoundary?: (boundary: BootstrapBoundary) => Promise<void> | void;
  paths: DesktopPaths;
  platform: NodeJS.Platform;
  repository?: {
    archiveBaseUrl: string;
    branch: string;
    commitMetadataUrl: string;
    gitUrl: string;
  };
  state: ReturnType<typeof createBootstrapState>;
}

export interface BootstrapResult {
  cancelled?: boolean;
  error?: string;
  ok: boolean;
  provenance?: BootstrapProvenance;
  revision?: string;
}

interface SourceIdentity {
  provenance: BootstrapProvenance;
  revision: string;
}

interface ToolPaths {
  corepack: string;
  node: string;
  uv: string;
}

function redact(value: string): string {
  return value
    .replace(/https?:\/\/[^\s"']+/gi, "<redacted-url>")
    .replace(/\b(token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+/gi, "$1$2<redacted>");
}

function requireCommit(value: string): string {
  const commit = value.trim().toLowerCase();
  if (!COMMIT_PATTERN.test(commit)) throw new Error("Source provenance did not provide a full Git commit.");
  return commit;
}

function markerPath(root: string, provenance: BootstrapProvenance): string {
  return provenance === "git" ? path.join(root, ".git", BOOTSTRAP_MARKER) : path.join(root, BOOTSTRAP_MARKER);
}

function archiveName(url: string): string {
  return path.basename(new URL(url).pathname);
}

function isWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export function createFirstRunBootstrap(options: BootstrapOptions) {
  const { dependencies, manifest, paths: desktopPaths, state } = options;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? 2_000;
  const target = `${options.platform}-${options.arch}`;
  const repository =
    options.repository ??
    Object.freeze({
      archiveBaseUrl: ARCHIVE_BASE_URL,
      branch: "main",
      commitMetadataUrl: MAIN_COMMIT_URL,
      gitUrl: REPOSITORY_URL,
    });
  let currentAbort: AbortController | null = null;
  let currentPromise: Promise<BootstrapResult> | null = null;
  let logQueue = Promise.resolve();

  const logPath = path.join(desktopPaths.logs, "desktop-bootstrap.jsonl");

  const log = (attempt: number, phase: BootstrapPhase, message: string): Promise<void> => {
    const event = { attempt, at: new Date().toISOString(), message: redact(message), phase };
    logQueue = logQueue.then(async () => {
      await dependencies.fileSystem.mkdir(desktopPaths.logs);
      await dependencies.fileSystem.appendText(logPath, `${JSON.stringify(event)}\n`);
    });
    return logQueue;
  };

  const publish = async (
    attempt: number,
    phase: BootstrapPhase,
    message: string,
    progress: number | null,
  ): Promise<void> => {
    state.publishForAttempt(attempt, { message: redact(message), phase, progress });
    await log(attempt, phase, message);
  };

  const assertAttempt = (attempt: number, signal: AbortSignal): void => {
    const snapshot = state.getSnapshot();
    if (signal.aborted || snapshot.attempt !== attempt || snapshot.status !== "running") {
      throw new DOMException("Bootstrap attempt was cancelled or superseded.", "AbortError");
    }
  };

  const runCommand = async (
    attempt: number,
    signal: AbortSignal,
    invocation: Omit<CommandInvocation, "signal">,
  ): Promise<CommandResult> => {
    assertAttempt(attempt, signal);
    const result = await dependencies.command.run({
      ...invocation,
      onOutput: (line, stream) => {
        void log(attempt, state.getSnapshot().phase, `${stream}: ${line}`);
        invocation.onOutput?.(line, stream);
      },
      signal,
    });
    assertAttempt(attempt, signal);
    return result;
  };

  const requiredCommand = async (
    attempt: number,
    signal: AbortSignal,
    invocation: Omit<CommandInvocation, "signal">,
  ): Promise<CommandResult> => {
    const result = await runCommand(attempt, signal, invocation);
    if (result.exitCode !== 0) throw new Error(redact(result.stderr.trim() || "A required command failed."));
    return result;
  };

  const readExistingMarker = async (): Promise<SourceIdentity | null> => {
    if (!(await dependencies.fileSystem.exists(desktopPaths.activeSource))) return null;
    for (const provenance of ["git", "github-archive"] as const) {
      const candidate = markerPath(desktopPaths.activeSource, provenance);
      if (!(await dependencies.fileSystem.exists(candidate))) continue;
      const parsed = JSON.parse(await dependencies.fileSystem.readText(candidate)) as Partial<SourceIdentity> & {
        repository?: string;
        schemaVersion?: number;
      };
      if (
        parsed.schemaVersion !== 1 ||
        parsed.provenance !== provenance ||
        parsed.repository !== repository.gitUrl ||
        !parsed.revision
      ) {
        break;
      }
      return { provenance, revision: requireCommit(parsed.revision) };
    }
    throw new Error("The active source path exists without a valid FlintTrade bootstrap marker.");
  };

  const validateRepositoryShape = async (root: string): Promise<void> => {
    for (const relative of [
      "package.json",
      "pyproject.toml",
      "uv.lock",
      "pnpm-lock.yaml",
      path.join("packages", "apps", "terminal", "package.json"),
    ]) {
      if (!(await dependencies.fileSystem.exists(path.join(root, relative)))) {
        throw new Error(`Source archive is not a FlintTrade checkout: missing ${relative}.`);
      }
    }
    const packageMetadata = JSON.parse(await dependencies.fileSystem.readText(path.join(root, "package.json"))) as {
      name?: string;
      packageManager?: string;
    };
    if (
      packageMetadata.name !== "flinttrade-monorepo" ||
      packageMetadata.packageManager !== manifest.pnpm.packageManager
    ) {
      throw new Error("Source provenance validation rejected the repository package identity.");
    }
  };

  const acquireArchive = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
  ): Promise<SourceIdentity> => {
    await publish(attempt, "cloning-source", "Resolving the public main archive", 12);
    const metadata = JSON.parse(await dependencies.download.text(repository.commitMetadataUrl, signal)) as { sha?: unknown };
    const revision = requireCommit(typeof metadata.sha === "string" ? metadata.sha : "");
    assertAttempt(attempt, signal);
    const downloadDirectory = path.join(desktopPaths.sourceRoot, ".downloads");
    const archive = path.join(downloadDirectory, `FlintTrade-${revision}.zip`);
    const unpack = `${candidate}.unpack`;
    await dependencies.fileSystem.mkdir(downloadDirectory);
    await dependencies.download.file(`${repository.archiveBaseUrl}/${revision}.zip`, archive, signal);
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.remove(unpack);
    await dependencies.fileSystem.mkdir(unpack);
    const entries = await dependencies.extractArchive({ archive, destination: unpack, kind: "zip", signal });
    const archiveRoot = `FlintTrade-${revision}`;
    if (
      entries.length === 0 ||
      entries.some((entry) => {
        const normalised = entry.replace(/\\/g, "/");
        return normalised.startsWith("/") || normalised.split("/").includes("..") || !normalised.startsWith(`${archiveRoot}/`);
      })
    ) {
      throw new Error("GitHub source archive failed path and provenance validation.");
    }
    const extracted = path.join(unpack, archiveRoot);
    await validateRepositoryShape(extracted);
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.rename(extracted, candidate);
    await dependencies.fileSystem.remove(unpack);
    return { provenance: "github-archive", revision };
  };

  const acquireSource = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
  ): Promise<SourceIdentity> => {
    await publish(attempt, "checking-source", "Checking system Git", 5);
    const gitProbe = await runCommand(attempt, signal, { args: ["--version"], command: "git", timeoutMs: 15_000 });
    if (gitProbe.exitCode !== 0) return acquireArchive(attempt, signal, candidate);

    await publish(attempt, "cloning-source", "Cloning the public source checkout", 12);
    const clone = await runCommand(attempt, signal, {
      args: ["clone", "--branch", repository.branch, "--single-branch", "--no-tags", repository.gitUrl, candidate],
      command: "git",
      env: { GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 20 * 60_000,
    });
    if (clone.exitCode !== 0) {
      await dependencies.fileSystem.remove(candidate);
      return acquireArchive(attempt, signal, candidate);
    }
    await validateRepositoryShape(candidate);
    const head = await requiredCommand(attempt, signal, {
      args: ["rev-parse", "HEAD"],
      command: "git",
      cwd: candidate,
      timeoutMs: 15_000,
    });
    const remote = await requiredCommand(attempt, signal, {
      args: ["remote", "get-url", "origin"],
      command: "git",
      cwd: candidate,
      timeoutMs: 15_000,
    });
    if (remote.stdout.trim() !== repository.gitUrl) throw new Error("Git provenance validation rejected the origin URL.");
    return { provenance: "git", revision: requireCommit(head.stdout) };
  };

  const installTool = async (
    attempt: number,
    signal: AbortSignal,
    tool: "node" | "uv",
    asset: ManifestAsset,
    version: string,
  ): Promise<string> => {
    const installRoot = path.join(desktopPaths.toolsRoot, tool, version, target);
    const executable = path.join(installRoot, asset.executable);
    const verifiedMarker = path.join(installRoot, ".flinttrade-tool-verified.json");
    if ((await dependencies.fileSystem.exists(executable)) && (await dependencies.fileSystem.exists(verifiedMarker))) {
      const verified = JSON.parse(await dependencies.fileSystem.readText(verifiedMarker)) as { sha256?: string };
      if (verified.sha256 === asset.sha256) return executable;
    }

    const downloads = path.join(desktopPaths.toolsRoot, ".downloads");
    const archive = path.join(downloads, archiveName(asset.url));
    const extracting = `${installRoot}.extracting-${attempt}`;
    await dependencies.fileSystem.mkdir(downloads);
    await dependencies.download.file(asset.url, archive, signal);
    assertAttempt(attempt, signal);
    if ((await dependencies.fileSystem.sha256(archive)) !== asset.sha256) {
      throw new Error(`${tool} archive checksum verification failed.`);
    }
    await dependencies.fileSystem.remove(extracting);
    await dependencies.fileSystem.mkdir(extracting);
    await dependencies.extractArchive({ archive, destination: extracting, kind: asset.archive, signal });
    assertAttempt(attempt, signal);
    const extractedExecutable = path.join(extracting, asset.executable);
    if (!(await dependencies.fileSystem.exists(extractedExecutable))) {
      throw new Error(`${tool} archive did not contain its expected executable.`);
    }
    const canonicalRoot = await dependencies.fileSystem.realpath(extracting);
    const canonicalExecutable = await dependencies.fileSystem.realpath(extractedExecutable);
    if (!isWithin(canonicalRoot, canonicalExecutable)) throw new Error(`${tool} executable escaped its verified archive root.`);
    await dependencies.fileSystem.writeTextAtomic(
      path.join(extracting, ".flinttrade-tool-verified.json"),
      `${JSON.stringify({ sha256: asset.sha256, version })}\n`,
    );
    await dependencies.fileSystem.remove(installRoot);
    await dependencies.fileSystem.mkdir(path.dirname(installRoot));
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.rename(extracting, installRoot);
    return executable;
  };

  const provisionTools = async (attempt: number, signal: AbortSignal): Promise<ToolPaths> => {
    const uvAsset = manifest.uv.assets[target];
    const nodeAsset = manifest.node.assets[target];
    if (!uvAsset || !nodeAsset) throw new Error(`No verified bootstrap tool manifest exists for ${target}.`);
    await publish(attempt, "installing-tools", `Provisioning uv ${manifest.uv.version}`, 28);
    const uv = await installTool(attempt, signal, "uv", uvAsset, manifest.uv.version);
    const uvProbe = await requiredCommand(attempt, signal, { args: ["--version"], command: uv, timeoutMs: 15_000 });
    const escapedUvVersion = manifest.uv.version.replace(/\./g, "\\.");
    if (!new RegExp(`^uv ${escapedUvVersion}(?:\\s|$)`).test(uvProbe.stdout.trim())) {
      throw new Error("The verified uv executable reported an unexpected version.");
    }

    let node = "node";
    let corepack = options.platform === "win32" ? "corepack.cmd" : "corepack";
    const nodeProbe = await runCommand(attempt, signal, { args: ["--version"], command: node, timeoutMs: 15_000 });
    const compatibleSystemNode = /^v22\.(?:1[2-9]|2\d)\.\d+$/.test(nodeProbe.stdout.trim());
    const corepackProbe = compatibleSystemNode
      ? await runCommand(attempt, signal, { args: ["--version"], command: corepack, timeoutMs: 15_000 })
      : { exitCode: 1 };
    if (!compatibleSystemNode || corepackProbe.exitCode !== 0) {
      await publish(attempt, "installing-tools", `Provisioning Node ${manifest.node.version}`, 36);
      node = await installTool(attempt, signal, "node", nodeAsset, manifest.node.version);
      corepack = path.join(path.dirname(node), options.platform === "win32" ? "corepack.cmd" : "corepack");
      if (!(await dependencies.fileSystem.exists(corepack))) throw new Error("Verified Node distribution did not contain Corepack.");
      const downloadedNodeProbe = await requiredCommand(attempt, signal, {
        args: ["--version"],
        command: node,
        timeoutMs: 15_000,
      });
      if (downloadedNodeProbe.stdout.trim() !== `v${manifest.node.version}`) {
        throw new Error("The verified Node executable reported an unexpected version.");
      }
      await requiredCommand(attempt, signal, {
        args: ["--version"],
        command: corepack,
        env: {
          COREPACK_DEFAULT_TO_LATEST: "0",
          COREPACK_HOME: path.join(desktopPaths.toolsRoot, "corepack"),
          PATH: `${path.dirname(node)}${path.delimiter}${process.env.PATH ?? ""}`,
        },
        timeoutMs: 15_000,
      });
    }
    return { corepack, node, uv };
  };

  const buildCandidate = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
    tools: ToolPaths,
  ): Promise<void> => {
    const nodeDirectory = tools.node === "node" ? null : path.dirname(tools.node);
    const env: NodeJS.ProcessEnv = {
      COREPACK_DEFAULT_TO_LATEST: "0",
      COREPACK_HOME: path.join(desktopPaths.toolsRoot, "corepack"),
      PATH: nodeDirectory ? `${nodeDirectory}${path.delimiter}${process.env.PATH ?? ""}` : (process.env.PATH ?? ""),
      UV_CACHE_DIR: path.join(desktopPaths.toolsRoot, "uv-cache"),
      UV_NO_EDITABLE: "1",
      UV_PYTHON: "3.12",
      UV_PYTHON_INSTALL_DIR: path.join(desktopPaths.toolsRoot, "python"),
    };
    await publish(attempt, "syncing-python", "Installing managed Python 3.12", 48);
    await requiredCommand(attempt, signal, {
      args: ["python", "install", "3.12"],
      command: tools.uv,
      cwd: candidate,
      env,
      timeoutMs: 20 * 60_000,
    });
    await requiredCommand(attempt, signal, {
      args: ["sync", "--frozen", "--all-packages", "--no-install-package", "flinttrade-ticks"],
      command: tools.uv,
      cwd: candidate,
      env,
      timeoutMs: 45 * 60_000,
    });
    await publish(attempt, "syncing-javascript", `Installing pnpm ${manifest.pnpm.version} dependencies`, 68);
    const pnpmVersion = await requiredCommand(attempt, signal, {
      args: ["pnpm", "--version"],
      command: tools.corepack,
      cwd: candidate,
      env,
      timeoutMs: 10 * 60_000,
    });
    if (pnpmVersion.stdout.trim() && pnpmVersion.stdout.trim() !== manifest.pnpm.version) {
      throw new Error("Corepack resolved a pnpm version that does not match the repository pin.");
    }
    await requiredCommand(attempt, signal, {
      args: ["pnpm", "install", "--frozen-lockfile"],
      command: tools.corepack,
      cwd: candidate,
      env,
      timeoutMs: 30 * 60_000,
    });
    await publish(attempt, "building-terminal", "Building the terminal for production", 84);
    await requiredCommand(attempt, signal, {
      args: ["pnpm", "--filter", "@flinttrade/terminal", "build"],
      command: tools.corepack,
      cwd: candidate,
      env,
      timeoutMs: 30 * 60_000,
    });
  };

  const runAttempt = async (attempt: number, signal: AbortSignal): Promise<BootstrapResult> => {
    const heartbeat = setInterval(() => {
      const snapshot = state.getSnapshot();
      state.publishForAttempt(attempt, { message: snapshot.message });
    }, heartbeatIntervalMs);
    heartbeat.unref?.();
    const candidate = `${desktopPaths.activeSource}.candidate-${attempt}`;
    try {
      await log(attempt, "preparing", "Starting first-run source bootstrap");
      const existing = await readExistingMarker();
      if (existing) {
        await validateRepositoryShape(desktopPaths.activeSource);
        if (existing.provenance === "git") {
          const head = await requiredCommand(attempt, signal, {
            args: ["rev-parse", "HEAD"],
            command: "git",
            cwd: desktopPaths.activeSource,
            timeoutMs: 15_000,
          });
          const remote = await requiredCommand(attempt, signal, {
            args: ["remote", "get-url", "origin"],
            command: "git",
            cwd: desktopPaths.activeSource,
            timeoutMs: 15_000,
          });
          if (requireCommit(head.stdout) !== existing.revision || remote.stdout.trim() !== repository.gitUrl) {
            throw new Error("The active Git checkout does not match its bootstrap provenance marker.");
          }
        }
        state.complete(attempt, `Source ${existing.revision.slice(0, 12)} is ready`);
        return { ...existing, ok: true };
      }
      await dependencies.fileSystem.mkdir(desktopPaths.sourceRoot);
      await dependencies.fileSystem.mkdir(desktopPaths.toolsRoot);
      for (let stale = 1; stale <= attempt; stale += 1) {
        await dependencies.fileSystem.remove(`${desktopPaths.activeSource}.candidate-${stale}`);
        await dependencies.fileSystem.remove(`${desktopPaths.activeSource}.candidate-${stale}.unpack`);
      }
      assertAttempt(attempt, signal);
      const identity = await acquireSource(attempt, signal, candidate);
      const tools = await provisionTools(attempt, signal);
      await buildCandidate(attempt, signal, candidate, tools);
      if (identity.provenance === "git") {
        const builtHead = await requiredCommand(attempt, signal, {
          args: ["rev-parse", "HEAD"],
          command: "git",
          cwd: candidate,
          timeoutMs: 15_000,
        });
        if (requireCommit(builtHead.stdout) !== identity.revision) throw new Error("Built Git revision changed before promotion.");
      }
      assertAttempt(attempt, signal);
      if (await dependencies.fileSystem.exists(desktopPaths.activeSource)) {
        throw new Error("Active source appeared during first-run bootstrap; refusing to replace it.");
      }
      await options.onPromotionBoundary?.("before-marker");
      assertAttempt(attempt, signal);
      const marker = {
        completedAt: new Date().toISOString(),
        node: manifest.node.version,
        pnpm: manifest.pnpm.version,
        provenance: identity.provenance,
        repository: repository.gitUrl,
        revision: identity.revision,
        schemaVersion: 1,
        uv: manifest.uv.version,
      };
      await dependencies.fileSystem.writeTextAtomic(markerPath(candidate, identity.provenance), `${JSON.stringify(marker)}\n`);
      await options.onPromotionBoundary?.("after-marker");
      assertAttempt(attempt, signal);
      if (path.dirname(candidate) !== path.dirname(desktopPaths.activeSource)) {
        throw new Error("Candidate and active source are not same-filesystem siblings.");
      }
      await options.onPromotionBoundary?.("before-rename");
      assertAttempt(attempt, signal);
      await dependencies.fileSystem.rename(candidate, desktopPaths.activeSource);
      await options.onPromotionBoundary?.("after-rename");
      assertAttempt(attempt, signal);
      state.complete(attempt, `Source ${identity.revision.slice(0, 12)} is ready`);
      await log(attempt, "complete", `First-run source ${identity.revision} is ready`);
      return { ...identity, ok: true };
    } catch (error) {
      const cancelled = error instanceof DOMException && error.name === "AbortError";
      const message = redact(error instanceof Error ? error.message : String(error));
      if (!cancelled) state.fail(attempt, message);
      await log(attempt, cancelled ? "cancelled" : "failed", message);
      return { cancelled, error: message, ok: false };
    } finally {
      clearInterval(heartbeat);
    }
  };

  const launch = (attempt: number): Promise<BootstrapResult> => {
    const abort = new AbortController();
    currentAbort = abort;
    const promise = runAttempt(attempt, abort.signal);
    currentPromise = promise;
    void promise.finally(() => {
      if (currentPromise === promise) {
        currentAbort = null;
        currentPromise = null;
      }
    });
    return promise;
  };

  return {
    cancel(): boolean {
      const attempt = state.getSnapshot().attempt;
      const cancelled = state.cancel(attempt);
      if (cancelled) currentAbort?.abort();
      return cancelled;
    },
    retry(): Promise<BootstrapResult> {
      if (!state.retry()) return Promise.resolve({ error: "Bootstrap is not retryable.", ok: false });
      return launch(state.getSnapshot().attempt);
    },
    start(): Promise<BootstrapResult> {
      if (state.getSnapshot().status === "running" && currentPromise) return currentPromise;
      const attempt = state.begin("Preparing source bootstrap", "preparing");
      return launch(attempt);
    },
  };
}
