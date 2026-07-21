// Bootstrap orchestration shape adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import path from "node:path";

import type { DesktopPaths } from "./paths";
import type { BootstrapPhase, createBootstrapState } from "./state";

export const BOOTSTRAP_MARKER = ".flinttrade-bootstrap-complete.json";
export const SOURCE_INPUTS_RECORD = ".flinttrade-source-inputs.json";
const REPOSITORY_URL = "https://github.com/navaneeshnagarajan/FlintTrade.git";
const MAIN_COMMIT_URL = "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/commits/main";
const ARCHIVE_BASE_URL = "https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip";
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;

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
    node: {
      sha256: string;
      signature: { fingerprint: string; keySha256: string; sha256: string; url: string };
      url: string;
    };
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

export interface DownloadPolicy {
  allowedHosts: readonly string[];
  idleTimeoutMs: number;
  label: string;
  maxBytes: number;
  totalTimeoutMs: number;
}

export interface DownloadReceipt {
  bytes: number;
  finalUrl: string;
  origin: string;
  sha256: string;
}

export interface TextDownloadReceipt extends DownloadReceipt {
  content: string;
}

export interface SourceTreeEntry {
  mode: number;
  path: string;
  sha256?: string;
  target?: string;
  type: "file" | "symlink";
}

export interface SourceTreeIdentity {
  digest: string;
  entries: SourceTreeEntry[];
}

export interface BootstrapDependencies {
  command: { run(invocation: CommandInvocation): Promise<CommandResult> };
  download: {
    file(url: string, destination: string, signal: AbortSignal, policy: DownloadPolicy): Promise<DownloadReceipt>;
    text(url: string, signal: AbortSignal, policy: DownloadPolicy): Promise<TextDownloadReceipt>;
  };
  extractArchive(input: {
    archive: string;
    destination: string;
    expectedRoot?: string;
    kind: "tar.gz" | "zip";
    signal: AbortSignal;
  }): Promise<string[]>;
  fileSystem: {
    acquireOperationLock(target: string): Promise<() => Promise<void>>;
    appendText(target: string, content: string): Promise<void>;
    exists(target: string): Promise<boolean>;
    mkdir(target: string): Promise<unknown>;
    promoteAbsent(source: string, destination: string): Promise<void>;
    readText(target: string): Promise<string>;
    realpath(target: string): Promise<string>;
    remove(target: string): Promise<void>;
    rename(source: string, destination: string): Promise<void>;
    sha256(target: string): Promise<string>;
    snapshotSourceTree(root: string): Promise<SourceTreeIdentity>;
    verifySourceTree(root: string, identity: SourceTreeIdentity): Promise<boolean>;
    writeTextAtomic(target: string, content: string): Promise<void>;
  };
}

export interface BootstrapOptions {
  arch: string;
  bootstrapResources: string;
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
  archiveFinalOrigin?: string;
  archiveSha256?: string;
  gitTree?: string;
  provenance: BootstrapProvenance;
  revision: string;
  sourceTree?: SourceTreeIdentity;
}

interface InstalledMarker {
  archiveFinalOrigin?: string;
  archiveSha256?: string;
  completedAt: string;
  gitTree?: string;
  node: string;
  pnpm: string;
  provenance: BootstrapProvenance;
  repository: string;
  revision: string;
  schemaVersion: 2;
  sourceInputDigest?: string;
  sourceInputRecordSha256?: string;
  uv: string;
}

interface ToolPaths {
  corepackJs: string;
  node: string;
  uv: string;
}

interface ToolVerificationMarker {
  archiveSha256: string;
  executable: string;
  executableSha256: string;
  schemaVersion: 2;
  treeDigest: string;
  version: string;
}

const metadataPolicy: DownloadPolicy = Object.freeze({
  allowedHosts: ["api.github.com"],
  idleTimeoutMs: 30_000,
  label: "GitHub commit metadata",
  maxBytes: 1024 * 1024,
  totalTimeoutMs: 2 * 60_000,
});
const sourceArchivePolicy: DownloadPolicy = Object.freeze({
  allowedHosts: ["codeload.github.com"],
  idleTimeoutMs: 60_000,
  label: "FlintTrade source archive",
  maxBytes: 512 * 1024 * 1024,
  totalTimeoutMs: 10 * 60_000,
});
const nodeAssetPolicy: DownloadPolicy = Object.freeze({
  allowedHosts: ["nodejs.org"],
  idleTimeoutMs: 60_000,
  label: "Node tool archive",
  maxBytes: 256 * 1024 * 1024,
  totalTimeoutMs: 10 * 60_000,
});
const uvAssetPolicy: DownloadPolicy = Object.freeze({
  allowedHosts: ["github.com", "release-assets.githubusercontent.com"],
  idleTimeoutMs: 60_000,
  label: "uv tool archive",
  maxBytes: 256 * 1024 * 1024,
  totalTimeoutMs: 10 * 60_000,
});

export function redactBootstrapText(value: string): string {
  return value
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer <redacted>")
    .replace(/https?:\/\/[^\s"']+/gi, (url) => {
      try {
        const parsed = new URL(url);
        if (parsed.username || parsed.password) return `${parsed.protocol}//<redacted-credentials>@${parsed.host}<redacted-url>`;
      } catch {
        // The broad URL redaction below remains fail-closed for malformed values.
      }
      return "<redacted-url>";
    })
    .replace(
      /\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|broker[_-]?(?:token|secret|key)|token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+/gi,
      "$1$2<redacted>",
    );
}

function requireCommit(value: string): string {
  const commit = value.trim().toLowerCase();
  if (!COMMIT_PATTERN.test(commit)) throw new Error("Source provenance did not provide a full Git commit.");
  return commit;
}

function requireDigest(value: unknown, label: string): string {
  if (typeof value !== "string" || !DIGEST_PATTERN.test(value)) throw new Error(`${label} is not a SHA-256 digest.`);
  return value;
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

function corepackRelativePath(nodeExecutable: string, platform: NodeJS.Platform): string {
  const root = platform === "win32" ? path.posix.dirname(nodeExecutable) : path.posix.dirname(path.posix.dirname(nodeExecutable));
  return platform === "win32"
    ? path.posix.join(root, "node_modules", "corepack", "dist", "corepack.js")
    : path.posix.join(root, "lib", "node_modules", "corepack", "dist", "corepack.js");
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
  let retryPromise: Promise<BootstrapResult> | null = null;
  let logQueue: Promise<void> = Promise.resolve();
  const logFailures = new Map<number, string>();
  const logPath = path.join(desktopPaths.logs, "desktop-bootstrap.jsonl");

  const queueLog = async (attempt: number, phase: BootstrapPhase, message: string): Promise<void> => {
    const event = { attempt, at: new Date().toISOString(), message: redactBootstrapText(message), phase };
    const operation = logQueue.then(async () => {
      await dependencies.fileSystem.mkdir(desktopPaths.logs);
      await dependencies.fileSystem.appendText(logPath, `${JSON.stringify(event)}\n`);
    });
    logQueue = operation.catch((error) => {
      const detail = redactBootstrapText(error instanceof Error ? error.message : String(error));
      if (!logFailures.has(attempt)) logFailures.set(attempt, `Durable bootstrap log failed: ${detail}`);
    });
    await logQueue;
  };

  const assertLogging = (attempt: number): void => {
    const failure = logFailures.get(attempt);
    if (failure) throw new Error(failure);
  };

  const publish = async (
    attempt: number,
    phase: BootstrapPhase,
    message: string,
    progress: number | null,
  ): Promise<void> => {
    state.publishForAttempt(attempt, { message: redactBootstrapText(message), phase, progress });
    await queueLog(attempt, phase, message);
    assertLogging(attempt);
  };

  const assertAttempt = (attempt: number, signal: AbortSignal): void => {
    const snapshot = state.getSnapshot();
    if (signal.aborted || snapshot.attempt !== attempt || snapshot.status !== "running") {
      throw new DOMException("Bootstrap attempt was cancelled or superseded.", "AbortError");
    }
    assertLogging(attempt);
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
        void queueLog(attempt, state.getSnapshot().phase, `${stream}: ${line}`);
        invocation.onOutput?.(line, stream);
      },
      signal,
    });
    await logQueue;
    assertAttempt(attempt, signal);
    return result;
  };

  const requiredCommand = async (
    attempt: number,
    signal: AbortSignal,
    invocation: Omit<CommandInvocation, "signal">,
  ): Promise<CommandResult> => {
    const result = await runCommand(attempt, signal, invocation);
    if (result.exitCode !== 0) throw new Error(redactBootstrapText(result.stderr.trim() || "A required command failed."));
    return result;
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
    if (packageMetadata.name !== "flinttrade-monorepo" || packageMetadata.packageManager !== manifest.pnpm.packageManager) {
      throw new Error("Source provenance validation rejected the repository package identity.");
    }
  };

  const readGitIdentity = async (attempt: number, signal: AbortSignal, root: string): Promise<SourceIdentity> => {
    const head = await requiredCommand(attempt, signal, {
      args: ["rev-parse", "HEAD"],
      command: "git",
      cwd: root,
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 15_000,
    });
    const tree = await requiredCommand(attempt, signal, {
      args: ["rev-parse", "HEAD^{tree}"],
      command: "git",
      cwd: root,
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 15_000,
    });
    const remote = await requiredCommand(attempt, signal, {
      args: ["remote", "get-url", "origin"],
      command: "git",
      cwd: root,
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 15_000,
    });
    const status = await requiredCommand(attempt, signal, {
      args: ["status", "--porcelain=v1", "--untracked-files=no"],
      command: "git",
      cwd: root,
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 30_000,
    });
    if (remote.stdout.trim() !== repository.gitUrl) throw new Error("Git provenance validation rejected the origin URL.");
    if (status.stdout.trim() !== "") throw new Error("The Git candidate has tracked or index changes after its build.");
    return { gitTree: requireCommit(tree.stdout), provenance: "git", revision: requireCommit(head.stdout) };
  };

  const validateExistingMarker = async (): Promise<SourceIdentity | null> => {
    if (!(await dependencies.fileSystem.exists(desktopPaths.activeSource))) return null;
    for (const provenance of ["git", "github-archive"] as const) {
      const candidate = markerPath(desktopPaths.activeSource, provenance);
      if (!(await dependencies.fileSystem.exists(candidate))) continue;
      const parsed = JSON.parse(await dependencies.fileSystem.readText(candidate)) as Partial<InstalledMarker>;
      if (
        parsed.schemaVersion !== 2 ||
        parsed.provenance !== provenance ||
        parsed.repository !== repository.gitUrl ||
        !parsed.revision
      ) {
        break;
      }
      const revision = requireCommit(parsed.revision);
      if (provenance === "git") {
        return { gitTree: requireCommit(parsed.gitTree ?? ""), provenance, revision };
      }
      const archiveSha256 = requireDigest(parsed.archiveSha256, "Archive digest");
      const sourceInputDigest = requireDigest(parsed.sourceInputDigest, "Source input digest");
      const sourceInputRecordSha256 = requireDigest(parsed.sourceInputRecordSha256, "Source input record digest");
      if (typeof parsed.archiveFinalOrigin !== "string") throw new Error("Archive marker is missing its final origin.");
      const recordPath = path.join(desktopPaths.activeSource, SOURCE_INPUTS_RECORD);
      if (
        !(await dependencies.fileSystem.exists(recordPath)) ||
        (await dependencies.fileSystem.sha256(recordPath)) !== sourceInputRecordSha256
      ) {
        throw new Error("Archive source input record does not match its completion marker.");
      }
      const sourceTree = JSON.parse(await dependencies.fileSystem.readText(recordPath)) as SourceTreeIdentity;
      if (sourceTree.digest !== sourceInputDigest || !(await dependencies.fileSystem.verifySourceTree(desktopPaths.activeSource, sourceTree))) {
        throw new Error("Archive-backed source inputs changed after bootstrap.");
      }
      return {
        archiveFinalOrigin: parsed.archiveFinalOrigin,
        archiveSha256,
        provenance,
        revision,
        sourceTree,
      };
    }
    throw new Error("The active source path exists without a valid FlintTrade bootstrap marker.");
  };

  const acquireArchive = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
  ): Promise<SourceIdentity> => {
    await publish(attempt, "cloning-source", "Resolving the public main archive", 12);
    const metadataReceipt = await dependencies.download.text(
      repository.commitMetadataUrl,
      signal,
      metadataPolicy,
    );
    const metadata = JSON.parse(metadataReceipt.content) as { sha?: unknown };
    const revision = requireCommit(typeof metadata.sha === "string" ? metadata.sha : "");
    assertAttempt(attempt, signal);
    const downloadDirectory = path.join(desktopPaths.sourceRoot, ".downloads");
    const archive = path.join(downloadDirectory, `FlintTrade-${revision}.zip`);
    const unpack = `${candidate}.unpack`;
    await dependencies.fileSystem.mkdir(downloadDirectory);
    const receipt = await dependencies.download.file(
      `${repository.archiveBaseUrl}/${revision}`,
      archive,
      signal,
      sourceArchivePolicy,
    );
    assertAttempt(attempt, signal);
    if ((await dependencies.fileSystem.sha256(archive)) !== receipt.sha256) {
      throw new Error("Source archive changed after its bounded download.");
    }
    await dependencies.fileSystem.remove(unpack);
    await dependencies.fileSystem.mkdir(unpack);
    const archiveRoot = `FlintTrade-${revision}`;
    const entries = await dependencies.extractArchive({
      archive,
      destination: unpack,
      expectedRoot: archiveRoot,
      kind: "zip",
      signal,
    });
    if (entries.length === 0 || entries.some((entry) => entry !== archiveRoot && !entry.startsWith(`${archiveRoot}/`))) {
      throw new Error("GitHub source archive failed path and provenance validation.");
    }
    const extracted = path.join(unpack, archiveRoot);
    await validateRepositoryShape(extracted);
    const sourceTree = await dependencies.fileSystem.snapshotSourceTree(extracted);
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.rename(extracted, candidate);
    await dependencies.fileSystem.remove(unpack);
    return {
      archiveFinalOrigin: receipt.origin,
      archiveSha256: receipt.sha256,
      provenance: "github-archive",
      revision,
      sourceTree,
    };
  };

  const acquireSource = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
  ): Promise<SourceIdentity> => {
    await publish(attempt, "checking-source", "Checking system Git", 5);
    const gitProbe = await runCommand(attempt, signal, {
      args: ["--version"],
      command: "git",
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 15_000,
    });
    if (gitProbe.exitCode !== 0) return acquireArchive(attempt, signal, candidate);

    await publish(attempt, "cloning-source", "Cloning the public source checkout", 12);
    const clone = await runCommand(attempt, signal, {
      args: ["clone", "--branch", repository.branch, "--single-branch", "--no-tags", repository.gitUrl, candidate],
      command: "git",
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 20 * 60_000,
    });
    if (clone.exitCode !== 0) {
      await dependencies.fileSystem.remove(candidate);
      return acquireArchive(attempt, signal, candidate);
    }
    await validateRepositoryShape(candidate);
    return await readGitIdentity(attempt, signal, candidate);
  };

  const installTool = async (
    attempt: number,
    signal: AbortSignal,
    tool: "node" | "uv",
    asset: ManifestAsset,
    version: string,
  ): Promise<{ executable: string; tree: SourceTreeIdentity }> => {
    const installRoot = path.join(desktopPaths.toolsRoot, tool, version, target);
    const executable = path.join(installRoot, ...asset.executable.split("/"));
    const verifiedMarker = `${installRoot}.flinttrade-tool-verified.json`;
    const downloads = path.join(desktopPaths.toolsRoot, ".downloads");
    const archive = path.join(downloads, archiveName(asset.url));
    const extracting = `${installRoot}.extracting-${attempt}`;
    await dependencies.fileSystem.mkdir(downloads);
    let archiveVerified = false;
    if (await dependencies.fileSystem.exists(archive)) {
      archiveVerified = (await dependencies.fileSystem.sha256(archive)) === asset.sha256;
    }
    if (!archiveVerified) {
      const receipt = await dependencies.download.file(
        asset.url,
        archive,
        signal,
        tool === "node" ? nodeAssetPolicy : uvAssetPolicy,
      );
      assertAttempt(attempt, signal);
      archiveVerified = receipt.sha256 === asset.sha256 && (await dependencies.fileSystem.sha256(archive)) === asset.sha256;
    }
    if (!archiveVerified) throw new Error(`${tool} archive checksum verification failed.`);
    await dependencies.fileSystem.remove(extracting);
    await dependencies.fileSystem.mkdir(extracting);
    await dependencies.extractArchive({ archive, destination: extracting, kind: asset.archive, signal });
    assertAttempt(attempt, signal);
    const expectedTree = await dependencies.fileSystem.snapshotSourceTree(extracting);
    const expectedExecutable = expectedTree.entries.find((entry) => entry.path === asset.executable);
    if (
      expectedExecutable?.type !== "file" ||
      !expectedExecutable.sha256 ||
      (options.platform !== "win32" && (expectedExecutable.mode & 0o111) === 0)
    ) {
      throw new Error(`${tool} archive did not contain its expected executable as a confined executable regular file.`);
    }
    if ((await dependencies.fileSystem.exists(installRoot)) && (await dependencies.fileSystem.exists(verifiedMarker))) {
      try {
        const verified = JSON.parse(await dependencies.fileSystem.readText(verifiedMarker)) as Partial<ToolVerificationMarker>;
        const tree = await dependencies.fileSystem.snapshotSourceTree(installRoot);
        const executableEntry = tree.entries.find((entry) => entry.path === asset.executable);
        if (
          verified.schemaVersion === 2 &&
          verified.archiveSha256 === asset.sha256 &&
          verified.version === version &&
          verified.treeDigest === expectedTree.digest &&
          tree.digest === expectedTree.digest &&
          verified.executable === asset.executable &&
          executableEntry?.type === "file" &&
          executableEntry.sha256 === expectedExecutable.sha256 &&
          verified.executableSha256 === expectedExecutable.sha256 &&
          (options.platform === "win32" || (executableEntry.mode & 0o111) !== 0)
        ) {
          const canonicalRoot = await dependencies.fileSystem.realpath(installRoot);
          const canonicalExecutable = await dependencies.fileSystem.realpath(executable);
          if (isWithin(canonicalRoot, canonicalExecutable)) {
            await dependencies.fileSystem.remove(extracting);
            return { executable, tree };
          }
        }
      } catch {
        // Re-extract below. A mutable marker never makes an existing tool trusted.
      }
    }
    const extractedExecutable = path.join(extracting, ...asset.executable.split("/"));
    const canonicalRoot = await dependencies.fileSystem.realpath(extracting);
    const canonicalExecutable = await dependencies.fileSystem.realpath(extractedExecutable);
    if (!isWithin(canonicalRoot, canonicalExecutable)) throw new Error(`${tool} executable escaped its verified archive root.`);
    const marker: ToolVerificationMarker = {
      archiveSha256: asset.sha256,
      executable: asset.executable,
      executableSha256: expectedExecutable.sha256,
      schemaVersion: 2,
      treeDigest: expectedTree.digest,
      version,
    };
    await dependencies.fileSystem.remove(installRoot);
    await dependencies.fileSystem.remove(verifiedMarker);
    await dependencies.fileSystem.mkdir(path.dirname(installRoot));
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.rename(extracting, installRoot);
    await dependencies.fileSystem.writeTextAtomic(verifiedMarker, `${JSON.stringify(marker)}\n`);
    return { executable, tree: expectedTree };
  };

  const provisionTools = async (attempt: number, signal: AbortSignal): Promise<ToolPaths> => {
    const uvAsset = manifest.uv.assets[target];
    const nodeAsset = manifest.node.assets[target];
    if (!uvAsset || !nodeAsset) throw new Error(`No verified bootstrap tool manifest exists for ${target}.`);
    await publish(attempt, "installing-tools", `Provisioning uv ${manifest.uv.version}`, 28);
    const uvInstall = await installTool(attempt, signal, "uv", uvAsset, manifest.uv.version);
    const uvProbe = await requiredCommand(attempt, signal, {
      args: ["--version"],
      command: uvInstall.executable,
      timeoutMs: 15_000,
    });
    const escapedUvVersion = manifest.uv.version.replace(/\./g, "\\.");
    if (!new RegExp(`^uv ${escapedUvVersion}(?:\\s|$)`).test(uvProbe.stdout.trim())) {
      throw new Error("The verified uv executable reported an unexpected version.");
    }

    await publish(attempt, "installing-tools", `Provisioning Node ${manifest.node.version}`, 36);
    const nodeInstall = await installTool(attempt, signal, "node", nodeAsset, manifest.node.version);
    const nodeProbe = await requiredCommand(attempt, signal, {
      args: ["--version"],
      command: nodeInstall.executable,
      timeoutMs: 15_000,
    });
    if (nodeProbe.stdout.trim() !== `v${manifest.node.version}`) {
      throw new Error("The verified Node executable reported an unexpected version.");
    }
    const corepackRelative = corepackRelativePath(nodeAsset.executable, options.platform);
    const corepackEntry = nodeInstall.tree.entries.find((entry) => entry.path === corepackRelative);
    if (corepackEntry?.type !== "file") throw new Error("Verified Node distribution did not contain confined Corepack JavaScript.");
    const corepackJs = path.join(
      desktopPaths.toolsRoot,
      "node",
      manifest.node.version,
      target,
      ...corepackRelative.split("/"),
    );
    const canonicalNodeRoot = await dependencies.fileSystem.realpath(
      path.join(desktopPaths.toolsRoot, "node", manifest.node.version, target),
    );
    if (!isWithin(canonicalNodeRoot, await dependencies.fileSystem.realpath(corepackJs))) {
      throw new Error("Corepack JavaScript escaped the verified Node tool root.");
    }
    await requiredCommand(attempt, signal, {
      args: [corepackJs, "--version"],
      command: nodeInstall.executable,
      env: {
        COREPACK_DEFAULT_TO_LATEST: "0",
        COREPACK_HOME: path.join(desktopPaths.toolsRoot, "corepack"),
      },
      timeoutMs: 15_000,
    });
    return { corepackJs, node: nodeInstall.executable, uv: uvInstall.executable };
  };

  const buildCandidate = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
    tools: ToolPaths,
  ): Promise<void> => {
    const script = path.join(
      options.bootstrapResources,
      options.platform === "win32" ? "flinttrade-bootstrap.ps1" : "flinttrade-bootstrap.sh",
    );
    if (!(await dependencies.fileSystem.exists(script))) throw new Error("Packaged bootstrap build entrypoint is missing.");
    const phaseOutput = (line: string): void => {
      const match = /^FLINTTRADE_BOOTSTRAP_PHASE\t([^\t]+)\t(\d+)\t(.+)$/.exec(line);
      if (!match) return;
      const phase = match[1] as BootstrapPhase;
      if (!["syncing-python", "syncing-javascript", "building-terminal"].includes(phase)) return;
      state.publishForAttempt(attempt, { message: redactBootstrapText(match[3]!), phase, progress: Number(match[2]) });
    };
    await publish(attempt, "syncing-python", "Starting the packaged source build", 44);
    const common = [candidate, tools.uv, tools.node, tools.corepackJs, desktopPaths.toolsRoot, manifest.pnpm.version];
    const invocation: Omit<CommandInvocation, "signal"> =
      options.platform === "win32"
        ? {
            args: [
              "-NoProfile",
              "-NonInteractive",
              "-ExecutionPolicy",
              "Bypass",
              "-File",
              script,
              "-Candidate",
              common[0]!,
              "-Uv",
              common[1]!,
              "-Node",
              common[2]!,
              "-CorepackJs",
              common[3]!,
              "-ToolsRoot",
              common[4]!,
              "-PnpmVersion",
              common[5]!,
            ],
            command: "powershell.exe",
            onOutput: phaseOutput,
            timeoutMs: 90 * 60_000,
          }
        : {
            args: [script, ...common],
            command: "/bin/sh",
            onOutput: phaseOutput,
            timeoutMs: 90 * 60_000,
          };
    await requiredCommand(attempt, signal, invocation);
  };

  const verifyCandidateBinding = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
    identity: SourceIdentity,
  ): Promise<SourceIdentity> => {
    if (identity.provenance === "git") {
      const built = await readGitIdentity(attempt, signal, candidate);
      if (built.revision !== identity.revision || built.gitTree !== identity.gitTree) {
        throw new Error("Built Git commit or source tree changed before promotion.");
      }
      return built;
    }
    if (!identity.sourceTree || !(await dependencies.fileSystem.verifySourceTree(candidate, identity.sourceTree))) {
      throw new Error("An archive source input changed during the build.");
    }
    return identity;
  };

  const executeAttempt = async (attempt: number, signal: AbortSignal): Promise<BootstrapResult> => {
    const candidate = `${desktopPaths.activeSource}.candidate-${attempt}`;
    await queueLog(attempt, "preparing", "Starting first-run source bootstrap");
    assertLogging(attempt);
    await dependencies.fileSystem.mkdir(desktopPaths.sourceRoot);
    await dependencies.fileSystem.mkdir(desktopPaths.toolsRoot);
    const releaseLock = await dependencies.fileSystem.acquireOperationLock(
      path.join(desktopPaths.sourceRoot, ".flinttrade-bootstrap-operation.lock"),
    );
    try {
      const existing = await validateExistingMarker();
      if (existing) {
        await validateRepositoryShape(desktopPaths.activeSource);
        if (existing.provenance === "git") {
          const actual = await readGitIdentity(attempt, signal, desktopPaths.activeSource);
          if (actual.revision !== existing.revision || actual.gitTree !== existing.gitTree) {
            throw new Error("The active Git checkout does not match its bootstrap provenance marker.");
          }
        }
        state.complete(attempt, `Source ${existing.revision.slice(0, 12)} is ready`);
        return { ok: true, provenance: existing.provenance, revision: existing.revision };
      }
      for (let stale = 1; stale <= attempt; stale += 1) {
        await dependencies.fileSystem.remove(`${desktopPaths.activeSource}.candidate-${stale}`);
        await dependencies.fileSystem.remove(`${desktopPaths.activeSource}.candidate-${stale}.unpack`);
      }
      assertAttempt(attempt, signal);
      let identity = await acquireSource(attempt, signal, candidate);
      const tools = await provisionTools(attempt, signal);
      await buildCandidate(attempt, signal, candidate, tools);
      identity = await verifyCandidateBinding(attempt, signal, candidate, identity);
      assertAttempt(attempt, signal);
      if (await dependencies.fileSystem.exists(desktopPaths.activeSource)) {
        throw new Error("Active source appeared during first-run bootstrap; refusing to replace it.");
      }
      const canonicalCandidate = await dependencies.fileSystem.realpath(candidate);
      const canonicalParent = await dependencies.fileSystem.realpath(path.dirname(candidate));
      if (!isWithin(canonicalParent, canonicalCandidate) || path.dirname(candidate) !== path.dirname(desktopPaths.activeSource)) {
        throw new Error("Candidate and active source are not confined same-filesystem siblings.");
      }
      await options.onPromotionBoundary?.("before-marker");
      assertAttempt(attempt, signal);
      let sourceInputRecordSha256: string | undefined;
      if (identity.provenance === "github-archive" && identity.sourceTree) {
        const recordPath = path.join(candidate, SOURCE_INPUTS_RECORD);
        await dependencies.fileSystem.writeTextAtomic(recordPath, `${JSON.stringify(identity.sourceTree)}\n`);
        sourceInputRecordSha256 = await dependencies.fileSystem.sha256(recordPath);
      }
      const marker: InstalledMarker = {
        completedAt: new Date().toISOString(),
        node: manifest.node.version,
        pnpm: manifest.pnpm.version,
        provenance: identity.provenance,
        repository: repository.gitUrl,
        revision: identity.revision,
        schemaVersion: 2,
        uv: manifest.uv.version,
        ...(identity.gitTree ? { gitTree: identity.gitTree } : {}),
        ...(identity.archiveFinalOrigin ? { archiveFinalOrigin: identity.archiveFinalOrigin } : {}),
        ...(identity.archiveSha256 ? { archiveSha256: identity.archiveSha256 } : {}),
        ...(identity.sourceTree ? { sourceInputDigest: identity.sourceTree.digest } : {}),
        ...(sourceInputRecordSha256 ? { sourceInputRecordSha256 } : {}),
      };
      await dependencies.fileSystem.writeTextAtomic(markerPath(candidate, identity.provenance), `${JSON.stringify(marker)}\n`);
      await options.onPromotionBoundary?.("after-marker");
      assertAttempt(attempt, signal);
      await options.onPromotionBoundary?.("before-rename");
      assertAttempt(attempt, signal);
      await dependencies.fileSystem.promoteAbsent(candidate, desktopPaths.activeSource);
      await options.onPromotionBoundary?.("after-rename");
      assertAttempt(attempt, signal);
      state.complete(attempt, `Source ${identity.revision.slice(0, 12)} is ready`);
      await queueLog(attempt, "complete", `First-run source ${identity.revision} is ready`);
      assertLogging(attempt);
      return { ok: true, provenance: identity.provenance, revision: identity.revision };
    } finally {
      await releaseLock();
    }
  };

  const runAttempt = async (attempt: number, signal: AbortSignal): Promise<BootstrapResult> => {
    logFailures.delete(attempt);
    const heartbeat = setInterval(() => {
      const snapshot = state.getSnapshot();
      state.publishForAttempt(attempt, { message: snapshot.message });
    }, heartbeatIntervalMs);
    heartbeat.unref?.();
    try {
      return await executeAttempt(attempt, signal);
    } catch (error) {
      const cancelled = error instanceof DOMException && error.name === "AbortError";
      const message = redactBootstrapText(error instanceof Error ? error.message : String(error));
      if (!cancelled) state.fail(attempt, message);
      await queueLog(attempt, cancelled ? "cancelled" : "failed", message);
      return { cancelled, error: message, ok: false };
    } finally {
      clearInterval(heartbeat);
    }
  };

  const launch = (attempt: number): Promise<BootstrapResult> => {
    const abort = new AbortController();
    currentAbort = abort;
    const promise = runAttempt(attempt, abort.signal).catch((error) => {
      const message = redactBootstrapText(error instanceof Error ? error.message : String(error));
      state.fail(attempt, message);
      return { error: message, ok: false };
    });
    currentPromise = promise;
    const clear = () => {
      if (currentPromise === promise) {
        currentAbort = null;
        currentPromise = null;
      }
    };
    void promise.then(clear, clear);
    return promise;
  };

  const cancelAndSettle = async (): Promise<boolean> => {
    const attempt = state.getSnapshot().attempt;
    const cancelled = state.cancel(attempt);
    const running = currentPromise;
    if (running) currentAbort?.abort();
    if (running) await running;
    return cancelled;
  };

  return {
    cancel: cancelAndSettle,
    retry(): Promise<BootstrapResult> {
      if (retryPromise) return retryPromise;
      retryPromise = (async () => {
        const running = currentPromise;
        if (running) await running;
        if (!state.retry()) return { error: "Bootstrap is not retryable.", ok: false };
        return await launch(state.getSnapshot().attempt);
      })();
      const scheduled = retryPromise;
      const clear = () => {
        if (retryPromise === scheduled) retryPromise = null;
      };
      void scheduled.then(clear, clear);
      return scheduled;
    },
    async shutdown(timeoutMs = 10_000): Promise<void> {
      const settlement = cancelAndSettle();
      let timeout: NodeJS.Timeout | undefined;
      try {
        await Promise.race([
          settlement,
          new Promise<never>((_resolve, reject) => {
            timeout = setTimeout(() => reject(new Error("Bootstrap process containment did not settle before quit.")), timeoutMs);
          }),
        ]);
      } finally {
        if (timeout) clearTimeout(timeout);
      }
    },
    start(): Promise<BootstrapResult> {
      if (state.getSnapshot().status === "running" && currentPromise) return currentPromise;
      const attempt = state.begin("Preparing source bootstrap", "preparing");
      return launch(attempt);
    },
  };
}
