/**
 * Offline F&O contracts for Example and Practice.
 *
 * Lot sizes follow the screener fallback table (NIFTY 65, BANKNIFTY 30).
 * Freeze quantities follow NSE/FAOP/76693 (NIFTY 3510, BANKNIFTY 1440).
 * The order pad can then refuse both a quantity that is not a whole lot
 * and a lot multiple above the freeze, without a broker instrument master.
 */

export interface ExampleFoInstrument {
  symbol: string;
  name: string;
  exchange: "NFO";
  instrumenttype: "FUTIDX" | "OPTIDX";
  lotsize: number;
  /** NSE/FAOP/76693 freeze quantity for this underlying. */
  freezeQty: number;
  tick_size: number;
}

export const EXAMPLE_FO_INSTRUMENTS: readonly ExampleFoInstrument[] = [
  {
    symbol: "NIFTY-OCT2026-FUT",
    name: "NIFTY OCT 2026 FUT",
    exchange: "NFO",
    instrumenttype: "FUTIDX",
    lotsize: 65,
    freezeQty: 3510,
    tick_size: 0.05,
  },
  {
    symbol: "NIFTY 24500 CE",
    name: "NIFTY 24500 CE",
    exchange: "NFO",
    instrumenttype: "OPTIDX",
    lotsize: 65,
    freezeQty: 3510,
    tick_size: 0.05,
  },
  {
    symbol: "NIFTY 24500 PE",
    name: "NIFTY 24500 PE",
    exchange: "NFO",
    instrumenttype: "OPTIDX",
    lotsize: 65,
    freezeQty: 3510,
    tick_size: 0.05,
  },
  {
    symbol: "BANKNIFTY-OCT2026-FUT",
    name: "BANKNIFTY OCT 2026 FUT",
    exchange: "NFO",
    instrumenttype: "FUTIDX",
    lotsize: 30,
    freezeQty: 1440,
    tick_size: 0.05,
  },
  {
    symbol: "BANKNIFTY 52000 CE",
    name: "BANKNIFTY 52000 CE",
    exchange: "NFO",
    instrumenttype: "OPTIDX",
    lotsize: 30,
    freezeQty: 1440,
    tick_size: 0.05,
  },
  {
    symbol: "BANKNIFTY 52000 PE",
    name: "BANKNIFTY 52000 PE",
    exchange: "NFO",
    instrumenttype: "OPTIDX",
    lotsize: 30,
    freezeQty: 1440,
    tick_size: 0.05,
  },
];

/** Symbol payload with both freeze spellings the pad and admission read. */
export function exampleFoSymbolPayload(
  contract: ExampleFoInstrument,
): ExampleFoInstrument & { freeze_qty: number } {
  return { ...contract, freeze_qty: contract.freezeQty };
}

export function findExampleFoInstrument(
  symbol: string,
  exchange?: string,
): ExampleFoInstrument | undefined {
  const name = symbol.trim().toUpperCase();
  const venue = exchange?.trim().toUpperCase();
  if (!name) return undefined;
  return EXAMPLE_FO_INSTRUMENTS.find((row) => (
    row.symbol.toUpperCase() === name && (!venue || row.exchange === venue)
  ));
}

export function searchExampleFoInstruments(
  query: string,
  exchange?: string,
): Array<{ symbol: string; exchange: string }> {
  const needle = query.trim().toUpperCase();
  const venue = exchange?.trim().toUpperCase();
  if (!needle) return [];
  return EXAMPLE_FO_INSTRUMENTS
    .filter((row) => row.symbol.toUpperCase().includes(needle) && (!venue || row.exchange === venue))
    .map((row) => ({ symbol: row.symbol, exchange: row.exchange }));
}
