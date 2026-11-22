import cases from "@flinttrade/order-rules-cases";
import { describe, expect, it } from "vitest";

import {
  evaluateOrderRules,
  hasBlockingRule,
  orderRules,
  ruleHeadline,
  ruleResultsFrom,
  stopLossLimitPrice,
  type OrderRuleInput,
} from "./orderRules";

interface Case {
  name: string;
  on: string;
  order: Record<string, string>;
  context: Record<string, string | boolean>;
  expected: { level: string; source: string; rule_id: string; message: string }[];
}

function toInput(item: Case): OrderRuleInput {
  const o = item.order;
  const c = item.context;
  const n = (value: unknown) => (value === undefined ? null : Number(value));
  return {
    symbol: o.symbol,
    exchange: o.exchange,
    orderType: o.pricetype,
    action: o.action,
    price: n(o.price),
    triggerPrice: n(o.trigger_price),
    product: o.product,
    hasStopLossOrTarget: Number(o.stop_loss_price ?? 0) > 0 || Number(o.target_price ?? 0) > 0,
    lastPrice: n(c.last_price),
    broker: (c.broker as string) ?? undefined,
    brokerName: (c.broker_name as string) ?? undefined,
    expiryDay: (c.expiry_day as boolean | undefined) ?? null,
    stopLossTargetPlacement: c.stop_loss_target_placement as "attached" | "separate" | undefined,
    tradedToday: (c.traded_today as boolean | undefined) ?? null,
    atMinutes: c.at_minutes === undefined ? null : Number(c.at_minutes),
    circuitLow: n(c.circuit_low),
    circuitHigh: n(c.circuit_high),
  };
}

describe("order rules mirror", () => {
  const all = (cases as unknown as { cases: Case[] }).cases;

  it("covers the shared case file", () => {
    expect(all.length).toBeGreaterThan(20);
  });

  it.each(all.map((item) => [item.name, item] as const))("matches the server for %s", (_name, item) => {
    expect(evaluateOrderRules(toInput(item), item.on)).toEqual(item.expected);
  });

  const limits = (cases as unknown as { stop_loss_limits: Record<string, string>[] }).stop_loss_limits;

  it.each(limits.map((item) => [`${item.symbol} ${item.exit_action} ${item.trigger}`, item] as const))(
    "places the stop-loss limit where the server does for %s",
    (_name, item) => {
      const limit = stopLossLimitPrice(
        { symbol: item.symbol, exchange: item.exchange, exitAction: item.exit_action, trigger: Number(item.trigger) },
        item.on,
      );
      expect(limit).toBe(Number(item.limit));
      const results = evaluateOrderRules(
        {
          symbol: item.symbol,
          exchange: item.exchange,
          orderType: "SL",
          action: item.exit_action,
          price: limit,
          triggerPrice: Number(item.trigger),
          lastPrice: Number(item.trigger),
        },
        item.on,
      );
      expect(results).toEqual([]);
    },
  );

  it("reads the same table the server reads", () => {
    const ids = orderRules().map((row) => row.id);
    expect(ids).toContain("bse-stop-limit-gap");
    expect(ids).toContain("sl-m-not-allowed-options");
  });

  it("prefixes the headline with its source", () => {
    const results = evaluateOrderRules({ symbol: "NIFTY25NOV2624000CE", exchange: "NFO", orderType: "MARKET" }, "2026-11-22");
    expect(ruleHeadline(results)).toBe("FlintTrade · Market orders aren't accepted on options. Use a limit price.");
    expect(hasBlockingRule(results)).toBe(true);
  });

  it("never blocks an equity limit order", () => {
    const results = evaluateOrderRules(
      { symbol: "RELIANCE", exchange: "NSE", orderType: "LIMIT", price: 1500, lastPrice: 1500 },
      "2026-11-22",
    );
    expect(hasBlockingRule(results)).toBe(false);
  });

  it("keeps only well-formed results from an API payload", () => {
    expect(
      ruleResultsFrom({
        rule_results: [{ level: "warn", source: "Exchange", rule_id: "x", message: "m" }, { level: "nope" }],
      }),
    ).toHaveLength(1);
    expect(ruleResultsFrom(null)).toEqual([]);
  });
});
