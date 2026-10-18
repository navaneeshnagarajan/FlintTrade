import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { initialiseSchemaValidation } from "../schemaValidation";

const original = { ...z.config() };
afterEach(() => { z.config({ ...original, jitless: original.jitless, customError: original.customError }); });

describe("schema validation bootstrap", () => {
  it("selects supported interpreted validation without replacing error policy", () => {
    const customError = () => "existing validation error";
    z.config({ jitless: false, customError });
    initialiseSchemaValidation();
    initialiseSchemaValidation();
    expect(z.config().jitless).toBe(true);
    expect(z.config().customError).toBe(customError);
    expect(z.config().localeError).toBe(original.localeError);
  });

  it("preserves strict validation, refinements and absent versus null values", async () => {
    initialiseSchemaValidation();
    const schema = z.strictObject({
      revision: z.number().int().positive(),
      digest: z.string().regex(/^[0-9a-f]{64}$/),
      optional: z.string().nullable().optional(),
      scope: z.strictObject({ allowed: z.literal(false) }),
    });
    const valid = { revision: 1, digest: "a".repeat(64), scope: { allowed: false } };
    expect(schema.parse(valid)).toEqual(valid);
    expect(Object.hasOwn(schema.parse(valid), "optional")).toBe(false);
    expect(schema.parse({ ...valid, optional: null }).optional).toBeNull();
    for (const invalid of [
      { ...valid, revision: "1" }, { ...valid, revision: 1.5 },
      { ...valid, digest: "a".repeat(63) }, { ...valid, unknown: true },
      { ...valid, scope: { allowed: false, unknown: true } },
    ]) expect(schema.safeParse(invalid).success).toBe(false);
    const refined = schema.refine(async value => value.revision === 1);
    expect((await refined.safeParseAsync(valid)).success).toBe(true);
    expect((await refined.safeParseAsync({ ...valid, revision: 2 })).success).toBe(false);
  });
});
