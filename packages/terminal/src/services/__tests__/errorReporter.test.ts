/**
 * Tests for errorReporter — fire-and-forget error reporting.
 *
 * Verifies that:
 *   1. reportError sends a POST with error details
 *   2. reportError silently swallows fetch failures
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import { reportError } from "../errorReporter";

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

describe("reportError", () => {
  it("sends a POST to /ft-api/v1/errors with error details", async () => {
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 200 }));

    const error = new Error("Something broke");
    error.stack = "Error: Something broke\n    at test.ts:1:1";

    await reportError(error, { widget: "chart" });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, options] = fetchSpy.mock.calls[0];
    expect(url).toBe("/ft-api/v1/errors");
    expect(options).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const body = JSON.parse(options.body as string);
    expect(body.message).toBe("Something broke");
    expect(body.stack).toContain("Something broke");
    expect(body.widget).toBe("chart");
    expect(body.timestamp).toBeDefined();
  });

  it("silently swallows fetch failures without throwing", async () => {
    fetchSpy.mockRejectedValueOnce(new Error("Network down"));

    // Should NOT throw
    await expect(
      reportError(new Error("test error")),
    ).resolves.toBeUndefined();
  });
});
