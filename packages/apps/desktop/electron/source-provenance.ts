import { createHash } from "node:crypto";
import path from "node:path";

import {
  BOOTSTRAP_MARKER,
  SOURCE_INPUTS_RECORD,
  redactBootstrapText,
  type BootstrapDependencies,
  type BootstrapProvenance,
  type DownloadPolicy,
  type FileSystemDirectoryMetadata,
  type FileSystemIdentity,
  type SourceTreeEntry,
  type SourceTreeIdentity,
} from "./bootstrap";
import { inspectHardenedGitCheckout } from "./git-source-inspection";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const TOOL_VERSION_PATTERN = /^(?!0\.0\.0(?:$|-))(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/;
const PACKAGE_MANAGER_PATTERN = /^pnpm@((?!0\.0\.0(?:$|-))(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?)(?:\+sha512\.[0-9A-Za-z_-]+)?$/;
const MAX_FRONTEND_OUTPUT_ENTRIES = 20_000;
const MAX_FRONTEND_OUTPUT_MANIFEST_BYTES = 32 * 1024 * 1024;
const REQUIRED_REPOSITORY_PATHS = Object.freeze([
  "package.json",
  "pyproject.toml",
  "uv.lock",
  "pnpm-lock.yaml",
  "packages/apps/terminal/package.json",
]);

export const ARCHIVE_GENERATED_SOURCE_ROOTS = Object.freeze([
  ".venv",
  "node_modules",
  "packages/apps/desktop/node_modules",
  "packages/apps/site/node_modules",
  "packages/apps/terminal/node_modules",
  "packages/apps/terminal/dist",
  "packages/core/design-system/node_modules",
]);

type ProvenanceFileSystem = Pick<
  BootstrapDependencies["fileSystem"],
  | "directoryIdentity"
  | "directoryMetadata"
  | "exists"
  | "existsNoFollow"
  | "fileIdentity"
  | "listNames"
  | "readTextNoFollow"
  | "realpath"
  | "sha256"
  | "snapshotSourceTree"
  | "verifySourceTree"
>;

export interface SourceProvenanceDependencies {
  command: Pick<BootstrapDependencies["command"], "run">;
  fileSystem: ProvenanceFileSystem;
}

export interface SourceRevisionDependencies {
  command: Pick<BootstrapDependencies["command"], "run">;
  download: Pick<BootstrapDependencies["download"], "text">;
}

export interface SourceRevisionRepository {
  archiveAllowedHosts: readonly string[];
  archiveBaseUrl: string;
  branch: string;
  commitMetadataUrl: string;
  gitOrigin: string;
  metadataAllowedHosts: readonly string[];
}

export interface SourceRevisionRequest {
  dependencies: SourceRevisionDependencies;
  platform: NodeJS.Platform;
  repository: SourceRevisionRepository;
  signal: AbortSignal;
}

export type ExactSourceRevision =
  | { provenance: "git"; revision: string }
  | {
      archiveOrigin: string;
      archiveUrl: string;
      provenance: "github-archive";
      revision: string;
    };

export interface ExpectedSourceProvenance {
  archiveOrigin: string;
  branch: string;
  gitOrigin: string;
  packageManager: string;
  packageName: string;
  toolchain: {
    node: string;
    pnpm: string;
    uv: string;
  };
}

export interface SourceProvenanceRequest {
  activeSource: string;
  bootstrapResources: string;
  dependencies: SourceProvenanceDependencies;
  disallowedAliases: readonly string[];
  expected: ExpectedSourceProvenance;
  platform: NodeJS.Platform;
  signal: AbortSignal;
  sourceRoot: string;
}

interface CommonInstalledMarkerV2 {
  completedAt: string;
  node: string;
  pnpm: string;
  provenance: BootstrapProvenance;
  repository: string;
  revision: string;
  schemaVersion: 2;
  uv: string;
}

interface CommonInstalledMarkerV3 extends Omit<CommonInstalledMarkerV2, "schemaVersion"> {
  frontendOutputDigest: string;
  frontendOutputEntryCount: number;
  frontendOutputIndexSha256: string;
  packageManager: string;
  schemaVersion: 3;
}

interface GitInstalledMarkerV2 extends CommonInstalledMarkerV2 {
  gitTree: string;
  provenance: "git";
}

interface GitInstalledMarkerV3 extends CommonInstalledMarkerV3 {
  gitTree: string;
  provenance: "git";
}

interface ArchiveInstalledMarkerV2 extends CommonInstalledMarkerV2 {
  archiveFinalOrigin: string;
  archiveSha256: string;
  provenance: "github-archive";
  sourceInputDigest: string;
  sourceInputRecordSha256: string;
}

interface ArchiveInstalledMarkerV3 extends CommonInstalledMarkerV3 {
  archiveFinalOrigin: string;
  archiveSha256: string;
  provenance: "github-archive";
  sourceInputDigest: string;
  sourceInputRecordSha256: string;
}

type GitInstalledMarker = GitInstalledMarkerV2 | GitInstalledMarkerV3;
type ArchiveInstalledMarker = ArchiveInstalledMarkerV2 | ArchiveInstalledMarkerV3;
type InstalledMarker = GitInstalledMarker | ArchiveInstalledMarker;

export interface SourceBuildIdentity {
  frontendOutputDigest: string | null;
  markerSchemaVersion: 2 | 3;
  packageManager: string;
  toolchain: {
    node: string;
    pnpm: string;
    uv: string;
  };
}

export type ActiveSourceIdentity =
  | {
      buildIdentity?: SourceBuildIdentity;
      canonicalPath: string;
      contentIdentity: string;
      directoryIdentity: FileSystemIdentity;
      provenance: "git";
      requiresRebuild?: boolean;
      revision: string;
    }
  | {
      archiveFinalOrigin: string;
      archiveSha256: string;
      buildIdentity?: SourceBuildIdentity;
      canonicalPath: string;
      contentIdentity: string;
      directoryIdentity: FileSystemIdentity;
      provenance: "github-archive";
      requiresRebuild?: boolean;
      revision: string;
    };

type UnboundSourceIdentity =
  | {
      buildIdentity: SourceBuildIdentity;
      contentIdentity: string;
      provenance: "git";
      requiresRebuild: boolean;
      revision: string;
    }
  | {
      archiveFinalOrigin: string;
      archiveSha256: string;
      buildIdentity: SourceBuildIdentity;
      contentIdentity: string;
      provenance: "github-archive";
      requiresRebuild: boolean;
      revision: string;
    };

interface ActiveDirectoryProof {
  canonicalPath: string;
  metadata: FileSystemDirectoryMetadata;
}

const GIT_MARKER_FIELDS_V2 = Object.freeze([
  "completedAt",
  "gitTree",
  "node",
  "pnpm",
  "provenance",
  "repository",
  "revision",
  "schemaVersion",
  "uv",
]);
const GIT_MARKER_FIELDS_V3 = Object.freeze([
  ...GIT_MARKER_FIELDS_V2,
  "frontendOutputDigest",
  "frontendOutputEntryCount",
  "frontendOutputIndexSha256",
  "packageManager",
]);
const ARCHIVE_MARKER_FIELDS_V2 = Object.freeze([
  "archiveFinalOrigin",
  "archiveSha256",
  "completedAt",
  "node",
  "pnpm",
  "provenance",
  "repository",
  "revision",
  "schemaVersion",
  "sourceInputDigest",
  "sourceInputRecordSha256",
  "uv",
]);
const ARCHIVE_MARKER_FIELDS_V3 = Object.freeze([
  ...ARCHIVE_MARKER_FIELDS_V2,
  "frontendOutputDigest",
  "frontendOutputEntryCount",
  "frontendOutputIndexSha256",
  "packageManager",
]);
const SOURCE_REVISION_METADATA_POLICY = Object.freeze({
  idleTimeoutMs: 30_000,
  label: "FlintTrade source revision metadata",
  maxBytes: 1024 * 1024,
  totalTimeoutMs: 2 * 60_000,
});
const SAFE_BRANCH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJsonObject(content: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    throw new Error(`${label} is not valid JSON.`);
  }
  if (!isObject(parsed)) throw new Error(`${label} must be a JSON object.`);
  return parsed;
}

function assertExactFields(value: Record<string, unknown>, fields: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  if (actual.length !== expected.length || actual.some((field, index) => field !== expected[index])) {
    throw new Error(`${label} has missing or unexpected fields.`);
  }
}

function requireCommit(value: unknown, label: string): string {
  if (typeof value !== "string" || !COMMIT_PATTERN.test(value)) {
    throw new Error(`${label} must be an exact lowercase Git object identity.`);
  }
  return value;
}

function requireSha256(value: unknown, label: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new Error(`${label} must be an exact lowercase SHA-256 identity.`);
  }
  return value;
}

function requireToolVersion(value: unknown, label: string): string {
  if (typeof value !== "string" || !TOOL_VERSION_PATTERN.test(value)) {
    throw new Error(`${label} must be a valid pinned tool version.`);
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

function requireFrontendEntryCount(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > MAX_FRONTEND_OUTPUT_ENTRIES) {
    throw new Error("The terminal output marker has an invalid bounded entry count.");
  }
  return value as number;
}

function assertCommonMarker(
  marker: Record<string, unknown>,
  expected: ExpectedSourceProvenance,
  provenance: BootstrapProvenance,
): void {
  if (
    (marker.schemaVersion !== 2 && marker.schemaVersion !== 3) ||
    marker.provenance !== provenance ||
    marker.repository !== expected.gitOrigin ||
    typeof marker.completedAt !== "string" ||
    Number.isNaN(Date.parse(marker.completedAt)) ||
    new Date(marker.completedAt).toISOString() !== marker.completedAt
  ) {
    throw new Error("The active source completion marker has foreign or inexact provenance.");
  }
  requireToolVersion(marker.node, "The recorded Node version");
  const pnpm = requireToolVersion(marker.pnpm, "The recorded pnpm version");
  requireToolVersion(marker.uv, "The recorded uv version");
  if (marker.schemaVersion === 3) {
    requirePackageManager(marker.packageManager, pnpm);
    requireSha256(marker.frontendOutputDigest, "The terminal output digest");
    requireSha256(marker.frontendOutputIndexSha256, "The terminal index digest");
    requireFrontendEntryCount(marker.frontendOutputEntryCount);
  }
}

function parseGitMarker(content: string, expected: ExpectedSourceProvenance): GitInstalledMarker {
  const parsed = parseJsonObject(content, "The Git completion marker");
  const schemaVersion = parsed.schemaVersion;
  assertExactFields(
    parsed,
    schemaVersion === 3 ? GIT_MARKER_FIELDS_V3 : GIT_MARKER_FIELDS_V2,
    "The Git completion marker",
  );
  assertCommonMarker(parsed, expected, "git");
  const common = {
    completedAt: parsed.completedAt as string,
    gitTree: requireCommit(parsed.gitTree, "The Git marker tree"),
    node: requireToolVersion(parsed.node, "The recorded Node version"),
    pnpm: requireToolVersion(parsed.pnpm, "The recorded pnpm version"),
    provenance: "git",
    repository: parsed.repository as string,
    revision: requireCommit(parsed.revision, "The Git marker revision"),
    uv: requireToolVersion(parsed.uv, "The recorded uv version"),
  };
  return schemaVersion === 3
    ? {
        ...common,
        frontendOutputDigest: requireSha256(parsed.frontendOutputDigest, "The terminal output digest"),
        frontendOutputEntryCount: requireFrontendEntryCount(parsed.frontendOutputEntryCount),
        frontendOutputIndexSha256: requireSha256(parsed.frontendOutputIndexSha256, "The terminal index digest"),
        packageManager: requirePackageManager(parsed.packageManager, common.pnpm),
        provenance: "git",
        schemaVersion: 3,
      }
    : { ...common, provenance: "git", schemaVersion: 2 };
}

function expectedArchiveOrigin(value: string): string {
  return trustedHttpsUrl(value, null, "The configured archive origin", true).origin;
}

function parseArchiveMarker(content: string, expected: ExpectedSourceProvenance): ArchiveInstalledMarker {
  const parsed = parseJsonObject(content, "The archive completion marker");
  const schemaVersion = parsed.schemaVersion;
  assertExactFields(
    parsed,
    schemaVersion === 3 ? ARCHIVE_MARKER_FIELDS_V3 : ARCHIVE_MARKER_FIELDS_V2,
    "The archive completion marker",
  );
  assertCommonMarker(parsed, expected, "github-archive");
  const archiveFinalOrigin = expectedArchiveOrigin(expected.archiveOrigin);
  if (parsed.archiveFinalOrigin !== archiveFinalOrigin) {
    throw new Error("The archive completion marker has a foreign final origin.");
  }
  const common = {
    archiveFinalOrigin,
    archiveSha256: requireSha256(parsed.archiveSha256, "The archive digest"),
    completedAt: parsed.completedAt as string,
    node: requireToolVersion(parsed.node, "The recorded Node version"),
    pnpm: requireToolVersion(parsed.pnpm, "The recorded pnpm version"),
    provenance: "github-archive",
    repository: parsed.repository as string,
    revision: requireCommit(parsed.revision, "The archive marker revision"),
    sourceInputDigest: requireSha256(parsed.sourceInputDigest, "The archive source-input digest"),
    sourceInputRecordSha256: requireSha256(
      parsed.sourceInputRecordSha256,
      "The archive source-input record digest",
    ),
    uv: requireToolVersion(parsed.uv, "The recorded uv version"),
  };
  return schemaVersion === 3
    ? {
        ...common,
        frontendOutputDigest: requireSha256(parsed.frontendOutputDigest, "The terminal output digest"),
        frontendOutputEntryCount: requireFrontendEntryCount(parsed.frontendOutputEntryCount),
        frontendOutputIndexSha256: requireSha256(parsed.frontendOutputIndexSha256, "The terminal index digest"),
        packageManager: requirePackageManager(parsed.packageManager, common.pnpm),
        provenance: "github-archive",
        schemaVersion: 3,
      }
    : { ...common, provenance: "github-archive", schemaVersion: 2 };
}

function sourceEntryPath(value: unknown): string {
  if (typeof value !== "string" || value === "" || value.includes("\\") || path.posix.isAbsolute(value)) {
    throw new Error("The archive source-input record contains an invalid path.");
  }
  const components = value.split("/");
  if (components.some((component) => component === "" || component === "." || component === "..")) {
    throw new Error("The archive source-input record contains an unconfined path.");
  }
  return value;
}

function parseSourceTreeEntry(value: unknown): SourceTreeEntry {
  if (!isObject(value)) throw new Error("The archive source-input record contains an invalid entry.");
  if (!Number.isInteger(value.mode) || (value.mode as number) < 0 || (value.mode as number) > 0o777) {
    throw new Error("The archive source-input record contains an invalid file mode.");
  }
  const entryPath = sourceEntryPath(value.path);
  if (value.type === "file") {
    assertExactFields(value, ["mode", "path", "sha256", "type"], "The archive source-input file entry");
    return {
      mode: value.mode as number,
      path: entryPath,
      sha256: requireSha256(value.sha256, "The archive source-input file digest"),
      type: "file",
    };
  }
  if (value.type === "symlink") {
    assertExactFields(value, ["mode", "path", "target", "type"], "The archive source-input symlink entry");
    if (typeof value.target !== "string") {
      throw new Error("The archive source-input record contains an invalid symlink target.");
    }
    return { mode: value.mode as number, path: entryPath, target: value.target, type: "symlink" };
  }
  throw new Error("The archive source-input record contains an unsupported entry type.");
}

function parseSourceTree(content: string): SourceTreeIdentity {
  const parsed = parseJsonObject(content, "The archive source-input record");
  assertExactFields(parsed, ["digest", "entries"], "The archive source-input record");
  const digest = requireSha256(parsed.digest, "The archive source-input digest");
  if (!Array.isArray(parsed.entries)) throw new Error("The archive source-input record entries must be an array.");
  const entries = parsed.entries.map(parseSourceTreeEntry);
  if (new Set(entries.map((entry) => entry.path)).size !== entries.length) {
    throw new Error("The archive source-input record contains duplicate paths.");
  }
  const actualDigest = createHash("sha256").update(JSON.stringify(entries)).digest("hex");
  if (actualDigest !== digest) throw new Error("The archive source-input record does not match its content identity.");
  return { digest, entries };
}

function samePath(left: string, right: string, platform: NodeJS.Platform): boolean {
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function sameIdentity(left: FileSystemIdentity, right: FileSystemIdentity): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function sameDirectoryMetadata(
  left: FileSystemDirectoryMetadata,
  right: FileSystemDirectoryMetadata,
): boolean {
  return (
    sameIdentity(left, right) &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function requestPath(request: SourceProvenanceRequest, ...parts: string[]): string {
  const pathApi = request.platform === "win32" ? path.win32 : path.posix;
  return pathApi.join(...parts);
}

async function proveActiveDirectory(request: SourceProvenanceRequest): Promise<ActiveDirectoryProof> {
  const { activeSource, dependencies, platform, sourceRoot } = request;
  if (!(await dependencies.fileSystem.exists(activeSource))) throw new Error("The managed active source is missing.");
  if (!(await dependencies.fileSystem.exists(sourceRoot))) throw new Error("The managed source root is missing.");
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  if (!samePath(pathApi.dirname(activeSource), sourceRoot, platform)) {
    throw new Error("The active source is not an exact managed-source sibling.");
  }
  const initialMetadata = await dependencies.fileSystem.directoryMetadata(activeSource);
  const canonicalRoot = await dependencies.fileSystem.realpath(sourceRoot);
  const initialCanonicalPath = await dependencies.fileSystem.realpath(activeSource);
  const finalMetadata = await dependencies.fileSystem.directoryMetadata(activeSource);
  const finalCanonicalPath = await dependencies.fileSystem.realpath(activeSource);
  const expectedCanonicalPath = pathApi.join(canonicalRoot, pathApi.basename(activeSource));
  if (
    !samePath(initialCanonicalPath, expectedCanonicalPath, platform) ||
    !samePath(finalCanonicalPath, expectedCanonicalPath, platform) ||
    !sameDirectoryMetadata(initialMetadata, finalMetadata)
  ) {
    throw new Error("The active source is aliased, escaped or changed during canonical inspection.");
  }
  return { canonicalPath: initialCanonicalPath, metadata: initialMetadata };
}

async function assertNoDisallowedAliases(
  request: SourceProvenanceRequest,
  active: ActiveDirectoryProof,
): Promise<void> {
  for (const alias of request.disallowedAliases) {
    if (!(await request.dependencies.fileSystem.exists(alias))) continue;
    const [canonicalAlias, aliasIdentity] = await Promise.all([
      request.dependencies.fileSystem.realpath(alias),
      request.dependencies.fileSystem.directoryIdentity(alias),
    ]);
    if (
      samePath(canonicalAlias, active.canonicalPath, request.platform) ||
      sameIdentity(aliasIdentity, active.metadata)
    ) {
      throw new Error("The active source aliases a candidate or last-known-good directory identity.");
    }
  }
}

async function assertRepositoryShape(
  request: SourceProvenanceRequest,
  marker: InstalledMarker,
): Promise<string> {
  for (const relative of REQUIRED_REPOSITORY_PATHS) {
    if (!(await request.dependencies.fileSystem.exists(requestPath(request, request.activeSource, ...relative.split("/"))))) {
      throw new Error(`The active source has a foreign repository shape: missing ${relative}.`);
    }
  }
  let metadata: unknown;
  try {
    metadata = JSON.parse(
      await request.dependencies.fileSystem.readTextNoFollow(requestPath(request, request.activeSource, "package.json")),
    );
  } catch {
    throw new Error("The active source package identity is not valid JSON in a no-follow regular file.");
  }
  if (!isObject(metadata) || metadata.name !== request.expected.packageName) {
    throw new Error("The active source has a foreign repository package identity.");
  }
  const packageManager = requirePackageManager(metadata.packageManager, marker.pnpm);
  if (marker.schemaVersion === 3 && marker.packageManager !== packageManager) {
    throw new Error("The active source package-manager pin does not match its completion marker.");
  }
  return packageManager;
}

function sourceBuildIdentity(marker: InstalledMarker, packageManager: string): SourceBuildIdentity {
  return {
    frontendOutputDigest: marker.schemaVersion === 3 ? marker.frontendOutputDigest : null,
    markerSchemaVersion: marker.schemaVersion,
    packageManager,
    toolchain: { node: marker.node, pnpm: marker.pnpm, uv: marker.uv },
  };
}

function requiresCurrentRebuild(
  marker: InstalledMarker,
  packageManager: string,
  expected: ExpectedSourceProvenance,
): boolean {
  return marker.schemaVersion !== 3 ||
    marker.node !== expected.toolchain.node ||
    marker.pnpm !== expected.toolchain.pnpm ||
    marker.uv !== expected.toolchain.uv ||
    packageManager !== expected.packageManager;
}

async function validateFrontendOutput(
  request: SourceProvenanceRequest,
  marker: InstalledMarker,
): Promise<string | null> {
  if (marker.schemaVersion === 2) return null;
  const output = await request.dependencies.fileSystem.snapshotSourceTree(
    requestPath(request, request.activeSource, "packages", "apps", "terminal", "dist"),
  );
  const manifestBytes = Buffer.byteLength(JSON.stringify(output.entries));
  if (
    output.entries.length === 0 ||
    output.entries.length > MAX_FRONTEND_OUTPUT_ENTRIES ||
    manifestBytes > MAX_FRONTEND_OUTPUT_MANIFEST_BYTES
  ) {
    throw new Error("The terminal output manifest is empty or exceeds its bounded acceptance limits.");
  }
  const index = output.entries.find((entry) => entry.path === "index.html");
  if (index?.type !== "file" || !index.sha256) {
    throw new Error("The terminal output is missing a no-follow regular index.html.");
  }
  if (
    output.digest !== marker.frontendOutputDigest ||
    output.entries.length !== marker.frontendOutputEntryCount ||
    index.sha256 !== marker.frontendOutputIndexSha256
  ) {
    throw new Error("The terminal output does not match its completion-marker identity.");
  }
  return output.digest;
}

async function selectedMarker(request: SourceProvenanceRequest): Promise<{
  content: string;
  path: string;
  provenance: BootstrapProvenance;
}> {
  const gitPath = requestPath(request, request.activeSource, ".git", BOOTSTRAP_MARKER);
  const archivePath = requestPath(request, request.activeSource, BOOTSTRAP_MARKER);
  const [hasGitMarker, hasArchiveMarker] = await Promise.all([
    request.dependencies.fileSystem.exists(gitPath),
    request.dependencies.fileSystem.exists(archivePath),
  ]);
  if (Number(hasGitMarker) + Number(hasArchiveMarker) !== 1) {
    throw new Error("The active source is unmarked or has ambiguous completion-marker provenance.");
  }
  const provenance = hasGitMarker ? "git" : "github-archive";
  const markerPath = hasGitMarker ? gitPath : archivePath;
  return {
    content: await request.dependencies.fileSystem.readTextNoFollow(markerPath),
    path: markerPath,
    provenance,
  };
}

function nullDevice(platform: NodeJS.Platform): string {
  return platform === "win32" ? "NUL" : "/dev/null";
}

function trustedGitWorkingDirectory(): string {
  return path.dirname(process.execPath);
}

function gitEnvironment(platform: NodeJS.Platform, ceiling?: string): NodeJS.ProcessEnv {
  return {
    ...(ceiling ? { GIT_CEILING_DIRECTORIES: ceiling } : {}),
    GIT_CONFIG_GLOBAL: nullDevice(platform),
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_SYSTEM: nullDevice(platform),
    GIT_TERMINAL_PROMPT: "0",
  };
}

function safeBranch(value: string): string {
  const components = value.split("/");
  if (
    !SAFE_BRANCH_PATTERN.test(value) ||
    value.includes("..") ||
    value.includes("//") ||
    value.includes("@{") ||
    value.endsWith(".") ||
    value.endsWith("/") ||
    value.endsWith(".lock") ||
    components.some((component) => component === "" || component.startsWith("."))
  ) {
    throw new Error("The configured source branch is not a safe exact Git ref.");
  }
  return value;
}

function trustedHosts(values: readonly string[], label: string): string[] {
  if (values.length === 0) throw new Error(`${label} does not configure any trusted hosts.`);
  const result = values.map((value) => value.toLowerCase());
  if (
    result.some(
      (value, index) =>
        value !== values[index] ||
        !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(value) ||
        value.includes(".."),
    ) ||
    new Set(result).size !== result.length
  ) {
    throw new Error(`${label} contains an invalid or duplicate trusted host.`);
  }
  return result;
}

function trustedHttpsUrl(
  value: string,
  allowedHosts: readonly string[] | null,
  label: string,
  configured: boolean,
): URL {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} is not a valid URL.`);
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.port !== "" ||
    parsed.hash !== "" ||
    (configured && parsed.search !== "") ||
    (allowedHosts && !allowedHosts.includes(parsed.hostname.toLowerCase()))
  ) {
    throw new Error(`${label} is not a trusted credential-free HTTPS URL.`);
  }
  return parsed;
}

function archiveUrl(base: URL, revision: string): string {
  const resolved = new URL(base.toString());
  resolved.pathname = `${resolved.pathname.replace(/\/+$/, "")}/${revision}`;
  return resolved.toString();
}

function exactRemoteRevision(stdout: string, ref: string): string {
  const match = /^([0-9a-f]{40})\t([^\r\n]+)\n?$/.exec(stdout);
  if (!match || match[2] !== ref) {
    throw new Error("Git did not return one exact commit for the configured branch ref.");
  }
  return match[1]!;
}

function cancellationError(): DOMException {
  return new DOMException("Source revision resolution was cancelled.", "AbortError");
}

function assertNotCancelled(signal: AbortSignal): void {
  if (signal.aborted) throw cancellationError();
}

function metadataPolicy(allowedHosts: readonly string[]): DownloadPolicy {
  return { ...SOURCE_REVISION_METADATA_POLICY, allowedHosts };
}

async function archiveFallback(
  request: SourceRevisionRequest,
  metadataUrl: URL,
  metadataAllowedHosts: readonly string[],
  archiveBase: URL,
): Promise<ExactSourceRevision> {
  assertNotCancelled(request.signal);
  let receipt: Awaited<ReturnType<SourceRevisionDependencies["download"]["text"]>>;
  try {
    receipt = await request.dependencies.download.text(
      metadataUrl.toString(),
      request.signal,
      metadataPolicy(metadataAllowedHosts),
    );
  } catch (error) {
    assertNotCancelled(request.signal);
    const detail = redactBootstrapText(error instanceof Error ? error.message : String(error));
    throw new Error(`Trusted source metadata resolution failed: ${detail}`);
  }
  assertNotCancelled(request.signal);
  const finalUrl = trustedHttpsUrl(receipt.finalUrl, metadataAllowedHosts, "The final source metadata URL", false);
  if (receipt.origin !== finalUrl.origin) {
    throw new Error("The source metadata receipt origin does not match its trusted final URL.");
  }
  const contentDigest = createHash("sha256").update(receipt.content).digest("hex");
  if (
    receipt.bytes !== Buffer.byteLength(receipt.content) ||
    !SHA256_PATTERN.test(receipt.sha256) ||
    receipt.sha256 !== contentDigest
  ) {
    throw new Error("The source metadata receipt does not match its exact downloaded content.");
  }
  const metadata = parseJsonObject(receipt.content, "The source revision metadata");
  const revision = requireCommit(metadata.sha, "The source metadata revision");
  return {
    archiveOrigin: archiveBase.origin,
    archiveUrl: archiveUrl(archiveBase, revision),
    provenance: "github-archive",
    revision,
  };
}

export async function resolveExactSourceRevision(request: SourceRevisionRequest): Promise<ExactSourceRevision> {
  assertNotCancelled(request.signal);
  const branch = safeBranch(request.repository.branch);
  const metadataAllowedHosts = trustedHosts(
    request.repository.metadataAllowedHosts,
    "The source metadata policy",
  );
  const archiveAllowedHosts = trustedHosts(request.repository.archiveAllowedHosts, "The source archive policy");
  const gitOriginUrl = trustedHttpsUrl(request.repository.gitOrigin, null, "The configured Git origin", true);
  if (!gitOriginUrl.pathname.endsWith(".git")) throw new Error("The configured Git origin is not an exact repository URL.");
  const metadataUrl = trustedHttpsUrl(
    request.repository.commitMetadataUrl,
    metadataAllowedHosts,
    "The configured source metadata URL",
    true,
  );
  let decodedMetadataPath: string;
  try {
    decodedMetadataPath = decodeURIComponent(metadataUrl.pathname);
  } catch {
    throw new Error("The configured source metadata URL has an invalid encoded path.");
  }
  if (!decodedMetadataPath.endsWith(`/commits/${branch}`)) {
    throw new Error("The configured source metadata URL is not bound to the exact source branch.");
  }
  const archiveBase = trustedHttpsUrl(
    request.repository.archiveBaseUrl,
    archiveAllowedHosts,
    "The configured source archive URL",
    true,
  );
  const ref = `refs/heads/${branch}`;
  const gitCwd = trustedGitWorkingDirectory();
  let gitResult: Awaited<ReturnType<SourceRevisionDependencies["command"]["run"]>>;
  try {
    gitResult = await request.dependencies.command.run({
      args: [
        "--no-optional-locks",
        "--no-replace-objects",
        `--git-dir=${nullDevice(request.platform)}`,
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "ls-remote",
        "--exit-code",
        "--refs",
        request.repository.gitOrigin,
        ref,
      ],
      command: "git",
      cwd: gitCwd,
      env: gitEnvironment(request.platform, gitCwd),
      signal: request.signal,
      timeoutMs: 30_000,
    });
  } catch (error) {
    throw new SourceOperationLeaseRetentionError(
      "Git source revision resolution rejected without proving command containment.",
      { cause: error },
    );
  }
  assertNotCancelled(request.signal);
  if (!gitResult.contained) {
    throw new SourceOperationLeaseRetentionError(
      "Git source revision resolution could not prove command containment.",
    );
  }
  if (gitResult.stdoutTruncated || gitResult.stderrTruncated) {
    throw new Error("Git source revision resolution returned truncated output.");
  }
  if (gitResult.exitCode === 0) {
    return { provenance: "git", revision: exactRemoteRevision(gitResult.stdout, ref) };
  }
  return archiveFallback(request, metadataUrl, metadataAllowedHosts, archiveBase);
}

async function validateGit(
  request: SourceProvenanceRequest,
  marker: GitInstalledMarker,
  markerContent: string,
  markerPath: string,
  buildIdentity: SourceBuildIdentity,
  requiresRebuild: boolean,
): Promise<UnboundSourceIdentity> {
  const identity = await inspectHardenedGitCheckout({
    bootstrapResources: request.bootstrapResources,
    dependencies: request.dependencies,
    expected: {
      branch: request.expected.branch,
      origin: request.expected.gitOrigin,
      revision: marker.revision,
      tree: marker.gitTree,
    },
    platform: request.platform,
    root: request.activeSource,
    signal: request.signal,
  });
  if ((await request.dependencies.fileSystem.readTextNoFollow(markerPath)) !== markerContent) {
    throw new Error("The active Git completion marker changed during provenance inspection.");
  }
  return {
    buildIdentity,
    contentIdentity: identity.tree,
    provenance: "git",
    requiresRebuild,
    revision: identity.revision,
  };
}

async function validateArchive(
  request: SourceProvenanceRequest,
  marker: ArchiveInstalledMarker,
  markerContent: string,
  markerPath: string,
  buildIdentity: SourceBuildIdentity,
  requiresRebuild: boolean,
): Promise<UnboundSourceIdentity> {
  const recordPath = requestPath(request, request.activeSource, SOURCE_INPUTS_RECORD);
  if (!(await request.dependencies.fileSystem.exists(recordPath))) {
    throw new Error("The archive source-input identity record is missing.");
  }
  const recordContent = await request.dependencies.fileSystem.readTextNoFollow(recordPath);
  if ((await request.dependencies.fileSystem.sha256(recordPath)) !== marker.sourceInputRecordSha256) {
    throw new Error("The archive source-input record does not match its completion-marker digest.");
  }
  const sourceTree = parseSourceTree(recordContent);
  if (sourceTree.digest !== marker.sourceInputDigest) {
    throw new Error("The archive source-input record does not match its completion-marker content identity.");
  }
  if ((await request.dependencies.fileSystem.readTextNoFollow(markerPath)) !== markerContent) {
    throw new Error("The archive completion marker changed during provenance inspection.");
  }
  if ((await request.dependencies.fileSystem.sha256(recordPath)) !== marker.sourceInputRecordSha256) {
    throw new Error("The archive source-input record changed during provenance inspection.");
  }
  if (
    !(await request.dependencies.fileSystem.verifySourceTree(
      request.activeSource,
      sourceTree,
      ARCHIVE_GENERATED_SOURCE_ROOTS,
      [BOOTSTRAP_MARKER, SOURCE_INPUTS_RECORD],
    ))
  ) {
    throw new Error("The archive-backed source content changed after bootstrap.");
  }
  return {
    archiveFinalOrigin: marker.archiveFinalOrigin,
    archiveSha256: marker.archiveSha256,
    buildIdentity,
    contentIdentity: sourceTree.digest,
    provenance: "github-archive",
    requiresRebuild,
    revision: marker.revision,
  };
}

async function assertFinalProof(
  request: SourceProvenanceRequest,
  active: ActiveDirectoryProof,
  markerPath: string,
  markerContent: string,
): Promise<void> {
  const finalProof = await proveActiveDirectory(request);
  if (
    !samePath(active.canonicalPath, finalProof.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(active.metadata, finalProof.metadata)
  ) {
    throw new Error("The active source directory identity changed during provenance inspection.");
  }
  await assertNoDisallowedAliases(request, active);
  if (await request.dependencies.fileSystem.existsNoFollow(requestPath(request, request.activeSource, ".env"))) {
    throw new Error("The active source contains a repository-root .env environment file.");
  }
  const finalMarker = await selectedMarker(request);
  if (finalMarker.path !== markerPath || finalMarker.content !== markerContent) {
    throw new Error("The active source completion-marker provenance changed during inspection.");
  }
}

export async function validateActiveSourceProvenance(
  request: SourceProvenanceRequest,
): Promise<ActiveSourceIdentity> {
  const expectedGitOrigin = trustedHttpsUrl(request.expected.gitOrigin, null, "The expected Git origin", true);
  if (!expectedGitOrigin.pathname.endsWith(".git")) {
    throw new Error("The expected Git origin is not an exact repository URL.");
  }
  expectedArchiveOrigin(request.expected.archiveOrigin);
  const active = await proveActiveDirectory(request);
  await assertNoDisallowedAliases(request, active);
  if (await request.dependencies.fileSystem.existsNoFollow(requestPath(request, request.activeSource, ".env"))) {
    throw new Error("The active source contains a repository-root .env environment file.");
  }
  const markerSelection = await selectedMarker(request);
  const marker = markerSelection.provenance === "git"
    ? parseGitMarker(markerSelection.content, request.expected)
    : parseArchiveMarker(markerSelection.content, request.expected);
  const packageManager = await assertRepositoryShape(request, marker);
  const buildIdentity = sourceBuildIdentity(marker, packageManager);
  const requiresRebuild = requiresCurrentRebuild(marker, packageManager, request.expected);
  const initialFrontendOutput = await validateFrontendOutput(request, marker);
  const identity = marker.provenance === "git"
    ? await validateGit(
        request,
        marker,
        markerSelection.content,
        markerSelection.path,
        buildIdentity,
        requiresRebuild,
      )
    : await validateArchive(
        request,
        marker,
        markerSelection.content,
        markerSelection.path,
        buildIdentity,
        requiresRebuild,
      );
  await assertFinalProof(request, active, markerSelection.path, markerSelection.content);
  const finalFrontendOutput = await validateFrontendOutput(request, marker);
  if (finalFrontendOutput !== initialFrontendOutput) {
    throw new Error("The terminal output identity changed during provenance inspection.");
  }
  return {
    ...identity,
    canonicalPath: active.canonicalPath,
    directoryIdentity: { dev: active.metadata.dev, ino: active.metadata.ino },
  };
}

export function sourceContentIdentityKey(identity: ActiveSourceIdentity): string {
  const content = identity.provenance === "git"
    ? {
        buildIdentity: identity.buildIdentity ?? null,
        contentIdentity: identity.contentIdentity,
        provenance: identity.provenance,
        revision: identity.revision,
      }
    : {
        archiveFinalOrigin: identity.archiveFinalOrigin,
        archiveSha256: identity.archiveSha256,
        buildIdentity: identity.buildIdentity ?? null,
        contentIdentity: identity.contentIdentity,
        provenance: identity.provenance,
        revision: identity.revision,
      };
  return createHash("sha256").update(JSON.stringify(content)).digest("hex");
}
