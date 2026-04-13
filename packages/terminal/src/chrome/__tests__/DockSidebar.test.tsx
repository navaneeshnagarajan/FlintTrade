/**
 * DockSidebar.test.tsx
 *
 * Tests for the macOS dock-style DockSidebar component.
 * Verifies rendering of route items, active indicator, separator groups,
 * and Settings always appearing at the bottom.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// framer-motion — avoid animation issues in tests
vi.mock("framer-motion", () => ({
  motion: {
    aside: ({ children, style, ...props }: Record<string, unknown>) => (
      <aside style={style as React.CSSProperties} {...props}>{children as React.ReactNode}</aside>
    ),
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
    button: ({ children, ...props }: Record<string, unknown>) => (
      <button {...props}>{children as React.ReactNode}</button>
    ),
    span: ({ children, ...props }: Record<string, unknown>) => (
      <span {...props}>{children as React.ReactNode}</span>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Reorder: {
    Group: ({
      children,
      ...props
    }: { children: React.ReactNode; [k: string]: unknown }) => (
      <ul {...props}>{children}</ul>
    ),
    Item: ({
      children,
      ...props
    }: { children: React.ReactNode; [k: string]: unknown }) => (
      <li {...props}>{children}</li>
    ),
  },
  useSpring: (initial: number) => ({
    set: vi.fn(),
    get: () => initial,
  }),
  useTransform: () => 1,
}));

// ---------------------------------------------------------------------------
// Store mock — default items matching DEFAULT_ITEMS in sidebarStore
// ---------------------------------------------------------------------------

const DEFAULT_MOCK_ITEMS = [
  { id: "home",     label: "Home",     icon: "Home",         route: "/",         type: "route" as const },
  { id: "trade",    label: "Trade",    icon: "TrendingUp",   route: "/trade",    type: "route" as const },
  { id: "invest",   label: "Invest",   icon: "Wallet",       route: "/invest",   type: "route" as const },
  { id: "learn",    label: "Learn",    icon: "BookOpen",     route: "/learn",    type: "route" as const },
  { id: "lab",      label: "Lab",      icon: "FlaskConical", route: "/lab",      type: "route" as const },
  { id: "automate", label: "Automate", icon: "Zap",          route: "/automate", type: "route" as const },
  { id: "sep-1",    label: "",         icon: "",             route: "",          type: "separator" as const },
  { id: "ai",       label: "AI Hub",   icon: "Bot",          route: "/ai",       type: "route" as const },
  { id: "ditto",    label: "Ditto",    icon: "Copy",         route: "/ditto",    type: "route" as const },
  { id: "admin",    label: "Admin",    icon: "Shield",       route: "/admin",    type: "route" as const },
  { id: "sep-2",    label: "",         icon: "",             route: "",          type: "separator" as const },
  { id: "settings", label: "Settings", icon: "Settings",     route: "/settings", type: "route" as const },
];

const mockSetMode = vi.fn();
const mockSetHovered = vi.fn();
const mockReorderItems = vi.fn();

// Default store state — icons mode, not hovered
let mockStoreState: {
  mode: "icons" | "expanded" | "auto-hide" | "hidden";
  items: typeof DEFAULT_MOCK_ITEMS;
  isHovered: boolean;
  setMode: typeof mockSetMode;
  setHovered: typeof mockSetHovered;
  reorderItems: typeof mockReorderItems;
} = {
  mode: "icons",
  items: DEFAULT_MOCK_ITEMS,
  isHovered: false,
  setMode: mockSetMode,
  setHovered: mockSetHovered,
  reorderItems: mockReorderItems,
};

vi.mock("@/stores/sidebarStore", () => ({
  useSidebarStore: vi.fn((selector?: (state: typeof mockStoreState) => unknown) => {
    if (selector) return selector(mockStoreState);
    return mockStoreState;
  }),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderSidebar(pathname = "/trade") {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      {/* DockSidebar is imported below after mocks are in place */}
      <SidebarUnderTest />
    </MemoryRouter>,
  );
}

// Lazy require to pick up mocks
let SidebarUnderTest: React.ComponentType;
import DockSidebar from "../DockSidebar";
SidebarUnderTest = DockSidebar;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DockSidebar", () => {
  beforeEach(() => {
    mockStoreState = {
      mode: "icons",
      items: DEFAULT_MOCK_ITEMS,
      isHovered: false,
      setMode: mockSetMode,
      setHovered: mockSetHovered,
      reorderItems: mockReorderItems,
    };
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // Renders all route items
  // -------------------------------------------------------------------------

  it("renders all route items from the default item list", () => {
    renderSidebar("/trade");

    const routeItems = DEFAULT_MOCK_ITEMS.filter((i) => i.type === "route");
    for (const item of routeItems) {
      expect(
        screen.getByRole("button", { name: item.label }),
        `Expected button for ${item.label}`,
      ).toBeInTheDocument();
    }
  });

  // -------------------------------------------------------------------------
  // Active route has indicator
  // -------------------------------------------------------------------------

  it("marks the active route item with aria-current=page", () => {
    renderSidebar("/trade");

    const tradeBtn = screen.getByRole("button", { name: "Trade" });
    expect(tradeBtn).toHaveAttribute("aria-current", "page");
  });

  it("does not mark inactive routes with aria-current", () => {
    renderSidebar("/trade");

    const investBtn = screen.getByRole("button", { name: "Invest" });
    expect(investBtn).not.toHaveAttribute("aria-current");
  });

  it("renders the active indicator element for the active route", () => {
    renderSidebar("/trade");

    // Active indicator is a span inside the active item's container
    const indicators = screen.getAllByTestId("active-indicator");
    expect(indicators.length).toBeGreaterThanOrEqual(1);
  });

  // -------------------------------------------------------------------------
  // Settings at bottom
  // -------------------------------------------------------------------------

  it("renders settings item in the settings section at the bottom", () => {
    renderSidebar("/trade");

    const settingsSection = screen.getByTestId("sidebar-settings-section");
    expect(settingsSection).toBeInTheDocument();

    const settingsBtn = screen.getByRole("button", { name: "Settings" });
    expect(settingsSection).toContainElement(settingsBtn);
  });

  it("marks settings as active when on /settings route", () => {
    renderSidebar("/settings");

    const settingsBtn = screen.getByRole("button", { name: "Settings" });
    expect(settingsBtn).toHaveAttribute("aria-current", "page");
  });

  // -------------------------------------------------------------------------
  // Separators between groups
  // -------------------------------------------------------------------------

  it("renders separator elements between item groups", () => {
    renderSidebar("/trade");

    const sep1 = screen.getByTestId("sidebar-separator-sep-1");
    const sep2 = screen.getByTestId("sidebar-separator-sep-2");

    expect(sep1).toBeInTheDocument();
    expect(sep2).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // hidden mode
  // -------------------------------------------------------------------------

  it("renders nothing in hidden mode", () => {
    mockStoreState = { ...mockStoreState, mode: "hidden" };
    const { container } = renderSidebar("/trade");
    expect(container.firstChild).toBeNull();
  });

  // -------------------------------------------------------------------------
  // auto-hide strip (collapsed)
  // -------------------------------------------------------------------------

  it("renders the auto-hide strip when mode is auto-hide and not hovered", () => {
    mockStoreState = { ...mockStoreState, mode: "auto-hide", isHovered: false };
    renderSidebar("/trade");

    expect(screen.getByTestId("auto-hide-strip")).toBeInTheDocument();
  });

  it("renders full sidebar when mode is auto-hide and hovered", () => {
    mockStoreState = { ...mockStoreState, mode: "auto-hide", isHovered: true };
    renderSidebar("/trade");

    // Should show route buttons, not the strip
    expect(screen.queryByTestId("auto-hide-strip")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trade" })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Navigation landmark
  // -------------------------------------------------------------------------

  it("wraps main items in a nav landmark with accessible label", () => {
    renderSidebar("/trade");

    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("has an aside landmark with accessible label", () => {
    renderSidebar("/trade");

    expect(screen.getByRole("complementary", { name: "Navigation sidebar" })).toBeInTheDocument();
  });
});
