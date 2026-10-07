import { describe, expect, it } from "vitest";

import {
  contractHasOpenExit,
  exitAlreadyPendingMessage,
  exitOrdersUnreadableMessage,
  orderRefusalMessage,
  orderStatusIsOpen,
  orderStatusIsCancelPending,
  exitRequestErrorMessage,
  orderRequestOutcomeIsUnknown,
} from "./positionReconcile";

describe("exit refusal copy", () => {
  it("maps this desk's unfilled exit and an unreadable broker book separately", () => {
    expect(exitAlreadyPendingMessage("INFY")).toBe(
      "Not placed. An exit for INFY is already pending. Wait for it to fill, or cancel it and try again.",
    );
    expect(exitOrdersUnreadableMessage("INFY")).toBe(
      "Not placed. Broker orders for INFY are unavailable. Reconcile them before another exit.",
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

describe("executable exit risk", () => {
  it.each([
    "CANCEL_PENDING",
    "CANCEL_REQUESTED",
    "CANCEL PENDING",
    "PENDING_CANCEL",
    "REJECT_PENDING",
    "COMPLETE_PENDING",
    "NOT_CANCELLED",
    "",
    "   ",
    "UNFAMILIAR_STATUS",
    " cancel_pending ",
  ])("keeps pending and unknown statuses executable: %j", (status) => {
    expect(orderStatusIsOpen(status)).toBe(true);
  });

  it.each([
    "COMPLETE", "COMPLETED", "FILLED", "CANCELLED", "CANCELED", "REJECTED", "TRADED", "EXPIRED",
  ])("closes only exact terminal statuses: %s", (status) => {
    expect(orderStatusIsOpen(status)).toBe(false);
    expect(orderStatusIsOpen(` ${status.toLowerCase()} `)).toBe(false);
  });

  it.each([
    { quantity: 10, action: "SELL" },
    { quantity: -10, action: "BUY" },
  ])("retains the exit-pending predicate for a $action cancellation", ({ quantity, action }) => {
    const contract = { symbol: "INFY", exchange: "NSE", product: "MIS" };
    expect(contractHasOpenExit(
      { ...contract, quantity },
      [{ ...contract, action, status: "CANCEL_PENDING" }],
    )).toBe(true);
  });
});

describe("truthful request warnings", () => {
  it.each(["INFY", " INFY ", ""])('labels unavailable evidence truthfully: %j', (contract) => {
    const label = contract.trim() || "this contract";
    expect(exitOrdersUnreadableMessage(contract)).toBe(
      `Not placed. Broker orders for ${label} are unavailable. Reconcile them before another exit.`,
    );
  });

  it.each(["CANCEL_PENDING", "cancel_requested", " CANCEL PENDING ", "PENDING_CANCEL"])(
    "identifies a known cancellation still pending: %j", (status) => {
      expect(orderStatusIsCancelPending(status)).toBe(true);
    },
  );

  it.each(["CANCELLED", "NOT_CANCELLED", "UNFAMILIAR_CANCEL_STATUS", ""])(
    "does not invent a cancellation state from a substring: %j", (status) => {
      expect(orderStatusIsCancelPending(status)).toBe(false);
    },
  );

  it("retains broker refusal details", () => {
    expect(exitRequestErrorMessage(Object.assign(new Error("DDPI authorisation required."), { status: 403 })))
      .toBe("DDPI authorisation required.");
  });

  it.each([new TypeError("Failed to fetch"), Object.assign(new Error("Gateway timeout"), { status: 504 })])(
    "does not relabel a lost response as a definite rejection", (error) => {
      expect(exitRequestErrorMessage(error)).toBe(
        `Exit status unknown. An order may still execute. ${error.message}`,
      );
    },
  );
});


describe("write outcome uncertainty", () => {
  it.each([
    { status: 403, unknown: false },
    { status: 422, unknown: false },
    { status: 408, unknown: true },
    { status: 500, unknown: true },
    { status: 504, unknown: true },
    { status: undefined, unknown: true },
  ])("keeps status $status distinct from a definite refusal", ({ status, unknown }) => {
    expect(orderRequestOutcomeIsUnknown(Object.assign(new Error("Broker detail"), { status })))
      .toBe(unknown);
  });
});
