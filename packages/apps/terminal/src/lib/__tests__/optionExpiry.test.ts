import { describe, expect, it } from "vitest";

import {
  optionExpiryIdentity,
  parseExpiryList,
  pickListedExpiry,
} from "../optionExpiry";

describe("optionExpiry helpers", () => {
  it("builds a shared identity from scope, symbol and exchange", () => {
    expect(optionExpiryIdentity("explore:mock", "NIFTY", "NFO")).toBe(
      "explore:mock:NIFTY:NFO",
    );
  });

  it("parses array and { expiry } payloads the same way Option Chain does", () => {
    expect(parseExpiryList(["17-SEP-26", " 24-SEP-26 "])).toEqual([
      "17-SEP-26",
      "24-SEP-26",
    ]);
    expect(parseExpiryList({ expiry: [null, "", "   ", " 17-SEP-26 "] })).toEqual([
      "17-SEP-26",
    ]);
    expect(parseExpiryList({ expiry: [] })).toEqual([]);
    expect(parseExpiryList(undefined)).toEqual([]);
  });

  it("prefers a still-listed shared selection, otherwise the nearest listed", () => {
    const listed = ["17-SEP-26", "24-SEP-26", "01-OCT-26"];
    expect(pickListedExpiry(listed, "24-SEP-26")).toBe("24-SEP-26");
    expect(pickListedExpiry(listed, " 24-SEP-26 ")).toBe("24-SEP-26");
    expect(pickListedExpiry(listed, "gone")).toBe("17-SEP-26");
    expect(pickListedExpiry(listed, null)).toBe("17-SEP-26");
    expect(pickListedExpiry([], "17-SEP-26")).toBeNull();
  });
});
