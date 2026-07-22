// Bootstrap orchestration shape adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { randomUUID } from "node:crypto";
import path from "node:path";

import type { DesktopPaths } from "./paths";
import { inspectHardenedGitCheckout } from "./git-source-inspection";
import {
  createSourceOperationCoordinator,
  SourceOperationLeaseRetentionError,
  type SourceOperationCoordinator,
  type SourceOperationLeaseProof,
} from "./source-operation";
import type { BootstrapPhase, createBootstrapState } from "./state";

export const BOOTSTRAP_MARKER = ".flinttrade-bootstrap-complete.json";
export const SOURCE_INPUTS_RECORD = ".flinttrade-source-inputs.json";
const REPOSITORY_URL = "https://github.com/navaneeshnagarajan/FlintTrade.git";
const MAIN_COMMIT_URL = "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/commits/main";
const ARCHIVE_BASE_URL = "https://codeload.github.com/navaneeshnagarajan/FlintTrade/zip";
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const TOOL_VERSION_PATTERN = /^(?!0\.0\.0(?:$|-))(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/;
const PACKAGE_MANAGER_PATTERN = /^pnpm@((?!0\.0\.0(?:$|-))(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?)(?:\+sha512\.[0-9A-Za-z_-]+)?$/;
const MAX_FRONTEND_OUTPUT_ENTRIES = 20_000;
const MAX_FRONTEND_OUTPUT_MANIFEST_BYTES = 32 * 1024 * 1024;
const ARCHIVE_GENERATED_ROOTS = Object.freeze([
  ".venv",
  "node_modules",
  "packages/apps/desktop/node_modules",
  "packages/apps/site/node_modules",
  "packages/apps/terminal/node_modules",
  "packages/apps/terminal/dist",
  "packages/core/design-system/node_modules",
]);

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
  /** Bind a Windows executable to this lowercase SHA-256 through CreateProcess. */
  expectedExecutableSha256?: string;
  /** Set false when `env` is the complete managed child environment. */
  inheritEnvironment?: boolean;
  onOutput?: (line: string, stream: "stdout" | "stderr") => void;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface CommandResult {
  /**
   * Whether the platform runner proved its supported containment domain empty.
   * POSIX proof covers the original process group and escaped descendants that
   * retain the inherited operation marker; it cannot attest a new-session
   * descendant that deliberately replaces its environment and discards it.
   */
  contained: boolean;
  exitCode: number;
  stderr: string;
  /** Whether the retained stderr is only a bounded tail of the full stream. */
  stderrTruncated: boolean;
  stdout: string;
  /** Whether the retained stdout is only a bounded tail of the full stream. */
  stdoutTruncated: boolean;
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
  command: {
    operationLeaseTarget?: string;
    /** Re-prove and durably clear only this process's recorded command-containment scope. */
    reconcileOperationContainment(): Promise<void>;
    run(invocation: CommandInvocation): Promise<CommandResult>;
    windowsPowerShell?: string;
  };
  download: {
    file(url: string, destination: string, signal: AbortSignal, policy: DownloadPolicy): Promise<DownloadReceipt>;
    text(url: string, signal: AbortSignal, policy: DownloadPolicy): Promise<TextDownloadReceipt>;
  };
  extractArchive(input: {
    archive: string;
    destination: string;
    destinationIdentity?: FileSystemIdentity;
    expectedSha256: string;
    expectedRoot?: string;
    kind: "tar.gz" | "zip";
    signal: AbortSignal;
    stripExpectedRoot?: boolean;
  }): Promise<string[]>;
  fileSystem: {
    acquireOperationLock(request: OperationLeaseRequest): Promise<() => Promise<void>>;
    appendText(target: string, content: string): Promise<void>;
    assertDirectoryIdentity(target: string, identity: FileSystemIdentity, requireEmpty?: boolean): Promise<void>;
    directoryIdentity(target: string): Promise<FileSystemIdentity>;
    directoryMetadata(target: string): Promise<FileSystemDirectoryMetadata>;
    ensureDurableDirectory(target: string, knownDurableAncestor: string): Promise<void>;
    exists(target: string): Promise<boolean>;
    existsNoFollow(target: string): Promise<boolean>;
    fileIdentity(target: string): Promise<FileSystemFileIdentity>;
    listNames(target: string): Promise<string[]>;
    mkdir(target: string): Promise<unknown>;
    preparePrivateTree(root: string, directories: readonly string[], files: readonly string[]): Promise<void>;
    promoteAbsent(source: string, destination: string, identity: FileSystemIdentity): Promise<void>;
    readText(target: string): Promise<string>;
    readTextNoFollow(target: string): Promise<string>;
    realpath(target: string): Promise<string>;
    remove(target: string): Promise<void>;
    reserveTemporaryDirectory(parent: string, prefix: string): Promise<TemporaryDirectoryReservation>;
    rename(source: string, destination: string): Promise<void>;
    sha256(target: string): Promise<string>;
    snapshotSourceTree(root: string): Promise<SourceTreeIdentity>;
    verifySourceTree(
      root: string,
      identity: SourceTreeIdentity,
      allowedGeneratedRoots?: readonly string[],
      allowedGeneratedFiles?: readonly string[],
    ): Promise<boolean>;
    writeTextAbsent(target: string, content: string): Promise<void>;
    writeTextAtomic(target: string, content: string): Promise<void>;
  };
}

export interface BootstrapOptions {
  arch: string;
  bootIdentity: string;
  bootstrapResources: string;
  dependencies: BootstrapDependencies;
  expectedRevision?: string;
  heartbeatIntervalMs?: number;
  manifest: BootstrapToolManifest;
  onPromotionBoundary?: (boundary: BootstrapBoundary) => Promise<void> | void;
  heldOperationLease?: SourceOperationLeaseProof;
  paths: DesktopPaths;
  platform: NodeJS.Platform;
  singletonAuthorised: boolean;
  operationCoordinator?: SourceOperationCoordinator;
  repository?: {
    archiveBaseUrl: string;
    branch: string;
    commitMetadataUrl: string;
    gitUrl: string;
  };
  state: ReturnType<typeof createBootstrapState>;
}

export interface FileSystemIdentity {
  dev: number;
  ino: number;
  /** Platform-native identity captured while an exclusive reservation is still proved. */
  nativeIdentity?: string;
}

export interface TemporaryDirectoryReservation {
  identity: FileSystemIdentity;
  path: string;
}

/** Mutation-sensitive no-follow identity for security-critical directories. */
export interface FileSystemDirectoryMetadata extends FileSystemIdentity {
  ctimeMs: number;
  mtimeMs: number;
  size: number;
}

export interface FileSystemFileIdentity extends FileSystemIdentity {
  ctimeMs: number;
  mtimeMs: number;
  size: number;
}

export interface OperationLeaseRequest {
  bootIdentity: string;
  ownerPid: number;
  singletonAuthorised: boolean;
  target: string;
}

export interface BootstrapResult {
  cancelled?: boolean;
  containmentFailed?: true;
  error?: string;
  ok: boolean;
  provenance?: BootstrapProvenance;
  revision?: string;
  sourceIdentity?: FileSystemIdentity;
}

interface SourceIdentity {
  archiveFinalOrigin?: string;
  archiveSha256?: string;
  gitTree?: string;
  frontendOutput?: FrontendOutputIdentity;
  provenance: BootstrapProvenance;
  revision: string;
  sourceTree?: SourceTreeIdentity;
}

interface AcquiredSource {
  candidate: string;
  candidateIdentity: FileSystemIdentity;
  identity: SourceIdentity;
}

interface FrontendOutputIdentity {
  digest: string;
  entryCount: number;
  indexSha256: string;
}

interface InstalledMarkerV2 {
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

interface InstalledMarkerV3 extends Omit<InstalledMarkerV2, "schemaVersion"> {
  frontendOutputDigest: string;
  frontendOutputEntryCount: number;
  frontendOutputIndexSha256: string;
  packageManager: string;
  schemaVersion: 3;
}

type InstalledMarker = InstalledMarkerV2 | InstalledMarkerV3;

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
    .replace(/\b(?:Authorization\s*[:=]\s*)?(?:Basic|Bearer)\s+[^\s,;}"']+/gi, "Authorization: <redacted>")
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
      /(^|[^a-z0-9_'"-])((?:["']?)[a-z0-9_-]*(?:key|token|secret|password|authorization)(?:["']?)\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)/gim,
      "$1$2<redacted>",
    );
}

function replacePrivatePath(
  value: string,
  target: string,
  replacement: string,
  platform: NodeJS.Platform,
): string {
  const variants = [...new Set([
    target,
    target.replaceAll("\\", "/"),
    target.replaceAll("/", "\\"),
  ])].sort((left, right) => right.length - left.length);
  return variants.reduce((current, variant) => {
    if (!variant) return current;
    if (platform !== "win32") return current.split(variant).join(replacement);
    const needle = variant.toLowerCase();
    let cursor = 0;
    let redacted = "";
    const lowered = current.toLowerCase();
    for (;;) {
      const index = lowered.indexOf(needle, cursor);
      if (index < 0) return redacted + current.slice(cursor);
      redacted += current.slice(cursor, index) + replacement;
      cursor = index + variant.length;
    }
  }, value);
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

function requireToolVersion(value: unknown, label: string): string {
  if (typeof value !== "string" || !TOOL_VERSION_PATTERN.test(value)) {
    throw new Error(`${label} is not a valid pinned tool version.`);
  }
  return value;
}

function requirePackageManager(value: unknown, pnpmVersion: string): string {
  if (typeof value !== "string") throw new Error("The repository package-manager pin is invalid.");
  const match = PACKAGE_MANAGER_PATTERN.exec(value);
  if (!match || match[1] !== pnpmVersion) {
    throw new Error("The repository package-manager pin does not match its recorded pnpm build version.");
  }
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
  const operationLeaseTarget = path.join(desktopPaths.sourceRoot, ".flinttrade-bootstrap-operation.lock");
  if (dependencies.command.operationLeaseTarget !== operationLeaseTarget) {
    throw new Error("Bootstrap command containment must be bound to the exact source operation lease.");
  }
  if (options.heldOperationLease && options.heldOperationLease.target !== operationLeaseTarget) {
    throw new Error("The held source-operation lease does not match bootstrap command containment.");
  }
  const repository =
    options.repository ??
    Object.freeze({
      archiveBaseUrl: ARCHIVE_BASE_URL,
      branch: "main",
      commitMetadataUrl: MAIN_COMMIT_URL,
      gitUrl: REPOSITORY_URL,
    });
  const expectedRevision = options.expectedRevision ? requireCommit(options.expectedRevision) : null;
  const operationCoordinator = options.operationCoordinator ?? createSourceOperationCoordinator();
  let currentAbort: AbortController | null = null;
  let currentPromise: Promise<BootstrapResult> | null = null;
  let retryPromise: Promise<BootstrapResult> | null = null;
  let shutdownSettlement: Promise<void> | null = null;
  let shuttingDown = false;
  let containmentFailure: Error | null = null;
  let logQueue: Promise<void> = Promise.resolve();
  let pendingLeaseRelease: (() => Promise<void>) | null = null;
  let pendingLeaseSettlement: Promise<void> | null = null;
  const logFailures = new Map<number, string>();
  const logPath = path.join(desktopPaths.logs, "desktop-bootstrap.jsonl");
  const managedUserRoot = path.join(desktopPaths.toolsRoot, "bootstrap-user");
  const managedHome = path.join(managedUserRoot, "home");
  const privatePathReplacements = [
    [desktopPaths.activeSource, "<active-source>"],
    [desktopPaths.sourceRoot, "<source-root>"],
    [desktopPaths.toolsRoot, "<tools-root>"],
    [desktopPaths.workspace, "<workspace>"],
    [options.bootstrapResources, "<bootstrap-resources>"],
  ] as const;
  const sanitise = (value: string): string => privatePathReplacements.reduce(
    (current, [targetPath, replacement]) =>
      replacePrivatePath(current, path.resolve(targetPath), replacement, options.platform),
    redactBootstrapText(value),
  );
  const managedChildEnvironment: NodeJS.ProcessEnv = Object.freeze({
    GIT_CONFIG_GLOBAL: path.join(managedUserRoot, "gitconfig"),
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_TERMINAL_PROMPT: "0",
    HOME: managedHome,
    NPM_CONFIG_CACHE: path.join(managedUserRoot, "npm-cache"),
    NPM_CONFIG_USERCONFIG: path.join(managedUserRoot, "npmrc"),
    PNPM_HOME: path.join(managedUserRoot, "pnpm-home"),
    USERPROFILE: managedHome,
    UV_CACHE_DIR: path.join(managedUserRoot, "uv-cache"),
    UV_CONFIG_FILE: path.join(managedUserRoot, "uv.toml"),
    XDG_CACHE_HOME: path.join(managedUserRoot, "xdg-cache"),
    XDG_CONFIG_HOME: path.join(managedUserRoot, "xdg-config"),
    XDG_DATA_HOME: path.join(managedUserRoot, "xdg-data"),
  });

  const uniqueDownloadPath = (directory: string, name: string, attempt: number): string =>
    path.join(directory, `${name}.bootstrap-${attempt}-${randomUUID()}`);

  const prepareManagedUserEnvironment = async (): Promise<void> => {
    await dependencies.fileSystem.preparePrivateTree(
      managedUserRoot,
      ["home", "npm-cache", "pnpm-home", "uv-cache", "xdg-cache", "xdg-config", "xdg-data"],
      ["gitconfig", "npmrc", "uv.toml"],
    );
  };

  const queueLog = async (attempt: number, phase: BootstrapPhase, message: string): Promise<void> => {
    const event = { attempt, at: new Date().toISOString(), message: sanitise(message), phase };
    const operation = logQueue.then(async () => {
      await dependencies.fileSystem.ensureDurableDirectory(desktopPaths.logs, path.dirname(desktopPaths.workspace));
      await dependencies.fileSystem.appendText(logPath, `${JSON.stringify(event)}\n`);
    });
    logQueue = operation.catch((error) => {
      const detail = sanitise(error instanceof Error ? error.message : String(error));
      if (!logFailures.has(attempt)) logFailures.set(attempt, `Durable bootstrap log failed: ${detail}`);
    });
    await logQueue;
  };

  const assertLogging = (attempt: number): void => {
    const failure = logFailures.get(attempt);
    if (failure) throw new Error(failure);
  };

  const settlePendingLease = (): Promise<void> => {
    const release = pendingLeaseRelease;
    if (!release) return Promise.resolve();
    if (pendingLeaseSettlement) return pendingLeaseSettlement;
    let settlement: Promise<void>;
    settlement = Promise.resolve()
      .then(release)
      .then(() => {
        if (pendingLeaseRelease === release) pendingLeaseRelease = null;
      })
      .finally(() => {
        if (pendingLeaseSettlement === settlement) pendingLeaseSettlement = null;
      });
    pendingLeaseSettlement = settlement;
    return settlement;
  };

  const publish = async (
    attempt: number,
    phase: BootstrapPhase,
    message: string,
    progress: number | null,
  ): Promise<void> => {
    state.publishForAttempt(attempt, { message: sanitise(message), phase, progress });
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
    let result: CommandResult;
    try {
      result = await dependencies.command.run({
        ...invocation,
        env: { ...managedChildEnvironment, ...invocation.env },
        onOutput: (line, stream) => {
          void queueLog(attempt, state.getSnapshot().phase, `${stream}: ${line}`);
          invocation.onOutput?.(line, stream);
        },
        signal,
      });
    } catch (error) {
      containmentFailure ??= error instanceof SourceOperationLeaseRetentionError
        ? error
        : new SourceOperationLeaseRetentionError(
            "Bootstrap command runner rejected without proving process containment; restart is blocked.",
            { cause: error },
          );
      throw containmentFailure;
    }
    if (!result.contained) {
      containmentFailure ??= new SourceOperationLeaseRetentionError(
        "Bootstrap command process containment could not be proven; restart is blocked.",
      );
    }
    await logQueue;
    if (containmentFailure) throw containmentFailure;
    assertAttempt(attempt, signal);
    return result;
  };

  const requiredCommand = async (
    attempt: number,
    signal: AbortSignal,
    invocation: Omit<CommandInvocation, "signal">,
  ): Promise<CommandResult> => {
    const result = await runCommand(attempt, signal, invocation);
    if (result.exitCode !== 0) throw new Error(sanitise(result.stderr.trim() || "A required command failed."));
    return result;
  };

  const validateRepositoryShape = async (
    root: string,
    expectedPackageManager = manifest.pnpm.packageManager,
  ): Promise<void> => {
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
    if (packageMetadata.name !== "flinttrade-monorepo" || packageMetadata.packageManager !== expectedPackageManager) {
      throw new Error("Source provenance validation rejected the repository package identity.");
    }
  };

  const snapshotFrontendOutput = async (root: string): Promise<FrontendOutputIdentity> => {
    const output = await dependencies.fileSystem.snapshotSourceTree(
      path.join(root, "packages", "apps", "terminal", "dist"),
    );
    const manifestBytes = Buffer.byteLength(JSON.stringify(output.entries));
    if (
      output.entries.length === 0 ||
      output.entries.length > MAX_FRONTEND_OUTPUT_ENTRIES ||
      manifestBytes > MAX_FRONTEND_OUTPUT_MANIFEST_BYTES
    ) {
      throw new Error("The built terminal output manifest is empty or exceeds its bounded acceptance limits.");
    }
    const index = output.entries.find((entry) => entry.path === "index.html");
    if (index?.type !== "file" || !index.sha256) {
      throw new Error("The built terminal output is missing a no-follow regular index.html.");
    }
    return {
      digest: requireDigest(output.digest, "Terminal output digest"),
      entryCount: output.entries.length,
      indexSha256: requireDigest(index.sha256, "Terminal index digest"),
    };
  };

  const readGitIdentity = async (
    attempt: number,
    signal: AbortSignal,
    root: string,
    expected?: { gitTree?: string; revision: string },
  ): Promise<SourceIdentity> => {
    const identity = await inspectHardenedGitCheckout({
      bootstrapResources: options.bootstrapResources,
      dependencies: {
        command: { run: (invocation) => runCommand(attempt, signal, invocation) },
        fileSystem: dependencies.fileSystem,
      },
      expected: {
        branch: repository.branch,
        origin: repository.gitUrl,
        ...(expected ? { revision: expected.revision } : {}),
        ...(expected?.gitTree ? { tree: expected.gitTree } : {}),
      },
      platform: options.platform,
      root,
      signal,
    });
    return { gitTree: identity.tree, provenance: "git", revision: identity.revision };
  };

  const validateExistingMarker = async (): Promise<SourceIdentity | null> => {
    if (!(await dependencies.fileSystem.exists(desktopPaths.activeSource))) return null;
    await dependencies.fileSystem.directoryIdentity(desktopPaths.activeSource);
    const canonicalSourceRoot = await dependencies.fileSystem.realpath(desktopPaths.sourceRoot);
    const canonicalActiveSource = await dependencies.fileSystem.realpath(desktopPaths.activeSource);
    if (!isWithin(canonicalSourceRoot, canonicalActiveSource) || path.dirname(desktopPaths.activeSource) !== desktopPaths.sourceRoot) {
      throw new Error("The active source root is aliased or escaped from its managed source directory.");
    }
    for (const provenance of ["git", "github-archive"] as const) {
      const candidate = markerPath(desktopPaths.activeSource, provenance);
      if (!(await dependencies.fileSystem.exists(candidate))) continue;
      const parsed = JSON.parse(await dependencies.fileSystem.readTextNoFollow(candidate)) as Partial<InstalledMarker>;
      if (
        (parsed.schemaVersion !== 2 && parsed.schemaVersion !== 3) ||
        parsed.provenance !== provenance ||
        parsed.repository !== repository.gitUrl ||
        typeof parsed.completedAt !== "string" ||
        Number.isNaN(Date.parse(parsed.completedAt)) ||
        new Date(parsed.completedAt).toISOString() !== parsed.completedAt ||
        !parsed.revision
      ) {
        break;
      }
      requireToolVersion(parsed.node, "The recorded Node version");
      const recordedPnpm = requireToolVersion(parsed.pnpm, "The recorded pnpm version");
      requireToolVersion(parsed.uv, "The recorded uv version");
      const packageMetadata = JSON.parse(
        await dependencies.fileSystem.readTextNoFollow(path.join(desktopPaths.activeSource, "package.json")),
      ) as { packageManager?: unknown };
      const packageManager = requirePackageManager(
        parsed.schemaVersion === 3 ? parsed.packageManager : packageMetadata.packageManager,
        recordedPnpm,
      );
      if (packageMetadata.packageManager !== packageManager) {
        throw new Error("The active source package-manager pin changed after it was built.");
      }
      await validateRepositoryShape(desktopPaths.activeSource, packageManager);
      let frontendOutput: FrontendOutputIdentity | undefined;
      if (parsed.schemaVersion === 3) {
        const output = await snapshotFrontendOutput(desktopPaths.activeSource);
        if (
          output.digest !== requireDigest(parsed.frontendOutputDigest, "Terminal output digest") ||
          output.indexSha256 !== requireDigest(parsed.frontendOutputIndexSha256, "Terminal index digest") ||
          parsed.frontendOutputEntryCount !== output.entryCount
        ) {
          throw new Error("The active terminal output does not match its bootstrap completion marker.");
        }
        frontendOutput = output;
      }
      const revision = requireCommit(parsed.revision);
      if (provenance === "git") {
        return {
          ...(frontendOutput ? { frontendOutput } : {}),
          gitTree: requireCommit(parsed.gitTree ?? ""),
          provenance,
          revision,
        };
      }
      const archiveSha256 = requireDigest(parsed.archiveSha256, "Archive digest");
      const sourceInputDigest = requireDigest(parsed.sourceInputDigest, "Source input digest");
      const sourceInputRecordSha256 = requireDigest(parsed.sourceInputRecordSha256, "Source input record digest");
      if (parsed.archiveFinalOrigin !== new URL(repository.archiveBaseUrl).origin) {
        throw new Error("Archive marker final origin does not match the configured source archive origin.");
      }
      const recordPath = path.join(desktopPaths.activeSource, SOURCE_INPUTS_RECORD);
      if (
        !(await dependencies.fileSystem.exists(recordPath)) ||
        (await dependencies.fileSystem.sha256(recordPath)) !== sourceInputRecordSha256
      ) {
        throw new Error("Archive source input record does not match its completion marker.");
      }
      const sourceTree = JSON.parse(await dependencies.fileSystem.readTextNoFollow(recordPath)) as SourceTreeIdentity;
      if (
        sourceTree.digest !== sourceInputDigest ||
        !(await dependencies.fileSystem.verifySourceTree(
          desktopPaths.activeSource,
          sourceTree,
          ARCHIVE_GENERATED_ROOTS,
          [BOOTSTRAP_MARKER, SOURCE_INPUTS_RECORD],
        ))
      ) {
        throw new Error("Archive-backed source inputs changed after bootstrap.");
      }
      return {
        archiveFinalOrigin: parsed.archiveFinalOrigin,
        archiveSha256,
        ...(frontendOutput ? { frontendOutput } : {}),
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
    candidate: TemporaryDirectoryReservation,
  ): Promise<SourceIdentity> => {
    await publish(
      attempt,
      "cloning-source",
      expectedRevision ? "Acquiring the exact source archive" : "Resolving the public main archive",
      12,
    );
    let revision = expectedRevision;
    if (!revision) {
      const metadataReceipt = await dependencies.download.text(
        repository.commitMetadataUrl,
        signal,
        metadataPolicy,
      );
      const metadata = JSON.parse(metadataReceipt.content) as { sha?: unknown };
      revision = requireCommit(typeof metadata.sha === "string" ? metadata.sha : "");
    }
    assertAttempt(attempt, signal);
    const downloadDirectory = path.join(desktopPaths.sourceRoot, ".downloads");
    const archive = uniqueDownloadPath(
      downloadDirectory,
      `FlintTrade-${revision}.zip`,
      attempt,
    );
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
    const archiveRoot = `FlintTrade-${revision}`;
    const entries = await dependencies.extractArchive({
      archive,
      destination: candidate.path,
      destinationIdentity: candidate.identity,
      expectedRoot: archiveRoot,
      expectedSha256: receipt.sha256,
      kind: "zip",
      signal,
      stripExpectedRoot: true,
    });
    if (entries.length === 0 || entries.some((entry) => entry !== archiveRoot && !entry.startsWith(`${archiveRoot}/`))) {
      throw new Error("GitHub source archive failed path and provenance validation.");
    }
    await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity);
    await validateRepositoryShape(candidate.path);
    const sourceTree = await dependencies.fileSystem.snapshotSourceTree(candidate.path);
    assertAttempt(attempt, signal);
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
  ): Promise<AcquiredSource> => {
    const acquireFreshArchive = async (): Promise<AcquiredSource> => {
      const candidate = await dependencies.fileSystem.reserveTemporaryDirectory(
        desktopPaths.sourceRoot,
        `${path.basename(desktopPaths.activeSource)}.candidate-${attempt}`,
      );
      await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity, true);
      return {
        candidate: candidate.path,
        candidateIdentity: candidate.identity,
        identity: await acquireArchive(attempt, signal, candidate),
      };
    };
    await publish(attempt, "checking-source", "Checking system Git", 5);
    const gitProbe = await runCommand(attempt, signal, {
      args: ["--version"],
      command: "git",
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 15_000,
    });
    if (gitProbe.exitCode !== 0) return acquireFreshArchive();

    await publish(attempt, "cloning-source", "Cloning the public source checkout", 12);
    const candidate = await dependencies.fileSystem.reserveTemporaryDirectory(
      desktopPaths.sourceRoot,
      `${path.basename(desktopPaths.activeSource)}.candidate-${attempt}`,
    );
    await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity, true);
    const clone = await runCommand(attempt, signal, {
      args: ["clone", "--branch", repository.branch, "--single-branch", "--no-tags", repository.gitUrl, candidate.path],
      command: "git",
      env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
      timeoutMs: 20 * 60_000,
    });
    if (clone.exitCode !== 0) {
      return acquireFreshArchive();
    }
    await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity);
    if (expectedRevision) {
      await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity);
      const checkout = await runCommand(attempt, signal, {
        args: ["checkout", "--detach", expectedRevision],
        command: "git",
        cwd: candidate.path,
        env: { GIT_CONFIG_NOSYSTEM: "1", GIT_TERMINAL_PROMPT: "0" },
        timeoutMs: 5 * 60_000,
      });
      if (checkout.exitCode !== 0) {
        return acquireFreshArchive();
      }
      await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity);
    }
    await validateRepositoryShape(candidate.path);
    const identity = await readGitIdentity(
      attempt,
      signal,
      candidate.path,
      expectedRevision ? { revision: expectedRevision } : undefined,
    );
    if (expectedRevision && identity.revision !== expectedRevision) {
      throw new Error("Cloned source does not match the requested update revision.");
    }
    await dependencies.fileSystem.assertDirectoryIdentity(candidate.path, candidate.identity);
    return { candidate: candidate.path, candidateIdentity: candidate.identity, identity };
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
    const archive = uniqueDownloadPath(downloads, archiveName(asset.url), attempt);
    const extracting = await dependencies.fileSystem.reserveTemporaryDirectory(
      path.dirname(installRoot),
      `${path.basename(installRoot)}.extracting-${attempt}`,
    );
    await dependencies.fileSystem.mkdir(downloads);
    await dependencies.fileSystem.assertDirectoryIdentity(extracting.path, extracting.identity, true);
    const receipt = await dependencies.download.file(
      asset.url,
      archive,
      signal,
      tool === "node" ? nodeAssetPolicy : uvAssetPolicy,
    );
    assertAttempt(attempt, signal);
    const archiveVerified =
      receipt.sha256 === asset.sha256 && (await dependencies.fileSystem.sha256(archive)) === asset.sha256;
    if (!archiveVerified) throw new Error(`${tool} archive checksum verification failed.`);
    await dependencies.extractArchive({
      archive,
      destination: extracting.path,
      destinationIdentity: extracting.identity,
      expectedSha256: asset.sha256,
      kind: asset.archive,
      signal,
    });
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.assertDirectoryIdentity(extracting.path, extracting.identity);
    const expectedTree = await dependencies.fileSystem.snapshotSourceTree(extracting.path);
    const expectedExecutable = expectedTree.entries.find((entry) => entry.path === asset.executable);
    if (
      expectedExecutable?.type !== "file" ||
      !expectedExecutable.sha256 ||
      (options.platform !== "win32" && (expectedExecutable.mode & 0o111) === 0)
    ) {
      throw new Error(`${tool} archive did not contain its expected executable as a confined executable regular file.`);
    }
    const installRootExists = await dependencies.fileSystem.existsNoFollow(installRoot);
    const verifiedMarkerExists = await dependencies.fileSystem.existsNoFollow(verifiedMarker);
    if (installRootExists || verifiedMarkerExists) {
      try {
        if (!installRootExists || !verifiedMarkerExists) {
          throw new Error("The managed tool root and verification marker are incomplete.");
        }
        const verified = JSON.parse(await dependencies.fileSystem.readTextNoFollow(verifiedMarker)) as Partial<ToolVerificationMarker>;
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
            return { executable, tree };
          }
        }
      } catch {
        // Fall through to the preserving failure below.
      }
      throw new Error(`Existing ${tool} tool state failed exact verification and was preserved.`);
    }
    const extractedExecutable = path.join(extracting.path, ...asset.executable.split("/"));
    const canonicalRoot = await dependencies.fileSystem.realpath(extracting.path);
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
    await dependencies.fileSystem.mkdir(path.dirname(installRoot));
    assertAttempt(attempt, signal);
    await dependencies.fileSystem.assertDirectoryIdentity(extracting.path, extracting.identity);
    await dependencies.fileSystem.promoteAbsent(extracting.path, installRoot, extracting.identity);
    await dependencies.fileSystem.writeTextAbsent(verifiedMarker, `${JSON.stringify(marker)}\n`);
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
      state.publishForAttempt(attempt, { message: sanitise(match[3]!), phase, progress: Number(match[2]) });
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
            command:
              dependencies.command.windowsPowerShell ??
              (() => {
                throw new Error("Trusted absolute Windows PowerShell is unavailable.");
              })(),
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

  const verifyRelocatableVirtualEnvironment = async (
    attempt: number,
    signal: AbortSignal,
    sourceRoot: string,
  ): Promise<void> => {
    const environmentRoot = path.join(sourceRoot, ".venv");
    const configurationPath = path.join(environmentRoot, "pyvenv.cfg");
    const entryPoint = path.join(
      environmentRoot,
      options.platform === "win32" ? "Scripts" : "bin",
      options.platform === "win32" ? "pytest.exe" : "pytest",
    );
    if (!(await dependencies.fileSystem.exists(configurationPath))) {
      throw new Error("The built virtual environment is missing pyvenv.cfg.");
    }
    if (!(await dependencies.fileSystem.exists(entryPoint))) {
      throw new Error("The built virtual environment is missing its pytest entry point.");
    }
    await dependencies.fileSystem.directoryIdentity(environmentRoot);
    const canonicalEnvironment = await dependencies.fileSystem.realpath(environmentRoot);
    const canonicalConfiguration = await dependencies.fileSystem.realpath(configurationPath);
    const canonicalEntryPoint = await dependencies.fileSystem.realpath(entryPoint);
    if (
      !isWithin(canonicalEnvironment, canonicalConfiguration) ||
      !isWithin(canonicalEnvironment, canonicalEntryPoint)
    ) {
      throw new Error("The built virtual environment contains an aliased relocation boundary.");
    }
    const relocatableSettings = (await dependencies.fileSystem.readText(configurationPath))
      .split(/\r?\n/)
      .flatMap((line) => {
        const match = /^\s*relocatable\s*=\s*(\S+)\s*$/.exec(line);
        return match ? [match[1]] : [];
      });
    if (relocatableSettings.length !== 1 || relocatableSettings[0] !== "true") {
      throw new Error("The built virtual environment is not explicitly relocatable.");
    }
    const probe = await requiredCommand(attempt, signal, {
      args: ["--version"],
      command: entryPoint,
      timeoutMs: 30_000,
    });
    if (!/^pytest\s+\d+(?:\.|$)/.test(probe.stdout.trim())) {
      throw new Error("The relocatable virtual-environment entry point returned an unexpected version.");
    }
  };

  const verifyCandidateBinding = async (
    attempt: number,
    signal: AbortSignal,
    candidate: string,
    identity: SourceIdentity,
    allowedGeneratedFiles: readonly string[] = [],
  ): Promise<SourceIdentity> => {
    if (identity.provenance === "git") {
      const built = await readGitIdentity(attempt, signal, candidate, {
        ...(identity.gitTree ? { gitTree: identity.gitTree } : {}),
        revision: identity.revision,
      });
      if (built.revision !== identity.revision || built.gitTree !== identity.gitTree) {
        throw new Error("Built Git commit or source tree changed before promotion.");
      }
      return built;
    }
    if (
      !identity.sourceTree ||
      !(await dependencies.fileSystem.verifySourceTree(
        candidate,
        identity.sourceTree,
        ARCHIVE_GENERATED_ROOTS,
        allowedGeneratedFiles,
      ))
    ) {
      throw new Error("An archive source input changed during the build.");
    }
    return identity;
  };

  const executeAttempt = async (attempt: number, signal: AbortSignal): Promise<BootstrapResult> => {
    await options.heldOperationLease?.assertHeld();
    assertAttempt(attempt, signal);
    await queueLog(attempt, "preparing", "Starting first-run source bootstrap");
    assertLogging(attempt);
    await dependencies.fileSystem.mkdir(desktopPaths.sourceRoot);
    await dependencies.fileSystem.mkdir(desktopPaths.toolsRoot);
    await dependencies.fileSystem.preparePrivateTree(desktopPaths.sourceRoot, [".downloads"], []);
    await dependencies.fileSystem.preparePrivateTree(
      desktopPaths.toolsRoot,
      [
        ".downloads",
        "corepack",
        "python",
        "uv-cache",
        `node/${manifest.node.version}`,
        `uv/${manifest.uv.version}`,
      ],
      [],
    );
    await prepareManagedUserEnvironment();
    if (!options.heldOperationLease) {
      await settlePendingLease();
      const releaseLock = await dependencies.fileSystem.acquireOperationLock({
        bootIdentity: options.bootIdentity,
        ownerPid: process.pid,
        singletonAuthorised: options.singletonAuthorised,
        target: operationLeaseTarget,
      });
      pendingLeaseRelease = releaseLock;
    }
    try {
      const existing = await validateExistingMarker();
      if (existing) {
        if (existing.provenance === "git") {
          const actual = await readGitIdentity(attempt, signal, desktopPaths.activeSource, {
            ...(existing.gitTree ? { gitTree: existing.gitTree } : {}),
            revision: existing.revision,
          });
          if (actual.revision !== existing.revision || actual.gitTree !== existing.gitTree) {
            throw new Error("The active Git checkout does not match its bootstrap provenance marker.");
          }
        }
        await verifyRelocatableVirtualEnvironment(attempt, signal, desktopPaths.activeSource);
        if (existing.frontendOutput) {
          const finalOutput = await snapshotFrontendOutput(desktopPaths.activeSource);
          if (
            finalOutput.digest !== existing.frontendOutput.digest ||
            finalOutput.entryCount !== existing.frontendOutput.entryCount ||
            finalOutput.indexSha256 !== existing.frontendOutput.indexSha256
          ) {
            throw new Error("The active terminal output changed during bootstrap validation.");
          }
        }
        return {
          ok: true,
          provenance: existing.provenance,
          revision: existing.revision,
          sourceIdentity: await dependencies.fileSystem.directoryIdentity(desktopPaths.activeSource),
        };
      }
      assertAttempt(attempt, signal);
      const acquired = await acquireSource(attempt, signal);
      const candidate = acquired.candidate;
      let identity = acquired.identity;
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      const tools = await provisionTools(attempt, signal);
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      await buildCandidate(attempt, signal, candidate, tools);
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      await verifyRelocatableVirtualEnvironment(attempt, signal, candidate);
      identity = await verifyCandidateBinding(attempt, signal, candidate, identity);
      assertAttempt(attempt, signal);
      if (await dependencies.fileSystem.existsNoFollow(desktopPaths.activeSource)) {
        throw new Error("Active source appeared during first-run bootstrap; refusing to replace it.");
      }
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      const canonicalCandidate = await dependencies.fileSystem.realpath(candidate);
      const canonicalParent = await dependencies.fileSystem.realpath(path.dirname(candidate));
      if (!isWithin(canonicalParent, canonicalCandidate) || path.dirname(candidate) !== path.dirname(desktopPaths.activeSource)) {
        throw new Error("Candidate and active source are not confined same-filesystem siblings.");
      }
      await options.onPromotionBoundary?.("before-marker");
      assertAttempt(attempt, signal);
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      let sourceInputRecordSha256: string | undefined;
      if (identity.provenance === "github-archive" && identity.sourceTree) {
        const recordPath = path.join(candidate, SOURCE_INPUTS_RECORD);
        await dependencies.fileSystem.writeTextAbsent(recordPath, `${JSON.stringify(identity.sourceTree)}\n`);
        sourceInputRecordSha256 = await dependencies.fileSystem.sha256(recordPath);
      }
      const frontendOutput = await snapshotFrontendOutput(candidate);
      const marker: InstalledMarker = {
        completedAt: new Date().toISOString(),
        frontendOutputDigest: frontendOutput.digest,
        frontendOutputEntryCount: frontendOutput.entryCount,
        frontendOutputIndexSha256: frontendOutput.indexSha256,
        node: manifest.node.version,
        packageManager: manifest.pnpm.packageManager,
        pnpm: manifest.pnpm.version,
        provenance: identity.provenance,
        repository: repository.gitUrl,
        revision: identity.revision,
        schemaVersion: 3,
        uv: manifest.uv.version,
        ...(identity.gitTree ? { gitTree: identity.gitTree } : {}),
        ...(identity.archiveFinalOrigin ? { archiveFinalOrigin: identity.archiveFinalOrigin } : {}),
        ...(identity.archiveSha256 ? { archiveSha256: identity.archiveSha256 } : {}),
        ...(identity.sourceTree ? { sourceInputDigest: identity.sourceTree.digest } : {}),
        ...(sourceInputRecordSha256 ? { sourceInputRecordSha256 } : {}),
      };
      const markerContent = `${JSON.stringify(marker)}\n`;
      const completionMarkerPath = markerPath(candidate, identity.provenance);
      await dependencies.fileSystem.writeTextAbsent(completionMarkerPath, markerContent);
      await options.onPromotionBoundary?.("after-marker");
      assertAttempt(attempt, signal);
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      await options.onPromotionBoundary?.("before-rename");
      assertAttempt(attempt, signal);
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      identity = await verifyCandidateBinding(
        attempt,
        signal,
        candidate,
        identity,
        identity.provenance === "github-archive" ? [BOOTSTRAP_MARKER, SOURCE_INPUTS_RECORD] : [],
      );
      await validateRepositoryShape(candidate);
      if ((await dependencies.fileSystem.readTextNoFollow(completionMarkerPath)) !== markerContent) {
        throw new Error("Bootstrap completion marker changed before promotion.");
      }
      const finalFrontendOutput = await snapshotFrontendOutput(candidate);
      if (
        finalFrontendOutput.digest !== frontendOutput.digest ||
        finalFrontendOutput.entryCount !== frontendOutput.entryCount ||
        finalFrontendOutput.indexSha256 !== frontendOutput.indexSha256
      ) {
        throw new Error("The built terminal output changed before promotion.");
      }
      if (identity.provenance === "github-archive") {
        const recordPath = path.join(candidate, SOURCE_INPUTS_RECORD);
        if (!sourceInputRecordSha256 || (await dependencies.fileSystem.sha256(recordPath)) !== sourceInputRecordSha256) {
          throw new Error("Archive source input record changed before promotion.");
        }
      }
      const finalCanonicalCandidate = await dependencies.fileSystem.realpath(candidate);
      const finalCanonicalParent = await dependencies.fileSystem.realpath(path.dirname(candidate));
      if (
        !isWithin(finalCanonicalParent, finalCanonicalCandidate) ||
        path.dirname(candidate) !== path.dirname(desktopPaths.activeSource)
      ) {
        throw new Error("Candidate and active source are not confined same-filesystem siblings.");
      }
      await dependencies.fileSystem.assertDirectoryIdentity(candidate, acquired.candidateIdentity);
      await dependencies.fileSystem.promoteAbsent(candidate, desktopPaths.activeSource, acquired.candidateIdentity);
      await options.onPromotionBoundary?.("after-rename");
      assertAttempt(attempt, signal);
      await verifyRelocatableVirtualEnvironment(attempt, signal, desktopPaths.activeSource);
      return {
        ok: true,
        provenance: identity.provenance,
        revision: identity.revision,
        sourceIdentity: acquired.candidateIdentity,
      };
    } finally {
      if (!options.heldOperationLease && !containmentFailure) await settlePendingLease();
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
      const result = await executeAttempt(attempt, signal);
      if (result.ok && result.revision) {
        assertAttempt(attempt, signal);
        await queueLog(attempt, "complete", `First-run source ${result.revision} is ready`);
        assertLogging(attempt);
        assertAttempt(attempt, signal);
        state.complete(attempt, `Source ${result.revision.slice(0, 12)} is ready`);
      }
      return result;
    } catch (error) {
      const snapshot = state.getSnapshot();
      const abortError =
        typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
      const cancelled =
        abortError &&
        (signal.aborted ||
          snapshot.attempt !== attempt ||
          (snapshot.attempt === attempt && snapshot.phase === "cancelled" && snapshot.status === "failed"));
      const message = sanitise(error instanceof Error ? error.message : String(error));
      if (containmentFailure) state.failClosed(attempt, containmentFailure.message);
      else if (cancelled) state.cancel(attempt);
      else state.fail(attempt, message);
      await queueLog(attempt, cancelled ? "cancelled" : "failed", message);
      return {
        cancelled,
        ...(containmentFailure ? { containmentFailed: true as const } : {}),
        error: message,
        ok: false,
      };
    } finally {
      clearInterval(heartbeat);
    }
  };

  const launch = (attempt: number): Promise<BootstrapResult> => {
    const abort = new AbortController();
    currentAbort = abort;
    const promise = operationCoordinator.run("bootstrap", abort.signal, (signal) => runAttempt(attempt, signal)).catch((error) => {
        const message = sanitise(error instanceof Error ? error.message : String(error));
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
    if (containmentFailure) return false;
    const attempt = state.getSnapshot().attempt;
    const cancelled = state.cancel(attempt);
    const running = currentPromise;
    if (running) currentAbort?.abort();
    if (running) await running;
    return cancelled;
  };

  const shutdownResult = (): BootstrapResult => ({ error: "Bootstrap is shutting down.", ok: false });
  const containmentFailureResult = (): BootstrapResult => ({
    containmentFailed: true,
    error: containmentFailure?.message ?? "Bootstrap command process containment could not be proven; restart is blocked.",
    ok: false,
  });

  return {
    cancel: cancelAndSettle,
    retry(): Promise<BootstrapResult> {
      if (shuttingDown) return Promise.resolve(shutdownResult());
      if (containmentFailure) return Promise.resolve(containmentFailureResult());
      if (retryPromise) return retryPromise;
      retryPromise = (async () => {
        const running = currentPromise;
        if (running) await running;
        if (shuttingDown) return shutdownResult();
        if (containmentFailure) return containmentFailureResult();
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
      if (!shutdownSettlement) {
        shuttingDown = true;
        currentAbort?.abort();
        const attempt = state.getSnapshot().attempt;
        state.cancel(attempt);
        shutdownSettlement = (async () => {
          while (currentPromise || retryPromise) {
            const pending = [currentPromise, retryPromise].filter(
              (promise): promise is Promise<BootstrapResult> => promise !== null,
            );
            if (pending.length === 0) break;
            await Promise.allSettled(pending);
          }
          await logQueue;
        })();
      }
      const settlement = (async () => {
        await Promise.all([shutdownSettlement, operationCoordinator.shutdown(timeoutMs)]);
        if (!containmentFailure) await settlePendingLease();
        await logQueue;
        if (containmentFailure) throw containmentFailure;
      })();
      let timeout: NodeJS.Timeout | undefined;
      return Promise.race([
        settlement,
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(() => reject(new Error("Bootstrap process containment did not settle before quit.")), timeoutMs);
        }),
      ]).finally(() => {
        if (timeout) clearTimeout(timeout);
      });
    },
    start(): Promise<BootstrapResult> {
      if (shuttingDown) return Promise.resolve(shutdownResult());
      if (containmentFailure) return Promise.resolve(containmentFailureResult());
      if (retryPromise) return retryPromise;
      if (currentPromise) return currentPromise;
      const attempt = state.begin("Preparing source bootstrap", "preparing");
      return launch(attempt);
    },
  };
}
