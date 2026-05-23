/**
 * errorReporter — sends frontend errors to the FlintTrade backend.
 *
 * The backend logs them via structlog and forwards to Glitchtip.
 * This is intentionally fire-and-forget; a failure to report must never
 * cause secondary errors or interrupt application logic.
 */

export async function reportError(
  error: Error,
  context?: Record<string, unknown>,
): Promise<void> {
  try {
    await fetch("/ft-api/v1/errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: error.message,
        stack: error.stack,
        url: window.location.href,
        userAgent: navigator.userAgent,
        timestamp: new Date().toISOString(),
        ...context,
      }),
    });
  } catch {
    // Silently fail — error reporting must never create error loops.
  }
}
