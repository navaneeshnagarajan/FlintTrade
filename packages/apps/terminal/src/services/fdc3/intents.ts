/**
 * intents.ts — FDC3 intents over the workspace event bus.
 *
 * The FDC3 intent verbs the terminal raises, resolved in-process onto the
 * existing `flinttrade:addWidget` CustomEvent — deliberately, because
 * AppLayout already forwards that event across routes (raise an intent on
 * /lab and the app navigates to /trade before opening the panel). The
 * resolver table is the single place a verb maps to a widget id, so a
 * future external FDC3 bridge only has to swap the dispatch.
 *
 * Verbs follow the FDC3 standard intent names where one exists:
 *   ViewChart      → chart panel for the instrument
 *   ViewInstrument → chart panel (the terminal's richest instrument view)
 *   CreateOrder    → order pad prefilled with the instrument (and side)
 */

import type { Context } from "@finos/fdc3";
import { instrumentFromContext } from "./contexts";

export type FlintIntent = "ViewChart" | "ViewInstrument" | "CreateOrder";

export interface RaiseIntentOptions {
  /** BUY / SELL prefill for CreateOrder. */
  side?: "BUY" | "SELL";
  /** Panel title override. */
  title?: string;
}

interface ResolvedIntentTarget {
  widgetId: string;
  props: Record<string, unknown>;
  title?: string;
}

function resolveIntent(
  intent: FlintIntent,
  context: Context,
  options?: RaiseIntentOptions,
): ResolvedIntentTarget | null {
  const instrument = instrumentFromContext(context);
  if (!instrument) return null;
  const base = { symbol: instrument.symbol, exchange: instrument.exchange };
  switch (intent) {
    case "ViewChart":
    case "ViewInstrument":
      return { widgetId: "chart", props: base, ...(options?.title ? { title: options.title } : {}) };
    case "CreateOrder":
      return {
        widgetId: "orderpad",
        props: { ...base, ...(options?.side ? { action: options.side } : {}) },
        title: options?.title ?? `Order — ${instrument.symbol}`,
      };
  }
}

/**
 * Raise an intent. Returns true when the intent resolved and was
 * dispatched, false for a context the verb cannot act on — callers keep
 * their own affordances honest by checking it.
 */
export function raiseIntent(
  intent: FlintIntent,
  context: Context,
  options?: RaiseIntentOptions,
): boolean {
  const target = resolveIntent(intent, context, options);
  if (!target) return false;
  window.dispatchEvent(
    new CustomEvent("flinttrade:addWidget", {
      detail: {
        widgetId: target.widgetId,
        props: target.props,
        ...(target.title ? { title: target.title } : {}),
      },
    }),
  );
  return true;
}
