import { get as httpGet } from "node:http";

const MAX_HEALTH_BODY_BYTES = 64 * 1_024;
const DEFAULT_HEALTH_TIMEOUT_MS = 180_000;
const DEFAULT_RETRY_INTERVAL_MS = 100;

export type BackendHealthFailureReason = "aborted" | "setup" | "timeout";

export interface BackendHealthResponse {
  body: unknown;
  statusCode: number;
}

export interface BackendHealthRequestBoundary {
  get(port: number, signal: AbortSignal): Promise<BackendHealthResponse>;
}

export interface BackendHealthOptions {
  port: number;
  request?: BackendHealthRequestBoundary;
  retryIntervalMs?: number;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export class BackendHealthError extends Error {
  readonly reason: BackendHealthFailureReason;

  constructor(reason: BackendHealthFailureReason, message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "BackendHealthError";
    this.reason = reason;
  }
}

function validPort(port: number): boolean {
  return Number.isSafeInteger(port) && port >= 1 && port <= 65_535;
}

function validPositiveMilliseconds(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0;
}

function healthy(response: BackendHealthResponse): boolean {
  return response.statusCode === 200
    && response.body !== null
    && typeof response.body === "object"
    && !Array.isArray(response.body)
    && (response.body as { status?: unknown }).status === "ok";
}

function abortable<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const finish = (callback: (value: T | unknown) => void, value: T | unknown): void => {
      signal.removeEventListener("abort", onAbort);
      callback(value);
    };
    const onAbort = (): void => finish(reject, signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    operation.then(
      (value) => finish(resolve as (value: T | unknown) => void, value),
      (error: unknown) => finish(reject, error),
    );
  });
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Perform one fixed-host loopback HTTP health request. */
export function requestBackendHealth(port: number, signal: AbortSignal): Promise<BackendHealthResponse> {
  if (!validPort(port)) return Promise.reject(new BackendHealthError("setup", "Backend health port is invalid."));
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error: unknown, response?: BackendHealthResponse): void => {
      if (settled) return;
      settled = true;
      if (error !== null) reject(error);
      else resolve(response!);
    };
    const request = httpGet({
      agent: false,
      headers: { connection: "close" },
      hostname: "127.0.0.1",
      method: "GET",
      path: "/api/v1/ping",
      port,
      signal,
    }, (response) => {
      let body = "";
      let bodyBytes = 0;
      response.setEncoding("utf8");
      response.on("data", (chunk: string) => {
        bodyBytes += Buffer.byteLength(chunk, "utf8");
        if (bodyBytes > MAX_HEALTH_BODY_BYTES) {
          finish(new Error("Backend health response exceeded its size limit."));
          response.destroy();
          return;
        }
        body += chunk;
      });
      response.once("aborted", () => finish(new Error("Backend health response was interrupted.")));
      response.once("error", (error) => finish(error));
      response.once("end", () => {
        if (settled) return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(body) as unknown;
        } catch (error) {
          finish(new Error("Backend health response was not valid JSON.", { cause: error }));
          return;
        }
        finish(null, { body: parsed, statusCode: response.statusCode ?? 0 });
      });
    });
    request.once("error", (error) => finish(error));
  });
}

const DEFAULT_REQUEST: BackendHealthRequestBoundary = { get: requestBackendHealth };

/** Retry loopback health until success, caller cancellation, or the hard deadline. */
export async function waitForBackendHealth(options: BackendHealthOptions): Promise<true> {
  if (!validPort(options.port)) throw new BackendHealthError("setup", "Backend health port is invalid.");
  const timeoutMs = options.timeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  const retryIntervalMs = options.retryIntervalMs ?? DEFAULT_RETRY_INTERVAL_MS;
  if (!validPositiveMilliseconds(timeoutMs) || !validPositiveMilliseconds(retryIntervalMs)) {
    throw new BackendHealthError("setup", "Backend health timing bounds must be positive safe integers.");
  }
  if (options.signal?.aborted) throw new BackendHealthError("aborted", "Backend health check was cancelled.");

  const controller = new AbortController();
  let timedOut = false;
  let lastFailure: unknown;
  const onCallerAbort = (): void => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", onCallerAbort, { once: true });
  const deadline = setTimeout(() => {
    timedOut = true;
    controller.abort(new Error("backend health deadline elapsed"));
  }, timeoutMs);
  const request = options.request ?? DEFAULT_REQUEST;

  try {
    while (true) {
      try {
        const response = await abortable(request.get(options.port, controller.signal), controller.signal);
        if (healthy(response)) return true;
      } catch (error) {
        if (controller.signal.aborted) {
          throw new BackendHealthError(
            timedOut ? "timeout" : "aborted",
            timedOut ? "Backend health check timed out." : "Backend health check was cancelled.",
            lastFailure,
          );
        }
        lastFailure = error;
      }
      try {
        await wait(retryIntervalMs, controller.signal);
      } catch {
        throw new BackendHealthError(
          timedOut ? "timeout" : "aborted",
          timedOut ? "Backend health check timed out." : "Backend health check was cancelled.",
          lastFailure,
        );
      }
    }
  } finally {
    clearTimeout(deadline);
    options.signal?.removeEventListener("abort", onCallerAbort);
  }
}
