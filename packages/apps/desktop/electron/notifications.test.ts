import { describe, expect, it, vi } from "vitest";

import { createNativeNotificationRelay } from "./notifications";

describe("native notification relay", () => {
  it("accepts only parsed notification events and bounds title and body", () => {
    const show = vi.fn();
    const relay = createNativeNotificationRelay({ isSupported: () => true, show });

    expect(relay.publish({ type: "ready", port: 8000 })).toBe(false);
    expect(relay.publish({ type: "notification", title: ` ${"T".repeat(200)} `, body: ` ${"B".repeat(2_000)} ` })).toBe(true);
    expect(show).toHaveBeenCalledWith({ title: "T".repeat(128), body: "B".repeat(1_024) });
  });

  it("rejects empty titles and degrades safely when unsupported or delivery throws", () => {
    const unsupported = createNativeNotificationRelay({ isSupported: () => false, show: vi.fn() });
    expect(unsupported.publish({ type: "notification", title: "Fill", body: "Done" })).toBe(false);

    const onFailure = vi.fn();
    const throwing = createNativeNotificationRelay({
      isSupported: () => true,
      onFailure,
      show: vi.fn(() => { throw new Error("denied"); }),
    });
    expect(throwing.publish({ type: "notification", title: "  ", body: "ignored" })).toBe(false);
    expect(throwing.publish({ type: "notification", title: "Risk block", body: "Order blocked" })).toBe(false);
    expect(onFailure).toHaveBeenCalledOnce();
  });
});
