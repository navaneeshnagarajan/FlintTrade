import { EXCHANGES, type ExchangeValue } from "@/lib/tradingConstants";

// OpenAlgo symbols preserve punctuation such as M&M; keep the allowlist tight
// but include the characters that real NSE/BSE symbols already use.
const SYMBOL_PATTERN = /^[A-Z0-9_&.-]{1,32}$/;
const KNOWN_EXCHANGES = new Set<string>(EXCHANGES.map(({ value }) => value));

export interface AISymbolContext {
  symbol: string;
  exchange: ExchangeValue;
  source: "palette";
}

/**
 * Validate and normalise untrusted symbol context from navigation events or URLs.
 * All three fields are required; no value is inferred.
 */
export function normaliseAISymbolContext(value: unknown): AISymbolContext | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate["symbol"] !== "string" ||
    typeof candidate["exchange"] !== "string" ||
    candidate["source"] !== "palette"
  ) {
    return null;
  }

  const symbol = candidate["symbol"].trim().toUpperCase();
  const exchange = candidate["exchange"].trim().toUpperCase();
  if (!SYMBOL_PATTERN.test(symbol) || !KNOWN_EXCHANGES.has(exchange)) return null;

  return {
    symbol,
    exchange: exchange as ExchangeValue,
    source: "palette",
  };
}

/** Parse an unambiguous context triplet from the current /ai URL. */
export function parseAISymbolContext(searchParams: URLSearchParams): AISymbolContext | null {
  const symbols = searchParams.getAll("symbol");
  const exchanges = searchParams.getAll("exchange");
  const sources = searchParams.getAll("source");
  if (symbols.length !== 1 || exchanges.length !== 1 || sources.length !== 1) return null;

  return normaliseAISymbolContext({
    symbol: symbols[0],
    exchange: exchanges[0],
    source: sources[0],
  });
}

/**
 * Add validated palette context to /ai only, preserving existing query/hash data.
 * Invalid context and every other route are returned byte-for-byte unchanged.
 */
export function appendAISymbolContext(path: string, value: unknown): string {
  const hashIndex = path.indexOf("#");
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : "";
  const pathAndQuery = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
  const queryIndex = pathAndQuery.indexOf("?");
  const pathname = queryIndex >= 0 ? pathAndQuery.slice(0, queryIndex) : pathAndQuery;
  if (pathname !== "/ai") return path;

  const context = normaliseAISymbolContext(value);
  if (!context) return path;

  const searchParams = new URLSearchParams(
    queryIndex >= 0 ? pathAndQuery.slice(queryIndex + 1) : "",
  );
  searchParams.set("symbol", context.symbol);
  searchParams.set("exchange", context.exchange);
  searchParams.set("source", context.source);
  const query = searchParams.toString();
  return `${pathname}${query ? `?${query}` : ""}${hash}`;
}
