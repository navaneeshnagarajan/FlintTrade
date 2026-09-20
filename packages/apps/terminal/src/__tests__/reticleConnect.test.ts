/**
 * Reticle must not open ws://localhost:4400 during Playwright CI.
 *
 * The fail-closed e2e registry treats WebSocket "connection refused" console
 * errors as failures (order-pad-practice + workspace-lifecycle). Official
 * `@reticlehq/vite-plugin` injects connect() on Vite serve; we only inject
 * when an operator has asked for it *and* a daemon is already listening.
 */
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  RETICLE_BRIDGE_HOST,
  isReticleDaemonListening,
  reticleBridgePort,
  shouldInjectReticleConnect,
} from "../reticleConnectGate";

describe("shouldInjectReticleConnect", () => {
  it("no-ops when the daemon port is closed", () => {
    expect(
      shouldInjectReticleConnect({
        env: {},
        isDaemonListening: () => false,
      }),
    ).toBe(false);
  });

  it("injects only when the daemon is already listening", () => {
    expect(
      shouldInjectReticleConnect({
        env: {},
        isDaemonListening: () => true,
      }),
    ).toBe(true);
  });

  it("honours RETICLE_CONNECT=0 even if a daemon is up (e2e/CI env gate)", () => {
    expect(
      shouldInjectReticleConnect({
        env: { RETICLE_CONNECT: "0" },
        isDaemonListening: () => true,
      }),
    ).toBe(false);
  });

  it("still no-ops when RETICLE_CONNECT=1 but nothing is listening", () => {
    expect(
      shouldInjectReticleConnect({
        env: { RETICLE_CONNECT: "1" },
        isDaemonListening: () => false,
      }),
    ).toBe(false);
  });

  it("reads RETICLE_PORT for the probe", () => {
    const ports: number[] = [];
    shouldInjectReticleConnect({
      env: { RETICLE_PORT: "4411" },
      isDaemonListening: (_host: string, port: number) => {
        ports.push(port);
        return false;
      },
    });
    expect(ports).toEqual([4411]);
    expect(reticleBridgePort({ RETICLE_PORT: "4411" })).toBe(4411);
  });
});

describe("Vite Reticle wiring", () => {
  it("uses the official inject option gated by shouldInjectReticleConnect", () => {
    const source = fs.readFileSync(path.resolve(import.meta.dirname, "../../vite.config.ts"), "utf8");
    expect(source).toContain("inject: shouldInjectReticleConnect()");
  });

  it("forces RETICLE_CONNECT=0 on the Playwright webServer used by fail-closed journeys", () => {
    const source = fs.readFileSync(
      path.resolve(import.meta.dirname, "../../playwright.config.ts"),
      "utf8",
    );
    expect(source).toContain("RETICLE_CONNECT: '0'");
  });
});

describe("isReticleDaemonListening", () => {
  it("returns false for a closed loopback port", () => {
    expect(isReticleDaemonListening(RETICLE_BRIDGE_HOST, 1)).toBe(false);
  });

  it("returns true for a bound loopback port", async () => {
    const server = net.createServer();
    await new Promise<void>((resolve) => {
      server.listen(0, RETICLE_BRIDGE_HOST, resolve);
    });
    const address = server.address();
    if (address === null || typeof address === "string") {
      server.close();
      throw new Error("expected a TCP address");
    }
    try {
      expect(isReticleDaemonListening(RETICLE_BRIDGE_HOST, address.port)).toBe(true);
    } finally {
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    }
  });
});
