import { describe, expect, it } from "vitest";
import {
  accountCharges,
  accountNetWorth,
  markedValue,
  type MarkedLine,
} from "../accountNetWorth";

describe("accountNetWorth", () => {
  it("is cash + holdings + positions − charges", () => {
    const holdings: MarkedLine[] = [{ ltp: 100, quantity: 2 }];
    const positions: MarkedLine[] = [{ ltp: 10, quantity: 3 }];
    const cash = 50;
    const charges = 4;

    expect(accountNetWorth(holdings, cash, positions, charges)).toBe(
      markedValue(holdings) + markedValue(positions) + cash - charges,
    );
  });

  it("uses the practice charges source, which is 0 today", () => {
    const practiceBook = {
      availableCash: 999_200,
      usedMargin: 800,
      totalBalance: 1_000_000,
    };
    const holdings: MarkedLine[] = [];
    const positions: MarkedLine[] = [{ ltp: 800, quantity: 1 }];
    const charges = accountCharges(practiceBook);

    expect(accountNetWorth(holdings, practiceBook.availableCash, positions, charges)).toBe(
      markedValue(holdings) + markedValue(positions) + practiceBook.availableCash - charges,
    );
  });
});
