/**
 * riskSchema — shared zod schema for risk limits.
 * Used by RiskSection (Settings) and RiskStep (setup wizard).
 */

import { z } from "zod";

export const riskSchema = z.object({
  maxPositionLots: z.number().int().min(0).max(1000),
  mtmStoploss: z.number().min(0),
  mtmTarget: z.number().min(0),
  maxOrdersPerMinute: z.number().int().min(1).max(100),
});

export type RiskFormValues = z.infer<typeof riskSchema>;

export const RISK_HINTS = {
  maxPositionLots:
    "Maximum total lots across all positions. SEBI recommends setting this to control exposure.",
  mtmStoploss:
    "Auto square-off all positions when day MTM loss exceeds this amount (₹). Set to 0 to disable.",
  mtmTarget:
    "Auto square-off all positions when day MTM profit reaches this amount (₹). Set to 0 to disable.",
  maxOrdersPerMinute:
    "Maximum orders per minute. SEBI rate limit is 10/sec = 600/min. Recommended: 50-100.",
} as const;
