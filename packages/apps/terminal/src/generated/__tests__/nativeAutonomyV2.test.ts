import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { nativeAutonomyV2Schemas, PositiveMoneyV2Schema } from "../nativeAutonomyV2";
import corpus from "./fixtures/native-autonomy-v2.json";

const fixture = z.strictObject({
  provenance: z.literal("synthetic_contract_examples_not_production_qualification"),
  cases: z.array(z.strictObject({ id: z.string(), model: z.string(), valid: z.boolean(), value: z.unknown() })),
}).parse(corpus);
const schemas = new Map<string, z.ZodType>(Object.entries(nativeAutonomyV2Schemas));

describe("synthetic native v2 transport (not qualification)", () => {
  for (const row of fixture.cases) {
    it(row.id, () => {
      const schema = schemas.get(row.model);
      expect(schema, row.model).toBeDefined();
      const parsed = schema?.safeParse(row.value);
      expect(parsed?.success, row.id).toBe(row.valid);
      if (parsed?.success) expect(parsed.data).toEqual(row.value);
    });
  }
  for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    it(`refuses non-JSON ${String(value)}`, () => {
      expect(PositiveMoneyV2Schema.safeParse({ amount: value, currency: "INR" }).success).toBe(false);
    });
  }
  it("constructs and parses without probing Function", async () => {
    z.config({ jitless: false });
    vi.resetModules();
    const forbidden = vi.fn(() => { throw new Error("dynamic compilation forbidden"); });
    vi.stubGlobal("Function", forbidden);
    try {
      const generated = await import("../nativeAutonomyV2");
      expect(generated.PositiveMoneyV2Schema.parse({ amount: "1", currency: "INR" })).toEqual({ amount: "1", currency: "INR" });
      expect(forbidden).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("retains the maintained no-eval bootstrap", () => {
    expect(z.config().jitless).toBe(true);
  });
});
