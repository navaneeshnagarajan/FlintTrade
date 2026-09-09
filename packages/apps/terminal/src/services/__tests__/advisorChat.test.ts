/**
 * Tests for the shared advisor chat client.
 *
 * Covers the fail-closed contract: HTTP 503, empty SSE, SSE error frames,
 * and an unreachable status probe must never resolve as a blank reply.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../advisorApi", () => ({
  getAdvisorBase: () => "",
}));

import {
  ADVISOR_UNAVAILABLE_MESSAGE,
  EMPTY_ADVISOR_REPLY_MESSAGE,
  LLM_NOT_CONFIGURED_MESSAGE,
  consumeAdvisorSse,
  probeAdvisorAvailability,
  readAdvisorHttpError,
  requestAdvisorReply,
} from "../advisorChat";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("advisorChat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the LLM-not-configured message from a 503 JSON body", async () => {
    const resp = jsonResponse(
      { status: "error", message: LLM_NOT_CONFIGURED_MESSAGE },
      503,
    );
    await expect(readAdvisorHttpError(resp)).resolves.toBe(LLM_NOT_CONFIGURED_MESSAGE);
  });

  it("treats a configured:false status probe as unconfigured", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { configured: false, provider: "", model: "" },
      }),
    );
    await expect(probeAdvisorAvailability()).resolves.toBe("unconfigured");
  });

  it("treats a network failure on the status probe as unreachable", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(probeAdvisorAvailability()).resolves.toBe("unreachable");
  });

  it("throws when the SSE stream ends with no tokens", async () => {
    const body = new Response('data: {"done":true}\n\n').body;
    expect(body).not.toBeNull();
    await expect(consumeAdvisorSse(body!)).rejects.toThrow(EMPTY_ADVISOR_REPLY_MESSAGE);
  });

  it("throws the SSE error frame instead of returning a blank string", async () => {
    const body = new Response('data: {"error":"Internal server error"}\n\n').body;
    expect(body).not.toBeNull();
    await expect(consumeAdvisorSse(body!)).rejects.toThrow("Internal server error");
  });

  it("assembles tokens on the happy path", async () => {
    const body = new Response(
      'data: {"token":"NIFTY"}\n\ndata: {"token":" is an index"}\n\ndata: {"done":true}\n\n',
    ).body;
    expect(body).not.toBeNull();
    await expect(consumeAdvisorSse(body!)).resolves.toBe("NIFTY is an index");
  });

  it("fails closed with the backend message when status says unconfigured", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { configured: false, provider: "", model: "" },
      }),
    );
    await expect(
      requestAdvisorReply({
        messages: [{ role: "user", content: "What is NIFTY?" }],
        context: "",
      }),
    ).rejects.toThrow(LLM_NOT_CONFIGURED_MESSAGE);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toMatch(/\/advisor\/status$/);
  });

  it("fails closed when the advisor backend is unreachable", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(
      requestAdvisorReply({
        messages: [{ role: "user", content: "What is NIFTY?" }],
        context: "",
      }),
    ).rejects.toThrow(ADVISOR_UNAVAILABLE_MESSAGE);
  });
});
