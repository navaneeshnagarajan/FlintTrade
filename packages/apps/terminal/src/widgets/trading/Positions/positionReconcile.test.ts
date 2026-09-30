import { describe, expect, it } from "vitest";

import {
  exitAlreadyPendingMessage,
  exitOrdersUnreadableMessage,
  orderRefusalMessage,
} from "./positionReconcile";

describe("exit refusal copy", () => {
  it("maps this desk's unfilled exit and an unreadable broker book separately", () => {
    expect(exitAlreadyPendingMessage("INFY")).toBe(
      "Not placed. An exit for INFY is already pending. Wait for it to fill, or cancel it and try again.",
    );
    expect(exitOrdersUnreadableMessage("INFY")).toBe(
      "Not placed. One exit at a time for INFY until your broker's orders load.",
    );
    expect(orderRefusalMessage("exit_pending", "INFY", "other")).toBe(exitAlreadyPendingMessage("INFY"));
    expect(orderRefusalMessage("exit_orders_unreadable", "INFY", "other")).toBe(
      exitOrdersUnreadableMessage("INFY"),
    );
    expect(orderRefusalMessage("gtt_unsupported", "INFY", "other")).toBe(
      "Not placed. GTT orders aren't supported right now.",
    );
    expect(orderRefusalMessage(undefined, "INFY", "other")).toBe("other");
  });
});
