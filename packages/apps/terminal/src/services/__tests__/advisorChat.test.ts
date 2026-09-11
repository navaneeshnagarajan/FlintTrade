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
  ADVISOR_STREAM_TIMEOUT_MS,
  ADVISOR_TIMEOUT_MESSAGE,
  ADVISOR_UNAVAILABLE_MESSAGE,
  EMPTY_ADVISOR_REPLY_MESSAGE,
  LLM_NOT_CONFIGURED_MESSAGE,
  advisorAvailabilityToChrome,
  advisorLlmChromeLabel,
  alignAdvisorChromeWithSettingsHydration,
  consumeAdvisorSse,
  isAdvisorChatReady,
  resolveAdvisorLlmChrome,
  probeAdvisorAvailability,
  readAdvisorHttpError,
  requestAdvisorReply,
  streamAdvisorChat,
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
    vi.useRealTimers();
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

  it("maps advisor availability to honest Chat chrome — never Connected unless configured", () => {
    expect(advisorAvailabilityToChrome(undefined)).toBe("loading");
    expect(advisorAvailabilityToChrome("unconfigured")).toBe("unconfigured");
    expect(advisorAvailabilityToChrome("configured")).toBe("ready");
    expect(advisorAvailabilityToChrome("unreachable")).toBe("disconnected");
    expect(advisorAvailabilityToChrome("unknown")).toBe("error");

    expect(advisorLlmChromeLabel("unconfigured")).toBe("Not configured");
    expect(advisorLlmChromeLabel("ready")).toBe("Connected");
    expect(advisorLlmChromeLabel("disconnected")).toBe("Disconnected");
    expect(advisorLlmChromeLabel("error")).toBe("Error");
    expect(isAdvisorChatReady("unconfigured")).toBe(false);
    expect(isAdvisorChatReady("disconnected")).toBe(false);
    expect(isAdvisorChatReady("error")).toBe(false);
    expect(isAdvisorChatReady("loading")).toBe(false);
    expect(isAdvisorChatReady("ready")).toBe(true);
  });

  it("does not keep Connected while a remount refetch of cached configured is in flight", () => {
    expect(resolveAdvisorLlmChrome({
      availability: "configured",
      isPending: false,
      isFetching: true,
      fetchStatus: "fetching",
    })).toBe("loading");
    expect(isAdvisorChatReady(resolveAdvisorLlmChrome({
      availability: "configured",
      isPending: false,
      isFetching: true,
      fetchStatus: "fetching",
    }))).toBe(false);
  });

  it("aligns Chat chrome with Settings #llm empty — never Connected from env-default advisor/status", () => {
    expect(alignAdvisorChromeWithSettingsHydration("ready", "empty")).toBe("unconfigured");
    expect(alignAdvisorChromeWithSettingsHydration("loading", "empty")).toBe("unconfigured");
    expect(alignAdvisorChromeWithSettingsHydration("disconnected", "empty")).toBe("unconfigured");
    expect(alignAdvisorChromeWithSettingsHydration("error", "empty")).toBe("unconfigured");
    expect(alignAdvisorChromeWithSettingsHydration("ready", "loading")).toBe("loading");
    expect(alignAdvisorChromeWithSettingsHydration("disconnected", "loading")).toBe("disconnected");
    expect(alignAdvisorChromeWithSettingsHydration("ready", "error")).toBe("error");
    expect(alignAdvisorChromeWithSettingsHydration("disconnected", "error")).toBe("disconnected");
    expect(alignAdvisorChromeWithSettingsHydration("ready", "ready")).toBe("ready");
    expect(alignAdvisorChromeWithSettingsHydration("unconfigured", "ready")).toBe("unconfigured");
    expect(isAdvisorChatReady(alignAdvisorChromeWithSettingsHydration("ready", "empty"))).toBe(false);
  });

  it("maps an offline-paused probe to Disconnected instead of a stuck Checking or Connected", () => {
    expect(resolveAdvisorLlmChrome({
      availability: undefined,
      isPending: true,
      isFetching: false,
      fetchStatus: "paused",
    })).toBe("disconnected");
    expect(resolveAdvisorLlmChrome({
      availability: "configured",
      isPending: false,
      isFetching: false,
      fetchStatus: "paused",
    })).toBe("disconnected");
    expect(resolveAdvisorLlmChrome({
      availability: "unconfigured",
      isPending: false,
      isFetching: false,
      fetchStatus: "paused",
    })).toBe("unconfigured");
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

  it("does not abort a healthy stream after the first token", async () => {
    vi.useFakeTimers();
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
    let sawFirstToken = false;
    let resolveFirstToken: (() => void) | undefined;
    const firstToken = new Promise<void>((resolve) => {
      resolveFirstToken = resolve;
    });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });

    vi.mocked(fetch).mockImplementationOnce((_url, init) => {
      init?.signal?.addEventListener("abort", () => {
        try {
          streamController?.error(new DOMException("The operation was aborted.", "AbortError"));
        } catch {
          /* already closed */
        }
      });
      return Promise.resolve(
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    const replyPromise = streamAdvisorChat({
      messages: [{ role: "user", content: "What is NIFTY?" }],
      context: "",
      onToken: () => {
        if (!sawFirstToken) {
          sawFirstToken = true;
          resolveFirstToken?.();
        }
      },
    });

    await Promise.resolve();
    expect(streamController).toBeDefined();
    streamController!.enqueue(encoder.encode('data: {"token":"Hello"}\n\n'));
    await firstToken;

    await vi.advanceTimersByTimeAsync(ADVISOR_STREAM_TIMEOUT_MS + 1_000);

    streamController!.enqueue(encoder.encode('data: {"token":" world"}\n\n'));
    streamController!.enqueue(encoder.encode('data: {"done":true}\n\n'));
    streamController!.close();

    await expect(replyPromise).resolves.toBe("Hello world");
  });

  it("still times out when the first streamed token never arrives", async () => {
    vi.useFakeTimers();
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });

    vi.mocked(fetch).mockImplementationOnce((_url, init) => {
      init?.signal?.addEventListener("abort", () => {
        try {
          streamController?.error(new DOMException("The operation was aborted.", "AbortError"));
        } catch {
          /* already closed */
        }
      });
      return Promise.resolve(
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    const replyPromise = streamAdvisorChat({
      messages: [{ role: "user", content: "What is NIFTY?" }],
      context: "",
    });
    await Promise.resolve();
    const expectation = expect(replyPromise).rejects.toThrow(ADVISOR_TIMEOUT_MESSAGE);
    await vi.advanceTimersByTimeAsync(ADVISOR_STREAM_TIMEOUT_MS + 1);
    await expectation;
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
