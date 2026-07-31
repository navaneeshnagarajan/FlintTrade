import { spawn } from "node:child_process";
import path from "node:path";

import { minimalChildEnvironment } from "./bootstrap-io";
import { activeSourcePythonPath, sourceGuardianScriptPath } from "./parent-identity";

const DEFAULT_PROVISION_TIMEOUT_MS = 45_000;

/**
 * Provisioning did not complete, but re-proved that the existing credential-vault
 * secret is present and hardened under the full at-rest policy.
 *
 * Mirrors `flinttrade_core.cli.EXIT_PROVISION_DEGRADED`. The backend only needs
 * that secret to exist and be readable, so refusing to launch would turn a
 * transient provisioning hiccup into a shell that will not open.
 */
const EXIT_PROVISION_DEGRADED = 3;

/**
 * Managed cleanup found the recovery-record transition lock held by a concurrent
 * transition and therefore removed nothing.
 *
 * Mirrors `packaging/desktop_backend.py::CLEANUP_CONTENDED_EXIT_CODE`. Python
 * already waits the lock out for `CLEANUP_GUARD_CONTENTION_SECONDS` before
 * reporting it, so this status means "another transition still holds the lock",
 * never "cleanup could not be proved" - nothing was mutated and the call is safe
 * to repeat. The dedicated status exists precisely so a caller reading only the
 * exit code can tell the two apart; collapsing it back into the generic failure
 * would latch the supervisor's record interlock on a transient Windows lock and
 * refuse every later backend start for the life of the shell.
 */
const EXIT_CLEANUP_CONTENDED = 75;

/** Total managed-cleanup invocations tolerated while the transition lock stays held. */
const DEFAULT_CLEANUP_CONTENTION_ATTEMPTS = 4;

/** Pause between contended managed-cleanup invocations. */
const DEFAULT_CLEANUP_CONTENTION_RETRY_MS = 250;

export type BackendProvisionFailureReason = "cancelled" | "provision" | "setup";

export interface BackendProvisionInvocation {
  args: readonly string[];
  command: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  output: "discard";
  signal?: AbortSignal;
  timeoutMs: number;
}

export interface BackendProvisionProcessBoundary {
  execute(invocation: BackendProvisionInvocation): Promise<{ exitCode: number | null }>;
}

export interface ProvisionBackendMasterPasswordOptions {
  inheritedEnvironment?: NodeJS.ProcessEnv;
  platform?: NodeJS.Platform;
  process?: BackendProvisionProcessBoundary;
  signal?: AbortSignal;
  sourceRoot: string;
  timeoutMs?: number;
  workspace: string;
}

export interface FinaliseBackendRecoveryRecordOptions {
  applicationPid: number | null;
  /** Total invocations tolerated while managed cleanup reports lock contention. */
  contentionAttempts?: number;
  /** Pause between contended invocations. */
  contentionRetryIntervalMs?: number;
  env: NodeJS.ProcessEnv;
  guardianPid: number;
  platform?: NodeJS.Platform;
  process?: BackendProvisionProcessBoundary;
  signal?: AbortSignal;
  sourceRoot: string;
  timeoutMs?: number;
  wait?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
}

export class BackendProvisionError extends Error {
  readonly reason: BackendProvisionFailureReason;

  constructor(reason: BackendProvisionFailureReason, message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "BackendProvisionError";
    this.reason = reason;
  }
}

function platformPath(platform: NodeJS.Platform): typeof path.posix {
  return platform === "win32" ? path.win32 : path.posix;
}

/** Pause between retries, rejecting the moment the caller cancels. */
function defaultWait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(signal.reason);
  return new Promise<void>((resolve, reject) => {
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export function createBackendProvisionEnvironment(
  sourceRoot: string,
  workspace: string,
  inherited: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  const environment = minimalChildEnvironment({ FLINTTRADE_DESKTOP: "1", PYTHONNOUSERSITE: "1" }, inherited, platform);
  environment.FLINTTRADE_SOURCE_ROOT = sourceRoot;
  environment.FLINTTRADE_WORKSPACE_DIR = workspace;
  return environment;
}

export function createNodeBackendProvisionProcessBoundary(): BackendProvisionProcessBoundary {
  return {
    execute(invocation) {
      if (invocation.signal?.aborted) return Promise.reject(invocation.signal.reason);
      return new Promise((resolve, reject) => {
        let settled = false;
        const child = spawn(invocation.command, [...invocation.args], {
          cwd: invocation.cwd,
          env: invocation.env,
          stdio: "ignore",
          windowsHide: true,
        });
        const finish = (error: unknown, exitCode: number | null = null): void => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          invocation.signal?.removeEventListener("abort", onAbort);
          if (error !== null) reject(error);
          else resolve({ exitCode });
        };
        const onAbort = (): void => {
          child.kill("SIGKILL");
          finish(invocation.signal?.reason ?? new Error("backend provisioning cancelled"));
        };
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          finish(new Error("backend provisioning timed out"));
        }, invocation.timeoutMs);
        child.once("error", (error) => finish(error));
        child.once("close", (exitCode) => finish(null, exitCode));
        invocation.signal?.addEventListener("abort", onAbort, { once: true });
      });
    },
  };
}

/** Ask managed Python to provision and verify the vault secret without exposing it to JavaScript. */
export async function provisionBackendMasterPassword(
  options: ProvisionBackendMasterPasswordOptions,
): Promise<void> {
  const platform = options.platform ?? process.platform;
  const pathApi = platformPath(platform);
  const timeoutMs = options.timeoutMs ?? DEFAULT_PROVISION_TIMEOUT_MS;
  if (!pathApi.isAbsolute(options.sourceRoot) || !pathApi.isAbsolute(options.workspace)
    || !Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new BackendProvisionError("setup", "Backend credential provisioning inputs are invalid.");
  }
  if (options.signal?.aborted) {
    throw new BackendProvisionError("cancelled", "Backend credential provisioning was cancelled.");
  }
  const processBoundary = options.process ?? createNodeBackendProvisionProcessBoundary();
  let exitCode: number | null;
  try {
    ({ exitCode } = await processBoundary.execute({
      args: ["-m", "flinttrade_core.cli", "init", "--provision-master-password"],
      command: activeSourcePythonPath(options.sourceRoot, platform),
      cwd: options.sourceRoot,
      env: createBackendProvisionEnvironment(options.sourceRoot, options.workspace, options.inheritedEnvironment, platform),
      output: "discard",
      ...(options.signal ? { signal: options.signal } : {}),
      timeoutMs,
    }));
  } catch (error) {
    if (options.signal?.aborted) {
      throw new BackendProvisionError("cancelled", "Backend credential provisioning was cancelled.", error);
    }
    throw new BackendProvisionError("provision", "Backend credential provisioning failed.");
  }
  if (exitCode !== 0 && exitCode !== EXIT_PROVISION_DEGRADED) {
    throw new BackendProvisionError("provision", "Backend credential provisioning failed.");
  }
}

/**
 * Ask managed Python to remove only the exact, proven v4 record under its
 * cross-platform transition lock. JavaScript never unlinks recovery state.
 *
 * Every failure is fail-closed on its first occurrence with one exception:
 * {@link EXIT_CLEANUP_CONTENDED}, which proves the record was left untouched
 * because a concurrent transition holds its lock. That one status is retried a
 * bounded number of times before it too fails closed, so a transient lock no
 * longer masquerades as unproved cleanup while a genuine cleanup failure keeps
 * blocking the supervisor exactly as before.
 */
export async function finaliseBackendRecoveryRecord(
  options: FinaliseBackendRecoveryRecordOptions,
): Promise<void> {
  const platform = options.platform ?? process.platform;
  const pathApi = platformPath(platform);
  const timeoutMs = options.timeoutMs ?? DEFAULT_PROVISION_TIMEOUT_MS;
  const contentionAttempts = options.contentionAttempts ?? DEFAULT_CLEANUP_CONTENTION_ATTEMPTS;
  const contentionRetryIntervalMs = options.contentionRetryIntervalMs ?? DEFAULT_CLEANUP_CONTENTION_RETRY_MS;
  const validPid = (value: number): boolean => Number.isSafeInteger(value) && value >= 1 && value <= 0xffff_ffff;
  if (!pathApi.isAbsolute(options.sourceRoot) || !validPid(options.guardianPid)
    || (options.applicationPid !== null && !validPid(options.applicationPid))
    || !Number.isSafeInteger(timeoutMs) || timeoutMs <= 0
    || !Number.isSafeInteger(contentionAttempts) || contentionAttempts < 1
    || !Number.isSafeInteger(contentionRetryIntervalMs) || contentionRetryIntervalMs < 0) {
    throw new BackendProvisionError("setup", "Backend recovery-record finalisation inputs are invalid.");
  }
  if (options.signal?.aborted) {
    throw new BackendProvisionError("cancelled", "Backend recovery-record finalisation was cancelled.");
  }
  const processBoundary = options.process ?? createNodeBackendProvisionProcessBoundary();
  const wait = options.wait ?? defaultWait;
  const invocation: BackendProvisionInvocation = {
    args: [
      sourceGuardianScriptPath(options.sourceRoot, platform),
      "--flinttrade-finalise-cleanup",
      "--guardian-pid",
      String(options.guardianPid),
      "--application-pid",
      options.applicationPid === null ? "pending" : String(options.applicationPid),
    ],
    command: activeSourcePythonPath(options.sourceRoot, platform),
    cwd: options.sourceRoot,
    env: options.env,
    output: "discard",
    ...(options.signal ? { signal: options.signal } : {}),
    timeoutMs,
  };

  for (let attempt = 1; ; attempt += 1) {
    let exitCode: number | null;
    try {
      ({ exitCode } = await processBoundary.execute(invocation));
    } catch {
      throw new BackendProvisionError("provision", "Backend recovery-record finalisation failed.");
    }
    if (exitCode === 0) return;
    // Only the dedicated contention status is retryable. Every other nonzero
    // status - and a null one - still fails closed on the first attempt.
    if (exitCode !== EXIT_CLEANUP_CONTENDED) {
      throw new BackendProvisionError("provision", "Backend recovery-record finalisation failed.");
    }
    if (attempt >= contentionAttempts) {
      throw new BackendProvisionError(
        "provision",
        "Backend recovery-record finalisation stayed contended; recovery state was retained.",
      );
    }
    try {
      await wait(contentionRetryIntervalMs, options.signal);
    } catch {
      throw new BackendProvisionError("cancelled", "Backend recovery-record finalisation was cancelled.");
    }
    if (options.signal?.aborted) {
      throw new BackendProvisionError("cancelled", "Backend recovery-record finalisation was cancelled.");
    }
  }
}
