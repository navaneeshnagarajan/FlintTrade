/**
 * PositionsCard renders the live Dhan and Kotak Neo adapter rows.
 *
 * The JSON is the output of from_dhan_position and from_kotak_position.
 * packages/integrations/gateway/tests/brokers/test_home_position_card_rows.py
 * fails if those functions drift from this file. Neither row carries pnlPercent.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

const rows = vi.hoisted(() => {
  const { readFileSync } = require("node:fs") as typeof import("node:fs");
  const { join } = require("node:path") as typeof import("node:path");
  const fixture = JSON.parse(
    readFileSync(join(process.cwd(), "src/routes/home/__tests__/fixtures/adapterPositionRows.json"), "utf8"),
  ) as Record<string, Record<string, unknown>>;
  return fixture;
});

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({
    data: [
      rows.dhan_without_pnl,
      rows.dhan_with_pnl,
      rows.dhan_no_cost,
      rows.neo_open_leg,
      rows.neo_no_cost,
    ],
    isLoading: false,
    isError: false,
    isSuccess: true,
    isFetching: false,
    fetchStatus: "idle",
    refetch: vi.fn(),
  }),
}));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
}));
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (sel: (s: { totalPnl: number }) => unknown) => sel({ totalPnl: 0 }),
}));

import { useModeStore } from "@/stores/modeStore";
import { PositionsCard } from "../PositionsCard";

function derivedPercent(row: Record<string, unknown>): string {
  const quantity = Math.abs(Number(row.quantity));
  const average = Number(row.average_price);
  const pnl = Number(row.pnl);
  const cost = average * quantity;
  const percent = (pnl / cost) * 100;
  return `${percent >= 0 ? "+" : ""}${percent.toFixed(2)}%`;
}

describe("PositionsCard broker rows", () => {
  it("derives the percent from cost on real Dhan and Neo rows", () => {
    expect(rows.dhan_with_pnl).not.toHaveProperty("pnlPercent");
    expect(rows.neo_open_leg).not.toHaveProperty("pnlPercent");
    expect(Number(rows.dhan_with_pnl.average_price) * Math.abs(Number(rows.dhan_with_pnl.quantity))).toBeGreaterThan(0);
    expect(Number(rows.neo_open_leg.average_price) * Math.abs(Number(rows.neo_open_leg.quantity))).toBeGreaterThan(0);

    useModeStore.setState({ mode: "live" });
    render(<PositionsCard />);

    expect(screen.getByTestId("position-pnl-percent-BANKNIFTY-JUN2026-FUT")).toHaveTextContent(
      derivedPercent(rows.dhan_with_pnl),
    );
    expect(screen.getByTestId("position-pnl-percent-BANKNIFTY-JUN2026-FUT")).toHaveTextContent("-0.03%");
    expect(screen.getByTestId("position-pnl-percent-NIFTY25JUNFUT")).toHaveTextContent(
      derivedPercent(rows.neo_open_leg),
    );
    expect(screen.getByTestId("position-pnl-percent-NIFTY25JUNFUT")).toHaveTextContent("+0.00%");
  });

  it("shows a dash when a real Dhan or Neo row has no cost basis", () => {
    expect(rows.dhan_no_cost).not.toHaveProperty("pnlPercent");
    expect(rows.neo_no_cost).not.toHaveProperty("pnlPercent");
    expect(rows.dhan_no_cost).not.toHaveProperty("average_price");
    expect(rows.neo_no_cost).not.toHaveProperty("average_price");
    expect(rows.dhan_without_pnl).not.toHaveProperty("pnl");

    useModeStore.setState({ mode: "live" });
    render(<PositionsCard />);

    expect(screen.getByTestId("position-pnl-percent-IDEA")).toHaveTextContent("—");
    expect(screen.getByTestId("position-pnl-percent-RELIANCE")).toHaveTextContent("—");
    expect(screen.getByTestId("position-pnl-percent-NIFTY-JUN2026-FUT")).toHaveTextContent("—");
  });
});
