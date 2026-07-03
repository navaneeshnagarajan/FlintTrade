/**
 * Tests for gatewayApi — FlintTrade Gateway REST API client.
 *
 * Verifies that:
 *   1. listBrokers makes a GET request and returns broker array
 *   2. addAccount makes a POST with correct body
 *   3. removeAccount makes a DELETE with encoded account ID
 *   4. Error responses throw with the server error message
 *   5. The operator session JWT is attached when present (backend G9 guard
 *      rejects gateway management writes without it)
 */

import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import { gatewayApi } from "../gatewayApi";
import { useAuthStore } from "@/stores/authStore";

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

let fetchSpy: MockInstance<typeof globalThis.fetch>;

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

    expect(fetchSpy).toHaveBeenCalledWith("/ft-api/v1/brokers", { headers: {} });
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
    expect(fetchSpy.mock.calls[0][1]).toEqual({ method: "DELETE", headers: {} });
  });

  it("attaches the session JWT on writes (backend G9 write guard)", async () => {
    useAuthStore.setState({ token: "jwt-abc" });
    try {
      fetchSpy.mockResolvedValueOnce(jsonResponse({ account: {} }));
      await gatewayApi.addAccount("zerodha", "Main", { api_key: "k" });
      const init = fetchSpy.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer jwt-abc");
    } finally {
      useAuthStore.setState({ token: null });
    }
  });

  it("throws with server error message on non-OK response", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ message: "Broker not found" }, 404),
    );

    await expect(gatewayApi.listBrokers()).rejects.toThrow("Gateway: Broker not found");
  });
});
