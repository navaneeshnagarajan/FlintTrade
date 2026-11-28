import { describe, expect, it } from "vitest";
import type { BrokerAccount } from "@/types/broker";
import { BrokerOrdersApiError } from "@/lib/brokerOrdersApi";
import { CANCELLATION_REQUESTED, ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";
import {
  brokerOrdersErrorMessage,
  brokerOrderTargetOptions,
  brokerOrderTargetExists,
  DEFAULT_BROKER_TARGET,
  isBrokerOrderTargetableAccount,
} from "./OrdersManagerShared";

const account = (overrides: Partial<BrokerAccount> = {}): BrokerAccount => ({
  account_id: "A1",
  broker: "dhan",
  label: "Dhan",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: false,
  source: "native",
  ...overrides,
});

describe("broker order target selection", () => {
  it("only treats connected accounts as selectable live order targets", () => {
    expect(isBrokerOrderTargetableAccount(account({ status: "connected" }))).toBe(true);
    expect(isBrokerOrderTargetableAccount(account({ status: "connected", read_only: true }))).toBe(false);
    expect(isBrokerOrderTargetableAccount(account({ status: "token_expired" }))).toBe(false);
    expect(isBrokerOrderTargetableAccount(account({ status: "disconnected" }))).toBe(false);
  });

  it("rejects placeholder and stale native targets", () => {
    expect(brokerOrderTargetExists(DEFAULT_BROKER_TARGET, [])).toBe(false);
    expect(
      brokerOrderTargetExists(
        { broker: "dhan", account_id: "A1" },
        [account({ status: "connected" })],
      ),
    ).toBe(true);
    expect(
      brokerOrderTargetExists(
        { broker: "dhan", account_id: "A1" },
        [account({ status: "token_expired" })],
      ),
    ).toBe(false);
  });

  it("can restrict a management surface to supported native brokers", () => {
    const options = brokerOrderTargetOptions(
      [
        account({ account_id: "D1", broker: "dhan", source: "native" }),
        account({ account_id: "U1", broker: "upstox", source: "native" }),
        account({ account_id: "G1", broker: "groww", source: "native" }),
        account({ account_id: "D2", broker: "dhan", source: "gateway" }),
      ],
      {
        nativeOnly: true,
        supportedBrokers: ["dhan", "upstox"],
      },
    );

    expect(options.map((option) => option.target)).toStrictEqual([
      { broker: "dhan", account_id: "D1" },
      { broker: "upstox", account_id: "U1" },
    ]);
  });
});

describe("broker order write errors", () => {
  it("says the order status is unknown when a write response was lost", () => {
    const dropped = new BrokerOrdersApiError("Cannot reach the FlintTrade backend — check that it is running.", undefined, {
      status: "error",
      order_outcome: "unknown",
      retry_safe: false,
    });
    expect(brokerOrdersErrorMessage(dropped, { write: "submit" })).toBe(ORDER_STATUS_UNKNOWN);
  });

  it("says the order status is unknown for a 5xx write with no readable body", () => {
    const serverError = new BrokerOrdersApiError("Broker orders API orders/super/SO-1: HTTP 502", 502, {
      status: "error",
      order_outcome: "unknown",
      retry_safe: false,
    });
    expect(brokerOrdersErrorMessage(serverError, { write: "submit" })).toBe(ORDER_STATUS_UNKNOWN);
  });

  it("calls a lost cancel a cancellation request, never cancelled", () => {
    const dropped = new BrokerOrdersApiError("Cannot reach the FlintTrade backend — check that it is running.", undefined, {
      status: "error",
      order_outcome: "unknown",
      retry_safe: false,
    });
    expect(brokerOrdersErrorMessage(dropped, { write: "cancel" })).toBe(CANCELLATION_REQUESTED);
  });

  it("keeps a definite refusal readable", () => {
    const refused = new BrokerOrdersApiError("Request refused", 403, { status: "error", message: "Request refused" });
    expect(brokerOrdersErrorMessage(refused, { write: "submit" })).toBe("Request refused");
  });

  it("keeps the unsupported-broker copy for writes", () => {
    const unsupported = new BrokerOrdersApiError("not supported", 501, { status: "error", message: "not supported" });
    expect(brokerOrdersErrorMessage(unsupported, { write: "submit" })).toBe("Not available for this broker.");
  });

  it("does not describe a failed read as an unknown order", () => {
    const dropped = new BrokerOrdersApiError("Cannot reach the FlintTrade backend — check that it is running.", undefined, {
      status: "error",
      order_outcome: "unknown",
    });
    expect(brokerOrdersErrorMessage(dropped)).toBe("Cannot reach the FlintTrade backend — check that it is running.");
  });
});
