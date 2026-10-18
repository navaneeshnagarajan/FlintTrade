import { describe, expect, it } from "vitest";
import { personaDefaultRoute } from "../personaDefaultRoute";

describe("personaDefaultRoute", () => {
  it("sends traders to Trade", () => {
    expect(personaDefaultRoute("trader")).toBe("/trade");
  });
  it("sends beginners to the unified Terminal alias", () => {
    expect(personaDefaultRoute("beginner")).toBe("/trade");
  });
  it("sends investors to the unified Terminal alias (Invest is secondary)", () => {
    expect(personaDefaultRoute("investor")).toBe("/trade");
  });
  it("falls back to the unified Terminal alias for null/unknown", () => {
    expect(personaDefaultRoute(null)).toBe("/trade");
    expect(personaDefaultRoute(undefined)).toBe("/trade");
    expect(personaDefaultRoute("legacy")).toBe("/trade");
  });
});
