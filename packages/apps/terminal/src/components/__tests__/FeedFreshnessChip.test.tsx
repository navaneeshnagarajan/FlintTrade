import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createStore, Provider as JotaiProvider } from "jotai";
import { tickerFallbackStatusAtom } from "@/hooks/useTickerFallback";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

const { mockWs } = vi.hoisted(() => ({
  mockWs: {
    diagnostics: { lastTickTimestamp: 0, tickAgeMs: -1, reconnectCount: 0 },
  },
}));

vi.mock("@/services/websocket", () => ({
  getWsService: () => mockWs,
}));

import FeedFreshnessChip from "../FeedFreshnessChip";

function renderChip() {
  const store = createStore();
  return render(
    <JotaiProvider store={store}>
      <FeedFreshnessChip />
    </JotaiProvider>,
  );
}

function renderChipWithFallback(status: {
  active: boolean;
  lastUpdatedAt: number | null;
  isStale: boolean;
}) {
  const store = createStore();
  store.set(tickerFallbackStatusAtom, {
    active: status.active,
    lastUpdatedAt: status.lastUpdatedAt,
    isStale: status.isStale,
    polledKeys: [],
    droppedKeys: [],
    truncated: false,
  });
  return render(
    <JotaiProvider store={store}>
      <FeedFreshnessChip />
    </JotaiProvider>,
  );
}

describe("FT-CORE-002 FeedFreshnessChip", () => {
  beforeEach(() => {
    mockWs.diagnostics.lastTickTimestamp = 0;
    useModeStore.setState({ mode: "explore" });
    useConnectionStore.setState({ wsConnected: false });
  });

  afterEach(() => {
    useModeStore.setState({ mode: "explore" });
    useConnectionStore.setState({ wsConnected: false });
  });

  it("Explore shows Sample, never a silent Live feed", () => {
    mockWs.diagnostics.lastTickTimestamp = Date.now() - 200;
    useConnectionStore.setState({ wsConnected: true });
    renderChip();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Sample");
    expect(chip).toHaveAttribute("data-state", "sample");
    expect(chip).toHaveAttribute("aria-label", expect.stringMatching(/feed source: sample/i));
    expect(chip).not.toHaveTextContent("Live");
  });

  it("Practice with a fresh WebSocket tick shows Live", () => {
    useModeStore.setState({ mode: "practice" });
    useConnectionStore.setState({ wsConnected: true });
    mockWs.diagnostics.lastTickTimestamp = Date.now() - 400;
    renderChip();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Live");
    expect(chip).toHaveAttribute("data-state", "live");
  });

  it("REST fallback snapshots show Delayed, not Live", () => {
    useModeStore.setState({ mode: "live" });
    renderChipWithFallback({
      active: true,
      lastUpdatedAt: Date.now() - 1_000,
      isStale: false,
    });

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Delayed");
    expect(chip).toHaveAttribute("data-state", "delayed");
    expect(chip).not.toHaveTextContent("Live");
  });

  it("stale quotes show muted Stale plus age", () => {
    useModeStore.setState({ mode: "live" });
    useConnectionStore.setState({ wsConnected: true });
    mockWs.diagnostics.lastTickTimestamp = Date.now() - 12_000;
    renderChip();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Stale · 12s");
    expect(chip).toHaveAttribute("data-state", "stale");
    expect(chip).toHaveClass("text-text-muted");
  });

  it("unknown source with no timestamp is muted Unknown without an invented age", () => {
    useModeStore.setState({ mode: "practice" });
    renderChip();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Unknown");
    expect(chip).not.toHaveTextContent("·");
    expect(chip).toHaveAttribute("data-state", "unknown");
    expect(chip).toHaveClass("text-text-muted");
  });
});
