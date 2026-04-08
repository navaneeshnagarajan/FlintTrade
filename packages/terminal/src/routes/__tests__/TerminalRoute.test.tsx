/**
 * TerminalRoute.test.tsx
 *
 * Smoke tests for the /trade workspace route.
 * Mocks dockview-react (canvas-based, not JSDOM-compatible), resizable panels,
 * chrome components, and all stores/hooks.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
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

// Child route components
vi.mock("@/routes/trade/TradeSidebar", () => ({
  TradeSidebar: () => <nav data-testid="trade-sidebar">Sidebar</nav>,
}));

vi.mock("@/routes/trade/TradeBottomPanel", () => ({
  TradeBottomPanel: () => <div data-testid="trade-bottom-panel">Bottom</div>,
}));

// Stores
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: Object.assign(
    vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        setDockviewApi: vi.fn(),
        dockviewApi: null,
        widgetPickerOpen: false,
        setWidgetPickerOpen: vi.fn(),
        presetPickerOpen: false,
        setPresetPickerOpen: vi.fn(),
        activeTabId: "default",
        getTabLayout: () => null,
        saveTabLayout: vi.fn(),
      }),
    ),
    { getState: () => ({ activeTabId: "default", getTabLayout: () => null, saveTabLayout: vi.fn(), dockviewApi: null, setDockviewApi: vi.fn() }), setState: vi.fn() },
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ getResolvedMode: () => "dark" }),
  ),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ totalPnl: 0 }),
  ),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ riskLimits: { mtmStoploss: 5000 } }),
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
  widgetComponents: {},
}));

vi.mock("@/layout/workspacePresets", () => ({
  applyPreset: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import TerminalRoute from "../TerminalRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TerminalRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing and shows the sr-only heading", () => {
    render(<TerminalRoute />);

    expect(screen.getByText("Trade Workspace")).toBeInTheDocument();
  });

  it("renders resizable panel structure with separators", () => {
    render(<TerminalRoute />);

    // Resizable groups and separators should be present
    expect(screen.getAllByRole("separator").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("trade-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("trade-bottom-panel")).toBeInTheDocument();
  });

  it("renders the tool overlay containers (widget picker and preset picker)", () => {
    render(<TerminalRoute />);

    expect(screen.getByTestId("widget-picker")).toBeInTheDocument();
    expect(screen.getByTestId("preset-picker")).toBeInTheDocument();
  });
});
