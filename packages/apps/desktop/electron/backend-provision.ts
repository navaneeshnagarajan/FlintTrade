import { spawn } from "node:child_process";
import path from "node:path";

import { minimalChildEnvironment } from "./bootstrap-io";
import { activeSourcePythonPath, sourceGuardianScriptPath } from "./parent-identity";

const DEFAULT_PROVISION_TIMEOUT_MS = 45_000;

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
  env: NodeJS.ProcessEnv;
  guardianPid: number;
  platform?: NodeJS.Platform;
  process?: BackendProvisionProcessBoundary;
  signal?: AbortSignal;
  sourceRoot: string;
  timeoutMs?: number;
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

export function createBackendProvisionEnvironment(
  workspace: string,
  inherited: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  const environment = minimalChildEnvironment({ FLINTTRADE_DESKTOP: "1", PYTHONNOUSERSITE: "1" }, inherited, platform);
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
      env: createBackendProvisionEnvironment(options.workspace, options.inheritedEnvironment, platform),
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
  if (exitCode !== 0) {
    throw new BackendProvisionError("provision", "Backend credential provisioning failed.");
  }
}

/**
 * Ask managed Python to remove only the exact, proven v4 record under its
 * cross-platform transition lock. JavaScript never unlinks recovery state.
 */
export async function finaliseBackendRecoveryRecord(
  options: FinaliseBackendRecoveryRecordOptions,
): Promise<void> {
  const platform = options.platform ?? process.platform;
  const pathApi = platformPath(platform);
  const timeoutMs = options.timeoutMs ?? DEFAULT_PROVISION_TIMEOUT_MS;
  const validPid = (value: number): boolean => Number.isSafeInteger(value) && value >= 1 && value <= 0xffff_ffff;
  if (!pathApi.isAbsolute(options.sourceRoot) || !validPid(options.guardianPid)
    || (options.applicationPid !== null && !validPid(options.applicationPid))
    || !Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    throw new BackendProvisionError("setup", "Backend recovery-record finalisation inputs are invalid.");
  }
  if (options.signal?.aborted) {
    throw new BackendProvisionError("cancelled", "Backend recovery-record finalisation was cancelled.");
  }
  const processBoundary = options.process ?? createNodeBackendProvisionProcessBoundary();
  let exitCode: number | null;
  try {
    ({ exitCode } = await processBoundary.execute({
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
    }));
  } catch {
    throw new BackendProvisionError("provision", "Backend recovery-record finalisation failed.");
  }
  if (exitCode !== 0) {
    throw new BackendProvisionError("provision", "Backend recovery-record finalisation failed.");
  }
}
