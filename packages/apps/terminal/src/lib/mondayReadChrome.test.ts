import { describe, expect, it } from "vitest";

import {
  API_SMOKE_LABEL,
  CONNECTED_READ_LABEL,
  NEO_OPERATOR_COPY,
  isMondayReadBroker,
  mondayAccountStatusLine,
  mondayReadChrome,
  mondayReadConnectable,
} from "./mondayReadChrome";

describe("mondayReadChrome", () => {
  it("labels Dhan and Neo Connected (read) only when connected", () => {
    expect(isMondayReadBroker("dhan")).toBe(true);
    expect(isMondayReadBroker("kotakneo")).toBe(true);
    expect(isMondayReadBroker("upstox")).toBe(false);
    expect(mondayReadChrome({ broker: "dhan", status: "connected" })).toBe(CONNECTED_READ_LABEL);
    expect(mondayReadChrome({ broker: "kotakneo", status: "connected" })).toBe(CONNECTED_READ_LABEL);
    expect(mondayReadChrome({ broker: "dhan", status: "disconnected" })).toBeNull();
    expect(mondayReadChrome({ broker: "upstox", status: "connected" })).toBeNull();
    expect(mondayReadConnectable("kotakneo", false)).toBe(true);
    expect(mondayReadConnectable("dhan", false)).toBe(true);
    expect(mondayReadConnectable("groww", false)).toBe(false);
    expect(mondayReadConnectable("upstox", true)).toBe(true);
  });

  it("never implies live order capability and never offers Neo Practice", () => {
    const neo = mondayAccountStatusLine({
      account_id: "N1",
      broker: "kotakneo",
      label: "Neo",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "native",
      read_only: true,
    });
    expect(neo).toContain(CONNECTED_READ_LABEL);
    expect(neo).toContain(API_SMOKE_LABEL);
    expect(neo).toContain(NEO_OPERATOR_COPY);
    expect(neo.toLowerCase()).not.toContain("practice");
    expect(neo.toLowerCase()).not.toContain("placeable");
    expect(neo).not.toMatch(/\bconnected\b(?! \(read\))/i);
  });
});
