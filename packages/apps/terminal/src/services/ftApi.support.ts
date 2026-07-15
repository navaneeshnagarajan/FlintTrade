import { z } from "zod";

import { getV1, isDemoAuthSession } from "./ftApi.helpers";

const supportErrorGroupSchema = z.object({
  route: z.string(),
  method: z.string(),
  status_code: z.number().int().nullable(),
  error_class: z.string(),
  occurrences: z.number().int().nonnegative(),
  first_seen: z.string(),
  last_seen: z.string(),
});

const supportDiagnosticsSchema = z.object({
  schema_version: z.literal(1),
  generated_at: z.string().min(1),
  app: z.object({
    name: z.literal("FlintTrade"),
    version: z.string().min(1),
  }),
  runtime: z.object({
    os: z.string(),
    os_release: z.string(),
    architecture: z.string(),
    python: z.string(),
  }),
  errors: z.object({
    available: z.boolean(),
    total: z.number().int().nonnegative(),
    sampled: z.number().int().nonnegative(),
    groups: z.array(supportErrorGroupSchema),
  }),
});

export type SupportErrorGroup = z.infer<typeof supportErrorGroupSchema>;
export type SupportDiagnostics = z.infer<typeof supportDiagnosticsSchema>;

export async function getSupportDiagnostics(): Promise<SupportDiagnostics> {
  if (isDemoAuthSession()) {
    throw new Error("Diagnostics are unavailable in Explore demo. Sign in to export local diagnostics.");
  }
  const value = await getV1<unknown>("support/diagnostics");
  const parsed = supportDiagnosticsSchema.safeParse(value);
  if (!parsed.success) throw new Error("Invalid support diagnostics response");
  return parsed.data;
}
