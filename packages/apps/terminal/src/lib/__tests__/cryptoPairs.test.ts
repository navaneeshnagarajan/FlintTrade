import { describe, expect, it } from "vitest";
import { CRYPTO_PAIRS, CRYPTO_SYMBOLS, formatCryptoPrice, getCryptoPairInfo, isCryptoPair } from "../cryptoPairs";
describe("Explore currency-pair examples", () => {
  it("marks every definition as sample data without provider trading rules", () => {
    expect(CRYPTO_SYMBOLS).toHaveLength(8);
    for (const pair of Object.values(CRYPTO_PAIRS)) {
      expect(pair.isSampleData).toBe(true);
      expect(pair).not.toHaveProperty("lotSize");
      expect(pair).not.toHaveProperty("makerFee");
      expect(pair).not.toHaveProperty("tickSize");
    }
  });
  it("normalises display lookup without accepting prototype keys", () => {
    expect(getCryptoPairInfo(" btcusd ")).toMatchObject({ base: "BTC", quote: "USD", isSampleData: true });
    expect(isCryptoPair("ETHINR")).toBe(true);
    expect(isCryptoPair("constructor")).toBe(false);
    expect(getCryptoPairInfo("RELIANCE")).toBeUndefined();
  });
  it("formats finite example prices", () => { expect(formatCryptoPrice(123.456, "BTCUSD")).toBe("123.46"); });
  it.each([-1, Infinity, NaN])("rejects an invalid example price %s", (value) => { expect(() => formatCryptoPrice(value, "BTCUSD")).toThrow(RangeError); });
  it("rejects unknown pairs instead of inventing a price convention", () => { expect(() => formatCryptoPrice(1, "UNKNOWN")).toThrow(/unknown/i); });
});
