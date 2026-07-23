import { createServer, type Server } from "node:http";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BackendHealthError,
  requestBackendHealth,
  waitForBackendHealth,
  type BackendHealthRequestBoundary,
} from "./backend-health";

const servers: Server[] = [];

async function listen(server: Server): Promise<number> {
  servers.push(server);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("fixture did not bind a port");
  return address.port;
}

afterEach(async () => {
  vi.restoreAllMocks();
  await Promise.all(servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))));
});

describe("backend health", () => {
  it("requests only the fixed loopback ping endpoint and accepts exact healthy JSON", async () => {
    const requests: Array<{
      host: string | undefined;
      method: string | undefined;
      url: string | undefined;
    }> = [];
    const port = await listen(createServer((request, response) => {
      requests.push({ host: request.headers.host, method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ status: "ok", timestamp: "fixture" }));
    }));

    const response = await requestBackendHealth(port, new AbortController().signal);
    expect(response).toEqual({ body: { status: "ok", timestamp: "fixture" }, statusCode: 200 });
    await expect(waitForBackendHealth({ port, retryIntervalMs: 5, timeoutMs: 100 })).resolves.toBe(true);
    expect(requests).toEqual([
      { host: `127.0.0.1:${port}`, method: "GET", url: "/api/v1/ping" },
      { host: `127.0.0.1:${port}`, method: "GET", url: "/api/v1/ping" },
    ]);
  });

  it.each([
    [{ body: { status: "ok" }, statusCode: 503 }],
    [{ body: { status: "OK" }, statusCode: 200 }],
    [{ body: null, statusCode: 200 }],
    [{ body: ["ok"], statusCode: 200 }],
  ])("retries responses that are not HTTP 200 object status=ok", async (unhealthy) => {
    const get = vi.fn()
      .mockResolvedValueOnce(unhealthy)
      .mockResolvedValueOnce({ body: { status: "ok" }, statusCode: 200 });

    await expect(waitForBackendHealth({
      port: 5100,
      request: { get },
      retryIntervalMs: 1,
      timeoutMs: 100,
    })).resolves.toBe(true);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("retries transient request failures", async () => {
    const get = vi.fn()
      .mockRejectedValueOnce(new Error("connection refused"))
      .mockResolvedValueOnce({ body: { status: "ok" }, statusCode: 200 });

    await expect(waitForBackendHealth({
      port: 5100,
      request: { get },
      retryIntervalMs: 1,
      timeoutMs: 100,
    })).resolves.toBe(true);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("enforces its deadline even when an injected request ignores cancellation", async () => {
    let observedSignal: AbortSignal | undefined;
    const request: BackendHealthRequestBoundary = {
      get(_port, signal) {
        observedSignal = signal;
        return new Promise(() => undefined);
      },
    };

    await expect(waitForBackendHealth({
      port: 5100,
      request,
      retryIntervalMs: 1,
      timeoutMs: 20,
    })).rejects.toMatchObject({ name: "BackendHealthError", reason: "timeout" });
    expect(observedSignal?.aborted).toBe(true);
  });

  it("propagates caller cancellation promptly", async () => {
    const controller = new AbortController();
    const request: BackendHealthRequestBoundary = {
      get: () => new Promise(() => undefined),
    };
    const health = waitForBackendHealth({
      port: 5100,
      request,
      retryIntervalMs: 1,
      signal: controller.signal,
      timeoutMs: 1_000,
    });

    controller.abort();
    await expect(health).rejects.toMatchObject({ name: "BackendHealthError", reason: "aborted" });
  });

  it.each([0, -1, 65_536, 1.5, Number.NaN])("rejects invalid port %j before requesting", async (port) => {
    const get = vi.fn();
    await expect(waitForBackendHealth({
      port,
      request: { get },
      retryIntervalMs: 1,
      timeoutMs: 10,
    })).rejects.toBeInstanceOf(BackendHealthError);
    expect(get).not.toHaveBeenCalled();
  });

  it("rejects invalid and oversized JSON bodies at the HTTP boundary", async () => {
    const invalidPort = await listen(createServer((_request, response) => {
      response.writeHead(200);
      response.end("not-json");
    }));
    await expect(requestBackendHealth(invalidPort, new AbortController().signal)).rejects.toThrow("valid JSON");

    const oversizedPort = await listen(createServer((_request, response) => {
      response.writeHead(200);
      response.end(`{"status":"ok","padding":"${"x".repeat(70_000)}"}`);
    }));
    await expect(requestBackendHealth(oversizedPort, new AbortController().signal)).rejects.toThrow("size limit");
  });
});
