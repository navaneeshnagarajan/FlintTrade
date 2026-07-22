import { lstat } from "node:fs/promises";
import { get as httpGet } from "node:http";
import path from "node:path";

import type { CommandInvocation, CommandResult } from "./bootstrap";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const READY_LINE = /^FLINTTRADE_BACKEND_READY port=([1-9][0-9]{0,4})$/;
const DEFAULT_TIMEOUT_MS = 180_000;
const DEFAULT_PING_INTERVAL_MS = 100;
const MAX_PING_BODY_BYTES = 64 * 1024;
const MAX_FRONTEND_BODY_BYTES = 2 * 1024 * 1024;

export type CandidateHealthFailureReason = "cancelled" | "cleanup" | "early-exit" | "setup" | "timeout";
export type CandidateHealthProcessInvocation = CommandInvocation;
export type CandidateHealthProcessResult = CommandResult;

export interface CandidateHealthProcessBoundary {
  /**
   * Launch with `invocation.env` as the candidate's complete managed
   * environment and resolve only after the owned process tree is contained.
   */
  run(invocation: CandidateHealthProcessInvocation): Promise<CandidateHealthProcessResult>;
}

export interface CandidatePingResponse {
  body: unknown;
  statusCode: number;
}

export interface CandidateHealthPingBoundary {
  get(port: number, signal: AbortSignal): Promise<CandidatePingResponse>;
}

export interface CandidateFrontendResponse {
  body: string;
  contentType: string;
  statusCode: number;
}

export interface CandidateHealthFrontendBoundary {
  get(port: number, signal: AbortSignal): Promise<CandidateFrontendResponse>;
}

export interface CandidateHealthIsolation {
  flinttradeHome: string;
  home: string;
  workspace: string;
}

export interface CandidateHealthEnvironmentInput {
  candidateRoot: string;
  isolation: CandidateHealthIsolation;
}

export interface CandidateHealthOptions {
  candidateRoot: string;
  frontend?: CandidateHealthFrontendBoundary;
  isolation: CandidateHealthIsolation;
  ping?: CandidateHealthPingBoundary;
  pingIntervalMs?: number;
  process: CandidateHealthProcessBoundary;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface CandidateHealthProof {
  candidateRoot: string;
  port: number;
}

export class CandidateHealthError extends Error {
  readonly reason: CandidateHealthFailureReason;

  constructor(reason: CandidateHealthFailureReason, message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "CandidateHealthError";
    this.reason = reason;
  }
}

export class CandidateHealthLeaseRetentionError extends SourceOperationLeaseRetentionError {
  readonly reason = "cleanup" as const;

  constructor(message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "CandidateHealthError";
  }
}

interface ProcessOutcome {
  error?: unknown;
  result?: CandidateHealthProcessResult;
}

function validPositiveMilliseconds(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0;
}

export function candidatePythonPath(candidateRoot: string): string {
  return process.platform === "win32"
    ? path.join(candidateRoot, ".venv", "Scripts", "python.exe")
    : path.join(candidateRoot, ".venv", "bin", "python");
}

function candidateFrontend(candidateRoot: string): string {
  return path.join(candidateRoot, "packages", "apps", "terminal", "dist");
}

function assertAbsolutePaths(input: CandidateHealthEnvironmentInput): void {
  const paths = [
    ["candidate root", input.candidateRoot],
    ["isolated HOME", input.isolation.home],
    ["isolated FlintTrade home", input.isolation.flinttradeHome],
    ["isolated workspace", input.isolation.workspace],
  ] as const;
  for (const [label, target] of paths) {
    if (!path.isAbsolute(target)) {
      throw new CandidateHealthError("setup", `Candidate health ${label} must be an absolute path.`);
    }
  }
}

export async function assertCandidateRepositoryEnvironmentAbsent(candidateRoot: string): Promise<void> {
  try {
    await lstat(path.join(candidateRoot, ".env"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw new CandidateHealthError("setup", "Candidate repository .env could not be safely excluded.", error);
  }
  throw new CandidateHealthError("setup", "Candidate repository contains a forbidden .env file.");
}

function cancellationError(): CandidateHealthError {
  return new CandidateHealthError("cancelled", "Candidate health proof was cancelled.");
}

function earlyExitError(outcome: ProcessOutcome): CandidateHealthError {
  if (outcome.result) {
    return new CandidateHealthError(
      "early-exit",
      `Candidate backend exited before health proof completed (exit ${outcome.result.exitCode}).`,
    );
  }
  return new CandidateHealthError("early-exit", "Candidate process boundary failed before health proof completed.");
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    timer.unref?.();
  });
}

function isHealthyPing(response: CandidatePingResponse): boolean {
  return (
    response.statusCode === 200 &&
    response.body !== null &&
    typeof response.body === "object" &&
    !Array.isArray(response.body) &&
    (response.body as { status?: unknown }).status === "ok"
  );
}

function isHealthyFrontend(response: CandidateFrontendResponse): boolean {
  return (
    response.statusCode === 200 &&
    response.contentType.toLowerCase().split(";", 1)[0]?.trim() === "text/html" &&
    /^\s*<!doctype\s+html(?:\s|>)/i.test(response.body) &&
    /<html(?:\s|>)/i.test(response.body)
  );
}

export function parseCandidateReadyLine(line: string): number | null {
  const match = READY_LINE.exec(line);
  if (!match) return null;
  const port = Number(match[1]);
  return Number.isSafeInteger(port) && port >= 1 && port <= 65_535 ? port : null;
}

export function createCandidateHealthEnvironment(
  input: CandidateHealthEnvironmentInput,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  assertAbsolutePaths(input);
  return {
    FLINTTRADE_DESKTOP: "1",
    FLINTTRADE_FRONTEND_DIST: candidateFrontend(input.candidateRoot),
    FLINTTRADE_HOME: input.isolation.flinttradeHome,
    FLINTTRADE_SOURCE_ROOT: input.candidateRoot,
    FLINTTRADE_WORKSPACE_DIR: input.isolation.workspace,
    HOME: input.isolation.home,
    PYTHONNOUSERSITE: "1",
    ...(platform === "win32" ? { USERPROFILE: input.isolation.home } : {}),
  };
}

export function requestCandidatePing(port: number, signal: AbortSignal): Promise<CandidatePingResponse> {
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    return Promise.reject(new Error("Candidate ping port is invalid."));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error: unknown, response?: CandidatePingResponse): void => {
      if (settled) return;
      settled = true;
      if (error !== null) reject(error);
      else resolve(response!);
    };
    const request = httpGet(
      {
        agent: false,
        headers: { connection: "close" },
        hostname: "127.0.0.1",
        method: "GET",
        path: "/api/v1/ping",
        port,
        signal,
      },
      (response) => {
        let body = "";
        let bytes = 0;
        response.setEncoding("utf8");
        response.on("data", (chunk: string) => {
          bytes += Buffer.byteLength(chunk);
          if (bytes > MAX_PING_BODY_BYTES) {
            response.destroy();
            finish(new Error("Candidate ping response exceeded its size limit."));
            return;
          }
          body += chunk;
        });
        response.once("aborted", () => finish(new Error("Candidate ping response was interrupted.")));
        response.once("error", (error) => finish(error));
        response.once("end", () => {
          if (settled) return;
          let parsed: unknown;
          try {
            parsed = JSON.parse(body) as unknown;
          } catch (error) {
            finish(new Error("Candidate ping did not return valid JSON.", { cause: error }));
            return;
          }
          finish(null, { body: parsed, statusCode: response.statusCode ?? 0 });
        });
      },
    );
    request.once("error", (error) => finish(error));
  });
}

export function requestCandidateFrontend(port: number, signal: AbortSignal): Promise<CandidateFrontendResponse> {
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    return Promise.reject(new Error("Candidate frontend port is invalid."));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error: unknown, response?: CandidateFrontendResponse): void => {
      if (settled) return;
      settled = true;
      if (error !== null) reject(error);
      else resolve(response!);
    };
    const request = httpGet(
      {
        agent: false,
        headers: { accept: "text/html", connection: "close" },
        hostname: "127.0.0.1",
        method: "GET",
        path: "/",
        port,
        signal,
      },
      (response) => {
        let body = "";
        let bytes = 0;
        response.setEncoding("utf8");
        response.on("data", (chunk: string) => {
          bytes += Buffer.byteLength(chunk);
          if (bytes > MAX_FRONTEND_BODY_BYTES) {
            finish(new Error("Candidate frontend response exceeded its size limit."));
            response.destroy();
            return;
          }
          body += chunk;
        });
        response.once("aborted", () => finish(new Error("Candidate frontend response was interrupted.")));
        response.once("error", (error) => finish(error));
        response.once("end", () => {
          finish(null, {
            body,
            contentType: String(response.headers["content-type"] ?? ""),
            statusCode: response.statusCode ?? 0,
          });
        });
      },
    );
    request.once("error", (error) => finish(error));
  });
}

export async function proveCandidateHealth(options: CandidateHealthOptions): Promise<CandidateHealthProof> {
  if (options.signal?.aborted) throw cancellationError();
  assertAbsolutePaths({ candidateRoot: options.candidateRoot, isolation: options.isolation });
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const pingIntervalMs = options.pingIntervalMs ?? DEFAULT_PING_INTERVAL_MS;
  if (!validPositiveMilliseconds(timeoutMs) || !validPositiveMilliseconds(pingIntervalMs)) {
    throw new CandidateHealthError("setup", "Candidate health timing bounds must be positive safe integers.");
  }
  await assertCandidateRepositoryEnvironmentAbsent(options.candidateRoot);
  if (options.signal?.aborted) throw cancellationError();

  const ownedAbort = new AbortController();
  const environment = createCandidateHealthEnvironment({
    candidateRoot: options.candidateRoot,
    isolation: options.isolation,
  });
  let readyResolved = false;
  let resolveReady!: (port: number) => void;
  const ready = new Promise<number>((resolve) => {
    resolveReady = resolve;
  });
  const invocation: CandidateHealthProcessInvocation = {
    args: ["-m", "flinttrade_core.desktop", "--port", "0"],
    command: candidatePythonPath(options.candidateRoot),
    cwd: options.candidateRoot,
    env: environment,
    inheritEnvironment: false,
    onOutput(line, stream) {
      if (readyResolved || stream !== "stdout") return;
      const port = parseCandidateReadyLine(line);
      if (port === null) return;
      readyResolved = true;
      resolveReady(port);
    },
    signal: ownedAbort.signal,
    timeoutMs,
  };
  const processOutcome = Promise.resolve()
    .then(() => options.process.run(invocation))
    .then(
      (result): ProcessOutcome => ({ result }),
      (error: unknown): ProcessOutcome => ({ error }),
    );
  const processEnded = processOutcome.then<never>((outcome) => {
    throw earlyExitError(outcome);
  });

  let stage = "the ready sentinel";
  let removeCallerAbort = (): void => undefined;
  const cancelled = new Promise<never>((_resolve, reject) => {
    if (!options.signal) return;
    const onAbort = () => reject(cancellationError());
    if (options.signal.aborted) {
      onAbort();
      return;
    }
    options.signal.addEventListener("abort", onAbort, { once: true });
    removeCallerAbort = () => options.signal?.removeEventListener("abort", onAbort);
  });
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<never>((_resolve, reject) => {
    timeout = setTimeout(() => {
      reject(new CandidateHealthError("timeout", `Candidate health proof timed out while waiting for ${stage}.`));
    }, timeoutMs);
    timeout.unref?.();
  });

  let failure: unknown;
  let proof: CandidateHealthProof | undefined;
  try {
    const port = await Promise.race([ready, processEnded, cancelled, timedOut]);
    stage = "the loopback ping";
    const ping = options.ping ?? { get: requestCandidatePing };
    while (true) {
      const response = await Promise.race([
        Promise.resolve()
          .then(() => ping.get(port, ownedAbort.signal))
          .then(
            (value) => ({ kind: "response" as const, value }),
            (error: unknown) => ({ error, kind: "error" as const }),
          ),
        processEnded,
        cancelled,
        timedOut,
      ]);
      if (response.kind === "response" && isHealthyPing(response.value)) {
        stage = "the terminal frontend";
        const frontend = options.frontend ?? { get: requestCandidateFrontend };
        const frontendResponse = await Promise.race([
          Promise.resolve()
            .then(() => frontend.get(port, ownedAbort.signal))
            .then(
              (value) => ({ kind: "response" as const, value }),
              (error: unknown) => ({ error, kind: "error" as const }),
            ),
          processEnded,
          cancelled,
          timedOut,
        ]);
        if (frontendResponse.kind === "response" && isHealthyFrontend(frontendResponse.value)) {
          proof = { candidateRoot: options.candidateRoot, port };
          break;
        }
        stage = "the loopback ping and terminal frontend";
      }
      await Promise.race([wait(pingIntervalMs), processEnded, cancelled, timedOut]);
    }
  } catch (error) {
    failure = error;
  }

  if (timeout) clearTimeout(timeout);
  removeCallerAbort();
  ownedAbort.abort();
  const outcome = await processOutcome;
  if (!outcome.result) {
    throw new CandidateHealthLeaseRetentionError(
      "Candidate process-tree cleanup could not be proven.",
      outcome.error,
    );
  }
  if (!outcome.result.contained) {
    throw new CandidateHealthLeaseRetentionError(
      "Candidate process-tree cleanup could not be proven.",
    );
  }
  if (failure !== undefined) throw failure;
  return proof!;
}
