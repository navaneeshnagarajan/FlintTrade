/**
 * Shared backoff for desk reads that tripped the backend rate limit.
 *
 * A hidden tab must not keep polling. HTTP 429 waits, then tries again.
 * Ordinary failures keep the previous short retry (QueryClient `retry: 2`).
 */

const RATE_LIMIT_BASE_MS = 8_000;
const RATE_LIMIT_CAP_MS = 60_000;

const inflight = new Map<string, Promise<unknown>>();

export function httpStatusFromError(error: unknown): number | null {
  if (!error || typeof error !== "object") return null;
  const record = error as { status?: unknown; message?: unknown };
  if (typeof record.status === "number") return record.status;
  if (typeof record.message === "string") {
    const match = /^HTTP (\d{3})\b/.exec(record.message);
    if (match) return Number(match[1]);
  }
  return null;
}

export function isHttp429(error: unknown): boolean {
  return httpStatusFromError(error) === 429;
}

/** Delay before another attempt after HTTP 429. `attempt` is 0 on the first failure. */
export function rateLimitRetryDelayMs(attempt: number): number {
  const step = Math.max(0, attempt);
  return Math.min(RATE_LIMIT_CAP_MS, RATE_LIMIT_BASE_MS * 2 ** step);
}

/**
 * QueryClient retry delay.
 *
 * Non-429 matches TanStack's default (`min(1000 * 2^failureCount, 30000)`),
 * which is what `retry: 2` used before this helper existed.
 */
export function deskQueryRetryDelay(failureCount: number, error: unknown): number {
  if (isHttp429(error)) return rateLimitRetryDelayMs(failureCount);
  return Math.min(1_000 * 2 ** failureCount, 30_000);
}

export function isDocumentHidden(): boolean {
  return typeof document !== "undefined" && document.hidden;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** Resolve when the tab is visible. Already-visible tabs resolve immediately. */
export function waitUntilVisible(): Promise<void> {
  if (!isDocumentHidden()) return Promise.resolve();
  return new Promise((resolve) => {
    const onChange = () => {
      if (!document.hidden) {
        document.removeEventListener("visibilitychange", onChange);
        resolve();
      }
    };
    document.addEventListener("visibilitychange", onChange);
  });
}

/** Wait out a backoff, and do not resume while the tab is hidden. */
export async function waitBeforeRetry(delayMs: number): Promise<void> {
  if (isDocumentHidden()) await waitUntilVisible();
  if (delayMs > 0) await sleep(delayMs);
  if (isDocumentHidden()) await waitUntilVisible();
}

/**
 * Run `fn` after `delayMs`, pausing the wait while the document is hidden.
 * Returns a cancel function for effect cleanup.
 */
export function scheduleWhenVisible(fn: () => void, delayMs: number): () => void {
  let timer = 0;
  let cancelled = false;

  const arm = () => {
    window.clearTimeout(timer);
    if (cancelled || isDocumentHidden()) return;
    timer = window.setTimeout(fn, delayMs);
  };

  const onVisibility = () => {
    if (cancelled) return;
    if (isDocumentHidden()) {
      window.clearTimeout(timer);
      return;
    }
    arm();
  };

  document.addEventListener("visibilitychange", onVisibility);
  arm();

  return () => {
    cancelled = true;
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}

/** Drop in-flight keys left behind by a test that never settles. */
export function clearCoalescedReadsForTests(): void {
  inflight.clear();
}

/** Collapse overlapping reads of the same key into one promise. */
export function coalesceInflight<T>(key: string, run: () => Promise<T>): Promise<T> {
  const existing = inflight.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const promise = run().finally(() => {
    if (inflight.get(key) === promise) inflight.delete(key);
  });
  inflight.set(key, promise);
  return promise;
}
