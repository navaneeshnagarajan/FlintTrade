import { createServer, type Server } from "node:http";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CommandInvocation } from "./bootstrap";
import {
  CandidateHealthError,
  type CandidateHealthOptions,
  type CandidateHealthPingBoundary,
  type CandidateHealthProcessBoundary,
  type CandidateHealthProcessResult,
  createCandidateHealthEnvironment,
  parseCandidateReadyLine,
  proveCandidateHealth,
  requestCandidateFrontend,
  requestCandidatePing,
} from "./candidate-health";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const CONTAINED_STOP: CandidateHealthProcessResult = {
  contained: true,
  exitCode: 130,
  stderr: "",
  stderrTruncated: false,
  stdout: "",
  stdoutTruncated: false,
};

interface WaitingProcess {
  boundary: CandidateHealthProcessBoundary;
  cleanupObserved(): boolean;
  invocations: CommandInvocation[];
}

function waitForAbort(signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
}

function waitingProcess(
  onStart?: (invocation: CommandInvocation) => void,
  result: CandidateHealthProcessResult = CONTAINED_STOP,
): WaitingProcess {
  const invocations: CommandInvocation[] = [];
  let cleanup = false;
  return {
    boundary: {
      async run(invocation) {
        invocations.push(invocation);
        onStart?.(invocation);
        if (!invocation.signal) throw new Error("candidate process signal missing");
        await waitForAbort(invocation.signal);
        cleanup = true;
        return result;
      },
    },
    cleanupObserved: () => cleanup,
    invocations,
  };
}

async function listen(server: Server): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("loopback fixture did not bind a TCP port");
  return address.port;
}

async function close(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

describe("candidate health proof", () => {
  let root = "";
  let candidateRoot = "";
  let options: Omit<CandidateHealthOptions, "process">;

  beforeEach(async () => {
    root = await mkdtemp(path.join(tmpdir(), "flinttrade-candidate-health-test-"));
    candidateRoot = path.join(root, "candidate");
    await mkdir(candidateRoot, { recursive: true });
    options = {
      candidateRoot,
      frontend: {
        get: vi.fn().mockResolvedValue({
          body: "<!doctype html><html><body>FlintTrade</body></html>",
          contentType: "text/html; charset=utf-8",
          statusCode: 200,
        }),
      },
      isolation: {
        flinttradeHome: path.join(root, "isolated", "flinttrade-home"),
        home: path.join(root, "isolated", "home"),
        workspace: path.join(root, "isolated", "workspace"),
      },
      pingIntervalMs: 5,
      timeoutMs: 200,
    };
  });

  afterEach(async () => {
    await rm(root, { force: true, recursive: true });
  });

  it.each([
    ["FLINTTRADE_BACKEND_READY port=1", 1],
    ["FLINTTRADE_BACKEND_READY port=5100", 5100],
    ["FLINTTRADE_BACKEND_READY port=65535", 65_535],
  ])("parses the exact complete ready line %j", (line, expected) => {
    expect(parseCandidateReadyLine(line)).toBe(expected);
  });

  it.each([
    "",
    " FLINTTRADE_BACKEND_READY port=5100",
    "FLINTTRADE_BACKEND_READY port=5100 ",
    "prefix FLINTTRADE_BACKEND_READY port=5100",
    "FLINTTRADE_BACKEND_READY port=5100 trailing",
    "FLINTTRADE_BACKEND_READY port=5100\nextra",
    "FLINTTRADE_BACKEND_READY port=0",
    "FLINTTRADE_BACKEND_READY port=00001",
    "FLINTTRADE_BACKEND_READY port=65536",
    "FLINTTRADE_BACKEND_READY port=-1",
    "FLINTTRADE_BACKEND_READY port=1.5",
    "FLINTTRADE_BACKEND_READY port=abc",
  ])("rejects malformed or invalid ready line %j", (line) => {
    expect(parseCandidateReadyLine(line)).toBeNull();
  });

  it("uses the candidate interpreter, isolated allowlisted environment and a real loopback ping", async () => {
    const requests: Array<{ host: string | undefined; method: string | undefined; url: string | undefined }> = [];
    const server = createServer((request, response) => {
      requests.push({ host: request.headers.host, method: request.method, url: request.url });
      if (request.url === "/api/v1/ping") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ status: "ok", timestamp: "fixture" }));
        return;
      }
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end("<!doctype html><html><body>FlintTrade fixture</body></html>");
    });
    const port = await listen(server);
    const process = waitingProcess((invocation) => {
      queueMicrotask(() => invocation.onOutput?.(`FLINTTRADE_BACKEND_READY port=${port}`, "stdout"));
    });

    try {
      const { frontend: _frontend, ...realOptions } = options;
      await expect(proveCandidateHealth({ ...realOptions, process: process.boundary })).resolves.toEqual({
        candidateRoot,
        port,
      });
    } finally {
      await close(server);
    }

    expect(requests).toEqual([
      { host: `127.0.0.1:${port}`, method: "GET", url: "/api/v1/ping" },
      { host: `127.0.0.1:${port}`, method: "GET", url: "/" },
    ]);
    expect(process.cleanupObserved()).toBe(true);
    expect(process.invocations).toHaveLength(1);
    const invocation = process.invocations[0]!;
    expect(invocation).toMatchObject({
      args: ["-m", "flinttrade_core.desktop", "--port", "0"],
      command:
        globalThis.process.platform === "win32"
          ? path.join(candidateRoot, ".venv", "Scripts", "python.exe")
          : path.join(candidateRoot, ".venv", "bin", "python"),
      cwd: candidateRoot,
      inheritEnvironment: false,
      timeoutMs: options.timeoutMs,
    });
    expect(invocation.env).toEqual(
      createCandidateHealthEnvironment({
        candidateRoot,
        isolation: options.isolation,
      }),
    );
    expect(Object.keys(invocation.env ?? {}).sort()).toEqual([
      "FLINTTRADE_DESKTOP",
      "FLINTTRADE_FRONTEND_DIST",
      "FLINTTRADE_HOME",
      "FLINTTRADE_SOURCE_ROOT",
      "FLINTTRADE_WORKSPACE_DIR",
      "HOME",
      "PYTHONNOUSERSITE",
      ...(globalThis.process.platform === "win32" ? ["USERPROFILE"] : []),
    ]);
    expect(invocation.env).not.toHaveProperty("OPENAI_API_KEY");
    expect(invocation.env).not.toHaveProperty("OPENALGO_API_KEY");
  });

  it("binds the Windows user profile to the isolated home", () => {
    expect(createCandidateHealthEnvironment({
      candidateRoot,
      isolation: options.isolation,
    }, "win32")).toMatchObject({
      HOME: options.isolation.home,
      USERPROFILE: options.isolation.home,
    });
  });

  it("does not resolve a successful proof until process-tree cleanup finishes", async () => {
    let releaseCleanup!: () => void;
    const cleanupGate = new Promise<void>((resolve) => {
      releaseCleanup = resolve;
    });
    let cleanupStarted = false;
    const boundary: CandidateHealthProcessBoundary = {
      async run(invocation) {
        queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout"));
        if (!invocation.signal) throw new Error("candidate process signal missing");
        await waitForAbort(invocation.signal);
        cleanupStarted = true;
        await cleanupGate;
        return CONTAINED_STOP;
      },
    };
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };
    let settled = false;
    const proof = proveCandidateHealth({ ...options, ping, process: boundary }).finally(() => {
      settled = true;
    });

    await vi.waitFor(() => expect(cleanupStarted).toBe(true), { timeout: 15_000 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(settled).toBe(false);
    releaseCleanup();
    await expect(proof).resolves.toEqual({ candidateRoot, port: 5100 });
  });

  it("never probes ping before an exact stdout ready line", async () => {
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };
    const process = waitingProcess((invocation) => {
      queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100 trailing", "stdout"));
      queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stderr"));
    });

    await expect(
      proveCandidateHealth({ ...options, ping, process: process.boundary, timeoutMs: 80 }),
    ).rejects.toMatchObject({ reason: "timeout" });
    expect(ping.get).not.toHaveBeenCalled();
    expect(process.cleanupObserved()).toBe(true);
  });

  it.each([
    [{ body: { status: "ok" }, statusCode: 503 }, "non-200 status"],
    [{ body: { status: "degraded" }, statusCode: 200 }, "non-ok JSON"],
    [{ body: ["ok"], statusCode: 200 }, "non-object JSON"],
  ])("rejects a sentinel without a valid ping: %s", async (response, _label) => {
    const ping = { get: vi.fn().mockResolvedValue(response) };
    const process = waitingProcess((invocation) => {
      queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout"));
    });

    await expect(
      proveCandidateHealth({ ...options, ping, process: process.boundary, timeoutMs: 80 }),
    ).rejects.toMatchObject({ reason: "timeout" });
    expect(ping.get).toHaveBeenCalled();
    expect(process.cleanupObserved()).toBe(true);
  });

  it("rejects malformed JSON from the real loopback ping boundary", async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end("not-json");
    });
    const port = await listen(server);
    try {
      await expect(requestCandidatePing(port, new AbortController().signal)).rejects.toThrow(/JSON/i);
    } finally {
      await close(server);
    }
  });

  it("rejects an API-only candidate whose root is not the built terminal", async () => {
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };
    const frontend = {
      get: vi.fn().mockResolvedValue({
        body: JSON.stringify({ status: "ok" }),
        contentType: "application/json",
        statusCode: 200,
      }),
    };
    const process = waitingProcess((invocation) => {
      queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout"));
    });

    await expect(
      proveCandidateHealth({ ...options, frontend, ping, process: process.boundary, timeoutMs: 80 }),
    ).rejects.toMatchObject({ reason: "timeout" });
    expect(ping.get).toHaveBeenCalled();
    expect(frontend.get).toHaveBeenCalled();
    expect(process.cleanupObserved()).toBe(true);
  });

  it("requires a bounded HTML document from the real frontend boundary", async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end("<!doctype html><html><body>FlintTrade</body></html>");
    });
    const port = await listen(server);
    try {
      await expect(requestCandidateFrontend(port, new AbortController().signal)).resolves.toMatchObject({
        body: expect.stringContaining("FlintTrade"),
        contentType: "text/html; charset=utf-8",
        statusCode: 200,
      });
    } finally {
      await close(server);
    }
  });

  it("rejects a frontend response which exceeds the bounded health-proof body", async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(`<!doctype html><html><body>${"x".repeat(2 * 1024 * 1024)}</body></html>`);
    });
    const port = await listen(server);
    try {
      await expect(requestCandidateFrontend(port, new AbortController().signal)).rejects.toThrow(/size limit/i);
    } finally {
      await close(server);
    }
  });

  it("fails when the candidate exits before readiness and still closes its process boundary", async () => {
    let invocationSignal: AbortSignal | undefined;
    const boundary: CandidateHealthProcessBoundary = {
      async run(invocation) {
        invocationSignal = invocation.signal;
        return {
          contained: true,
          exitCode: 7,
          stderr: "fixture failed",
          stderrTruncated: false,
          stdout: "",
          stdoutTruncated: false,
        };
      },
    };

    await expect(proveCandidateHealth({ ...options, process: boundary })).rejects.toMatchObject({
      reason: "early-exit",
    });
    expect(invocationSignal?.aborted).toBe(true);
  });

  it("fails when the candidate exits after the sentinel but before ping succeeds", async () => {
    const boundary: CandidateHealthProcessBoundary = {
      async run(invocation) {
        invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout");
        await new Promise((resolve) => setTimeout(resolve, 5));
        return {
          contained: true,
          exitCode: 0,
          stderr: "",
          stderrTruncated: false,
          stdout: "",
          stdoutTruncated: false,
        };
      },
    };
    const ping: CandidateHealthPingBoundary = {
      get: vi.fn(() => new Promise<never>(() => undefined)),
    };

    await expect(proveCandidateHealth({ ...options, ping, process: boundary })).rejects.toMatchObject({
      reason: "early-exit",
    });
  });

  it("rejects an immediate post-sentinel exit even when ping reports healthy", async () => {
    const boundary: CandidateHealthProcessBoundary = {
      async run(invocation) {
        invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout");
        return {
          contained: true,
          exitCode: 0,
          stderr: "",
          stderrTruncated: false,
          stdout: "",
          stdoutTruncated: false,
        };
      },
    };
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };

    await expect(proveCandidateHealth({ ...options, ping, process: boundary })).rejects.toMatchObject({
      reason: "early-exit",
    });
  });

  it("cancels through the owned process signal and awaits cleanup", async () => {
    const abort = new AbortController();
    const process = waitingProcess();
    const proof = proveCandidateHealth({ ...options, process: process.boundary, signal: abort.signal });
    await vi.waitFor(() => expect(process.invocations).toHaveLength(1), { timeout: 15_000 });
    abort.abort();

    await expect(proof).rejects.toMatchObject({ reason: "cancelled" });
    expect(process.cleanupObserved()).toBe(true);
  });

  it("times out through the owned process signal and awaits cleanup", async () => {
    const process = waitingProcess();

    await expect(
      proveCandidateHealth({ ...options, process: process.boundary, timeoutMs: 50 }),
    ).rejects.toMatchObject({ reason: "timeout" });
    expect(process.cleanupObserved()).toBe(true);
  });

  it("fails closed when the process boundary cannot prove containment", async () => {
    const process = waitingProcess(
      (invocation) => {
        queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout"));
      },
      {
        contained: false,
        exitCode: 1,
        stderr: "containment unavailable",
        stderrTruncated: false,
        stdout: "",
        stdoutTruncated: false,
      },
    );
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };

    const proof = proveCandidateHealth({ ...options, ping, process: process.boundary });
    await expect(proof).rejects.toMatchObject({ reason: "cleanup" });
    await expect(proof).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(process.cleanupObserved()).toBe(true);
  });

  it("fails closed when the process boundary rejects during cleanup", async () => {
    const boundary: CandidateHealthProcessBoundary = {
      async run(invocation) {
        queueMicrotask(() => invocation.onOutput?.("FLINTTRADE_BACKEND_READY port=5100", "stdout"));
        if (!invocation.signal) throw new Error("candidate process signal missing");
        await waitForAbort(invocation.signal);
        throw new Error("cleanup fixture failed");
      },
    };
    const ping = { get: vi.fn().mockResolvedValue({ body: { status: "ok" }, statusCode: 200 }) };

    const proof = proveCandidateHealth({ ...options, ping, process: boundary });
    await expect(proof).rejects.toMatchObject({ reason: "cleanup" });
    await expect(proof).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
  });

  it("refuses a repository-root .env before spawning the candidate", async () => {
    await writeFile(path.join(candidateRoot, ".env"), "OPENAI_API_KEY=must-not-load\n");
    const run = vi.fn();

    await expect(
      proveCandidateHealth({ ...options, process: { run } }),
    ).rejects.toMatchObject({ reason: "setup" });
    expect(run).not.toHaveBeenCalled();
  });

  it("reports cancellation before spawn without invoking the process boundary", async () => {
    const abort = new AbortController();
    abort.abort();
    const run = vi.fn();

    await expect(
      proveCandidateHealth({ ...options, process: { run }, signal: abort.signal }),
    ).rejects.toEqual(expect.objectContaining<Partial<CandidateHealthError>>({ reason: "cancelled" }));
    expect(run).not.toHaveBeenCalled();
  });
});
