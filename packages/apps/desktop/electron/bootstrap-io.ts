import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
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
  writeFile,
} from "node:fs/promises";
import https from "node:https";
import path from "node:path";

import type { BootstrapDependencies, CommandInvocation, CommandResult } from "./bootstrap";

const OUTPUT_LIMIT = 256 * 1024;
const TEXT_DOWNLOAD_LIMIT = 1024 * 1024;

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
        let settled = false;
        let terminating = false;
        let forceKill: NodeJS.Timeout | null = null;
        const child = spawn(invocation.command, invocation.args, {
          ...(invocation.cwd ? { cwd: invocation.cwd } : {}),
          env: { ...process.env, ...invocation.env },
          detached: platform !== "win32",
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true,
        });

        const terminate = (reason: "cancelled" | "timeout") => {
          cancelled ||= reason === "cancelled";
          timedOut ||= reason === "timeout";
          if (terminating) return;
          terminating = true;
          if (platform === "win32" && windowsTaskkill && child.pid) {
            spawn(windowsTaskkill, ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
          } else if (child.pid) {
            try {
              process.kill(-child.pid, "SIGTERM");
            } catch {
              child.kill("SIGTERM");
            }
          }
          forceKill = setTimeout(() => {
            if (platform === "win32" && windowsTaskkill && child.pid) {
              spawn(windowsTaskkill, ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
            } else if (child.pid) {
              try {
                process.kill(-child.pid, "SIGKILL");
              } catch {
                child.kill("SIGKILL");
              }
            }
          }, 5_000);
          forceKill.unref?.();
        };
        const onAbort = () => terminate("cancelled");
        invocation.signal?.addEventListener("abort", onAbort, { once: true });
        const timeout = setTimeout(() => terminate("timeout"), invocation.timeoutMs ?? 30 * 60_000);
        timeout.unref?.();

        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk: string) => {
          stdout = appendBounded(stdout, chunk);
          stdoutBuffer = emitLines(stdoutBuffer, chunk, "stdout", invocation.onOutput);
        });
        child.stderr.on("data", (chunk: string) => {
          stderr = appendBounded(stderr, chunk);
          stderrBuffer = emitLines(stderrBuffer, chunk, "stderr", invocation.onOutput);
        });
        child.on("error", (error) => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          if (forceKill) clearTimeout(forceKill);
          invocation.signal?.removeEventListener("abort", onAbort);
          resolve({ exitCode: cancelled ? 130 : 127, stderr: error.message, stdout });
        });
        child.on("close", (code) => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          if (forceKill) clearTimeout(forceKill);
          invocation.signal?.removeEventListener("abort", onAbort);
          if (stdoutBuffer) invocation.onOutput?.(stdoutBuffer, "stdout");
          if (stderrBuffer) invocation.onOutput?.(stderrBuffer, "stderr");
          resolve({
            exitCode: cancelled ? 130 : timedOut ? 124 : (code ?? 1),
            stderr: timedOut ? appendBounded(stderr, "\nCommand timed out.") : stderr,
            stdout,
          });
        });
      });
    },
  };
}

async function requestBytes(url: string, signal: AbortSignal, redirects = 0): Promise<Buffer> {
  if (redirects > 4) throw new Error("HTTPS download exceeded the redirect limit.");
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") throw new Error("Bootstrap downloads require HTTPS.");
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }
    const request = https.get(
      parsed,
      { headers: { Accept: "application/octet-stream, application/json", "User-Agent": "FlintTrade-Desktop" } },
      async (response) => {
        try {
          if (response.statusCode && [301, 302, 303, 307, 308].includes(response.statusCode)) {
            response.resume();
            if (!response.headers.location) throw new Error("HTTPS redirect did not include a destination.");
            resolve(await requestBytes(new URL(response.headers.location, parsed).href, signal, redirects + 1));
            return;
          }
          if (response.statusCode !== 200) throw new Error(`HTTPS download failed with status ${response.statusCode}.`);
          const chunks: Buffer[] = [];
          let length = 0;
          for await (const chunk of response) {
            const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
            length += bytes.length;
            if (length > TEXT_DOWNLOAD_LIMIT) throw new Error("HTTPS metadata response exceeded its size limit.");
            chunks.push(bytes);
          }
          resolve(Buffer.concat(chunks));
        } catch (error) {
          reject(error);
        }
      },
    );
    const onAbort = () => request.destroy(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    request.setTimeout(10 * 60_000, () => request.destroy(new Error("HTTPS download timed out.")));
    request.on("close", () => signal.removeEventListener("abort", onAbort));
    request.on("error", reject);
  });
}

async function downloadFile(url: string, destination: string, signal: AbortSignal, redirects = 0): Promise<void> {
  if (redirects > 4) throw new Error("HTTPS download exceeded the redirect limit.");
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") throw new Error("Bootstrap downloads require HTTPS.");
  await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = `${destination}.download-${process.pid}-${randomUUID()}`;
  await rm(temporary, { force: true });
  await new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }
    const request = https.get(parsed, { headers: { "User-Agent": "FlintTrade-Desktop" } }, async (response) => {
      try {
        if (response.statusCode && [301, 302, 303, 307, 308].includes(response.statusCode)) {
          response.resume();
          if (!response.headers.location) throw new Error("HTTPS redirect did not include a destination.");
          await downloadFile(new URL(response.headers.location, parsed).href, destination, signal, redirects + 1);
          resolve();
          return;
        }
        if (response.statusCode !== 200) throw new Error(`HTTPS download failed with status ${response.statusCode}.`);
        const handle = await open(temporary, "w", 0o600);
        try {
          for await (const chunk of response) {
            if (signal.aborted) throw abortError();
            await handle.write(chunk);
          }
          await handle.sync();
        } finally {
          await handle.close();
        }
        await rename(temporary, destination);
        resolve();
      } catch (error) {
        await rm(temporary, { force: true });
        reject(error);
      }
    });
    const onAbort = () => request.destroy(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    request.setTimeout(10 * 60_000, () => request.destroy(new Error("HTTPS download timed out.")));
    request.on("close", () => signal.removeEventListener("abort", onAbort));
    request.on("error", reject);
  });
}

function createDownloader(): BootstrapDependencies["download"] {
  return {
    file: downloadFile,
    async text(url, signal) {
      return (await requestBytes(url, signal)).toString("utf8");
    },
  };
}

export function validateArchiveEntries(entries: string[], label: string, expectedRoot?: string): string[] {
  if (entries.length === 0) throw new Error(`${label} archive is empty.`);
  const normalised = entries.map((entry) => entry.replace(/\\/g, "/").replace(/\/$/, ""));
  for (const entry of normalised) {
    const parts = entry.split("/");
    if (!entry || entry.startsWith("/") || /^[A-Za-z]:/.test(entry) || parts.includes("..")) {
      throw new Error(`${label} archive contains an unsafe path.`);
    }
    if (expectedRoot && parts[0] !== expectedRoot) throw new Error(`${label} archive contains an unexpected root.`);
  }
  return normalised;
}

export function validateTarLinkEntries(entries: string[], verboseListing: string, label: string): void {
  for (const line of verboseListing.split(/\r?\n/).filter(Boolean)) {
    const type = line[0];
    if (type !== "l" && type !== "h") continue;
    const separator = type === "l" ? " -> " : " link to ";
    const separatorIndex = line.lastIndexOf(separator);
    if (separatorIndex < 0) throw new Error(`${label} archive has unparseable link metadata.`);
    const left = line.slice(0, separatorIndex).trimEnd();
    const entry = [...entries].sort((a, b) => b.length - a.length).find((candidate) => left.endsWith(candidate));
    if (!entry) throw new Error(`${label} archive link does not match a listed path.`);
    const root = entry.split("/")[0];
    const target = line.slice(separatorIndex + separator.length).trim();
    const resolved =
      type === "l"
        ? path.posix.resolve("/", path.posix.dirname(entry), target)
        : path.posix.resolve("/", target);
    if (resolved !== `/${root}` && !resolved.startsWith(`/${root}/`)) {
      throw new Error(`${label} archive link escapes its archive root.`);
    }
  }
}

function validateZipMetadata(verboseListing: string): void {
  for (const line of verboseListing.split(/\r?\n/)) {
    if (/^[lh][rwx-]{9}\s/.test(line)) throw new Error("zip archive contains a link entry.");
  }
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

function createArchiveExtractor(
  command: BootstrapDependencies["command"],
  platform: NodeJS.Platform,
): BootstrapDependencies["extractArchive"] {
  const required = async (invocation: CommandInvocation): Promise<CommandResult> => {
    const result = await command.run(invocation);
    if (result.exitCode !== 0) throw new Error(result.stderr.trim() || "Archive tool capability probe failed.");
    return result;
  };
  return async ({ archive, destination, kind, signal }) => {
    if (kind === "tar.gz") {
      await required({ args: ["--version"], command: "tar", signal, timeoutMs: 15_000 });
      const listing = await required({ args: ["-tzf", archive], command: "tar", signal, timeoutMs: 60_000 });
      const entries = validateArchiveEntries(listing.stdout.split(/\r?\n/).filter(Boolean), "tar");
      const verbose = await required({ args: ["-tvzf", archive], command: "tar", signal, timeoutMs: 60_000 });
      validateTarLinkEntries(entries, verbose.stdout, "tar");
      await required({ args: ["-xzf", archive, "-C", destination], command: "tar", signal, timeoutMs: 10 * 60_000 });
      await assertExtractedTreeConfined(destination);
      return entries;
    }
    if (platform === "win32") {
      const powershell = "powershell.exe";
      await required({
        args: ["-NoProfile", "-NonInteractive", "-Command", "Get-Command Expand-Archive | Out-Null"],
        command: powershell,
        signal,
        timeoutMs: 15_000,
      });
      const listingScript =
        "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; " +
        "$z=[IO.Compression.ZipFile]::OpenRead($args[0]); try {$z.Entries | ForEach-Object {" +
        "if (((($_.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000)) {throw 'zip archive contains a link entry'}; " +
        "$_.FullName}} finally {$z.Dispose()}";
      const listing = await required({
        args: ["-NoProfile", "-NonInteractive", "-Command", listingScript, archive],
        command: powershell,
        signal,
        timeoutMs: 60_000,
      });
      const entries = validateArchiveEntries(listing.stdout.split(/\r?\n/).filter(Boolean), "zip");
      await required({
        args: [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $args[0] -DestinationPath $args[1] -Force",
          archive,
          destination,
        ],
        command: powershell,
        signal,
        timeoutMs: 10 * 60_000,
      });
      await assertExtractedTreeConfined(destination);
      return entries;
    }
    await required({ args: ["-v"], command: "unzip", signal, timeoutMs: 15_000 });
    const listing = await required({ args: ["-Z1", archive], command: "unzip", signal, timeoutMs: 60_000 });
    const entries = validateArchiveEntries(listing.stdout.split(/\r?\n/).filter(Boolean), "zip");
    const verbose = await required({ args: ["-Z", "-l", archive], command: "unzip", signal, timeoutMs: 60_000 });
    validateZipMetadata(verbose.stdout);
    await required({ args: ["-q", archive, "-d", destination], command: "unzip", signal, timeoutMs: 10 * 60_000 });
    await assertExtractedTreeConfined(destination);
    return entries;
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
    extractArchive: createArchiveExtractor(command, platform),
    fileSystem: createFileSystem(),
  };
}
