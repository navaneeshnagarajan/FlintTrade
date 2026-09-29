import { describe, expect, it } from "vitest";
import {
  accountCharges,
  accountNetWorth,
  markedValue,
  NET_WORTH_LABEL,
  NET_WORTH_POSITIONS_NOTE,
  positionsUnrealisedPnl,
  type MarkedLine,
  type PositionLine,
} from "../accountNetWorth";

const shortOption: PositionLine = {
  quantity: -65,
  averagePrice: 235,
  ltp: 205,
  pnl: 0,
};

const longFuture: PositionLine = {
  quantity: 50,
  averagePrice: 22_000,
  ltp: 22_100,
  pnl: 0,
};

const flatPosition: PositionLine = {
  quantity: 0,
  averagePrice: 235,
  ltp: 205,
  pnl: 1_950,
};

describe("accountNetWorth", () => {
  it("keeps one total label and describes positions at unrealised P&L", () => {
    expect(NET_WORTH_LABEL).toBe("Net Worth (Cash + Holdings + Positions)");
    expect(NET_WORTH_POSITIONS_NOTE).toBe("Positions count at unrealised P&L.");
  });

  it("adds a short option's unrealised P&L and never its notional", () => {
    const contribution = positionsUnrealisedPnl([shortOption]);
    const notional = 205 * 65;

    expect(contribution).toBe(1_950);
    expect(contribution).not.toBe(notional);
    expect(contribution).not.toBe(235 * 65);
    expect(accountNetWorth([], 0, [shortOption])).toBe(1_950);
    expect(accountNetWorth([], 0, [shortOption])).not.toBe(notional);
  });

  it("adds a long F&O position's unrealised P&L and never its notional", () => {
    const contribution = positionsUnrealisedPnl([longFuture]);
    const notional = 22_100 * 50;

    expect(contribution).toBe(5_000);
    expect(contribution).not.toBe(notional);
    expect(accountNetWorth([], 0, [longFuture])).toBe(5_000);
  });

  it("adds nothing for a flat position, even when a broker pnl field is set", () => {
    expect(positionsUnrealisedPnl([flatPosition])).toBe(0);
    expect(accountNetWorth([], 10_000, [flatPosition])).toBe(10_000);
  });

  it("is cash + holdings market value + unrealised P&L − charges on a mixed book", () => {
    const holdings: MarkedLine[] = [{ ltp: 100, quantity: 10 }];
    const positions = [shortOption, longFuture, flatPosition];
    const cash = 500_000;
    const charges = 25;
    const positionPnl = 1_950 + 5_000;
    const notional = 205 * 65 + 22_100 * 50;

    expect(positionsUnrealisedPnl(positions)).toBe(positionPnl);
    expect(accountNetWorth(holdings, cash, positions, charges)).toBe(
      markedValue(holdings) + positionPnl + cash - charges,
    );
    expect(accountNetWorth(holdings, cash, positions, charges)).not.toBe(
      markedValue(holdings) + notional + cash - charges,
    );
  });

  it("uses the practice charges source, which is 0 today, and ignores flat notional", () => {
    const practiceBook = {
      availableCash: 999_200,
      usedMargin: 800,
      totalBalance: 1_000_000,
    };
    const holdings: MarkedLine[] = [];
    const positions: PositionLine[] = [{ ltp: 800, quantity: 1, averagePrice: 800, pnl: 0 }];
    const charges = accountCharges(practiceBook);
    const total = accountNetWorth(holdings, practiceBook.availableCash, positions, charges);

    expect(charges).toBe(0);
    expect(positionsUnrealisedPnl(positions)).toBe(0);
    expect(total).toBe(practiceBook.availableCash);
    expect(total).not.toBe(practiceBook.availableCash + 800);
  });
});
