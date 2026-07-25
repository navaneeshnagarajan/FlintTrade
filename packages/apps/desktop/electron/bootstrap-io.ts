import { execFileSync, spawn } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import {
  chmodSync,
  close as closeFd,
  closeSync,
  constants,
  createReadStream,
  createWriteStream,
  fchmodSync,
  fstat as fstatFd,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdtempSync,
  open as openFd,
  openSync,
  readSync,
  readFileSync,
  realpathSync,
  rmdirSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import {
  access,
  chmod,
  type FileHandle,
  link,
  lstat,
  mkdtemp,
  mkdir,
  open,
  readFile,
  readdir,
  readlink,
  realpath,
  rename,
  rmdir,
  rm,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import https from "node:https";
import type { IncomingMessage } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

import * as tar from "tar";
import * as yauzl from "yauzl";

import type {
  BootstrapDependencies,
  CommandInvocation,
  CommandResult,
  DownloadPolicy,
  DownloadReceipt,
  FileSystemDirectoryMetadata,
  FileSystemIdentity,
  FileSystemFileIdentity,
  OperationLeaseRequest,
  SourceTreeEntry,
  SourceTreeIdentity,
  TemporaryDirectoryReservation,
  TextDownloadReceipt,
} from "./bootstrap";

const OUTPUT_LIMIT = 256 * 1024;
const TEXT_DOWNLOAD_LIMIT = 1024 * 1024;
const ARCHIVE_LIMITS = Object.freeze({
  compressedBytes: 512 * 1024 * 1024,
  entries: 50_000,
  expandedBytes: 1024 * 1024 * 1024,
  listingBytes: 16 * 1024 * 1024,
  nameBytes: 512,
  singleFileBytes: 256 * 1024 * 1024,
});

export interface BootIdentityDependencies {
  environment: NodeJS.ProcessEnv;
  readTextFile(target: string): string;
  runFile(command: string, args: readonly string[]): string;
}

const NODE_BOOT_IDENTITY_DEPENDENCIES: BootIdentityDependencies = {
  environment: process.env,
  readTextFile: (target) => readFileSync(target, "utf8"),
  runFile: (command, args) => execFileSync(command, [...args], {
    encoding: "utf8",
    maxBuffer: 4096,
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 15_000,
    windowsHide: true,
  }),
};

function unavailableBootIdentity(platform: NodeJS.Platform, cause?: unknown): Error {
  return new Error(`Authoritative ${platform} boot-session identity is unavailable.`, {
    ...(cause === undefined ? {} : { cause }),
  });
}

/** Return one kernel-owned identity that remains constant for the complete OS boot. */
export function currentBootIdentity(
  platform: NodeJS.Platform = process.platform,
  dependencies: BootIdentityDependencies = NODE_BOOT_IDENTITY_DEPENDENCIES,
): string {
  try {
    if (platform === "linux") {
      const bootId = dependencies.readTextFile("/proc/sys/kernel/random/boot_id").trim();
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(bootId)) {
        throw unavailableBootIdentity(platform);
      }
      return `linux:${bootId.toLowerCase()}`;
    }

    if (platform === "darwin") {
      const bootId = dependencies.runFile("/usr/sbin/sysctl", ["-n", "kern.bootsessionuuid"]).trim();
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(bootId)) {
        throw unavailableBootIdentity(platform);
      }
      return `darwin:${bootId.toLowerCase()}`;
    }

    if (platform === "win32") {
      const windowsRoot = dependencies.environment.SystemRoot ?? dependencies.environment.WINDIR ?? "";
      if (windowsRoot.trim() !== windowsRoot || !path.win32.isAbsolute(windowsRoot)) {
        throw unavailableBootIdentity(platform);
      }
      const powershell = path.win32.join(
        windowsRoot,
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
      );
      const command = [
        "$boot = (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime",
        "if ($null -eq $boot) { throw 'boot-time-unavailable' }",
        "[Console]::Out.Write($boot.ToFileTimeUtc().ToString([Globalization.CultureInfo]::InvariantCulture))",
      ].join("; ");
      const fileTime = dependencies.runFile(
        powershell,
        ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
      ).trim();
      if (!/^[1-9][0-9]{15,19}$/.test(fileTime) || BigInt(fileTime) > 9_223_372_036_854_775_807n) {
        throw unavailableBootIdentity(platform);
      }
      return `win32:${fileTime}`;
    }

    throw unavailableBootIdentity(platform);
  } catch (error) {
    throw unavailableBootIdentity(platform, error);
  }
}

const CHILD_ENVIRONMENT_KEYS = new Set([
  "ALL_PROXY",
  "COMSPEC",
  "HOME",
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "NODE_EXTRA_CA_CERTS",
  "NO_PROXY",
  "PATH",
  "PATHEXT",
  "SSL_CERT_DIR",
  "SSL_CERT_FILE",
  "SystemRoot",
  "TEMP",
  "TMP",
  "TMPDIR",
  "USERPROFILE",
  "WINDIR",
  "all_proxy",
  "http_proxy",
  "https_proxy",
  "no_proxy",
]);
const BOOTSTRAP_ENVIRONMENT_KEYS = new Set([
  "COREPACK_DEFAULT_TO_LATEST",
  "COREPACK_HOME",
  "FLINTTRADE_DESKTOP",
  "FLINTTRADE_FRONTEND_DIST",
  "FLINTTRADE_HOME",
  "FLINTTRADE_BOOTSTRAP_COREPACK_JS",
  "FLINTTRADE_BOOTSTRAP_NODE",
  "FLINTTRADE_BOOTSTRAP_PNPM_VERSION",
  "FLINTTRADE_BOOTSTRAP_TOOLS_ROOT",
  "FLINTTRADE_BOOTSTRAP_UV",
  "FLINTTRADE_WORKSPACE_DIR",
  "GIT_CEILING_DIRECTORIES",
  "GIT_ATTR_NOSYSTEM",
  "GIT_COMMON_DIR",
  "GIT_CONFIG_NOSYSTEM",
  "GIT_CONFIG_GLOBAL",
  "GIT_CONFIG_SYSTEM",
  "GIT_INDEX_FILE",
  "GIT_NO_REPLACE_OBJECTS",
  "GIT_OBJECT_DIRECTORY",
  "GIT_TERMINAL_PROMPT",
  "NPM_CONFIG_CACHE",
  "NPM_CONFIG_USERCONFIG",
  "PNPM_HOME",
  "PYTHONNOUSERSITE",
  "UV_CONFIG_FILE",
  "UV_CACHE_DIR",
  "UV_NO_EDITABLE",
  "UV_PYTHON",
  "UV_PYTHON_INSTALL_DIR",
  "XDG_CACHE_HOME",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
]);

const WINDOWS_CHILD_ENVIRONMENT_CANONICAL = new Map(
  [...CHILD_ENVIRONMENT_KEYS].map((key) => [key.toLowerCase(), key]),
);
const WINDOWS_OVERRIDE_ENVIRONMENT_CANONICAL = new Map(
  [...CHILD_ENVIRONMENT_KEYS, ...BOOTSTRAP_ENVIRONMENT_KEYS].map((key) => [key.toLowerCase(), key]),
);

function abortError(): DOMException {
  return new DOMException("Operation cancelled.", "AbortError");
}

function appendBounded(current: string, chunk: string): { text: string; truncated: boolean } {
  const combined = current + chunk;
  return combined.length <= OUTPUT_LIMIT
    ? { text: combined, truncated: false }
    : { text: combined.slice(-OUTPUT_LIMIT), truncated: true };
}

function emitLines(
  buffer: string,
  chunk: string,
  stream: "stdout" | "stderr",
  listener?: CommandInvocation["onOutput"],
): string {
  let pending = buffer + chunk;
  let newline = pending.indexOf("\n");
  while (newline >= 0) {
    const line = pending.slice(0, newline).replace(/\r$/, "");
    if (line) listener?.(line, stream);
    pending = pending.slice(newline + 1);
    newline = pending.indexOf("\n");
  }
  return pending.length <= OUTPUT_LIMIT ? pending : pending.slice(-OUTPUT_LIMIT);
}

export function minimalChildEnvironment(
  overrides: NodeJS.ProcessEnv = {},
  inherited: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {};
  if (platform === "win32") {
    const copy = (
      source: NodeJS.ProcessEnv,
      allowed: ReadonlyMap<string, string>,
      replace: boolean,
    ): void => {
      for (const [key, value] of Object.entries(source)) {
        if (value === undefined) continue;
        const canonical = allowed.get(key.toLowerCase());
        if (!canonical) continue;
        if (replace || result[canonical] === undefined || key === canonical) result[canonical] = value;
      }
    };
    copy(inherited, WINDOWS_CHILD_ENVIRONMENT_CANONICAL, false);
    copy(overrides, WINDOWS_OVERRIDE_ENVIRONMENT_CANONICAL, true);
    return result;
  }
  for (const [key, value] of Object.entries(inherited)) {
    if (value !== undefined && CHILD_ENVIRONMENT_KEYS.has(key)) result[key] = value;
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined && (CHILD_ENVIRONMENT_KEYS.has(key) || BOOTSTRAP_ENVIRONMENT_KEYS.has(key))) {
      result[key] = value;
    }
  }
  return result;
}

const delay = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForPosixProcessGroupExit(processGroupId: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (posixProcessGroupExists(processGroupId)) {
    if (Date.now() >= deadline) return false;
    await delay(20);
  }
  return true;
}

interface BootstrapIoOptions {
  atomicPromotion?: {
    expectedHelperSha256: string;
    helper: string;
    protocol: "posix" | "windows-source-fs";
  };
  canonicalisePath?: (target: string) => string;
  environment?: NodeJS.ProcessEnv;
  fileExists?: (target: string) => boolean;
  posixProcessEnumerators?: readonly string[];
  probeExecutable?: (command: string, args: string[]) => boolean;
  testHooks?: {
    appendWriteChunkBytes?: number;
    archiveSnapshotWriteChunkBytes?: number;
    beforeAppendOpen?: (target: string) => void;
    beforeAppendParentSync?: (target: string) => void;
    beforeArchiveSnapshotSetup?: (
      stage: "destination-open" | "directory-create" | "directory-inspect",
    ) => void;
    beforeArchiveSnapshotVerify?: (target: string) => void;
    beforeAtomicPromotion?: (source: string, destination: string) => Promise<void> | void;
    afterAtomicPromotionModulePinned?: (target: string) => void;
    beforeDurableDirectorySync?: (target: string, kind: "directory" | "parent") => void;
    beforeDownloadTemporaryOpen?: (target: string) => void;
    afterTemporaryDirectoryCreated?: (target: string) => void;
    beforeLeaseReleaseStage?: (
      stage: "directory-remove" | "directory-sync" | "owner-unlink" | "parent-sync",
    ) => void;
    beforeProcessAnchorReleaseStage?: (stage: "directory-sync" | "record-unlink") => void;
    onDownloadTemporaryLifecycle?: (
      event: "before-remove" | "handle-closed" | "handle-opened",
    ) => Promise<void> | void;
    onArchiveSnapshotRemove?: (target: string, directory: string) => void;
    onArchiveEntry?: (index: number, kind: "tar.gz" | "zip") => void;
    onLeaseOwnerPublication?: (
      stage: "after-open" | "after-write" | "before-open",
      bytesWritten: number,
    ) => Promise<void> | void;
    onPreLeaseCommandScope?: (operationLeaseTarget: string | undefined) => void;
    onZipSnapshotHandle?: (event: "closed" | "opened") => void;
    downloadWriteChunkBytes?: number;
    leaseOwnerWriteChunkBytes?: number;
    recordedProcessWaitMs?: number;
    inspectTrustedGit?: (target: string, platform: NodeJS.Platform) => TrustedExecutableSnapshot | null;
    testAtomicPromote?: (
      source: string,
      destination: string,
      identity: FileSystemIdentity,
    ) => Promise<void>;
    testNativeDirectoryIdentity?: (target: string, identity: FileSystemIdentity) => Promise<string>;
    temporaryDirectoryId?: () => string;
  };
  trustedGitCandidates?: readonly string[];
  operationLeaseTarget?: string;
  windowsJobSupervisor?: string;
}

export interface TrustedExecutableSnapshot {
  canonicalPath: string;
  ctimeMs: number;
  dev: number;
  ino: number;
  mode: number;
  mtimeMs: number;
  size: number;
}

const WINDOWS_SUPERVISOR_PREFIX = "FLINTTRADE_JOB_SUPERVISOR";
const WINDOWS_SUPERVISOR_TOKEN = /^[0-9a-f]{32}$/;
type WindowsSupervisorStopReason = "cancel" | "listener" | "shutdown" | "timeout";

async function writeBufferCompletely(
  handle: FileHandle,
  value: Buffer,
  chunkLimit = Math.max(value.length, 1),
  onProgress?: (bytesWritten: number) => Promise<void> | void,
): Promise<void> {
  if (!Number.isSafeInteger(chunkLimit) || chunkLimit <= 0) {
    throw new Error("Durable file write chunk must be a positive safe integer.");
  }
  let offset = 0;
  while (offset < value.length) {
    const requested = Math.min(chunkLimit, value.length - offset);
    const { bytesWritten } = await handle.write(value, offset, requested, null);
    if (bytesWritten <= 0 || bytesWritten > requested) {
      throw new Error("Durable file write did not complete a valid write.");
    }
    offset += bytesWritten;
    await onProgress?.(offset);
  }
}

export function buildWindowsSupervisorInvocation(input: {
  args: readonly string[];
  cwd?: string;
  expectedTargetSha256?: string;
  helper: string;
  parentPid: number;
  target: string;
  token: string;
}): { args: string[]; command: string } {
  if (!path.win32.isAbsolute(input.helper) || path.win32.extname(input.helper).toLowerCase() !== ".exe") {
    throw new Error("Windows Job supervisor must be an absolute executable path.");
  }
  if (!path.win32.isAbsolute(input.target) || path.win32.extname(input.target).toLowerCase() !== ".exe") {
    throw new Error("Windows bootstrap target must be an absolute executable path.");
  }
  if (input.cwd && !path.win32.isAbsolute(input.cwd)) {
    throw new Error("Windows bootstrap working directory must be absolute.");
  }
  if (input.expectedTargetSha256 !== undefined && !/^[0-9a-f]{64}$/.test(input.expectedTargetSha256)) {
    throw new Error("Windows bootstrap target SHA-256 must be a lowercase digest.");
  }
  if (!WINDOWS_SUPERVISOR_TOKEN.test(input.token) || !Number.isSafeInteger(input.parentPid) || input.parentPid <= 0) {
    throw new Error("Windows Job supervisor identity is invalid.");
  }
  return {
    args: [
      "--protocol",
      "1",
      "--token",
      input.token,
      "--parent-pid",
      String(input.parentPid),
      ...(input.cwd ? ["--cwd", input.cwd] : []),
      ...(input.expectedTargetSha256 ? ["--target-sha256", input.expectedTargetSha256] : []),
      "--",
      input.target,
      ...input.args,
    ],
    command: input.helper,
  };
}

export function windowsSupervisorControlLine(token: string, reason: WindowsSupervisorStopReason): string {
  if (!WINDOWS_SUPERVISOR_TOKEN.test(token)) throw new Error("Windows Job supervisor token is invalid.");
  return `FLINTTRADE_JOB_TERMINATE\t1\t${token}\t${reason}\n`;
}

function windowsSupervisorStartLine(token: string): string {
  if (!WINDOWS_SUPERVISOR_TOKEN.test(token)) throw new Error("Windows Job supervisor token is invalid.");
  return `FLINTTRADE_JOB_START\t1\t${token}\n`;
}

function windowsSupervisorReleaseLine(token: string): string {
  if (!WINDOWS_SUPERVISOR_TOKEN.test(token)) throw new Error("Windows Job supervisor token is invalid.");
  return `FLINTTRADE_JOB_RELEASE\t1\t${token}\n`;
}

function hasWindowsSupervisorSettledProof(stderr: string, token: string, stderrTruncated: boolean): boolean {
  if (stderrTruncated) return false;
  const protocolLines = stderr
    .replaceAll("\r\n", "\n")
    .split("\n")
    .filter((line) => line.startsWith(`${WINDOWS_SUPERVISOR_PREFIX}\t`));
  if (protocolLines.length !== 1) return false;
  const fields = protocolLines[0]!.split("\t");
  const leaderExit = Number(fields[5]);
  return (
    fields.length === 7 &&
    fields[0] === WINDOWS_SUPERVISOR_PREFIX &&
    fields[1] === "1" &&
    fields[2] === token &&
    fields[3] === "settled" &&
    fields[6] === "0" &&
    Number.isSafeInteger(leaderExit) &&
    leaderExit >= 0 &&
    leaderExit <= 0xffff_ffff
  );
}

async function writeControlLine(
  control: NodeJS.WritableStream,
  line: string,
  end = false,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error) => reject(error);
    control.once("error", onError);
    const complete = () => {
      control.removeListener("error", onError);
      resolve();
    };
    if (end && "end" in control && typeof control.end === "function") control.end(line, complete);
    else if ("write" in control && typeof control.write === "function") control.write(line, complete);
    else reject(new Error("Bootstrap process control pipe is not writable."));
  });
}

export function parseWindowsSupervisorProof(
  stderr: string,
  token: string,
  helperExitCode: number | null,
  stderrTruncated: boolean,
): { contained: boolean; exitCode: number; stderr: string } {
  if (stderrTruncated) {
    return { contained: false, exitCode: 1, stderr: "Windows containment proof output was truncated." };
  }
  const lines = stderr.replaceAll("\r\n", "\n").split("\n");
  const protocolIndexes = lines.flatMap((line, index) => (line.startsWith(`${WINDOWS_SUPERVISOR_PREFIX}\t`) ? [index] : []));
  const filtered = lines.filter((_line, index) => !protocolIndexes.includes(index));
  const ordinaryStderr = filtered.join("\n").replace(/\n{2,}$/, "\n");
  let finalNonEmpty = -1;
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (lines[index]!.length > 0) {
      finalNonEmpty = index;
      break;
    }
  }
  if (protocolIndexes.length !== 1 || protocolIndexes[0] !== finalNonEmpty || !WINDOWS_SUPERVISOR_TOKEN.test(token)) {
    return { contained: false, exitCode: 1, stderr: ordinaryStderr };
  }
  const fields = lines[protocolIndexes[0]!]!.split("\t");
  const leaderExit = Number(fields[5]);
  if (
    fields.length !== 7 ||
    fields[0] !== WINDOWS_SUPERVISOR_PREFIX ||
    fields[1] !== "1" ||
    fields[2] !== token ||
    fields[3] !== "settled" ||
    fields[6] !== "0" ||
    !Number.isSafeInteger(leaderExit) ||
    leaderExit < 0 ||
    leaderExit > 0xffff_ffff
  ) {
    return { contained: false, exitCode: 1, stderr: ordinaryStderr };
  }
  const reason = fields[4];
  const expectedExit =
    reason === "natural"
      ? leaderExit
      : reason === "orphan-drained"
        ? leaderExit === 0
          ? 1
          : leaderExit
        : reason === "timeout"
          ? 124
          : reason === "listener" || reason === "control-error"
            ? 1
            : reason === "setup-failed"
              ? 127
              : reason === "cancel" || reason === "shutdown" || reason === "parent-lost"
                ? 130
                : null;
  if (expectedExit === null || helperExitCode !== expectedExit) {
    return { contained: false, exitCode: 1, stderr: ordinaryStderr };
  }
  return { contained: true, exitCode: expectedExit, stderr: ordinaryStderr };
}

export function applyWindowsSupervisorLocalState(
  proof: { contained: boolean; exitCode: number; stderr: string },
  local: { cancelled: boolean; listenerFailure: boolean; timedOut: boolean },
): { contained: boolean; exitCode: number; stderr: string } {
  return {
    ...proof,
    exitCode: local.listenerFailure ? 1 : local.timedOut ? 124 : local.cancelled ? 130 : proof.exitCode,
  };
}

function noFollowRegularFile(target: string): boolean {
  try {
    const metadata = lstatSync(target);
    return metadata.isFile() && !metadata.isSymbolicLink();
  } catch {
    return false;
  }
}

async function readNoFollowRegularText(target: string): Promise<string> {
  const before = await lstat(target);
  if (before.isSymbolicLink() || !before.isFile()) {
    throw new Error("Trusted bootstrap metadata must be a no-follow regular file.");
  }
  const handle = await open(target, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || opened.dev !== before.dev || opened.ino !== before.ino) {
      throw new Error("Trusted bootstrap metadata identity changed before open.");
    }
    const content = await handle.readFile("utf8");
    const [afterHandle, afterPath] = await Promise.all([handle.stat(), lstat(target)]);
    if (
      afterPath.isSymbolicLink() ||
      !afterPath.isFile() ||
      afterPath.dev !== opened.dev ||
      afterPath.ino !== opened.ino ||
      afterHandle.dev !== opened.dev ||
      afterHandle.ino !== opened.ino ||
      afterHandle.size !== opened.size ||
      afterHandle.mtimeMs !== opened.mtimeMs ||
      afterHandle.ctimeMs !== opened.ctimeMs
    ) {
      throw new Error("Trusted bootstrap metadata changed while it was read.");
    }
    return content;
  } finally {
    await handle.close();
  }
}

async function writeTextAbsent(target: string, content: string): Promise<void> {
  const parent = path.dirname(target);
  const parentMetadata = await lstat(parent);
  if (parentMetadata.isSymbolicLink() || !parentMetadata.isDirectory()) {
    throw new Error("Exclusive bootstrap file parent must be a no-follow directory.");
  }
  const canonicalParent = await realpath(parent);
  const handle = await open(
    target,
    constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
    0o600,
  );
  try {
    const opened = await handle.stat();
    if (!opened.isFile()) throw new Error("Exclusive bootstrap file was not a regular file.");
    await writeBufferCompletely(handle, Buffer.from(content, "utf8"));
    await handle.chmod(0o600);
    await handle.sync();
    const pathname = await lstat(target);
    if (
      pathname.isSymbolicLink() ||
      !pathname.isFile() ||
      pathname.dev !== opened.dev ||
      pathname.ino !== opened.ino ||
      (await realpath(path.dirname(target))) !== canonicalParent
    ) {
      throw new Error("Exclusive bootstrap file identity changed before settlement.");
    }
    await syncDirectoryForDurability(canonicalParent);
  } finally {
    await handle.close();
  }
}

export function resolveWindowsExecutable(
  command: string,
  environment: NodeJS.ProcessEnv,
  fileExists: (target: string) => boolean = noFollowRegularFile,
  canonicalise: (target: string) => string = (target) => realpathSync.native(target),
): string | null {
  const extension = path.win32.extname(command).toLowerCase();
  if (path.win32.isAbsolute(command)) {
    if (extension !== ".exe" || !fileExists(command)) return null;
    try {
      const canonical = canonicalise(command);
      return path.win32.isAbsolute(canonical) && fileExists(canonical) ? canonical : null;
    } catch {
      return null;
    }
  }
  if (command.includes("/") || command.includes("\\") || (extension && extension !== ".exe")) return null;
  const inheritedPath = Object.entries(environment).find(([key]) => key.toLowerCase() === "path")?.[1];
  if (!inheritedPath) return null;
  const executable = extension ? command : `${command}.exe`;
  for (const directory of inheritedPath.split(path.win32.delimiter)) {
    if (!directory || !path.win32.isAbsolute(directory)) continue;
    const candidate = path.win32.join(directory, executable);
    if (fileExists(candidate)) {
      try {
        const canonical = canonicalise(candidate);
        if (path.win32.isAbsolute(canonical) && fileExists(canonical)) return canonical;
      } catch {
        return null;
      }
    }
  }
  return null;
}

function trustedWindowsLauncher(
  environment: NodeJS.ProcessEnv,
  relative: string[],
  fileExists: (target: string) => boolean,
): string | null {
  const systemRoot = environment.SystemRoot ?? environment.SYSTEMROOT ?? environment.WINDIR;
  if (!systemRoot || !path.win32.isAbsolute(systemRoot)) return null;
  const candidate = path.win32.join(systemRoot, ...relative);
  if (!fileExists(candidate)) return null;
  return candidate;
}

export function resolveTrustedWindowsPowerShell(
  environment: NodeJS.ProcessEnv = process.env,
  fileExists: (target: string) => boolean = (target) => {
    try {
      const metadata = lstatSync(target);
      return metadata.isFile() && !metadata.isSymbolicLink();
    } catch {
      return false;
    }
  },
): string | null {
  return trustedWindowsLauncher(
    environment,
    ["System32", "WindowsPowerShell", "v1.0", "powershell.exe"],
    fileExists,
  );
}

function buildPosixProcessAnchor(enumerators: readonly string[], platform: NodeJS.Platform): string {
  if (
    enumerators.length === 0 ||
    enumerators.some((enumerator) => !enumerator.startsWith("/") || !/^\/[A-Za-z0-9._/-]+$/.test(enumerator))
  ) {
    throw new Error("POSIX process enumerators must be trusted absolute paths.");
  }
  const probes = enumerators
    .map((enumerator, index) => `${index === 0 ? "if" : "elif"} [ -x '${enumerator}' ]; then enumerator='${enumerator}'`)
    .join("\n");
  const enumerationFlags = platform === "darwin" ? "-Eww -ax" : "axeww";
  return String.raw`
containment_token=$1
shift
containment_marker=FLINTTRADE_PROCESS_ANCHOR=$containment_token
target=
watchdog=
enumerator=
containment_cgroup=
${probes}
fi
# Linux cgroup v2 containment.
#
# The marker sweep below finds processes that left the process group via
# setsid(). It is inherently racy: it can only kill what it can SEE, so a
# descendant that appears after the sweep has gone quiet survives. cgroup
# membership is inherited and an unprivileged process cannot leave it, so a
# scope removes the escape route entirely rather than trying to out-run it.
#
# Delegation is not guaranteed (containers, non-systemd sessions, cgroup v1),
# so this is best-effort: on failure containment_cgroup stays empty and the
# sweep remains the mechanism. Nothing here weakens the sweep.
if [ -w /sys/fs/cgroup/cgroup.procs ] || [ -d /sys/fs/cgroup/cgroup.controllers ]; then
  for cgroup_base in \
    "/sys/fs/cgroup$(cat /proc/self/cgroup 2>/dev/null | sed -n 's/^0:://p')" \
    /sys/fs/cgroup
  do
    [ -d "$cgroup_base" ] || continue
    candidate_cgroup=$cgroup_base/flinttrade-$containment_token
    if mkdir "$candidate_cgroup" 2>/dev/null; then
      # The scope must contain ONLY the target tree. The supervisor and its
      # watchdog stay outside it, or cgroup.kill would take them down too.
      if [ -w "$candidate_cgroup/cgroup.procs" ]; then
        containment_cgroup=$candidate_cgroup
      else
        rmdir "$candidate_cgroup" 2>/dev/null || :
      fi
      break
    fi
  done
fi
cgroup_contain() {
  # cgroup.kill (Linux 5.14+) terminates every member atomically, including
  # processes that appeared a moment ago — no scan window, no race.
  [ -n "$containment_cgroup" ] || return 1
  if [ -w "$containment_cgroup/cgroup.kill" ]; then
    printf '1\n' > "$containment_cgroup/cgroup.kill" 2>/dev/null || :
    return 0
  fi
  # Older kernels: signal the exact membership list instead. Still exact —
  # cgroup.procs is authoritative, unlike a ps snapshot.
  cgroup_rounds=0
  while [ "$cgroup_rounds" -lt 50 ]; do
    cgroup_members=$(cat "$containment_cgroup/cgroup.procs" 2>/dev/null) || return 0
    cgroup_remaining=
    for cgroup_member in $cgroup_members; do
      cgroup_remaining=1
      if [ "$cgroup_rounds" -gt 10 ]; then
        /bin/kill -KILL "$cgroup_member" 2>/dev/null || :
      else
        /bin/kill -TERM "$cgroup_member" 2>/dev/null || :
      fi
    done
    [ -n "$cgroup_remaining" ] || return 0
    cgroup_rounds=$((cgroup_rounds + 1))
    /bin/sleep 0.02
  done
  return 0
}
cgroup_release() {
  [ -n "$containment_cgroup" ] || return 0
  rmdir "$containment_cgroup" 2>/dev/null || :
}
proc_tr=
proc_grep=
for candidate_tr in /usr/bin/tr /bin/tr; do
  if [ -x "$candidate_tr" ]; then proc_tr=$candidate_tr; break; fi
done
for candidate_grep in /bin/grep /usr/bin/grep; do
  if [ -x "$candidate_grep" ]; then proc_grep=$candidate_grep; break; fi
done
snapshot_tagged_proc_descendants() {
  # Linux only: /proc/<pid>/environ is the authoritative record of a process's
  # environment. The ps path below depends on the enumerator rendering the
  # environment into an explicit "-o command=" field, which is a formatting
  # promise rather than a guarantee. Reading /proc removes that dependency on
  # the one platform that offers it.
  #
  # Entries are NUL separated, so they are split to lines and matched WHOLE
  # (grep -x): a token that is only a PREFIX of a longer one must not match,
  # which the prefix-match test pins.
  [ -d /proc ] || return 0
  # Resolve the helpers by absolute path, the same way the ps enumerator is
  # resolved above: this script runs with no guaranteed PATH, so a bare tr or
  # grep would silently produce nothing rather than failing loudly.
  [ -n "$proc_tr" ] && [ -n "$proc_grep" ] || return 0
  for environ_path in /proc/[0-9]*/environ; do
    [ -r "$environ_path" ] || continue
    if "$proc_tr" '\0' '\n' < "$environ_path" 2>/dev/null | "$proc_grep" -q -x -F -- "$containment_marker"; then
      proc_pid=$(printf '%s' "$environ_path" | "$proc_tr" -dc '0-9')
      case "$proc_pid" in
        ''|*[!0-9]*) continue ;;
      esac
      printf '%s\n' "$proc_pid"
    fi
  done
  return 0
}
snapshot_tagged_descendants() {
  [ -n "$enumerator" ] || return 1
  tagged_snapshot=$("$enumerator" ${enumerationFlags} -o pid= -o ppid= -o pgid= -o command= 2>/dev/null) || return 1
  # Union of both sources. This can only ever surface MORE tagged processes
  # than the ps scan alone, so it cannot weaken containment; duplicates are
  # harmless because the caller only sends signals.
  snapshot_tagged_proc_descendants
  while read -r tagged_member tagged_parent tagged_group tagged_rest; do
    case "$tagged_member" in
      ''|*[!0-9]*) continue ;;
    esac
    case " $tagged_rest " in
      *" $containment_marker "*) printf '%s\n' "$tagged_member" ;;
    esac
  done <<FLINT_TAGGED_SNAPSHOT
$tagged_snapshot
FLINT_TAGGED_SNAPSHOT
}
on_term() {
  if [ -n "$target" ]; then /bin/kill -TERM "$target" 2>/dev/null || :; fi
}
trap on_term TERM
(
  trap '' TERM HUP INT
  if IFS= read -r _ <&4; then exit 0; fi
  /bin/kill -TERM -$$ 2>/dev/null || :
  # Exact containment first where the kernel can give it to us. When this
  # succeeds nothing can have escaped, so the sweep below has nothing left to
  # find; when it is unavailable the sweep is unchanged.
  cgroup_contain || :
  watchdog_attempts=0
  watchdog_empty_scans=0
  while [ "$watchdog_attempts" -lt 150 ]; do
    watchdog_tagged=$(snapshot_tagged_descendants) || break
    if [ -z "$watchdog_tagged" ]; then
      watchdog_empty_scans=$((watchdog_empty_scans + 1))
      if [ "$watchdog_empty_scans" -ge 2 ]; then break; fi
    else
      watchdog_empty_scans=0
      watchdog_attempts=$((watchdog_attempts + 1))
      for tagged_member in $watchdog_tagged; do
        if [ "$watchdog_attempts" -gt 10 ]; then
          /bin/kill -KILL "$tagged_member" 2>/dev/null || :
        else
          /bin/kill -TERM "$tagged_member" 2>/dev/null || :
        fi
      done
    fi
    /bin/sleep 0.02
  done
  cgroup_contain || :
  cgroup_release
  /bin/kill -KILL -$$ 2>/dev/null || :
) &
watchdog=$!
if ! IFS= read -r start; then
  /bin/kill -KILL "$watchdog" 2>/dev/null || :
  wait "$watchdog" 2>/dev/null || :
  exit 125
fi
tab=$(printf '\t')
case "$start" in
  "FLINTTRADE_CANCEL\${tab}cancelled") status=130 ;;
  "FLINTTRADE_CANCEL\${tab}timeout") status=124 ;;
  "FLINTTRADE_CANCEL\${tab}listener"|"FLINTTRADE_CANCEL\${tab}containment") status=1 ;;
  FLINTTRADE_START) status= ;;
  *) status=125 ;;
esac
if [ -n "$status" ]; then
  printf 'settled\t%s\t0\n' "$status" >&3
  if IFS= read -r release && [ "$release" = FLINTTRADE_RELEASE ]; then
    wait "$watchdog" 2>/dev/null || :
    exit "$status"
  fi
  while :; do /bin/sleep 3600; done
fi
(
  trap - TERM HUP INT
  FLINTTRADE_PROCESS_ANCHOR=$containment_token
  export FLINTTRADE_PROCESS_ANCHOR
  # Join the containment scope before exec. Everything this process spawns
  # inherits the membership, and an unprivileged process cannot leave it —
  # which is what closes the setsid() escape the marker sweep cannot win.
  if [ -n "$containment_cgroup" ]; then
    printf '%s\n' "$$" > "$containment_cgroup/cgroup.procs" 2>/dev/null || :
  fi
  exec "$@" </dev/null 3>&- 4<&-
) &
target=$!
wait "$target"
status=$?
target=
[ -n "$enumerator" ] || {
  printf '%s\n' containment-failed >&3
  while :; do /bin/sleep 3600; done
}
descendants=0
drain_attempts=0
empty_scans=0
while :; do
  snapshot=$(
    "$enumerator" ${enumerationFlags} -o pid= -o ppid= -o pgid= -o command= 2>/dev/null &
    probe=$!
    printf 'FLINTTRADE_PROBE %s\n' "$probe"
    wait "$probe"
  ) || {
    printf '%s\n' containment-failed >&3
    while :; do /bin/sleep 3600; done
  }
  probe=
  probe_parent=
  while read -r first second third rest; do
    if [ "$first" = FLINTTRADE_PROBE ]; then probe=$second; fi
  done <<FLINT_SNAPSHOT_PROBE
$snapshot
FLINT_SNAPSHOT_PROBE
  while read -r member parent member_group rest; do
    if [ "$member" = "$probe" ]; then probe_parent=$parent; fi
  done <<FLINT_SNAPSHOT_PARENT
$snapshot
FLINT_SNAPSHOT_PARENT
  [ -n "$probe" ] && [ -n "$probe_parent" ] || {
    printf '%s\n' containment-failed >&3
    while :; do /bin/sleep 3600; done
  }
  external=
  escaped=
  while read -r member parent member_group rest; do
    case "$member" in
      FLINTTRADE_PROBE|'') continue ;;
    esac
    if [ "$member_group" = "$$" ] &&
       [ "$member" != "$$" ] &&
       [ "$member" != "$watchdog" ] &&
       [ "$member" != "$probe" ] &&
       [ "$member" != "$probe_parent" ]; then
      external="$external $member"
    elif [ "$member" != "$$" ] &&
         [ "$member" != "$watchdog" ] &&
         [ "$member" != "$probe" ] &&
         [ "$member" != "$probe_parent" ]; then
      case " $rest " in
        *" $containment_marker "*) escaped="$escaped $member" ;;
      esac
    fi
  done <<FLINT_SNAPSHOT_MEMBERS
$snapshot
FLINT_SNAPSHOT_MEMBERS
  if [ -z "$external$escaped" ]; then
    empty_scans=$((empty_scans + 1))
    if [ "$empty_scans" -ge 2 ]; then break; fi
    /bin/sleep 0.02
    continue
  fi
  empty_scans=0
  descendants=1
  drain_attempts=$((drain_attempts + 1))
  if [ "$drain_attempts" -gt 100 ]; then
    printf '%s\n' containment-failed >&3
    while :; do /bin/sleep 3600; done
  fi
  if [ -n "$external" ]; then /bin/kill -TERM -$$ 2>/dev/null || :; fi
  for escaped_member in $escaped; do
    if [ "$drain_attempts" -gt 10 ]; then
      /bin/kill -KILL "$escaped_member" 2>/dev/null || :
    else
      /bin/kill -TERM "$escaped_member" 2>/dev/null || :
    fi
  done
  /bin/sleep 0.02
done
if [ "$descendants" -eq 1 ]; then status=1; fi
printf 'settled\t%s\t%s\n' "$status" "$descendants" >&3
if IFS= read -r release && [ "$release" = FLINTTRADE_RELEASE ]; then
  wait "$watchdog" 2>/dev/null || :
  exit "$status"
fi
while :; do
  /bin/sleep 3600
done
`;
}

function samePlatformPath(left: string, right: string, platform: NodeJS.Platform): boolean {
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

export function systemGitCandidates(
  platform: NodeJS.Platform,
  environment: NodeJS.ProcessEnv = process.env,
): readonly string[] {
  if (platform !== "win32") return ["/usr/bin/git"];
  const systemRoot = environment.SystemRoot ?? environment.SYSTEMROOT ?? environment.WINDIR ?? "";
  if (!path.win32.isAbsolute(systemRoot) || systemRoot.trim() !== systemRoot) return [];
  const driveRoot = path.win32.parse(path.win32.normalize(systemRoot)).root;
  if (!/^[A-Za-z]:\\$/.test(driveRoot)) return [];
  return [
    path.win32.join(driveRoot, "Program Files", "Git", "cmd", "git.exe"),
    path.win32.join(driveRoot, "Program Files", "Git", "bin", "git.exe"),
  ];
}

function inspectTrustedExecutable(
  target: string,
  platform: NodeJS.Platform,
): TrustedExecutableSnapshot | null {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  if (!pathApi.isAbsolute(target)) return null;
  let canonicalPath: string;
  try {
    canonicalPath = realpathSync.native(target);
  } catch {
    return null;
  }
  if (!samePlatformPath(pathApi.normalize(target), pathApi.normalize(canonicalPath), platform)) return null;

  let cursor = canonicalPath;
  let fileMetadata: ReturnType<typeof lstatSync> | null = null;
  for (;;) {
    let metadata: ReturnType<typeof lstatSync>;
    try {
      metadata = lstatSync(cursor);
    } catch {
      return null;
    }
    if (metadata.isSymbolicLink()) return null;
    if (cursor === canonicalPath) {
      if (!metadata.isFile()) return null;
      fileMetadata = metadata;
    } else if (!metadata.isDirectory()) {
      return null;
    }
    if (
      platform !== "win32" &&
      (metadata.uid !== 0 || (metadata.mode & 0o022) !== 0)
    ) {
      return null;
    }
    const parent = pathApi.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
  if (!fileMetadata || (platform !== "win32" && (fileMetadata.mode & 0o111) === 0)) return null;
  return {
    canonicalPath,
    ctimeMs: fileMetadata.ctimeMs,
    dev: fileMetadata.dev,
    ino: fileMetadata.ino,
    mode: fileMetadata.mode,
    mtimeMs: fileMetadata.mtimeMs,
    size: fileMetadata.size,
  };
}

function sameTrustedExecutable(
  left: TrustedExecutableSnapshot,
  right: TrustedExecutableSnapshot,
  platform: NodeJS.Platform,
): boolean {
  return (
    samePlatformPath(left.canonicalPath, right.canonicalPath, platform) &&
    left.ctimeMs === right.ctimeMs &&
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.mode === right.mode &&
    left.mtimeMs === right.mtimeMs &&
    left.size === right.size
  );
}

function resolveTrustedGit(
  platform: NodeJS.Platform,
  environment: NodeJS.ProcessEnv,
  options: BootstrapIoOptions,
): { inspect: (target: string, platform: NodeJS.Platform) => TrustedExecutableSnapshot | null; snapshot: TrustedExecutableSnapshot } | null {
  const inspect = options.testHooks?.inspectTrustedGit ?? inspectTrustedExecutable;
  const candidates = options.trustedGitCandidates ?? systemGitCandidates(platform, environment);
  for (const candidate of candidates) {
    const snapshot = inspect(candidate, platform);
    if (!snapshot || !samePlatformPath(snapshot.canonicalPath, candidate, platform)) continue;
    return { inspect, snapshot };
  }
  return null;
}

function createCommandRunner(platform: NodeJS.Platform, options: BootstrapIoOptions): BootstrapDependencies["command"] {
  const environment = options.environment ?? process.env;
  const fileExists = options.fileExists ?? noFollowRegularFile;
  const canonicalise = options.canonicalisePath ?? ((target: string) => realpathSync.native(target));
  const powerShellCandidate =
    platform === "win32" ? resolveTrustedWindowsPowerShell(environment, fileExists) : null;
  const windowsPowerShell = powerShellCandidate
    ? resolveWindowsExecutable(powerShellCandidate, environment, fileExists, canonicalise)
    : null;
  let canonicalSupervisor: string | null = null;
  if (
    options.windowsJobSupervisor &&
    path.win32.isAbsolute(options.windowsJobSupervisor) &&
    fileExists(options.windowsJobSupervisor)
  ) {
    try {
      canonicalSupervisor = canonicalise(options.windowsJobSupervisor);
    } catch {
      canonicalSupervisor = null;
    }
  }
  const windowsJobSupervisor =
    platform === "win32" &&
    canonicalSupervisor &&
    path.win32.isAbsolute(canonicalSupervisor) &&
    path.win32.extname(canonicalSupervisor).toLowerCase() === ".exe" &&
    fileExists(canonicalSupervisor)
      ? canonicalSupervisor
      : null;
  const posixProcessAnchor = buildPosixProcessAnchor(
    options.posixProcessEnumerators ?? ["/bin/ps", "/usr/bin/ps"],
    platform,
  );
  const trustedGit = resolveTrustedGit(platform, environment, options);
  return {
    ...(options.operationLeaseTarget ? { operationLeaseTarget: options.operationLeaseTarget } : {}),
    ...(windowsPowerShell ? { windowsPowerShell } : {}),
    async reconcileOperationContainment(): Promise<void> {
      if (!options.operationLeaseTarget) {
        throw new Error("Command containment reconciliation requires the shared source-operation lease target.");
      }
      await reconcileActiveOperationContainment(
        options.operationLeaseTarget,
        options.testHooks?.recordedProcessWaitMs,
        options.posixProcessEnumerators,
        options.testHooks,
      );
    },
    run(invocation): Promise<CommandResult> {
      return new Promise((resolve) => {
        if (platform === "win32" && !windowsJobSupervisor) {
          resolve({
            contained: true,
            exitCode: 127,
            stderr: "Verified Windows Job supervisor is unavailable.",
            stderrTruncated: false,
            stdout: "",
            stdoutTruncated: false,
          });
          return;
        }
        if (invocation.signal?.aborted) {
          resolve({
            contained: true,
            exitCode: 130,
            stderr: "Operation cancelled.",
            stderrTruncated: false,
            stdout: "",
            stdoutTruncated: false,
          });
          return;
        }
        let invocationCommand = invocation.command;
        if (invocationCommand === "git") {
          const current = trustedGit?.inspect(trustedGit.snapshot.canonicalPath, platform) ?? null;
          if (!trustedGit || !current || !sameTrustedExecutable(current, trustedGit.snapshot, platform)) {
            resolve({
              contained: true,
              exitCode: 127,
              stderr: "Verified system Git is unavailable.",
              stderrTruncated: false,
              stdout: "",
              stdoutTruncated: false,
            });
            return;
          }
          invocationCommand = trustedGit.snapshot.canonicalPath;
        }
        let stdout = "";
        let stderr = "";
        let stdoutTruncated = false;
        let stderrTruncated = false;
        let stdoutBuffer = "";
        let stderrBuffer = "";
        let controlBuffer = "";
        let listenerFailure = "";
        let descendantLeak = false;
        let terminalReason: "cancelled" | "containment" | "descendant" | "listener" | "timeout" | null = null;
        let settled = false;
        let terminating: Promise<void> | null = null;
        let closeCode: number | null = null;
        let closeObserved = false;
        let terminationError = "";
        let releaseProcessAnchor: (() => Promise<void>) | null = null;
        let protocolReleaseStarted = false;
        let protocolSettlement: Promise<void> | null = null;
        let protocolReady = false;
        let protocolSetup: Promise<void> | null = null;
        let prestartReason: "cancelled" | "containment" | "descendant" | "listener" | "timeout" | null = null;
        let observeClose!: () => void;
        const closeSignal = new Promise<void>((resolveClose) => {
          observeClose = resolveClose;
        });
        let supervisorToken: string | null = null;
        const posixContainmentToken = platform === "win32" ? null : randomBytes(16).toString("hex");
        let spawnCommand = "/bin/sh";
        let spawnArgs = [
          "-c",
          posixProcessAnchor,
          "flinttrade-process-anchor",
          posixContainmentToken!,
          invocationCommand,
          ...invocation.args,
        ];
        const childEnvironment = minimalChildEnvironment(
          invocation.env,
          invocation.inheritEnvironment === false ? {} : environment,
          platform,
        );
        if (platform === "win32") {
          const targetExecutable = resolveWindowsExecutable(invocationCommand, childEnvironment, fileExists, canonicalise);
          if (!targetExecutable) {
            resolve({
              contained: true,
              exitCode: 127,
              stderr: "Windows bootstrap target is not a trusted absolute executable.",
              stderrTruncated: false,
              stdout: "",
              stdoutTruncated: false,
            });
            return;
          }
          supervisorToken = randomBytes(16).toString("hex");
          try {
            const supervisor = buildWindowsSupervisorInvocation({
              args: invocation.args,
              ...(invocation.cwd ? { cwd: invocation.cwd } : {}),
              ...(invocation.expectedExecutableSha256
                ? { expectedTargetSha256: invocation.expectedExecutableSha256 }
                : {}),
              helper: windowsJobSupervisor!,
              parentPid: process.pid,
              target: targetExecutable,
              token: supervisorToken,
            });
            spawnCommand = supervisor.command;
            spawnArgs = supervisor.args;
          } catch (error) {
            resolve({
              contained: true,
              exitCode: 127,
              stderr: error instanceof Error ? error.message : String(error),
              stderrTruncated: false,
              stdout: "",
              stdoutTruncated: false,
            });
            return;
          }
        }
        const child = spawn(
          spawnCommand,
          spawnArgs,
          {
          ...(invocation.cwd && platform !== "win32" ? { cwd: invocation.cwd } : {}),
          env: childEnvironment,
          detached: platform !== "win32",
          stdio: platform === "win32" ? ["pipe", "pipe", "pipe"] : ["pipe", "pipe", "pipe", "pipe", "pipe"],
          windowsHide: true,
          },
        );
        const unregisterProcessAnchor = async (): Promise<void> => {
          const release = releaseProcessAnchor;
          if (!release) return;
          let firstFailure: unknown = null;
          for (let attempt = 0; attempt < 2; attempt += 1) {
            try {
              await release();
              if (releaseProcessAnchor === release) releaseProcessAnchor = null;
              return;
            } catch (error) {
              firstFailure ??= error;
              if (attempt === 1) throw firstFailure;
              await delay(20);
            }
          }
        };
        const releaseProtocolAnchor = (line: string): Promise<void> => {
          if (protocolSettlement) return protocolSettlement;
          if (protocolReleaseStarted) return Promise.resolve();
          protocolReleaseStarted = true;
          const settlement = (async () => {
            if (!child.stdin) throw new Error("Bootstrap process release control pipe is unavailable.");
            await writeControlLine(child.stdin, line, true);
            if (platform !== "win32") {
              const liveness = child.stdio[4] as unknown as NodeJS.WritableStream | null;
              if (!liveness) throw new Error("Bootstrap parent-liveness control pipe is unavailable.");
              await writeControlLine(liveness, "FLINTTRADE_PARENT_RELEASE\n", true);
            }
            await closeSignal;
            await unregisterProcessAnchor();
          })();
          protocolSettlement = settlement;
          void settlement.then(
            () => {
              if (protocolSettlement === settlement) protocolSettlement = null;
              finish();
            },
            (error) => {
              if (protocolSettlement === settlement) protocolSettlement = null;
              failProtocolRelease(error);
              finish();
            },
          );
          return settlement;
        };
        const failProtocolRelease = (error: unknown): void => {
          terminationError = error instanceof Error ? error.message : String(error);
          if (platform === "win32") child.kill("SIGKILL");
          else if (child.pid) {
            try {
              process.kill(-child.pid, "SIGKILL");
            } catch (killError) {
              if ((killError as NodeJS.ErrnoException).code !== "ESRCH") child.kill("SIGKILL");
            }
          }
        };
        const finish = (): void => {
          if (
            settled ||
            !closeObserved ||
            protocolSetup ||
            protocolSettlement ||
            (terminating && terminationError === "pending")
          ) return;
          settled = true;
          clearTimeout(timeout);
          invocation.signal?.removeEventListener("abort", onAbort);
          try {
            if (stdoutBuffer) invocation.onOutput?.(stdoutBuffer, "stdout");
            if (stderrBuffer && !stderrBuffer.startsWith(`${WINDOWS_SUPERVISOR_PREFIX}\t`)) {
              invocation.onOutput?.(stderrBuffer, "stderr");
            }
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminalReason ??= "listener";
          }
          const unresolvedAnchorRecord = releaseProcessAnchor !== null;
          const windowsProof =
            platform === "win32" && supervisorToken
              ? applyWindowsSupervisorLocalState(parseWindowsSupervisorProof(
                  stderr,
                  supervisorToken,
                  closeCode,
                  stderrTruncated,
                ), {
                  cancelled: terminalReason === "cancelled",
                  listenerFailure: terminalReason === "listener",
                  timedOut: terminalReason === "timeout",
                })
              : null;
          const resultStderr = windowsProof?.stderr ?? stderr;
          const stderrSuffix = terminalReason === "timeout" && !windowsProof
            ? `\nCommand timed out.${terminationError && terminationError !== "pending" ? ` ${terminationError}` : ""}`
            : `${terminationError && terminationError !== "pending" ? `\n${terminationError}` : ""}${unresolvedAnchorRecord ? "\nDurable process-anchor registration did not settle." : ""}${listenerFailure ? `\nOutput listener failed: ${listenerFailure}` : ""}${descendantLeak ? "\nCommand leader exited before its descendant tree; containment terminated the tree." : ""}${terminalReason === "containment" ? "\nProcess-group enumeration failed; forced cleanup was required." : ""}`;
          const finalStderr = appendBounded(resultStderr, stderrSuffix);
          resolve({
            contained: windowsProof
              ? windowsProof.contained && !terminationError && !unresolvedAnchorRecord
              : terminalReason !== "containment" && !terminationError && !unresolvedAnchorRecord,
            exitCode: windowsProof
              ? windowsProof.contained && !terminationError && !unresolvedAnchorRecord
                ? windowsProof.exitCode
                : 1
              : terminalReason === "listener" || terminalReason === "containment" || terminalReason === "descendant" || descendantLeak
                ? 1
                : terminalReason === "cancelled"
                  ? 130
                  : terminalReason === "timeout"
                    ? 124
                    : (closeCode ?? 1),
            stderr: finalStderr.text,
            stderrTruncated: stderrTruncated || finalStderr.truncated,
            stdout,
            stdoutTruncated,
          });
        };

        const terminate = (reason: "cancelled" | "containment" | "descendant" | "listener" | "timeout"): void => {
          if (terminalReason || terminating) return;
          terminalReason = reason;
          descendantLeak = reason === "descendant";
          if (!protocolReady) {
            prestartReason = reason;
            return;
          }
          terminationError = "pending";
          terminating = (async () => {
            const pid = child.pid;
            if (!pid) return;
            if (platform === "win32") {
              if (!supervisorToken || !child.stdin) throw new Error("Windows Job supervisor control pipe is unavailable.");
              const controlReason: WindowsSupervisorStopReason =
                reason === "timeout" ? "timeout" : reason === "listener" ? "listener" : "cancel";
              try {
                await writeControlLine(child.stdin, windowsSupervisorControlLine(supervisorToken!, controlReason));
                await Promise.race([
                  closeSignal,
                  delay(8_000).then(() => {
                    throw new Error("Windows Job supervisor did not settle after its control request.");
                  }),
                ]);
              } catch (error) {
                child.kill("SIGKILL");
                await Promise.race([
                  closeSignal,
                  delay(5_000).then(() => {
                    throw new Error("Windows Job supervisor handle did not close after forced termination.");
                  }),
                ]);
                if (parseWindowsSupervisorProof(stderr, supervisorToken, closeCode, stderrTruncated).contained) {
                  await unregisterProcessAnchor();
                  return;
                }
                throw error;
              }
              return;
            }
            try {
              process.kill(-pid, "SIGTERM");
            } catch (error) {
              if ((error as NodeJS.ErrnoException).code !== "ESRCH") child.kill("SIGTERM");
            }
            try {
              await Promise.race([
                closeSignal,
                delay(2_000).then(() => {
                  throw new Error("POSIX process anchor did not settle through its control protocol.");
                }),
              ]);
            } catch (error) {
              try {
                process.kill(-pid, "SIGKILL");
              } catch (killError) {
                if ((killError as NodeJS.ErrnoException).code !== "ESRCH") throw killError;
              }
              if (!(await waitForPosixProcessGroupExit(pid, 5_000))) {
                throw new Error("Descendant process group did not terminate after forced containment.");
              }
              await Promise.race([
                closeSignal,
                delay(5_000).then(() => {
                  throw new Error("POSIX process anchor handle did not close after forced containment.");
                }),
              ]);
              await waitForRecordedProcessesGone(
                [{ containmentToken: posixContainmentToken, processGroupId: pid }],
                [],
                5_000,
                options.posixProcessEnumerators,
              );
              if (reason !== "containment") {
                await unregisterProcessAnchor();
              }
            }
          })();
          void terminating.then(
            () => {
              terminationError = "";
              finish();
            },
            (error) => {
              terminationError = error instanceof Error ? error.message : String(error);
              finish();
            },
          );
        };
        const onAbort = () => terminate("cancelled");
        invocation.signal?.addEventListener("abort", onAbort, { once: true });
        const timeout = setTimeout(() => terminate("timeout"), invocation.timeoutMs ?? 30 * 60_000);
        timeout.unref?.();

        const childStdout = child.stdout;
        const childStderr = child.stderr;
        if (!childStdout || !childStderr) throw new Error("Bootstrap command output pipes were not created.");
        childStdout.setEncoding("utf8");
        childStderr.setEncoding("utf8");
        childStdout.on("data", (chunk: string) => {
          const appended = appendBounded(stdout, chunk);
          stdout = appended.text;
          stdoutTruncated ||= appended.truncated;
          try {
            stdoutBuffer = emitLines(stdoutBuffer, chunk, "stdout", invocation.onOutput);
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminate("listener");
          }
        });
        childStderr.on("data", (chunk: string) => {
          const appended = appendBounded(stderr, chunk);
          stderr = appended.text;
          stderrTruncated ||= appended.truncated;
          try {
            stderrBuffer = emitLines(stderrBuffer, chunk, "stderr", (line, stream) => {
              if (line.startsWith(`${WINDOWS_SUPERVISOR_PREFIX}\t`)) {
                if (platform === "win32" && stderrTruncated) terminate("containment");
                return;
              }
              invocation.onOutput?.(line, stream);
            });
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminate("listener");
          }
          if (
            platform === "win32" &&
            supervisorToken &&
            hasWindowsSupervisorSettledProof(stderr, supervisorToken, stderrTruncated)
          ) {
            void releaseProtocolAnchor(windowsSupervisorReleaseLine(supervisorToken));
          }
        });
        if (platform !== "win32") {
          const control = child.stdio[3] as Readable | null;
          control?.setEncoding("utf8");
          control?.on("data", (chunk: string) => {
            controlBuffer += chunk;
            let newline = controlBuffer.indexOf("\n");
            while (newline >= 0) {
              const event = controlBuffer.slice(0, newline).replace(/\r$/, "");
              controlBuffer = controlBuffer.slice(newline + 1);
              if (event === "containment-failed" && !terminalReason) terminate("containment");
              else {
                const proof = /^settled\t(0|[1-9][0-9]*)\t([01])$/.exec(event);
                if (proof) {
                  const targetExit = Number(proof[1]);
                  if (!Number.isSafeInteger(targetExit) || targetExit > 255) terminate("containment");
                  else {
                    if (proof[2] === "1") {
                      descendantLeak = true;
                      terminalReason ??= "descendant";
                    }
                    void releaseProtocolAnchor("FLINTTRADE_RELEASE\n");
                  }
                }
              }
              newline = controlBuffer.indexOf("\n");
            }
            if (controlBuffer.length > 128 && !terminalReason) terminate("containment");
          });
        }
        const setup = (async () => {
          const pid = child.pid;
          if (!pid) throw new Error("Bootstrap process anchor did not receive a PID.");
          if (options.operationLeaseTarget) {
            releaseProcessAnchor = await registerOperationProcessAnchor(
              options.operationLeaseTarget,
              pid,
              platform === "win32" ? "windows-supervisor" : "posix-group",
              posixContainmentToken,
              options.testHooks,
            );
          }
          if (invocation.signal?.aborted && !prestartReason) {
            terminalReason = "cancelled";
            prestartReason = "cancelled";
          }
          if (!child.stdin) throw new Error("Bootstrap process start control pipe is unavailable.");
          const cancellingBeforeStart = prestartReason;
          if (cancellingBeforeStart) {
            const reasonValue: string = cancellingBeforeStart;
            const windowsReason: WindowsSupervisorStopReason =
              reasonValue === "timeout"
                ? "timeout"
                : reasonValue === "listener" || reasonValue === "containment" || reasonValue === "descendant"
                  ? "listener"
                  : "cancel";
            await writeControlLine(
              child.stdin,
              platform === "win32"
                ? windowsSupervisorControlLine(supervisorToken!, windowsReason)
                : `FLINTTRADE_CANCEL\t${reasonValue}\n`,
            );
            protocolReady = true;
            return;
          }
          await writeControlLine(child.stdin, platform === "win32" ? windowsSupervisorStartLine(supervisorToken!) : "FLINTTRADE_START\n");
          protocolReady = true;
          if (prestartReason) {
            const deferredReason = prestartReason;
            terminalReason = null;
            prestartReason = null;
            terminate(deferredReason);
          }
        })();
        protocolSetup = setup;
        void setup.then(
          () => {
            if (protocolSetup === setup) protocolSetup = null;
            finish();
          },
          (error) => {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminationError = listenerFailure;
            if (platform === "win32") child.kill("SIGKILL");
            else if (child.pid) {
              try {
                process.kill(-child.pid, "SIGKILL");
              } catch (killError) {
                if ((killError as NodeJS.ErrnoException).code !== "ESRCH") child.kill("SIGKILL");
              }
            }
            if (protocolSetup === setup) protocolSetup = null;
            finish();
          },
        );
        child.on("error", (error) => {
          if (settled) return;
          closeObserved = true;
          observeClose();
          closeCode = terminalReason === "cancelled" ? 130 : 127;
          const appended = appendBounded(stderr, error.message);
          stderr = appended.text;
          stderrTruncated ||= appended.truncated;
          finish();
        });
        child.on("close", (code) => {
          if (settled) return;
          closeObserved = true;
          observeClose();
          closeCode = code;
          finish();
        });
      });
    },
  };
}

function validateDownloadUrl(url: string, policy: DownloadPolicy): URL {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") throw new Error(`${policy.label} download requires HTTPS.`);
  if (parsed.username || parsed.password || parsed.hash) {
    throw new Error(`${policy.label} download URL may not contain credentials or a fragment.`);
  }
  if (!policy.allowedHosts.includes(parsed.hostname.toLowerCase())) {
    throw new Error(`${policy.label} download host is not approved.`);
  }
  return parsed;
}

function contentLengthWithinLimit(value: string | undefined, policy: DownloadPolicy): void {
  if (!value) return;
  const length = Number(value);
  if (!Number.isSafeInteger(length) || length < 0 || length > policy.maxBytes) {
    throw new Error(`${policy.label} download declared an invalid or excessive content length.`);
  }
}

async function requestDownload(
  url: string,
  signal: AbortSignal,
  policy: DownloadPolicy,
  consume: (response: NodeJS.ReadableStream, finalUrl: string) => Promise<{ bytes: number; sha256: string }>,
  deadline = Date.now() + policy.totalTimeoutMs,
  redirects = 0,
): Promise<DownloadReceipt> {
  if (redirects > 4) throw new Error(`${policy.label} download exceeded the redirect limit.`);
  if (Date.now() >= deadline) throw new Error(`${policy.label} download exceeded its total deadline.`);
  const parsed = validateDownloadUrl(url, policy);
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    let completed = false;
    let responseTaskStarted = false;
    let activeResponse: IncomingMessage | null = null;
    let terminalError: Error | null = null;
    const remaining = Math.max(1, deadline - Date.now());
    let totalTimer: NodeJS.Timeout;
    const cleanup = (): void => {
      clearTimeout(totalTimer);
      signal.removeEventListener("abort", onAbort);
    };
    const settle = (
      outcome: { receipt: DownloadReceipt } | { error: unknown },
    ): void => {
      if (completed) return;
      completed = true;
      cleanup();
      if ("receipt" in outcome) resolve(outcome.receipt);
      else reject(outcome.error);
    };
    const terminate = (error: Error): void => {
      terminalError ??= error;
      activeResponse?.destroy();
      request.destroy(terminalError);
    };
    const onAbort = (): void => terminate(abortError());
    const request = https.get(
      parsed,
      { headers: { Accept: "application/octet-stream, application/json", "User-Agent": "FlintTrade-Desktop" } },
      (response) => {
        activeResponse = response;
        responseTaskStarted = true;
        const responseTask = (async () => {
          if (response.statusCode && [301, 302, 303, 307, 308].includes(response.statusCode)) {
            const location = response.headers.location;
            await destroyDownloadResponse(response);
            if (!location) throw new Error(`${policy.label} redirect omitted its destination.`);
            return await requestDownload(
              new URL(location, parsed).href,
              signal,
              policy,
              consume,
              deadline,
              redirects + 1,
            );
          }
          if (response.statusCode !== 200) {
            await destroyDownloadResponse(response);
            throw new Error(`${policy.label} download failed with status ${response.statusCode}.`);
          }
          try {
            contentLengthWithinLimit(response.headers["content-length"], policy);
            const receipt = await consume(response, parsed.href);
            return { ...receipt, finalUrl: parsed.href, origin: parsed.origin };
          } catch (error) {
            await destroyDownloadResponse(response);
            throw error;
          }
        })();
        void responseTask.then(
          (receipt) => {
            if (terminalError) settle({ error: terminalError });
            else settle({ receipt });
          },
          (error) => {
            settle({ error: terminalError ?? error });
          },
        );
      },
    );
    totalTimer = setTimeout(
      () => terminate(new Error(`${policy.label} download exceeded its total deadline.`)),
      remaining,
    );
    totalTimer.unref?.();
    signal.addEventListener("abort", onAbort, { once: true });
    request.setTimeout(policy.idleTimeoutMs, () => terminate(new Error(`${policy.label} download became idle.`)));
    request.on("error", (error) => {
      if (!responseTaskStarted) settle({ error: terminalError ?? error });
    });
  });
}

async function destroyDownloadResponse(response: IncomingMessage): Promise<void> {
  if (response.closed) return;
  await new Promise<void>((resolve) => {
    response.once("close", resolve);
    if (!response.destroyed) response.destroy();
  });
}

async function consumeBytes(
  response: NodeJS.ReadableStream,
  policy: DownloadPolicy,
): Promise<{ buffer: Buffer; bytes: number; sha256: string }> {
  const chunks: Buffer[] = [];
  const hash = createHash("sha256");
  let bytes = 0;
  for await (const chunk of response) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += value.length;
    if (bytes > policy.maxBytes) throw new Error(`${policy.label} download exceeded its size limit.`);
    hash.update(value);
    chunks.push(value);
  }
  return { buffer: Buffer.concat(chunks), bytes, sha256: hash.digest("hex") };
}

async function downloadFile(
  url: string,
  destination: string,
  signal: AbortSignal,
  policy: DownloadPolicy,
  options: BootstrapIoOptions,
): Promise<DownloadReceipt> {
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const receipt = await requestDownload(url, signal, policy, async (response) => {
    const hash = createHash("sha256");
    let bytes = 0;
    options.testHooks?.beforeDownloadTemporaryOpen?.(destination);
    const handle = await open(destination, "wx", 0o600);
    await options.testHooks?.onDownloadTemporaryLifecycle?.("handle-opened");
    try {
      const opened = await handle.stat();
      if (!opened.isFile()) throw new Error("Bootstrap download destination was not a regular file.");
      for await (const chunk of response) {
        if (signal.aborted) throw abortError();
        const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        bytes += value.length;
        if (bytes > policy.maxBytes) throw new Error(`${policy.label} download exceeded its size limit.`);
        hash.update(value);
        await writeBufferCompletely(handle, value, options.testHooks?.downloadWriteChunkBytes);
      }
      await handle.sync();
      const pathname = await lstat(destination);
      if (
        pathname.isSymbolicLink() ||
        !pathname.isFile() ||
        pathname.dev !== opened.dev ||
        pathname.ino !== opened.ino
      ) {
        throw new Error("Bootstrap download destination identity changed before settlement.");
      }
    } finally {
      await handle.close();
      await options.testHooks?.onDownloadTemporaryLifecycle?.("handle-closed");
    }
    return { bytes, sha256: hash.digest("hex") };
  });
  await syncDirectoryForDurability(path.dirname(destination));
  return receipt;
}

function createDownloader(options: BootstrapIoOptions): BootstrapDependencies["download"] {
  return {
    file: (url, destination, signal, policy) => downloadFile(url, destination, signal, policy, options),
    async text(url, signal, policy): Promise<TextDownloadReceipt> {
      let content: Buffer<ArrayBufferLike> = Buffer.alloc(0);
      const receipt = await requestDownload(url, signal, policy, async (response) => {
        const consumed = await consumeBytes(response, policy);
        content = consumed.buffer;
        return consumed;
      });
      return { ...receipt, content: content.toString("utf8") };
    },
  };
}

type ArchiveEntryKind = "directory" | "file" | "hardlink" | "symlink";

interface ValidatedArchiveEntry {
  kind: ArchiveEntryKind;
  mode: number;
  name: string;
  size: number;
  target?: string;
}

class ArchiveValidator {
  readonly entries: ValidatedArchiveEntry[] = [];
  private readonly names = new Map<string, ArchiveEntryKind>();
  private expandedBytes = 0;
  private listingBytes = 0;

  constructor(
    private readonly label: string,
    private readonly expectedRoot?: string,
  ) {}

  add(raw: ValidatedArchiveEntry): void {
    if (this.entries.length >= ARCHIVE_LIMITS.entries) throw new Error(`${this.label} archive has too many entries.`);
    if (raw.name.includes("\0") || raw.name.includes("\\")) {
      throw new Error(`${this.label} archive contains an unsafe path.`);
    }
    const name = raw.name.replace(/\/+$/, "");
    const parts = name.split("/");
    if (
      !name ||
      name.startsWith("/") ||
      name.startsWith("//") ||
      /^[A-Za-z]:/.test(name) ||
      parts.some((part) => part === "" || part === "." || part === "..")
    ) {
      throw new Error(`${this.label} archive contains an unsafe path.`);
    }
    if (this.expectedRoot && name !== this.expectedRoot && !name.startsWith(`${this.expectedRoot}/`)) {
      throw new Error(`${this.label} archive contains an unexpected root.`);
    }
    const nameBytes = Buffer.byteLength(name);
    this.listingBytes += nameBytes;
    if (nameBytes > ARCHIVE_LIMITS.nameBytes || this.listingBytes > ARCHIVE_LIMITS.listingBytes) {
      throw new Error(`${this.label} archive listing exceeded its size limit.`);
    }
    if (!Number.isSafeInteger(raw.size) || raw.size < 0 || raw.size > ARCHIVE_LIMITS.singleFileBytes) {
      throw new Error(`${this.label} archive entry exceeded its size limit.`);
    }
    this.expandedBytes += raw.size;
    if (this.expandedBytes > ARCHIVE_LIMITS.expandedBytes) {
      throw new Error(`${this.label} archive expanded size exceeded its limit.`);
    }
    const folded = name.toLocaleLowerCase("en-US");
    if (this.names.has(folded)) throw new Error(`${this.label} archive contains a duplicate or case-colliding path.`);
    for (let index = 1; index < parts.length; index += 1) {
      const ancestor = parts.slice(0, index).join("/").toLocaleLowerCase("en-US");
      const ancestorKind = this.names.get(ancestor);
      if (ancestorKind && ancestorKind !== "directory") {
        throw new Error(`${this.label} archive places a path below a non-directory entry.`);
      }
    }
    if (raw.kind !== "directory") {
      for (const existing of this.names.keys()) {
        if (existing.startsWith(`${folded}/`)) {
          throw new Error(`${this.label} archive replaces an existing directory ancestor.`);
        }
      }
    }
    if (raw.kind === "symlink" || raw.kind === "hardlink") {
      if (!raw.target || raw.target.includes("\0") || raw.target.includes("\\")) {
        throw new Error(`${this.label} archive has invalid link metadata.`);
      }
      const root = name.split("/")[0];
      const resolved =
        raw.kind === "symlink"
          ? path.posix.resolve("/", path.posix.dirname(name), raw.target)
          : path.posix.resolve("/", raw.target);
      if (resolved !== `/${root}` && !resolved.startsWith(`/${root}/`)) {
        throw new Error(`${this.label} archive link escapes its archive root.`);
      }
    }
    this.names.set(folded, raw.kind);
    this.entries.push({ ...raw, name });
  }

  complete(): ValidatedArchiveEntry[] {
    if (this.entries.length === 0) throw new Error(`${this.label} archive is empty.`);
    const byName = new Map(this.entries.map((entry) => [entry.name, entry]));
    for (const entry of this.entries) {
      if (entry.kind !== "symlink" && entry.kind !== "hardlink") continue;
      const target =
        entry.kind === "symlink"
          ? path.posix.normalize(path.posix.join(path.posix.dirname(entry.name), entry.target!))
          : path.posix.normalize(entry.target!);
      const targetEntry = byName.get(target);
      if (!targetEntry || (targetEntry.kind !== "file" && targetEntry.kind !== "directory")) {
        throw new Error(`${this.label} archive link target is missing or resolves through another link.`);
      }
      if (entry.kind === "hardlink" && targetEntry.kind !== "file") {
        throw new Error(`${this.label} archive hardlink target is not a regular file.`);
      }
    }
    return this.entries;
  }
}

export function validateArchiveEntries(entries: string[], label: string, expectedRoot?: string): string[] {
  const validator = new ArchiveValidator(label, expectedRoot);
  for (const entry of entries) {
    validator.add({ kind: entry.endsWith("/") ? "directory" : "file", mode: 0, name: entry, size: 0 });
  }
  return validator.complete().map((entry) => entry.name);
}

export function validateTarLinkEntries(entries: string[], verboseListing: string, label: string): void {
  const validator = new ArchiveValidator(label);
  const links = new Map<string, { kind: "hardlink" | "symlink"; target: string }>();
  for (const line of verboseListing.split(/\r?\n/).filter(Boolean)) {
    const type = line[0];
    if (type !== "l" && type !== "h") continue;
    const separator = type === "l" ? " -> " : " link to ";
    const separatorIndex = line.lastIndexOf(separator);
    if (separatorIndex < 0) throw new Error(`${label} archive has unparseable link metadata.`);
    const left = line.slice(0, separatorIndex).trimEnd();
    const entry = [...entries].sort((a, b) => b.length - a.length).find((candidate) => left.endsWith(candidate));
    if (!entry) throw new Error(`${label} archive link does not match a listed path.`);
    links.set(entry, {
      kind: type === "l" ? "symlink" : "hardlink",
      target: line.slice(separatorIndex + separator.length).trim(),
    });
  }
  for (const entry of entries) {
    const link = links.get(entry);
    validator.add({ kind: link?.kind ?? "file", mode: 0, name: entry, size: 0, ...(link ? { target: link.target } : {}) });
  }
  validator.complete();
}

async function assertExtractedTreeConfined(root: string): Promise<void> {
  const canonicalRoot = await realpath(root);
  const visit = async (directory: string): Promise<void> => {
    for (const entry of await readdir(directory)) {
      const candidate = path.join(directory, entry);
      const metadata = await lstat(candidate);
      if (metadata.isSymbolicLink()) {
        const target = path.resolve(path.dirname(candidate), await readlink(candidate));
        if (!isPathWithin(canonicalRoot, target)) throw new Error("Extracted archive symlink escapes its root.");
        const canonicalTarget = await realpath(candidate);
        if (!isPathWithin(canonicalRoot, canonicalTarget)) throw new Error("Extracted archive symlink escapes its root.");
      } else if (metadata.isDirectory()) {
        await visit(candidate);
      }
    }
  };
  await visit(canonicalRoot);
}

function isPathWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function sha256File(target: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const stream = createReadStream(target);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

async function snapshotSourceTree(
  root: string,
  ignoredRoots: readonly string[] = [],
  ignoredFiles: readonly string[] = [],
): Promise<SourceTreeIdentity> {
  const entries: SourceTreeEntry[] = [];
  const rootMetadata = await lstat(root);
  if (rootMetadata.isSymbolicLink() || !rootMetadata.isDirectory()) {
    throw new Error("Source-tree root must be a no-follow directory.");
  }
  const canonicalRoot = await realpath(root);
  const ignored = ignoredRoots.map((entry) => {
    const normalised = entry.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
    if (!normalised || path.posix.isAbsolute(normalised) || normalised.split("/").some((component) => component === "..")) {
      throw new Error("Allowed generated source-tree roots must be confined relative paths.");
    }
    return normalised;
  });
  const ignoredRegularFiles = ignoredFiles.map((entry) => {
    const normalised = entry.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
    if (!normalised || path.posix.isAbsolute(normalised) || normalised.split("/").some((component) => component === "..")) {
      throw new Error("Allowed generated source-tree files must be confined relative paths.");
    }
    return normalised;
  });
  const visit = async (directory: string): Promise<void> => {
    const children = await readdir(directory);
    children.sort();
    for (const child of children) {
      const target = path.join(directory, child);
      const relative = path.relative(root, target).split(path.sep).join("/");
      const metadata = await lstat(target);
      if (ignored.includes(relative)) {
        if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
          throw new Error(`Allowed generated source-tree root ${relative} must be a no-follow directory.`);
        }
        const canonicalGeneratedRoot = await realpath(target);
        const generatedRelative = path.relative(canonicalRoot, canonicalGeneratedRoot);
        if (generatedRelative.startsWith("..") || path.isAbsolute(generatedRelative)) {
          throw new Error(`Allowed generated source-tree root ${relative} escaped the candidate.`);
        }
        continue;
      }
      if (ignoredRegularFiles.includes(relative)) {
        if (metadata.isSymbolicLink() || !metadata.isFile()) {
          throw new Error(`Allowed generated source-tree file ${relative} must be a no-follow regular file.`);
        }
        continue;
      }
      if (metadata.isDirectory()) {
        await visit(target);
      } else if (metadata.isFile()) {
        entries.push({ mode: metadata.mode & 0o777, path: relative, sha256: await sha256File(target), type: "file" });
      } else if (metadata.isSymbolicLink()) {
        entries.push({ mode: metadata.mode & 0o777, path: relative, target: await readlink(target), type: "symlink" });
      } else {
        throw new Error(`Source input contains unsupported filesystem entry ${relative}.`);
      }
    }
  };
  await visit(root);
  const digest = createHash("sha256").update(JSON.stringify(entries)).digest("hex");
  return { digest, entries };
}

async function verifySourceTree(
  root: string,
  identity: SourceTreeIdentity,
  allowedGeneratedRoots: readonly string[] = [],
  allowedGeneratedFiles: readonly string[] = [],
): Promise<boolean> {
  if (createHash("sha256").update(JSON.stringify(identity.entries)).digest("hex") !== identity.digest) return false;
  try {
    const actual = await snapshotSourceTree(root, allowedGeneratedRoots, allowedGeneratedFiles);
    return actual.digest === identity.digest && JSON.stringify(actual.entries) === JSON.stringify(identity.entries);
  } catch {
    return false;
  }
}

async function assertDirectoryIdentity(
  target: string,
  identity: FileSystemIdentity,
  requireEmpty = false,
): Promise<void> {
  const inspect = async () => {
    const metadata = await lstat(target);
    if (
      metadata.isSymbolicLink() ||
      !metadata.isDirectory() ||
      metadata.dev !== identity.dev ||
      metadata.ino !== identity.ino
    ) {
      throw new Error("Reserved bootstrap directory identity changed before use.");
    }
  };
  await inspect();
  if (requireEmpty && (await readdir(target)).length !== 0) {
    throw new Error("Reserved bootstrap directory was not empty before use.");
  }
  await inspect();
}

async function reserveTemporaryDirectory(
  parent: string,
  prefix: string,
  platform: NodeJS.Platform,
  command: BootstrapDependencies["command"],
  options: BootstrapIoOptions,
): Promise<TemporaryDirectoryReservation> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(prefix)) {
    throw new Error("Bootstrap temporary-directory prefix is invalid.");
  }
  const parentMetadata = await lstat(parent);
  if (parentMetadata.isSymbolicLink() || !parentMetadata.isDirectory()) {
    throw new Error("Bootstrap temporary-directory parent must be a no-follow directory.");
  }
  const canonicalParent = await realpath(parent);
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const id = options.testHooks?.temporaryDirectoryId?.() ?? randomUUID();
    if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) {
      throw new Error("Bootstrap temporary-directory identifier is invalid.");
    }
    const target = path.join(parent, `${prefix}-${id.toLowerCase()}`);
    try {
      await mkdir(target, { mode: 0o700 });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") continue;
      throw error;
    }
    const created = await lstat(target);
    if (created.isSymbolicLink() || !created.isDirectory()) {
      throw new Error("Exclusive bootstrap temporary-directory reservation was not a directory.");
    }
    let identity: FileSystemIdentity = { dev: created.dev, ino: created.ino };
    options.testHooks?.afterTemporaryDirectoryCreated?.(target);
    await assertDirectoryIdentity(target, identity, true);
    if ((await realpath(path.dirname(target))) !== canonicalParent) {
      throw new Error("Bootstrap temporary-directory parent identity changed during reservation.");
    }
    await chmod(target, 0o700);
    await syncDirectoryForDurability(target);
    await syncDirectoryForDurability(canonicalParent);
    await assertDirectoryIdentity(target, identity, true);
    if (platform === "win32") {
      const nativeIdentity = options.testHooks?.testNativeDirectoryIdentity
        ? await options.testHooks.testNativeDirectoryIdentity(target, identity)
        : await inspectWindowsNativeDirectoryIdentity(target, command, options);
      if (!/^[0-9a-f]{16}:[0-9a-f]{32}$/.test(nativeIdentity)) {
        throw new Error("Windows bootstrap reservation returned an invalid native directory identity.");
      }
      identity = { ...identity, nativeIdentity };
      await assertDirectoryIdentity(target, identity, true);
    }
    return { identity, path: target };
  }
  throw new Error("Unable to reserve a unique bootstrap temporary directory without replacing existing data.");
}

interface NativePromotionResponse {
  code?: string;
  identity?: string;
  native?: number;
  ok: boolean;
  status?: string;
}

function parseNativePromotionResponse(stdout: string): NativePromotionResponse {
  const normalised = stdout.replaceAll("\r\n", "\n").trimEnd();
  if (!normalised || normalised.includes("\n")) {
    throw new Error("Atomic promotion helper returned an invalid response envelope.");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(normalised);
  } catch (error) {
    throw new Error("Atomic promotion helper returned invalid JSON.", { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Atomic promotion helper returned an invalid response schema.");
  }
  const response = parsed as Record<string, unknown>;
  if (response.ok === true && typeof response.status === "string") {
    if (response.status === "present") {
      if (
        Object.keys(response).sort().join(",") !== "identity,ok,status" ||
        typeof response.identity !== "string" ||
        !/^[0-9a-f]{16}:[0-9a-f]{32}$/.test(response.identity)
      ) {
        throw new Error("Atomic promotion helper returned an invalid native identity.");
      }
    } else if (
      !["promoted", "renamed"].includes(response.status) ||
      Object.keys(response).sort().join(",") !== "ok,status"
    ) {
      throw new Error("Atomic promotion helper returned an invalid success response.");
    }
    return response as unknown as NativePromotionResponse;
  }
  if (
    response.ok !== false ||
    typeof response.code !== "string" ||
    !/^[A-Z_]+$/.test(response.code) ||
    !Number.isSafeInteger(response.native) ||
    Number(response.native) < 0 ||
    Object.keys(response).sort().join(",") !== "code,native,ok"
  ) {
    throw new Error("Atomic promotion helper returned an invalid error response.");
  }
  return response as unknown as NativePromotionResponse;
}

function requireAtomicPromotionConfiguration(
  platform: NodeJS.Platform,
  options: BootstrapIoOptions,
): NonNullable<BootstrapIoOptions["atomicPromotion"]> {
  const configured = options.atomicPromotion;
  if (!configured || !/^[0-9a-f]{64}$/.test(configured.expectedHelperSha256)) {
    throw new Error(`Native atomic no-replace promotion is unavailable on ${platform}.`);
  }
  const absolute = configured.protocol === "windows-source-fs"
    ? path.win32.isAbsolute(configured.helper)
    : path.posix.isAbsolute(configured.helper);
  if (!absolute || (platform === "win32") !== (configured.protocol === "windows-source-fs")) {
    throw new Error(`Native atomic no-replace promotion is misconfigured on ${platform}.`);
  }
  return configured;
}

async function runAtomicPromotionHelper(
  platform: NodeJS.Platform,
  command: BootstrapDependencies["command"],
  options: BootstrapIoOptions,
  args: string[],
): Promise<NativePromotionResponse> {
  const configured = requireAtomicPromotionConfiguration(platform, options);
  if (platform !== "win32" || configured.protocol !== "windows-source-fs") {
    throw new Error("External atomic promotion commands are supported only through the Windows source-filesystem helper.");
  }
  const result = await command.run({
    args,
    command: configured.helper,
    env: {},
    expectedExecutableSha256: configured.expectedHelperSha256,
    inheritEnvironment: false,
    timeoutMs: 60_000,
  });
  if (!result.contained) {
    throw new Error("Atomic promotion helper process containment could not be proven.");
  }
  if (result.stdoutTruncated || result.stderrTruncated || result.stderr !== "") {
    throw new Error("Atomic promotion helper returned truncated or unexpected output.");
  }
  const response = parseNativePromotionResponse(result.stdout);
  if (response.ok !== (result.exitCode === 0)) {
    throw new Error("Atomic promotion helper exit status contradicted its response.");
  }
  return response;
}

interface PosixAtomicPromoter {
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

const MAX_ATOMIC_PROMOTER_BYTES = 4 * 1024 * 1024;

function hashDescriptor(descriptor: number, size: number): string {
  const digest = createHash("sha256");
  const buffer = Buffer.allocUnsafe(64 * 1024);
  let offset = 0;
  while (offset < size) {
    const bytesRead = readSync(descriptor, buffer, 0, Math.min(buffer.length, size - offset), offset);
    if (bytesRead <= 0) throw new Error("Packaged atomic promotion module ended before its proved size.");
    digest.update(buffer.subarray(0, bytesRead));
    offset += bytesRead;
  }
  return digest.digest("hex");
}

interface PinnedPosixAtomicPromoterSnapshot {
  descriptor: number;
  linkedDirectory: string | null;
  linkedPath: string | null;
}

function disposePinnedPosixAtomicPromoterSnapshot(snapshot: PinnedPosixAtomicPromoterSnapshot): void {
  if (snapshot.linkedPath) {
    try {
      unlinkSync(snapshot.linkedPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    snapshot.linkedPath = null;
  }
  if (snapshot.linkedDirectory) {
    try {
      rmdirSync(snapshot.linkedDirectory);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    snapshot.linkedDirectory = null;
  }
}

/**
 * Copy a pinned module into a private read-only snapshot before dlopen.
 * Linux unlinks the snapshot before loading; Darwin retains its random name
 * only through synchronous dlopen because library validation rejects an
 * unlinked Mach-O vnode. Loading the original descriptor is insufficient
 * because an in-place writer can mutate that inode after its digest is checked.
 */
function snapshotPinnedPosixAtomicPromoter(
  sourceDescriptor: number,
  sourceSize: number,
  expectedSha256: string,
  platform: NodeJS.Platform,
): PinnedPosixAtomicPromoterSnapshot {
  let directory = "";
  let snapshotPath = "";
  let writer = -1;
  let reader = -1;
  try {
    directory = mkdtempSync(path.join(tmpdir(), "flinttrade-native-module-"));
    chmodSync(directory, 0o700);
    const directoryMetadata = lstatSync(directory);
    const effectiveUser = typeof process.geteuid === "function" ? process.geteuid() : directoryMetadata.uid;
    if (
      directoryMetadata.isSymbolicLink() ||
      !directoryMetadata.isDirectory() ||
      directoryMetadata.uid !== effectiveUser ||
      (directoryMetadata.mode & 0o777) !== 0o700
    ) {
      throw new Error("Private atomic promotion snapshot directory was not owner-bound mode 0700.");
    }

    snapshotPath = path.join(directory, "module.node");
    writer = openSync(
      snapshotPath,
      constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | (constants.O_NOFOLLOW ?? 0),
      0o600,
    );
    const buffer = Buffer.allocUnsafe(64 * 1024);
    let offset = 0;
    while (offset < sourceSize) {
      const bytesRead = readSync(
        sourceDescriptor,
        buffer,
        0,
        Math.min(buffer.length, sourceSize - offset),
        offset,
      );
      if (bytesRead <= 0) throw new Error("Packaged atomic promotion module ended during private snapshot copy.");
      let written = 0;
      while (written < bytesRead) {
        const bytesWritten = writeSync(writer, buffer, written, bytesRead - written, offset + written);
        if (bytesWritten <= 0) throw new Error("Private atomic promotion module snapshot write did not progress.");
        written += bytesWritten;
      }
      offset += bytesRead;
    }
    fsyncSync(writer);
    fchmodSync(writer, 0o400);
    fsyncSync(writer);
    closeSync(writer);
    writer = -1;

    reader = openSync(snapshotPath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    const beforeHash = fstatSync(reader);
    if (
      !beforeHash.isFile() ||
      beforeHash.size !== sourceSize ||
      beforeHash.size <= 0 ||
      beforeHash.size > MAX_ATOMIC_PROMOTER_BYTES ||
      (beforeHash.mode & 0o222) !== 0
    ) {
      throw new Error("Private atomic promotion module snapshot was not a bounded read-only regular file.");
    }
    const digest = hashDescriptor(reader, sourceSize);
    const afterHash = fstatSync(reader);
    if (
      afterHash.dev !== beforeHash.dev ||
      afterHash.ino !== beforeHash.ino ||
      afterHash.size !== beforeHash.size ||
      afterHash.mtimeMs !== beforeHash.mtimeMs ||
      afterHash.ctimeMs !== beforeHash.ctimeMs ||
      digest !== expectedSha256
    ) {
      throw new Error("Private atomic promotion module snapshot failed its build-bound descriptor check.");
    }

    // Linux permits dyld-equivalent loading from an unlinked /proc descriptor.
    // macOS library validation refuses an unlinked Mach-O vnode, so Darwin
    // retains this random mode-0400 name inside the mode-0700 directory only
    // through the synchronous dlopen call and removes it immediately after.
    if (platform !== "darwin") {
      unlinkSync(snapshotPath);
      snapshotPath = "";
      rmdirSync(directory);
      directory = "";
      const unlinked = fstatSync(reader);
      if (unlinked.nlink !== 0 || (unlinked.mode & 0o222) !== 0) {
        throw new Error("Private atomic promotion module snapshot was not unlinked and read-only.");
      }
    }
    const result: PinnedPosixAtomicPromoterSnapshot = {
      descriptor: reader,
      linkedDirectory: directory || null,
      linkedPath: snapshotPath || null,
    };
    reader = -1;
    directory = "";
    snapshotPath = "";
    return result;
  } finally {
    if (writer >= 0) closeSync(writer);
    if (reader >= 0) closeSync(reader);
    if (snapshotPath) {
      try {
        unlinkSync(snapshotPath);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
    if (directory) {
      try {
        rmdirSync(directory);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  }
}

function loadPinnedPosixAtomicPromoter(
  platform: NodeJS.Platform,
  options: BootstrapIoOptions,
): PosixAtomicPromoter {
  const configured = requireAtomicPromotionConfiguration(platform, options);
  if (configured.protocol !== "posix") {
    throw new Error("POSIX atomic promotion requires its packaged native module.");
  }
  const descriptor = openSync(configured.helper, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  let snapshot: PinnedPosixAtomicPromoterSnapshot | null = null;
  try {
    const metadata = fstatSync(descriptor);
    if (!metadata.isFile() || metadata.size <= 0 || metadata.size > MAX_ATOMIC_PROMOTER_BYTES) {
      throw new Error("Packaged atomic promotion module was not a bounded regular file.");
    }
    snapshot = snapshotPinnedPosixAtomicPromoter(
      descriptor,
      metadata.size,
      configured.expectedHelperSha256,
      platform,
    );
    const afterHash = fstatSync(descriptor);
    if (
      afterHash.dev !== metadata.dev ||
      afterHash.ino !== metadata.ino ||
      afterHash.size !== metadata.size ||
      afterHash.mtimeMs !== metadata.mtimeMs ||
      afterHash.ctimeMs !== metadata.ctimeMs ||
      hashDescriptor(descriptor, metadata.size) !== configured.expectedHelperSha256
    ) {
      throw new Error("Packaged atomic promotion module failed its build-bound descriptor check.");
    }
    options.testHooks?.afterAtomicPromotionModulePinned?.(configured.helper);
    const snapshotBeforeLoad = fstatSync(snapshot.descriptor);
    if (
      snapshotBeforeLoad.nlink !== (platform === "darwin" ? 1 : 0) ||
      snapshotBeforeLoad.size !== metadata.size ||
      (snapshotBeforeLoad.mode & 0o222) !== 0 ||
      hashDescriptor(snapshot.descriptor, metadata.size) !== configured.expectedHelperSha256
    ) {
      throw new Error("Private atomic promotion module snapshot changed before load.");
    }
    const loaded = { exports: {} } as NodeModule;
    const descriptorPath = platform === "darwin"
      ? `/dev/fd/${snapshot.descriptor}`
      : `/proc/self/fd/${snapshot.descriptor}`;
    process.dlopen(loaded, descriptorPath);
    disposePinnedPosixAtomicPromoterSnapshot(snapshot);
    const exported = loaded.exports as Partial<PosixAtomicPromoter>;
    if (
      !exported ||
      typeof exported !== "object" ||
      Object.keys(exported).join(",") !== "promoteAbsent" ||
      typeof exported.promoteAbsent !== "function"
    ) {
      throw new Error("Packaged atomic promotion module exposed an invalid N-API surface.");
    }
    return exported as PosixAtomicPromoter;
  } finally {
    if (snapshot) {
      disposePinnedPosixAtomicPromoterSnapshot(snapshot);
      closeSync(snapshot.descriptor);
    }
    closeSync(descriptor);
  }
}

async function inspectWindowsNativeDirectoryIdentity(
  target: string,
  command: BootstrapDependencies["command"],
  options: BootstrapIoOptions,
): Promise<string> {
  const configured = requireAtomicPromotionConfiguration("win32", options);
  if (configured.protocol !== "windows-source-fs") {
    throw new Error("Windows atomic promotion requires the packaged source-filesystem helper.");
  }
  const response = await runAtomicPromotionHelper(
    "win32",
    command,
    options,
    ["--source-fs", "1", "inspect", "--path", target],
  );
  if (!response.ok || response.status !== "present" || !response.identity) {
    throw new Error("Windows bootstrap reservation disappeared before native identity capture.");
  }
  return response.identity;
}

async function promoteAbsent(
  source: string,
  destination: string,
  identity: FileSystemIdentity,
  platform: NodeJS.Platform,
  command: BootstrapDependencies["command"],
  options: BootstrapIoOptions,
  getPosixPromoter: () => PosixAtomicPromoter,
): Promise<void> {
  const sourceParent = await realpath(path.dirname(source));
  const destinationParent = await realpath(path.dirname(destination));
  if (sourceParent !== destinationParent) throw new Error("Candidate and active source must share one canonical parent.");
  const sourceMetadata = await lstat(source);
  if (
    sourceMetadata.isSymbolicLink() ||
    !sourceMetadata.isDirectory() ||
    sourceMetadata.dev !== identity.dev ||
    sourceMetadata.ino !== identity.ino
  ) {
    throw new Error("Candidate directory identity changed at the final promotion boundary.");
  }
  const parentMetadata = await stat(sourceParent);
  if (sourceMetadata.dev !== parentMetadata.dev) throw new Error("Candidate and active source must be on one filesystem.");
  await options.testHooks?.beforeAtomicPromotion?.(source, destination);
  if (options.testHooks?.testAtomicPromote) {
    await options.testHooks.testAtomicPromote(source, destination, identity);
  } else {
    const configured = requireAtomicPromotionConfiguration(platform, options);
    if (platform !== "win32") {
      try {
        getPosixPromoter().promoteAbsent(
          sourceParent,
          path.basename(source),
          path.basename(destination),
          String(identity.dev),
          String(identity.ino),
          String(parentMetadata.dev),
          String(parentMetadata.ino),
        );
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          const occupied = new Error("Promotion destination already exists; refusing to replace it.") as NodeJS.ErrnoException;
          occupied.code = "EEXIST";
          throw occupied;
        }
        throw error;
      }
    } else {
      const response = await runAtomicPromotionHelper(
          platform,
          command,
          options,
          [
            "--source-fs", "1", "rename",
            "--parent", sourceParent,
            "--source", path.basename(source),
            "--destination", path.basename(destination),
            "--expected", identity.nativeIdentity ?? "",
          ],
        );
      if (!response.ok) {
        if (["DESTINATION_OCCUPIED", "DESTINATION_EXISTS"].includes(response.code ?? "")) {
          const error = new Error("Promotion destination already exists; refusing to replace it.") as NodeJS.ErrnoException;
          error.code = "EEXIST";
          throw error;
        }
        throw new Error(`Native atomic promotion was refused (${response.code ?? "UNKNOWN"}).`);
      }
      if (response.status !== "renamed" || configured.protocol !== "windows-source-fs") {
        throw new Error("Native atomic promotion returned an unexpected success status.");
      }
    }
  }
  const promotedMetadata = await lstat(destination);
  let sourceStillExists = true;
  try {
    await lstat(source);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") sourceStillExists = false;
    else throw error;
  }
  if (
    sourceStillExists ||
    promotedMetadata.dev !== sourceMetadata.dev ||
    promotedMetadata.ino !== sourceMetadata.ino ||
    (await realpath(path.dirname(destination))) !== destinationParent
  ) {
    throw new Error("First-run promotion postcondition was ambiguous; refusing to continue.");
  }
  await syncDirectoryForDurability(destinationParent);
}

interface StableArchiveSnapshot {
  dev: number;
  directory: string;
  directoryDev: number;
  directoryIno: number;
  ino: number;
  path: string;
  size: number;
}

async function openNoFollowRegular(target: string) {
  const handle = await open(target, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const metadata = await handle.stat();
    if (!metadata.isFile()) throw new Error("Bootstrap archive must be a no-follow regular file.");
    return { handle, metadata };
  } catch (error) {
    await handle.close();
    throw error;
  }
}

async function createStableArchiveSnapshot(
  archive: string,
  expectedSha256: string,
  signal: AbortSignal,
  options: BootstrapIoOptions,
): Promise<StableArchiveSnapshot> {
  const sourcePathMetadata = await lstat(archive);
  if (sourcePathMetadata.isSymbolicLink() || !sourcePathMetadata.isFile()) {
    throw new Error("Bootstrap archive must be a no-follow regular file.");
  }
  const source = await openNoFollowRegular(archive);
  let destination: FileHandle | null = null;
  try {
    options.testHooks?.beforeArchiveSnapshotSetup?.("directory-create");
    const directory = await mkdtemp(path.join(path.dirname(archive), ".flinttrade-archive-snapshot-"));
    options.testHooks?.beforeArchiveSnapshotSetup?.("directory-inspect");
    const directoryMetadata = await lstat(directory);
    if (directoryMetadata.isSymbolicLink() || !directoryMetadata.isDirectory()) {
      throw new Error("Private bootstrap archive snapshot directory was not an exclusive directory.");
    }
    const snapshotPath = path.join(directory, "archive");
    options.testHooks?.beforeArchiveSnapshotSetup?.("destination-open");
    destination = await open(
      snapshotPath,
      constants.O_RDWR | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
      0o600,
    );
    const hash = createHash("sha256");
    let bytes = 0;
    if (source.metadata.dev !== sourcePathMetadata.dev || source.metadata.ino !== sourcePathMetadata.ino) {
      throw new Error("Bootstrap archive identity changed before its stable snapshot opened.");
    }
    for await (const chunk of source.handle.createReadStream({ autoClose: false })) {
      if (signal.aborted) throw abortError();
      const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      bytes += value.length;
      if (bytes > ARCHIVE_LIMITS.compressedBytes) {
        throw new Error("Bootstrap archive exceeded its compressed size limit.");
      }
      hash.update(value);
      await writeBufferCompletely(destination, value, options.testHooks?.archiveSnapshotWriteChunkBytes);
    }
    if (signal.aborted) throw abortError();
    const sourceAfter = await source.handle.stat();
    if (
      sourceAfter.dev !== source.metadata.dev ||
      sourceAfter.ino !== source.metadata.ino ||
      sourceAfter.size !== source.metadata.size ||
      bytes !== source.metadata.size
    ) {
      throw new Error("Bootstrap archive identity changed while its stable snapshot was created.");
    }
    const digest = hash.digest("hex");
    if (digest !== expectedSha256) throw new Error("Bootstrap archive checksum changed before extraction.");
    await destination.sync();
    const metadata = await destination.stat();
    options.testHooks?.beforeArchiveSnapshotVerify?.(snapshotPath);
    const snapshotPathMetadata = await lstat(snapshotPath);
    if (
      snapshotPathMetadata.isSymbolicLink() ||
      !snapshotPathMetadata.isFile() ||
      snapshotPathMetadata.dev !== metadata.dev ||
      snapshotPathMetadata.ino !== metadata.ino
    ) {
      throw new Error("Private bootstrap archive snapshot identity changed before verification.");
    }
    const copiedHash = createHash("sha256");
    let copiedBytes = 0;
    for await (const chunk of destination.createReadStream({ autoClose: false, start: 0 })) {
      if (signal.aborted) throw abortError();
      const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      copiedBytes += value.length;
      copiedHash.update(value);
    }
    const verifiedMetadata = await destination.stat();
    if (
      verifiedMetadata.dev !== metadata.dev ||
      verifiedMetadata.ino !== metadata.ino ||
      verifiedMetadata.size !== bytes ||
      copiedBytes !== bytes ||
      copiedHash.digest("hex") !== expectedSha256
    ) {
      throw new Error("Private bootstrap archive snapshot failed size or checksum verification.");
    }
    return {
      dev: verifiedMetadata.dev,
      directory,
      directoryDev: directoryMetadata.dev,
      directoryIno: directoryMetadata.ino,
      ino: verifiedMetadata.ino,
      path: snapshotPath,
      size: copiedBytes,
    };
  } finally {
    await destination?.close().catch(() => undefined);
    await source.handle.close().catch(() => undefined);
  }
}

async function openStableSnapshot(snapshot: StableArchiveSnapshot) {
  const opened = await openNoFollowRegular(snapshot.path);
  if (
    opened.metadata.dev !== snapshot.dev ||
    opened.metadata.ino !== snapshot.ino ||
    opened.metadata.size !== snapshot.size
  ) {
    await opened.handle.close();
    throw new Error("Private bootstrap archive snapshot identity changed.");
  }
  return opened.handle;
}

async function preserveStableSnapshot(
  snapshot: StableArchiveSnapshot,
  hooks?: BootstrapIoOptions["testHooks"],
): Promise<void> {
  hooks?.onArchiveSnapshotRemove?.(snapshot.path, snapshot.directory);
  const [snapshotMetadata, directoryMetadata] = await Promise.all([
    lstat(snapshot.path),
    lstat(snapshot.directory),
  ]);
  if (
    snapshotMetadata.isSymbolicLink() ||
    !snapshotMetadata.isFile() ||
    snapshotMetadata.dev !== snapshot.dev ||
    snapshotMetadata.ino !== snapshot.ino ||
    snapshotMetadata.size !== snapshot.size ||
    directoryMetadata.isSymbolicLink() ||
    !directoryMetadata.isDirectory() ||
    directoryMetadata.dev !== snapshot.directoryDev ||
    directoryMetadata.ino !== snapshot.directoryIno
  ) {
    throw new Error("Private bootstrap archive snapshot cleanup identity changed; preserving all paths.");
  }
  // Node does not expose an identity-bound unlink primitive. Even after the
  // proof above, a pathname unlink would reopen a swap window and could remove
  // a foreign replacement. Preserve this private, UUID-named snapshot instead;
  // bounded user-mediated maintenance can clean it without risking data loss.
}

function tarEntryMetadata(entry: tar.ReadEntry): ValidatedArchiveEntry {
  const kinds: Partial<Record<string, ArchiveEntryKind>> = {
    Directory: "directory",
    File: "file",
    Link: "hardlink",
    OldFile: "file",
    SymbolicLink: "symlink",
  };
  const kind = kinds[entry.type];
  if (!kind) throw new Error(`tar archive contains unsupported ${entry.type} entry.`);
  return {
    kind,
    mode: entry.mode ?? 0,
    name: entry.path,
    size: kind === "file" ? entry.size : 0,
    ...((kind === "hardlink" || kind === "symlink") && entry.linkpath ? { target: entry.linkpath } : {}),
  };
}

async function listTarArchive(
  snapshot: StableArchiveSnapshot,
  signal: AbortSignal,
  expectedRoot: string | undefined,
  hooks: BootstrapIoOptions["testHooks"],
): Promise<ValidatedArchiveEntry[]> {
  const validator = new ArchiveValidator("tar", expectedRoot);
  let validationFailure: unknown;
  let index = 0;
  const parser = tar.list({
    onentry(entry) {
      try {
        if (signal.aborted) throw abortError();
        hooks?.onArchiveEntry?.(index, "tar.gz");
        index += 1;
        validator.add(tarEntryMetadata(entry));
      } catch (error) {
        validationFailure ??= error;
      }
      entry.resume();
    },
    preservePaths: false,
    strict: true,
  });
  const handle = await openStableSnapshot(snapshot);
  try {
    await pipeline(handle.createReadStream({ autoClose: false }), parser, { signal });
  } finally {
    await handle.close();
  }
  if (validationFailure) throw validationFailure;
  return validator.complete();
}

async function openStableZip(
  snapshot: StableArchiveSnapshot,
  hooks?: BootstrapIoOptions["testHooks"],
): Promise<yauzl.ZipFile> {
  const fd = await new Promise<number>((resolve, reject) => {
    openFd(snapshot.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0), (error, openedFd) => {
      if (error) reject(error);
      else resolve(openedFd);
    });
  });
  const closeRawFd = () =>
    new Promise<void>((resolve, reject) => {
      closeFd(fd, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  hooks?.onZipSnapshotHandle?.("opened");
  try {
    const metadata = await new Promise<import("node:fs").Stats>((resolve, reject) => {
      fstatFd(fd, (error, result) => {
        if (error) reject(error);
        else resolve(result);
      });
    });
    if (
      !metadata.isFile() ||
      metadata.dev !== snapshot.dev ||
      metadata.ino !== snapshot.ino ||
      metadata.size !== snapshot.size
    ) {
      throw new Error("Private bootstrap archive snapshot identity changed.");
    }
    const zip = await new Promise<yauzl.ZipFile>((resolve, reject) => {
      yauzl.fromFd(
        fd,
        { autoClose: false, lazyEntries: true, strictFileNames: true, validateEntrySizes: true },
        (error, opened) => {
          if (error || !opened) reject(error ?? new Error("Could not open ZIP archive."));
          else resolve(opened);
        },
      );
    });
    return zip;
  } catch (error) {
    await closeRawFd();
    hooks?.onZipSnapshotHandle?.("closed");
    throw error;
  }
}

async function closeStableZip(
  zip: yauzl.ZipFile,
  hooks?: BootstrapIoOptions["testHooks"],
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const onClose = () => {
      zip.removeListener("error", onCloseError);
      resolve();
    };
    const onCloseError = (error: unknown) => {
      zip.removeListener("close", onClose);
      reject(error);
    };
    zip.once("close", onClose);
    zip.once("error", onCloseError);
    try {
      zip.close();
    } catch (error) {
      zip.removeListener("close", onClose);
      zip.removeListener("error", onCloseError);
      reject(error);
    }
  });
  hooks?.onZipSnapshotHandle?.("closed");
}

function zipEntryKind(entry: yauzl.Entry): { kind: "directory" | "file"; mode: number } {
  const mode = (entry.externalFileAttributes >>> 16) & 0xffff;
  const type = mode & 0o170000;
  const directory = entry.fileName.endsWith("/");
  if (type === 0o120000) throw new Error("zip archive contains a link entry.");
  if (type !== 0 && type !== 0o100000 && type !== 0o040000) {
    throw new Error("zip archive contains an unsupported special entry.");
  }
  return { kind: directory ? "directory" : "file", mode };
}

async function listZipArchive(
  snapshot: StableArchiveSnapshot,
  signal: AbortSignal,
  expectedRoot: string | undefined,
  hooks: BootstrapIoOptions["testHooks"],
): Promise<ValidatedArchiveEntry[]> {
  const zip = await openStableZip(snapshot, hooks);
  const validator = new ArchiveValidator("zip", expectedRoot);
  return new Promise((resolve, reject) => {
    let index = 0;
    let settled = false;
    const close = async () => {
      signal.removeEventListener("abort", onAbort);
      await closeStableZip(zip, hooks);
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      void close().then(
        () => reject(error),
        (closeError) => reject(new AggregateError([error, closeError], "ZIP listing failed and did not close cleanly.")),
      );
    };
    const onAbort = () => fail(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    zip.on("error", fail);
    zip.on("entry", (entry) => {
      try {
        if (signal.aborted) throw abortError();
        hooks?.onArchiveEntry?.(index, "zip");
        index += 1;
        const metadata = zipEntryKind(entry);
        validator.add({ ...metadata, name: entry.fileName, size: entry.uncompressedSize });
        zip.readEntry();
      } catch (error) {
        fail(error);
      }
    });
    zip.on("end", () => {
      try {
        const entries = validator.complete();
        settled = true;
        void close().then(() => resolve(entries), reject);
      } catch (error) {
        fail(error);
      }
    });
    zip.readEntry();
  });
}

async function extractZipArchive(
  snapshot: StableArchiveSnapshot,
  destination: string,
  expected: ValidatedArchiveEntry[],
  signal: AbortSignal,
  hooks?: BootstrapIoOptions["testHooks"],
  stripExpectedRoot?: string,
): Promise<void> {
  const zip = await openStableZip(snapshot, hooks);
  let index = 0;
  await new Promise<void>((resolve, reject) => {
    let working = false;
    let settled = false;
    const replay = new ArchiveValidator("zip");
    const close = async () => {
      signal.removeEventListener("abort", onAbort);
      await closeStableZip(zip, hooks);
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      void close().then(
        () => reject(error),
        (closeError) => reject(new AggregateError([error, closeError], "ZIP extraction failed and did not close cleanly.")),
      );
    };
    const onAbort = () => fail(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    zip.on("error", fail);
    zip.on("entry", (entry) => {
      if (working) return fail(new Error("ZIP parser emitted overlapping entries."));
      working = true;
      void (async () => {
        if (signal.aborted) throw abortError();
        const expectedEntry = expected[index];
        const metadata = zipEntryKind(entry);
        const name = entry.fileName.replace(/\/+$/, "");
        const actual = { ...metadata, name: entry.fileName, size: entry.uncompressedSize };
        replay.add(actual);
        const replayed = replay.entries.at(-1);
        if (!expectedEntry || JSON.stringify(expectedEntry) !== JSON.stringify(replayed)) {
          throw new Error("ZIP archive changed between validation and extraction.");
        }
        const relativeName = stripExpectedRoot
          ? name === stripExpectedRoot
            ? ""
            : name.slice(stripExpectedRoot.length + 1)
          : name;
        if (!relativeName) {
          if (metadata.kind !== "directory") throw new Error("ZIP archive root was not a directory.");
          index += 1;
          working = false;
          zip.readEntry();
          return;
        }
        const target = path.join(destination, ...relativeName.split("/"));
        if (metadata.kind === "directory") {
          await mkdir(target, { mode: 0o700, recursive: true });
        } else {
          await mkdir(path.dirname(target), { mode: 0o700, recursive: true });
          const source = await new Promise<NodeJS.ReadableStream>((resolveStream, rejectStream) => {
            zip.openReadStream(entry, (error, stream) => {
              if (error || !stream) rejectStream(error ?? new Error("Could not read ZIP entry."));
              else resolveStream(stream);
            });
          });
          const mode = metadata.mode & 0o777;
          await pipeline(source, createWriteStream(target, { flags: "wx", mode: mode || 0o600 }), { signal });
        }
        index += 1;
        working = false;
        zip.readEntry();
      })().catch(fail);
    });
    zip.on("end", () => {
      try {
        replay.complete();
        if (index !== expected.length) throw new Error("ZIP archive changed between validation and extraction.");
        settled = true;
        void close().then(resolve, reject);
      } catch (error) {
        fail(error);
      }
    });
    zip.readEntry();
  });
}

async function extractTarArchive(
  snapshot: StableArchiveSnapshot,
  destination: string,
  expected: ValidatedArchiveEntry[],
  signal: AbortSignal,
): Promise<void> {
  const replay = new ArchiveValidator("tar");
  let index = 0;
  let validationFailure: unknown;
  const extractor = tar.extract({
    cwd: destination,
    onentry(entry) {
      try {
        if (signal.aborted) throw abortError();
        replay.add(tarEntryMetadata(entry));
        if (JSON.stringify(expected[index]) !== JSON.stringify(replay.entries.at(-1))) {
          throw new Error("TAR archive changed between validation and extraction.");
        }
        index += 1;
      } catch (error) {
        validationFailure ??= error;
      }
    },
    preservePaths: false,
    strict: true,
  });
  const extractorClosed = new Promise<void>((resolve) => {
    extractor.once("close", resolve);
  });
  const onAbort = () => {
    const error = new Error("Operation cancelled.");
    error.name = "AbortError";
    extractor.abort(error);
  };
  signal.addEventListener("abort", onAbort, { once: true });
  const handle = await openStableSnapshot(snapshot);
  try {
    if (signal.aborted) onAbort();
    try {
      await pipeline(handle.createReadStream({ autoClose: false }), extractor, { signal });
    } catch (error) {
      await extractorClosed;
      throw error;
    }
  } finally {
    signal.removeEventListener("abort", onAbort);
    await handle.close();
  }
  if (validationFailure) throw validationFailure;
  replay.complete();
  if (index !== expected.length) throw new Error("TAR archive changed between validation and extraction.");
}

function createArchiveExtractor(options: BootstrapIoOptions): BootstrapDependencies["extractArchive"] {
  return async ({
    archive,
    destination,
    destinationIdentity,
    expectedRoot,
    expectedSha256,
    kind,
    signal,
    stripExpectedRoot,
  }) => {
    const snapshot = await createStableArchiveSnapshot(archive, expectedSha256, signal, options);
    try {
      let ownedIdentity = destinationIdentity;
      if (ownedIdentity) {
        await assertDirectoryIdentity(destination, ownedIdentity, true);
      } else {
        await mkdir(destination, { mode: 0o700 });
        const metadata = await lstat(destination);
        if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
          throw new Error("Extraction destination is not an exclusively created directory.");
        }
        ownedIdentity = { dev: metadata.dev, ino: metadata.ino };
      }
      if (stripExpectedRoot && (!expectedRoot || kind !== "zip")) {
        throw new Error("Archive root stripping requires one validated ZIP root.");
      }
      const entries =
        kind === "tar.gz"
          ? await listTarArchive(snapshot, signal, expectedRoot, options.testHooks)
          : await listZipArchive(snapshot, signal, expectedRoot, options.testHooks);
      await assertDirectoryIdentity(destination, ownedIdentity, true);
      if (kind === "tar.gz") await extractTarArchive(snapshot, destination, entries, signal);
      else {
        await extractZipArchive(
          snapshot,
          destination,
          entries,
          signal,
          options.testHooks,
          stripExpectedRoot ? expectedRoot : undefined,
        );
      }
      await assertDirectoryIdentity(destination, ownedIdentity);
      await assertExtractedTreeConfined(destination);
      return entries.map((entry) => entry.name);
    } finally {
      await preserveStableSnapshot(snapshot, options.testHooks);
    }
  };
}

export async function syncDirectoryForDurability(directory: string): Promise<void> {
  try {
    const handle = await open(directory, "r");
    try {
      await handle.sync();
    } finally {
      await handle.close();
    }
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (process.platform !== "win32" || !["EACCES", "EINVAL", "EISDIR", "EPERM"].includes(code ?? "")) throw error;
  }
}

interface OperationLeaseOwner {
  acquiredAt: string;
  bootIdentity: string;
  operationId: string;
  ownerPid: number;
}

const activeOperationLeases = new Map<string, string>();
const MAX_PRESERVED_WINDOWS_OPERATION_LEASE_QUARANTINES = 64;

function sameFileSystemIdentity(left: FileSystemIdentity, right: FileSystemIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.nativeIdentity === right.nativeIdentity
  );
}

function sameLeaseRecoveryScope(left: OperationLeaseDirectory, right: OperationLeaseDirectory): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.ownerPresent === right.ownerPresent &&
    JSON.stringify(left.owner) === JSON.stringify(right.owner) &&
    JSON.stringify(left.processGroups) === JSON.stringify(right.processGroups) &&
    JSON.stringify(left.processRecordNames) === JSON.stringify(right.processRecordNames) &&
    JSON.stringify(left.supervisorPids) === JSON.stringify(right.supervisorPids)
  );
}

function hasExactObjectKeys(value: unknown, expected: readonly string[]): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort())
  );
}

function parseOperationLeaseOwner(content: string): OperationLeaseOwner {
  const parsed = JSON.parse(content) as unknown;
  if (
    !hasExactObjectKeys(parsed, ["acquiredAt", "bootIdentity", "operationId", "ownerPid"]) ||
    typeof parsed.acquiredAt !== "string" ||
    typeof parsed.bootIdentity !== "string" ||
    typeof parsed.operationId !== "string" ||
    !Number.isSafeInteger(parsed.ownerPid) ||
    (parsed.ownerPid as number) <= 0
  ) {
    throw new Error("Source operation lease owner record is invalid.");
  }
  return parsed as unknown as OperationLeaseOwner;
}

interface OperationLeaseDirectory {
  dev: number;
  ino: number;
  owner: OperationLeaseOwner | null;
  ownerPresent: boolean;
  processGroups: Array<{ containmentToken: string | null; processGroupId: number }>;
  processRecordNames: string[];
  supervisorPids: number[];
}

const OPERATION_PROCESS_GROUP_PATTERN = /^process-group-([1-9][0-9]*)\.json$/;
const OPERATION_SUPERVISOR_PATTERN = /^windows-supervisor-([1-9][0-9]*)\.json$/;
const OPERATION_PROCESS_PUBLICATION_PATTERN = /^\.(process-group|windows-supervisor)-([1-9][0-9]*)\.publishing-([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json$/i;

function posixProcessGroupExists(processGroupId: number): boolean {
  try {
    process.kill(-processGroupId, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    if ((error as NodeJS.ErrnoException).code === "EPERM") return true;
    throw error;
  }
}

function processExists(processId: number): boolean {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    if ((error as NodeJS.ErrnoException).code === "EPERM") return true;
    throw error;
  }
}

async function enumerateTaggedPosixProcesses(
  containmentTokens: readonly string[],
  enumerators: readonly string[],
): Promise<number[]> {
  if (containmentTokens.length === 0) return [];
  if (
    containmentTokens.some((token) => !WINDOWS_SUPERVISOR_TOKEN.test(token)) ||
    enumerators.length === 0 ||
    enumerators.some((enumerator) => !enumerator.startsWith("/") || !/^\/[A-Za-z0-9._/-]+$/.test(enumerator))
  ) {
    throw new Error("Durable POSIX containment metadata is invalid.");
  }
  const markers = containmentTokens.map((token) => `FLINTTRADE_PROCESS_ANCHOR=${token}`);
  const enumerationArguments = [
    ...(process.platform === "darwin" ? ["-Eww", "-ax"] : ["axeww"]),
    "-o",
    "pid=",
    "-o",
    "ppid=",
    "-o",
    "pgid=",
    "-o",
    "command=",
  ];
  let lastError: Error | null = null;
  for (const enumerator of enumerators) {
    try {
      return await new Promise<number[]>((resolve, reject) => {
        const child = spawn(
          enumerator,
          enumerationArguments,
          {
            env: { LANG: "C", LC_ALL: "C", PATH: "/usr/bin:/bin" },
            stdio: ["ignore", "pipe", "ignore"],
            windowsHide: true,
          },
        );
        let output = "";
        let failure: Error | null = null;
        const timer = setTimeout(() => {
          failure ??= new Error("Trusted POSIX process enumeration timed out.");
          child.kill("SIGKILL");
        }, 5_000);
        timer.unref?.();
        child.stdout?.setEncoding("utf8");
        child.stdout?.on("data", (chunk: string) => {
          if (failure) return;
          output += chunk;
          if (Buffer.byteLength(output, "utf8") > 32 * 1024 * 1024) {
            failure = new Error("Trusted POSIX process enumeration exceeded its output bound.");
            child.kill("SIGKILL");
          }
        });
        child.once("error", (error) => {
          failure ??= error;
        });
        child.once("close", (code) => {
          clearTimeout(timer);
          if (failure) return reject(failure);
          if (code !== 0) return reject(new Error(`Trusted POSIX process enumeration exited ${String(code)}.`));
          const processIds = new Set<number>();
          for (const line of output.split(/\r?\n/)) {
            const padded = ` ${line} `;
            if (!markers.some((marker) => padded.includes(` ${marker} `))) continue;
            const match = /^\s*([1-9][0-9]*)\s+/.exec(line);
            if (!match) return reject(new Error("Trusted POSIX process enumeration returned an invalid tagged row."));
            const processId = Number(match[1]);
            if (!Number.isSafeInteger(processId)) {
              return reject(new Error("Trusted POSIX process enumeration returned an invalid PID."));
            }
            processIds.add(processId);
          }
          resolve([...processIds].sort((left, right) => left - right));
        });
      });
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw new Error(`Trusted POSIX process enumeration was unavailable: ${lastError?.message ?? "no enumerator succeeded"}`);
}

async function waitForRecordedProcessesGone(
  processGroups: ReadonlyArray<{ containmentToken: string | null; processGroupId: number }>,
  supervisorPids: readonly number[],
  timeoutMs = 6_000,
  enumerators: readonly string[] = ["/bin/ps", "/usr/bin/ps"],
): Promise<void> {
  const startedAt = Date.now();
  const deadline = Date.now() + timeoutMs;
  let emptyScans = 0;
  const containmentTokens = processGroups.flatMap(({ containmentToken }) =>
    containmentToken ? [containmentToken] : [],
  );
  while (true) {
    const liveGroup = processGroups.find(({ processGroupId }) => posixProcessGroupExists(processGroupId));
    const liveSupervisor = supervisorPids.find((supervisorPid) => processExists(supervisorPid));
    const taggedProcesses =
      liveGroup === undefined
        ? await enumerateTaggedPosixProcesses(containmentTokens, enumerators)
        : [];
    if (liveGroup === undefined && liveSupervisor === undefined && taggedProcesses.length === 0) {
      if (containmentTokens.length === 0 || ++emptyScans >= 2) return;
    } else {
      emptyScans = 0;
      const signal = Date.now() - startedAt >= 1_000 ? "SIGKILL" : "SIGTERM";
      for (const processId of taggedProcesses) {
        try {
          process.kill(processId, signal);
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
        }
      }
    }
    if (Date.now() >= deadline) {
      if (liveGroup !== undefined) {
        throw new Error(`Source operation lease process group ${liveGroup.processGroupId} is still alive.`);
      }
      if (taggedProcesses.length > 0) {
        throw new Error(`Source operation lease tagged POSIX process ${taggedProcesses[0]} is still alive.`);
      }
      throw new Error(`Source operation lease Windows supervisor ${liveSupervisor} is still alive.`);
    }
    await delay(20);
  }
}

async function validateOperationLeaseDirectory(
  target: string,
  allowInvalidOwner = false,
): Promise<OperationLeaseDirectory> {
  const metadata = await lstat(target);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error("Source operation lease path must be a no-follow directory.");
  }
  const entries = (await readdir(target)).sort();
  const groupEntries = entries.filter((entry) => OPERATION_PROCESS_GROUP_PATTERN.test(entry));
  const supervisorEntries = entries.filter((entry) => OPERATION_SUPERVISOR_PATTERN.test(entry));
  const publicationEntries = entries.filter((entry) => OPERATION_PROCESS_PUBLICATION_PATTERN.test(entry));
  if (
    entries.some(
      (entry) =>
        entry !== "owner.json" &&
        !OPERATION_PROCESS_GROUP_PATTERN.test(entry) &&
        !OPERATION_SUPERVISOR_PATTERN.test(entry) &&
        !OPERATION_PROCESS_PUBLICATION_PATTERN.test(entry),
    ) ||
    (publicationEntries.length > 0 && !allowInvalidOwner)
  ) {
    throw new Error("Source operation lease contains unexpected entries.");
  }
  const processGroups: Array<{ containmentToken: string | null; processGroupId: number }> = [];
  const finalProcessRecordOwners: Array<{ operationId: string; ownerPid: number }> = [];
  for (const entry of groupEntries) {
    const match = OPERATION_PROCESS_GROUP_PATTERN.exec(entry)!;
    const processGroupId = Number(match[1]);
    if (!Number.isSafeInteger(processGroupId)) throw new Error("Source operation lease process-group record is invalid.");
    const groupMetadata = await lstat(path.join(target, entry));
    if (groupMetadata.isSymbolicLink() || !groupMetadata.isFile() || groupMetadata.size > 16 * 1024) {
      throw new Error("Source operation lease process-group record must be a bounded no-follow regular file.");
    }
    const parsed = JSON.parse(await readNoFollowRegularText(path.join(target, entry))) as unknown;
    if (
      !hasExactObjectKeys(parsed, ["containmentToken", "kind", "operationId", "ownerPid", "processId", "protocol"]) ||
      parsed.protocol !== 1 ||
      parsed.kind !== "posix-group" ||
      parsed.processId !== processGroupId ||
      typeof parsed.operationId !== "string" ||
      !Number.isSafeInteger(parsed.ownerPid) ||
      (parsed.ownerPid as number) <= 0 ||
      typeof parsed.containmentToken !== "string" ||
      !WINDOWS_SUPERVISOR_TOKEN.test(parsed.containmentToken)
    ) {
      throw new Error("Source operation lease process-group record is invalid.");
    }
    processGroups.push({ containmentToken: parsed.containmentToken, processGroupId });
    finalProcessRecordOwners.push({ operationId: parsed.operationId, ownerPid: parsed.ownerPid as number });
  }
  const supervisorPids: number[] = [];
  for (const entry of supervisorEntries) {
    const match = OPERATION_SUPERVISOR_PATTERN.exec(entry)!;
    const supervisorPid = Number(match[1]);
    if (!Number.isSafeInteger(supervisorPid)) throw new Error("Source operation lease supervisor record is invalid.");
    const supervisorMetadata = await lstat(path.join(target, entry));
    if (supervisorMetadata.isSymbolicLink() || !supervisorMetadata.isFile() || supervisorMetadata.size > 16 * 1024) {
      throw new Error("Source operation lease supervisor record must be a bounded no-follow regular file.");
    }
    const parsed = JSON.parse(await readNoFollowRegularText(path.join(target, entry))) as unknown;
    if (
      !hasExactObjectKeys(parsed, ["kind", "operationId", "ownerPid", "processId", "protocol"]) ||
      parsed.protocol !== 1 ||
      parsed.kind !== "windows-supervisor" ||
      parsed.processId !== supervisorPid ||
      typeof parsed.operationId !== "string" ||
      !Number.isSafeInteger(parsed.ownerPid) ||
      (parsed.ownerPid as number) <= 0
    ) {
      throw new Error("Source operation lease supervisor record is invalid.");
    }
    supervisorPids.push(supervisorPid);
    finalProcessRecordOwners.push({ operationId: parsed.operationId, ownerPid: parsed.ownerPid as number });
  }
  for (const entry of publicationEntries) {
    const match = OPERATION_PROCESS_PUBLICATION_PATTERN.exec(entry)!;
    const kind = match[1];
    const processId = Number(match[2]);
    if (!Number.isSafeInteger(processId)) throw new Error("Source operation lease publication record is invalid.");
    const publicationMetadata = await lstat(path.join(target, entry));
    if (
      publicationMetadata.isSymbolicLink() ||
      !publicationMetadata.isFile() ||
      publicationMetadata.size > 16 * 1024
    ) {
      throw new Error("Source operation lease publication record must be a bounded no-follow regular file.");
    }
    if (kind === "process-group") processGroups.push({ containmentToken: null, processGroupId: processId });
    else supervisorPids.push(processId);
  }
  const processRecordNames = [...groupEntries, ...supervisorEntries, ...publicationEntries].sort();
  const ownerPresent = entries.includes("owner.json");
  if (!ownerPresent) {
    if (!allowInvalidOwner) throw new Error("Source operation lease owner record is missing.");
    if (finalProcessRecordOwners.length > 0) {
      throw new Error("Source operation lease final process record is not bound to a valid owner.");
    }
    return {
      dev: metadata.dev,
      ino: metadata.ino,
      owner: null,
      ownerPresent: false,
      processGroups,
      processRecordNames,
      supervisorPids,
    };
  }
  const ownerPath = path.join(target, "owner.json");
  const ownerMetadata = await lstat(ownerPath);
  if (ownerMetadata.isSymbolicLink() || !ownerMetadata.isFile()) {
    throw new Error("Source operation lease owner record must be a no-follow regular file.");
  }
  const ownerHandle = await open(ownerPath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const openedOwner = await ownerHandle.stat();
    if (
      !openedOwner.isFile() ||
      openedOwner.dev !== ownerMetadata.dev ||
      openedOwner.ino !== ownerMetadata.ino
    ) {
      throw new Error("Source operation lease owner record identity changed during validation.");
    }
    let owner: OperationLeaseOwner | null = null;
    try {
      if (openedOwner.size > 16 * 1024) throw new Error("Source operation lease owner record is too large.");
      owner = parseOperationLeaseOwner(await ownerHandle.readFile("utf8"));
    } catch (error) {
      if (!allowInvalidOwner) throw error;
    }
    if (
      finalProcessRecordOwners.some(
        (recordOwner) =>
          !owner || recordOwner.operationId !== owner.operationId || recordOwner.ownerPid !== owner.ownerPid,
      )
    ) {
      throw new Error("Source operation lease final process record is not bound to its owner.");
    }
    return {
      dev: metadata.dev,
      ino: metadata.ino,
      owner,
      ownerPresent: true,
      processGroups,
      processRecordNames,
      supervisorPids,
    };
  } finally {
    await ownerHandle.close();
  }
}

async function registerOperationProcessAnchor(
  leaseTarget: string,
  processId: number,
  kind: "posix-group" | "windows-supervisor",
  containmentToken: string | null,
  testHooks?: BootstrapIoOptions["testHooks"],
): Promise<() => Promise<void>> {
  if (!Number.isSafeInteger(processId) || processId <= 0) {
    throw new Error("Bootstrap process-anchor registration requires a positive safe PID.");
  }
  if (
    (kind === "posix-group" && (!containmentToken || !WINDOWS_SUPERVISOR_TOKEN.test(containmentToken))) ||
    (kind === "windows-supervisor" && containmentToken !== null)
  ) {
    throw new Error("Bootstrap process-anchor containment token is invalid.");
  }
  const lease = await validateOperationLeaseDirectory(leaseTarget);
  if (lease.owner?.ownerPid !== process.pid || lease.processGroups.length !== 0 || lease.supervisorPids.length !== 0) {
    throw new Error("Bootstrap process-anchor registration is not bound to this lease owner.");
  }
  const record = {
    ...(containmentToken ? { containmentToken } : {}),
    kind,
    operationId: lease.owner.operationId,
    ownerPid: process.pid,
    processId,
    protocol: 1,
  };
  const recordKind = kind === "posix-group" ? "process-group" : "windows-supervisor";
  const recordName = `${recordKind}-${processId}.json`;
  const recordPath = path.join(leaseTarget, recordName);
  const publicationPath = path.join(
    leaseTarget,
    `.${recordKind}-${processId}.publishing-${randomUUID()}.json`,
  );
  const handle = await open(
    publicationPath,
    constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
    0o600,
  );
  let finalPublished = false;
  try {
    await writeBufferCompletely(handle, Buffer.from(`${JSON.stringify(record)}\n`, "utf8"));
    await handle.sync();
    const written = await handle.stat();
    const publication = await lstat(publicationPath);
    if (
      !written.isFile() ||
      publication.isSymbolicLink() ||
      !publication.isFile() ||
      publication.dev !== written.dev ||
      publication.ino !== written.ino
    ) {
      throw new Error("Bootstrap process-anchor publication identity changed before commit.");
    }
    await link(publicationPath, recordPath);
    finalPublished = true;
    const [afterHandle, finalRecord, afterPublication] = await Promise.all([
      handle.stat(),
      lstat(recordPath),
      lstat(publicationPath),
    ]);
    if (
      !finalRecord.isFile() ||
      finalRecord.isSymbolicLink() ||
      finalRecord.dev !== written.dev ||
      finalRecord.ino !== written.ino ||
      afterPublication.dev !== written.dev ||
      afterPublication.ino !== written.ino ||
      afterHandle.dev !== written.dev ||
      afterHandle.ino !== written.ino ||
      afterHandle.size !== written.size
    ) {
      throw new Error("Bootstrap process-anchor publication identity changed during commit.");
    }
    await syncDirectoryForDurability(leaseTarget);
    await unlink(publicationPath);
    await syncDirectoryForDurability(leaseTarget);
  } catch (error) {
    if (!finalPublished) await unlink(publicationPath).catch(() => undefined);
    throw error;
  } finally {
    await handle.close();
  }
  const published = await validateOperationLeaseDirectory(leaseTarget);
  if (
    published.dev !== lease.dev ||
    published.ino !== lease.ino ||
    published.owner?.operationId !== lease.owner.operationId ||
    (kind === "posix-group"
      ? published.processGroups.length !== 1 ||
        published.processGroups[0]?.processGroupId !== processId ||
        published.processGroups[0]?.containmentToken !== containmentToken ||
        published.supervisorPids.length !== 0
      : published.supervisorPids.length !== 1 || published.supervisorPids[0] !== processId || published.processGroups.length !== 0) ||
    (await readNoFollowRegularText(recordPath)) !== `${JSON.stringify(record)}\n`
  ) {
    throw new Error("Bootstrap process group registration changed during durable publication.");
  }

  let recordRemoved = false;
  let directorySynced = false;
  return async () => {
    if (directorySynced) return;
    if (!recordRemoved) {
      const current = await validateOperationLeaseDirectory(leaseTarget);
      if (
        current.dev !== lease.dev ||
        current.ino !== lease.ino ||
        current.owner?.operationId !== lease.owner?.operationId ||
        (kind === "posix-group"
          ? current.processGroups.length !== 1 ||
            current.processGroups[0]?.processGroupId !== processId ||
            current.processGroups[0]?.containmentToken !== containmentToken ||
            current.supervisorPids.length !== 0
          : current.supervisorPids.length !== 1 || current.supervisorPids[0] !== processId || current.processGroups.length !== 0) ||
        (await readNoFollowRegularText(recordPath)) !== `${JSON.stringify(record)}\n`
      ) {
        throw new Error("Bootstrap process group registration identity changed before release.");
      }
      testHooks?.beforeProcessAnchorReleaseStage?.("record-unlink");
      await unlink(recordPath);
      recordRemoved = true;
    }
    const afterUnlink = await validateOperationLeaseDirectory(leaseTarget);
    if (
      afterUnlink.dev !== lease.dev ||
      afterUnlink.ino !== lease.ino ||
      afterUnlink.owner?.operationId !== lease.owner?.operationId ||
      afterUnlink.processGroups.length !== 0 ||
      afterUnlink.supervisorPids.length !== 0
    ) {
      throw new Error("Bootstrap process group registration identity changed after release.");
    }
    testHooks?.beforeProcessAnchorReleaseStage?.("directory-sync");
    await syncDirectoryForDurability(leaseTarget);
    directorySynced = true;
  };
}

function sameOperationContainmentScope(
  expected: OperationLeaseDirectory,
  current: OperationLeaseDirectory,
): boolean {
  const expectedOwner = expected.owner;
  const currentOwner = current.owner;
  return (
    expected.dev === current.dev &&
    expected.ino === current.ino &&
    expected.ownerPresent &&
    current.ownerPresent &&
    expectedOwner !== null &&
    currentOwner !== null &&
    expectedOwner.acquiredAt === currentOwner.acquiredAt &&
    expectedOwner.bootIdentity === currentOwner.bootIdentity &&
    expectedOwner.operationId === currentOwner.operationId &&
    expectedOwner.ownerPid === currentOwner.ownerPid &&
    JSON.stringify(expected.processGroups) === JSON.stringify(current.processGroups) &&
    JSON.stringify(expected.processRecordNames) === JSON.stringify(current.processRecordNames) &&
    JSON.stringify(expected.supervisorPids) === JSON.stringify(current.supervisorPids)
  );
}

async function reconcileActiveOperationContainment(
  requestedTarget: string,
  recordedProcessWaitMs?: number,
  enumerators: readonly string[] = ["/bin/ps", "/usr/bin/ps"],
  testHooks?: BootstrapIoOptions["testHooks"],
): Promise<void> {
  const parent = await realpath(path.dirname(requestedTarget));
  const target = path.join(parent, path.basename(requestedTarget));
  const operationId = activeOperationLeases.get(target);
  if (!operationId || operationId.startsWith("publishing:")) {
    throw new Error("Command containment reconciliation requires an active same-process source-operation lease.");
  }
  const retained = await validateOperationLeaseDirectory(target);
  if (
    retained.owner?.ownerPid !== process.pid ||
    retained.owner.operationId !== operationId
  ) {
    throw new Error("Command containment reconciliation is not bound to this runtime lease owner.");
  }

  await waitForRecordedProcessesGone(
    retained.processGroups,
    retained.supervisorPids,
    recordedProcessWaitMs,
    enumerators,
  );
  testHooks?.beforeProcessAnchorReleaseStage?.("record-unlink");
  const settled = await validateOperationLeaseDirectory(target);
  if (
    activeOperationLeases.get(target) !== operationId ||
    !sameOperationContainmentScope(retained, settled)
  ) {
    throw new Error("Command containment reconciliation scope changed before durable release.");
  }
  for (const recordName of settled.processRecordNames) {
    await unlink(path.join(target, recordName));
  }
  testHooks?.beforeProcessAnchorReleaseStage?.("directory-sync");
  const cleared = await validateOperationLeaseDirectory(target);
  if (
    activeOperationLeases.get(target) !== operationId ||
    cleared.dev !== retained.dev ||
    cleared.ino !== retained.ino ||
    cleared.owner?.ownerPid !== process.pid ||
    cleared.owner.operationId !== operationId ||
    cleared.processGroups.length !== 0 ||
    cleared.processRecordNames.length !== 0 ||
    cleared.supervisorPids.length !== 0
  ) {
    throw new Error("Command containment reconciliation scope changed after record release.");
  }
  await syncDirectoryForDurability(target);
}

async function removeValidatedLeaseDirectory(
  target: string,
  expected: { dev: number; ino: number },
  enumerators: readonly string[] = ["/bin/ps", "/usr/bin/ps"],
): Promise<void> {
  const current = await validateOperationLeaseDirectory(target, true);
  if (current.dev !== expected.dev || current.ino !== expected.ino) {
    throw new Error("Source operation lease identity changed during recovery.");
  }
  await waitForRecordedProcessesGone(current.processGroups, current.supervisorPids, 1_000, enumerators);
  for (const recordName of current.processRecordNames) await unlink(path.join(target, recordName));
  if (current.ownerPresent) await unlink(path.join(target, "owner.json"));
  await syncDirectoryForDurability(target);
  await rmdir(target);
}

async function reconcileOperationLeaseQuarantines(
  parent: string,
  targetName: string,
  platform: NodeJS.Platform,
  captureLeaseIdentity: (target: string, identity: FileSystemIdentity) => Promise<FileSystemIdentity>,
  recordedProcessWaitMs?: number,
  enumerators: readonly string[] = ["/bin/ps", "/usr/bin/ps"],
): Promise<number> {
  const escaped = targetName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const quarantinePattern = new RegExp(
    `^${escaped}\\.stale-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`,
    "i",
  );
  const names = (await readdir(parent)).filter((name) => quarantinePattern.test(name)).sort();
  for (const name of names) {
    const quarantine = path.join(parent, name);
    const named = await lstat(quarantine);
    const captured = await captureLeaseIdentity(quarantine, { dev: named.dev, ino: named.ino });
    const stale = await validateOperationLeaseDirectory(quarantine, true);
    if (stale.dev !== captured.dev || stale.ino !== captured.ino) {
      throw new Error("Source operation lease quarantine changed after its native identity was captured.");
    }
    await waitForRecordedProcessesGone(
      stale.processGroups,
      stale.supervisorPids,
      recordedProcessWaitMs,
      enumerators,
    );
    const settled = await validateOperationLeaseDirectory(quarantine, true);
    const confirmed = await captureLeaseIdentity(quarantine, { dev: stale.dev, ino: stale.ino });
    if (!sameLeaseRecoveryScope(stale, settled) || !sameFileSystemIdentity(captured, confirmed)) {
      throw new Error("Source operation lease quarantine changed during containment reconciliation.");
    }
    if (platform !== "win32") {
      await removeValidatedLeaseDirectory(quarantine, stale, enumerators);
      await syncDirectoryForDurability(parent);
    }
  }
  if (platform === "win32" && names.length >= MAX_PRESERVED_WINDOWS_OPERATION_LEASE_QUARANTINES) {
    throw new Error(
      `Windows preserved source-operation lease quarantines reached ${MAX_PRESERVED_WINDOWS_OPERATION_LEASE_QUARANTINES}; ` +
      "stop FlintTrade, archive the exact .stale-* directories, and manually remove only confirmed stale evidence before retrying.",
    );
  }
  return platform === "win32" ? names.length : 0;
}

async function acquireOperationLease(
  request: OperationLeaseRequest,
  platform: NodeJS.Platform,
  captureLeaseIdentity: (target: string, identity: FileSystemIdentity) => Promise<FileSystemIdentity>,
  promoteLeaseAbsent: BootstrapDependencies["fileSystem"]["promoteAbsent"],
  options: BootstrapIoOptions = {},
): Promise<() => Promise<void>> {
  if (!request.singletonAuthorised) {
    throw new Error("Source operation lease requires explicit application-singleton authority.");
  }
  const parent = await realpath(path.dirname(request.target));
  const target = path.join(parent, path.basename(request.target));
  if (activeOperationLeases.has(target)) throw new Error("Source operation lease is already held by this process (re-entrance denied).");
  const reservationId = `publishing:${randomUUID()}`;
  activeOperationLeases.set(target, reservationId);
  try {
    const preservedWindowsQuarantines = await reconcileOperationLeaseQuarantines(
      parent,
      path.basename(target),
      platform,
      captureLeaseIdentity,
      options.testHooks?.recordedProcessWaitMs,
      options.posixProcessEnumerators,
    );
    try {
      const named = await lstat(target);
      const captured = await captureLeaseIdentity(target, { dev: named.dev, ino: named.ino });
      const stale = await validateOperationLeaseDirectory(target, true);
      if (stale.dev !== captured.dev || stale.ino !== captured.ino) {
        throw new Error("Source operation lease changed after its native identity was captured.");
      }
      await waitForRecordedProcessesGone(
        stale.processGroups,
        stale.supervisorPids,
        options.testHooks?.recordedProcessWaitMs,
        options.posixProcessEnumerators,
      );
      const settled = await validateOperationLeaseDirectory(target, true);
      const confirmed = await captureLeaseIdentity(target, { dev: stale.dev, ino: stale.ino });
      if (!sameLeaseRecoveryScope(stale, settled) || !sameFileSystemIdentity(captured, confirmed)) {
        throw new Error("Source operation lease changed during containment reconciliation.");
      }
      const quarantine = `${target}.stale-${randomUUID()}`;
      await promoteLeaseAbsent(target, quarantine, captured);
      await syncDirectoryForDurability(parent);
      const quarantined = await validateOperationLeaseDirectory(quarantine, true);
      const quarantinedIdentity = await captureLeaseIdentity(
        quarantine,
        { dev: quarantined.dev, ino: quarantined.ino },
      );
      if (
        quarantined.dev !== stale.dev ||
        quarantined.ino !== stale.ino ||
        !sameLeaseRecoveryScope(settled, quarantined) ||
        !sameFileSystemIdentity(captured, quarantinedIdentity)
      ) {
        throw new Error("Source operation lease identity changed during quarantine.");
      }
      if (platform === "win32") {
        if (preservedWindowsQuarantines + 1 >= MAX_PRESERVED_WINDOWS_OPERATION_LEASE_QUARANTINES) {
          throw new Error(
            `Windows preserved source-operation lease quarantines reached ${MAX_PRESERVED_WINDOWS_OPERATION_LEASE_QUARANTINES}; ` +
            `evidence remains at ${quarantine}. Stop FlintTrade, archive the exact .stale-* directories, and manually remove ` +
            "only confirmed stale evidence before retrying.",
          );
        }
      } else {
        await removeValidatedLeaseDirectory(
          quarantine,
          stale,
          options.posixProcessEnumerators,
        );
        await syncDirectoryForDurability(parent);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }

    await mkdir(target, { mode: 0o700 });
    const targetMetadata = await lstat(target);
    if (targetMetadata.isSymbolicLink() || !targetMetadata.isDirectory()) {
      throw new Error("Source operation lease path must be a no-follow directory.");
    }
    await syncDirectoryForDurability(target);
    await syncDirectoryForDurability(parent);
    const owner: OperationLeaseOwner = {
      acquiredAt: new Date().toISOString(),
      bootIdentity: request.bootIdentity,
      operationId: randomUUID(),
      ownerPid: request.ownerPid,
    };
    const ownerPath = path.join(target, "owner.json");
    await options.testHooks?.onLeaseOwnerPublication?.("before-open", 0);
    const ownerHandle = await open(
      ownerPath,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
      0o600,
    );
    try {
      await options.testHooks?.onLeaseOwnerPublication?.("after-open", 0);
      await writeBufferCompletely(
        ownerHandle,
        Buffer.from(`${JSON.stringify(owner)}\n`, "utf8"),
        options.testHooks?.leaseOwnerWriteChunkBytes,
        (bytesWritten) => options.testHooks?.onLeaseOwnerPublication?.("after-write", bytesWritten),
      );
      await ownerHandle.sync();
    } finally {
      await ownerHandle.close();
    }
    await syncDirectoryForDurability(target);
    await syncDirectoryForDurability(parent);
    if (activeOperationLeases.get(target) !== reservationId) {
      throw new Error("Source operation lease publication reservation changed unexpectedly.");
    }
    activeOperationLeases.set(target, owner.operationId);

    let ownerRemoved = false;
    let directorySynced = false;
    let directoryRemoved = false;
    let released = false;
    const assertLeaseDirectoryIdentity = async (expectOwner: boolean): Promise<void> => {
      const current = await validateOperationLeaseDirectory(target, !expectOwner);
      if (
        current.dev !== targetMetadata.dev ||
        current.ino !== targetMetadata.ino ||
        current.processGroups.length !== 0 ||
        current.supervisorPids.length !== 0 ||
        (expectOwner ? current.owner?.operationId !== owner.operationId : current.ownerPresent)
      ) {
        throw new Error("Source operation lease identity changed before release.");
      }
    };
    const assertLeaseDirectoryAbsent = async (): Promise<void> => {
      try {
        await lstat(target);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
        throw error;
      }
      throw new Error("Source operation lease path reappeared before durable release.");
    };
    return async () => {
      if (released) return;
      if (!ownerRemoved) {
        if (activeOperationLeases.get(target) !== owner.operationId) {
          throw new Error("Source operation lease is no longer owned by this operation.");
        }
        options.testHooks?.beforeLeaseReleaseStage?.("owner-unlink");
        await assertLeaseDirectoryIdentity(true);
        await unlink(ownerPath);
        ownerRemoved = true;
      }
      if (!directorySynced) {
        options.testHooks?.beforeLeaseReleaseStage?.("directory-sync");
        await assertLeaseDirectoryIdentity(false);
        await syncDirectoryForDurability(target);
        directorySynced = true;
      }
      if (!directoryRemoved) {
        options.testHooks?.beforeLeaseReleaseStage?.("directory-remove");
        await assertLeaseDirectoryIdentity(false);
        await rmdir(target);
        directoryRemoved = true;
      }
      options.testHooks?.beforeLeaseReleaseStage?.("parent-sync");
      await assertLeaseDirectoryAbsent();
      await syncDirectoryForDurability(parent);
      released = true;
      activeOperationLeases.delete(target);
    };
  } catch (error) {
    if (activeOperationLeases.get(target) === reservationId) activeOperationLeases.delete(target);
    throw error;
  }
}

function validatePrivateRelativePath(relative: string): string[] {
  const normalised = relative.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
  const parts = normalised.split("/");
  if (!normalised || path.posix.isAbsolute(normalised) || parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error("Managed bootstrap-user entries must be confined relative paths.");
  }
  return parts;
}

async function ensurePrivateDirectory(target: string): Promise<void> {
  try {
    await mkdir(target, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const metadata = await lstat(target);
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new Error("Managed bootstrap-user path must be a no-follow directory.");
  }
  await chmod(target, 0o700);
}

async function ensureDurableDirectory(
  target: string,
  knownDurableAncestor: string,
  options: BootstrapIoOptions,
  states: Map<string, { anchor: string; complete: boolean }>,
): Promise<void> {
  const resolvedTarget = path.resolve(target);
  const requestedAnchor = path.resolve(knownDurableAncestor);
  const requestedRelative = path.relative(requestedAnchor, resolvedTarget);
  if (requestedRelative.startsWith("..") || path.isAbsolute(requestedRelative)) {
    throw new Error("Durable bootstrap log path escaped its requested directory anchor.");
  }
  let state = states.get(resolvedTarget);
  const hadState = state !== undefined;
  if (!state) {
    let anchor = requestedAnchor;
    while (true) {
      try {
        const metadata = await lstat(anchor);
        if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
          throw new Error("Durable bootstrap log path must contain only no-follow directories.");
        }
        break;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        const parent = path.dirname(anchor);
        if (parent === anchor) throw new Error("Durable bootstrap log path has no existing directory ancestor.");
        anchor = parent;
      }
    }
    state = { anchor, complete: false };
    states.set(resolvedTarget, state);
  }

  const relative = path.relative(state.anchor, resolvedTarget);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("Durable bootstrap log path escaped its validated directory anchor.");
  }
  const chain = [state.anchor];
  for (const component of relative.split(path.sep).filter(Boolean)) {
    chain.push(path.join(chain.at(-1)!, component));
  }
  const needsRepair = hadState && !state.complete;
  const syncDirectoryAndParent = async (directory: string): Promise<void> => {
    const parent = path.dirname(directory);
    options.testHooks?.beforeDurableDirectorySync?.(directory, "directory");
    await syncDirectoryForDurability(directory);
    options.testHooks?.beforeDurableDirectorySync?.(parent, "parent");
    await syncDirectoryForDurability(parent);
  };

  for (let index = 0; index < chain.length; index += 1) {
    const directory = chain[index]!;
    let created = false;
    try {
      const metadata = await lstat(directory);
      if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
        throw new Error("Durable bootstrap log path must contain only no-follow directories.");
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT" || index === 0) throw error;
      state.complete = false;
      try {
        await mkdir(directory, { mode: 0o700 });
        created = true;
      } catch (mkdirError) {
        if ((mkdirError as NodeJS.ErrnoException).code !== "EEXIST") throw mkdirError;
      }
      const metadata = await lstat(directory);
      if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
        throw new Error("Durable bootstrap log path must contain only no-follow directories.");
      }
    }
    if (created) {
      await chmod(directory, 0o700);
      await syncDirectoryAndParent(directory);
    }
  }

  if (!hadState || needsRepair || !state.complete) {
    for (const directory of chain) {
      await syncDirectoryAndParent(directory);
    }
  }
  state.complete = true;
}

async function preparePrivateTree(
  root: string,
  directories: readonly string[],
  files: readonly string[],
): Promise<void> {
  const parent = path.dirname(root);
  const parentMetadata = await lstat(parent);
  if (parentMetadata.isSymbolicLink() || !parentMetadata.isDirectory()) {
    throw new Error("Managed bootstrap-user parent must be a no-follow directory.");
  }
  await ensurePrivateDirectory(root);
  const canonicalRoot = await realpath(root);
  const prepared = new Set<string>();
  for (const relative of directories) {
    const parts = validatePrivateRelativePath(relative);
    for (let index = 1; index <= parts.length; index += 1) {
      const target = path.join(root, ...parts.slice(0, index));
      if (prepared.has(target)) continue;
      await ensurePrivateDirectory(target);
      const canonicalTarget = await realpath(target);
      const confined = path.relative(canonicalRoot, canonicalTarget);
      if (confined.startsWith("..") || path.isAbsolute(confined)) {
        throw new Error("Managed bootstrap-user directory escaped its private root.");
      }
      prepared.add(target);
    }
  }
  for (const relative of files) {
    const parts = validatePrivateRelativePath(relative);
    const target = path.join(root, ...parts);
    await ensurePrivateDirectory(path.dirname(target));
    try {
      const existing = await lstat(target);
      if (existing.isSymbolicLink() || !existing.isFile()) {
        throw new Error("Managed bootstrap-user config must be a no-follow regular file.");
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    const handle = await open(
      target,
      constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC | (constants.O_NOFOLLOW ?? 0),
      0o600,
    );
    try {
      const metadata = await handle.stat();
      if (!metadata.isFile()) throw new Error("Managed bootstrap-user config must be a regular file.");
      await handle.chmod(0o600);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await syncDirectoryForDurability(path.dirname(target));
  }
  await syncDirectoryForDurability(canonicalRoot);
}

function createFileSystem(
  platform: NodeJS.Platform,
  command: BootstrapDependencies["command"],
  options: BootstrapIoOptions,
): BootstrapDependencies["fileSystem"] {
  const durableDirectoryStates = new Map<string, { anchor: string; complete: boolean }>();
  let posixAtomicPromoter: PosixAtomicPromoter | null = null;
  const getPosixAtomicPromoter = (): PosixAtomicPromoter => {
    posixAtomicPromoter ??= loadPinnedPosixAtomicPromoter(platform, options);
    return posixAtomicPromoter;
  };
  let preLeaseCommand = command;
  if (platform === "win32") {
    const preLeaseOptions = { ...options };
    delete preLeaseOptions.operationLeaseTarget;
    preLeaseCommand = createCommandRunner(platform, preLeaseOptions);
    if (preLeaseCommand.operationLeaseTarget !== undefined) {
      throw new Error("Windows pre-lease native runner retained an operation-lease registration target.");
    }
    options.testHooks?.onPreLeaseCommandScope?.(preLeaseCommand.operationLeaseTarget);
  }
  const captureLeaseIdentity = async (
    target: string,
    identity: FileSystemIdentity,
  ): Promise<FileSystemIdentity> => {
    await assertDirectoryIdentity(target, identity);
    if (platform !== "win32") return identity;
    const nativeIdentity = options.testHooks?.testNativeDirectoryIdentity
      ? await options.testHooks.testNativeDirectoryIdentity(target, identity)
      : await inspectWindowsNativeDirectoryIdentity(target, preLeaseCommand, options);
    if (!/^[0-9a-f]{16}:[0-9a-f]{32}$/.test(nativeIdentity)) {
      throw new Error("Windows stale operation lease returned an invalid native directory identity.");
    }
    await assertDirectoryIdentity(target, identity);
    return { ...identity, nativeIdentity };
  };
  const promoteLeaseAbsent: BootstrapDependencies["fileSystem"]["promoteAbsent"] = async (
    source,
    destination,
    identity,
  ) => {
    if (platform === "win32" && !identity.nativeIdentity) {
      throw new Error("Windows stale operation lease promotion requires its pre-validation native identity.");
    }
    await promoteAbsent(
      source,
      destination,
      identity,
      platform,
      preLeaseCommand,
      options,
      getPosixAtomicPromoter,
    );
  };
  return {
    acquireOperationLock: (request) =>
      acquireOperationLease(request, platform, captureLeaseIdentity, promoteLeaseAbsent, options),
    assertDirectoryIdentity,
    async appendText(target, content) {
      const parent = path.dirname(target);
      const parentMetadata = await lstat(parent);
      if (parentMetadata.isSymbolicLink() || !parentMetadata.isDirectory()) {
        throw new Error("Durable bootstrap log parent must be a no-follow directory.");
      }
      const parentIdentity = { dev: parentMetadata.dev, ino: parentMetadata.ino };
      const canonicalParent = await realpath(parent);
      let parentHandle: Awaited<ReturnType<typeof open>> | null = null;
      try {
        parentHandle = await open(
          parent,
          constants.O_RDONLY | (constants.O_DIRECTORY ?? 0) | (constants.O_NOFOLLOW ?? 0),
        );
        const openedParent = await parentHandle.stat();
        if (
          !openedParent.isDirectory() ||
          openedParent.dev !== parentIdentity.dev ||
          openedParent.ino !== parentIdentity.ino
        ) {
          throw new Error("Durable bootstrap log parent identity changed before its handle opened.");
        }
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (process.platform !== "win32" || !["EACCES", "EINVAL", "EISDIR", "EPERM"].includes(code ?? "")) {
          await parentHandle?.close().catch(() => undefined);
          throw error;
        }
        parentHandle = null;
      }
      const assertParentIdentity = async (): Promise<void> => {
        const current = await lstat(parent);
        if (
          current.isSymbolicLink() ||
          !current.isDirectory() ||
          current.dev !== parentIdentity.dev ||
          current.ino !== parentIdentity.ino ||
          (await realpath(parent)) !== canonicalParent
        ) {
          throw new Error("Durable bootstrap log parent identity changed before append settlement.");
        }
      };
      try {
        let expectedIdentity: { dev: number; ino: number } | null = null;
        try {
          const existing = await lstat(target);
          if (existing.isSymbolicLink() || !existing.isFile()) {
            throw new Error("Durable bootstrap log must be a no-follow regular file.");
          }
          expectedIdentity = { dev: existing.dev, ino: existing.ino };
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
        options.testHooks?.beforeAppendOpen?.(target);
        await assertParentIdentity();
        const handle = await open(
          target,
          constants.O_WRONLY |
            constants.O_APPEND |
            (expectedIdentity ? 0 : constants.O_CREAT | constants.O_EXCL) |
            (constants.O_NOFOLLOW ?? 0),
          0o600,
        );
        try {
          await assertParentIdentity();
          const metadata = await handle.stat();
          if (
            !metadata.isFile() ||
            (expectedIdentity && (metadata.dev !== expectedIdentity.dev || metadata.ino !== expectedIdentity.ino))
          ) {
            throw new Error("Durable bootstrap log identity changed before append.");
          }
          const appendedIdentity = { dev: metadata.dev, ino: metadata.ino };
          const assertTargetIdentity = async (): Promise<void> => {
            const current = await lstat(target);
            if (
              current.isSymbolicLink() ||
              !current.isFile() ||
              current.dev !== appendedIdentity.dev ||
              current.ino !== appendedIdentity.ino
            ) {
              throw new Error("Durable bootstrap log pathname changed before append settlement.");
            }
          };
          await handle.chmod(0o600);
          const encoded = Buffer.from(content, "utf8");
          const configuredChunk = options.testHooks?.appendWriteChunkBytes ?? Math.max(encoded.length, 1);
          if (!Number.isSafeInteger(configuredChunk) || configuredChunk <= 0) {
            throw new Error("Durable bootstrap log write chunk must be a positive safe integer.");
          }
          let offset = 0;
          while (offset < encoded.length) {
            const requested = Math.min(configuredChunk, encoded.length - offset);
            const { bytesWritten } = await handle.write(encoded, offset, requested, null);
            if (bytesWritten <= 0 || bytesWritten > requested) {
              throw new Error("Durable bootstrap log append did not complete a valid write.");
            }
            offset += bytesWritten;
          }
          await handle.sync();
          options.testHooks?.beforeAppendParentSync?.(target);
          await assertParentIdentity();
          await assertTargetIdentity();
          if (parentHandle) await parentHandle.sync();
          else await syncDirectoryForDurability(canonicalParent);
          await assertParentIdentity();
          await assertTargetIdentity();
        } finally {
          await handle.close();
        }
      } finally {
        await parentHandle?.close();
      }
    },
    async directoryIdentity(target) {
      const metadata = await lstat(target);
      if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
        throw new Error("Candidate root must be a no-follow directory.");
      }
      return { dev: metadata.dev, ino: metadata.ino };
    },
    async directoryMetadata(target): Promise<FileSystemDirectoryMetadata> {
      const metadata = await lstat(target);
      if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
        throw new Error("Candidate directory must be a no-follow directory.");
      }
      return {
        ctimeMs: metadata.ctimeMs,
        dev: metadata.dev,
        ino: metadata.ino,
        mtimeMs: metadata.mtimeMs,
        size: metadata.size,
      };
    },
    ensureDurableDirectory: (target, anchor) =>
      ensureDurableDirectory(target, anchor, options, durableDirectoryStates),
    async exists(target) {
      try {
        await access(target);
        return true;
      } catch {
        return false;
      }
    },
    async existsNoFollow(target) {
      try {
        await lstat(target);
        return true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
        throw error;
      }
    },
    async fileIdentity(target): Promise<FileSystemFileIdentity> {
      const metadata = await lstat(target);
      if (metadata.isSymbolicLink() || !metadata.isFile()) {
        throw new Error("Candidate file must be a no-follow regular file.");
      }
      return {
        ctimeMs: metadata.ctimeMs,
        dev: metadata.dev,
        ino: metadata.ino,
        mtimeMs: metadata.mtimeMs,
        size: metadata.size,
      };
    },
    async listNames(target) {
      try {
        return await readdir(target);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
        throw error;
      }
    },
    mkdir: (target) => mkdir(target, { recursive: true, mode: 0o700 }),
    preparePrivateTree,
    promoteAbsent: (source, destination, identity) =>
      promoteAbsent(source, destination, identity, platform, command, options, getPosixAtomicPromoter),
    readText: (target) => readFile(target, "utf8"),
    readTextNoFollow: readNoFollowRegularText,
    realpath,
    remove: (target) => rm(target, { force: true, recursive: true }),
    reserveTemporaryDirectory: (parent, prefix) =>
      reserveTemporaryDirectory(parent, prefix, platform, command, options),
    async rename(source, destination) {
      await rename(source, destination);
      await syncDirectoryForDurability(path.dirname(destination));
      if (path.dirname(source) !== path.dirname(destination)) {
        await syncDirectoryForDurability(path.dirname(source));
      }
    },
    sha256(target) {
      return new Promise((resolve, reject) => {
        const hash = createHash("sha256");
        const stream = createReadStream(target);
        stream.on("data", (chunk) => hash.update(chunk));
        stream.on("error", reject);
        stream.on("end", () => resolve(hash.digest("hex")));
      });
    },
    snapshotSourceTree,
    verifySourceTree,
    writeTextAbsent,
    async writeTextAtomic(target, content) {
      await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
      const parent = path.dirname(target);
      const parentMetadata = await lstat(parent);
      if (parentMetadata.isSymbolicLink() || !parentMetadata.isDirectory()) {
        throw new Error("Atomic bootstrap write parent must be a no-follow directory.");
      }
      const temporary = `${target}.tmp-${process.pid}-${randomUUID()}`;
      const handle = await open(
        temporary,
        constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
        0o600,
      );
      let identity: { dev: number; ino: number } | null = null;
      let preparationFailed = false;
      let preparationError: unknown;
      try {
        const metadata = await handle.stat();
        if (!metadata.isFile()) throw new Error("Atomic bootstrap temporary must be a regular file.");
        identity = { dev: metadata.dev, ino: metadata.ino };
        await handle.writeFile(content, { encoding: "utf8" });
        await handle.chmod(0o600);
        await handle.sync();
      } catch (error) {
        preparationFailed = true;
        preparationError = error;
      } finally {
        await handle.close();
      }
      if (preparationFailed) {
        if (identity) {
          const current = await lstat(temporary);
          if (!current.isSymbolicLink() && current.isFile() && current.dev === identity.dev && current.ino === identity.ino) {
            await unlink(temporary);
            await syncDirectoryForDurability(parent);
          }
        }
        throw preparationError;
      }
      try {
        const temporaryMetadata = await lstat(temporary);
        if (
          !identity ||
          temporaryMetadata.isSymbolicLink() ||
          !temporaryMetadata.isFile() ||
          temporaryMetadata.dev !== identity.dev ||
          temporaryMetadata.ino !== identity.ino
        ) {
          throw new Error("Atomic bootstrap temporary identity changed before rename.");
        }
        await rename(temporary, target);
        await syncDirectoryForDurability(parent);
      } catch (error) {
        if (identity) {
          try {
            const current = await lstat(temporary);
            if (!current.isSymbolicLink() && current.isFile() && current.dev === identity.dev && current.ino === identity.ino) {
              await unlink(temporary);
              await syncDirectoryForDurability(parent);
            }
          } catch (cleanupError) {
            if ((cleanupError as NodeJS.ErrnoException).code !== "ENOENT") throw cleanupError;
          }
        }
        throw error;
      }
    },
  };
}

export function createNodeBootstrapDependencies(
  platform: NodeJS.Platform,
  options: BootstrapIoOptions = {},
): BootstrapDependencies {
  const command = createCommandRunner(platform, options);
  return {
    command,
    download: createDownloader(options),
    extractArchive: createArchiveExtractor(options),
    fileSystem: createFileSystem(platform, command, options),
  };
}
