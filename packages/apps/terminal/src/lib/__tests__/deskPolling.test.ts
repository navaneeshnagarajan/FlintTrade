import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import {
  coalesceInflight,
  deskQueryRetryDelay,
  isHttp429,
  rateLimitRetryDelayMs,
  scheduleWhenVisible,
} from "../deskPolling";

describe("deskPolling", () => {
  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
  });

  it("treats an HTTP 429 error as rate limited and backs off", () => {
    expect(isHttp429(new Error("HTTP 429"))).toBe(true);
    expect(isHttp429(new Error("HTTP 500"))).toBe(false);
    expect(rateLimitRetryDelayMs(0)).toBe(8_000);
    expect(rateLimitRetryDelayMs(1)).toBe(16_000);
    expect(deskQueryRetryDelay(0, new Error("HTTP 429"))).toBe(8_000);
    expect(deskQueryRetryDelay(0, new Error("HTTP 503"))).toBe(1_000);
  });

  it("does not retry a query inside the rate-limit backoff", async () => {
    vi.useFakeTimers();
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: 2, retryDelay: deskQueryRetryDelay },
      },
    });
    let calls = 0;
    const pending = client.fetchQuery({
      queryKey: ["desk-rate-limit"],
      queryFn: () => {
        calls += 1;
        throw new Error("HTTP 429");
      },
    });
    pending.catch(() => undefined);

    await vi.advanceTimersByTimeAsync(1_000);
    expect(calls).toBe(1);

    await vi.advanceTimersByTimeAsync(7_000);
    expect(calls).toBe(2);
    client.clear();
  });

  it("shares one in-flight read across callers", async () => {
    let release!: (value: string) => void;
    const run = vi.fn(
      () => new Promise<string>((resolve) => {
        release = resolve;
      }),
    );
    const first = coalesceInflight("shared-read", run);
    const second = coalesceInflight("shared-read", run);
    expect(run).toHaveBeenCalledTimes(1);
    release("ok");
    await expect(Promise.all([first, second])).resolves.toEqual(["ok", "ok"]);
  });

  it("does not fire a hidden-tab timer until the tab is visible", () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    const fn = vi.fn();
    const cancel = scheduleWhenVisible(fn, 1_000);

    vi.advanceTimersByTime(5_000);
    expect(fn).not.toHaveBeenCalled();

    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(999);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    cancel();
  });
});
