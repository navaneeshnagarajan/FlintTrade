import { describe, expect, it } from "vitest";
import { accountNetWorth, formatAccountNetWorth } from "../accountNetWorth";

describe("accountNetWorth", () => {
  it("keeps ₹10,00,000 after buying 1 SBIN at ₹800 when the price is unchanged", () => {
    const worth = accountNetWorth([], 999_200, [{ ltp: 800, quantity: 1 }]);

    expect(worth).toBe(1_000_000);
    expect(formatAccountNetWorth(worth)).toBe(formatAccountNetWorth(1_000_000));
  });

  it("sums cash, holdings, and positions", () => {
    expect(
      accountNetWorth(
        [{ ltp: 100, quantity: 2 }],
        50,
        [{ ltp: 10, quantity: 3 }],
      ),
    ).toBe(280);
  });
});
