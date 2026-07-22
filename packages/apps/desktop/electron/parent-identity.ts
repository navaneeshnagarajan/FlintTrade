import { spawn } from "node:child_process";
import path from "node:path";

import { minimalChildEnvironment } from "./bootstrap-io";

const PARENT_IDENTITY_ARGUMENT = "--flinttrade-print-parent-identity";
const PARENT_IDENTITY_PREFIX = "FLINTTRADE_PARENT_IDENTITY ";
const DEFAULT_PROBE_TIMEOUT_MS = 5_000;
const DEFAULT_OUTPUT_LIMIT_BYTES = 4_096;
const MAX_PROCESS_ID = 0xffff_ffff;

export type ParentIdentityPlatform = "darwin" | "linux" | "win32";
export type ParentIdentityFailureReason = "cancelled" | "probe" | "setup";

export interface ParentIdentityProof {
  imageSha256: string;
  kernelStartToken: string;
  parentPid: number;
  platform: ParentIdentityPlatform;
  raw: string;
}

export interface ParentIdentityCommandInvocation {
  args: readonly string[];
  command: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  maxOutputBytes: number;
  signal?: AbortSignal;
  timeoutMs: number;
}

export interface ParentIdentityCommandResult {
  exitCode: number | null;
  stderr: string;
  stderrTruncated: boolean;
  stdout: string;
  stdoutTruncated: boolean;
}

export interface ParentIdentityProcessBoundary {
  run(invocation: ParentIdentityCommandInvocation): Promise<ParentIdentityCommandResult>;
}

export interface CaptureParentIdentityOptions {
  inheritedEnvironment?: NodeJS.ProcessEnv;
  parentPid?: number;
  platform?: NodeJS.Platform;
  process?: ParentIdentityProcessBoundary;
  signal?: AbortSignal;
  sourceRoot: string;
  timeoutMs?: number;
}

export class ParentIdentityError extends Error {
  readonly reason: ParentIdentityFailureReason;

  constructor(reason: ParentIdentityFailureReason, message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "ParentIdentityError";
    this.reason = reason;
  }
}

function validPositiveInteger(value: number, maximum = Number.MAX_SAFE_INTEGER): boolean {
  return Number.isSafeInteger(value) && value >= 1 && value <= maximum;
}

function platformPath(platform: NodeJS.Platform): typeof path.posix {
  return platform === "win32" ? path.win32 : path.posix;
}

export function activeSourcePythonPath(sourceRoot: string, platform: NodeJS.Platform = process.platform): string {
  const pathApi = platformPath(platform);
  return platform === "win32"
    ? pathApi.join(sourceRoot, ".venv", "Scripts", "python.exe")
    : pathApi.join(sourceRoot, ".venv", "bin", "python");
}

export function sourceGuardianScriptPath(sourceRoot: string, platform: NodeJS.Platform = process.platform): string {
  return platformPath(platform).join(sourceRoot, "packaging", "desktop_backend.py");
}

export function createParentIdentityEnvironment(
  inherited: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  return minimalChildEnvironment({ PYTHONNOUSERSITE: "1" }, inherited, platform);
}

/** Parse the probe's one complete line without trimming or prefix recovery. */
export function parseParentIdentityOutput(stdout: string, expectedParentPid: number): ParentIdentityProof {
  if (!stdout.endsWith("\n")) {
    throw new ParentIdentityError("probe", "Parent identity probe did not return a complete line.");
  }
  const body = stdout.endsWith("\r\n") ? stdout.slice(0, -2) : stdout.slice(0, -1);
  if (body.includes("\n") || body.includes("\r")) {
    throw new ParentIdentityError("probe", "Parent identity probe returned more than one line.");
  }
  const pattern = new RegExp(
    `^${PARENT_IDENTITY_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`
      + "v1\\|(darwin|linux|win32)\\|([1-9][0-9]*)\\|([A-Za-z0-9:._-]+)\\|([0-9a-f]{64})$",
  );
  const match = pattern.exec(body);
  if (!match) {
    throw new ParentIdentityError("probe", "Parent identity probe returned a non-canonical line.");
  }
  const parentPid = Number(match[2]);
  if (!validPositiveInteger(parentPid, MAX_PROCESS_ID) || parentPid !== expectedParentPid) {
    throw new ParentIdentityError("probe", "Parent identity probe PID did not match the Electron process PID.");
  }
  const platform = match[1] as ParentIdentityPlatform;
  const kernelStartToken = match[3]!;
  const imageSha256 = match[4]!;
  return {
    imageSha256,
    kernelStartToken,
    parentPid,
    platform,
    raw: `v1|${platform}|${parentPid}|${kernelStartToken}|${imageSha256}`,
  };
}

function appendBounded(current: string, chunk: Buffer, maximumBytes: number): { text: string; truncated: boolean } {
  const combined = Buffer.concat([Buffer.from(current, "utf8"), chunk]);
  if (combined.byteLength <= maximumBytes) return { text: combined.toString("utf8"), truncated: false };
  return { text: combined.subarray(0, maximumBytes).toString("utf8"), truncated: true };
}

export function createNodeParentIdentityProcessBoundary(): ParentIdentityProcessBoundary {
  return {
    run(invocation) {
      if (invocation.signal?.aborted) return Promise.reject(invocation.signal.reason);
      return new Promise<ParentIdentityCommandResult>((resolve, reject) => {
        let stdout = "";
        let stderr = "";
        let stdoutTruncated = false;
        let stderrTruncated = false;
        let settled = false;
        let timedOut = false;
        const child = spawn(invocation.command, [...invocation.args], {
          cwd: invocation.cwd,
          env: invocation.env,
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true,
        });
        const finish = (error: unknown, exitCode: number | null = null): void => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          invocation.signal?.removeEventListener("abort", onAbort);
          if (error !== null) reject(error);
          else resolve({ exitCode, stderr, stderrTruncated, stdout, stdoutTruncated });
        };
        const onAbort = (): void => {
          child.kill("SIGKILL");
          finish(invocation.signal?.reason ?? new Error("parent identity probe cancelled"));
        };
        const timer = setTimeout(() => {
          timedOut = true;
          child.kill("SIGKILL");
          finish(new Error("parent identity probe timed out"));
        }, invocation.timeoutMs);
        child.stdout.on("data", (chunk: Buffer) => {
          const appended = appendBounded(stdout, chunk, invocation.maxOutputBytes);
          stdout = appended.text;
          stdoutTruncated ||= appended.truncated;
        });
        child.stderr.on("data", (chunk: Buffer) => {
          const appended = appendBounded(stderr, chunk, invocation.maxOutputBytes);
          stderr = appended.text;
          stderrTruncated ||= appended.truncated;
        });
        child.once("error", (error) => finish(error));
        child.once("close", (exitCode) => {
          if (!timedOut) finish(null, exitCode);
        });
        invocation.signal?.addEventListener("abort", onAbort, { once: true });
      });
    },
  };
}

/** Capture the exact direct-parent generation before any launch token exists. */
export async function captureParentIdentity(options: CaptureParentIdentityOptions): Promise<ParentIdentityProof> {
  const platform = options.platform ?? process.platform;
  const pathApi = platformPath(platform);
  const parentPid = options.parentPid ?? process.pid;
  const timeoutMs = options.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
  if (!pathApi.isAbsolute(options.sourceRoot) || !validPositiveInteger(parentPid, MAX_PROCESS_ID)
    || !validPositiveInteger(timeoutMs)) {
    throw new ParentIdentityError("setup", "Parent identity probe inputs are invalid.");
  }
  if (options.signal?.aborted) {
    throw new ParentIdentityError("cancelled", "Parent identity probe was cancelled.");
  }
  const processBoundary = options.process ?? createNodeParentIdentityProcessBoundary();
  let result: ParentIdentityCommandResult;
  try {
    result = await processBoundary.run({
      args: [sourceGuardianScriptPath(options.sourceRoot, platform), PARENT_IDENTITY_ARGUMENT],
      command: activeSourcePythonPath(options.sourceRoot, platform),
      cwd: options.sourceRoot,
      env: createParentIdentityEnvironment(options.inheritedEnvironment, platform),
      maxOutputBytes: DEFAULT_OUTPUT_LIMIT_BYTES,
      ...(options.signal ? { signal: options.signal } : {}),
      timeoutMs,
    });
  } catch (error) {
    if (options.signal?.aborted) {
      throw new ParentIdentityError("cancelled", "Parent identity probe was cancelled.", error);
    }
    throw new ParentIdentityError("probe", "Parent identity probe failed.", error);
  }
  if (result.exitCode !== 0) {
    throw new ParentIdentityError("probe", "Parent identity probe exited unsuccessfully.");
  }
  if (result.stdoutTruncated || result.stderrTruncated) {
    throw new ParentIdentityError("probe", "Parent identity probe exceeded its bounded output allowance.");
  }
  if (result.stderr.length !== 0) {
    throw new ParentIdentityError("probe", "Parent identity probe returned unexpected diagnostics.");
  }
  return parseParentIdentityOutput(result.stdout, parentPid);
}
