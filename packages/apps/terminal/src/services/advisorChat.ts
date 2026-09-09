/**
 * Shared AI advisor chat client.
 *
 * Both `/ai` (`AIAdvisorWidget`) and the floating tutor (`AITutorPill`) send
 * through this module so Explore/sample-data and Live share one request,
 * stream, and error path. An empty or failed completion must throw a
 * user-visible error — never resolve as a blank assistant message.
 */

import { safeParse, sseTokenSchema } from "@/lib/safeParse";
import { AdvisorResponseSchema, AdvisorStatusResponseSchema } from "@/lib/schemas/ftApi";
import { getAdvisorBase } from "./advisorApi";

/** Matches the backend 503 body when no LLM provider is configured. */
export const LLM_NOT_CONFIGURED_MESSAGE =
  "LLM not configured. Set provider in Settings → AI.";

export const ADVISOR_UNAVAILABLE_MESSAGE =
  "Could not reach the AI advisor. Start the FlintTrade backend, or configure an LLM in Settings → AI.";

export const EMPTY_ADVISOR_REPLY_MESSAGE =
  "The AI advisor returned no reply. Check Settings → AI, or try again.";

export const ADVISOR_TIMEOUT_MESSAGE =
  "The AI advisor timed out. Check Settings → AI, or try again.";

export const STREAMING_NOT_AVAILABLE = "STREAMING_NOT_AVAILABLE";

/** Fail-fast probe so Explore does not sit on a hanging Vite proxy. */
export const ADVISOR_STATUS_TIMEOUT_MS = 4_000;

/** First-token budget once a provider is known to be configured. */
export const ADVISOR_STREAM_TIMEOUT_MS = 45_000;

export type AdvisorAvailability = "configured" | "unconfigured" | "unknown" | "unreachable";

export type AdvisorChatContext = string | object;

export interface AdvisorChatRequest {
  messages: Array<{ role: string; content: string }>;
  context: AdvisorChatContext;
  sessionId?: string;
  signal?: AbortSignal;
  onToken?: (token: string, fullText: string) => void;
}

function combineAbortSignals(
  parent: AbortSignal | undefined,
  timeoutMs: number,
): {
  signal: AbortSignal;
  cleanup: () => void;
  clearTimer: () => void;
  timedOut: () => boolean;
} {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = (): void => {
    controller.abort();
  };
  parent?.addEventListener("abort", onAbort);
  if (parent?.aborted) controller.abort();
  const clearTimer = (): void => {
    clearTimeout(timer);
  };
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    clearTimer,
    cleanup: () => {
      clearTimer();
      parent?.removeEventListener("abort", onAbort);
    },
  };
}

/**
 * Read a user-visible error from a non-OK advisor HTTP response.
 *
 * Prefers the JSON ``message`` field (503 LLM-not-configured) over a bare
 * status code so Explore chat never shows a silent or opaque failure.
 */
export async function readAdvisorHttpError(resp: Response): Promise<string> {
  try {
    const raw: unknown = await resp.json();
    if (raw && typeof raw === "object" && "message" in raw) {
      const message = (raw as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) {
        return message.trim();
      }
    }
  } catch {
    // Body is not JSON — fall through to the status fallback.
  }
  if (resp.status === 503) return LLM_NOT_CONFIGURED_MESSAGE;
  return `Advisor API: HTTP ${resp.status}`;
}

/**
 * Cheap GET /advisor/status probe.
 *
 * ``unconfigured`` and ``unreachable`` are definitive fail-closed answers.
 * Anything else (malformed body, unexpected status) is ``unknown`` so the
 * caller can still attempt the real stream/fallback path.
 */
export async function probeAdvisorAvailability(
  signal?: AbortSignal,
): Promise<AdvisorAvailability> {
  const gated = combineAbortSignals(signal, ADVISOR_STATUS_TIMEOUT_MS);
  try {
    const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor/status`, {
      signal: gated.signal,
    });
    if (!resp.ok) return "unknown";
    let raw: unknown;
    try {
      raw = await resp.json();
    } catch {
      return "unknown";
    }
    const parsed = AdvisorStatusResponseSchema.safeParse(raw);
    if (!parsed.success || parsed.data.status !== "success" || !parsed.data.data) {
      return "unknown";
    }
    return parsed.data.data.configured ? "configured" : "unconfigured";
  } catch (err) {
    if (signal?.aborted && !gated.timedOut()) throw err;
    return "unreachable";
  } finally {
    gated.cleanup();
  }
}

/**
 * Consume an advisor SSE body. Throws on an ``error`` frame or a token-less
 * completion so callers cannot persist a blank assistant bubble.
 */
export async function consumeAdvisorSse(
  body: ReadableStream<Uint8Array>,
  onToken?: (token: string, fullText: string) => void,
): Promise<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let assistantText = "";
  let streamError: string | undefined;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      let streamDone = false;
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === "[DONE]") continue;
        const data = safeParse(raw, sseTokenSchema);
        if (!data) continue;
        if (data.error) {
          streamError = data.error;
          streamDone = true;
          break;
        }
        if (data.done) {
          streamDone = true;
          break;
        }
        if (data.token) {
          assistantText += data.token;
          onToken?.(data.token, assistantText);
        }
      }
      if (streamDone) break;
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* already cancelled */
    }
    reader.releaseLock();
  }
  if (streamError) {
    throw new Error(streamError);
  }
  if (!assistantText.trim()) {
    throw new Error(EMPTY_ADVISOR_REPLY_MESSAGE);
  }
  return assistantText;
}

export async function streamAdvisorChat(request: AdvisorChatRequest): Promise<string> {
  const gated = combineAbortSignals(request.signal, ADVISOR_STREAM_TIMEOUT_MS);
  try {
    const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: request.messages,
        context: request.context,
        ...(request.sessionId ? { session_id: request.sessionId } : {}),
      }),
      signal: gated.signal,
    });
    if (resp.status === 404) {
      throw new Error(STREAMING_NOT_AVAILABLE);
    }
    if (!resp.ok) {
      throw new Error(await readAdvisorHttpError(resp));
    }
    if (!resp.body) {
      throw new Error("No readable stream in response");
    }
    return await consumeAdvisorSse(resp.body, (token, fullText) => {
      gated.clearTimer();
      request.onToken?.(token, fullText);
    });
  } catch (err) {
    if (gated.timedOut()) {
      throw new Error(ADVISOR_TIMEOUT_MESSAGE);
    }
    throw err;
  } finally {
    gated.cleanup();
  }
}

export async function postAdvisorChat(request: AdvisorChatRequest): Promise<string> {
  const gated = combineAbortSignals(request.signal, ADVISOR_STREAM_TIMEOUT_MS);
  try {
    const resp = await fetch(`${getAdvisorBase()}/api/v1/advisor`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: request.messages,
        message: request.messages[request.messages.length - 1]?.content ?? "",
        context: request.context,
        ...(request.sessionId ? { session_id: request.sessionId } : {}),
      }),
      signal: gated.signal,
    });
    if (!resp.ok) {
      throw new Error(await readAdvisorHttpError(resp));
    }
    const raw: unknown = await resp.json();
    const result = AdvisorResponseSchema.safeParse(raw);
    if (!result.success) {
      throw new Error("Unexpected response format from advisor.");
    }
    if (result.data.status === "error") {
      throw new Error(result.data.message ?? "Unknown error from advisor.");
    }
    const reply = result.data.data?.response ?? "";
    if (!reply.trim()) {
      throw new Error(EMPTY_ADVISOR_REPLY_MESSAGE);
    }
    return reply;
  } catch (err) {
    if (gated.timedOut()) {
      throw new Error(ADVISOR_TIMEOUT_MESSAGE);
    }
    throw err;
  } finally {
    gated.cleanup();
  }
}

/**
 * Full chat path: probe availability, stream, then non-streaming fallback.
 *
 * Explore/sample-data uses this same path. When the LLM is missing or the
 * backend is unreachable the probe fails closed with a clear message instead
 * of hanging on ``/advisor/stream`` behind the Vite proxy.
 */
export async function requestAdvisorReply(request: AdvisorChatRequest): Promise<string> {
  const availability = await probeAdvisorAvailability(request.signal);
  if (availability === "unconfigured") {
    throw new Error(LLM_NOT_CONFIGURED_MESSAGE);
  }
  if (availability === "unreachable") {
    throw new Error(ADVISOR_UNAVAILABLE_MESSAGE);
  }
  try {
    return await streamAdvisorChat(request);
  } catch (err) {
    if (err instanceof Error && err.message === STREAMING_NOT_AVAILABLE) {
      return await postAdvisorChat(request);
    }
    throw err;
  }
}
