/**
 * SettingsSections.test.tsx — Render tests for all Settings section components.
 *
 * Covers: ConnectionSection, AppearanceSection, SecuritySection,
 *         RiskSection, GeneralSection.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be before imports
// ---------------------------------------------------------------------------

// useTestConnection (ConnectionSection)
vi.mock("@/hooks/useTestConnection", () => ({
  useTestConnection: () => ({
    status: "idle",
    message: "",
    testConnection: vi.fn(),
  }),
}));

// themeStore (AppearanceSection) — called both with selector and destructured
const themeState = {
  glass: false,
  setGlass: vi.fn(),
  mode: "dark" as const,
  reduceMotion: false,
  setMode: vi.fn(),
  setReduceMotion: vi.fn(),
};
vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selectorOrUndefined?: unknown) => {
      if (typeof selectorOrUndefined === "function") {
        return (selectorOrUndefined as (s: typeof themeState) => unknown)(themeState);
      }
      // Destructured usage — return full state
      return themeState;
    },
    {
      getState: () => themeState,
    },
  ),
}));

// settingsStore (AppearanceSection)
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ density: "compact" }),
    {
      getState: () => ({ setDensity: vi.fn() }),
    },
  ),
}));

// ThemePicker / BackgroundPicker (AppearanceSection children)
vi.mock("@/components/theme/ThemePicker", () => ({
  ThemePicker: () => <div data-testid="theme-picker">ThemePicker</div>,
}));
vi.mock("@/components/theme/BackgroundPicker", () => ({
  BackgroundPicker: () => <div data-testid="bg-picker">BackgroundPicker</div>,
}));

// TanStack Query (SecuritySection + RiskSection)
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    isFetching: false,
  }),
  useMutation: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
  }),
}));

// ftApi services (SecuritySection + RiskSection)
vi.mock("@/services/ftApi", () => ({
  getSecurityStats: vi.fn(),
  getBannedIPs: vi.fn(),
  banIP: vi.fn(),
  unbanIP: vi.fn(),
  getSecuritySettings: vi.fn(),
  updateSecuritySettings: vi.fn(),
  updateSafetyConfig: vi.fn(),
}));

// riskSchema (RiskSection)
vi.mock("@/lib/schemas/riskSchema", () => ({
  RISK_HINTS: {
    maxPositionLots: "Max lots hint",
    mtmStoploss: "MTM SL hint",
    mtmTarget: "MTM target hint",
    maxOrdersPerMinute: "Max orders hint",
  },
}));

// shadcn Button and Badge — pass through children
vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: Record<string, unknown>) => (
    <button {...props}>{children as React.ReactNode}</button>
  ),
}));
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: Record<string, unknown>) => (
    <span {...props}>{children as React.ReactNode}</span>
  ),
}));

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import { ConnectionSection } from "../ConnectionSection";
import { AppearanceSection } from "../AppearanceSection";
import { SecuritySection } from "../SecuritySection";
import { RiskSection } from "../RiskSection";
import { GeneralSection } from "../GeneralSection";

// ---------------------------------------------------------------------------
// 1. ConnectionSection
// ---------------------------------------------------------------------------

describe("ConnectionSection", () => {
  it("renders with host input and section title", () => {
    render(
      <ConnectionSection
        settings={{ host: "http://127.0.0.1:5000", apiKey: "", wsPort: "8765" }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("API Connection")).toBeInTheDocument();
    expect(screen.getByLabelText("OpenAlgo host")).toBeInTheDocument();
    expect(screen.getByLabelText("WebSocket port")).toBeInTheDocument();
    expect(screen.getByText("Test Connection")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 2. AppearanceSection
// ---------------------------------------------------------------------------

describe("AppearanceSection", () => {
  it("renders with theme picker and colour mode buttons", () => {
    render(<AppearanceSection />);

    expect(screen.getByText("Appearance")).toBeInTheDocument();
    expect(screen.getByTestId("theme-picker")).toBeInTheDocument();
    expect(screen.getByLabelText("Light mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Dark mode")).toBeInTheDocument();
    expect(screen.getByLabelText("System mode")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 3. SecuritySection
// ---------------------------------------------------------------------------

describe("SecuritySection", () => {
  it("renders with security title and ban IP input", () => {
    render(<SecuritySection />);

    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.getByLabelText("IP address to ban")).toBeInTheDocument();
    expect(screen.getByText("Threat Statistics")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 4. RiskSection
// ---------------------------------------------------------------------------

describe("RiskSection", () => {
  it("renders with risk limit inputs", () => {
    render(
      <RiskSection
        settings={{
          maxPositionLots: "",
          mtmStoploss: "",
          mtmTarget: "",
          maxOrdersPerMinute: "",
        }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Risk Limits")).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum position size in lots")).toBeInTheDocument();
    expect(screen.getByLabelText("MTM stoploss in rupees")).toBeInTheDocument();
    expect(screen.getByLabelText("MTM profit target in rupees")).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum orders per minute")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 5. GeneralSection
// ---------------------------------------------------------------------------

describe("GeneralSection", () => {
  it("renders with font size segment control", () => {
    render(
      <GeneralSection
        settings={{ fontSize: "normal" }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Font Size")).toBeInTheDocument();
    expect(screen.getByText("Normal (13px)")).toBeInTheDocument();
  });
});
