import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { nativeAutonomyV2Schemas } from "../nativeAutonomyV2";
import corpus from "./fixtures/native-options-v2.json";

const fixture = z.strictObject({
  provenance: z.literal("synthetic_contract_examples_not_production_qualification"),
  cases: z.array(z.strictObject({ id: z.string(), model: z.string(), valid: z.boolean(), value: z.unknown() })),
}).parse(corpus);
const schemas = new Map<string, z.ZodType>(Object.entries(nativeAutonomyV2Schemas));

describe("synthetic index-options transport, not authority", () => {
  for (const row of fixture.cases) {
    it(row.id, () => {
      const schema = schemas.get(row.model);
      expect(schema, row.model).toBeDefined();
      const result = schema?.safeParse(row.value);
      expect(result?.success).toBe(row.valid);
      if (result?.success) expect(result.data).toEqual(row.value);
    });
  }
  it("constructs all new validators cold without Function or eval", async () => {
    z.config({ jitless: false });
    vi.resetModules();
    const forbidden = vi.fn(() => { throw new Error("dynamic compilation forbidden"); });
    vi.stubGlobal("Function", forbidden);
    vi.stubGlobal("eval", forbidden);
    try {
      const generated = await import("../nativeAutonomyV2");
      const fresh = new Map<string, z.ZodType>(Object.entries(generated.nativeAutonomyV2Schemas));
      for (const row of fixture.cases) expect(fresh.get(row.model)?.safeParse(row.value).success).toBe(row.valid);
      expect(forbidden).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
