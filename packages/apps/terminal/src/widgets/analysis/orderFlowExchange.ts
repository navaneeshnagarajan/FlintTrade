import { MCX_COMMODITIES } from "@/lib/mcxLots";

const NSE_INDEX_SYMBOLS = new Set([
  "NIFTY",
  "BANKNIFTY",
  "FINNIFTY",
  "MIDCPNIFTY",
  "INDIAVIX",
]);
const BSE_INDEX_SYMBOLS = new Set(["SENSEX", "BANKEX"]);
const CDS_UNDERLYINGS = ["USDINR", "EURINR", "GBPINR", "JPYINR"];

function isKnownUnderlyingOrContract(symbol: string, underlyings: string[]): boolean {
  return underlyings.some((underlying) => {
    if (symbol === underlying) return true;
    return symbol.startsWith(underlying) && /^\d/.test(symbol.slice(underlying.length));
  });
}

function isDerivativeContractSymbol(symbol: string): boolean {
  return /\d.*(?:CE|PE|FUT)$/.test(symbol);
}

/** Resolves the capture exchange for an order-flow instrument. */
export function resolveOrderFlowExchange(symbol: string, explicitExchange?: string): string {
  const normalisedExchange = explicitExchange?.trim().toUpperCase();
  if (normalisedExchange) return normalisedExchange;

  const normalisedSymbol = symbol.trim().toUpperCase();

  if (isKnownUnderlyingOrContract(normalisedSymbol, MCX_COMMODITIES)) return "MCX";
  if (isKnownUnderlyingOrContract(normalisedSymbol, CDS_UNDERLYINGS)) return "CDS";
  if (isDerivativeContractSymbol(normalisedSymbol)) {
    return [...BSE_INDEX_SYMBOLS].some((underlying) => normalisedSymbol.startsWith(underlying))
      ? "BFO"
      : "NFO";
  }
  if (BSE_INDEX_SYMBOLS.has(normalisedSymbol)) return "BSE_INDEX";
  if (NSE_INDEX_SYMBOLS.has(normalisedSymbol)) return "NSE_INDEX";
  return "NSE";
}
