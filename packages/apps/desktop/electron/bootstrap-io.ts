import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { createReadStream, createWriteStream, existsSync } from "node:fs";
import {
  access,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  readlink,
  realpath,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import https from "node:https";
import path from "node:path";
import { pipeline } from "node:stream/promises";

import * as tar from "tar";
import * as yauzl from "yauzl";

import type {
  BootstrapDependencies,
  CommandInvocation,
  CommandResult,
  DownloadPolicy,
  DownloadReceipt,
  SourceTreeEntry,
  SourceTreeIdentity,
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
  "FLINTTRADE_BOOTSTRAP_COREPACK_JS",
  "FLINTTRADE_BOOTSTRAP_NODE",
  "FLINTTRADE_BOOTSTRAP_PNPM_VERSION",
  "FLINTTRADE_BOOTSTRAP_TOOLS_ROOT",
  "FLINTTRADE_BOOTSTRAP_UV",
  "GIT_CONFIG_NOSYSTEM",
  "GIT_TERMINAL_PROMPT",
  "UV_CACHE_DIR",
  "UV_NO_EDITABLE",
  "UV_PYTHON",
  "UV_PYTHON_INSTALL_DIR",
]);

function abortError(): DOMException {
  return new DOMException("Operation cancelled.", "AbortError");
}

function appendBounded(current: string, chunk: string): string {
  const combined = current + chunk;
  return combined.length <= OUTPUT_LIMIT ? combined : combined.slice(-OUTPUT_LIMIT);
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
  return pending;
}

export function minimalChildEnvironment(
  overrides: NodeJS.ProcessEnv = {},
  inherited: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {};
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

export function isSuccessfulTaskkillExit(exitCode: number | null): boolean {
  return exitCode === 0;
}

const delay = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function processGroupExists(processGroup: number): boolean {
  try {
    process.kill(-processGroup, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function createCommandRunner(platform: NodeJS.Platform): BootstrapDependencies["command"] {
  const taskkillCandidate =
    platform === "win32" && process.env.SystemRoot
      ? path.join(process.env.SystemRoot, "System32", "taskkill.exe")
      : null;
  const windowsTaskkill =
    taskkillCandidate &&
    existsSync(taskkillCandidate) &&
    spawnSync(taskkillCandidate, ["/?"], { stdio: "ignore", windowsHide: true }).status === 0
      ? taskkillCandidate
      : null;
  return {
    run(invocation): Promise<CommandResult> {
      return new Promise((resolve) => {
        if (platform === "win32" && (!windowsTaskkill || !existsSync(windowsTaskkill))) {
          resolve({ exitCode: 127, stderr: "Windows descendant-process cancellation requires taskkill.exe.", stdout: "" });
          return;
        }
        if (invocation.signal?.aborted) {
          resolve({ exitCode: 130, stderr: "Operation cancelled.", stdout: "" });
          return;
        }
        let stdout = "";
        let stderr = "";
        let stdoutBuffer = "";
        let stderrBuffer = "";
        let cancelled = false;
        let timedOut = false;
        let listenerFailure = "";
        let settled = false;
        let terminating: Promise<void> | null = null;
        let closeCode: number | null = null;
        let closeObserved = false;
        let terminationError = "";
        let observeClose!: () => void;
        const closeSignal = new Promise<void>((resolveClose) => {
          observeClose = resolveClose;
        });
        const child = spawn(invocation.command, invocation.args, {
          ...(invocation.cwd ? { cwd: invocation.cwd } : {}),
          env: minimalChildEnvironment(invocation.env),
          detached: platform !== "win32",
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true,
        });

        const finish = (): void => {
          if (settled || !closeObserved || (terminating && terminationError === "pending")) return;
          settled = true;
          clearTimeout(timeout);
          invocation.signal?.removeEventListener("abort", onAbort);
          try {
            if (stdoutBuffer) invocation.onOutput?.(stdoutBuffer, "stdout");
            if (stderrBuffer) invocation.onOutput?.(stderrBuffer, "stderr");
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
          }
          resolve({
            exitCode: listenerFailure ? 1 : cancelled ? 130 : timedOut ? 124 : (closeCode ?? 1),
            stderr: timedOut
              ? appendBounded(stderr, `\nCommand timed out.${terminationError && terminationError !== "pending" ? ` ${terminationError}` : ""}`)
              : appendBounded(
                  stderr,
                  `${terminationError && terminationError !== "pending" ? `\n${terminationError}` : ""}${listenerFailure ? `\nOutput listener failed: ${listenerFailure}` : ""}`,
                ),
            stdout,
          });
        };

        const runTaskkill = (pid: number): Promise<void> =>
          new Promise((resolveKill, rejectKill) => {
            if (!windowsTaskkill) return rejectKill(new Error("taskkill.exe is unavailable."));
            const killer = spawn(windowsTaskkill, ["/PID", String(pid), "/T", "/F"], {
              env: minimalChildEnvironment(),
              stdio: "ignore",
              windowsHide: true,
            });
            killer.once("error", rejectKill);
            killer.once("close", (code) => {
              if (isSuccessfulTaskkillExit(code)) resolveKill();
              else rejectKill(new Error(`taskkill.exe failed with exit code ${code ?? "unknown"}.`));
            });
          });

        const terminate = (reason: "cancelled" | "listener" | "timeout"): void => {
          cancelled ||= reason === "cancelled";
          timedOut ||= reason === "timeout";
          if (terminating) return;
          terminationError = "pending";
          terminating = (async () => {
            const pid = child.pid;
            if (!pid) return;
            if (platform === "win32") {
              try {
                await runTaskkill(pid);
              } catch (error) {
                child.kill("SIGKILL");
                throw error;
              }
              return;
            }
            try {
              process.kill(-pid, "SIGTERM");
            } catch (error) {
              if ((error as NodeJS.ErrnoException).code !== "ESRCH") child.kill("SIGTERM");
            }
            await Promise.race([delay(1_000), closeSignal]);
            if (processGroupExists(pid)) {
              try {
                process.kill(-pid, "SIGKILL");
              } catch (error) {
                if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
              }
            }
            const deadline = Date.now() + 5_000;
            while (processGroupExists(pid) && Date.now() < deadline) await delay(25);
            if (processGroupExists(pid)) throw new Error("Descendant process group did not terminate.");
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

        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk: string) => {
          stdout = appendBounded(stdout, chunk);
          try {
            stdoutBuffer = emitLines(stdoutBuffer, chunk, "stdout", invocation.onOutput);
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminate("listener");
          }
        });
        child.stderr.on("data", (chunk: string) => {
          stderr = appendBounded(stderr, chunk);
          try {
            stderrBuffer = emitLines(stderrBuffer, chunk, "stderr", invocation.onOutput);
          } catch (error) {
            listenerFailure ||= error instanceof Error ? error.message : String(error);
            terminate("listener");
          }
        });
        child.on("error", (error) => {
          if (settled) return;
          closeObserved = true;
          observeClose();
          closeCode = cancelled ? 130 : 127;
          stderr = appendBounded(stderr, error.message);
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
    const remaining = Math.max(1, deadline - Date.now());
    const request = https.get(
      parsed,
      { headers: { Accept: "application/octet-stream, application/json", "User-Agent": "FlintTrade-Desktop" } },
      (response) => {
        void (async () => {
          if (response.statusCode && [301, 302, 303, 307, 308].includes(response.statusCode)) {
            response.resume();
            if (!response.headers.location) throw new Error(`${policy.label} redirect omitted its destination.`);
            return await requestDownload(
              new URL(response.headers.location, parsed).href,
              signal,
              policy,
              consume,
              deadline,
              redirects + 1,
            );
          }
          if (response.statusCode !== 200) {
            response.resume();
            throw new Error(`${policy.label} download failed with status ${response.statusCode}.`);
          }
          contentLengthWithinLimit(response.headers["content-length"], policy);
          const receipt = await consume(response, parsed.href);
          return { ...receipt, finalUrl: parsed.href, origin: parsed.origin };
        })().then(
          (receipt) => {
            completed = true;
            resolve(receipt);
          },
          (error) => {
            completed = true;
            reject(error);
          },
        );
      },
    );
    const totalTimer = setTimeout(() => request.destroy(new Error(`${policy.label} download exceeded its total deadline.`)), remaining);
    totalTimer.unref?.();
    const onAbort = () => request.destroy(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    request.setTimeout(policy.idleTimeoutMs, () => request.destroy(new Error(`${policy.label} download became idle.`)));
    request.on("close", () => {
      clearTimeout(totalTimer);
      signal.removeEventListener("abort", onAbort);
    });
    request.on("error", (error) => {
      if (!completed) reject(error);
    });
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
): Promise<DownloadReceipt> {
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = `${destination}.download-${process.pid}-${randomUUID()}`;
  await rm(temporary, { force: true });
  try {
    const receipt = await requestDownload(url, signal, policy, async (response) => {
      const hash = createHash("sha256");
      let bytes = 0;
      const handle = await open(temporary, "wx", 0o600);
      try {
        for await (const chunk of response) {
          if (signal.aborted) throw abortError();
          const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          bytes += value.length;
          if (bytes > policy.maxBytes) throw new Error(`${policy.label} download exceeded its size limit.`);
          hash.update(value);
          await handle.write(value);
        }
        await handle.sync();
      } finally {
        await handle.close();
      }
      return { bytes, sha256: hash.digest("hex") };
    });
    await rename(temporary, destination);
    await syncDirectoryForDurability(path.dirname(destination));
    return receipt;
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
}

function createDownloader(): BootstrapDependencies["download"] {
  return {
    file: downloadFile,
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

async function snapshotSourceTree(root: string): Promise<SourceTreeIdentity> {
  const entries: SourceTreeEntry[] = [];
  const visit = async (directory: string): Promise<void> => {
    const children = await readdir(directory);
    children.sort();
    for (const child of children) {
      const target = path.join(directory, child);
      const relative = path.relative(root, target).split(path.sep).join("/");
      const metadata = await lstat(target);
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

async function verifySourceTree(root: string, identity: SourceTreeIdentity): Promise<boolean> {
  if (createHash("sha256").update(JSON.stringify(identity.entries)).digest("hex") !== identity.digest) return false;
  for (const expected of identity.entries) {
    const target = path.join(root, ...expected.path.split("/"));
    if (!isPathWithin(root, target)) return false;
    try {
      const metadata = await lstat(target);
      if ((metadata.mode & 0o777) !== expected.mode) return false;
      if (expected.type === "file") {
        if (!metadata.isFile() || metadata.isSymbolicLink() || (await sha256File(target)) !== expected.sha256) return false;
      } else if (!metadata.isSymbolicLink() || (await readlink(target)) !== expected.target) {
        return false;
      }
    } catch {
      return false;
    }
  }
  return true;
}

async function promoteAbsent(source: string, destination: string): Promise<void> {
  const sourceParent = await realpath(path.dirname(source));
  const destinationParent = await realpath(path.dirname(destination));
  if (sourceParent !== destinationParent) throw new Error("Candidate and active source must share one canonical parent.");
  const sourceMetadata = await lstat(source);
  const parentMetadata = await stat(sourceParent);
  if (sourceMetadata.dev !== parentMetadata.dev) throw new Error("Candidate and active source must be on one filesystem.");
  try {
    await lstat(destination);
    throw new Error("Active source already exists; refusing to replace it.");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  await rename(source, destination);
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

async function assertCompressedArchiveBound(archive: string): Promise<void> {
  const metadata = await stat(archive);
  if (!metadata.isFile() || metadata.size > ARCHIVE_LIMITS.compressedBytes) {
    throw new Error("Bootstrap archive exceeded its compressed size limit.");
  }
}

async function listTarArchive(
  archive: string,
  signal: AbortSignal,
  expectedRoot?: string,
): Promise<ValidatedArchiveEntry[]> {
  const validator = new ArchiveValidator("tar", expectedRoot);
  let validationFailure: unknown;
  await tar.list({
    file: archive,
    onentry(entry) {
      try {
        if (signal.aborted) throw abortError();
        const kinds: Partial<Record<string, ArchiveEntryKind>> = {
          Directory: "directory",
          File: "file",
          Link: "hardlink",
          OldFile: "file",
          SymbolicLink: "symlink",
        };
        const kind = kinds[entry.type];
        if (!kind) throw new Error(`tar archive contains unsupported ${entry.type} entry.`);
        validator.add({
          kind,
          mode: entry.mode ?? 0,
          name: entry.path,
          size: kind === "file" ? entry.size : 0,
          ...((kind === "hardlink" || kind === "symlink") && entry.linkpath ? { target: entry.linkpath } : {}),
        });
      } catch (error) {
        validationFailure ??= error;
      }
      entry.resume();
    },
    preservePaths: false,
    strict: true,
  });
  if (validationFailure) throw validationFailure;
  return validator.complete();
}

function openZip(archive: string): Promise<yauzl.ZipFile> {
  return new Promise((resolve, reject) => {
    yauzl.open(archive, { autoClose: true, lazyEntries: true, strictFileNames: true, validateEntrySizes: true }, (error, zip) => {
      if (error || !zip) reject(error ?? new Error("Could not open ZIP archive."));
      else resolve(zip);
    });
  });
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

async function listZipArchive(archive: string, signal: AbortSignal, expectedRoot?: string): Promise<ValidatedArchiveEntry[]> {
  const zip = await openZip(archive);
  const validator = new ArchiveValidator("zip", expectedRoot);
  return new Promise((resolve, reject) => {
    const fail = (error: unknown) => {
      zip.close();
      reject(error);
    };
    zip.on("error", fail);
    zip.on("entry", (entry) => {
      try {
        if (signal.aborted) throw abortError();
        const metadata = zipEntryKind(entry);
        validator.add({ ...metadata, name: entry.fileName, size: entry.uncompressedSize });
        zip.readEntry();
      } catch (error) {
        fail(error);
      }
    });
    zip.on("end", () => {
      try {
        resolve(validator.complete());
      } catch (error) {
        reject(error);
      }
    });
    zip.readEntry();
  });
}

async function extractZipArchive(
  archive: string,
  destination: string,
  expected: ValidatedArchiveEntry[],
  signal: AbortSignal,
): Promise<void> {
  const zip = await openZip(archive);
  let index = 0;
  await new Promise<void>((resolve, reject) => {
    let working = false;
    const fail = (error: unknown) => {
      zip.close();
      reject(error);
    };
    zip.on("error", fail);
    zip.on("entry", (entry) => {
      if (working) return fail(new Error("ZIP parser emitted overlapping entries."));
      working = true;
      void (async () => {
        if (signal.aborted) throw abortError();
        const expectedEntry = expected[index];
        const metadata = zipEntryKind(entry);
        const name = entry.fileName.replace(/\/+$/, "");
        if (!expectedEntry || expectedEntry.name !== name || expectedEntry.kind !== metadata.kind) {
          throw new Error("ZIP archive changed between validation and extraction.");
        }
        const target = path.join(destination, ...name.split("/"));
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
          await pipeline(source, createWriteStream(target, { flags: "wx", mode: mode || 0o600 }));
        }
        index += 1;
        working = false;
        zip.readEntry();
      })().catch(fail);
    });
    zip.on("end", () => {
      if (index !== expected.length) reject(new Error("ZIP archive changed between validation and extraction."));
      else resolve();
    });
    zip.readEntry();
  });
}

function createArchiveExtractor(): BootstrapDependencies["extractArchive"] {
  return async ({ archive, destination, expectedRoot, kind, signal }) => {
    await assertCompressedArchiveBound(archive);
    const digestBefore = await sha256File(archive);
    const entries =
      kind === "tar.gz"
        ? await listTarArchive(archive, signal, expectedRoot)
        : await listZipArchive(archive, signal, expectedRoot);
    if (kind === "tar.gz") {
      if (signal.aborted) throw abortError();
      await tar.extract({ cwd: destination, file: archive, preservePaths: false, strict: true });
    } else {
      await extractZipArchive(archive, destination, entries, signal);
    }
    if ((await sha256File(archive)) !== digestBefore) {
      throw new Error("Bootstrap archive changed between validation and extraction.");
    }
    await assertExtractedTreeConfined(destination);
    return entries.map((entry) => entry.name);
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

function createFileSystem(): BootstrapDependencies["fileSystem"] {
  return {
    async acquireOperationLock(target) {
      try {
        await mkdir(target, { mode: 0o700 });
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          throw new Error("Another source bootstrap operation holds the exclusive operation lock.");
        }
        throw error;
      }
      let released = false;
      return async () => {
        if (released) return;
        released = true;
        await rm(target, { recursive: true });
        await syncDirectoryForDurability(path.dirname(target));
      };
    },
    async appendText(target, content) {
      await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
      const handle = await open(target, "a", 0o600);
      try {
        await handle.write(content);
        await handle.sync();
      } finally {
        await handle.close();
      }
    },
    async exists(target) {
      try {
        await access(target);
        return true;
      } catch {
        return false;
      }
    },
    mkdir: (target) => mkdir(target, { recursive: true, mode: 0o700 }),
    promoteAbsent,
    readText: (target) => readFile(target, "utf8"),
    realpath,
    remove: (target) => rm(target, { force: true, recursive: true }),
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
    async writeTextAtomic(target, content) {
      await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
      const temporary = `${target}.tmp`;
      await writeFile(temporary, content, { encoding: "utf8", mode: 0o600 });
      const handle = await open(temporary, "r");
      try {
        await handle.sync();
      } finally {
        await handle.close();
      }
      await rename(temporary, target);
      await syncDirectoryForDurability(path.dirname(target));
    },
  };
}

export function createNodeBootstrapDependencies(platform: NodeJS.Platform): BootstrapDependencies {
  const command = createCommandRunner(platform);
  return {
    command,
    download: createDownloader(),
    extractArchive: createArchiveExtractor(),
    fileSystem: createFileSystem(),
  };
}
