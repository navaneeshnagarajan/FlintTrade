/** Example currency pairs for Explore screens. No native crypto broker exists;
 * these display definitions carry no order size, tick or provider fee claims.
 */
export interface CryptoPairInfo {
  base: string;
  quote: "USD" | "INR";
  description: string;
  isSampleData: true;
}
const currencies = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP" } as const;
export const CRYPTO_PAIRS: Readonly<Record<string, CryptoPairInfo>> = Object.freeze(
  Object.fromEntries(Object.entries(currencies).flatMap(([base, name]) =>
    (["USD", "INR"] as const).map((quote) => [`${base}${quote}`, Object.freeze({
      base, quote, description: `${name} / ${quote} example`, isSampleData: true as const,
    })]),
  )),
);
export const CRYPTO_SYMBOLS = Object.freeze(Object.keys(CRYPTO_PAIRS).sort());
export function getCryptoPairInfo(symbol: string): CryptoPairInfo | undefined {
  const key = symbol.trim().toUpperCase();
  return Object.hasOwn(CRYPTO_PAIRS, key) ? CRYPTO_PAIRS[key] : undefined;
}
export function isCryptoPair(symbol: string): boolean { return getCryptoPairInfo(symbol) !== undefined; }
export function formatCryptoPrice(price: number, symbol: string): string {
  if (!Number.isFinite(price) || price < 0) throw new RangeError("Example price must be finite and non-negative");
  if (!getCryptoPairInfo(symbol)) throw new RangeError("Unknown example currency pair");
  return price.toFixed(2);
}
