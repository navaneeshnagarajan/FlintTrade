import path from "node:path";

import type {
  BootstrapDependencies,
  CommandResult,
  FileSystemDirectoryMetadata,
  FileSystemFileIdentity,
} from "./bootstrap";
import { assertGitHeadBindingStable, captureGitHeadBinding } from "./git-head-binding";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const SAFE_BRANCH_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;
const MAX_GIT_CONFIG_BYTES = 64 * 1024;
const SAFE_GIT_TEXT_PATTERN = /^[\t\n\r\x20-\x7e]*$/;
const MAX_GIT_INFO_BYTES = 64 * 1024;
const GIT_COMMON_SENTINEL = "FlintTrade hardened Git object-directory sentinel.\n";
const GIT_REFS_SENTINEL = "FlintTrade hardened Git ref-directory sentinel.\n";

type HardenedGitFileSystem = Pick<
  BootstrapDependencies["fileSystem"],
  | "directoryMetadata"
  | "existsNoFollow"
  | "fileIdentity"
  | "listNames"
  | "readTextNoFollow"
  | "realpath"
>;

export interface HardenedGitInspectionDependencies {
  command: Pick<BootstrapDependencies["command"], "run">;
  fileSystem: HardenedGitFileSystem;
}

export interface HardenedGitInspectionRequest {
  bootstrapResources: string;
  dependencies: HardenedGitInspectionDependencies;
  expected: {
    branch: string;
    origin: string;
    revision?: string;
    tree?: string;
  };
  platform: NodeJS.Platform;
  root: string;
  signal: AbortSignal;
}

export interface HardenedGitIdentity {
  revision: string;
  tree: string;
}

interface DirectoryProof {
  canonicalPath: string;
  metadata: FileSystemDirectoryMetadata;
}

interface GitMetadataProof {
  attributes: OptionalFileProof;
  alternates: OptionalFileProof;
  checkoutDirectory: DirectoryProof;
  config: FileSystemFileIdentity;
  exclude: OptionalFileProof;
  gitDirectory: DirectoryProof;
  head: FileSystemFileIdentity;
  infoDirectory: DirectoryProof;
  index: FileSystemFileIdentity;
  objectDirectory: DirectoryProof;
  objectInfoDirectory: DirectoryProof;
}

interface OptionalFileProof {
  content: string | null;
  identity: FileSystemFileIdentity | null;
}

interface IsolatedCommonProof {
  commonDirectory: DirectoryProof;
  objectDirectory: DirectoryProof;
  objectSentinel: FileSystemFileIdentity;
  refDirectory: DirectoryProof;
  refSentinel: FileSystemFileIdentity;
  resourceDirectory: DirectoryProof;
}

function samePath(left: string, right: string, platform: NodeJS.Platform): boolean {
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function sameDirectoryMetadata(
  left: FileSystemDirectoryMetadata,
  right: FileSystemDirectoryMetadata,
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function sameFileIdentity(left: FileSystemFileIdentity, right: FileSystemFileIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ctimeMs === right.ctimeMs &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function sameOptionalFileProof(left: OptionalFileProof, right: OptionalFileProof): boolean {
  if (left.content !== right.content || (left.identity === null) !== (right.identity === null)) return false;
  return left.identity === null || right.identity === null || sameFileIdentity(left.identity, right.identity);
}

function requireCommit(value: string, label: string): string {
  const commit = value.trim();
  if (!COMMIT_PATTERN.test(commit)) {
    throw new Error(`${label} must be one exact lowercase Git object identity.`);
  }
  return commit;
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
    components.some(
      (component) =>
        component === "" ||
        component.startsWith(".") ||
        component.toLowerCase().endsWith(".lock"),
    )
  ) {
    throw new Error("The configured source branch is not a safe exact Git ref.");
  }
  return value;
}

function nullDevice(platform: NodeJS.Platform): string {
  return platform === "win32" ? "NUL" : "/dev/null";
}

function exactNames(actual: readonly string[], expected: readonly string[], label: string): void {
  const sortedActual = [...actual].sort();
  const sortedExpected = [...expected].sort();
  if (
    sortedActual.length !== sortedExpected.length ||
    sortedActual.some((name, index) => name !== sortedExpected[index])
  ) {
    throw new Error(`${label} has missing or unexpected entries.`);
  }
}

async function proveDirectory(
  fileSystem: HardenedGitFileSystem,
  requestedPath: string,
  expectedCanonicalPath: string,
  platform: NodeJS.Platform,
  label: string,
): Promise<DirectoryProof> {
  const initialMetadata = await fileSystem.directoryMetadata(requestedPath);
  const initialCanonicalPath = await fileSystem.realpath(requestedPath);
  const finalMetadata = await fileSystem.directoryMetadata(requestedPath);
  const finalCanonicalPath = await fileSystem.realpath(requestedPath);
  if (
    !samePath(initialCanonicalPath, expectedCanonicalPath, platform) ||
    !samePath(finalCanonicalPath, expectedCanonicalPath, platform) ||
    !sameDirectoryMetadata(initialMetadata, finalMetadata)
  ) {
    throw new Error(`${label} is symbolic, aliased or changed during canonical inspection.`);
  }
  return { canonicalPath: initialCanonicalPath, metadata: initialMetadata };
}

async function proveIsolatedCommonDirectory(
  request: HardenedGitInspectionRequest,
): Promise<IsolatedCommonProof> {
  const fileSystem = request.dependencies.fileSystem;
  if (!path.isAbsolute(request.bootstrapResources)) {
    throw new Error("Hardened Git inspection requires an absolute bootstrap-resource root.");
  }
  const resourceRoot = path.resolve(request.bootstrapResources);
  const canonicalResourceRoot = await fileSystem.realpath(resourceRoot);
  const resourceDirectory = await proveDirectory(
    fileSystem,
    resourceRoot,
    canonicalResourceRoot,
    request.platform,
    "The packaged bootstrap-resource directory",
  );
  const commonPath = path.join(resourceRoot, "git-common");
  const commonDirectory = await proveDirectory(
    fileSystem,
    commonPath,
    path.join(resourceDirectory.canonicalPath, "git-common"),
    request.platform,
    "The packaged Git common directory",
  );
  exactNames(await fileSystem.listNames(commonPath), ["objects", "refs"], "The packaged Git common directory");

  const objectsPath = path.join(commonPath, "objects");
  const refsPath = path.join(commonPath, "refs");
  const objectDirectory = await proveDirectory(
    fileSystem,
    objectsPath,
    path.join(commonDirectory.canonicalPath, "objects"),
    request.platform,
    "The packaged Git common object directory",
  );
  const refDirectory = await proveDirectory(
    fileSystem,
    refsPath,
    path.join(commonDirectory.canonicalPath, "refs"),
    request.platform,
    "The packaged Git common ref directory",
  );
  exactNames(await fileSystem.listNames(objectsPath), [".flinttrade-empty"], "The packaged Git common object directory");
  exactNames(await fileSystem.listNames(refsPath), [".flinttrade-empty"], "The packaged Git common ref directory");
  const objectSentinelPath = path.join(objectsPath, ".flinttrade-empty");
  const refSentinelPath = path.join(refsPath, ".flinttrade-empty");
  const [objectSentinel, refSentinel, objectContent, refContent] = await Promise.all([
    fileSystem.fileIdentity(objectSentinelPath),
    fileSystem.fileIdentity(refSentinelPath),
    fileSystem.readTextNoFollow(objectSentinelPath),
    fileSystem.readTextNoFollow(refSentinelPath),
  ]);
  if (objectContent !== GIT_COMMON_SENTINEL || refContent !== GIT_REFS_SENTINEL) {
    throw new Error("The packaged Git common directory sentinel content is invalid.");
  }
  return { commonDirectory, objectDirectory, objectSentinel, refDirectory, refSentinel, resourceDirectory };
}

async function proveGitMetadata(request: HardenedGitInspectionRequest): Promise<GitMetadataProof> {
  const fileSystem = request.dependencies.fileSystem;
  const canonicalRoot = await fileSystem.realpath(request.root);
  const checkoutDirectory = await proveDirectory(
    fileSystem,
    request.root,
    canonicalRoot,
    request.platform,
    "The checkout root directory",
  );
  const gitPath = path.join(request.root, ".git");
  const gitDirectory = await proveDirectory(
    fileSystem,
    gitPath,
    path.join(checkoutDirectory.canonicalPath, ".git"),
    request.platform,
    "The checkout .git directory",
  );
  const objectsPath = path.join(gitPath, "objects");
  const infoPath = path.join(gitPath, "info");
  const objectInfoPath = path.join(objectsPath, "info");
  const objectDirectory = await proveDirectory(
    fileSystem,
    objectsPath,
    path.join(gitDirectory.canonicalPath, "objects"),
    request.platform,
    "The checkout Git object directory",
  );
  const infoDirectory = await proveDirectory(
    fileSystem,
    infoPath,
    path.join(gitDirectory.canonicalPath, "info"),
    request.platform,
    "The checkout Git info directory",
  );
  const objectInfoDirectory = await proveDirectory(
    fileSystem,
    objectInfoPath,
    path.join(objectDirectory.canonicalPath, "info"),
    request.platform,
    "The checkout Git object-info directory",
  );
  const [config, head, index, exclude, attributes, alternates] = await Promise.all([
    fileSystem.fileIdentity(path.join(gitPath, "config")),
    fileSystem.fileIdentity(path.join(gitPath, "HEAD")),
    fileSystem.fileIdentity(path.join(gitPath, "index")),
    captureOptionalNoFollowText(fileSystem, path.join(infoPath, "exclude"), "The Git info-exclude file"),
    captureOptionalNoFollowText(fileSystem, path.join(infoPath, "attributes"), "The Git info-attributes file"),
    captureOptionalNoFollowText(fileSystem, path.join(objectInfoPath, "alternates"), "The Git object-alternates file"),
  ]);
  if (alternates.content !== null) {
    throw new Error("The Git checkout contains unsupported alternate object storage.");
  }
  for (const forbidden of [
    [path.join(gitPath, "commondir"), "shared commondir metadata"],
  ] as const) {
    if (await fileSystem.existsNoFollow(forbidden[0])) {
      throw new Error(`The Git checkout contains unsupported ${forbidden[1]}.`);
    }
  }
  return {
    alternates,
    attributes,
    checkoutDirectory,
    config,
    exclude,
    gitDirectory,
    head,
    index,
    infoDirectory,
    objectDirectory,
    objectInfoDirectory,
  };
}

function gitEnvironment(
  request: HardenedGitInspectionRequest,
  commonDirectory: string,
): NodeJS.ProcessEnv {
  const gitDirectory = path.join(request.root, ".git");
  return {
    GIT_ATTR_NOSYSTEM: "1",
    GIT_CEILING_DIRECTORIES: request.root,
    GIT_COMMON_DIR: commonDirectory,
    GIT_CONFIG_GLOBAL: nullDevice(request.platform),
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_SYSTEM: nullDevice(request.platform),
    GIT_INDEX_FILE: path.join(gitDirectory, "index"),
    GIT_NO_REPLACE_OBJECTS: "1",
    GIT_OBJECT_DIRECTORY: path.join(gitDirectory, "objects"),
    GIT_TERMINAL_PROMPT: "0",
  };
}

function hardenedArguments(request: HardenedGitInspectionRequest, args: readonly string[]): string[] {
  const disabledPath = nullDevice(request.platform);
  const posix = request.platform !== "win32";
  return [
    "--no-optional-locks",
    "--no-replace-objects",
    `--git-dir=${path.join(request.root, ".git")}`,
    `--work-tree=${request.root}`,
    "-c",
    "core.bare=false",
    "-c",
    "core.fsmonitor=",
    "-c",
    `core.hooksPath=${disabledPath}`,
    "-c",
    `core.excludesFile=${disabledPath}`,
    "-c",
    `core.attributesFile=${disabledPath}`,
    "-c",
    `core.filemode=${String(posix)}`,
    "-c",
    "core.ignorecase=false",
    "-c",
    `core.symlinks=${String(posix)}`,
    "-c",
    `core.precomposeunicode=${String(request.platform === "darwin")}`,
    "-c",
    "extensions.worktreeConfig=false",
    ...args,
  ];
}

async function runGit(
  request: HardenedGitInspectionRequest,
  commonDirectory: string,
  args: readonly string[],
  timeoutMs: number,
  label: string,
): Promise<CommandResult> {
  let result: CommandResult;
  try {
    result = await request.dependencies.command.run({
      args: hardenedArguments(request, args),
      command: "git",
      cwd: request.root,
      env: gitEnvironment(request, commonDirectory),
      signal: request.signal,
      timeoutMs,
    });
  } catch (error) {
    throw new SourceOperationLeaseRetentionError(
      `${label} rejected without proving command containment.`,
      { cause: error },
    );
  }
  if (!result.contained) {
    throw new SourceOperationLeaseRetentionError(`${label} could not prove command containment.`);
  }
  if (result.stdoutTruncated || result.stderrTruncated) {
    throw new Error(`${label} returned truncated output and cannot be inspected completely.`);
  }
  return result;
}

function requiredGitResult(result: CommandResult, label: string): string {
  if (result.exitCode !== 0) throw new Error(`${label} failed in the isolated Git inspection.`);
  return result.stdout;
}

async function readRawGitConfig(
  request: HardenedGitInspectionRequest,
  configPath: string,
): Promise<string> {
  const cwd = path.dirname(process.execPath);
  let result: CommandResult;
  try {
    result = await request.dependencies.command.run({
      args: [
        "--no-optional-locks",
        "--no-replace-objects",
        `--git-dir=${nullDevice(request.platform)}`,
        "config",
        "--file",
        configPath,
        "--no-includes",
        "--null",
        "--list",
      ],
      command: "git",
      cwd,
      env: {
        GIT_ATTR_NOSYSTEM: "1",
        GIT_CEILING_DIRECTORIES: cwd,
        GIT_CONFIG_GLOBAL: nullDevice(request.platform),
        GIT_CONFIG_NOSYSTEM: "1",
        GIT_CONFIG_SYSTEM: nullDevice(request.platform),
        GIT_NO_REPLACE_OBJECTS: "1",
        GIT_TERMINAL_PROMPT: "0",
      },
      signal: request.signal,
      timeoutMs: 15_000,
    });
  } catch (error) {
    throw new SourceOperationLeaseRetentionError(
      "Git source config inspection rejected without proving command containment.",
      { cause: error },
    );
  }
  if (!result.contained) {
    throw new SourceOperationLeaseRetentionError(
      "Git source config inspection could not prove command containment.",
    );
  }
  if (result.stdoutTruncated || result.stderrTruncated) {
    throw new Error("Git source config inspection returned truncated output.");
  }
  return requiredGitResult(result, "Git source config inspection");
}

function parseRawGitConfig(stdout: string): Map<string, string[]> {
  if (stdout !== "" && !stdout.endsWith("\0")) {
    throw new Error("Git source config inspection returned a truncated record.");
  }
  const entries = new Map<string, string[]>();
  for (const record of stdout.split("\0").slice(0, -1)) {
    const separator = record.indexOf("\n");
    if (separator <= 0) throw new Error("Git source config inspection returned an invalid record.");
    const key = record.slice(0, separator).toLowerCase();
    const values = entries.get(key) ?? [];
    values.push(record.slice(separator + 1));
    entries.set(key, values);
  }
  return entries;
}

function assertExactConfigValue(entries: Map<string, string[]>, key: string, expected: string): void {
  const values = entries.get(key);
  if (values?.length !== 1 || values[0] !== expected) {
    throw new Error(`The Git checkout has an inexact ${key} setting.`);
  }
}

function assertOptionalBooleanConfig(entries: Map<string, string[]>, key: string): void {
  const values = entries.get(key);
  if (values && (values.length !== 1 || !["true", "false"].includes(values[0]!))) {
    throw new Error(`The Git checkout has an inexact ${key} setting.`);
  }
}

function assertManagedGitConfig(
  entries: Map<string, string[]>,
  request: HardenedGitInspectionRequest,
): void {
  const branch = safeBranch(request.expected.branch);
  const branchKey = branch.toLowerCase();
  const allowed = new Set([
    "core.bare",
    "core.filemode",
    "core.ignorecase",
    "core.logallrefupdates",
    "core.precomposeunicode",
    "core.repositoryformatversion",
    "core.symlinks",
    `branch.${branchKey}.merge`,
    `branch.${branchKey}.remote`,
    "remote.origin.fetch",
    "remote.origin.tagopt",
    "remote.origin.url",
  ]);
  for (const key of entries.keys()) {
    if (!allowed.has(key)) {
      throw new Error("The Git checkout contains unexpected or executable local configuration.");
    }
  }
  assertExactConfigValue(entries, "core.repositoryformatversion", "0");
  assertExactConfigValue(entries, "core.filemode", String(request.platform !== "win32"));
  assertExactConfigValue(entries, "core.bare", "false");
  assertExactConfigValue(entries, "core.logallrefupdates", "true");
  assertOptionalBooleanConfig(entries, "core.ignorecase");
  assertOptionalBooleanConfig(entries, "core.precomposeunicode");
  assertOptionalBooleanConfig(entries, "core.symlinks");
  assertExactConfigValue(entries, "remote.origin.url", request.expected.origin);
  assertExactConfigValue(
    entries,
    "remote.origin.fetch",
    `+refs/heads/${branch}:refs/remotes/origin/${branch}`,
  );
  assertExactConfigValue(entries, "remote.origin.tagopt", "--no-tags");
  assertExactConfigValue(entries, `branch.${branchKey}.remote`, "origin");
  assertExactConfigValue(entries, `branch.${branchKey}.merge`, `refs/heads/${branch}`);
}

function assertNoHiddenIndexFlags(stdout: string): void {
  if (stdout !== "" && !stdout.endsWith("\0")) {
    throw new Error("Git index flag inspection returned a truncated record.");
  }
  if (stdout.split("\0").slice(0, -1).some((record) => !record.startsWith("H "))) {
    throw new Error("The Git index contains hidden or nonstandard tracked-file flags.");
  }
}

function assertNoActiveGitInfoRules(content: string, kind: "attributes" | "exclude"): void {
  if (!SAFE_GIT_TEXT_PATTERN.test(content)) {
    throw new Error(`The Git info-${kind} file contains non-ASCII or invalid text.`);
  }
  if (content.split(/\r?\n/).some((line) => line.trim() !== "" && !line.trimStart().startsWith("#"))) {
    const risk = kind === "exclude"
      ? "hide untracked source files"
      : "change source conversions outside the committed tree";
    throw new Error(`The Git info-${kind} file contains rules that can ${risk}.`);
  }
}

async function captureOptionalNoFollowText(
  fileSystem: HardenedGitFileSystem,
  target: string,
  label: string,
): Promise<OptionalFileProof> {
  if (!(await fileSystem.existsNoFollow(target))) return { content: null, identity: null };
  const initialIdentity = await fileSystem.fileIdentity(target);
  if (initialIdentity.size > MAX_GIT_INFO_BYTES) {
    throw new Error(`${label} is oversized.`);
  }
  const content = await fileSystem.readTextNoFollow(target);
  const finalIdentity = await fileSystem.fileIdentity(target);
  if (
    !sameFileIdentity(initialIdentity, finalIdentity) ||
    Buffer.byteLength(content, "utf8") !== initialIdentity.size
  ) {
    throw new Error(`${label} changed during no-follow inspection.`);
  }
  return { content, identity: initialIdentity };
}

async function assertStableGitMetadata(
  request: HardenedGitInspectionRequest,
  initial: GitMetadataProof,
): Promise<void> {
  const current = await proveGitMetadata(request);
  if (
    !samePath(initial.checkoutDirectory.canonicalPath, current.checkoutDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.checkoutDirectory.metadata, current.checkoutDirectory.metadata) ||
    !samePath(initial.gitDirectory.canonicalPath, current.gitDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.gitDirectory.metadata, current.gitDirectory.metadata) ||
    !samePath(initial.objectDirectory.canonicalPath, current.objectDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.objectDirectory.metadata, current.objectDirectory.metadata) ||
    !samePath(initial.infoDirectory.canonicalPath, current.infoDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.infoDirectory.metadata, current.infoDirectory.metadata) ||
    !samePath(initial.objectInfoDirectory.canonicalPath, current.objectInfoDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.objectInfoDirectory.metadata, current.objectInfoDirectory.metadata) ||
    !sameFileIdentity(initial.config, current.config) ||
    !sameFileIdentity(initial.head, current.head) ||
    !sameFileIdentity(initial.index, current.index) ||
    !sameOptionalFileProof(initial.exclude, current.exclude) ||
    !sameOptionalFileProof(initial.attributes, current.attributes) ||
    !sameOptionalFileProof(initial.alternates, current.alternates)
  ) {
    throw new Error("The Git metadata identity changed during hardened inspection.");
  }
}

async function assertStableCommonDirectory(
  request: HardenedGitInspectionRequest,
  initial: IsolatedCommonProof,
): Promise<void> {
  const current = await proveIsolatedCommonDirectory(request);
  if (
    !samePath(initial.resourceDirectory.canonicalPath, current.resourceDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.resourceDirectory.metadata, current.resourceDirectory.metadata) ||
    !samePath(initial.commonDirectory.canonicalPath, current.commonDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.commonDirectory.metadata, current.commonDirectory.metadata) ||
    !samePath(initial.objectDirectory.canonicalPath, current.objectDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.objectDirectory.metadata, current.objectDirectory.metadata) ||
    !samePath(initial.refDirectory.canonicalPath, current.refDirectory.canonicalPath, request.platform) ||
    !sameDirectoryMetadata(initial.refDirectory.metadata, current.refDirectory.metadata) ||
    !sameFileIdentity(initial.objectSentinel, current.objectSentinel) ||
    !sameFileIdentity(initial.refSentinel, current.refSentinel)
  ) {
    throw new Error("The packaged Git common-directory identity changed during inspection.");
  }
}

export async function inspectHardenedGitCheckout(
  request: HardenedGitInspectionRequest,
): Promise<HardenedGitIdentity> {
  if (!path.isAbsolute(request.root)) throw new Error("Hardened Git inspection requires an absolute checkout root.");
  safeBranch(request.expected.branch);
  const expectedRevision = request.expected.revision
    ? requireCommit(request.expected.revision, "The expected Git revision")
    : null;
  const expectedTree = request.expected.tree
    ? requireCommit(request.expected.tree, "The expected Git tree")
    : null;
  if (expectedTree && !expectedRevision) {
    throw new Error("An expected Git tree requires an explicit expected revision.");
  }

  const common = await proveIsolatedCommonDirectory(request);
  const metadata = await proveGitMetadata(request);
  const gitDirectory = path.join(request.root, ".git");
  const configPath = path.join(gitDirectory, "config");
  const configContent = await request.dependencies.fileSystem.readTextNoFollow(configPath);
  if (Buffer.byteLength(configContent) > MAX_GIT_CONFIG_BYTES || !SAFE_GIT_TEXT_PATTERN.test(configContent)) {
    throw new Error("The Git checkout has an oversized or non-ASCII local configuration.");
  }
  assertManagedGitConfig(parseRawGitConfig(await readRawGitConfig(request, configPath)), request);
  if ((await request.dependencies.fileSystem.readTextNoFollow(configPath)) !== configContent) {
    throw new Error("The Git local configuration changed during no-follow inspection.");
  }

  const excludeContent = metadata.exclude.content;
  const attributesContent = metadata.attributes.content;
  if (excludeContent !== null) assertNoActiveGitInfoRules(excludeContent, "exclude");
  if (attributesContent !== null) assertNoActiveGitInfoRules(attributesContent, "attributes");

  const headResult = await runGit(request, common.commonDirectory.canonicalPath, ["rev-parse", "HEAD"], 15_000, "Git HEAD inspection");
  const revision = requireCommit(requiredGitResult(headResult, "Git HEAD inspection"), "Git HEAD");
  if (expectedRevision && revision !== expectedRevision) {
    throw new Error("The Git HEAD does not match the explicit expected revision.");
  }
  const selectedRevision = expectedRevision ?? revision;
  const headBindingRequest = {
    branch: request.expected.branch,
    fileSystem: request.dependencies.fileSystem,
    gitPath: metadata.gitDirectory.canonicalPath,
    platform: request.platform,
    selectedRevision,
  };
  const headBinding = await captureGitHeadBinding(headBindingRequest);
  const treeResult = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["rev-parse", `${selectedRevision}^{tree}`],
    15_000,
    "Git tree inspection",
  );
  const tree = requireCommit(requiredGitResult(treeResult, "Git tree inspection"), "The Git source tree");
  if (expectedTree && tree !== expectedTree) {
    throw new Error("The Git source tree does not match the explicit expected content identity.");
  }

  const indexFlags = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["ls-files", "-v", "-z"],
    15_000,
    "Git index flag inspection",
  );
  assertNoHiddenIndexFlags(requiredGitResult(indexFlags, "Git index flag inspection"));

  const staged = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["diff-index", "--cached", "--quiet", "--ignore-submodules=none", selectedRevision, "--"],
    30_000,
    "Git staged-content inspection",
  );
  if (staged.exitCode === 1) throw new Error("The Git checkout has staged changes.");
  requiredGitResult(staged, "Git staged-content inspection");

  // `diff-files --quiet` reports a stat-cache mismatch without proving that
  // tracked content differs. Porcelain status refreshes that comparison in
  // memory under `--no-optional-locks`; because it renders no patch, it does
  // not invoke external diff or textconv drivers. Untracked inputs remain a
  // separate bounded inspection below.
  const tracked = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["status", "--porcelain=v2", "-z", "--untracked-files=no", "--ignore-submodules=none"],
    30_000,
    "Git tracked-content inspection",
  );
  if (requiredGitResult(tracked, "Git tracked-content inspection") !== "") {
    throw new Error("The Git checkout has tracked worktree changes.");
  }

  const untracked = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["ls-files", "--others", "--exclude-standard", "-z"],
    30_000,
    "Git untracked-content inspection",
  );
  if (requiredGitResult(untracked, "Git untracked-content inspection") !== "") {
    throw new Error("The Git checkout has nonignored untracked source files.");
  }

  // Object alternates can redirect only content-addressed object reads; they
  // cannot execute a process. Replacement refs and every configuration,
  // attributes, excludes and hooks surface are independently disabled. The
  // active object directory and alternates absence are nevertheless reproved
  // to reject a concurrent metadata mutation.
  await assertStableGitMetadata(request, metadata);
  await assertStableCommonDirectory(request, common);
  if ((await request.dependencies.fileSystem.readTextNoFollow(configPath)) !== configContent) {
    throw new Error("The Git local configuration changed during hardened inspection.");
  }
  await assertGitHeadBindingStable(headBindingRequest, headBinding);
  const finalHeadResult = await runGit(
    request,
    common.commonDirectory.canonicalPath,
    ["rev-parse", "HEAD"],
    15_000,
    "Final Git HEAD inspection",
  );
  const finalRevision = requireCommit(
    requiredGitResult(finalHeadResult, "Final Git HEAD inspection"),
    "The final Git HEAD",
  );
  if (finalRevision !== selectedRevision) {
    throw new Error("The Git HEAD changed during hardened inspection.");
  }
  await assertGitHeadBindingStable(headBindingRequest, headBinding);
  await assertStableGitMetadata(request, metadata);
  await assertStableCommonDirectory(request, common);
  return { revision: selectedRevision, tree };
}
