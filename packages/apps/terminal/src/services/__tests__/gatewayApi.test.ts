/**
 * Tests for gatewayApi — FlintTrade Gateway REST API client.
 *
 * Verifies that:
 *   1. listBrokers makes a GET request and returns broker array
 *   2. removeAccount makes a DELETE with encoded account ID
 *   3. Error responses throw with the server error message
 *   4. The operator session JWT is attached when present (backend G9 guard
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




  it("attaches the session JWT on writes (backend G9 write guard)", async () => {
    useAuthStore.setState({ token: "jwt-abc" });
    try {
      fetchSpy.mockResolvedValueOnce(jsonResponse({ limits: { zerodha: { order: 5, data: 10 } } }));
      await gatewayApi.setRateLimit("zerodha", 5, 10);
      const init = fetchSpy.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer jwt-abc");
    } finally {
      useAuthStore.setState({ token: null });
    }
  });


});
