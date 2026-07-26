/**
 * chartSyncBus.test.ts
 *
 * The bus is a module-level singleton, so each test uses its own group name
 * instead of resetting shared state.
 */

import { describe, it, expect, vi } from "vitest";
import { publishChartSync, subscribeChartSync } from "@/lib/chartSyncBus";
import type { ChartSyncRange } from "@/lib/chartSyncBus";

const RANGE: ChartSyncRange = { from: 10, to: 120 };

describe("chartSyncBus", () => {
  it("fans a publication out to every other member of the group", () => {
    const a = vi.fn();
    const b = vi.fn();
    const c = vi.fn();
    subscribeChartSync("fan-out", "a", a);
    subscribeChartSync("fan-out", "b", b);
    subscribeChartSync("fan-out", "c", c);

    publishChartSync("fan-out", "a", RANGE);

    expect(b).toHaveBeenCalledExactlyOnceWith(RANGE);
    expect(c).toHaveBeenCalledExactlyOnceWith(RANGE);
  });

  it("never delivers a publication back to its publisher", () => {
    const publisher = vi.fn();
    const peer = vi.fn();
    subscribeChartSync("self-exclusion", "publisher", publisher);
    subscribeChartSync("self-exclusion", "peer", peer);

    publishChartSync("self-exclusion", "publisher", RANGE);

    expect(publisher).not.toHaveBeenCalled();
    expect(peer).toHaveBeenCalledExactlyOnceWith(RANGE);
  });

  it("keeps groups isolated from each other", () => {
    const insider = vi.fn();
    const outsider = vi.fn();
    subscribeChartSync("group-one", "insider", insider);
    subscribeChartSync("group-two", "outsider", outsider);

    publishChartSync("group-one", "someone-else", RANGE);

    expect(insider).toHaveBeenCalledExactlyOnceWith(RANGE);
    expect(outsider).not.toHaveBeenCalled();
  });

  it("publishing to an empty or unknown group is a no-op", () => {
    expect(() => publishChartSync("nobody-home", "a", RANGE)).not.toThrow();
  });

  it("stops delivery after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeChartSync("unsub", "member", listener);

    publishChartSync("unsub", "peer", RANGE);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    publishChartSync("unsub", "peer", RANGE);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("a stale unsubscribe does not tear down a newer same-id subscription", () => {
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribeFirst = subscribeChartSync("re-subscribe", "member", first);
    subscribeChartSync("re-subscribe", "member", second);

    // The stale handle must be a no-op — the id now belongs to `second`.
    unsubscribeFirst();
    publishChartSync("re-subscribe", "peer", RANGE);

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledExactlyOnceWith(RANGE);
  });

  it("the documented apply-guard prevents a publish feedback loop", () => {
    // Two members using the caller-side guard contract from the module docs:
    // while applying a received range, range-change events on their own chart
    // must not be re-published. Simulate each chart echoing every applied
    // range as a synchronous range-change event (as lightweight-charts does).
    const makeMember = (id: string) => {
      const applied: ChartSyncRange[] = [];
      let isApplying = false;
      const onOwnRangeChange = (range: ChartSyncRange) => {
        if (isApplying) return; // the guard under test
        publishChartSync("loop-guard", id, range);
      };
      subscribeChartSync("loop-guard", id, (range) => {
        isApplying = true;
        try {
          applied.push(range);
          onOwnRangeChange(range); // the chart echoes the applied range
        } finally {
          isApplying = false;
        }
      });
      return { applied, onOwnRangeChange };
    };

    const a = makeMember("a");
    const b = makeMember("b");
    const c = makeMember("c");

    // A user-driven range change on chart A…
    a.onOwnRangeChange(RANGE);

    // …reaches B and C exactly once each and never boomerangs back to A.
    expect(a.applied).toEqual([]);
    expect(b.applied).toEqual([RANGE]);
    expect(c.applied).toEqual([RANGE]);
  });
});
