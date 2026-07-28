/**
 * contexts.ts — FDC3 context shapes for FlintTrade.
 *
 * The terminal speaks the FINOS FDC3 2.2 `fdc3.instrument` context on its
 * widget-interop channels. The standard identifies instruments by
 * `id.ticker` plus an optional `market` block; Indian venues do not map
 * cleanly onto MIC alone (NSE_INDEX, MCX segments…), so the FlintTrade
 * `exchange` string rides along as a documented extension field and is the
 * authoritative venue for anything talking to the backend. The MIC is
 * populated best-effort so a future cross-app FDC3 bridge stays honest.
 */

import type { Context } from "@finos/fdc3";
import type { WsInstrument } from "@/types/api";

export const INSTRUMENT_CONTEXT_TYPE = "fdc3.instrument" as const;

/** FDC3 2.2 instrument context carrying FlintTrade's venue extension. */
export interface FlintInstrumentContext extends Context {
  type: typeof INSTRUMENT_CONTEXT_TYPE;
  name?: string;
  id: {
    ticker: string;
  };
  market?: {
    MIC?: string;
    COUNTRY_ISOALPHA2?: string;
  };
  /** FlintTrade extension: the exchange string the backend understands. */
  exchange: string;
}

/** Best-effort exchange → ISO 10383 MIC mapping for the standard field. */
const EXCHANGE_MIC: Readonly<Record<string, string>> = {
  NSE: "XNSE",
  NSE_INDEX: "XNSE",
  NFO: "XNSE",
  BSE: "XBOM",
  BSE_INDEX: "XBOM",
  BFO: "XBOM",
  MCX: "XIMC",
  CDS: "XNSE",
};

/** Build an fdc3.instrument context from a FlintTrade instrument. */
export function instrumentContext(instrument: WsInstrument): FlintInstrumentContext {
  const mic = EXCHANGE_MIC[instrument.exchange];
  return {
    type: INSTRUMENT_CONTEXT_TYPE,
    name: instrument.symbol,
    id: { ticker: instrument.symbol },
    ...(mic ? { market: { MIC: mic, COUNTRY_ISOALPHA2: "IN" } } : {}),
    exchange: instrument.exchange,
  };
}

/**
 * Recover the FlintTrade instrument from a context, or null when the
 * context is not an instrument (or carries no usable identifier).
 * Contexts without the `exchange` extension (from a future external FDC3
 * source) fall back to NSE — the venue an Indian ticker most plausibly
 * means — rather than being dropped.
 */
export function instrumentFromContext(context: Context | null): WsInstrument | null {
  if (!context || context.type !== INSTRUMENT_CONTEXT_TYPE) return null;
  const id = (context as FlintInstrumentContext).id;
  const ticker = typeof id?.ticker === "string" ? id.ticker.trim() : "";
  if (!ticker) return null;
  const exchange = (context as FlintInstrumentContext).exchange;
  return {
    symbol: ticker,
    exchange: typeof exchange === "string" && exchange ? exchange : "NSE",
  };
}
