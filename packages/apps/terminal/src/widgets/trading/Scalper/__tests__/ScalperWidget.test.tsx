/**
 * ScalperWidget.test.tsx
 *
 * Tests for the Scalper trading widget.
 * Verifies rendering, CE/PE sections, quantity controls, runtime lot-size
 * resolution (symbol master → resolver route → fail closed), and the
 * optional SL/Target bracket legs through the gated bracket endpoint.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { createStore, Provider } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { broadcastInstrument, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { EXPLORE_SCALPER_ORDER_HELPER } from "../exploreGate";
import WatchlistWidget from "@/widgets/utility/Watchlist/WatchlistWidget";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockModeStore = vi.hoisted(() => vi.fn());
const mockPlaceOrder = vi.hoisted(() => vi.fn());
const mockCancelAllOrders = vi.hoisted(() => vi.fn());
const mockExitAllPositions = vi.hoisted(() => vi.fn());
const mockGetExpiry = vi.hoisted(() => vi.fn());
const mockGetQuotes = vi.hoisted(() => vi.fn());
const mockGetSymbol = vi.hoisted(() => vi.fn());
const mockGetLotSize = vi.hoisted(() => vi.fn());
const mockPlaceBracketOrder = vi.hoisted(() => vi.fn());
const mockCancelBracket = vi.hoisted(() => vi.fn());
/** Mutable tick map handed to the widget by the mocked useWebSocket hook. */
const mockTicks = vi.hoisted(() => ({
  current: {} as Record<string, { ltp?: number; close?: number }>,
}));

const mockGetMultiQuotes = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  placeOrder: mockPlaceOrder,
  cancelAllOrders: mockCancelAllOrders,
  exitAllPositions: mockExitAllPositions,
  getExpiry: mockGetExpiry,
  getQuotes: mockGetQuotes,
  getSymbol: mockGetSymbol,
  getMultiQuotes: mockGetMultiQuotes,
  searchSymbol: vi.fn().mockResolvedValue([]),
  normaliseMultiQuotes: () => [],
}));

vi.mock("@/services/ftApi", () => ({
  getLotSize: mockGetLotSize,
  placeBracketOrder: mockPlaceBracketOrder,
  cancelBracket: mockCancelBracket,
}));

vi.mock("@/hooks/useVoiceAlert", () => ({
  useVoiceAlert: () => ({ announceOrder: vi.fn() }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    mockModeStore(selector),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  default: () => ({ ticks: mockTicks.current }),
}));

vi.mock("@/components/Chart", () => ({
  default: () => <div data-testid="mock-chart" />,
}));

// Mock radix Select to avoid complex portal/popover rendering in JSDOM.
// Expose the current value so channel-follow tests can assert retarget.
vi.mock("@/components/ui/select", () => ({
  Select: ({ children, value }: { children: React.ReactNode; value?: string }) => (
    <div data-testid="scalper-select" data-value={value}>{children}</div>
  ),
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
  ),
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
}));

// Mock AlertDialog similarly
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogAction: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import ScalperWidget from "../ScalperWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScalperWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTicks.current = {};
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "live" }),
    );
    mockPlaceOrder.mockResolvedValue({});
    mockPlaceBracketOrder.mockResolvedValue({ message: "Bracket placed", data: null });
    mockCancelAllOrders.mockResolvedValue({});
    mockExitAllPositions.mockResolvedValue({});
    mockGetExpiry.mockResolvedValue(["2026-04-10", "2026-04-17"]);
    mockGetQuotes.mockResolvedValue({ ltp: 24000 });
    // Primary lot-size source: the broker symbol master (QuickTrade's
    // getSymbol pattern), probed with the concrete CE contract.
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY10APR2624000CE",
      name: "NIFTY",
      exchange: "NFO",
      instrumenttype: "OPTIDX",
      lotsize: 75,
      tick_size: 0.05,
    });
    // Secondary source: the backend resolver route. Sample-flagged by
    // default so tests prove the symbol master is what verifies.
    mockGetLotSize.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NFO",
      lot_size: 75,
      is_sample_data: true,
    });
    mockGetMultiQuotes.mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = render(<ScalperWidget {...defaultProps} />);
    expect(container).toBeTruthy();
  });

  it("has CE section with Buy CE and Sell CE buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Buy CE")).toBeInTheDocument();
    expect(screen.getByText("Sell CE")).toBeInTheDocument();
  });

  it("has PE section with Buy PE and Sell PE buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Buy PE")).toBeInTheDocument();
    expect(screen.getByText("Sell PE")).toBeInTheDocument();
  });

  it("has lot quantity controls with increase/decrease buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    // The Lot stepper label should be present
    expect(screen.getByText("Lot")).toBeInTheDocument();

    // Increase/decrease buttons for Lot
    expect(screen.getByLabelText("Decrease Lot")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase Lot")).toBeInTheDocument();
  });

  it("has CE Strike and PE Strike steppers", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("CE Strike")).toBeInTheDocument();
    expect(screen.getByText("PE Strike")).toBeInTheDocument();

    expect(screen.getByLabelText("Decrease CE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase CE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Decrease PE Strike")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase PE Strike")).toBeInTheDocument();
  });

  it("has Close All and Cancel All action buttons", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByText("Close All")).toBeInTheDocument();
    expect(screen.getByText("Cancel All")).toBeInTheDocument();
    expect(screen.getByText(/all pending orders for the selected broker account/i)).toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("clicking 1-CLICK button toggles it to '1-CLICK ON' state", () => {
    render(<ScalperWidget {...defaultProps} />);

    // Initial state: one-click is OFF
    const toggleBtn = screen.getByTitle(/one-click off/i);
    expect(toggleBtn).toHaveTextContent("1-CLICK");

    fireEvent.click(toggleBtn);

    // After click: one-click is ON
    expect(screen.getByTitle(/one-click on/i)).toHaveTextContent("1-CLICK ON");
  });

  it("clicking 1-CLICK ON button toggles it back to OFF", () => {
    render(<ScalperWidget {...defaultProps} />);

    const toggleBtn = screen.getByTitle(/one-click off/i);
    fireEvent.click(toggleBtn);
    expect(screen.getByTitle(/one-click on/i)).toBeInTheDocument();

    // Click again to turn off
    fireEvent.click(screen.getByTitle(/one-click on/i));
    expect(screen.getByTitle(/one-click off/i)).toBeInTheDocument();
  });

  it("clicking Increase Lot increments the lot display span", () => {
    render(<ScalperWidget {...defaultProps} />);

    // The Lot Stepper renders the value as a <span> with text like "1 (50)"
    const increaseBtn = screen.getByLabelText("Increase Lot");
    const lotSpan = increaseBtn.closest("div")?.querySelector("span.font-mono") as HTMLElement;
    // Default lots = 1
    expect(lotSpan.textContent).toContain("1");

    fireEvent.click(increaseBtn);

    // After one click lots = 2
    expect(lotSpan.textContent).toContain("2");
  });

  it("clicking Decrease Lot when at minimum (1) keeps display at 1", () => {
    render(<ScalperWidget {...defaultProps} />);

    const decreaseBtn = screen.getByLabelText("Decrease Lot");
    const lotSpan = decreaseBtn.closest("div")?.querySelector("span.font-mono") as HTMLElement;

    // Default is 1; decrease is clamped by Math.max(1, l-1)
    fireEvent.click(decreaseBtn);
    expect(lotSpan.textContent).toContain("1");
  });

  it("keeps expiry and strike controls usable in explore mode without broker expiry calls", async () => {
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "explore" }),
    );
    mockGetExpiry.mockRejectedValue(new Error("OpenAlgo unavailable"));

    render(<ScalperWidget {...defaultProps} />);

    const ceStrikeLabel = await screen.findByText("CE Strike");
    expect(ceStrikeLabel.closest("div")).toHaveTextContent(/\d{4,}/);
    expect(screen.queryByText("Failed to load")).not.toBeInTheDocument();
    expect(mockGetExpiry).not.toHaveBeenCalled();
  });

  // ── FT-TRADE-009: Explore external-action gate (Telegram Send Test class) ─

  const EXPLORE_SCALPER_HELPER = EXPLORE_SCALPER_ORDER_HELPER;
  const EXPLORE_ONE_CLICK_TITLE = "One-click unavailable in Explore";

  async function renderExploreScalper(): Promise<void> {
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "explore" }),
    );
    render(<ScalperWidget {...defaultProps} />);
    await waitFor(() => {
      expect(screen.getByText("Buy CE").closest("button")).not.toBeNull();
    });
  }

  it("never opens Confirm Order from Buy CE / Sell in Explore", async () => {
    await renderExploreScalper();

    fireEvent.click(screen.getByText("Buy CE"));
    fireEvent.click(screen.getByText("Sell CE"));
    fireEvent.click(screen.getByText("Buy PE"));
    fireEvent.click(screen.getByText("Sell PE"));

    expect(screen.queryByText("Confirm Order")).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm BUY")).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm SELL")).not.toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(mockPlaceBracketOrder).not.toHaveBeenCalled();
  });

  it("shows the locked Explore helper and keeps Buy/Sell disarmed", async () => {
    await renderExploreScalper();

    expect(screen.getByText(EXPLORE_SCALPER_HELPER)).toBeInTheDocument();
    expect(screen.getByText("Buy CE").closest("button")).toBeDisabled();
    expect(screen.getByText("Sell CE").closest("button")).toBeDisabled();
    expect(screen.getByText("Buy PE").closest("button")).toBeDisabled();
    expect(screen.getByText("Sell PE").closest("button")).toBeDisabled();
  });

  it("keeps 1-CLICK OFF, disabled, and titled exactly in Explore", async () => {
    await renderExploreScalper();

    const toggleBtn = screen.getByRole("button", { name: /1-CLICK/ });
    expect(toggleBtn).toHaveTextContent("1-CLICK");
    expect(toggleBtn).toBeDisabled();
    expect(toggleBtn).toHaveAttribute("title", EXPLORE_ONE_CLICK_TITLE);

    fireEvent.click(toggleBtn);
    expect(toggleBtn).toHaveTextContent("1-CLICK");
    expect(screen.queryByText("1-CLICK ON")).not.toBeInTheDocument();
    expect(screen.queryByTitle(/one-click on/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm Order")).not.toBeInTheDocument();
  });

  it("still opens Confirm Order in Practice when the mode allows it", async () => {
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "practice" }),
    );
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    await waitFor(() => {
      const btn = screen.getByText("Buy CE").closest("button") as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
    fireEvent.click(screen.getByText("Buy CE"));

    expect(await screen.findByText("Confirm Order")).toBeInTheDocument();
    expect(screen.getByText("Confirm BUY")).toBeInTheDocument();
    expect(screen.queryByText(EXPLORE_SCALPER_HELPER)).not.toBeInTheDocument();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  // ── Order safety tests ─────────────────────────────────────────────────────

  /** Wait for the CE contract to resolve, click Buy CE, confirm the modal. */
  async function buyCeWithConfirm(): Promise<void> {
    await waitFor(() => {
      const btn = screen.getByText("Buy CE").closest("button") as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
    fireEvent.click(screen.getByText("Buy CE"));
    fireEvent.click(await screen.findByText("Confirm BUY"));
  }

  it("renders the SL/Target points inputs (wired to the gated bracket route)", () => {
    render(<ScalperWidget {...defaultProps} />);

    expect(screen.getByLabelText("Stop-loss points")).toBeInTheDocument();
    expect(screen.getByLabelText("Target points")).toBeInTheDocument();
  });

  // ── Lot-size resolution (fetch → fallback → fail closed) ─────────────────

  it("sizes the order from the symbol master (getSymbol) — the QuickTrade pattern", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY10APR2624000CE",
      name: "NIFTY",
      exchange: "NFO",
      instrumenttype: "OPTIDX",
      lotsize: 99,
      tick_size: 0.05,
    });
    render(<ScalperWidget {...defaultProps} />);

    // Sublabel confirms the dynamic lot size arrived (not the built-in 75)
    await screen.findByText("×99");
    expect(mockGetSymbol).toHaveBeenCalledWith(expect.stringMatching(/CE$/), "NFO");

    await buyCeWithConfirm();

    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ action: "BUY", quantity: 99, price: 0, orderType: "MARKET" }),
      );
    });
  });

  it("falls back to the resolver route when it is NOT sample-flagged", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol master unavailable"));
    mockGetLotSize.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NFO",
      lot_size: 80,
      is_sample_data: false,
    });
    render(<ScalperWidget {...defaultProps} />);

    await screen.findByText("×80");

    await buyCeWithConfirm();

    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ action: "BUY", quantity: 80 }),
      );
    });
  });

  it("treats a sample-flagged resolver lot size as unverified and fails closed", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol master unavailable"));
    // Default mockGetLotSize is sample-flagged 75 — display only.
    render(<ScalperWidget {...defaultProps} />);

    await screen.findByText("×75 (unverified)");

    await buyCeWithConfirm();

    await screen.findByText(/Lot size not confirmed from the backend yet/);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    expect(mockPlaceBracketOrder).not.toHaveBeenCalled();
  });

  it("fails closed when no backend source confirms the lot size", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol master unavailable"));
    mockGetLotSize.mockRejectedValue(new Error("backend down"));
    render(<ScalperWidget {...defaultProps} />);

    // Falls back to the built-in table for DISPLAY only, marked unverified
    await screen.findByText("×75 (unverified)");

    await buyCeWithConfirm();

    await screen.findByText(/Lot size not confirmed from the backend yet/);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("blocks a LIMIT order without a limit price instead of sending ₹0", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    // Switch to LIMIT — the price input appears; leave it empty
    fireEvent.click(screen.getByText("LIMIT"));
    expect(screen.getByText("Limit ₹")).toBeInTheDocument();

    await buyCeWithConfirm();

    await screen.findByText(/price above zero before placing a LIMIT order/);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("sends the entered limit price with a LIMIT order", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });

    await buyCeWithConfirm();

    await waitFor(() => {
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({ orderType: "LIMIT", price: 185.5, quantity: 75 }),
      );
    });
  });

  it("reports 'placed' — never 'filled' — after placeOrder resolves", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    await buyCeWithConfirm();

    await screen.findByText(/placed$/);
    expect(screen.queryByText(/filled/)).not.toBeInTheDocument();
  });

  // ── SL/Target bracket legs (gated bracket endpoint) ───────────────────────

  it("keeps the plain gated order path when SL/Target are blank", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    await buyCeWithConfirm();

    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceBracketOrder).not.toHaveBeenCalled();
  });

  it("places a bracket with an SL leg anchored to the LIMIT price", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await waitFor(() => {
      expect(mockPlaceBracketOrder).toHaveBeenCalledWith({
        entry: expect.objectContaining({
          exchange: "NFO",
          action: "BUY",
          quantity: 75,
          price: 185.5,
          product: "MIS",
          strategy: "FlintScalper",
        }),
        stoploss: 165.5,
      });
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("places a bracket with a target leg (and no stoploss key)", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Target points"), { target: { value: "10" } });

    await buyCeWithConfirm();

    await waitFor(() => expect(mockPlaceBracketOrder).toHaveBeenCalledTimes(1));
    const arg = mockPlaceBracketOrder.mock.calls[0][0] as Record<string, unknown>;
    expect(arg.target).toBe(195.5);
    expect(arg).not.toHaveProperty("stoploss");
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("anchors a MARKET bracket to the option's live LTP", async () => {
    // Every tick key answers with ₹200 — the CE contract included.
    mockTicks.current = new Proxy(
      {},
      { get: () => ({ ltp: 200, close: 200 }) },
    ) as Record<string, { ltp?: number; close?: number }>;
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await waitFor(() => {
      expect(mockPlaceBracketOrder).toHaveBeenCalledWith(
        expect.objectContaining({ stoploss: 180 }),
      );
    });
    const arg = mockPlaceBracketOrder.mock.calls[0][0] as { entry: { price: number } };
    expect(arg.entry.price).toBe(0); // MARKET entry
  });

  it("fails closed on a MARKET bracket when no live price is available", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await screen.findByText(/Live price unavailable to anchor SL\/Target/);
    expect(mockPlaceBracketOrder).not.toHaveBeenCalled();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("refuses SL and Target together (no OCO fill monitor) without sending", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("Target points"), { target: { value: "10" } });

    await buyCeWithConfirm();

    await screen.findByText(/SL and Target together are not supported yet — enter exactly one/);
    expect(mockPlaceBracketOrder).not.toHaveBeenCalled();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("reports a bracket as PLACED (legs pending) — never as filled", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await screen.findByText(/bracket placed — legs pending, not filled/);
  });

  it("surfaces the backend Practice-mode refusal and points to Live mode", async () => {
    mockPlaceBracketOrder.mockRejectedValue(
      Object.assign(
        new Error(
          "Advanced orders (basket, split, options-strategy, bracket) are not yet "
            + "available in Practice mode. Switch to Live with PIN verified, or use "
            + "single-leg orders which support practice.",
        ),
        { code: "practice_unsupported" },
      ),
    );
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await screen.findByText(/not yet available in Practice mode.*brackets need Live mode/);
  });

  it("surfaces other backend bracket errors verbatim", async () => {
    mockPlaceBracketOrder.mockRejectedValue(
      Object.assign(new Error("Safety layer L1 rejected the entry leg"), { code: "" }),
    );
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    await screen.findByText("Safety layer L1 rejected the entry leg");
  });

  it("pins a persistent unprotected-position banner and cancels the partial bracket", async () => {
    // Entry leg live, exit leg rejected → HTTP 422 partial: the position is NAKED.
    mockPlaceBracketOrder.mockRejectedValue(
      Object.assign(new Error("Entry leg placed but the protective exit leg failed"), {
        code: "",
        data: { bracket_id: "brk-77", symbol: "NIFTY24APR24000CE", action: "BUY", quantity: 75, status: "partial" },
      }),
    );
    mockCancelBracket.mockResolvedValue({ message: "Bracket cancelled", warnings: [] });
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.click(screen.getByText("LIMIT"));
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "185.5" } });
    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await buyCeWithConfirm();

    // Persistent alert (role="alert"), the bracket id, and a real cancel action.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Position unprotected");
    expect(alert).toHaveTextContent("brk-77");

    fireEvent.click(screen.getByRole("button", { name: "Cancel bracket" }));
    await waitFor(() => expect(mockCancelBracket).toHaveBeenCalledWith("brk-77"));
    await waitFor(() => expect(screen.queryByText("Position unprotected")).not.toBeInTheDocument());
  });

  it("shows the SL leg in the confirm modal before placing", async () => {
    render(<ScalperWidget {...defaultProps} />);
    await screen.findByText("×75");

    fireEvent.change(screen.getByLabelText("Stop-loss points"), { target: { value: "20" } });

    await waitFor(() => {
      const btn = screen.getByText("Buy CE").closest("button") as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
    fireEvent.click(screen.getByText("Buy CE"));

    await screen.findByText("SL (bracket leg)");
    expect(screen.getByText("20 pts")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// FT-TRADE-011: shared symbol bus (FDC3 red channel / selectedSymbolAtom)
// ---------------------------------------------------------------------------

function scalperIndexValue(): string | null {
  return screen.getByTestId("scalper-index").getAttribute("data-symbol");
}

function renderScalperOnBus(
  store = createStore(),
  props: ReturnType<typeof makeWidgetPanelProps> = makeWidgetPanelProps(),
) {
  const view = render(
    <Provider store={store}>
      <ScalperWidget {...props} />
    </Provider>,
  );
  return { ...view, store };
}

describe("ScalperWidget — FT-TRADE-011 shared symbol bus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTicks.current = {};
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "live" }),
    );
    mockGetExpiry.mockResolvedValue(["2026-04-10", "2026-04-17"]);
    mockGetQuotes.mockResolvedValue({ ltp: 24000 });
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY10APR2624000CE",
      name: "NIFTY",
      exchange: "NFO",
      instrumenttype: "OPTIDX",
      lotsize: 75,
      tick_size: 0.05,
    });
    mockGetLotSize.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NFO",
      lot_size: 75,
      is_sample_data: true,
    });
    mockGetMultiQuotes.mockResolvedValue([]);
    localStorage.removeItem("flinttrade:watchlists");
    localStorage.removeItem("flinttrade:watchlist");
    localStorage.removeItem("flinttrade:watchlist:view");
  });

  it("follows a watchlist selection written to selectedSymbolAtom", async () => {
    const { store } = renderScalperOnBus();
    expect(scalperIndexValue()).toBe("NIFTY");

    act(() => {
      store.set(selectedSymbolAtom, { symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
    });

    await waitFor(() => expect(scalperIndexValue()).toBe("BANKNIFTY"));
    expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
  });

  it("follows a Watchlist row click onto the real Scalper widget", async () => {
    const store = createStore();
    localStorage.setItem(
      "flinttrade:watchlists",
      JSON.stringify([
        {
          id: "t1",
          name: "Watchlist 1",
          symbols: [
            { symbol: "NIFTY", exchange: "NSE_INDEX" },
            { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
          ],
        },
      ]),
    );

    render(
      <Provider store={store}>
        <WatchlistWidget
          {...makeWidgetPanelProps({
            api: { id: "watchlist-panel", updateParameters: () => undefined },
          })}
        />
        <ScalperWidget
          {...makeWidgetPanelProps({
            api: { id: "scalper-panel", updateParameters: () => undefined },
          })}
        />
      </Provider>,
    );

    expect(scalperIndexValue()).toBe("NIFTY");
    expect(store.get(selectedSymbolAtom)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "BANKNIFTY" }));

    await waitFor(() => expect(scalperIndexValue()).toBe("BANKNIFTY"));
    expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
  });

  it("follows a Watchlist selection on the shared red channel", async () => {
    const { store } = renderScalperOnBus();
    expect(scalperIndexValue()).toBe("NIFTY");

    act(() => {
      broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
    });

    await waitFor(() => expect(scalperIndexValue()).toBe("BANKNIFTY"));
    expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
  });

  it("does not silently retarget when the shared bus is empty", async () => {
    const store = createStore();
    expect(store.get(selectedSymbolAtom)).toBeNull();
    renderScalperOnBus(store);
    expect(scalperIndexValue()).toBe("NIFTY");
    await waitFor(() => expect(store.get(selectedSymbolAtom)).toBeNull());
    expect(scalperIndexValue()).toBe("NIFTY");
  });

  it("keeps the current index when the broadcast is not a Scalper underlying", async () => {
    const { store } = renderScalperOnBus();
    act(() => {
      store.set(selectedSymbolAtom, { symbol: "RELIANCE", exchange: "NSE" });
    });
    await waitFor(() => {
      expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "RELIANCE", exchange: "NSE" });
    });
    expect(scalperIndexValue()).toBe("NIFTY");
  });

  it("ignores the bus when joined to no channel", async () => {
    const { store } = renderScalperOnBus(
      createStore(),
      makeWidgetPanelProps({ params: { channel: "none" } }),
    );
    act(() => {
      broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
    });
    await waitFor(() => {
      expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "BANKNIFTY", exchange: "NSE_INDEX" });
    });
    expect(scalperIndexValue()).toBe("NIFTY");
  });

  it("keeps Explore Sample labels after a retarget", async () => {
    mockModeStore.mockImplementation((selector: (s: { mode: string }) => unknown) =>
      selector({ mode: "explore" }),
    );
    const { store } = renderScalperOnBus();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.getByText(EXPLORE_SCALPER_ORDER_HELPER)).toBeInTheDocument();

    act(() => {
      broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "SENSEX", exchange: "BSE_INDEX" });
    });

    await waitFor(() => expect(scalperIndexValue()).toBe("SENSEX"));
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.getByText(EXPLORE_SCALPER_ORDER_HELPER)).toBeInTheDocument();
    expect(screen.getByText("Buy CE").closest("button")).toBeDisabled();
  });
});
