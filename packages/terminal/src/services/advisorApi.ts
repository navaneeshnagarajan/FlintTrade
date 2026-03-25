/**
 * advisorApi.ts
 *
 * Shared helpers for all components that communicate with the FlintTrade AI
 * advisor backend (/ft-api/api/v1/advisor/*).
 *
 * Consumers: AITutorPill, AIAdvisorWidget
 *
 * In development the Vite proxy rewrites /ft-api → FlintTrade backend so we
 * use the prefix only in dev. In production the app is co-served with the
 * backend on the same origin so no prefix is needed.
 */

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

export function getAdvisorBase(): string {
  return import.meta.env.DEV ? "/ft-api" : "";
}

// ---------------------------------------------------------------------------
// Status check
// ---------------------------------------------------------------------------

/**
 * Returns true when the backend reports that an LLM provider is configured.
 * Silently returns false if the backend is unreachable.
 */
export async function fetchAdvisorStatus(): Promise<boolean> {
  try {
    const res = await fetch(`${getAdvisorBase()}/api/v1/advisor/status`);
    if (!res.ok) return false;
    const data = (await res.json()) as { status?: string; data?: { configured?: boolean } };
    return data?.data?.configured === true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Streaming endpoint
// ---------------------------------------------------------------------------

/**
 * Opens a streaming POST to /ft-api/api/v1/advisor/stream.
 * Returns the raw Response so callers can consume the ReadableStream themselves.
 *
 * Callers are responsible for handling 404 (streaming not available) and
 * other non-ok status codes.
 */
export async function streamAdvisorMessage(
  message: string,
  history: { role: string; content: string }[],
  context?: { route?: string },
  signal?: AbortSignal,
): Promise<Response> {
  return fetch(`${getAdvisorBase()}/api/v1/advisor/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      ...(context ? { context } : {}),
    }),
    signal,
  });
}

// ---------------------------------------------------------------------------
// Non-streaming fallback
// ---------------------------------------------------------------------------

/**
 * POST a single message (with history) to the non-streaming advisor endpoint.
 * Returns the advisor reply string.
 * Throws on HTTP errors.
 */
export async function postAdvisorMessage(
  message: string,
  history: { role: string; content: string }[],
  context?: { route?: string },
): Promise<{ response: string }> {
  const res = await fetch(`${getAdvisorBase()}/api/v1/advisor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      ...(context ? { context } : {}),
    }),
  });

  if (!res.ok) {
    throw new Error(`Advisor API: HTTP ${res.status}`);
  }

  return res.json() as Promise<{ response: string }>;
}
