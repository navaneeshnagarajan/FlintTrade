/**
 * useLatestRequest — the extracted request-generation / in-flight-key guard.
 *
 * These cases pin the invariants that used to be pinned only indirectly, three
 * times over, through the OI Analytics and Option Chain widget suites.
 */

import { describe, it, expect } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useLatestRequest } from "../useLatestRequest";

describe("useLatestRequest", () => {
  it("commits a response that is still the newest for the active key", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const ticket = result.current.begin("NIFTY:NFO:2026-07-30");

    expect(ticket).not.toBeNull();
    expect(ticket!.isCurrent()).toBe(true);
    expect(ticket!.settle()).toBe(true);
  });

  it("skips a poll tick while a request of the same generation is in flight", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const first = result.current.begin("NIFTY:NFO:2026-07-30");
    const second = result.current.begin("NIFTY:NFO:2026-07-30");

    expect(first).not.toBeNull();
    expect(second).toBeNull();
  });

  it("lets the next tick through once the pending request settles", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const first = result.current.begin("NIFTY:NFO:2026-07-30");
    first!.settle();

    expect(result.current.begin("NIFTY:NFO:2026-07-30")).not.toBeNull();
  });

  it("rejects a response whose identity is no longer on screen", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useLatestRequest(key),
      { initialProps: { key: "NIFTY:NFO:2026-07-30" } },
    );

    const ticket = result.current.begin("NIFTY:NFO:2026-07-30");
    act(() => rerender({ key: "BANKNIFTY:NFO:2026-08-06" }));

    expect(ticket!.isCurrent()).toBe(false);
    // A superseded request must not report itself as the one that finished
    // loading, or it clears the spinner belonging to the new identity.
    expect(ticket!.settle()).toBe(false);
  });

  it("does not let an abandoned same-key request block a later round trip", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useLatestRequest(key),
      { initialProps: { key: "NIFTY:NFO:2026-07-30" } },
    );

    // Request one hangs and is never settled.
    const abandoned = result.current.begin("NIFTY:NFO:2026-07-30");
    expect(abandoned).not.toBeNull();

    // The operator switches away and back — the same key comes round again
    // while the abandoned request is still out there.
    act(() => rerender({ key: "BANKNIFTY:NFO:2026-08-06" }));
    act(() => rerender({ key: "NIFTY:NFO:2026-07-30" }));

    const retry = result.current.begin("NIFTY:NFO:2026-07-30");
    expect(retry).not.toBeNull();
    expect(retry!.isCurrent()).toBe(true);
    // The abandoned one lost: it can neither commit nor free the newer slot.
    expect(abandoned!.isCurrent()).toBe(false);
    expect(abandoned!.settle()).toBe(false);
    expect(retry!.isCurrent()).toBe(true);
  });

  it("keeps an older in-flight response from overwriting a newer one for the same key", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const older = result.current.begin("NIFTY:NFO:2026-07-30");
    result.current.invalidate();
    const newer = result.current.begin("NIFTY:NFO:2026-07-30");

    expect(older!.isCurrent()).toBe(false);
    expect(newer!.isCurrent()).toBe(true);
  });

  it("invalidates every in-flight request on teardown", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const ticket = result.current.begin("NIFTY:NFO:2026-07-30");
    act(() => result.current.invalidate());

    expect(ticket!.isCurrent()).toBe(false);
  });

  it("tracks separate keys independently", () => {
    const { result } = renderHook(() => useLatestRequest("NIFTY:NFO:2026-07-30"));

    const active = result.current.begin("NIFTY:NFO:2026-07-30");
    const other = result.current.begin("NIFTY:NFO:2026-08-06");

    // Both started, but only the one matching the rendered identity may commit.
    expect(other).not.toBeNull();
    expect(other!.isCurrent()).toBe(false);
    expect(active!.isCurrent()).toBe(false); // superseded by the newer generation
  });

  it("gives two guards over the same key independent generations", () => {
    // OI Analytics runs the chain loop and the 60 s max-pain loop against one
    // identity; a max-pain request must not consume the chain loop's slot.
    const { result } = renderHook(() => ({
      chain: useLatestRequest("NIFTY:NFO:2026-07-30"),
      maxPain: useLatestRequest("NIFTY:NFO:2026-07-30"),
    }));

    const chainTicket = result.current.chain.begin("NIFTY:NFO:2026-07-30");
    const maxPainTicket = result.current.maxPain.begin("NIFTY:NFO:2026-07-30");

    expect(chainTicket!.isCurrent()).toBe(true);
    expect(maxPainTicket!.isCurrent()).toBe(true);

    result.current.maxPain.invalidate();
    expect(maxPainTicket!.isCurrent()).toBe(false);
    expect(chainTicket!.isCurrent()).toBe(true);
  });

  it("keeps one stable guard identity across re-renders", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useLatestRequest(key),
      { initialProps: { key: "NIFTY:NFO:2026-07-30" } },
    );

    const first = result.current;
    act(() => rerender({ key: "NIFTY:NFO:2026-07-30" }));

    // A changing guard identity would restart every useCallback/useEffect that
    // depends on it, which is what the polling loops are keyed on.
    expect(result.current).toBe(first);
  });
});
