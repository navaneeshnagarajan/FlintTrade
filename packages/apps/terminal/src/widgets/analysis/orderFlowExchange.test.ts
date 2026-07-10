import { describe, expect, it } from "vitest";
import { resolveOrderFlowExchange } from "./orderFlowExchange";

describe("resolveOrderFlowExchange", () => {
  it.each([
    ["NIFTY", undefined, "NSE_INDEX"],
    ["BANKNIFTY", undefined, "NSE_INDEX"],
    ["FINNIFTY", undefined, "NSE_INDEX"],
    ["MIDCPNIFTY", undefined, "NSE_INDEX"],
    ["INDIAVIX", undefined, "NSE_INDEX"],
    ["SENSEX", undefined, "BSE_INDEX"],
    ["BANKEX", undefined, "BSE_INDEX"],
    ["RELIANCE", undefined, "NSE"],
    ["NIFTY25JULFUT", undefined, "NFO"],
    ["NIFTY25JUL2525000CE", undefined, "NFO"],
    ["SENSEX25JUL80000PE", undefined, "BFO"],
    ["GOLD", undefined, "MCX"],
    ["GOLD02APR26FUT", undefined, "MCX"],
    ["CRUDEOIL", undefined, "MCX"],
    ["CRUDEOIL25JANFUT", undefined, "MCX"],
    ["USDINR", undefined, "CDS"],
    ["USDINR24APR25FUT", undefined, "CDS"],
    ["USDINR24APR2583.5PE", undefined, "CDS"],
    ["NIFTY", "NFO", "NFO"],
    ["NIFTY", "  nfo  ", "NFO"],
    ["RELIANCE", "  bSe  ", "BSE"],
    ["RELIANCE", "   ", "NSE"],
  ])("resolves %s on %s to %s", (symbol, explicitExchange, exchange) => {
    expect(resolveOrderFlowExchange(symbol, explicitExchange)).toBe(exchange);
  });
});
