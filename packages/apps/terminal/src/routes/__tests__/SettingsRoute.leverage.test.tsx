/**
 * SettingsRoute.leverage.test — FT-SET-004 route-level blank-pane lock.
 *
 * Selecting Settings `#leverage` must never leave the Leverage tab
 * highlighted over an empty tabpanel. Uses the real LeverageSection so a
 * `return null` cannot hide behind the SettingsRoute section stub.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

import type { BrokerCapabilities } from "@/types/api";

const mockNavigate = vi.fn();

const caps = vi.hoisted(() => ({
  data: undefined as BrokerCapabilities | undefined,
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
}));

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/components/layout/CinematicLayout", () => ({
  CinematicLayout: ({
    children,
    className,
  }: {
    children: React.ReactNode;
    className?: string;
  }) => <div className={className} data-testid="settings-layout">{children}</div>,
}));

vi.mock("@/tools/Settings/ProfileSection", () => ({
  ProfileSection: () => <div data-testid="profile-section">Profile</div>,
}));
vi.mock("@/routes/settings/TickerSettings", () => ({
  TickerSettings: () => <div data-testid="ticker-section">Ticker Bar</div>,
}));
vi.mock("@/tools/Settings/GeneralSection", () => ({
  GeneralSection: () => <div data-testid="general-section">General</div>,
}));
vi.mock("@/tools/Settings/AppearanceSection", () => ({
  AppearanceSection: () => <div data-testid="appearance-section">Appearance</div>,
}));
vi.mock("@/tools/Settings/ConnectionSection", () => ({
  ConnectionSection: () => <div data-testid="connection-section">Connection</div>,
}));
vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div data-testid="brokers-section">Brokers</div>,
}));
vi.mock("@/tools/Settings/TradingSection", () => ({
  TradingSection: () => <div data-testid="trading-section">Trading</div>,
}));
vi.mock("@/tools/Settings/RiskSection", () => ({
  RiskSection: () => <div data-testid="risk-section">Risk</div>,
}));
vi.mock("@/tools/Settings/KeyboardSection", () => ({
  KeyboardSection: () => <div data-testid="keyboard-section">Keyboard</div>,
}));
vi.mock("@/tools/Settings/LLMSection", () => ({
  LLMSection: () => <div data-testid="llm-section">LLM</div>,
}));
vi.mock("@/tools/Settings/TelegramSection", () => ({
  TelegramSection: () => <div data-testid="telegram-section">Telegram</div>,
}));
vi.mock("@/tools/Settings/DataSection", () => ({
  DataSection: () => <div data-testid="data-section">Data</div>,
}));
vi.mock("@/tools/Settings/AboutSection", () => ({
  AboutSection: () => <div data-testid="about-section">About</div>,
}));
vi.mock("@/tools/Settings/SupportSection", () => ({
  SupportSection: () => <div data-testid="support-section">Report Bug</div>,
}));
vi.mock("@/tools/Settings/PracticeSection", () => ({
  PracticeSection: () => <div data-testid="practice-section">Practice</div>,
}));
vi.mock("@/tools/Settings/SecuritySection", () => ({
  SecuritySection: () => <div data-testid="security-section">Security</div>,
}));
vi.mock("@/tools/Settings/MonitoringSection", () => ({
  MonitoringSection: () => <div data-testid="monitoring-section">Monitoring</div>,
}));
vi.mock("@/tools/Settings/SkillSection", () => ({
  SkillSection: () => <div data-testid="skill-section">Skill Level</div>,
}));
vi.mock("@/tools/Settings/PresetSection", () => ({
  PresetSection: () => <div data-testid="preset-section">Workspace Presets</div>,
}));
vi.mock("@/tools/Settings/UpdatesSection", () => ({
  UpdatesSection: () => <div data-testid="updates-section">Updates</div>,
}));

vi.mock("@/hooks/useSettingsState", () => ({
  useSettingsState: () => ({
    general: {},
    trading: {},
    risk: {},
    llm: {},
    llmSetupPending: false,
    llmSaveState: "saved",
    llmHydrationState: "ready",
    llmCredentialConfigured: true,
    llmCredentialLast4: "live",
    telegram: {},
    dataPaths: {},
    connection: {},
    restarting: false,
    updateGeneral: vi.fn(),
    updateTradingDefaults: vi.fn(),
    updateRiskLimits: vi.fn(),
    updateLLM: vi.fn(),
    updateLLMProvider: vi.fn(),
    removeLLMCredential: vi.fn(),
    retryLlmHydration: vi.fn(),
    updateTelegram: vi.fn(),
    updateDataPaths: vi.fn(),
    acceptConnection: vi.fn(),
    handleRestart: vi.fn(),
  }),
}));

vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({
    data: caps.data,
    isLoading: caps.isLoading,
    isError: caps.isError,
    refetch: caps.refetch,
  }),
}));

vi.mock("@/services/api", () => ({
  getLeverageSettings: vi.fn(),
}));

import SettingsRoute from "../SettingsRoute";

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<SettingsRoute />, { wrapper });
}

describe("Settings #leverage blank-pane lock (FT-SET-004)", () => {
  beforeEach(() => {
    caps.data = {
      broker_name: "Zerodha",
      broker_type: "equity",
      supported_exchanges: ["NSE"],
      features: {
        market_protection: false,
        leverage: false,
        bracket_orders: false,
        cover_orders: false,
      },
    };
    caps.isLoading = false;
    caps.isError = false;
    caps.refetch.mockReset().mockResolvedValue(undefined);
    window.history.replaceState(null, "", "/settings#leverage");
  });

  it("REGRESSION: #leverage keeps the tab highlighted and shows honest empty + Retry", () => {
    renderSettings();

    const tab = screen.getByRole("tab", { name: "Leverage" });
    expect(tab).toHaveAttribute("aria-selected", "true");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "settings-tabpanel-leverage");
    expect((panel.textContent ?? "").trim().length).toBeGreaterThan(0);
    expect(within(panel).getByText("Leverage settings unavailable.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
