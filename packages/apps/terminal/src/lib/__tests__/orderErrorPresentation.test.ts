import { describe, expect, it } from "vitest";
import { nativeOrderErrorPresentation } from "@/lib/orderErrorPresentation";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";
import { OrderApiError } from "@/services/api";
import type { PlaceOrderParams } from "@/types/api";

const STATIC_IP = "Dhan rejected the order. Send it from your registered static IP.";
const STATIC_IP_OR_SEGMENT = "Dhan rejected the order. Check static IP and segment activation.";
const params = { action: "BUY", symbol: "INFY", exchange: "NSE", product: "MIS", quantity: 1, orderType: "MARKET" } as PlaceOrderParams;

function present(broker: string, patch: Record<string, unknown>) {
  const body = {
    status: "error", message: "Order dispatch failed", dispatch_outcome: "unknown_after_dispatch", retry_safe: false,
    affected_item: { broker, account_id: "ACC-1", operation: "place", symbol: "INFY", exchange: "NSE", product: "MIS", action: "BUY" },
    ...patch,
  };
  return nativeOrderErrorPresentation(new OrderApiError("failed", 500, body), { broker, accountId: "ACC-1", params });
}

describe("Dhan rejection sentences", () => {
  it("shows the static-IP sentence with Dhan's message below it", () => {
    const shown = present("dhan", { broker_code: "DH-905", broker_message: "Invalid IP", broker_reason: STATIC_IP });
    expect(shown?.body).toBe(`${ORDER_STATUS_UNKNOWN}\n${STATIC_IP}\nInvalid IP`);
  });

  it("shows the static-IP or segment sentence for a bare DH-903", () => {
    const shown = present("dhan", { broker_code: "DH-903", broker_message: "Account not active", broker_reason: STATIC_IP_OR_SEGMENT });
    expect(shown?.body).toBe(`${ORDER_STATUS_UNKNOWN}\n${STATIC_IP_OR_SEGMENT}\nAccount not active`);
  });

  it("adds no static-IP sentence when none is sent", () => {
    const shown = present("dhan", { broker_code: "DH-905", broker_message: "Missing required fields" });
    expect(shown?.body).toBe(ORDER_STATUS_UNKNOWN);
  });

  it("places the sentence after a pre-dispatch refusal without repeating Dhan's message", () => {
    const shown = present("dhan", { dispatch_outcome: "refused_before_dispatch", broker_code: "DH-906", broker_message: "IP not whitelisted", broker_reason: STATIC_IP });
    expect(shown?.body).toMatch(new RegExp(`Broker code: DH-906\\.\\n${STATIC_IP.replace(/[.]/g, "\\.")}\\nIP not whitelisted$`));
    expect(shown?.body).not.toContain("Broker reason (observation)");
  });

  it("ignores free text in the sentence field", () => {
    const shown = present("dhan", { broker_message: "Invalid IP", broker_reason: "Order filled." });
    expect(shown?.body).toBe(ORDER_STATUS_UNKNOWN);
  });

  it("ignores a Dhan sentence on another broker", () => {
    const shown = present("kotakneo", { broker_message: "Invalid IP", broker_reason: STATIC_IP });
    expect(shown?.body).toBe(ORDER_STATUS_UNKNOWN);
  });
});
