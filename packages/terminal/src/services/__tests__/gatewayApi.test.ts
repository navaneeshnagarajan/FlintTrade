/**
 * Tests for gatewayApi — FlintTrade Gateway REST API client.
 *
 * Verifies that:
 *   1. listBrokers makes a GET request and returns broker array
 *   2. addAccount makes a POST with correct body
 *   3. removeAccount makes a DELETE with encoded account ID
 *   4. Error responses throw with the server error message
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import { gatewayApi } from "../gatewayApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("gatewayApi", () => {
  it("listBrokers sends GET and returns broker array", async () => {
    const brokers = [
      { id: "zerodha", name: "Zerodha", auth_type: "api_key" },
      { id: "angel", name: "Angel One", auth_type: "api_key" },
    ];
    fetchSpy.mockResolvedValueOnce(jsonResponse({ brokers }));

    const result = await gatewayApi.listBrokers();

    expect(fetchSpy).toHaveBeenCalledWith("/ft-api/v1/brokers");
    expect(result).toEqual(brokers);
  });

  it("addAccount sends POST with broker, label, credentials", async () => {
    const account = { id: "acc-1", broker: "zerodha", label: "Main", status: "connected" };
    fetchSpy.mockResolvedValueOnce(jsonResponse({ account }));

    const result = await gatewayApi.addAccount("zerodha", "Main", {
      api_key: "key123",
      secret: "sec456",
    });

    expect(fetchSpy).toHaveBeenCalledWith("/ft-api/v1/auth/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        broker: "zerodha",
        label: "Main",
        credentials: { api_key: "key123", secret: "sec456" },
      }),
    });
    expect(result).toEqual(account);
  });

  it("removeAccount sends DELETE with URL-encoded account ID", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "deleted" }));

    await gatewayApi.removeAccount("acc/special&id");

    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toBe("/ft-api/v1/accounts/acc%2Fspecial%26id");
    expect(fetchSpy.mock.calls[0][1]).toEqual({ method: "DELETE" });
  });

  it("throws with server error message on non-OK response", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ message: "Broker not found" }, 404),
    );

    await expect(gatewayApi.listBrokers()).rejects.toThrow("Gateway: Broker not found");
  });
});
