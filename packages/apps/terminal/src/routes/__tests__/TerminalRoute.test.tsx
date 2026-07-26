/**
 * TerminalRoute.test.tsx
 *
 * Smoke tests for the /trade workspace route.
 * Mocks dockview-react (canvas-based, not JSDOM-compatible), resizable panels,
 * chrome components, and all stores/hooks.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockTradingState = vi.hoisted(() => ({
  totalPnl: 0,
  mtmStoploss: 5000,
  mode: "live",
}));

const mockLayoutState = vi.hoisted(() => {
  const state = {
    setDockviewApi: vi.fn(),
    dockviewApi: null as Record<string, unknown> | null,
    widgetPickerOpen: false,
    setWidgetPickerOpen: vi.fn(),
    presetPickerOpen: false,
    setPresetPickerOpen: vi.fn(),
    activeTabId: "default",
    getTabLayout: vi.fn(() => null),
    saveTabLayout: vi.fn(),
  };
  state.setDockviewApi = vi.fn((api: Record<string, unknown> | null) => {
    state.dockviewApi = api;
  });
  return state;
});

const mockDockviewState = vi.hoisted(() => ({
  api: null as {
    panels: unknown[];
    addPanel: ReturnType<typeof vi.fn>;
    fromJSON: ReturnType<typeof vi.fn>;
    toJSON: ReturnType<typeof vi.fn>;
    onDidAddPanel: ReturnType<typeof vi.fn>;
    onDidRemovePanel: ReturnType<typeof vi.fn>;
    onDidActivePanelChange: ReturnType<typeof vi.fn>;
    onDidLayoutChange: ReturnType<typeof vi.fn>;
  } | null,
}));

const mockNavigate = vi.fn();
const mockGetSafetyConfig = vi.hoisted(() => vi.fn());
const mockActivateKillSwitch = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: () => mockGetSafetyConfig(),
  activateKillSwitch: (reason: string) => mockActivateKillSwitch(reason),
}));

// Dockview — canvas-based, must be fully mocked
vi.mock("dockview-react", () => ({
  DockviewReact: ({ onReady }: { onReady: (event: unknown) => void }) => {
    // Fire onReady synchronously with a minimal stub API
    const fakeApi = {
      panels: [],
      addPanel: vi.fn(),
      fromJSON: vi.fn(),
      toJSON: vi.fn().mockReturnValue({}),
      onDidAddPanel: vi.fn().mockReturnValue({ dispose: vi.fn() }),
      onDidRemovePanel: vi.fn().mockReturnValue({ dispose: vi.fn() }),
      onDidActivePanelChange: vi.fn().mockReturnValue({ dispose: vi.fn() }),
      onDidLayoutChange: vi.fn().mockReturnValue({ dispose: vi.fn() }),
    };
    mockDockviewState.api = fakeApi;
    // Schedule onReady in a microtask so the component mounts first
    Promise.resolve().then(() => onReady({ api: fakeApi }));
    return <div data-testid="dockview-canvas" />;
  },
}));

// Resizable panels
vi.mock("react-resizable-panels", () => ({
  Group: ({ children, ...props }: Record<string, unknown>) => (
    <div data-testid="resizable-group" {...props}>{children as React.ReactNode}</div>
  ),
  Panel: ({ children, id }: { children: React.ReactNode; id?: string }) => (
    <div data-testid={`panel-${id ?? "unknown"}`}>{children}</div>
  ),
  Separator: ({ id }: { id?: string }) => (
    <div data-testid={`separator-${id ?? "unknown"}`} role="separator" />
  ),
  useDefaultLayout: () => ({ defaultLayout: undefined, onLayoutChanged: vi.fn() }),
  usePanelRef: () => ({ current: null }),
}));

// Layout components
vi.mock("@/components/layout/CinematicLayout", () => ({
  CinematicLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/layout/SectionHeader", () => ({
  SectionHeader: ({ title }: { title: string }) => <h3>{title}</h3>,
}));

// Chrome components
vi.mock("@/chrome/WidgetPicker", () => ({
  default: () => <div data-testid="widget-picker" />,
}));

vi.mock("@/chrome/PresetPicker", () => ({
  default: () => <div data-testid="preset-picker" />,
}));

vi.mock("@/routes/trade/TradeBottomPanel", () => ({
  TradeBottomPanel: () => <div data-testid="trade-bottom-panel">Bottom</div>,
}));

// Stores
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: Object.assign(
    vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
      selector(mockLayoutState),
    ),
    { getState: () => mockLayoutState, setState: vi.fn() },
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      getResolvedMode: () => "dark",
      setTheme: vi.fn(),
      setMode: vi.fn(),
      mode: "dark",
    }),
  ),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ totalPnl: mockTradingState.totalPnl }),
  ),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ riskLimits: { mtmStoploss: mockTradingState.mtmStoploss } }),
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ mode: mockTradingState.mode }),
  ),
}));

// Hooks
vi.mock("@/hooks/useGlobalKeys", () => ({
  default: vi.fn(),
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: vi.fn().mockReturnValue("intermediate"),
}));

vi.mock("@/hooks/useDockviewTheme", () => ({
  useDockviewTheme: vi.fn().mockReturnValue({}),
}));

// Tour
vi.mock("@/components/help/SpotlightTour", () => ({
  SpotlightTour: () => null,
}));

vi.mock("@/lib/tourDefinitions", () => ({
  TOUR_DEFINITIONS: {},
}));

// Widget factory
vi.mock("@/layout/widgetFactory", () => ({
  widgetComponents: {
    chart: () => <div data-testid="compact-widget-chart">Chart widget</div>,
    threepanel: () => <div>Three-Panel Chart widget</div>,
    watchlist: () => <div data-testid="compact-widget-watchlist">Watchlist widget</div>,
    orderpad: () => <div data-testid="compact-widget-orderpad">Order Pad widget</div>,
    positions: () => <div data-testid="compact-widget-positions">Positions widget</div>,
    indexstrip: () => <div data-testid="compact-widget-indexstrip">Index Strip widget</div>,
  },
  widgetCatalog: [
    {
      id: "threepanel",
      name: "Three-Panel Chart",
      category: "Analysis",
      description: "Three synchronised chart panels",
    },
  ],
}));

vi.mock("@/layout/workspacePresets", () => ({
  applyPreset: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import TerminalRoute from "../TerminalRoute";

const inactiveSafetyConfig = {
  check_market_hours: true,
  max_qty_nse: 1800,
  max_qty_nfo: 1800,
  max_qty_mcx: 100,
  kill_switch_active: false,
  max_positions: 10,
  max_margin_pct: 80,
  daily_loss_pause_pct: 3,
  daily_loss_kill_pct: 5,
  max_net_delta: 500,
  max_net_vega: 200,
  kill_switch_reason: "",
  flatten_complete: true,
  emergency_result: null,
};

function renderTerminalRoute({
  seedSafetyConfig = true,
}: {
  seedSafetyConfig?: boolean | typeof inactiveSafetyConfig;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (seedSafetyConfig) {
    queryClient.setQueryData(
      ["safetyConfig"],
      seedSafetyConfig === true ? { ...inactiveSafetyConfig } : seedSafetyConfig,
    );
  }

  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <TerminalRoute />
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  });
  window.dispatchEvent(new Event("resize"));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TerminalRoute", () => {
  beforeEach(() => {
    setViewportWidth(1280);
    mockTradingState.totalPnl = 0;
    mockTradingState.mtmStoploss = 5000;
    mockTradingState.mode = "live";
    mockLayoutState.dockviewApi = null;
    mockLayoutState.widgetPickerOpen = false;
    mockLayoutState.presetPickerOpen = false;
    mockLayoutState.getTabLayout.mockReturnValue(null);
    mockDockviewState.api = null;
    vi.clearAllMocks();
    mockGetSafetyConfig.mockReset().mockResolvedValue({ ...inactiveSafetyConfig });
    mockActivateKillSwitch.mockReset();
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders without crashing and shows the sr-only heading", () => {
    renderTerminalRoute();

    expect(screen.getByText("Trade Workspace")).toBeInTheDocument();
  });

  it("clears the mounted Dockview API when the trade route unmounts", async () => {
    const { unmount } = renderTerminalRoute();

    await waitFor(() => expect(mockLayoutState.dockviewApi).toBe(mockDockviewState.api));
    unmount();

    expect(mockLayoutState.setDockviewApi).toHaveBeenLastCalledWith(null);
    expect(mockLayoutState.dockviewApi).toBeNull();
  });

  it("renders resizable panel structure with separators", () => {
    renderTerminalRoute();

    // Resizable groups and separators should be present
    expect(screen.getAllByRole("separator").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByTestId("panel-trade-sidebar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("separator-trade-sep-left")).not.toBeInTheDocument();
    expect(screen.getByTestId("trade-bottom-panel")).toBeInTheDocument();
  });

  it("keeps the collapsed right order-pad panel from creating horizontal overflow", () => {
    const { container } = renderTerminalRoute();

    const shell = container.querySelector("[data-testid='trade-right-panel-shell']");

    expect(shell).toHaveClass("w-full", "min-w-0", "overflow-x-hidden");
    expect(shell).toHaveClass("box-border");
  });

  it("keeps the kill switch in reserved trade-route layout space", () => {
    mockTradingState.totalPnl = -3000;

    renderTerminalRoute();

    const alert = screen.getByRole("status", { name: /daily loss alert/i });
    expect(alert).toHaveClass("shrink-0");
    expect(alert).not.toHaveClass("fixed");
    expect(alert).not.toHaveClass("absolute");
  });

  it("keeps emergency activation disabled until authoritative safety state loads", async () => {
    mockTradingState.totalPnl = -3000;
    let resolveSafetyConfig: ((value: typeof inactiveSafetyConfig) => void) | undefined;
    mockGetSafetyConfig.mockReturnValueOnce(new Promise((resolve) => {
      resolveSafetyConfig = resolve;
    }));

    renderTerminalRoute({ seedSafetyConfig: false });

    const button = screen.getByRole("button", { name: /activate emergency kill switch/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(mockActivateKillSwitch).not.toHaveBeenCalled();

    resolveSafetyConfig?.({ ...inactiveSafetyConfig });
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("keeps emergency activation available on a failed refresh with last-known state", async () => {
    mockTradingState.totalPnl = -3000;
    mockGetSafetyConfig.mockRejectedValueOnce(new Error("transient refresh failure"));

    renderTerminalRoute({ seedSafetyConfig: { ...inactiveSafetyConfig } });

    await screen.findByText(/last known state; latest refresh failed/i);
    const button = screen.getByRole("button", { name: /activate emergency kill switch/i });
    expect(button).toBeEnabled();
  });

  it("keeps an active L5 kill switch visible below the local MTM warning threshold", () => {
    mockTradingState.totalPnl = 0;

    renderTerminalRoute({
      seedSafetyConfig: {
        ...inactiveSafetyConfig,
        kill_switch_active: true,
        kill_switch_reason: "operator request",
        flatten_complete: true,
      },
    });

    expect(screen.getByRole("status", { name: /kill switch status: active/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /kill switch is active/i })).toHaveTextContent("Kill Active");
  });

  it("renders an explicit loading state instead of inactive before L5 loads", () => {
    mockGetSafetyConfig.mockReturnValueOnce(new Promise(() => undefined));

    renderTerminalRoute({ seedSafetyConfig: false });

    expect(screen.getByRole("status", { name: /kill switch status: loading/i })).toBeInTheDocument();
    expect(screen.getByText(/checking kill-switch state/i)).toBeInTheDocument();
    expect(screen.queryByText(/kill switch inactive/i)).not.toBeInTheDocument();
  });

  it("renders an unavailable state instead of inactive when the L5 read fails", async () => {
    mockGetSafetyConfig.mockRejectedValueOnce(new Error("backend unavailable"));

    renderTerminalRoute({ seedSafetyConfig: false });

    expect(await screen.findByRole("alert", { name: /kill switch status: unavailable/i }))
      .toHaveTextContent(/authoritative kill-switch state is unavailable/i);
    expect(screen.queryByText(/kill switch inactive/i)).not.toBeInTheDocument();
  });

  it("keeps a visible retry action after a partial emergency dispatch", async () => {
    mockTradingState.totalPnl = -3000;
    const partialEmergencyResult = {
      policy: "l5_emergency_flatten",
      complete: false,
      target_count: 1,
      completed_target_count: 0,
      summary: "No configured targets completed",
      targets: [{
        selector: "configured:account",
        complete: false,
        outcomes: [{
            verb: "cancel_all_orders",
            attempted: false,
            succeeded: false,
            failure_code: "router_unavailable",
        }],
      }],
      outcomes: [{
        verb: "cancel_all_orders",
        attempted: false,
        succeeded: false,
        failure_code: "router_unavailable",
      }],
    };
    mockActivateKillSwitch.mockResolvedValueOnce({
      message: "Kill switch activated, but broker actions did not complete",
      reason: "operator request",
      is_active: true,
      emergency_actions: partialEmergencyResult,
    });
    mockGetSafetyConfig.mockResolvedValueOnce({ ...inactiveSafetyConfig });
    mockGetSafetyConfig.mockResolvedValue({
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: false,
      emergency_result: partialEmergencyResult,
    });
    renderTerminalRoute();

    fireEvent.click(screen.getByRole("button", { name: /activate emergency kill switch/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /retry emergency broker actions/i }))
        .toHaveTextContent("Retry Flatten");
    });
    expect(screen.getByRole("button", { name: /retry emergency broker actions/i })).toBeEnabled();
    expect(screen.getByText(/broker flattening is incomplete/i)).toBeInTheDocument();
  });

  it("hides the kill switch in explore mode", () => {
    mockTradingState.totalPnl = -3000;
    mockTradingState.mode = "explore";

    renderTerminalRoute();

    expect(screen.queryByRole("status", { name: /daily loss alert/i })).not.toBeInTheDocument();
  });

  it("hides the kill switch in practice mode", () => {
    mockTradingState.totalPnl = -3000;
    mockTradingState.mode = "practice";

    renderTerminalRoute();

    expect(screen.queryByRole("status", { name: /daily loss alert/i })).not.toBeInTheDocument();
  });

  it("surfaces activation failures and leaves the action retryable", async () => {
    mockTradingState.totalPnl = -3000;
    mockActivateKillSwitch.mockRejectedValueOnce(new Error("backend unavailable"));
    renderTerminalRoute();

    fireEvent.click(screen.getByRole("button", { name: /activate emergency kill switch/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("backend unavailable");
    expect(screen.getByRole("button", { name: /activate emergency kill switch/i })).toBeEnabled();
  });

  it("follows the shared safety query after an external reset", async () => {
    mockTradingState.totalPnl = -3000;
    const completedEmergencyResult = {
      policy: "l5_emergency_flatten",
      complete: true,
      target_count: 1,
      completed_target_count: 1,
      summary: "All configured targets completed",
      targets: [],
      outcomes: [],
    };
    mockActivateKillSwitch.mockResolvedValueOnce({
      message: "Kill switch activated",
      reason: "operator request",
      is_active: true,
      emergency_actions: completedEmergencyResult,
    });
    mockGetSafetyConfig.mockResolvedValueOnce({ ...inactiveSafetyConfig });
    mockGetSafetyConfig.mockResolvedValue({
      ...inactiveSafetyConfig,
      kill_switch_active: true,
      kill_switch_reason: "operator request",
      flatten_complete: true,
      emergency_result: completedEmergencyResult,
    });
    const { queryClient } = renderTerminalRoute();

    fireEvent.click(screen.getByRole("button", { name: /activate emergency kill switch/i }));
    expect(await screen.findByRole("button", { name: /kill switch is active/i }))
      .toHaveTextContent("Kill Active");

    mockGetSafetyConfig.mockResolvedValue({ ...inactiveSafetyConfig });
    await queryClient.refetchQueries({ queryKey: ["safetyConfig"] });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /activate emergency kill switch/i }))
        .toHaveTextContent("Kill Switch");
    });
    expect(screen.getByRole("button", { name: /activate emergency kill switch/i })).toBeEnabled();
  });

  it("renders the tool overlay containers (widget picker and preset picker)", () => {
    renderTerminalRoute();

    expect(screen.getByTestId("widget-picker")).toBeInTheDocument();
    expect(screen.getByTestId("preset-picker")).toBeInTheDocument();
  });

  it("uses a tabbed compact workspace instead of the dockview split on narrow screens", () => {
    setViewportWidth(390);

    renderTerminalRoute();

    expect(screen.getByTestId("trade-compact-workspace")).toBeInTheDocument();
    expect(screen.queryByTestId("dockview-canvas")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("compact-widget-chart")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Order Pad" }));

    expect(screen.getByRole("tab", { name: "Order Pad" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("compact-widget-orderpad")).toBeInTheDocument();
  });

  it("offers the Index Strip (not the retired Dashboard) as the fifth compact tab", () => {
    setViewportWidth(390);
    renderTerminalRoute();

    expect(screen.queryByRole("tab", { name: "Dashboard" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Indices" }));

    expect(screen.getByRole("tab", { name: "Indices" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("compact-widget-indexstrip")).toBeInTheDocument();
  });

  it("supports arrow-key navigation across compact workspace tabs", () => {
    setViewportWidth(390);
    renderTerminalRoute();

    const chartTab = screen.getByRole("tab", { name: "Chart" });
    chartTab.focus();
    fireEvent.keyDown(chartTab, { key: "ArrowRight" });

    const watchlistTab = screen.getByRole("tab", { name: "Watchlist" });
    expect(watchlistTab).toHaveFocus();
    expect(watchlistTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("compact-widget-watchlist")).toBeInTheDocument();

    fireEvent.keyDown(watchlistTab, { key: "ArrowLeft" });
    expect(chartTab).toHaveFocus();
    expect(chartTab).toHaveAttribute("aria-selected", "true");
  });

  it("adds a widget when the command palette dispatches flinttrade:addWidget", async () => {
    renderTerminalRoute();

    await waitFor(() => expect(mockDockviewState.api).not.toBeNull());

    window.dispatchEvent(
      new CustomEvent("flinttrade:addWidget", {
        detail: { widgetId: "threepanel" },
      }),
    );

    expect(mockDockviewState.api?.addPanel).toHaveBeenCalledWith(
      expect.objectContaining({
        component: "threepanel",
        title: "Three-Panel Chart",
      }),
    );
  });
});
