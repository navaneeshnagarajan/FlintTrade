/**
 * PositionsWidget.test.tsx
 *
 * Tests for the merged Positions widget — the position book's THREE views.
 * Covers the gated write path (per-row Convert, per-row square-off, the typed
 * exit-all flow, exact displayed-account authority and the fail-closed product
 * check), the Excel export, and the two absorbed views: netting/grouping/totals
 * (from the retired Net Position widget) and the treemap/grouping/chart-open
 * contract (from the retired Position Heat Map widget).
 *
 * The pure kernel (`positionBook.ts`) is exercised directly at the bottom —
 * exposure, mark-to-market and netting have ONE definition each now, so those
 * assertions are the reconciliation's pins.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// Force DEV mode so ftApi.helpers' getBase() returns "/ft-api" — the convert
// and exit-all actions go through the real helpers with a stubbed fetch.
vi.stubEnv("DEV", true);

// Radix Select (the broker-target picker, the heat-map group picker) and the
// heat map's container measurement both need ResizeObserver.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUsePositions = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockConnectionState = vi.hoisted(() => ({
  apiKey: "",
  // openAlgoHydrated: true models a normally-loaded app; the hydration
  // fail-closed window is covered by brokerTargets/api tests.
  openAlgoHydrated: true,
}));
const mockModeState = vi.hoisted(() => ({
  mode: "live",
}));
const mockBrokerState = vi.hoisted(() => ({
  accounts: [] as Array<{
    broker: string;
    account_id: string;
    label: string;
    source?: string;
    status?: string;
    is_primary?: boolean;
    read_only?: boolean;
  }>,
  activeAccountId: null as string | null,
}));
const mockReadState = vi.hoisted(() => ({
  identity: null as null | {
    mode: string;
    scopeKey: string;
    brokerType: string;
    accountId: string;
  },
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseBrokerConnected(),
  useAccountReadContext: () => {
    const mode = mockModeState.mode;
    const account = mockBrokerState.accounts.find((candidate) =>
      mockBrokerAccountMatch(candidate, mockBrokerState.activeAccountId),
    ) ?? mockBrokerState.accounts[0];
    const identity = mockReadState.identity ?? (mode === "explore"
      ? {
          mode,
          scopeKey: "explore:mock:default",
          brokerType: "mock",
          accountId: "default",
        }
      : mode === "practice"
        ? {
            mode,
            scopeKey: "practice:sandbox:default",
            brokerType: "sandbox",
            accountId: "default",
          }
        : account
          ? {
              mode,
              scopeKey: ["live", "native", account.broker, account.account_id]
                .map(encodeURIComponent)
                .join(":"),
              brokerType: account.broker,
              accountId: account.account_id,
            }
          : {
              mode,
              scopeKey: "live:openalgo:test",
              brokerType: "openalgo",
              accountId: "default",
            });
    return {
      identity,
      enabled: mockUseBrokerConnected(),
      host: "",
      apiKey: "",
    };
  },
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Deterministic colour string so the heat-map assertions do not depend on
// exact RGB maths.
vi.mock("@/lib/colourScale", () => ({
  divergingColourScaleRange: () => "rgb(80,160,100)",
  divergingColourScale: () => "rgb(80,160,100)",
}));

// Mock tradingStore to avoid side-effects in usePositions
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: Object.assign(() => ({}), {
    getState: () => ({ updateFromPositions: vi.fn() }),
  }),
}));

// ftApi.helpers reads these stores for auth headers on every call.
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: Object.assign(
    (selector?: (s: { apiKey: string }) => unknown) =>
      typeof selector === "function" ? selector(mockConnectionState) : mockConnectionState,
    { getState: () => mockConnectionState },
  ),
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector(mockModeState) : mockModeState,
}));

const mockDownloadExcel = vi.fn();
vi.mock("@/services/ftApi.data", () => ({
  downloadExcel: (...args: unknown[]) => mockDownloadExcel(...args),
}));

// Square-off goes through the existing gated placeOrder path (services/api →
// /ft-api/api/v1/orders/place → SafetySystem → gate_order → BrokerRouter).
const mockPlaceOrder = vi.fn();
vi.mock("@/services/api", () => ({
  placeOrder: (...args: unknown[]) => mockPlaceOrder(...args),
}));

const mockEmitNotification = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmitNotification(...args),
}));

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: { account_id: string; broker: string; source?: string }) => [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":"),
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: string }>,
    selector: string | null,
  ) => accounts.find((account) => mockBrokerAccountMatch(account, selector)),
  isBrokerAccountMatch: (
    account: { account_id: string; broker: string; source?: string },
    selector: string | null,
  ) => mockBrokerAccountMatch(account, selector),
  useBrokerStore: Object.assign(
    (selector?: (s: typeof mockBrokerState) => unknown) =>
      typeof selector === "function" ? selector(mockBrokerState) : mockBrokerState,
    { getState: () => mockBrokerState },
  ),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import PositionsWidget from "../PositionsWidget";
import {
  netPositions,
  normalisePositions,
  positionExposure,
  underlyingOf,
} from "../positionBook";
import { SAMPLE_POSITION_BOOK } from "../sampleBook";

function mockBrokerAccountMatch(
  account: { account_id: string; broker: string; source?: string },
  selector: string | null,
) {
  if (!selector) return false;
  const key = [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":");
  return key === selector || account.account_id === selector;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

/** Panel props that open the widget on one of the two absorbed views. */
function viewProps(view: "table" | "net" | "heat") {
  return makeWidgetPanelProps<Record<string, unknown>>({ params: { view } });
}

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    ...overrides,
  };
}

/** JSDOM reports 0×0 for every rect, which culls every treemap cell. */
function withMeasuredContainer(run: () => void) {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function () {
    return {
      width: 800, height: 400, top: 0, left: 0, right: 800, bottom: 400, x: 0, y: 0,
      toJSON() {},
    } as DOMRect;
  };
  try {
    run();
  } finally {
    Element.prototype.getBoundingClientRect = original;
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PositionsWidget", () => {
  afterEach(async () => {
    // Radix focus-scope schedules a setTimeout on dialog unmount; drain it
    // INSIDE this test's jsdom realm. Left pending, it fires during the
    // next test file's realm swap and crashes the run with "parameter 1 is
    // not of type 'Event'" — the cross-file flake that intermittently
    // failed the whole trading bucket.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  beforeEach(() => {
    vi.restoreAllMocks();
    mockPlaceOrder.mockReset();
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockUseBrokerConnected.mockReturnValue(true);
    mockBrokerState.accounts = [];
    mockBrokerState.activeAccountId = null;
    mockReadState.identity = null;
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = render(<PositionsWidget {...defaultProps} />);
    expect(container.querySelector("[data-tour-target='positions']")).toBeInTheDocument();
  });

  it("shows 'No open positions' when data is empty", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("shows the empty state when data is undefined", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: undefined }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("shows pending status before first authoritative success (and no empty or error)", () => {
    mockUsePositions.mockReturnValue(queryResult({ isPending: true, isLoading: true, data: undefined }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByLabelText(/loading positions/i)).toBeInTheDocument();
    expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows error/unavailable on failure but never with empty when no prior data", () => {
    mockUsePositions.mockReturnValue(
      queryResult({ isError: true, error: new Error("network fail"), data: undefined }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/failed to load positions/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
  });

  it("shows empty copy only after a successful empty response", () => {
    mockUsePositions.mockReturnValue(queryResult({ isPending: false, isError: false, data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("does not fetch or expose position actions without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /exit all positions/i })).not.toBeInTheDocument();
  });

  it("does not fetch for the heat view either when the broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...viewProps("heat")} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
  });

  it("displays position rows with symbol, qty, and P&L", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, average_price: 134 },
          { symbol: "BANKNIFTY24APR51000PE", pnl: -800, quantity: -30, ltp: 220, average_price: 193 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Symbols should be visible
    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR51000PE")).toBeInTheDocument();

    // P&L is the shared mark-to-market, not the broker's `pnl` field:
    // (150 − 134) × 75 = +1,200 and (220 − 193) × −30 = −810 (the broker said
    // −800). A loss now carries its minus sign; the table used to print the
    // absolute value, so a ₹810 loss read as "₹810".
    expect(screen.getByText("+₹1,200")).toBeInTheDocument();
    expect(screen.getByText("-₹810")).toBeInTheDocument();
  });

  it("shows connected practice positions read-only without broker write controls", () => {
    mockModeState.mode = "practice";
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, exchange: "NFO", product: "NRML" },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: true }));
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    // Provenance is labelled separately from capability: sandbox book, no writes.
    expect(screen.getByText("Practice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
  });

  it("shows the header with position count", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Header shows "Positions (1)"
    expect(screen.getByText("Positions (1)")).toBeInTheDocument();
  });

  it("displays total P&L in the header from the shared mark-to-market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "A", pnl: 1000, quantity: 10, ltp: 100, average_price: 90 },
          { symbol: "B", pnl: -300, quantity: 20, ltp: 50, average_price: 65 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // (100 − 90) × 10 = +100, (50 − 65) × 20 = −300 → −200. The broker's own
    // `pnl` fields would have summed to +700; totalPositionMtm is the single
    // definition, so the header, the net total and the heat cells agree.
    expect(screen.getByText("P&L: -₹200")).toBeInTheDocument();
  });

  it("falls back to the broker P&L when the row cannot be marked to market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        // ltp 0 — an illiquid option the broker never priced. Recomputing would
        // fabricate a (0 − 134) × 75 loss.
        data: [{ symbol: "NIFTY24APR24000CE", pnl: 640, quantity: 75, ltp: 0, average_price: 134 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("P&L: +₹640")).toBeInTheDocument();
  });

  // ── Absorbed from the retired Dashboard widget (ruling D5) ───────────────

  it("shows the P&L% column with the kernel's derived percentage", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        // No broker pnlPercent → the kernel derives (150 − 134) / 134 × 100
        // × sign(qty) = +11.94%. The retired Dashboard recomputed this
        // per-row; the column now renders the ONE normalised figure.
        data: [{ symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, average_price: 134 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByRole("columnheader", { name: /P&L%/ })).toBeInTheDocument();
    expect(screen.getByText("+11.94%")).toBeInTheDocument();
  });

  it("prefers a broker-supplied P&L% over the derivation, like every other view", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "INFY", pnl: 3000, quantity: 100, ltp: 1510, average_price: 1480, pnlPercent: 5.5 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("+5.50%")).toBeInTheDocument();
    // The derivation would have said +2.03% — the broker figure wins.
    expect(screen.queryByText("+2.03%")).not.toBeInTheDocument();
  });

  it("signs a losing row's P&L% as a loss", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TCS", pnl: -4000, quantity: 50, ltp: 3820, average_price: 3900 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const pct = screen.getByText("-2.05%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-loss");
  });

  it("renders the position-status tracker with counts from the shared mark-to-market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          // (100 − 90) × 10 = +100 → profit.
          { symbol: "A", pnl: 100, quantity: 10, ltp: 100, average_price: 90 },
          // (50 − 65) × 20 = −300 → loss, even though the broker's own `pnl`
          // says +1000: the tracker tones by the kernel mtm, not the raw field.
          { symbol: "B", pnl: 1000, quantity: 20, ltp: 50, average_price: 65 },
          // (2500 − 2500) × 10 = 0 → flat.
          { symbol: "C", pnl: 0, quantity: 10, ltp: 2500, average_price: 2500 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByRole("img", { name: "Position status tracker" })).toBeInTheDocument();
    expect(screen.getByText("1 profit")).toBeInTheDocument();
    expect(screen.getByText("1 loss")).toBeInTheDocument();
    expect(screen.getByText("1 flat")).toBeInTheDocument();
  });

  it("keeps the tracker off the net and heat views and off the empty book", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);
    expect(screen.queryByRole("img", { name: "Position status tracker" })).not.toBeInTheDocument();

    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "A", pnl: 100, quantity: 10, ltp: 100, average_price: 90, exchange: "NSE", product: "MIS" }],
      }),
    );
    render(<PositionsWidget {...viewProps("net")} />);
    expect(screen.queryByRole("img", { name: "Position status tracker" })).not.toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("shows an unfrozen error banner and Retry button when the initial fetch has no data", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Network timeout"),
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/failed to load positions/i);
    // No prior row or successful update exists, so nothing can truthfully be
    // described as frozen.
    expect(alert.textContent).not.toMatch(/frozen/i);
    expect(alert.textContent).toContain("Network timeout");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("calls refetch when Retry button is clicked in error state", () => {
    const mockRefetch = vi.fn();
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Server error"),
        refetch: mockRefetch,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryBtn);

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });

  it("clicking the Symbol column header toggles sort direction indicator", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
          { symbol: "BANKNIFTY", pnl: 200, quantity: 25, ltp: 200, average_price: 190 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const symbolHeader = screen.getByRole("columnheader", { name: /symbol/i });
    // First click — ascending sort indicator
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↑/i);

    // Second click — descending
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↓/i);
  });

  it("shows Retry button as disabled while isFetching is true", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Error"),
        isFetching: true,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retrying/i });
    expect(retryBtn).toBeDisabled();
  });

  // ── Freshness (absorbed from the retired Net Position widget) ────────────

  it("shows a last-updated indicator once data arrives", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TATAMOTORS", pnl: 250, quantity: 5, ltp: 950, average_price: 900 }],
        dataUpdatedAt: Date.now(),
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const chip = screen.getByRole("status", { name: /positions last updated/i });
    expect(chip.textContent).toMatch(/updated \d{2}:\d{2}:\d{2}/i);
    expect(chip.textContent).not.toMatch(/stale/i);
  });

  it("flags the P&L as stale when the feed stops refreshing", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TATAMOTORS", pnl: 250, quantity: 5, ltp: 950, average_price: 900 }],
        // Beyond both the market (30s) and off-hours (150s) thresholds.
        dataUpdatedAt: Date.now() - 200_000,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const chip = screen.getByRole("status", { name: /positions last updated .* stale/i });
    expect(chip.textContent).toMatch(/stale since \d{2}:\d{2}:\d{2}/i);
  });

  it("shows no error banner, staleness chip or broker warning for the Explore sample", () => {
    mockModeState.mode = "explore";
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(
      queryResult({ data: undefined, isError: true, error: new Error("unreachable") }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.getByText(/Sample data — connect a broker/i)).toBeInTheDocument();
  });

  // ── Excel export ─────────────────────────────────────────────────────────

  it("does not show the export button when there are no positions", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);
    expect(screen.queryByRole("button", { name: /export positions to excel/i })).toBeNull();
  });

  it("exports the positions and emits a success notification", async () => {
    mockDownloadExcel.mockResolvedValue(2);
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
          { symbol: "BANKNIFTY", pnl: -200, quantity: 25, ltp: 200, average_price: 190 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /export positions to excel/i }));

    await vi.waitFor(() => expect(mockDownloadExcel).toHaveBeenCalledTimes(1));
    // Exports the mapped rows under the "Positions" sheet.
    expect(mockDownloadExcel.mock.calls[0][1]).toBe("Positions");
    expect(mockDownloadExcel.mock.calls[0][0]).toHaveLength(2);
    await vi.waitFor(() =>
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Positions exported" }),
      ),
    );
  });

  it("emits an alert notification when the export fails", async () => {
    mockDownloadExcel.mockRejectedValue(new Error("backend down"));
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /export positions to excel/i }));

    await vi.waitFor(() =>
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "alert", title: "Export failed", body: "backend down" }),
      ),
    );
  });

  // ── Convert + exit-all safety actions ───────────────────────────────────

  describe("position actions", () => {
    beforeEach(() => {
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "POSITIONS-A",
        label: "Positions account",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:POSITIONS-A";
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function stubFetch(body: unknown = { status: "success", data: { ok: true } }, status = 200) {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    const positions = [
      {
        symbol: "NIFTY24APR24000CE",
        pnl: 1200,
        quantity: 75,
        ltp: 150,
        average_price: 134,
        exchange: "NFO",
        product: "NRML",
      },
      {
        symbol: "RELIANCE",
        pnl: -200,
        quantity: -10,
        ltp: 2900,
        average_price: 2880,
        exchange: "NSE",
        product: "MIS",
      },
    ];

    it("converts a position through the gated convert route", async () => {
      const fetchMock = stubFetch();
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      expect(screen.getByText("Convert position")).toBeInTheDocument();

      // NRML defaults to MIS as the target product — confirm without
      // touching the select.
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/convert");
      expect(init.method).toBe("POST");
      const body = JSON.parse(String(init.body)) as {
        broker: string;
        req: Record<string, unknown>;
      };
      expect(body.broker).toBe("dhan");
      expect(body.req).toMatchObject({
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        quantity: 75,
        position_type: "LONG",
        from_product: "NRML",
        to_product: "MIS",
        new_product: "MIS",
      });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Position conversion submitted" }),
      );
    });

    it("surfaces the mode-guard 403 honestly inside the convert dialog", async () => {
      stubFetch(
        { status: "error", message: "Live orders are allowed in live mode only — switch mode first" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      expect(
        await screen.findByText("Live orders are allowed in live mode only — switch mode first"),
      ).toBeInTheDocument();
      // The dialog stays open so the operator can read what blocked it.
      expect(screen.getByText("Convert position")).toBeInTheDocument();
    });

    it("blocks exit-all until the operator types EXIT, then posts the confirmed body", async () => {
      const fetchMock = stubFetch({ status: "success", data: { status: "ok" } });
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();

      const confirmButton = screen.getByRole("button", { name: "Confirm exit all positions" });
      expect(confirmButton).toBeDisabled();

      // Clicking while disabled must never reach the backend.
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // A wrong phrase keeps it blocked.
      const input = screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i);
      fireEvent.change(input, { target: { value: "exit" } });
      expect(confirmButton).toBeDisabled();
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // The exact phrase unlocks the action.
      fireEvent.change(input, { target: { value: "EXIT" } });
      expect(confirmButton).toBeEnabled();
      fireEvent.click(confirmButton);

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/exit-all");
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toStrictEqual({
        confirm: true,
        broker: "dhan",
        account_id: "POSITIONS-A",
      });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Exit-all submitted" }),
      );
    });

    it("keeps exit-all reachable from the absorbed views (it is book-level)", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByRole("button", { name: "Exit all positions" })).toBeInTheDocument();
      // Per-row writes stay on the table view: a net row is an aggregate of
      // broker rows, and squaring one off would mean inventing a multi-leg plan.
      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
    });

    it("surfaces the mode-guard 403 honestly inside the exit-all dialog", async () => {
      stubFetch(
        { status: "error", message: "Live mode is locked — verify your PIN to unlock live trading" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      expect(
        await screen.findByText("Live mode is locked — verify your PIN to unlock live trading"),
      ).toBeInTheDocument();
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();
    });

    // ── Per-position square-off (existing gated placeOrder path) ────────────

    it("squares off a long position with an opposite-side market order via placeOrder", async () => {
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ1" });
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));

      // Confirm dialog spells out symbol, quantity and side before anything fires.
      expect(screen.getByText("Square off position?")).toBeInTheDocument();
      expect(
        screen.getByText((_, el) =>
          (el?.textContent ?? "").includes("SELL market order for 75 NIFTY24APR24000CE") &&
          el?.tagName === "P",
        ),
      ).toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith({
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        action: "SELL",
        product: "NRML",
        orderType: "MARKET",
        quantity: 75,
        price: 0,
        triggerPrice: 0,
        strategy: "FlintPositions",
      }, {
        mode: "live",
        scopeKey: "live:native:dhan:POSITIONS-A",
        brokerType: "dhan",
        accountId: "POSITIONS-A",
      });
      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "order", title: "Square-off submitted" }),
      );
    });

    it("squares off a short position with a BUY market order for the absolute quantity", async () => {
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ2" });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off RELIANCE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off RELIANCE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "RELIANCE",
          exchange: "NSE",
          action: "BUY",
          product: "MIS",
          orderType: "MARKET",
          quantity: 10,
        }),
        expect.objectContaining({
          scopeKey: "live:native:dhan:POSITIONS-A",
          brokerType: "dhan",
          accountId: "POSITIONS-A",
        }),
      );
    });

    it("surfaces the backend rejection honestly inside the square-off dialog", async () => {
      mockPlaceOrder.mockRejectedValue(
        new Error("Live orders are allowed in live mode only — switch mode first"),
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      expect(
        await screen.findByText("Live orders are allowed in live mode only — switch mode first"),
      ).toBeInTheDocument();
      // The dialog stays open so the operator can read what blocked it.
      expect(screen.getByText("Square off position?")).toBeInTheDocument();
    });

    it("fails closed on an unrecognised product instead of guessing one", async () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            {
              symbol: "NIFTY24APR24000CE",
              pnl: 100,
              quantity: 75,
              ltp: 150,
              average_price: 134,
              exchange: "NFO",
              product: "BO", // bracket order — not a convertible/square-off product here
            },
          ],
        }),
      );
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      expect(screen.getByText(/unrecognised product/i)).toBeInTheDocument();

      const confirmBtn = screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" });
      expect(confirmBtn).toBeDisabled();
      fireEvent.click(confirmBtn);
      expect(mockPlaceOrder).not.toHaveBeenCalled();
    });

    it("exposes no mutations when account A owns the displayed book but account B is selected", () => {
      const fetchMock = stubFetch();
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [
        {
          broker: "dhan",
          account_id: "ACCOUNT-A",
          label: "Account A",
          source: "native",
          status: "connected",
        },
        {
          broker: "upstox",
          account_id: "ACCOUNT-B",
          label: "Account B",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("keeps native-only convert and exit-all off an OpenAlgo position book", () => {
      mockConnectionState.apiKey = "openalgo-key";
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:openalgo:book-scope",
        brokerType: "openalgo",
        accountId: "default",
      };
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "ACCOUNT-A",
        label: "Native account",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:ACCOUNT-A";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    });

    it("refuses mutation when a primary native book is shown without an active selection", () => {
      const fetchMock = stubFetch();
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:PRIMARY-A",
        brokerType: "dhan",
        accountId: "PRIMARY-A",
      };
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "PRIMARY-A",
        label: "Primary account",
        source: "native",
        status: "connected",
        is_primary: true,
      }];
      mockBrokerState.activeAccountId = null;
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("does not square off account A after account B is selected while confirmation is open", async () => {
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [
        {
          broker: "dhan",
          account_id: "ACCOUNT-A",
          label: "Account A",
          source: "native",
          status: "connected",
        },
        {
          broker: "upstox",
          account_id: "ACCOUNT-B",
          label: "Account B",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:dhan:ACCOUNT-A";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      const { rerender } = render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
      rerender(<PositionsWidget {...makeWidgetPanelProps()} />);

      const confirm = screen.queryByRole("button", { name: "Confirm square off NIFTY24APR24000CE" });
      if (confirm) fireEvent.click(confirm);
      await waitFor(() => expect(mockPlaceOrder).not.toHaveBeenCalled());
    });

    it("pins the exact displayed account identity into square-off placeOrder", async () => {
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:upstox:ACCOUNT-A",
        brokerType: "upstox",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [{
        broker: "upstox",
        account_id: "ACCOUNT-A",
        label: "Account A",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-A";
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ-EXACT" });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "NIFTY24APR24000CE",
          action: "SELL",
          quantity: 75,
        }),
        {
          mode: "live",
          scopeKey: "live:native:upstox:ACCOUNT-A",
          brokerType: "upstox",
          accountId: "ACCOUNT-A",
        },
      );
    });

    // ── Exact displayed-account target (convert/exit-all are native-only) ──

    it("does not render an independent broker-target selector for position mutations", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    });

    it("defaults gated position writes to the active native account in native-only Live mode", async () => {
      mockBrokerState.accounts = [
        {
          broker: "upstox",
          account_id: "UP-9",
          label: "F&O",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:upstox:UP-9";
      const fetchMock = stubFetch();
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(String(init.body)) as { broker: string; account_id: string };
      expect(body.broker).toBe("upstox");
      expect(body.account_id).toBe("UP-9");
    });

    it("threads the exact displayed native account into the convert request", async () => {
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "DHAN-1",
        label: "Primary",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:DHAN-1";
      const fetchMock = stubFetch();
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(String(init.body)) as { broker: string; account_id: string };
      expect(body.broker).toBe("dhan");
      expect(body.account_id).toBe("DHAN-1");
    });

    it("threads the exact displayed native account into the exit-all request", async () => {
      mockBrokerState.accounts = [{
        broker: "upstox",
        account_id: "UP-9",
        label: "F&O",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:upstox:UP-9";
      const fetchMock = stubFetch({ status: "success", data: { status: "ok" } });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(String(init.body))).toStrictEqual({
        confirm: true,
        broker: "upstox",
        account_id: "UP-9",
      });
    });
  });

  // ── Net view (absorbed from the retired Net Position widget) ─────────────

  describe("net view", () => {
    const LIVE = [
      { symbol: "TATAMOTORS", exchange: "NSE", product: "MIS", quantity: 5, averagePrice: 900, ltp: 950, pnl: 250 },
      { symbol: "TATAMOTORS", exchange: "NSE", product: "CNC", quantity: -2, averagePrice: 900, ltp: 950, pnl: -100 },
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
    ];

    it("renders the netted table with its headers and totals footer", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByLabelText("Net positions table")).toBeInTheDocument();
      expect(screen.getByText("Symbol")).toBeInTheDocument();
      expect(screen.getByText("Net Qty")).toBeInTheDocument();
      expect(screen.getByText("Avg")).toBeInTheDocument();
      expect(screen.getByText("LTP")).toBeInTheDocument();
      expect(screen.getByText(/Net P&L/i)).toBeInTheDocument();
      expect(screen.getByText("Exposure")).toBeInTheDocument();
      expect(screen.getByText("Total")).toBeInTheDocument();
    });

    it("nets the broker's split rows for one symbol into a single net row", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      // 5 long MIS + 2 short CNC = net +3, one row, under the TATAMOTORS group.
      expect(screen.getByLabelText("TATAMOTORS: net qty 3")).toBeInTheDocument();
      expect(screen.getByLabelText("TATAMOTORS group — 1 positions")).toBeInTheDocument();
      expect(screen.getByText("Positions (2)")).toBeInTheDocument();
    });

    it("clicking a group header collapses its rows", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      const group = screen.getByLabelText("TATAMOTORS group — 1 positions");
      expect(group.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByLabelText("TATAMOTORS: net qty 3")).toBeInTheDocument();

      fireEvent.click(group);
      expect(group.getAttribute("aria-expanded")).toBe("false");
      expect(screen.queryByLabelText("TATAMOTORS: net qty 3")).not.toBeInTheDocument();
    });

    it("drops symbols that net flat and says so in the total", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "RELIANCE", exchange: "NSE", product: "CNC", quantity: 80, averagePrice: 2950, ltp: 2870, pnl: -6400 },
            { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: -80, averagePrice: 2960, ltp: 2870, pnl: 7200 },
            { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
          ],
        }),
      );
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
      // The whole book's P&L still counts the flat legs — the label says so
      // rather than letting the footer disagree with the header.
      expect(screen.getByText(/incl. 2 flat legs/i)).toBeInTheDocument();
    });

    it("renders live positions, never the Explore sample, when a broker is connected", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getAllByText("TATAMOTORS").length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText("NIFTY24APR22500CE")).toBeNull();
      expect(screen.queryByText("Sample")).toBeNull();
    });

    it("shows the empty state when connected with no positions", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByText("No open positions")).toBeInTheDocument();
    });
  });

  // ── Heat view (absorbed from the retired Position Heat Map widget) ───────

  describe("heat view", () => {
    const MOCK_POSITIONS = [
      { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
      { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
    ];

    it("renders cells rather than the empty state, and counts them in the header", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
        expect(screen.getByText("Positions (2)")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^INFY:/ })).toBeInTheDocument();
      });
    });

    it("renders the group-mode selector", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      render(<PositionsWidget {...viewProps("heat")} />);

      expect(screen.getByRole("combobox", { name: /group heat map by/i })).toBeInTheDocument();
    });

    it("clicking a position cell opens a chart via flinttrade:addWidget (not a dead no-op)", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      const events: CustomEvent[] = [];
      const handler = (e: Event) => events.push(e as CustomEvent);
      window.addEventListener("flinttrade:addWidget", handler);
      try {
        withMeasuredContainer(() => {
          render(<PositionsWidget {...viewProps("heat")} />);
          // Cells are role="button" with the symbol in the aria-label.
          fireEvent.click(screen.getByRole("button", { name: /^INFY:/ }));
        });
        expect(events).toHaveLength(1);
        expect(events[0].detail).toMatchObject({
          widgetId: "chart",
          props: { symbol: "INFY", exchange: "NSE" },
        });
      } finally {
        window.removeEventListener("flinttrade:addWidget", handler);
      }
    });

    it("labels a cell with the shared mark-to-market, not the broker P&L field", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        // (1510 − 1480) × 100 = +3,000 and (3820 − 3900) × 50 = −4,000.
        expect(screen.getByRole("button", { name: "INFY: +₹3,000 (+2.00%)" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "TCS: -₹4,000 (-2.10%)" })).toBeInTheDocument();
      });
      // Header total agrees with the cells: 3,000 − 4,000 = −1,000.
      expect(screen.getByText("P&L: -₹1,000")).toBeInTheDocument();
    });

    it("shows the Explore sample and its watermark without a broker", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        expect(screen.getByText(/Sample data — connect a broker/i)).toBeInTheDocument();
        expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
      });
    });
  });
});

// ---------------------------------------------------------------------------
// positionBook kernel — the reconciled definitions
// ---------------------------------------------------------------------------

describe("positionBook", () => {
  it("derives the underlying from the symbol root, spaced or not", () => {
    expect(underlyingOf("NIFTY 22200 CE 10APR")).toBe("NIFTY");
    expect(underlyingOf("BANKNIFTY FUT 24APR")).toBe("BANKNIFTY");
    // A real broker symbol has no spaces — the retired widget's whitespace
    // split made live grouping a no-op.
    expect(underlyingOf("NIFTY24APR22500CE")).toBe("NIFTY");
    expect(underlyingOf("RELIANCE")).toBe("RELIANCE");
  });

  it("classifies a position's sector from lib/sectors.ts, derivatives included", () => {
    const [option, stock] = normalisePositions([
      { symbol: "NIFTY24APR22500CE", quantity: 75, ltp: 235, average_price: 180 },
      { symbol: "SBIN", quantity: 10, ltp: 832, average_price: 810 },
    ]);
    expect(option.sector).toBe("Other"); // index options are not a stock sector
    expect(stock.sector).toBe("Banking");
  });

  it("computes exposure at the mark, falling back to entry when LTP is unusable", () => {
    // |qty| × ltp — what the position is worth now, not what it cost.
    expect(positionExposure(2, 22450, 22400)).toBe(2 * 22450);
    // Short positions carry exposure too.
    expect(positionExposure(-2, 22450, 22400)).toBe(2 * 22450);
    // A broker that reports ltp 0 on an open position must not report zero risk.
    expect(positionExposure(2, 0, 22400)).toBe(2 * 22400);
  });

  it("marks each row to market once, with the broker figure as the fallback", () => {
    const [marked, unpriced] = normalisePositions([
      { symbol: "TCS", quantity: 10, ltp: 3050, average_price: 3000, pnl: 400 },
      { symbol: "NIFTY24APR22500CE", quantity: 75, ltp: 0, average_price: 180, pnl: 640 },
    ]);
    // The recomputation Net Position performed — minus its always-1 lot factor.
    expect(marked.mtm).toBe((3050 - 3000) * 10);
    expect(unpriced.mtm).toBe(640);
  });

  it("nets long and short of the same symbol across products", () => {
    const rows = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", exchange: "NFO", product: "NRML", quantity: 2, average_price: 22400, ltp: 22450 },
        { symbol: "NIFTY FUT", exchange: "NFO", product: "MIS", quantity: -1, average_price: 22400, ltp: 22450 },
      ]),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].netQty).toBe(1);
    expect(rows[0].legs).toBe(2);
  });

  it("excludes flat positions (net qty = 0)", () => {
    const rows = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", quantity: 1, average_price: 22400, ltp: 22400 },
        { symbol: "NIFTY FUT", quantity: -1, average_price: 22400, ltp: 22400 },
      ]),
    );
    expect(rows).toHaveLength(0);
  });

  it("nets P&L as the sum of the rows' mark-to-market, so views cannot disagree", () => {
    const normalised = normalisePositions([
      { symbol: "NIFTY FUT", quantity: 2, average_price: 22400, ltp: 22500, pnl: 1 },
      { symbol: "NIFTY FUT", quantity: -1, average_price: 22400, ltp: 22500, pnl: 2 },
    ]);
    const [net] = netPositions(normalised);
    expect(net.mtm).toBe(normalised.reduce((sum, row) => sum + row.mtm, 0));
    expect(net.mtm).toBeGreaterThan(0); // net long into a rising market
  });

  it("net-row P&L turns negative when the mark falls below a long's average", () => {
    const [net] = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", quantity: 1, average_price: 22400, ltp: 22300 },
      ]),
    );
    expect(net.mtm).toBeLessThan(0);
  });

  it("prices a net row's exposure off the net quantity", () => {
    const [net] = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", quantity: 3, average_price: 22400, ltp: 22450 },
        { symbol: "NIFTY FUT", quantity: -1, average_price: 22400, ltp: 22450 },
      ]),
    );
    // Net 2 lots at the mark — NOT the gross 4, and not the entry price.
    expect(net.exposure).toBe(2 * 22450);
  });

  it("nets the sample book into fewer rows than it has legs", () => {
    const rows = netPositions(normalisePositions(SAMPLE_POSITION_BOOK));
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(SAMPLE_POSITION_BOOK.length);
    // The two RELIANCE legs cancel exactly.
    expect(rows.find((row) => row.symbol === "RELIANCE")).toBeUndefined();
    // The two NIFTY option legs net to +45 under the NIFTY underlying.
    const nifty = rows.find((row) => row.symbol === "NIFTY24APR22500CE");
    expect(nifty?.netQty).toBe(45);
    expect(nifty?.underlying).toBe("NIFTY");
  });
});
