/**
 * SettingsSections.test.tsx — Render tests for all Settings section components.
 *
 * Covers: ConnectionSection, AppearanceSection, SecuritySection,
 *         RiskSection, GeneralSection.
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

// ftApi services (SecuritySection + RiskSection + MonitoringSection)
vi.mock("@/services/ftApi", () => ({
  getAuthStatus: vi.fn(),
  setAuthPin: vi.fn(),
  getSecurityStats: vi.fn(),
  getBannedIPs: vi.fn(),
  banIP: vi.fn(),
  unbanIP: vi.fn(),
  getSecuritySettings: vi.fn(),
  updateSecuritySettings: vi.fn(),
  updateSafetyConfig: vi.fn(),
  getHealth: vi.fn(),
  getTrafficStats: vi.fn(),
  getLatencyStats: vi.fn(),
}));

// @/services/api (TelegramSection sendTelegram, LeverageSection getLeverageSettings)
vi.mock("@/services/api", () => ({
  sendTelegram: vi.fn(),
  getLeverageSettings: vi.fn(),
}));
vi.mock("@/services/ftApi.automation", () => ({ testWhatsAppAlert: vi.fn() }));

// Store/hook deps for the heavier sections.
vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({ data: undefined, isLoading: false, capabilities: null }),
}));
vi.mock("@/components/sandbox/SandboxControls", () => ({
  default: () => <div data-testid="sandbox-controls" />,
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: unknown) =>
    typeof selector === "function"
      ? (selector as (s: Record<string, unknown>) => unknown)({ mode: "explore" })
      : { mode: "explore" },
}));
vi.mock("@/stores/skillStore", () => {
  const state = {
    globalLevel: "intermediate",
    routeOverrides: {},
    helpPrefs: {},
    metrics: {
      trade: { ordersPlaced: 0, widgetsUsed: 0, daysActive: 0, lastActiveDate: "" },
      invest: { holdingsViewed: 0, sipsCreated: 0, goalsSet: 0 },
      learn: { lessonsCompleted: 0, quizzesPassed: 0, articlesRead: 0 },
      lab: { backtestsRun: 0, strategiesCreated: 0, optimizationsRun: 0 },
      automate: { flowsCreated: 0, alertsSet: 0, strategiesUploaded: 0 },
      ai: { queriesRun: 0, agentsDeployed: 0 },
    },
    getEffectiveLevel: () => "intermediate",
    setGlobalLevel: vi.fn(),
    setRouteOverride: vi.fn(),
    clearRouteOverride: vi.fn(),
    setHelpPref: vi.fn(),
    resetToDefaults: vi.fn(),
  };
  return {
    useSkillStore: (selector?: (s: typeof state) => unknown) =>
      typeof selector === "function" ? selector(state) : state,
  };
});

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
import { AboutSection } from "../AboutSection";
import { SecuritySection } from "../SecuritySection";
import { RiskSection } from "../RiskSection";
import { GeneralSection } from "../GeneralSection";
import { TradingSection } from "../TradingSection";
import { LLMSection } from "../LLMSection";
import { TelegramSection } from "../TelegramSection";
import { WhatsAppSection } from "../WhatsAppSection";
import { DataSection } from "../DataSection";
import { KeyboardSection } from "../KeyboardSection";
import { LeverageSection } from "../LeverageSection";
import { PracticeSection } from "../PracticeSection";
import { MonitoringSection } from "../MonitoringSection";
import { SkillSection } from "../SkillSection";
import { APP_VERSION_TAG } from "@/lib/appVersion";

// ---------------------------------------------------------------------------
// 1. ConnectionSection
// ---------------------------------------------------------------------------

describe("ConnectionSection", () => {
  function renderConnectionSection() {
    return render(
      <ConnectionSection
        settings={{ host: "http://127.0.0.1:5000", port: "5000", apiKey: "", wsPort: "8765" }}
        onChange={vi.fn()}
      />,
    );
  }

  it("renders with host input and section title", () => {
    renderConnectionSection();

    expect(screen.getByText("Broker Gateway")).toBeInTheDocument();
    expect(screen.getByLabelText("Broker gateway URL")).toBeInTheDocument();
    expect(screen.getByLabelText("REST port")).toBeInTheDocument();
    expect(screen.getByLabelText("WebSocket port")).toBeInTheDocument();
    expect(screen.getByText("Test Connection")).toBeInTheDocument();
  });

  it("suggests OpenAlgo's port 5000 in the gateway URL placeholder, never FlintTrade's 5100", () => {
    // 5100 is FlintTrade's own backend — pointing the OpenAlgo bridge at it
    // guarantees a broken connection (item 1).
    renderConnectionSection();

    expect(screen.getByLabelText("Broker gateway URL")).toHaveAttribute(
      "placeholder",
      "http://127.0.0.1:5000",
    );
  });

  it("offers a setup wizard entry point that navigates to /setup", () => {
    renderConnectionSection();

    const listener = vi.fn();
    window.addEventListener("flinttrade:navigate", listener);
    try {
      fireEvent.click(screen.getByRole("button", { name: /open setup wizard/i }));
      expect(listener).toHaveBeenCalledTimes(1);
      expect((listener.mock.calls[0][0] as CustomEvent<string>).detail).toBe("/setup");
    } finally {
      window.removeEventListener("flinttrade:navigate", listener);
    }
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
    // Quick-unlock PIN block (full behaviour covered in SecuritySection.test.tsx).
    expect(screen.getByText("Quick-unlock PIN")).toBeInTheDocument();
    expect(screen.getByLabelText("New 6-digit PIN")).toBeInTheDocument();
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
    // Daily-loss thresholds are percentages (L4), not rupee MTM — the backend
    // safety/config endpoint only enforces pnl_pause_pct / pnl_kill_pct.
    expect(screen.getByLabelText("Daily loss kill threshold in percent")).toBeInTheDocument();
    expect(screen.getByLabelText("Daily loss pause threshold in percent")).toBeInTheDocument();
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

// ---------------------------------------------------------------------------
// 6. AboutSection
// ---------------------------------------------------------------------------

describe("AboutSection", () => {
  it("renders the central app version", () => {
    render(<AboutSection />);

    expect(screen.getByText(`Version ${APP_VERSION_TAG}`)).toBeInTheDocument();
    expect(screen.getByText(APP_VERSION_TAG)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Smoke-render crash guard — the other prop-taking sections.
//
// SettingsRoute mocks every section, so a render-time crash in one of these is
// otherwise uncaught. These prove each renders with a minimal settings object.
// ---------------------------------------------------------------------------

describe("Section smoke renders (crash guard)", () => {
  it("TradingSection renders", () => {
    const { container } = render(
      <TradingSection
        settings={{ exchange: "NSE", product: "MIS", orderType: "MARKET", quantity: "1" } as unknown as React.ComponentProps<typeof TradingSection>["settings"]}
        onChange={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("LLMSection renders", () => {
    const { container } = render(
      <LLMSection
        settings={{ provider: "openai", host: "", apiKey: "", model: "" } as unknown as React.ComponentProps<typeof LLMSection>["settings"]}
        onChange={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("TelegramSection renders", () => {
    const { container } = render(
      <TelegramSection
        settings={{ enabled: false, botToken: "", chatId: "" } as unknown as React.ComponentProps<typeof TelegramSection>["settings"]}
        onChangeField={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("WhatsAppSection renders", () => {
    const { container } = render(
      <WhatsAppSection
        settings={{ enabled: false, phoneE164: "", adminUrl: "" } as unknown as React.ComponentProps<typeof WhatsAppSection>["settings"]}
        onChangeField={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("DataSection renders", () => {
    const { container } = render(
      <DataSection
        settings={{ fastStoragePath: "/data", archiveStoragePath: "/archive" } as unknown as React.ComponentProps<typeof DataSection>["settings"]}
        onChange={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  // Store/hook-heavy sections (no props) — rendered against their mocked deps.
  it("KeyboardSection renders", () => {
    const { container } = render(<KeyboardSection />);
    expect(container.firstChild).toBeTruthy();
  });

  it("LeverageSection renders without throwing", () => {
    // Renders a null/empty state under the mocked (data-less) query — the guard
    // is that it does not THROW during render.
    expect(() => render(<LeverageSection />)).not.toThrow();
  });

  it("PracticeSection renders", () => {
    const { container } = render(<PracticeSection />);
    expect(container.firstChild).toBeTruthy();
  });

  it("MonitoringSection renders", () => {
    const { container } = render(<MonitoringSection />);
    expect(container.firstChild).toBeTruthy();
  });

  it("SkillSection renders", () => {
    const { container } = render(<SkillSection />);
    expect(container.firstChild).toBeTruthy();
  });
});
