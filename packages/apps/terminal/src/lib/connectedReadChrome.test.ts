import { describe, expect, it } from "vitest";

import {
  API_SMOKE_LABEL,
  CONNECTED_READ_LABEL,
  NEO_OPERATOR_COPY,
  isConnectedReadBroker,
  connectedAccountStatusLine,
  connectedReadChrome,
  connectedReadConnectable,
} from "./connectedReadChrome";

describe("connectedReadChrome", () => {
  it("labels Dhan and Neo Connected (read) only when connected", () => {
    expect(isConnectedReadBroker("dhan")).toBe(true);
    expect(isConnectedReadBroker("kotakneo")).toBe(true);
    expect(isConnectedReadBroker("upstox")).toBe(false);
    expect(connectedReadChrome({ broker: "dhan", status: "connected", read_smoke_ok: true })).toBe(CONNECTED_READ_LABEL);
    expect(connectedReadChrome({ broker: "kotakneo", status: "connected", read_smoke_ok: true })).toBe(CONNECTED_READ_LABEL);
    expect(connectedReadChrome({ broker: "dhan", status: "connected" })).toBeNull();
    expect(connectedReadChrome({ broker: "dhan", status: "disconnected", read_smoke_ok: true })).toBeNull();
    expect(connectedReadChrome({ broker: "upstox", status: "connected", read_smoke_ok: true })).toBeNull();
    expect(connectedReadConnectable("kotakneo", false)).toBe(true);
    expect(connectedReadConnectable("dhan", false)).toBe(true);
    expect(connectedReadConnectable("groww", false)).toBe(false);
    expect(connectedReadConnectable("upstox", true)).toBe(true);
  });

  it("never implies live order capability and never offers Neo Practice", () => {
    const neo = connectedAccountStatusLine({
      account_id: "N1",
      broker: "kotakneo",
      label: "Neo",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "native",
      read_only: true,
      read_smoke_ok: true,
    });
    expect(neo).toContain(CONNECTED_READ_LABEL);
    expect(neo).not.toContain(API_SMOKE_LABEL);
    expect(neo).toContain(NEO_OPERATOR_COPY);
    expect(neo.toLowerCase()).not.toContain("practice");
    expect(neo.toLowerCase()).not.toContain("placeable");
    expect(neo).not.toMatch(/\bconnected\b(?! \(read\))/i);
  });
});
