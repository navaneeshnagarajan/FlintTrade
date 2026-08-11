import { describe, expect, it } from "vitest";
import { personaDefaultRoute } from "../personaDefaultRoute";

describe("personaDefaultRoute", () => {
  it("sends traders to Trade", () => {
    expect(personaDefaultRoute("trader")).toBe("/trade");
  });
  it("sends beginners to Home", () => {
    expect(personaDefaultRoute("beginner")).toBe("/home");
  });
  it("sends investors to Home (Invest is secondary)", () => {
    expect(personaDefaultRoute("investor")).toBe("/home");
  });
  it("falls back to Home for null/unknown", () => {
    expect(personaDefaultRoute(null)).toBe("/home");
    expect(personaDefaultRoute(undefined)).toBe("/home");
    expect(personaDefaultRoute("legacy")).toBe("/home");
  });
});
