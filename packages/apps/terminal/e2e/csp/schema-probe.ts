import { z } from "zod";

// Parser-only companion to the unmodified installed bundle. Deliberately no
// bootstrap/config call: the real application entry must set the shared policy.
export async function checkSchemas() {
  const item = z.strictObject({
    id: z.string().uuid(),
    revision: z.number().int().positive(),
    digest: z.string().regex(/^[0-9a-f]{64}$/),
    note: z.string().nullable().optional(),
    nested: z.strictObject({ allowed: z.literal(false) }),
  });
  const value = { id: "12345678-1234-4234-8234-123456789abc", revision: 1, digest: "a".repeat(64), nested: { allowed: false } };
  const valid = item.safeParse(value);
  const invalid = [
    { ...value, revision: "1" },
    { ...value, revision: 1.5 },
    { ...value, digest: "a".repeat(63) },
    { ...value, unknown: true },
    { ...value, nested: { allowed: false, unknown: true } },
    { ...value, nested: { allowed: true } },
  ].map(input => item.safeParse(input).success);
  const asyncItem = item.refine(async input => input.revision === 1);
  return {
    jitless: z.config().jitless === true,
    valid: valid.success && JSON.stringify(valid.data) === JSON.stringify(value),
    invalid,
    absentPreserved: valid.success && !Object.hasOwn(valid.data, "note"),
    nullPreserved: item.parse({ ...value, note: null }).note === null,
    asyncValid: (await asyncItem.safeParseAsync(value)).success,
    asyncInvalid: (await asyncItem.safeParseAsync({ ...value, revision: 2 })).success,
  };
}
