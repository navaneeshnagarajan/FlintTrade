import { describe, expect, it } from "vitest";
import {
  accountCharges,
  accountLedgerCash,
  accountNetWorth,
  markedValue,
  NET_WORTH_LABEL,
  NET_WORTH_POSITIONS_NOTE,
  positionNetWorthContribution,
  positionsNetWorthContribution,
  type MarkedLine,
  type PositionLine,
} from "../accountNetWorth";

const STARTING_CASH = 1_000_000;

describe("accountNetWorth", () => {
  it("keeps the total label and the positions note", () => {
    expect(NET_WORTH_LABEL).toBe("Net Worth (Cash + Holdings + Positions)");
    expect(NET_WORTH_POSITIONS_NOTE).toBe(
      "Options at market value, futures at unrealised P&L.",
    );
  });

  it("stays flat when a long option is bought and nothing else changes", () => {
    const premium = 235 * 65;
    const longOption: PositionLine = {
      symbol: "NIFTY24SEP23500CE",
      exchange: "NFO",
      quantity: 65,
      averagePrice: 235,
      ltp: 235,
    };
    const cashAfterPremium = STARTING_CASH - premium;

    expect(positionNetWorthContribution(longOption)).toBe(premium);
    expect(accountNetWorth([], cashAfterPremium, [longOption])).toBe(STARTING_CASH);
  });

  it("stays flat when a short option is sold, then moves with LTP", () => {
    const premium = 235 * 65;
    const cashAfterCredit = STARTING_CASH + premium;
    const atEntry: PositionLine = {
      symbol: "NIFTY24SEP23500PE",
      exchange: "NFO",
      quantity: -65,
      averagePrice: 235,
      ltp: 235,
    };
    const markedDown: PositionLine = { ...atEntry, ltp: 205 };

    expect(accountNetWorth([], cashAfterCredit, [atEntry])).toBe(STARTING_CASH);
    expect(positionNetWorthContribution(markedDown)).toBe(-205 * 65);
    expect(accountNetWorth([], cashAfterCredit, [markedDown])).toBe(STARTING_CASH + 30 * 65);
    expect(accountNetWorth([], cashAfterCredit, [markedDown])).not.toBe(205 * 65);
  });

  it("does not drop net worth by the margin blocked to open a future", () => {
    const blockedMargin = 50_000;
    const ledger = STARTING_CASH;
    const opened: PositionLine = {
      symbol: "NIFTY24APRFUT",
      exchange: "NFO",
      quantity: 50,
      averagePrice: 22_000,
      settlementPrice: 22_000,
      ltp: 22_000,
      futuresMtmInLedger: true,
    };

    expect(accountLedgerCash({
      availableCash: ledger - blockedMargin,
      usedMargin: blockedMargin,
      ledgerBalance: ledger,
    })).toBe(ledger);
    expect(positionNetWorthContribution(opened, [], true)).toBe(0);
    expect(accountNetWorth([], ledger, [opened], 0, true)).toBe(ledger);
    expect(accountNetWorth([], ledger, [opened], 0, true)).not.toBe(ledger - blockedMargin);
  });

  it("does not count settled futures MTM twice", () => {
    const carried: PositionLine = {
      symbol: "NIFTY24APRFUT",
      exchange: "NFO",
      quantity: 50,
      averagePrice: 22_000,
      settlementPrice: 22_100,
      ltp: 22_150,
    };
    const fromSettlement = (22_150 - 22_100) * 50;
    const fromEntry = (22_150 - 22_000) * 50;

    expect(positionNetWorthContribution(carried, [], true)).toBe(fromSettlement);
    expect(positionNetWorthContribution(carried, [], true)).not.toBe(fromEntry);
    expect(accountNetWorth([], STARTING_CASH, [carried], 0, true)).toBe(STARTING_CASH + fromSettlement);
    expect(positionNetWorthContribution(carried, [], false)).toBe(fromEntry);
  });

  it("adds nothing for a flat position, even when a broker pnl field is set", () => {
    const flatPosition: PositionLine = {
      symbol: "NIFTY24SEP23500CE",
      quantity: 0,
      averagePrice: 235,
      ltp: 205,
      pnl: 1_950,
    };

    expect(positionsNetWorthContribution([flatPosition])).toBe(0);
    expect(accountNetWorth([], 10_000, [flatPosition])).toBe(10_000);
  });

  it("mixes holdings, options, a settled future, and an equity position", () => {
    const holdings: MarkedLine[] = [
      { symbol: "RELIANCE", exchange: "NSE", ltp: 100, quantity: 10 },
    ];
    const positions: PositionLine[] = [
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        product: "CNC",
        quantity: 10,
        averagePrice: 90,
        ltp: 100,
      },
      {
        symbol: "INFY",
        exchange: "NSE",
        product: "MIS",
        quantity: 2,
        averagePrice: 40,
        ltp: 50,
      },
      {
        symbol: "NIFTY24SEP23500CE",
        exchange: "NFO",
        quantity: 65,
        averagePrice: 20,
        ltp: 20,
      },
      {
        symbol: "NIFTY24SEP23500PE",
        exchange: "NFO",
        quantity: -65,
        averagePrice: 10,
        ltp: 10,
      },
      {
        symbol: "NIFTY24APRFUT",
        exchange: "NFO",
        quantity: 50,
        averagePrice: 22_000,
        settlementPrice: 22_100,
        ltp: 22_150,
      },
      {
        symbol: "NIFTY24APRFUT",
        exchange: "NFO",
        quantity: 0,
        averagePrice: 22_000,
        ltp: 22_150,
        pnl: 9_999,
      },
    ];
    const cash = 500_000;
    const charges = 25;
    const positionsTerm = 0 + 100 + 1_300 + -650 + 2_500 + 0;

    expect(positionsNetWorthContribution(positions, holdings, true)).toBe(positionsTerm);
    expect(accountNetWorth(holdings, cash, positions, charges, true)).toBe(
      markedValue(holdings) + positionsTerm + cash - charges,
    );
  });

  it("uses the practice charges source, which is 0 today, and keeps blocked margin in cash", () => {
    const practiceBook = {
      availableCash: 999_200,
      usedMargin: 800,
      totalBalance: 1_000_000,
      ledgerBalance: 1_000_000,
      futuresMtmInLedger: false as const,
    };
    const positions: PositionLine[] = [{
      symbol: "NIFTY24APRFUT",
      exchange: "NFO",
      ltp: 22_000,
      quantity: 1,
      averagePrice: 22_000,
    }];
    const charges = accountCharges(practiceBook);
    const cash = accountLedgerCash(practiceBook);
    const total = accountNetWorth([], cash, positions, charges, practiceBook.futuresMtmInLedger);

    expect(charges).toBe(0);
    expect(cash).toBe(1_000_000);
    expect(positionsNetWorthContribution(positions)).toBe(0);
    expect(total).toBe(1_000_000);
    expect(total).not.toBe(practiceBook.availableCash);
  });
});
