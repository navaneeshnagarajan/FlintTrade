/**
 * Connection-step form schema + helpers.
 *
 * Lives OUTSIDE the component file so ConnectionStep.tsx exports only React
 * components — mixing these consts into the component module broke Vite Fast
 * Refresh (HG4).
 */

import { z } from "zod";

export const connectionSchema = z.object({
  host: z.string().min(1, "Host is required").url("Must be a valid URL (include http://)"),
  port: z.string().min(1, "REST port is required"),
  apiKey: z.string().min(8, "API key must be at least 8 characters"),
  wsPort: z.string().min(1, "WebSocket port is required"),
});

/** Settings may preserve an already-configured key by leaving this field blank. */
export const editableConnectionSchema = connectionSchema.extend({
  apiKey: z.string().refine(
    (value) => value === "" || value.length >= 8,
    "API key must be at least 8 characters",
  ),
});

export type ConnectionFormValues = z.infer<typeof connectionSchema>;

export function deriveWsUrl(host: string, wsPort: string): string {
  try {
    const url = new URL(host);
    const proto = url.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${url.hostname}:${wsPort}`;
  } catch {
    return `ws://localhost:${wsPort}`;
  }
}
