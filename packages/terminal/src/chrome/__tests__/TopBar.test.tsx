/**
 * TopBar.test.tsx
 *
 * Tests for the TopBar chrome component — route tabs, market status,
 * IST clock, connection status, and mode indicator.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock framer-motion to avoid animation issues in tests
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => <div {...props}>{children as React.ReactNode}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock child components that have their own complex dependencies
vi.mock("../AccountSwitcher", () => ({
  default: () => <div data-testid="account-switcher" />,
}));

vi.mock("../ModeIndicator", () => ({
  default: () => <div data-testid="mode-indicator">EXPLORE</div>,
}));

vi.mock("../QuickAccessPanel", () => ({
  default: () => null,
}));

vi.mock("../ToolsDropdown", () => ({
  default: () => null,
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => <svg data-testid="logo-icon" width={size} height={size} />,
}));

// Mock stores
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      status: "disconnected",
      setStatus: vi.fn(),
    }),
  ),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      totalPnl: 0,
      positionCount: 0,
    }),
  ),
}));

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      tabs: [{ id: "default", name: "Default" }],
      activeTabId: "default",
      toolsMenuOpen: false,
      setActiveTab: vi.fn(),
      addTab: vi.fn(),
      removeTab: vi.fn(),
      renameTab: vi.fn(),
      saveTabLayout: vi.fn(),
      getTabLayout: vi.fn(),
      setWidgetPickerOpen: vi.fn(),
      setToolsMenuOpen: vi.fn(),
      setPresetPickerOpen: vi.fn(),
    }),
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      glass: false,
      mode: "dark",
      setMode: vi.fn(),
      getResolvedMode: () => "dark",
    }),
  ),
}));

vi.mock("@/hooks/useMarketStatus", () => ({
  useTimings: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
}));

vi.mock("@/hooks/useSkillLevel", () => ({
  useSkillLevel: vi.fn().mockReturnValue("intermediate"),
}));

vi.mock("@/services/api", () => ({
  ping: vi.fn().mockRejectedValue(new Error("not connected")),
}));

vi.mock("@/services/ftApi", () => ({
  getPendingOrders: vi.fn().mockResolvedValue([]),
}));

import TopBar from "../TopBar";

function renderTopBar(initialPath = "/trade") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <TopBar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TopBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = renderTopBar();
    expect(container).toBeTruthy();
  });

  it("shows route navigation tabs", () => {
    renderTopBar();

    expect(screen.getByText("Learn")).toBeInTheDocument();
    expect(screen.getByText("Invest")).toBeInTheDocument();
    expect(screen.getByText("Trade")).toBeInTheDocument();
    expect(screen.getByText("Lab")).toBeInTheDocument();
    expect(screen.getByText("Automate")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
  });

  it("shows the main navigation landmark", () => {
    renderTopBar();

    const nav = screen.getByLabelText("Main navigation");
    expect(nav).toBeInTheDocument();
  });

  it("shows market status indicator", () => {
    renderTopBar();

    // MarketStatusBadge renders with aria-label "Market status: ..."
    expect(screen.getByLabelText(/market status/i)).toBeInTheDocument();
  });

  it("shows IST clock", () => {
    renderTopBar();

    expect(screen.getByLabelText("Current time in IST")).toBeInTheDocument();
    expect(screen.getByText(/IST$/)).toBeInTheDocument();
  });

  it("shows the FlintTrade logo", () => {
    renderTopBar();

    expect(screen.getByTestId("logo-icon")).toBeInTheDocument();
    expect(screen.getByLabelText("FlintTrade home")).toBeInTheDocument();
  });

  it("shows the TOOLS button", () => {
    renderTopBar();

    expect(screen.getByText("TOOLS")).toBeInTheDocument();
  });
});
